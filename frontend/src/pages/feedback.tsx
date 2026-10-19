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
import { fmtDate, fmtDateTime, fmtRelative, fmtTime } from "@/lib/format";
import { useMe } from "@/lib/me";
import { href, navigate, type Route } from "@/lib/router";
import type { FeedbackList } from "@/lib/types";
import { CallSheet } from "./call-detail";
import { t } from "@/lib/i18n";

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
    const timer = window.setTimeout(() => setQuery({ q: search }), 300);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const params = new URLSearchParams({ limit: String(LIMIT) });
  if (q) params.set("q", q);
  if (author) params.set("author", author);
  const { data, loading, reload } = useApi<FeedbackList>(`/api/feedback?${params}`);

  const items = data?.feedback ?? [];
  const total = data?.total ?? 0;
  const authorItems = [{ label: t("feedback.allAuthors"), value: "all" }, ...(data?.authors ?? []).map((a) => ({ label: a, value: a }))];
  const hasFilters = !!(q || author);
  const callHref = (id: string) => href("feedback", id, { author, q });

  return (
    <>
      <PageHeader
        description={
          isAdmin
            ? t("feedback.descriptionAdmin")
            : t("feedback.descriptionAgent")
        }
        title={t("nav.feedback")}
      />

      <div className="flex flex-wrap items-center gap-2">
        <InputGroup className="w-full sm:w-72">
          <InputGroupInput
            aria-label={t("feedback.search")}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("feedback.searchPlaceholder")}
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
            <SelectTrigger aria-label={t("feedback.author")} className="w-auto">
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
            {t("common.reset")}
          </Button>
        )}
      </div>

      <CardFrame>
        <CardFrameHeader className="flex min-h-14 flex-row items-center py-3">
          <div className="text-muted-foreground text-sm">
            {data ? t("feedback.notes", { count: total }) : t("feedback.loading")}
          </div>
        </CardFrameHeader>
        <Table variant="card">
          <TableHeader>
            <TableRow>
              <TableHead>{t("feedback.added")}</TableHead>
              <TableHead>{t("feedback.author")}</TableHead>
              <TableHead className="min-w-64">{t("feedback.feedback")}</TableHead>
              <TableHead>{t("feedback.score")}</TableHead>
              <TableHead>{t("feedback.call")}</TableHead>
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
                          {t("feedback.edited", { time: fmtRelative(f.updated_at) })}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      <div className="flex flex-col items-start gap-1">
                        {f.score !== null ? (
                          <Badge className="tabular-nums" variant="outline">
                            {t("feedback.humanScore", { score: f.score })}
                          </Badge>
                        ) : (
                          <span className="text-muted-foreground">–</span>
                        )}
                        {f.call.score !== null && (
                          <span className="flex items-center gap-1 text-muted-foreground text-xs">
                            {t("feedback.ai")} <ScoreBadge score={f.call.score} />
                          </span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      <div className="font-medium tabular-nums">
                        #{f.call.id} · {f.call.customer}
                      </div>
                      <div className="text-muted-foreground text-xs">
                        {t("shell.agentExt", { ext: f.call.agent })} · {fmtDate(f.call.date_call)}
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
                      <EmptyTitle>{t("feedback.noneFound")}</EmptyTitle>
                      <EmptyDescription>
                        {hasFilters
                          ? t("common.tryDifferentSearch")
                          : isAdmin
                            ? t("feedback.emptyAdmin")
                            : t("feedback.emptyAgent")}
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
              {t("feedback.showingLatest", { shown: items.length, total })}
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
