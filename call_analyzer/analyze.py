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

from . import voice as voice_mod
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


class VoiceTone(BaseModel):
    """How the AGENT sounds, judged on the measurements taken from the audio (see voice.py), not on the words."""
    score: int = Field(description="1-10: the agent's voice tone: calm, warm, confident, steady, lively intonation")
    agent_tone: Literal["warm_confident", "calm_professional", "neutral_flat", "hesitant_nervous",
                        "tense_impatient", "irritated_angry"]
    customer_tone: Literal["positive", "neutral", "anxious_confused", "frustrated", "angry", "unknown"]
    evidence: str = Field(description="1-3 sentences: which stretches of the call (mm:ss) and which measurements "
                                      "(emotion, loudness, pitch variation, pauses) support the score")
    coaching_tip: str = Field(description="One concrete change in HOW the agent sounds (pace, energy, smile, calm)")
    confidence: Literal["high", "medium", "low"] = Field(
        description="low when you could not tell whose voice the windows carry or the classifier looks unreliable here")


class ServiceMistake(BaseModel):
    quote: str = Field(description="What the agent actually said (original language), short")
    problem: str = Field(description="Why it hurt the customer's experience or the resolution")
    better_version: str = Field(description="Exact sentence the agent should have said instead, in the call's language")


class ServiceScores(BaseModel):
    greeting: int = Field(description="1-10: greeting, identifying the customer and their shop/account")
    understanding: int = Field(description="1-10: listened and asked what was needed to understand the problem")
    solution: int = Field(description="1-10: correct and complete answer or fix, following our procedures")
    clarity: int = Field(description="1-10: explained simply and step by step, checked the customer understood")
    empathy_and_tone: int = Field(description="1-10: patience, politeness, calm with a frustrated customer")
    resolution: int = Field(description="1-10: problem solved or properly escalated, clear next step")


class ServiceAnalysis(BaseModel):
    """Analysis of a customer service / technical support call (judged on service, not on selling)."""
    # Set by analyze_call from the classification, not asked from the model (see _strict_schema).
    call_kind: Literal["service"] = "service"
    issue_category: Literal["technical_problem", "balance_or_deposit", "pricing_or_tiers", "hardware_printer_pda",
                            "account_or_access", "how_to_use", "complaint", "other"]
    summary: str = Field(description="2-4 sentences: who, what the problem was, how it ended")
    resolution_status: Literal["resolved", "escalated", "pending_customer", "unresolved"]
    customer_sentiment: Literal["satisfied", "neutral", "frustrated", "unknown"]
    overall_score: int = Field(description="1-10 overall quality of the agent's customer service")
    scores: ServiceScores
    strengths: list[str]
    mistakes: list[ServiceMistake]
    missed_opportunities: list[str] = Field(
        description="Chances to prevent the next problem, teach the customer something or keep them active")
    top_coaching_tip: str = Field(description="The single most impactful thing to change next time")
    follow_up_action: str = Field(description="What the agent or the company should still do for this customer")
    # Only when the recording was measured; analyses from before voice analysis have none.
    voice: VoiceTone | None = None


class CallAnalysis(BaseModel):
    # Set by analyze_call from the classification, not asked from the model (see _strict_schema).
    call_kind: Literal["sales"] = "sales"
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
    voice: VoiceTone | None = None


class OtherAnalysis(BaseModel):
    """A call that is neither sales nor service: voicemail, no answer, wrong number, internal call. There is nothing
    to judge, so it is never rated: no score, in no report and in no average score."""
    call_kind: Literal["other"] = "other"
    is_sales_conversation: Literal[False] = False
    summary: str = Field(description="What the call was, e.g. voicemail, no answer")


def _business_context() -> str:
    path = settings.business_context_path
    return path.read_text(encoding="utf-8") if path.exists() else "(no business context provided)"


CALL_KINDS = ("sales", "service", "other")

# business.md is split on its "## " headings. A heading that mentions service/support is only given when judging
# service calls; one about the sales process only when judging sales calls; the rest (what we sell, the team...)
# goes to both. The first match wins, so "Customer service: ideal call" is a service section.
_SERVICE_HEADING = re.compile(r"service|support", re.I)
_SALES_HEADING = re.compile(r"ideal call|who we call|sales|objection|pitch|competitor", re.I)


