"""Per-call feedback and per-agent coaching reports.

ANALYSIS_BACKEND picks who writes them:
- "claude" (default): Claude, via CLAUDE_BACKEND.
- "cursor": the Cursor SDK, using CURSOR_API_KEY.
- "auto": Claude first; Cursor if the Claude CLI is missing or the session limit is hit.

CLAUDE_BACKEND, when Claude is used:
- "subscription" (default): runs the local `claude` CLI (Claude Code) in print mode, so it uses the
  Claude Pro/Max subscription you're logged into. No API key needed.
- "api": calls the Anthropic API with ANTHROPIC_API_KEY (pay per token).
"""
import codecs
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Literal

from pydantic import BaseModel, Field

from .config import settings


class Mistake(BaseModel):
    quote: str = Field(description="What the agent actually said (original language), short")
    problem: str = Field(description="Why it hurt the sale")
    better_version: str = Field(description="Exact sentence the agent should have said instead, in the call's language")


class Objection(BaseModel):
    objection: str = Field(description="The customer's objection or hesitation")
    how_handled: str
    better_answer: str = Field(description="A stronger reply, in the call's language")


class Scores(BaseModel):
    opening: int = Field(description="1-10: introduction, permission, hook")
    discovery: int = Field(description="1-10: questions about needs, situation, decision maker, budget")
    pitch: int = Field(description="1-10: value tied to the customer's needs, clarity")
    objection_handling: int = Field(description="1-10")
    closing: int = Field(description="1-10: asked for a clear next step / commitment")
    tone_and_listening: int = Field(description="1-10: confidence, empathy, talk/listen balance")


class CallAnalysis(BaseModel):
    is_sales_conversation: bool = Field(description="False for voicemail, wrong number, internal call, pure support, no answer")
    call_category: Literal["prospecting", "follow_up", "inbound_lead", "negotiation", "support", "other"]
    summary: str = Field(description="2-4 sentences: who, what was discussed, how it ended")
    outcome: Literal["sale", "appointment_or_next_step", "callback_requested", "not_interested", "no_decision", "not_applicable"]
    customer_interest: Literal["high", "medium", "low", "unknown"]
    overall_score: int = Field(description="1-10 overall quality of the agent's sales performance")
    scores: Scores
    strengths: list[str]
    mistakes: list[Mistake]
    objections: list[Objection]
    missed_opportunities: list[str]
    top_coaching_tip: str = Field(description="The single most impactful thing to change next time")
    follow_up_action: str = Field(description="What the agent should do now with this customer")


def _business_context() -> str:
    path = settings.business_context_path
    return path.read_text(encoding="utf-8") if path.exists() else "(no business context provided)"


def _system_prompt() -> str:
    return f"""You are an expert B2B/B2C sales coach working for a Tunisian company. You review recorded phone calls
between our sales agents and customers and give honest, specific, actionable feedback that helps close more deals.

The calls are usually in Tunisian Arabic (Derja), French, or a mix. Transcripts come from automatic speech-to-text,
so expect errors, misheard words and imperfect speaker labels; infer meaning from context and never punish the agent
for transcription noise. Speaker labels (channel_L/channel_R, speaker_0/speaker_1) are not fixed, and some transcripts
have no labels at all: work out who is our agent and who is the customer from context.

Write all feedback in {settings.feedback_language}. Keep quotes and "better_version"/"better_answer" sentences in the
language actually spoken in the call (Derja/French), so the agent can reuse them word for word.

Be concrete: cite what was said, explain why it helps or hurts, and propose exact wording. Do not invent facts that are
not in the transcript. Score fairly: 5 is average, 8+ is genuinely strong.

<business_context>
{_business_context()}
</business_context>"""


def _direction(call) -> str:
    return {
        "OUT": "Outbound call: our agent called the customer.",
        "IN": "Inbound call: the customer called us directly.",
        "QUEUE": "Inbound call routed through the call queue: the customer called us.",
    }.get(call["type"], f"Call type: {call['type']}")


