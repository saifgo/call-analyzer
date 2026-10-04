// Mixed Arabic (RTL) / French-English (LTR) text.
// Each block takes the direction of most of its letters, and Arabic phrases inside
// LTR text are isolated in <bdi dir="rtl"> so embedded French words don't scramble the word order.
import type * as React from "react";
import { cn } from "@/lib/utils";

const ARABIC = "؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿";
const ARABIC_CHAR = new RegExp(`[${ARABIC}]`);
const ARABIC_CHARS = new RegExp(`[${ARABIC}]`, "g");
// An Arabic run, allowing up to 3 Latin words (French terms) between Arabic words.
const ARABIC_RUN = new RegExp(
  String.raw`[${ARABIC}]+(?:[\s\d.,:;!?'’"«»()\-،؛؟]*(?:[A-Za-zÀ-ÿ'’]+[\s\d.,:;!?'’"«»()\-،؛؟]*){0,3}[${ARABIC}]+)*[؟،؛!?.]?`,
  "g",
);

/** Direction by majority of letters, not the first one: "TuniMobile صباح الخير، معاك أنس" is an RTL sentence. */
export function textDir(text: string | null | undefined): "rtl" | "ltr" {
  if (!text) return "ltr";
  const rtl = (text.match(ARABIC_CHARS) || []).length;
  const ltr = (text.match(/[A-Za-zÀ-ÿ]/g) || []).length;
  return rtl > ltr ? "rtl" : "ltr";
}

/** Inline text with Arabic runs isolated, for use inside LTR blocks. */
export function BidiInline({ text }: { text: string }): React.ReactNode {
  if (!ARABIC_CHAR.test(text) || textDir(text) === "rtl") return text;
  const parts: React.ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(ARABIC_RUN)) {
    parts.push(text.slice(last, m.index));
    parts.push(
      <bdi dir="rtl" key={m.index}>
        {m[0]}
      </bdi>,
    );
    last = m.index + m[0].length;
  }
  parts.push(text.slice(last));
  return parts;
}

/** A block of mixed-direction text: sets dir from its content and isolates Arabic runs. */
export function Bidi({
  text,
  as: Tag = "p",
  className,
}: {
  text: string | null | undefined;
  as?: "p" | "div" | "span" | "li" | "blockquote";
  className?: string;
}): React.ReactElement {
  const value = text ?? "";
  const dir = textDir(value);
  return (
    <Tag className={cn(dir === "rtl" && "text-right", className)} dir={dir}>
      <BidiInline text={value} />
    </Tag>
  );
}

const BLOCKS = "p, ul, ol, li, td, th, h1, h2, h3, h4, h5, h6, blockquote";

/** Same treatment for HTML we don't render ourselves (markdown reports). */
export function fixBidiDom(root: HTMLElement | null): void {
  if (!root) return;
  root.querySelectorAll<HTMLElement>(BLOCKS).forEach((el) => el.setAttribute("dir", textDir(el.textContent)));
  // "**Top tip:** <Arabic…>" -> move the English bold label onto its own line above the Arabic text.
  root.querySelectorAll<HTMLElement>('[dir="rtl"]').forEach((el) => {
    const first = [...el.childNodes].find((n) => n.nodeType === Node.ELEMENT_NODE || n.textContent?.trim());
    if (
      first instanceof HTMLElement &&
      first.matches("strong, b") &&
      textDir(first.textContent) === "ltr"
    ) {
      first.style.display = "block";
      first.textContent = (first.textContent ?? "").replace(/\s*:\s*$/, "");
      if (first.nextSibling?.nodeType === Node.TEXT_NODE) {
        const next = first.nextSibling as Text;
        next.data = next.data.replace(/^\s*:\s*/, "");
      }
    }
  });
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) =>
      // Only isolate Arabic inside LTR text; in RTL blocks the browser already orders it correctly,
      // and splitting there would break bracket pairs like "(شكونك + TuniMobile + الفايدة)".
      node.parentElement?.closest("textarea, input, script, style, bdi, [dir='rtl']") ||
      !ARABIC_CHAR.test((node as Text).data)
        ? NodeFilter.FILTER_REJECT
        : NodeFilter.FILTER_ACCEPT,
  });
  const nodes: Text[] = [];
  while (walker.nextNode()) nodes.push(walker.currentNode as Text);
  for (const node of nodes) {
    const frag = document.createDocumentFragment();
    let last = 0;
    for (const m of node.data.matchAll(ARABIC_RUN)) {
      frag.append(node.data.slice(last, m.index));
      const bdi = document.createElement("bdi");
      bdi.dir = "rtl";
      bdi.textContent = m[0];
      frag.append(bdi);
      last = m.index + m[0].length;
    }
    frag.append(node.data.slice(last));
    node.replaceWith(frag);
  }
}
