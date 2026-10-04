import {
  ArrowDownIcon,
  ArrowUpIcon,
  CalendarIcon,
  ChevronsUpDownIcon,
  FileAudioIcon,
  MicIcon,
  SearchIcon,
  SparklesIcon,
  WorkflowIcon,
  XIcon,
} from "lucide-react";
import * as React from "react";
import type { DateRange } from "@daypicker/react";
import { OutcomeBadge, ScoreBadge, StatusBadge } from "@/components/call-badges";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { CardFrame, CardFrameFooter, CardFrameHeader } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group";
import { Pagination, PaginationContent, PaginationItem, PaginationNext, PaginationPrevious } from "@/components/ui/pagination";
import { Popover, PopoverPopup, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectItem, SelectPopup, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { fmtDate, fmtDateTime, fmtDuration, fmtRelative, fmtTime, isoDay, numberFmt, parseDate } from "@/lib/format";
import { useJob, useOnJobFinished } from "@/lib/jobs";
import { useMe } from "@/lib/me";
import { href, navigate, type Route } from "@/lib/router";
import type { CallList } from "@/lib/types";
import { CallSheet } from "./call-detail";

const PAGE_SIZE = 50;
const FILTER_KEYS = ["q", "agent", "status", "since", "until", "min"] as const;
// Everything kept in the URL: the filters plus the table sort ("duration", "-duration", …).
const QUERY_KEYS = [...FILTER_KEYS, "sort"] as const;
type Filters = Record<(typeof QUERY_KEYS)[number], string>;

const DEFAULT_SORT = "-date";
type SortKey = "date" | "agent" | "customer" | "duration" | "score" | "updated";
// Direction used the first time a column is clicked.
const FIRST_DESC: Record<SortKey, boolean> = { date: true, agent: false, customer: false, duration: true, score: true, updated: true };

function SortableHead({
  column,
  sort,
  onSort,
  className,
  children,
}: {
  column: SortKey;
  sort: string;
  onSort: (sort: string) => void;
  className?: string;
  children: React.ReactNode;
}) {
  const active = sort.replace(/^-/, "") === column;
  const desc = sort.startsWith("-");
  const Icon = !active ? ChevronsUpDownIcon : desc ? ArrowDownIcon : ArrowUpIcon;
  const next = active ? (desc ? column : `-${column}`) : FIRST_DESC[column] ? `-${column}` : column;
  return (
    <TableHead aria-sort={active ? (desc ? "descending" : "ascending") : undefined} className={className}>
      <button
        className={cn(
          "-mx-1 inline-flex items-center gap-1 rounded px-1 py-0.5 hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring",
          active && "text-foreground",
          className?.includes("text-right") && "flex-row-reverse",
        )}
        onClick={() => onSort(next === DEFAULT_SORT ? "" : next)}
        type="button"
      >
        {children}
        <Icon aria-hidden="true" className={cn("size-3.5", !active && "opacity-48")} />
      </button>
    </TableHead>
  );
}

const STATUS_ITEMS = [
  { label: "Any status", value: "all" },
  { label: "Not downloaded", value: "new" },
  { label: "Downloaded", value: "downloaded" },
  { label: "Transcribed", value: "transcribed" },
  { label: "Analyzed", value: "analyzed" },
  { label: "Needs re-analysis", value: "stale" },
  { label: "Errors", value: "error" },
];

const LENGTH_ITEMS = [
  { label: "Any length", value: "all" },
  { label: "30 s or more", value: "30" },
  { label: "1 min or more", value: "60" },
  { label: "2 min or more", value: "120" },
  { label: "5 min or more", value: "300" },
];

const rangeFmt = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });

