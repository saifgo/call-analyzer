"""Standalone, printable review page for one call (used for share links, HTML download and PDF)."""
import base64
import html
import html.parser
import json
import re
from datetime import datetime
from pathlib import Path

ARABIC = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
LATIN = re.compile(r"[A-Za-zÀ-ÿ]")
TIMESTAMP_LINE = re.compile(r"^\[(\d{2}:\d{2}(?::\d{2})?)\]\s*(?:(speaker_\w+|channel_\w+):\s*)?(.*)$")

SCORE_NAMES = {
    "opening": "Opening", "discovery": "Discovery", "pitch": "Pitch",
    "objection_handling": "Objections", "closing": "Closing", "tone_and_listening": "Tone & listening",
}
DIRECTIONS = {"OUT": "Outbound", "IN": "Inbound", "QUEUE": "Inbound (queue)"}
GOOD_OUTCOMES = {"sale", "appointment_or_next_step"}
BAD_OUTCOMES = {"not_interested"}


def text_dir(text: str) -> str:
    """Direction by majority script, so 'TuniMobile صباح الخير' reads right-to-left."""
    return "rtl" if len(ARABIC.findall(text or "")) > len(LATIN.findall(text or "")) else "ltr"


def _e(text) -> str:
    return html.escape(str(text if text is not None else ""))


def _human(value) -> str:
    text = str(value or "").replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def _tone(score) -> str:
    if not isinstance(score, (int, float)):
        return "neutral"
    return "good" if score >= 7 else "warn" if score >= 5 else "bad"


def _fmt_duration(seconds) -> str:
    seconds = int(seconds or 0)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _fmt_date(value) -> str:
    try:
        d = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value or "")
    return f"{d.day} {d:%b %Y}, {d:%H:%M}"


def _block(text, tag="p", cls="") -> str:
    """A block whose direction follows its own content."""
    cls_attr = f' class="{cls}"' if cls else ""
    return f'<{tag} dir="{text_dir(text)}"{cls_attr}>{_e(text)}</{tag}>'


def _field(label: str, text, cls="") -> str:
    """Label on its own line above the content, both on the content's side (never mixed with Arabic on one line)."""
    return (f'<div class="field {cls}" dir="{text_dir(text)}"><div class="label">{_e(label)}</div>'
            f'<div class="content">{_e(text)}</div></div>')


def _section(title: str, items: list[str], *, content_text: str = "", empty: str = "None") -> str:
    """Heading plus content. The heading is kept on the same page as the first item, so it's never stranded."""
    items = items or [f'<p class="muted">{_e(empty)}</p>']
    head = f'<h2 dir="{text_dir(content_text)}">{_e(title)}</h2>'
    return (f'<section><div class="keep">{head}{items[0]}</div>{"".join(items[1:])}</section>')


def _bullets(items) -> list[str]:
    if not items:
        return []
    # Items share the list's direction so bullets and alignment stay consistent in mixed-script lists.
    return [f'<ul class="bullets" dir="{text_dir(" ".join(items))}">' + "".join(f"<li>{_e(i)}</li>" for i in items) + "</ul>"]


def _speaker_names(transcript: str) -> dict[str, str]:
    """speaker_0 / channel_L -> "Speaker 1", in order of first appearance (labels aren't reliably agent or customer)."""
    names: dict[str, str] = {}
    for line in transcript.splitlines():
        match = TIMESTAMP_LINE.match(line.strip())
        if match and match.group(2) and match.group(2) not in names:
            names[match.group(2)] = f"Speaker {len(names) + 1}"
    return names