def business_for(text: str, kind: str) -> str:
    """The parts of business.md that apply to this kind of call: "sales" (and "other"), "service", or "shared"
    for what applies to every call."""
    parts, section = [], []
    for line in text.splitlines(keepends=True):
        if line.startswith("## ") and section:
            parts.append(section)
            section = []
        section.append(line)
    parts.append(section)
    keep = []
    for lines in parts:
        heading = lines[0] if lines and lines[0].startswith("## ") else ""
        if _SERVICE_HEADING.search(heading):
            wanted = kind == "service"
        elif _SALES_HEADING.search(heading):
            wanted = kind in ("sales", "other")
        else:
            wanted = True
        if wanted:
            keep.extend(lines)
    return "".join(keep)


_LANGUAGE_RULES = """The calls are usually in Tunisian Arabic (Derja), French, or a mix. Transcripts come from automatic speech-to-text,
so expect errors, misheard words and imperfect speaker labels; infer meaning from context and never punish the agent
for transcription noise. Speaker labels (channel_L/channel_R, speaker_0/speaker_1) are not fixed, and some transcripts
have no labels at all: work out who is our agent and who is the customer from context."""


_VOICE_RULES = """You also receive <voice_analysis>: measurements taken from the audio itself by a speech-emotion
classifier and a loudness/pitch analysis. Judge how the AGENT sounds, which the transcript cannot show.
- The recording is mono, so the windows are not labelled by speaker. Use the transcript timestamps and what is said to
  decide whose voice a window carries, and ignore the windows you cannot attribute. When the tracks are
  channel_L/channel_R, work out which channel is the agent from the transcript.
- The classifier was trained on English acted speech and the audio is 8 kHz phone speech in Derja/French, so one
  window proves little: trust patterns over several windows. Ringing, hold music and the IVR can sound like emotion at
  the start of a call.
- A customer who sounds angry or upset is not the agent's fault. What counts is how the agent sounds, and whether the
  agent stays calm and warm while the customer is upset (that deserves a high score).
- Voice score: 5 is average. 8+ is calm, warm, confident, steady, with lively intonation. 4 or less is a flat
  monotone, a rushed or tense voice, impatience, a tired or sad voice, or sounding irritated or angry. Several windows
  where the agent sounds angry weigh heavily; very long pauses (dead air) cost points.
- Fill "voice" from this evidence, and let it also inform the tone/empathy score of the score card (which also
  uses the words). If the measurements and the transcript disagree, say so in the evidence."""


def _system_prompt(cfg=None, business: str | None = None, kind: str = "sales", voice: bool = False) -> str:
    """`business` is the text of business.md; an agent receives it from the server instead of reading a file.
    `kind` picks the coach: sales calls are judged on selling, service calls on helping the customer. `voice`: the
    recording was measured (see voice.py), so the analysis also scores the agent's voice."""
    cfg = cfg or settings
    context = business_for(business if business is not None else _business_context(), kind)
    if kind == "service":
        role = """You are an expert customer service and technical support coach working for a Tunisian company. You
review recorded phone calls between our support agents and customers (shops that already use our product) and give
honest, specific, actionable feedback that helps solve problems faster and leave customers satisfied. These calls are
judged on service quality, never on selling: do not penalize the agent for not pitching or closing."""
        scoring = "Score fairly: 5 is average, 8+ is genuinely strong. A problem that was solved clearly and politely deserves a high score."
    else:
        role = """You are an expert B2B/B2C sales coach working for a Tunisian company. You review recorded phone calls
between our sales agents and customers and give honest, specific, actionable feedback that helps close more deals."""
        scoring = "Score fairly: 5 is average, 8+ is genuinely strong."
    return f"""{role}

{_LANGUAGE_RULES}

Write all feedback in {cfg.feedback_language}. Keep quotes and "better_version"/"better_answer" sentences in the
language actually spoken in the call (Derja/French), so the agent can reuse them word for word.

Be concrete: cite what was said, explain why it helps or hurts, and propose exact wording. Do not invent facts that are
not in the transcript. {scoring}
{_VOICE_RULES if voice else ""}
<business_context>
{context}
</business_context>"""