def _ask_claude_cli(system: str, prompt: str, schema: dict | None = None):
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("`claude` CLI not found. Install Claude Code and run `claude` once to log in.")
    with tempfile.TemporaryDirectory() as workdir:
        system_file = f"{workdir}/system.md"
        with open(system_file, "w", encoding="utf-8") as fh:
            fh.write(system)
        cmd = [
            exe, "-p",
            "--output-format", "json",
            "--model", settings.claude_model,
            "--effort", "high",
            "--system-prompt-file", system_file,
            # Plain text-in/text-out: no tools, MCP servers, skills or project settings.
            "--tools", "",
            "--strict-mcp-config",
            "--setting-sources", "",
            "--disable-slash-commands",
            "--no-session-persistence",
        ]
        if schema:
            cmd += ["--json-schema", json.dumps(schema)]
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                              cwd=workdir, timeout=1800)
    try:
        result = json.loads(proc.stdout)
    except ValueError:
        raise RuntimeError(f"claude CLI failed (exit {proc.returncode}): {(proc.stderr or proc.stdout)[-1000:]}")
    if result.get("is_error"):
        raise RuntimeError(f"claude CLI error: {result.get('result') or result.get('subtype')}")
    if schema:
        if result.get("structured_output") is None:
            raise RuntimeError(f"No structured output returned: {str(result.get('result'))[:500]}")
        return result["structured_output"]
    return result.get("result", "")


def _ask_claude_api(system: str, prompt: str, schema: dict | None = None):
    import anthropic

    client = anthropic.Anthropic(max_retries=4)
    request = dict(
        model=settings.claude_model,
        max_tokens=64000,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}],
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        # On a safety-classifier decline the API re-runs the request on a fallback model automatically.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if schema:
        request["output_config"]["format"] = {"type": "json_schema", "schema": schema}
    with client.beta.messages.stream(**request) as stream:
        message = stream.get_final_message()
    if message.stop_reason == "refusal":
        raise RuntimeError(f"Claude declined: {message.stop_details}")
    text = "".join(block.text for block in message.content if block.type == "text")
    return json.loads(text) if schema else text


def ask_claude(system: str, prompt: str, schema: dict | None = None):
    if settings.claude_backend == "api":
        return _ask_claude_api(system, prompt, schema)
    if settings.claude_backend == "subscription":
        return _ask_claude_cli(system, prompt, schema)
    raise RuntimeError(f"Unknown CLAUDE_BACKEND={settings.claude_backend!r}; use subscription or api")


_cursor_lock = threading.Lock()
_LIMIT_MARKERS = (
    "hit your limit",
    "rate limit",
    "rate_limit",
    "usage limit",
    "session limit",
    "too many requests",
)


def _claude_unavailable(exc: BaseException) -> bool:
    text = str(exc).lower()
    if "claude" in text and "not found" in text:
        return True
    return any(marker in text for marker in _LIMIT_MARKERS)


def _json_from_text(text: str):
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise RuntimeError(f"Cursor did not return JSON: {text[:500]}") from None


def _install_windows_bridge_fix() -> None:
    """cursor-sdk reads the bridge's stderr with select(). Windows select() only accepts sockets, so
    discovery dies with WinError 10038. Poll the pipe instead."""
    if os.name != "nt":
        return
    import cursor_sdk._bridge as bridge

    if getattr(bridge, "_call_analyzer_pipe_fix", False):
        return

    def _read_discovery(process: subprocess.Popen[str], timeout: float):
        if process.stderr is None:
            raise bridge.CursorSDKError("Bridge process stderr is unavailable")
        stderr_fd = process.stderr.fileno()
        was_blocking = os.get_blocking(stderr_fd)
        os.set_blocking(stderr_fd, False)
        try:
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            deadline = time.monotonic() + timeout
            stderr_lines: list[str] = []
            pending = ""

            def drain_available():
                nonlocal pending
                while True:
                    try:
                        chunk = os.read(stderr_fd, 8192)
                    except BlockingIOError:
                        return None
                    if not chunk:
                        final_text = decoder.decode(b"", final=True)
                        if final_text:
                            pending += final_text
                        if pending:
                            line = pending
                            pending = ""
                            stderr_lines.append(line)
                            return bridge.parse_discovery_line(line)
                        return None
                    pending += decoder.decode(chunk)
                    while "\n" in pending:
                        line, pending = pending.split("\n", 1)
                        line += "\n"
                        stderr_lines.append(line)
                        discovery = bridge.parse_discovery_line(line)
                        if discovery is not None:
                            return discovery

            while time.monotonic() < deadline:
                discovery = drain_available()
                if discovery is not None:
                    return discovery
                exit_code = process.poll()
                if exit_code is not None:
                    discovery = drain_available()
                    if discovery is not None:
                        return discovery
                    raise bridge.CursorSDKError(
                        f"Bridge exited before discovery with status {exit_code}: "
                        + "".join(stderr_lines)
                        + pending
                    )
                time.sleep(0.05)
            raise bridge.CursorSDKError("Timed out waiting for bridge discovery")
        finally:
            os.set_blocking(stderr_fd, was_blocking)

    bridge._read_discovery = _read_discovery
    bridge._call_analyzer_pipe_fix = True


