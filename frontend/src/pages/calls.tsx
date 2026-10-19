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
} from "@/lib/format";
import { t } from "@/lib/i18n";
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
          className?.includes("text-end") && "flex-row-reverse",
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

// Functions, not constants, so the labels follow the interface language.
const statusItems = () => [
  { label: t("calls.status.new"), value: "new" },
  { label: t("calls.status.downloaded"), value: "downloaded" },
  { label: t("calls.status.transcribed"), value: "transcribed" },
  { label: t("calls.status.analyzed"), value: "analyzed" },
  { label: t("calls.status.stale"), value: "stale" },
  { label: t("calls.filter.skipped"), value: "skipped" },
  { label: t("calls.filter.errors"), value: "error" },
];

const kindItems = () => [
  { label: t("calls.filter.allCalls"), value: "all" },
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
const lengthItems = () => [
  { label: t("calls.len.under30"), value: "-30" },
  { label: t("calls.len.30to60"), value: "30-60" },
  { label: t("calls.len.1to2"), value: "60-120" },
  { label: t("calls.len.2to5"), value: "120-300" },
  { label: t("calls.len.over5"), value: "300-" },
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
  if (!items.length) return <p className="text-muted-foreground text-sm">{t("calls.noneNoted")}</p>;
  return (
    <ul className="flex flex-col gap-1.5">
      {items.map((item, i) => (
        <li className="flex gap-2 text-sm" key={i}>
          <Icon aria-hidden="true" className={cn("mt-0.5 size-3.5 shrink-0", className)} />
          <span dir="auto">{item}</span>
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
        aria-label={t("calls.highlightsFor", { id: callId })}
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
          <p className="text-muted-foreground text-sm">{t("calls.notAnalyzedYet")}</p>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <PopoverTitle className="text-sm">{t("calls.positives")}</PopoverTitle>
              <HighlightList className="text-success-foreground" icon={ThumbsUpIcon} items={positives} />
            </div>
            <div className="flex flex-col gap-2">
              <PopoverTitle className="text-sm">{t("calls.negatives")}</PopoverTitle>
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
    const timer = window.setTimeout(() => setQuery({ q: search }), 300);
    return () => window.clearTimeout(timer);
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
  const agentItems = (data?.agents ?? []).map((a) => ({ label: t("shell.agentExt", { ext: a }), value: a }));
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
            ? t("calls.descriptionAdmin")
            : t("calls.descriptionAgent")
        }
        title={isAdmin ? t("nav.calls") : t("calls.myCalls")}
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
        <TabsList aria-label={t("calls.kindOfCall")}>
          {kindItems().map((item) => (
            <TabsTab key={item.value} value={item.value}>
              {item.label}
            </TabsTab>
          ))}
        </TabsList>
      </Tabs>

      <div className="flex flex-wrap items-center gap-2">
        <InputGroup className="w-full sm:w-72">
          <InputGroupInput
            aria-label={t("calls.search")}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("calls.searchPlaceholder")}
            type="search"
            value={search}
          />
          <InputGroupAddon>
            <SearchIcon aria-hidden="true" />
          </InputGroupAddon>
        </InputGroup>
        {(isAdmin || agentItems.length > 1) && (
          <MultiSelectFilter
            allLabel={t("pipeline.allAgents")}
            items={agentItems}
            label={t("board.agents")}
            onChange={(agent) => setQuery({ agent })}
            value={filters.agent}
          />
        )}
        <MultiSelectFilter
          allLabel={t("calls.filter.anyStatus")}
          items={statusItems()}
          label={t("calls.filter.statuses")}
          onChange={(status) => setQuery({ status })}
          value={filters.status}
        />
        <MultiSelectFilter
          allLabel={t("calls.filter.anyOutcome")}
          items={outcomes}
          label={t("dashboard.outcomes")}
          onChange={(outcome) => setQuery({ outcome })}
          value={filters.outcome}
        />
        <MultiSelectFilter
          allLabel={t("calls.filter.anyLength")}
          items={lengthItems()}
          label={t("calls.filter.lengths")}
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
            {t("common.reset")}
          </Button>
        )}
      </div>

      <CardFrame>
        <CardFrameHeader className="flex min-h-14 flex-row flex-wrap items-center justify-between gap-2 py-3">
          {isAdmin && checked.size > 0 ? (
            <>
              <div className="flex items-center gap-2 font-medium text-sm">
                {t("calls.selected", { count: checked.size })}
                <Button onClick={() => setChecked(new Set())} size="xs" variant="ghost">
                  {t("calls.clear")}
                </Button>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button disabled={running} onClick={() => bulk(["download", "voice", "transcribe", "analyze"])} size="sm">
                  <WorkflowIcon aria-hidden="true" />
                  {t("calls.process")}
                </Button>
                <Button disabled={running} onClick={() => bulk(["transcribe"], true)} size="sm" variant="outline">
                  <MicIcon aria-hidden="true" />
                  {t("calls.retranscribe")}
                </Button>
                <Button disabled={running} onClick={() => bulk(["analyze"], true)} size="sm" variant="outline">
                  <SparklesIcon aria-hidden="true" />
                  {t("calls.reanalyze")}
                </Button>
              </div>
            </>
          ) : (
            <div className="text-muted-foreground text-sm">
              {data ? t("desk.nCalls", { count: total }) : t("calls.loading")}
            </div>
          )}
        </CardFrameHeader>
        <Table variant="card">
          <TableHeader>
            <TableRow>
              {isAdmin && (
                <TableHead className="w-10">
                  <Checkbox
                    aria-label={t("calls.selectAll")}
                    checked={allChecked}
                    indeterminate={someChecked && !allChecked}
                    onCheckedChange={(v) => toggleAll(v)}
                  />
                </TableHead>
              )}
              <SortableHead column="date" onSort={(s) => setQuery({ sort: s })} sort={sort}>
                {t("calls.col.date")}
              </SortableHead>
              <SortableHead column="agent" onSort={(s) => setQuery({ sort: s })} sort={sort}>
                {t("shell.agent")}
              </SortableHead>
              <SortableHead column="customer" onSort={(s) => setQuery({ sort: s })} sort={sort}>
                {t("value.customer")}
              </SortableHead>
              <TableHead className="max-md:hidden">{t("calls.col.type")}</TableHead>
              <SortableHead className="text-end" column="duration" onSort={(s) => setQuery({ sort: s })} sort={sort}>
                {t("calls.col.length")}
              </SortableHead>
              <TableHead>{t("board.status")}</TableHead>
              <SortableHead column="score" onSort={(s) => setQuery({ sort: s })} sort={sort}>
                {t("kpis.aiScore")}
              </SortableHead>
              <SortableHead column="human" onSort={(s) => setQuery({ sort: s })} sort={sort}>
                {t("calls.col.humanScore")}
              </SortableHead>
              <TableHead className="max-lg:hidden">{t("insights.outcome")}</TableHead>
              <SortableHead className="max-xl:hidden" column="updated" onSort={(s) => setQuery({ sort: s })} sort={sort}>
                {t("calls.col.updated")}
              </SortableHead>
              <TableHead className="w-10">
                <span className="sr-only">{t("calls.col.details")}</span>
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
                          aria-label={t("calls.selectCall", { id: c.id })}
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
                    <TableCell className="tabular-nums">
                      <span dir="ltr">{c.customer}</span>
                    </TableCell>
                    <TableCell className="text-muted-foreground max-md:hidden">{c.type}</TableCell>
                    <TableCell className="text-end tabular-nums">{fmtDuration(c.duration)}</TableCell>
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
                      <EmptyTitle>{t("calls.noneFound")}</EmptyTitle>
                      <EmptyDescription>
                        {hasFilters
                          ? t("calls.tryFilters")
                          : isAdmin
                            ? t("calls.emptyAdmin")
                            : t("calls.emptyAgent")}
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
              {t("calls.range", { first, last, total })}
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
                    {t("calls.pageOf", { last: lastPage, page })}
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
