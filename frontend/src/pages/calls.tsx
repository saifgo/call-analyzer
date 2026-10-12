import {
  ArrowDownIcon,
  ArrowUpIcon,
  ChevronsUpDownIcon,
  FileAudioIcon,
  InfoIcon,
  MicIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
  SearchIcon,
  SparklesIcon,
  WorkflowIcon,
  XIcon,
} from "lucide-react";
import * as React from "react";
import { KIND_LABEL, KindBadge, OutcomeBadge, ScoreBadge, StatusBadge } from "@/components/call-badges";
import { DateRangeFilter } from "@/components/date-range-filter";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { CardFrame, CardFrameFooter, CardFrameHeader } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group";
import { Pagination, PaginationContent, PaginationItem, PaginationNext, PaginationPrevious } from "@/components/ui/pagination";
import { Popover, PopoverPopup, PopoverTitle, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectItem, SelectPopup, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTab } from "@/components/ui/tabs";
import { useApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  fmtDate,
  fmtDateTime,
  fmtDuration,
  fmtRelative,
  fmtTime,
  humanize,
  numberFmt,
} from "@/lib/format";
import { useJob, useOnJobFinished } from "@/lib/jobs";
import { useMe } from "@/lib/me";
import { href, navigate, type Route } from "@/lib/router";
import type { CallDetail, CallList } from "@/lib/types";
import { CallSheet } from "./call-detail";

const PAGE_SIZE = 50;
// agent, status, outcome and len hold several comma-separated choices.
const FILTER_KEYS = ["q", "agent", "status", "kind", "outcome", "since", "until", "len"] as const;
// Everything kept in the URL: the filters plus the table sort ("duration", "-duration", …).
const QUERY_KEYS = [...FILTER_KEYS, "sort"] as const;
type Filters = Record<(typeof QUERY_KEYS)[number], string>;

const DEFAULT_SORT = "-date";
type SortKey = "date" | "agent" | "customer" | "duration" | "score" | "human" | "updated";
// Direction used the first time a column is clicked.
const FIRST_DESC: Record<SortKey, boolean> = { date: true, agent: false, customer: false, duration: true, score: true, human: true, updated: true };

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
  { label: "Not downloaded", value: "new" },
  { label: "Downloaded", value: "downloaded" },
  { label: "Transcribed", value: "transcribed" },
  { label: "Analyzed", value: "analyzed" },
  { label: "Needs re-analysis", value: "stale" },
  { label: "Skipped (SKIP_NUMBERS)", value: "skipped" },
  { label: "Errors", value: "error" },
];

const KIND_ITEMS = [
  { label: "All calls", value: "all" },
  ...["sales", "service", "other"].map((value) => ({ label: KIND_LABEL[value], value })),
];

// Same values as CallAnalysis.outcome and ServiceAnalysis.resolution_status in analyze.py.
const SALES_OUTCOMES = ["sale", "appointment_or_next_step", "callback_requested", "not_interested", "no_decision", "not_applicable"];
const SERVICE_OUTCOMES = ["resolved", "escalated", "pending_customer", "unresolved"];

// Only offer the outcomes that exist for the selected kind of call.
function outcomeItems(kind: string) {
  const values = kind === "sales" ? SALES_OUTCOMES : kind === "service" ? SERVICE_OUTCOMES : [...SALES_OUTCOMES, ...SERVICE_OUTCOMES];
  return values.map((value) => ({ label: humanize(value), value }));
}

// Length buckets as "min-max" seconds (max exclusive), the format of the API's `length` parameter.
const LENGTH_ITEMS = [
  { label: "Under 30 s", value: "-30" },
  { label: "30 s – 1 min", value: "30-60" },
  { label: "1 – 2 min", value: "60-120" },
  { label: "2 – 5 min", value: "120-300" },
  { label: "5 min or more", value: "300-" },
];

const splitList = (value: string) => (value ? value.split(",") : []);

// Select allowing several values; the trigger shows the single choice, or "<label> · n".
function MultiSelectFilter({
  label,
  allLabel,
  items,
  value,
  onChange,
}: {
  label: string;
  allLabel: string;
  items: { label: string; value: string }[];
  value: string;
  onChange: (value: string) => void;
}) {
  const selected = splitList(value);
  return (
    <Select
      items={items}
      multiple
      onValueChange={(v) => {
        // Keep the list order so the URL stays stable.
        const chosen = new Set(v as string[]);
        onChange(items.filter((i) => chosen.has(i.value)).map((i) => i.value).join(","));
      }}
      value={selected}
    >
      <SelectTrigger aria-label={label} className="w-auto">
        <SelectValue>
          {(v: string[]) =>
            !v.length ? (
              <span className="text-muted-foreground">{allLabel}</span>
            ) : v.length === 1 ? (
              (items.find((i) => i.value === v[0])?.label ?? v[0])
            ) : (
              `${label} · ${v.length}`
            )
          }
        </SelectValue>
      </SelectTrigger>
      <SelectPopup alignItemWithTrigger={false}>
        {items.map((item) => (
          <SelectItem key={item.value} value={item.value}>
            {item.label}
          </SelectItem>
        ))}
      </SelectPopup>
    </Select>
  );
}