def _transcript(transcript: str) -> str:
    if not transcript:
        return '<p class="muted">No transcript.</p>'
    names = _speaker_names(transcript)
    rows = []
    for line in transcript.splitlines():
        if not line.strip():
            continue
        match = TIMESTAMP_LINE.match(line.strip())
        ts, speaker, text = match.groups() if match else ("", None, line.strip())
        index = list(names).index(speaker) % 4 if speaker in names else 0
        who = f'<span class="who s{index}">{_e(names[speaker])}</span>' if speaker else ""
        rows.append(f'<div class="turn"><span class="ts">{_e(ts)}</span>{who}'
                    f'<span class="said" dir="{text_dir(text)}">{_e(text)}</span></div>')
    # Mostly-Arabic call: timestamps and speakers go on the right, next to where each line starts.
    return f'<div class="transcript" dir="{text_dir(transcript)}">{"".join(rows)}</div>'


_BLOCKS = {"p", "ul", "ol", "li", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}
_ARABIC_RUN = re.compile(
    ARABIC.pattern + r"+(?:[\s\d.,:;!?'’\"«»()\-،؛؟]*(?:[A-Za-zÀ-ÿ'’]+[\s\d.,:;!?'’\"«»()\-،؛؟]*){0,3}"
    + ARABIC.pattern + r"+)*[؟،؛!?.]?"
)


class _El:
    def __init__(self, tag: str, attrs: list[tuple[str, str | None]]):
        self.tag = tag
        self.attrs = attrs
        self.children: list = []


