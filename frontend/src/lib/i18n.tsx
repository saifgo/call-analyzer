// Interface language: English, French or Arabic (right-to-left).
// Strings live in src/locales; `en` is the source and the other locales must define every key (tsc enforces it).
// Plurals: a key "x" used with { count } resolves to "x_one" / "x_other" (Arabic adds _zero, _two, _few, _many).
import * as React from "react";
import { ar } from "@/locales/ar";
import { en } from "@/locales/en";
import { fr } from "@/locales/fr";

export type Locale = "en" | "fr" | "ar";

type PluralForm = "zero" | "one" | "two" | "few" | "many" | "other";
type EnKey = keyof typeof en;
type PluralBase = EnKey extends infer K ? (K extends `${infer B}_other` ? B : never) : never;
/** Keys accepted by t(): plain keys, plus plural keys without their _one/_other suffix. */
export type TKey = Exclude<EnKey, `${string}_${PluralForm}`> | PluralBase;
/** What every locale must provide; Arabic plural forms beyond _one/_other are optional. */
export type Messages = Record<EnKey, string> & Partial<Record<`${PluralBase}_${PluralForm}`, string>>;
export type Vars = Record<string, string | number | null | undefined>;

export const LOCALES: { value: Locale; label: string; dir: "ltr" | "rtl" }[] = [
  { dir: "ltr", label: "English", value: "en" },
  { dir: "ltr", label: "Français", value: "fr" },
  { dir: "rtl", label: "العربية", value: "ar" },
];

const MESSAGES: Record<Locale, Messages> = { ar, en, fr };
/** Locale used for Intl formatting: Tunisian Arabic keeps Latin digits, like the phone numbers and amounts agents read. */
const INTL_LOCALE: Record<Locale, string> = { ar: "ar-TN", en: "en-GB", fr: "fr-FR" };

function detect(): Locale {
  const saved = localStorage.getItem("lang");
  if (saved === "en" || saved === "fr" || saved === "ar") return saved;
  const nav = navigator.language.slice(0, 2);
  return nav === "fr" || nav === "ar" ? nav : "en";
}

let current: Locale = detect();
const listeners = new Set<() => void>();
const pluralRules = new Map<Locale, Intl.PluralRules>();

export const getLocale = (): Locale => current;
export const intlLocale = (): string => INTL_LOCALE[current];
export const isRtl = (): boolean => current === "ar";

function applyDocument(locale: Locale) {
  document.documentElement.lang = locale;
  document.documentElement.dir = locale === "ar" ? "rtl" : "ltr";
}
applyDocument(current);

export function setLocale(locale: Locale): void {
  if (locale === current) return;
  current = locale;
  localStorage.setItem("lang", locale);
  applyDocument(locale);
  for (const fn of listeners) fn();
}

function interpolate(text: string, vars?: Vars): string {
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (m, name: string) => {
    const v = vars[name];
    if (v === null || v === undefined) return m;
    return typeof v === "number" ? v.toLocaleString(INTL_LOCALE[current]) : v;
  });
}

function lookup(key: string, vars?: Vars): string {
  const messages = MESSAGES[current] as Record<string, string>;
  const fallback = en as Record<string, string>;
  if (vars && typeof vars.count === "number") {
    let rules = pluralRules.get(current);
    if (!rules) {
      rules = new Intl.PluralRules(INTL_LOCALE[current]);
      pluralRules.set(current, rules);
    }
    const form = rules.select(vars.count);
    const plural =
      messages[`${key}_${form}`] ??
      messages[`${key}_other`] ??
      fallback[`${key}_${vars.count === 1 ? "one" : "other"}`];
    if (plural !== undefined) return plural;
  }
  return messages[key] ?? fallback[key] ?? key;
}

/** Translate outside React (module code, toasts). Inside components prefer useT() so the text updates on switch. */
export function t(key: TKey, vars?: Vars): string {
  return interpolate(lookup(key, vars), vars);
}

/** Translate a key built at runtime (e.g. from an API value); undefined when no locale defines it. */
export function maybeT(key: string, vars?: Vars): string | undefined {
  const known = key in (MESSAGES[current] as object) || key in en || `${key}_other` in en;
  return known ? interpolate(lookup(key, vars), vars) : undefined;
}

/** Translate with React elements in the placeholders: tx("x", { link: <a/> }) for "Open {link} now". */
export function tx(key: TKey, vars: Record<string, React.ReactNode>): React.ReactNode {
  const text = lookup(key, vars as Vars);
  const parts: React.ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(/\{(\w+)\}/g)) {
    parts.push(text.slice(last, m.index));
    const v = vars[m[1]];
    parts.push(
      React.isValidElement(v) ? React.cloneElement(v, { key: m.index }) : typeof v === "number" ? v.toLocaleString(INTL_LOCALE[current]) : v,
    );
    last = m.index + m[0].length;
  }
  parts.push(text.slice(last));
  return parts;
}

/** A label map translated on read, so module-level tables like STEP_LABELS[step] follow the current language. */
export function labels<K extends string>(keys: Record<K, TKey>): Record<K, string> {
  const out = {} as Record<K, string>;
  for (const k of Object.keys(keys) as K[]) {
    Object.defineProperty(out, k, { enumerable: true, get: () => t(keys[k]) });
  }
  return out;
}

/** A list joined the locale's way: "a, b and c" / "a, b et c" / "a وb وc". */
export function joinList(items: string[], type: "conjunction" | "disjunction" = "conjunction"): string {
  return new Intl.ListFormat(INTL_LOCALE[current], { type }).format(items);
}

function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Current language plus translate helpers; re-renders the component when the language changes. */
export function useT(): { t: typeof t; tx: typeof tx; locale: Locale; dir: "ltr" | "rtl"; setLocale: typeof setLocale } {
  const locale = React.useSyncExternalStore(subscribe, getLocale);
  return { dir: locale === "ar" ? "rtl" : "ltr", locale, setLocale, t, tx };
}