function DateRangeFilter({ since, until, onChange }: { since: string; until: string; onChange: (since: string, until: string) => void }) {
  const from = parseDate(since) ?? undefined;
  // `until` is exclusive in the API; show the inclusive last day.
  const untilDate = parseDate(until);
  const to = untilDate ? new Date(untilDate.getTime() - 86400000) : undefined;
  const label = from ? (to && +to !== +from ? `${rangeFmt.format(from)} – ${rangeFmt.format(to)}` : rangeFmt.format(from)) : "Any date";

  const select = (range: DateRange | undefined) => {
    if (!range?.from) return onChange("", "");
    const end = new Date((range.to ?? range.from).getTime() + 86400000);
    onChange(isoDay(range.from), isoDay(end));
  };

  return (
    <Popover>
      <PopoverTrigger render={<Button className="justify-start font-normal" variant="outline" />}>
        <CalendarIcon aria-hidden="true" />
        <span className={from ? "" : "text-muted-foreground"}>{label}</span>
      </PopoverTrigger>
      <PopoverPopup align="start" className="*:p-2">
        <div className="flex flex-col gap-2">
          <Calendar defaultMonth={from} mode="range" onSelect={select} selected={{ from, to }} />
          {from && (
            <Button onClick={() => onChange("", "")} size="sm" variant="ghost">
              Clear dates
            </Button>
          )}
        </div>
      </PopoverPopup>
    </Popover>
  );
}