class _Tree(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _El("root", [])
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _El(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {"br", "hr", "img"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _plain(node) -> str:
    if isinstance(node, str):
        return node
    return "".join(_plain(child) for child in node.children)


def _isolate_arabic(text: str) -> str:
    parts, last = [], 0
    for match in _ARABIC_RUN.finditer(text):
        parts.append(html.escape(text[last:match.start()]))
        parts.append(f'<bdi dir="rtl">{html.escape(match.group())}</bdi>')
        last = match.end()
    parts.append(html.escape(text[last:]))
    return "".join(parts)


def _strip_colon(node: _El):
    for child in reversed(node.children):
        if isinstance(child, str) and child.strip():
            node.children[node.children.index(child)] = re.sub(r"\s*:\s*$", "", child)
            return


def _render_node(node, in_rtl: bool) -> str:
    if isinstance(node, str):
        return html.escape(node) if in_rtl or not ARABIC.search(node) else _isolate_arabic(node)
    rtl = in_rtl
    attrs = list(node.attrs)
    if node.tag in _BLOCKS:
        rtl = text_dir(_plain(node)) == "rtl"
        attrs = [(key, value) for key, value in attrs if key != "dir"] + [("dir", "rtl" if rtl else "ltr")]
        if rtl:
            first = next((child for child in node.children if not isinstance(child, str) or child.strip()), None)
            if isinstance(first, _El) and first.tag in {"strong", "b"} and text_dir(_plain(first)) == "ltr":
                first.attrs = [(key, value) for key, value in first.attrs if key != "style"]
                first.attrs.append(("style", "display:block"))
                _strip_colon(first)
                nxt = node.children.index(first) + 1
                if nxt < len(node.children) and isinstance(node.children[nxt], str):
                    node.children[nxt] = re.sub(r"^\s*:\s*", "", node.children[nxt])
    rendered = "".join(_render_node(child, rtl) for child in node.children)
    attr = "".join(
        f" {html.escape(key)}" if value is None else f' {html.escape(key)}="{html.escape(value)}"'
        for key, value in attrs
    )
    if node.tag in {"br", "hr", "img"}:
        return f"<{node.tag}{attr}>"
    return f"<{node.tag}{attr}>{rendered}</{node.tag}>"


def _bidi_html(fragment: str) -> str:
    """Give each block the direction of its own text, and isolate Arabic phrases inside Latin sentences."""
    parser = _Tree()
    parser.feed(fragment)
    parser.close()
    return "".join(_render_node(child, False) for child in parser.root.children)


def render_report_page(title: str, markdown_text: str) -> str:
    """Printable coaching report. Used for the public share page and for PDF export."""
    import markdown

    body = _bidi_html(markdown.markdown(
        markdown_text, extensions=["tables", "fenced_code", "sane_lists"],
    ))
    running = html.escape(title).replace('"', "'")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title>
<style>{REPORT_CSS.replace("__RUNNING__", running)}</style></head>
<body><main>
<header class="doc-header"><div class="brand"><span class="mark">CA</span> Call Analyzer
<span class="sep">/</span> <span class="muted">Coaching report</span></div></header>
<article>{body}</article>
<p class="doc-footer">Coaching report · Call Analyzer</p>
</main></body></html>"""


def audio_data_uri(path: Path) -> str:
    return "data:audio/mpeg;base64," + base64.b64encode(path.read_bytes()).decode()


def _overview(a: dict) -> str:
    score = a.get("overall_score")
    outcome = a.get("outcome")
    outcome_tone = "good" if outcome in GOOD_OUTCOMES else "bad" if outcome in BAD_OUTCOMES else "neutral"
    chips = [f'<span class="chip {outcome_tone}">{_e(_human(outcome) or "Unknown outcome")}</span>']
    if a.get("customer_interest"):
        chips.append(f'<span class="chip">Interest: {_e(_human(a["customer_interest"]))}</span>')
    if a.get("call_category"):
        chips.append(f'<span class="chip">{_e(_human(a["call_category"]))}</span>')
    if a.get("is_sales_conversation") is False:
        chips.append('<span class="chip warn">Not a sales conversation</span>')

    scores = a.get("scores") or {}
    bars = "".join(
        f'<div class="bar"><div class="bar-head"><span>{_e(name)}</span><b>{_e(scores.get(key, "–"))}<small>/10</small></b>'
        f'</div><div class="track"><div class="fill {_tone(scores.get(key))}" '
        f'style="width:{max(0, min(10, scores.get(key) or 0)) * 10}%"></div></div></div>'
        for key, name in SCORE_NAMES.items())

    return f"""
    <section class="overview keep">
      <div class="overall {_tone(score)}">
        <div class="overall-label">Overall score</div>
        <div class="overall-value">{_e(score if score is not None else "–")}<small>/10</small></div>
        <div class="chips">{''.join(chips)}</div>
      </div>
      <div class="bars">{bars}</div>
    </section>"""


def render_call_page(row, *, audio_src: str | None, links: list[tuple[str, str]], for_print: bool = False) -> str:
    a = json.loads(row["analysis"]) if row["analysis"] else None
    direction = DIRECTIONS.get(row["type"], row["type"])
    meta = [("Date", _fmt_date(row["date_call"])), ("Direction", direction), ("Agent", row["agent"]),
            ("Customer", row["customer"]), ("Length", _fmt_duration(row["duration"]))]

    parts = [f"""
    <header class="doc-header">
      <div class="brand"><span class="mark">CA</span><span>Call Analyzer</span><span class="sep">·</span>
        <span class="muted">Call review</span></div>
      <h1>Call #{_e(row['id'])}</h1>
      <dl class="meta">{''.join(f'<div><dt>{_e(k)}</dt><dd>{_e(v)}</dd></div>' for k, v in meta)}</dl>
    </header>"""]

    if audio_src and not for_print:
        parts.append(f'<section class="audio"><audio controls preload="metadata" src="{_e(audio_src)}"></audio></section>')
    if links:
        parts.append('<p class="links"><span class="muted">Recording</span> ' + "".join(
            f'<a href="{_e(url)}">{_e(label)} ↗</a>' for label, url in links) + "</p>")

    if a:
        parts.append(_overview(a))
        summary = a.get("summary", "")
        parts.append(_section("Summary", [_block(summary)] if summary else [], content_text=summary))
        if tip := a.get("top_coaching_tip"):
            parts.append(f'<section class="keep"><div class="callout tip">{_field("Top coaching tip", tip)}</div></section>')

        strengths = a.get("strengths") or []
        parts.append(_section("Strengths", _bullets(strengths), content_text=" ".join(strengths)))

        mistakes = a.get("mistakes") or []
        parts.append(_section("Mistakes and what to say instead", [
            '<div class="card">' + _field("Said", m.get("quote"), "quote") + _field("Why it hurt", m.get("problem"))
            + _field("Say instead", m.get("better_version"), "better") + "</div>" for m in mistakes
        ], content_text=" ".join(m.get("problem", "") for m in mistakes)))

        objections = a.get("objections") or []
        parts.append(_section("Objections", [
            '<div class="card">' + _field("Objection", o.get("objection"), "strong")
            + _field("How it was handled", o.get("how_handled"), "soft")
            + _field("Better answer", o.get("better_answer"), "better") + "</div>" for o in objections
        ], content_text=" ".join(o.get("objection", "") for o in objections)))

        missed = a.get("missed_opportunities") or []
        parts.append(_section("Missed opportunities", _bullets(missed), content_text=" ".join(missed)))
        if follow := a.get("follow_up_action"):
            parts.append(f'<section class="keep"><div class="callout next">{_field("Follow-up", follow)}</div></section>')
    else:
        parts.append('<p class="callout muted">This call has not been analyzed yet.</p>')

    parts.append('<section class="transcript-section"><h2>Transcript</h2>'
                 '<p class="muted small">Automatic transcription; it may contain errors and speaker labels may be swapped.</p>'
                 + _transcript(row["transcript"]) + "</section>")
    parts.append(f'<footer class="doc-footer">Generated {_fmt_date(datetime.now().isoformat(timespec="minutes"))} '
                 f'by Call Analyzer</footer>')

    running = f"Call #{row['id']} · Agent {row['agent']} · {_fmt_date(row['date_call'])}"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Call review #{_e(row['id'])} · {_e(row['date_call'])}</title>
<style>{PAGE_CSS.replace("__RUNNING__", running.replace('"', "'"))}</style></head>
<body><main>{''.join(parts)}</main></body></html>"""


PAGE_CSS = """
:root {
  --fg: #262626; --muted: #737373; --faint: #a3a3a3; --border: #e5e5e5; --soft: #f5f5f5;
  --brand: #0d9488;
  --good: #047857; --good-bg: #ecfdf5; --good-fill: #10b981;
  --warn: #b45309; --warn-bg: #fffbeb; --warn-fill: #f59e0b;
  --bad: #b91c1c; --bad-bg: #fef2f2; --bad-fill: #ef4444;
  --info: #1d4ed8; --info-bg: #eff6ff;
}
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; background: var(--soft); color: var(--fg);
  font: 14px/1.6 "Inter", "Segoe UI", "Noto Sans Arabic", "Noto Sans", Tahoma, Arial, sans-serif; }
main { max-width: 840px; margin: 24px auto; padding: 36px 40px 28px; background: #fff;
  border: 1px solid var(--border); border-radius: 16px; }
.muted { color: var(--muted); }
.small { font-size: 12px; }

.doc-header { padding-bottom: 18px; margin-bottom: 18px; border-bottom: 1px solid var(--border); }
.brand { display: flex; align-items: center; gap: 8px; font-size: 12px; font-weight: 600; }
.brand .mark { display: inline-grid; place-items: center; width: 22px; height: 22px; border-radius: 6px;
  background: var(--brand); color: #fff; font-size: 10px; letter-spacing: .02em; }
.brand .sep { color: var(--faint); }
.brand .muted { font-weight: 400; }
h1 { margin: 14px 0 14px; font-size: 26px; line-height: 1.2; letter-spacing: -.01em; }
.meta { display: grid; grid-template-columns: repeat(5, auto); justify-content: space-between; gap: 8px 20px; margin: 0; }
.meta dt { font-size: 11px; color: var(--muted); }
.meta dd { margin: 0; font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }

.links { font-size: 12px; margin: 0 0 18px; display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: center; }
.links a { color: var(--fg); text-decoration: none; border: 1px solid var(--border); border-radius: 999px; padding: 2px 10px; }
audio { width: 100%; margin: 0 0 16px; }

.overview { display: grid; grid-template-columns: 210px 1fr; gap: 24px; padding: 18px 20px; margin-bottom: 8px;
  border: 1px solid var(--border); border-radius: 12px; }
.overall-label { font-size: 12px; color: var(--muted); }
.overall-value { font-size: 44px; font-weight: 700; line-height: 1.1; letter-spacing: -.02em; margin: 2px 0 12px; }
.overall-value small, .bar-head small { font-size: .45em; font-weight: 500; color: var(--muted); letter-spacing: 0; }
.overall.good .overall-value { color: var(--good); }
.overall.warn .overall-value { color: var(--warn); }
.overall.bad .overall-value { color: var(--bad); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { font-size: 11px; font-weight: 500; padding: 1px 8px; border-radius: 6px; background: var(--soft); white-space: nowrap; }
.chip.good { background: var(--good-bg); color: var(--good); }
.chip.warn { background: var(--warn-bg); color: var(--warn); }
.chip.bad { background: var(--bad-bg); color: var(--bad); }
.bars { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 24px; align-content: center; }
.bar-head { display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 4px; }
.bar-head b { font-size: 13px; font-variant-numeric: tabular-nums; }
.track { height: 6px; border-radius: 999px; background: #ececec; overflow: hidden; }
.fill { height: 100%; border-radius: 999px; background: var(--faint); }
.fill.good { background: var(--good-fill); }
.fill.warn { background: var(--warn-fill); }
.fill.bad { background: var(--bad-fill); }

section { margin-top: 22px; }
h2 { font-size: 15px; margin: 0 0 10px; letter-spacing: -.005em; }
.keep, .card, .callout, .turn { break-inside: avoid; }
p { margin: 0 0 8px; }

.field + .field { margin-top: 10px; }
.label { font-size: 11px; font-weight: 600; color: var(--muted); margin-bottom: 2px; }
.field.quote .content { border-inline-start: 2px solid var(--border); padding-inline-start: 10px; color: #525252; }
/* Arabic has no true italics; slanting it only makes it harder to read. */
.field.quote[dir="ltr"] .content { font-style: italic; }
.field.strong .content { font-weight: 600; }
.field.soft .content { color: #525252; }
.field.better .label { color: var(--good); }
.field.better .content { background: var(--good-bg); color: #065f46; border-radius: 8px; padding: 6px 10px; font-weight: 500; }
.card { border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; margin-bottom: 10px; }
.callout { border-radius: 12px; padding: 14px 16px; border: 1px solid var(--border); }
.callout.tip { background: var(--info-bg); border-color: #dbeafe; }
.callout.tip .label { color: var(--info); }
.callout.next { background: var(--soft); }
.callout .content { font-size: 1.05em; }

.bullets { margin: 0; padding-inline-start: 20px; }
.bullets li { margin: 0 0 4px; padding-inline-start: 2px; }
.bullets li::marker { color: var(--faint); }

.transcript-section { break-before: page; }
.transcript { border-top: 1px solid var(--border); }
.turn { display: grid; grid-template-columns: 44px 76px 1fr; gap: 10px; align-items: baseline;
  padding: 7px 0; border-bottom: 1px solid #f0f0f0; }
.ts { font-size: 11px; color: var(--faint); font-variant-numeric: tabular-nums; }
.who { font-size: 11px; font-weight: 600; }
.who.s0 { color: var(--brand); }
.who.s1 { color: #7c3aed; }
.who.s2 { color: #c2410c; }
.who.s3 { color: #2563eb; }
.said { text-align: start; }

.doc-footer { margin-top: 28px; padding-top: 12px; border-top: 1px solid var(--border); font-size: 11px; color: var(--faint); text-align: center; }

@media (max-width: 640px) {
  main { margin: 0; border: 0; border-radius: 0; padding: 22px 18px; }
  .meta { grid-template-columns: repeat(2, 1fr); }
  .overview { grid-template-columns: 1fr; }
  .bars { grid-template-columns: 1fr; }
}
@media print {
  body { background: #fff; font-size: 12.5px; }
  main { max-width: none; margin: 0; padding: 0; border: 0; border-radius: 0; }
  a { color: var(--fg); }
  .doc-footer { display: none; }
}
@page {
  size: A4; margin: 16mm 15mm 18mm;
  @bottom-left { content: "__RUNNING__"; font: 9px "Segoe UI", "Noto Sans", Arial, sans-serif; color: #a3a3a3; }
  @bottom-right { content: "Page " counter(page) " of " counter(pages); font: 9px "Segoe UI", "Noto Sans", Arial, sans-serif; color: #a3a3a3; }
}
"""


REPORT_CSS = """
:root {
  --fg: #262626; --muted: #737373; --faint: #a3a3a3; --border: #e5e5e5; --soft: #f5f5f5; --brand: #0d9488;
}
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; background: var(--soft); color: var(--fg);
  font: 15px/1.6 "Inter", "Segoe UI", "Noto Sans Arabic", "Noto Sans", Tahoma, Arial, sans-serif; }
main { max-width: 840px; margin: 24px auto; padding: 36px 40px 28px; background: #fff;
  border: 1px solid var(--border); border-radius: 16px; }
.doc-header { padding-bottom: 8px; }
.brand { display: flex; align-items: center; gap: 8px; font-size: 12px; font-weight: 600; }
.brand .mark { display: inline-grid; place-items: center; width: 22px; height: 22px; border-radius: 6px;
  background: var(--brand); color: #fff; font-size: 10px; }
.brand .sep { color: var(--faint); }
.brand .muted { font-weight: 400; }
article h1 { margin: 8px 0 16px; font-size: 26px; line-height: 1.25; letter-spacing: -.01em; }
article h2 { font-size: 18px; margin: 26px 0 8px; }
article h3 { font-size: 15px; margin: 18px 0 6px; }
article p { margin: 0 0 10px; }
article ul, article ol { margin: 0 0 12px; padding-inline-start: 1.3em; }
article li { margin: 0 0 4px; }
article li::marker { color: var(--faint); }
article strong { font-weight: 650; }
article blockquote { margin: 0 0 12px; padding: 8px 12px; border-inline-start: 3px solid var(--border); color: #525252; }
article table { width: 100%; border-collapse: collapse; margin: 0 0 14px; font-size: 13px; }
article th, article td { border: 1px solid var(--border); padding: 6px 8px; vertical-align: top; text-align: start; }
article th { background: var(--soft); font-size: 12px; }
article code { font-family: "Geist Mono", ui-monospace, Consolas, monospace; font-size: .92em; }
article pre { background: var(--soft); padding: 10px 12px; border-radius: 8px; overflow: auto; }
article pre code { font-size: 12px; }
article [dir="rtl"] { text-align: right; }
h2, h3, tr, blockquote, li { break-inside: avoid; }
.doc-footer { margin-top: 28px; padding-top: 12px; border-top: 1px solid var(--border); font-size: 11px; color: var(--faint); text-align: center; }
@media (max-width: 640px) {
  main { margin: 0; border: 0; border-radius: 0; padding: 22px 18px; }
}
@media print {
  body { background: #fff; font-size: 12.5px; }
  main { max-width: none; margin: 0; padding: 0; border: 0; border-radius: 0; }
  .doc-footer { display: none; }
}
@page {
  size: A4; margin: 16mm 15mm 18mm;
  @bottom-left { content: "__RUNNING__"; font: 9px "Segoe UI", "Noto Sans", Arial, sans-serif; color: #a3a3a3; }
  @bottom-right { content: "Page " counter(page) " of " counter(pages); font: 9px "Segoe UI", "Noto Sans", Arial, sans-serif; color: #a3a3a3; }
}
"""