def _direction(call) -> str:
    return {
        "OUT": "Outbound call: our agent called the customer.",
        "IN": "Inbound call: the customer called us directly.",
        "QUEUE": "Inbound call routed through the call queue: the customer called us.",
    }.get(call["type"], f"Call type: {call['type']}")


def _ask_claude_cli(system: str, prompt: str, schema: dict | None = None, cfg=None):
    cfg = cfg or settings
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
            "--model", cfg.claude_model,
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


def _ask_claude_api(system: str, prompt: str, schema: dict | None = None, cfg=None):
    import anthropic

    cfg = cfg or settings

    client = anthropic.Anthropic(max_retries=4)
    request = dict(
        model=cfg.claude_model,
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


def ask_claude(system: str, prompt: str, schema: dict | None = None, cfg=None):
    cfg = cfg or settings
    if cfg.claude_backend == "api":
        return _ask_claude_api(system, prompt, schema, cfg)
    if cfg.claude_backend == "subscription":
        return _ask_claude_cli(system, prompt, schema, cfg)
    raise RuntimeError(f"Unknown CLAUDE_BACKEND={cfg.claude_backend!r}; use subscription or api")


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


def _ask_cursor(system: str, prompt: str, schema: dict | None = None, cfg=None):
    """One-shot Cursor agent. No tools, and it runs in an empty folder so it cannot edit this project."""
    cfg = cfg or settings
    if not cfg.cursor_api_key:
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
                        api_key=cfg.cursor_api_key,
                        model=cfg.cursor_model or "composer-2.5",
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


def _claude_label(cfg=None) -> str:
    cfg = cfg or settings
    via = "Claude Code subscription" if cfg.claude_backend == "subscription" else "API"
    return f"Claude {cfg.claude_model} ({via})"


def _cursor_label(cfg=None) -> str:
    return f"Cursor {(cfg or settings).cursor_model or 'composer-2.5'}"


def ask_model_labeled(system: str, prompt: str, schema: dict | None = None, cfg=None):
    """Like ask_model, but also returns which system answered (relevant when "auto" falls back)."""
    cfg = cfg or settings
    backend = cfg.analysis_backend
    if backend == "cursor":
        return _ask_cursor(system, prompt, schema, cfg), _cursor_label(cfg)
    if backend == "claude":
        return ask_claude(system, prompt, schema, cfg), _claude_label(cfg)
    if backend == "auto":
        try:
            return ask_claude(system, prompt, schema, cfg), _claude_label(cfg)
        except RuntimeError as exc:
            if not _claude_unavailable(exc):
                raise
            print(f"Claude unavailable ({exc}); using Cursor.", file=sys.stderr)
            return _ask_cursor(system, prompt, schema, cfg), _cursor_label(cfg)
    raise RuntimeError(f"Unknown ANALYSIS_BACKEND={backend!r}; use claude, cursor or auto")


def ask_model(system: str, prompt: str, schema: dict | None = None, cfg=None):
    return ask_model_labeled(system, prompt, schema, cfg)[0]


def _strict_schema(model: type[BaseModel], voice: bool = False) -> dict:
    """Pydantic schema with additionalProperties=false on every object (required by structured outputs). The voice
    tone is asked for only when the recording was measured (`voice`), and then it is required."""
    schema = model.model_json_schema()
    schema.get("properties", {}).pop("call_kind", None)  # decided by classify_call, not by the analysis model
    schema["required"] = [name for name in schema.get("required", []) if name != "call_kind"]
    if voice:
        schema["properties"]["voice"] = {"$ref": "#/$defs/VoiceTone"}
        schema["required"].append("voice")
    else:
        schema["properties"].pop("voice", None)
        schema.get("$defs", {}).pop("VoiceTone", None)

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


def _classify_system(cfg=None, business: str | None = None) -> str:
    context = business_for(business if business is not None else _business_context(), "shared")
    return f"""You sort recorded phone calls of a Tunisian company into three kinds, from the transcript.

- sales: our agent is trying to sell: prospecting a shop, following up an offer, presenting prices or tiers,
  negotiating, or answering a prospect who wants to know if they should sign up or deposit money.
- service: a customer who already uses our product calls for help, or our agent calls them about a problem: a
  technical issue, a balance or deposit that did not arrive, how to use the app/PDA/printer, an account or access
  problem, a complaint. The aim is to solve something, not to sell. A few words about selling at the end of a
  support call does not make it a sales call.
- other: the customer never picked up: voicemail or answering machine (our agent leaves a message, or only the
  operator's recorded message is heard, e.g. the number is unreachable or switched off), ringing with no answer.
  Also a wrong number, an internal call, or a call too short or too garbled to tell. These calls are not rated.

When a call mixes both, pick the kind that took most of the conversation.

{_LANGUAGE_RULES}

<business_context>
{context}
</business_context>"""


def classify_call(call, cfg=None, business: str | None = None) -> str:
    """"sales", "service" or "other": decides which coach and which score card judge the call."""
    return _classify(call, cfg, business)[0]


def _classify(call, cfg=None, business: str | None = None) -> tuple[str, str, str]:
    """The kind of call, the model's one-sentence reason, and a label of the model that decided."""
    prompt = f"""Which kind of call is this?

<call_metadata>
{_direction(call)}
Duration: {call['duration']} seconds
</call_metadata>

<transcript>
{(call['transcript'] or '')[:6000]}
</transcript>"""
    schema = {"type": "object", "additionalProperties": False, "required": ["reason", "call_kind"], "properties": {
        "reason": {"type": "string", "description": "One short sentence: what the call is about"},
        "call_kind": {"type": "string", "enum": list(CALL_KINDS)}}}
    data, by = ask_model_labeled(_classify_system(cfg, business), prompt, schema=schema, cfg=cfg)
    kind = data.get("call_kind") if isinstance(data, dict) else None
    if kind not in CALL_KINDS:
        raise RuntimeError(f"The model did not say what kind of call this is: {str(data)[:300]}")
    return kind, str(data.get("reason") or ""), by


ANALYSIS_MODELS = {"sales": CallAnalysis, "service": ServiceAnalysis, "other": OtherAnalysis}


def parse_analysis(data) -> CallAnalysis | ServiceAnalysis | OtherAnalysis:
    """Validate a stored or agent-sent analysis with the model of its kind. An "other" call scored by an older agent
    loses its score card here, since those calls are not rated."""
    model = ANALYSIS_MODELS[kind_of(data)] if isinstance(data, dict) else CallAnalysis
    return model.model_validate(data)


def kind_of(analysis: dict) -> str:
    """The kind of an analysis; those written before kinds existed count as sales if they were sales conversations."""
    return analysis.get("call_kind") or ("sales" if analysis.get("is_sales_conversation") else "other")


# kind_of in SQL, over the calls.analysis column.
KIND_SQL = ("COALESCE(json_extract(analysis, '$.call_kind'), "
            "CASE WHEN json_extract(analysis, '$.is_sales_conversation') THEN 'sales' ELSE 'other' END)")
# The AI score of a call, NULL for "other" calls: voicemails and the like are not rated, even when they were analyzed
# (and given a score) before they stopped being rated.
SCORE_SQL = f"CASE WHEN {KIND_SQL} != 'other' THEN json_extract(analysis, '$.overall_score') END"


def analyze_call(call, cfg=None, business: str | None = None) -> tuple[CallAnalysis | ServiceAnalysis | OtherAnalysis, str]:
    """Returns the analysis and a label of the model that wrote it. `cfg` and `business` (the text of business.md)
    are given by an agent, which uses the server's settings merged with its own.

    The call is classified first: sales calls are judged as selling, service calls as customer service, each with
    its own score card and the parts of business.md that apply to it. When the recording was measured (call["voice"],
    see voice.py) the analysis also scores how the agent sounds. Other calls (voicemail, no answer...) are not rated:
    they only keep the classifier's reason."""
    kind, reason, by = _classify(call, cfg, business)
    if kind == "other":
        return OtherAnalysis(summary=reason or "Not a sales or service call"), by
    model = ServiceAnalysis if kind == "service" else CallAnalysis
    measured = voice_mod.of_call(call)
    voice_block = f"\n\n<voice_analysis>\n{voice_mod.describe(measured)}\n</voice_analysis>" if measured else ""
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
</transcript>{voice_block}"""
    data, by = ask_model_labeled(_system_prompt(cfg, business, kind, voice=bool(measured)), prompt,
                                 schema=_strict_schema(model, voice=bool(measured)), cfg=cfg)
    return model.model_validate(data), by


_SALES_REPORT = (
    "**Snapshot**: number of calls, outcomes breakdown, average scores per dimension (and the average voice tone "
    "score and the usual tones, when the analyses have a `voice` part).",
    "**Recurring patterns**: what keeps working and what keeps failing, with call ids/dates as evidence.",
    "**Top 3 priorities** to fix, ranked by impact on closing, each with a concrete drill or rule.",
    "**Improved pitch script**: a rewritten opening, 4-6 discovery questions, value pitch, and close, in the language\n"
    "   the calls are actually held in (Derja/French), ready to use.",
    "**Objection playbook**: the most frequent objections heard and the best answer for each.",
    "**Best and worst call** to listen to (call ids) and why.",
    "**Hot leads to follow up**: customers with high/medium interest and the next action.",
)
_SERVICE_REPORT = (
    "**Snapshot**: number of calls, resolution breakdown (resolved, escalated, pending, unresolved), customer "
    "sentiment, the main issue categories, average scores per dimension (and the average voice tone score and the "
    "usual tones, when the analyses have a `voice` part).",
    "**What customers call about**: the most frequent problems and their likely root causes, with call ids/dates as "
    "evidence, and what product, process or training change would make those calls unnecessary.",
    "**Recurring agent patterns**: what keeps working and what keeps failing in how the agents help.",
    "**Top 3 priorities** to fix, ranked by impact on resolution and customer satisfaction, each with a concrete "
    "drill or rule.",
    "**Answer playbook**: for the most frequent problems, the exact steps and wording that solve them, in the "
    "language the calls are actually held in (Derja/French), ready to use.",
    "**Best and worst call** to listen to (call ids) and why.",
    "**Customers to follow up**: unresolved, escalated or frustrated customers and the next action for each.",
)


def coaching_report(title: str, calls: list, feedback: dict[str, list[dict]] | None = None,
                    kind: str = "sales") -> str:
    """Turn many per-call analyses into one coaching report (markdown): sales calls get the sales report, `kind`
    "service" the customer service one. `feedback` is the human feedback by call id (db.feedback_by_call): it is
    shown next to each call's analysis and outweighs it when the two disagree."""
    feedback = feedback or {}
    items = []
    for call in calls:
        analysis = json.loads(call["analysis"])
        item = {
            "call_id": call["id"], "date": call["date_call"], "agent": call["agent"], "type": call["type"],
            "duration_s": call["duration"], **analysis,
        }
        if notes := feedback.get(call["id"]):
            item["human_feedback"] = notes
        items.append(item)
    reviewed = sum("human_feedback" in item for item in items)
    sections = list(_SERVICE_REPORT if kind == "service" else _SALES_REPORT)
    human_rule = ""
    if reviewed:
        sections.append("**Human review**: what the reviewers said, where they agree or disagree with the AI "
                        "(call ids, both scores), and what that changes in the advice above.")
        human_rule = f"""
{reviewed} of these calls carry `human_feedback`: notes (and sometimes a 1-10 `reviewer_score`) written by the
people who manage this team. They know the customers and the business, so they outweigh the AI analysis: when a
human note contradicts the AI (a score, a mistake, an outcome, a missed opportunity), follow the human and say so.
Weave what the humans said into the patterns, priorities and playbooks, and never present as a weakness something
a reviewer praised, or the reverse.
"""
    what = "customer service calls" if kind == "service" else "calls"
    manager = "support" if kind == "service" else "sales"
    numbered = "\n".join(f"{i}. {text}" for i, text in enumerate(sections, 1))
    prompt = f"""Below are the analyses of {len(items)} recorded {what} for: {title}.

<call_analyses>
{json.dumps(items, ensure_ascii=False, indent=1)}
</call_analyses>
{human_rule}
Write a coaching report in markdown for the {manager} manager. Include:
{numbered}
If several agents are present, add a short per-agent comparison.

Output only the report in markdown."""
    return ask_model(_system_prompt(kind=kind), prompt)