export function CallsPage({ route }: { route: Route }): React.ReactElement {
  const job = useJob();
  // Agent accounts get a read-only list: no selection or bulk processing.
  const { isAdmin } = useMe();
  const filters = Object.fromEntries(QUERY_KEYS.map((k) => [k, route.query.get(k) ?? ""])) as Filters;
  const sort = filters.sort || DEFAULT_SORT;
  const page = Math.max(1, Number(route.query.get("page")) || 1);
  const selectedId = route.param;

  const setQuery = (patch: Partial<Filters> & { page?: string }) => {
    const next = { ...filters, page: "", ...patch };
    navigate(href("calls", selectedId, next), { replace: true });
  };

  // Search box updates the URL after a short pause so typing stays smooth.
  const [search, setSearch] = React.useState(filters.q);
  React.useEffect(() => setSearch(filters.q), [filters.q]);
  React.useEffect(() => {
    if (search === filters.q) return;
    const t = window.setTimeout(() => setQuery({ q: search }), 300);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String((page - 1) * PAGE_SIZE) });
  if (filters.q) params.set("q", filters.q);
  if (filters.agent) params.set("agent", filters.agent);
  if (filters.status) params.set("status", filters.status);
  if (filters.since) params.set("since", filters.since);
  if (filters.until) params.set("until", filters.until);
  if (filters.min) params.set("min_duration", filters.min);
  params.set("sort", sort);
  const { data, loading, reload } = useApi<CallList>(`/api/calls?${params}`);
  useOnJobFinished(reload);

  const [checked, setChecked] = React.useState<Set<string>>(new Set());
  const calls = data?.calls ?? [];
  const allChecked = calls.length > 0 && calls.every((c) => checked.has(c.id));
  const someChecked = calls.some((c) => checked.has(c.id));
  const toggleAll = (on: boolean) =>
    setChecked((prev) => {
      const next = new Set(prev);
      for (const c of calls) {
        if (on) next.add(c.id);
        else next.delete(c.id);
      }
      return next;
    });
  const toggle = (id: string, on: boolean) =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  const bulk = async (commands: string[], redo = false) => {
    if (await job.start(commands, { ids: [...checked].join(","), redo, workers: 4 })) setChecked(new Set());
  };

  const agentItems = [{ label: "All agents", value: "all" }, ...(data?.agents ?? []).map((a) => ({ label: `Agent ${a}`, value: a }))];
  const hasFilters = FILTER_KEYS.some((k) => filters[k]);
  const total = data?.total ?? 0;
  const first = total ? (page - 1) * PAGE_SIZE + 1 : 0;
  const last = Math.min(page * PAGE_SIZE, total);
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const pageHref = (p: number) => href("calls", null, { ...filters, page: p > 1 ? String(p) : "" });
  const running = !!job.state?.running;
  const columns = isAdmin ? 10 : 9;

  return (
    <>
      <PageHeader
        description={
          isAdmin
            ? "Listen to calls, correct transcripts and read the coaching feedback."
            : "Listen to your calls and read the AI coaching feedback on each one."
        }
        title={isAdmin ? "Calls" : "My calls"}
      />

      <div className="flex flex-wrap items-center gap-2">
        <InputGroup className="w-full sm:w-72">
          <InputGroupInput
            aria-label="Search calls"
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search number, call ID or transcript"
            type="search"
            value={search}
          />
          <InputGroupAddon>
            <SearchIcon aria-hidden="true" />
          </InputGroupAddon>
        </InputGroup>
        {(isAdmin || agentItems.length > 2) && (
          <Select
            items={agentItems}
            onValueChange={(v) => setQuery({ agent: v === "all" ? "" : (v as string) })}
            value={filters.agent || "all"}
          >
            <SelectTrigger aria-label="Agent" className="w-auto">
              <SelectValue />
            </SelectTrigger>
            <SelectPopup>
              {agentItems.map((item) => (
                <SelectItem key={item.value} value={item.value}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectPopup>
          </Select>
        )}
        <Select
          items={STATUS_ITEMS}
          onValueChange={(v) => setQuery({ status: v === "all" ? "" : (v as string) })}
          value={filters.status || "all"}
        >
          <SelectTrigger aria-label="Status" className="w-auto">
            <SelectValue />
          </SelectTrigger>
          <SelectPopup>
            {STATUS_ITEMS.map((item) => (
              <SelectItem key={item.value} value={item.value}>
                {item.label}
              </SelectItem>
            ))}
          </SelectPopup>
        </Select>
        <Select
          items={LENGTH_ITEMS}
          onValueChange={(v) => setQuery({ min: v === "all" ? "" : (v as string) })}
          value={LENGTH_ITEMS.some((i) => i.value === filters.min) ? filters.min : "all"}
        >
          <SelectTrigger aria-label="Minimum length" className="w-auto">
            <SelectValue />
          </SelectTrigger>
          <SelectPopup>
            {LENGTH_ITEMS.map((item) => (
              <SelectItem key={item.value} value={item.value}>
                {item.label}
              </SelectItem>
            ))}
          </SelectPopup>
        </Select>
        <DateRangeFilter
          onChange={(since, until) => setQuery({ since, until })}
          since={filters.since}
          until={filters.until}
        />
        {hasFilters && (
          <Button onClick={() => navigate(href("calls", selectedId, { sort: filters.sort }), { replace: true })} variant="ghost">
            <XIcon aria-hidden="true" />
            Reset
          </Button>
        )}
      </div>

      <CardFrame>
        <CardFrameHeader className="flex min-h-14 flex-row flex-wrap items-center justify-between gap-2 py-3">
          {isAdmin && checked.size > 0 ? (
            <>
              <div className="flex items-center gap-2 font-medium text-sm">
                {checked.size} selected
                <Button onClick={() => setChecked(new Set())} size="xs" variant="ghost">
                  Clear
                </Button>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button disabled={running} onClick={() => bulk(["download", "transcribe", "analyze"])} size="sm">
                  <WorkflowIcon aria-hidden="true" />
                  Process
                </Button>
                <Button disabled={running} onClick={() => bulk(["transcribe"], true)} size="sm" variant="outline">
                  <MicIcon aria-hidden="true" />
                  Re-transcribe
                </Button>
                <Button disabled={running} onClick={() => bulk(["analyze"], true)} size="sm" variant="outline">
                  <SparklesIcon aria-hidden="true" />
                  Re-analyze
                </Button>
              </div>
            </>
          ) : (
            <div className="text-muted-foreground text-sm">
              {data ? `${numberFmt.format(total)} ${total === 1 ? "call" : "calls"}` : "Loading calls…"}
            </div>
          )}
        </CardFrameHeader>
        <Table variant="card">
          <TableHeader>
            <TableRow>
              {isAdmin && (
                <TableHead className="w-10">
                  <Checkbox
                    aria-label="Select all calls on this page"
                    checked={allChecked}
                    indeterminate={someChecked && !allChecked}
                    onCheckedChange={(v) => toggleAll(v)}
                  />
                </TableHead>
              )}
              <SortableHead column="date" onSort={(s) => setQuery({ sort: s })} sort={sort}>
                Date
              </SortableHead>
              <SortableHead column="agent" onSort={(s) => setQuery({ sort: s })} sort={sort}>
                Agent
              </SortableHead>
              <SortableHead column="customer" onSort={(s) => setQuery({ sort: s })} sort={sort}>
                Customer
              </SortableHead>
              <TableHead className="max-md:hidden">Type</TableHead>
              <SortableHead className="text-right" column="duration" onSort={(s) => setQuery({ sort: s })} sort={sort}>
                Length
              </SortableHead>
              <TableHead>Status</TableHead>
              <SortableHead column="score" onSort={(s) => setQuery({ sort: s })} sort={sort}>
                Score
              </SortableHead>
              <TableHead className="max-lg:hidden">Outcome</TableHead>
              <SortableHead className="max-xl:hidden" column="updated" onSort={(s) => setQuery({ sort: s })} sort={sort}>
                Updated
              </SortableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {!data && loading
              ? Array.from({ length: 8 }, (_, i) => (
                  <TableRow key={i}>
                    <TableCell colSpan={columns}>
                      <Skeleton className="h-5 w-full" />
                    </TableCell>
                  </TableRow>
                ))
              : calls.map((c) => (
                  <TableRow
                    className="cursor-pointer"
                    data-state={c.id === selectedId || checked.has(c.id) ? "selected" : undefined}
                    key={c.id}
                    onClick={() => navigate(href("calls", c.id, { ...filters, page: page > 1 ? String(page) : "" }))}
                  >
                    {isAdmin && (
                      <TableCell onClick={(e) => e.stopPropagation()}>
                        <Checkbox
                          aria-label={`Select call ${c.id}`}
                          checked={checked.has(c.id)}
                          onCheckedChange={(v) => toggle(c.id, v)}
                        />
                      </TableCell>
                    )}
                    <TableCell className="whitespace-nowrap">
                      <div className="font-medium">{fmtDate(c.date_call)}</div>
                      <div className="text-muted-foreground text-xs">{fmtTime(c.date_call)}</div>
                    </TableCell>
                    <TableCell className="tabular-nums">{c.agent}</TableCell>
                    <TableCell className="tabular-nums">{c.customer}</TableCell>
                    <TableCell className="text-muted-foreground max-md:hidden">{c.type}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmtDuration(c.duration)}</TableCell>
                    <TableCell>
                      <StatusBadge call={c} />
                    </TableCell>
                    <TableCell>
                      <ScoreBadge score={c.score} />
                    </TableCell>
                    <TableCell className="max-lg:hidden">
                      <OutcomeBadge outcome={c.outcome} />
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground max-xl:hidden" title={fmtDateTime(c.updated_at)}>
                      {fmtRelative(c.updated_at)}
                    </TableCell>
                  </TableRow>
                ))}
            {data && calls.length === 0 && (
              <TableRow>
                <TableCell colSpan={columns}>
                  <Empty className="md:py-12">
                    <EmptyHeader>
                      <EmptyMedia variant="icon">
                        <FileAudioIcon />
                      </EmptyMedia>
                      <EmptyTitle>No calls found</EmptyTitle>
                      <EmptyDescription>
                        {hasFilters
                          ? "Try different filters."
                          : isAdmin
                            ? "Run a sync from the Pipeline page to fetch calls."
                            : "No calls for your extensions yet."}
                      </EmptyDescription>
                    </EmptyHeader>
                  </Empty>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
        {total > PAGE_SIZE && (
          <CardFrameFooter className="flex flex-wrap items-center justify-between gap-2 py-3">
            <p className="text-muted-foreground text-sm tabular-nums">
              {numberFmt.format(first)}–{numberFmt.format(last)} of {numberFmt.format(total)}
            </p>
            <Pagination className="mx-0 w-auto">
              <PaginationContent>
                <PaginationItem>
                  <PaginationPrevious
                    aria-disabled={page <= 1}
                    className={page <= 1 ? "pointer-events-none opacity-64" : ""}
                    href={pageHref(page - 1)}
                  />
                </PaginationItem>
                <PaginationItem>
                  <span className="px-2 text-muted-foreground text-sm tabular-nums">
                    Page {page} of {lastPage}
                  </span>
                </PaginationItem>
                <PaginationItem>
                  <PaginationNext
                    aria-disabled={page >= lastPage}
                    className={page >= lastPage ? "pointer-events-none opacity-64" : ""}
                    href={pageHref(page + 1)}
                  />
                </PaginationItem>
              </PaginationContent>
            </Pagination>
          </CardFrameFooter>
        )}
      </CardFrame>

      <CallSheet
        callId={selectedId}
        onChanged={reload}
        onClose={() => navigate(href("calls", null, { ...filters, page: page > 1 ? String(page) : "" }))}
      />
    </>
  );
}
