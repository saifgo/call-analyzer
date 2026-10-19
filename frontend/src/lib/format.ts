import { intlLocale, maybeT, t } from "@/lib/i18n";

export const fmtDuration = (s: number): string => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

/** An API value for display: its translation from the locales' "value.*" keys, else "not_interested" -> "Not interested". */
export const humanize = (s: string | null | undefined): string => {
  const known = s ? maybeT(`value.${s}`) : undefined;
  if (known) return known;
  const text = String(s ?? "").replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
};

/** One formatter per (options, language), rebuilt when the interface language changes. */
function cached<F>(make: (locale: string) => F): () => F {
  let locale = "";
  let fmt: F;
  return () => {
    if (locale !== intlLocale()) {
      locale = intlLocale();
      fmt = make(locale);
    }
    return fmt;
  };
}

/** An Intl.DateTimeFormat that follows the interface language. */
export const dateTimeFormat = (options: Intl.DateTimeFormatOptions): (() => Intl.DateTimeFormat) =>
  cached((locale) => new Intl.DateTimeFormat(locale, options));

const dateFmt = dateTimeFormat({ day: "numeric", month: "short", year: "numeric" });
const dateTimeFmt = dateTimeFormat({ day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const timeFmt = dateTimeFormat({ hour: "2-digit", minute: "2-digit" });

/** Server timestamps are local "YYYY-MM-DD HH:MM:SS" or ISO without timezone. */
export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const d = new Date(value.replace(" ", "T"));
  return Number.isNaN(d.getTime()) ? null : d;
}

export function fmtDate(value: string | null | undefined): string {
  const d = parseDate(value);
  return d ? dateFmt().format(d) : (value ?? "");
}

export function fmtDateTime(value: string | null | undefined): string {
  const d = parseDate(value);
  return d ? dateTimeFmt().format(d) : (value ?? "");
}

export function fmtTime(value: string | null | undefined): string {
  const d = parseDate(value);
  return d ? timeFmt().format(d) : "";
}

const rtf = cached((locale) => new Intl.RelativeTimeFormat(locale, { numeric: "auto" }));

export function fmtRelative(value: string | null | undefined): string {
  const d = parseDate(value);
  if (!d) return "";
  const seconds = Math.round((d.getTime() - Date.now()) / 1000);
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) return rtf().format(Math.round(seconds / size), unit);
  }
  return t("common.justNow");
}

/** Local date as YYYY-MM-DD (what the API's since/until filters expect). */
export function isoDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const numberFormat = cached((locale) => new Intl.NumberFormat(locale));
/** Locale number formatting: numberFmt.format(1234) -> "1,234" / "1 234". */
export const numberFmt = { format: (n: number | bigint): string => numberFormat().format(n) };