function HighlightList({ items, icon: Icon, className }: { items: string[]; icon: typeof ThumbsUpIcon; className: string }) {
  if (!items.length) return <p className="text-muted-foreground text-sm">None noted.</p>;
  return (
    <ul className="flex flex-col gap-1.5">
      {items.map((item, i) => (
        <li className="flex gap-2 text-sm" key={i}>
          <Icon aria-hidden="true" className={cn("mt-0.5 size-3.5 shrink-0", className)} />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

// Three positives and three negatives from the call's analysis, fetched when the popover opens.
function CallHighlights({ callId }: { callId: string }) {
  const [open, setOpen] = React.useState(false);
  const { data: call, error } = useApi<CallDetail>(open ? `/api/calls/${encodeURIComponent(callId)}` : null);
  const a = call?.analysis;
  const positives = a?.strengths.slice(0, 3) ?? [];
  // Mistakes first, topped up with missed opportunities.
  const negatives = a ? [...a.mistakes.map((m) => m.problem), ...a.missed_opportunities].slice(0, 3) : [];

  return (
    <Popover onOpenChange={setOpen} open={open}>
      <PopoverTrigger
        aria-label={`Positives and negatives for call ${callId}`}
        onClick={(e) => e.stopPropagation()}
        render={<Button size="icon-xs" variant="ghost" />}
      >
        <InfoIcon aria-hidden="true" />
      </PopoverTrigger>
      <PopoverPopup align="end" className="w-80" onClick={(e) => e.stopPropagation()}>
        {error ? (
          <p className="text-destructive-foreground text-sm">{error.message}</p>
        ) : !call ? (
          <div className="flex justify-center py-4">
            <Spinner />
          </div>
        ) : !a ? (
          <p className="text-muted-foreground text-sm">This call hasn't been analyzed yet.</p>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <PopoverTitle className="text-sm">Positives</PopoverTitle>
              <HighlightList className="text-success-foreground" icon={ThumbsUpIcon} items={positives} />
            </div>
            <div className="flex flex-col gap-2">
              <PopoverTitle className="text-sm">Negatives</PopoverTitle>
              <HighlightList className="text-destructive-foreground" icon={ThumbsDownIcon} items={negatives} />
            </div>
          </div>
        )}
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
  if (filters.kind) params.set("kind", filters.kind);
  if (filters.outcome) params.set("outcome", filters.outcome);
  if (filters.since) params.set("since", filters.since);
  if (filters.until) params.set("until", filters.until);
  if (filters.len) params.set("length", filters.len);
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

  const outcomes = outcomeItems(filters.kind);
  const agentItems = (data?.agents ?? []).map((a) => ({ label: `Agent ${a}`, value: a }));
  const hasFilters = FILTER_KEYS.some((k) => filters[k]);
  const total = data?.total ?? 0;
  const first = total ? (page - 1) * PAGE_SIZE + 1 : 0;
  const last = Math.min(page * PAGE_SIZE, total);
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const pageHref = (p: number) => href("calls", null, { ...filters, page: p > 1 ? String(p) : "" });
  const running = !!job.state?.running;
  const columns = isAdmin ? 12 : 11;

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

      <Tabs
        onValueChange={(v) => {
          const kind = v === "all" ? "" : (v as string);
          // Drop outcomes that don't exist for the newly selected kind.
          const valid = new Set(outcomeItems(kind).map((i) => i.value));
          setQuery({ kind, outcome: splitList(filters.outcome).filter((o) => valid.has(o)).join(",") });
        }}
        value={filters.kind || "all"}
      >
        <TabsList aria-label="Kind of call">
          {KIND_ITEMS.map((item) => (
            <TabsTab key={item.value} value={item.value}>
              {item.label}
            </TabsTab>
          ))}
        </TabsList>
      </Tabs>

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
        {(isAdmin || agentItems.length > 1) && (
          <MultiSelectFilter
            allLabel="All agents"
            items={agentItems}
            label="Agents"
            onChange={(agent) => setQuery({ agent })}
            value={filters.agent}
          />
        )}
        <MultiSelectFilter
          allLabel="Any status"
          items={STATUS_ITEMS}
          label="Statuses"
          onChange={(status) => setQuery({ status })}
          value={filters.status}
        />
        <MultiSelectFilter
          allLabel="Any outcome"
          items={outcomes}
          label="Outcomes"
          onChange={(outcome) => setQuery({ outcome })}
          value={filters.outcome}
        />
        <MultiSelectFilter
          allLabel="Any length"
          items={LENGTH_ITEMS}
          label="Lengths"
          onChange={(len) => setQuery({ len })}
          value={filters.len}
        />
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
                <Button disabled={running} onClick={() => bulk(["download", "voice", "transcribe", "analyze"])} size="sm">
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
                AI score
              </SortableHead>
              <SortableHead column="human" onSort={(s) => setQuery({ sort: s })} sort={sort}>
                Human score
              </SortableHead>
              <TableHead className="max-lg:hidden">Outcome</TableHead>
              <SortableHead className="max-xl:hidden" column="updated" onSort={(s) => setQuery({ sort: s })} sort={sort}>
                Updated
              </SortableHead>
              <TableHead className="w-10">
                <span className="sr-only">Details</span>
              </TableHead>
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
                    <TableCell>
                      <ScoreBadge score={c.human_score} />
                    </TableCell>
                    <TableCell className="max-lg:hidden">
                      <div className="flex flex-wrap gap-1">
                        <KindBadge kind={c.kind} />
                        <OutcomeBadge outcome={c.outcome} />
                      </div>
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground max-xl:hidden" title={fmtDateTime(c.updated_at)}>
                      {fmtRelative(c.updated_at)}
                    </TableCell>
                    <TableCell onClick={(e) => e.stopPropagation()}>
                      {c.score !== null && <CallHighlights callId={c.id} />}
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
