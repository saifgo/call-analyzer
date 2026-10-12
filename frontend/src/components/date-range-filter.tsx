import { CalendarIcon } from "lucide-react";
import type { DateRange } from "@daypicker/react";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverPopup, PopoverTrigger } from "@/components/ui/popover";
import { isoDay, parseDate } from "@/lib/format";

const DAY = 86400000;
const rangeFmt = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });

function startOfToday(): Date {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d;
}

// Quick ranges: [label, first day, exclusive end].
function presets(): [string, Date, Date][] {
  const today = startOfToday();
  const tomorrow = new Date(today.getTime() + DAY);
  const daysAgo = (n: number) => new Date(today.getTime() - n * DAY);
  const monthStart = new Date(today.getFullYear(), today.getMonth(), 1);
  return [
    ["Today", today, tomorrow],
    ["Yesterday", daysAgo(1), today],
    ["Last 7 days", daysAgo(6), tomorrow],
    ["Last 30 days", daysAgo(29), tomorrow],
    ["This month", monthStart, tomorrow],
    ["Last month", new Date(today.getFullYear(), today.getMonth() - 1, 1), monthStart],
  ];
}

/** Date range picker. `since`/`until` are ISO days; `until` is exclusive, like the API. */
export function DateRangeFilter({
  since,
  until,
  onChange,
}: {
  since: string;
  until: string;
  onChange: (since: string, until: string) => void;
}) {
  const from = parseDate(since) ?? undefined;
  // `until` is exclusive in the API; show the inclusive last day.
  const untilDate = parseDate(until);
  const to = untilDate ? new Date(untilDate.getTime() - DAY) : undefined;
  const label = from ? (to && +to !== +from ? `${rangeFmt.format(from)} – ${rangeFmt.format(to)}` : rangeFmt.format(from)) : "Any date";

  const select = (range: DateRange | undefined) => {
    if (!range?.from) return onChange("", "");
    const end = new Date((range.to ?? range.from).getTime() + DAY);
    onChange(isoDay(range.from), isoDay(end));
  };

  return (
    <Popover>
      <PopoverTrigger render={<Button className="justify-start font-normal" variant="outline" />}>
        <CalendarIcon aria-hidden="true" />
        <span className={from ? "" : "text-muted-foreground"}>{label}</span>
      </PopoverTrigger>
      <PopoverPopup align="start" className="*:p-2">
        <div className="flex gap-2 max-sm:flex-col">
          <div className="flex flex-col gap-1 sm:border-e sm:pe-2 max-sm:flex-row max-sm:flex-wrap">
            {presets().map(([name, start, end]) => {
              const active = since === isoDay(start) && until === isoDay(end);
              return (
                <Button
                  className="justify-start"
                  key={name}
                  onClick={() => onChange(isoDay(start), isoDay(end))}
                  size="sm"
                  variant={active ? "secondary" : "ghost"}
                >
                  {name}
                </Button>
              );
            })}
          </div>
          <div className="flex flex-col gap-2">
            <Calendar defaultMonth={from} mode="range" onSelect={select} selected={{ from, to }} />
            {from && (
              <Button onClick={() => onChange("", "")} size="sm" variant="ghost">
                Clear dates
              </Button>
            )}
          </div>
        </div>
      </PopoverPopup>
    </Popover>
  );
}
