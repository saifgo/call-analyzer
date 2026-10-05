import { MessageSquareTextIcon, SearchIcon, XIcon } from "lucide-react";
import * as React from "react";
import { ScoreBadge } from "@/components/call-badges";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CardFrame, CardFrameFooter, CardFrameHeader } from "@/components/ui/card";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group";
import { Select, SelectItem, SelectPopup, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi } from "@/lib/api";
import { Bidi } from "@/lib/bidi";
import { fmtDate, fmtDateTime, fmtRelative, fmtTime, numberFmt } from "@/lib/format";
import { useMe } from "@/lib/me";
import { href, navigate, type Route } from "@/lib/router";
import type { FeedbackList } from "@/lib/types";
import { CallSheet } from "./call-detail";

const LIMIT = 200;

/** Every note people wrote about calls, with the call each one is linked to. Click a row to open that call. */
export function FeedbackPage({ route }: { route: Route }): React.ReactElement {
  const { isAdmin } = useMe();
  const q = route.query.get("q") ?? "";
  const author = route.query.get("author") ?? "";
  const selectedId = route.param;

  const setQuery = (patch: { q?: string; author?: string }) =>
    navigate(href("feedback", selectedId, { author, q, ...patch }), { replace: true });

  // Search box updates the URL after a short pause so typing stays smooth.
  const [search, setSearch] = React.useState(q);
  React.useEffect(() => setSearch(q), [q]);
  React.useEffect(() => {
    if (search === q) return;
    const t = window.setTimeout(() => setQuery({ q: search }), 300);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const params = new URLSearchParams({ limit: String(LIMIT) });
  if (q) params.set("q", q);
  if (author) params.set("author", author);
  const { data, loading, reload } = useApi<FeedbackList>(`/api/feedback?${params}`);

  const items = data?.feedback ?? [];
  const total = data?.total ?? 0;
  const authorItems = [{ label: "All authors", value: "all" }, ...(data?.authors ?? []).map((a) => ({ label: a, value: a }))];
  const hasFilters = !!(q || author);
  const callHref = (id: string) => href("feedback", id, { author, q });

  return (
    <>
      <PageHeader
        description={
          isAdmin
            ? "Everything the team wrote about calls. Open a row to see the call, and add or edit feedback there."
            : "What reviewers wrote about your calls."
        }
        title="Human feedback"
      />

      <div className="flex flex-wrap items-center gap-2">
        <InputGroup className="w-full sm:w-72">
          <InputGroupInput
            aria-label="Search feedback"
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search feedback, number or call ID"
            type="search"
            value={search}
          />
          <InputGroupAddon>
            <SearchIcon aria-hidden="true" />
          </InputGroupAddon>
        </InputGroup>
        {authorItems.length > 2 && (
          <Select
            items={authorItems}
            onValueChange={(v) => setQuery({ author: v === "all" ? "" : (v as string) })}
            value={author || "all"}
          >
            <SelectTrigger aria-label="Author" className="w-auto">
              <SelectValue />
            </SelectTrigger>
            <SelectPopup>
              {authorItems.map((item) => (
                <SelectItem key={item.value} value={item.value}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectPopup>
          </Select>
        )}
        {hasFilters && (
          <Button onClick={() => navigate(href("feedback", selectedId), { replace: true })} variant="ghost">
            <XIcon aria-hidden="true" />
            Reset
          </Button>
        )}
      </div>

      <CardFrame>
        <CardFrameHeader className="flex min-h-14 flex-row items-center py-3">
          <div className="text-muted-foreground text-sm">
            {data ? `${numberFmt.format(total)} ${total === 1 ? "note" : "notes"}` : "Loading feedback…"}
          </div>
        </CardFrameHeader>
        <Table variant="card">
          <TableHeader>
            <TableRow>
              <TableHead>Added</TableHead>
              <TableHead>Author</TableHead>
              <TableHead className="min-w-64">Feedback</TableHead>
              <TableHead>Score</TableHead>
              <TableHead>Call</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {!data && loading
              ? Array.from({ length: 6 }, (_, i) => (
                  <TableRow key={i}>
                    <TableCell colSpan={5}>
                      <Skeleton className="h-5 w-full" />
                    </TableCell>
                  </TableRow>
                ))
              : items.map((f) => (
                  <TableRow
                    className="cursor-pointer align-top"
                    data-state={f.call_id === selectedId ? "selected" : undefined}
                    key={f.id}
                    onClick={() => navigate(callHref(f.call_id))}
                  >
                    <TableCell className="whitespace-nowrap" title={fmtDateTime(f.created_at)}>
                      <div className="font-medium">{fmtDate(f.created_at)}</div>
                      <div className="text-muted-foreground text-xs">{fmtTime(f.created_at)}</div>
                    </TableCell>
                    <TableCell className="whitespace-nowrap">{f.author_name}</TableCell>
                    <TableCell className="whitespace-normal">
                      <Bidi className="line-clamp-3 whitespace-pre-wrap" text={f.body} />
                      {f.updated_at !== f.created_at && (
                        <span className="text-muted-foreground text-xs" title={fmtDateTime(f.updated_at)}>
                          edited {fmtRelative(f.updated_at)}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      <div className="flex flex-col items-start gap-1">
                        {f.score !== null ? (
                          <Badge className="tabular-nums" variant="outline">
                            Human {f.score}/10
                          </Badge>
                        ) : (
                          <span className="text-muted-foreground">–</span>
                        )}
                        {f.call.score !== null && (
                          <span className="flex items-center gap-1 text-muted-foreground text-xs">
                            AI <ScoreBadge score={f.call.score} />
                          </span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      <div className="font-medium tabular-nums">
                        #{f.call.id} · {f.call.customer}
                      </div>
                      <div className="text-muted-foreground text-xs">
                        Agent {f.call.agent} · {fmtDate(f.call.date_call)}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
            {data && items.length === 0 && (
              <TableRow>
                <TableCell colSpan={5}>
                  <Empty className="md:py-12">
                    <EmptyHeader>
                      <EmptyMedia variant="icon">
                        <MessageSquareTextIcon />
                      </EmptyMedia>
                      <EmptyTitle>No feedback found</EmptyTitle>
                      <EmptyDescription>
                        {hasFilters
                          ? "Try a different search."
                          : isAdmin
                            ? "Open a call and use its Human feedback tab to write the first note."
                            : "Nobody has written feedback on your calls yet."}
                      </EmptyDescription>
                    </EmptyHeader>
                  </Empty>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
        {total > items.length && (
          <CardFrameFooter className="py-3">
            <p className="text-muted-foreground text-sm tabular-nums">
              Showing the latest {numberFmt.format(items.length)} of {numberFmt.format(total)}. Search to narrow it down.
            </p>
          </CardFrameFooter>
        )}
      </CardFrame>

      <CallSheet
        callId={selectedId}
        initialTab="human"
        onChanged={reload}
        onClose={() => navigate(href("feedback", null, { author, q }))}
      />
    </>
  );
}
