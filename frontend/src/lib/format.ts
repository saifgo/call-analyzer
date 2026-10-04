export const fmtDuration = (s: number): string => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

export const humanize = (s: string | null | undefined): string => {
  const text = String(s ?? "").replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
};

const dateFmt = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric" });
const dateTimeFmt = new Intl.DateTimeFormat(undefined, {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});
const timeFmt = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });

/** Server timestamps are local "YYYY-MM-DD HH:MM:SS" or ISO without timezone. */
export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const d = new Date(value.replace(" ", "T"));
  return Number.isNaN(d.getTime()) ? null : d;
}

export function fmtDate(value: string | null | undefined): string {
  const d = parseDate(value);
  return d ? dateFmt.format(d) : (value ?? "");
}

export function fmtDateTime(value: string | null | undefined): string {
  const d = parseDate(value);
  return d ? dateTimeFmt.format(d) : (value ?? "");
}

export function fmtTime(value: string | null | undefined): string {
  const d = parseDate(value);
  return d ? timeFmt.format(d) : "";
}

const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

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
    if (Math.abs(seconds) >= size) return rtf.format(Math.round(seconds / size), unit);
  }
  return "just now";
}

/** Local date as YYYY-MM-DD (what the API's since/until filters expect). */
export function isoDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export const numberFmt = new Intl.NumberFormat();