def _ask_cursor(system: str, prompt: str, schema: dict | None = None):
    """One-shot Cursor agent. No tools, and it runs in an empty folder so it cannot edit this project."""
    if not settings.cursor_api_key:
        raise RuntimeError("CURSOR_API_KEY is empty. Set it in Settings.")
    try:
        from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions
    except ImportError as exc:
        raise RuntimeError("cursor-sdk is not installed. Run: pip install cursor-sdk") from exc
    _install_windows_bridge_fix()

    body = f"{system}\n\n{prompt}\n\nDo not use tools or edit files."
    if schema:
        body += (
            "\nReply with one JSON object only, matching this schema. No markdown fences, no commentary.\n"
            + json.dumps(schema)
        )
    with tempfile.TemporaryDirectory() as workdir:
        with _cursor_lock:
            try:
                result = Agent.prompt(
                    body,
                    AgentOptions(
                        api_key=settings.cursor_api_key,
                        model=settings.cursor_model or "composer-2.5",
                        tools=[],
                        local=LocalAgentOptions(cwd=workdir),
                    ),
                )
            except CursorAgentError as exc:
                raise RuntimeError(f"Cursor failed to start: {exc}") from exc
    if result.status != "finished":
        raise RuntimeError(f"Cursor run {result.status}: {(result.result or '')[:500]}")
    text = (result.result or "").strip()
    return _json_from_text(text) if schema else text


def _claude_label() -> str:
    via = "Claude Code subscription" if settings.claude_backend == "subscription" else "API"
    return f"Claude {settings.claude_model} ({via})"


def _cursor_label() -> str:
    return f"Cursor {settings.cursor_model or 'composer-2.5'}"


def ask_model_labeled(system: str, prompt: str, schema: dict | None = None):
    """Like ask_model, but also returns which system answered (relevant when "auto" falls back)."""
    backend = settings.analysis_backend
    if backend == "cursor":
        return _ask_cursor(system, prompt, schema), _cursor_label()
    if backend == "claude":
        return ask_claude(system, prompt, schema), _claude_label()
    if backend == "auto":
        try:
            return ask_claude(system, prompt, schema), _claude_label()
        except RuntimeError as exc:
            if not _claude_unavailable(exc):
                raise
            print(f"Claude unavailable ({exc}); using Cursor.", file=sys.stderr)
            return _ask_cursor(system, prompt, schema), _cursor_label()
    raise RuntimeError(f"Unknown ANALYSIS_BACKEND={backend!r}; use claude, cursor or auto")


def ask_model(system: str, prompt: str, schema: dict | None = None):
    return ask_model_labeled(system, prompt, schema)[0]


def _strict_schema(model: type[BaseModel]) -> dict:
    """Pydantic schema with additionalProperties=false on every object (required by structured outputs)."""
    schema = model.model_json_schema()

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["additionalProperties"] = False
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return schema


def analyze_call(call) -> tuple[CallAnalysis, str]:
    """Returns the analysis and a label of the model that wrote it."""
    prompt = f"""Analyze this call.

<call_metadata>
Agent extension: {call['agent']}
Customer number: {call['customer']}
Date: {call['date_call']}
Duration: {call['duration']} seconds
{_direction(call)}
</call_metadata>

<transcript>
{call['transcript']}
</transcript>"""
    data, by = ask_model_labeled(_system_prompt(), prompt, schema=_strict_schema(CallAnalysis))
    return CallAnalysis.model_validate(data), by


def coaching_report(title: str, calls: list) -> str:
    """Turn many per-call analyses into one coaching report (markdown)."""
    items = []
    for call in calls:
        analysis = json.loads(call["analysis"])
        items.append({
            "call_id": call["id"], "date": call["date_call"], "agent": call["agent"], "type": call["type"],
            "duration_s": call["duration"], **analysis,
        })
    prompt = f"""Below are the analyses of {len(items)} recorded calls for: {title}.

<call_analyses>
{json.dumps(items, ensure_ascii=False, indent=1)}
</call_analyses>

Write a coaching report in markdown for the sales manager. Include:
1. **Snapshot**: number of calls, outcomes breakdown, average scores per dimension.
2. **Recurring patterns**: what keeps working and what keeps failing, with call ids/dates as evidence.
3. **Top 3 priorities** to fix, ranked by impact on closing, each with a concrete drill or rule.
4. **Improved pitch script**: a rewritten opening, 4-6 discovery questions, value pitch, and close, in the language
   the calls are actually held in (Derja/French), ready to use.
5. **Objection playbook**: the most frequent objections heard and the best answer for each.
6. **Best and worst call** to listen to (call ids) and why.
7. **Hot leads to follow up**: customers with high/medium interest and the next action.
If several agents are present, add a short per-agent comparison.

Output only the report in markdown."""
    return ask_model(_system_prompt(), prompt)
