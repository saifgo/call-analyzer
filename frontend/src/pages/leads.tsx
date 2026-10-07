import { CheckIcon, CopyIcon, ExternalLinkIcon, PhoneOutgoingIcon, RefreshCwIcon, SearchIcon, XIcon } from "lucide-react";
import * as React from "react";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CardFrame, CardFrameFooter, CardFrameHeader } from "@/components/ui/card";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group";
import { Label } from "@/components/ui/label";
import { Select, SelectItem, SelectPopup, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipPopup, TooltipTrigger } from "@/components/ui/tooltip";
import { api, useApi } from "@/lib/api";
import { Bidi } from "@/lib/bidi";
import { fmtDate, fmtDateTime, fmtRelative, numberFmt } from "@/lib/format";
import { href, navigate, type Route } from "@/lib/router";
import type { CrmLead, CrmLeads } from "@/lib/types";

/** Digits only, for matching a search against phone numbers however they are written. */
const digits = (text: string) => text.replace(/\D/g, "");

function CopyNumber({ number }: { number: string }) {
  const [copied, setCopied] = React.useState(false);
  return (
    <Button
      aria-label={`Copy ${number}`}
      onClick={async () => {
        await navigator.clipboard.writeText(number.replace(/\s/g, ""));
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      }}
      size="icon-xs"
      variant="ghost"
    >
      {copied ? <CheckIcon aria-hidden="true" /> : <CopyIcon aria-hidden="true" />}
    </Button>
  );
}

function OurCalls({ lead }: { lead: CrmLead }) {
  const { count, match, last_date } = lead.calls;
  if (!count) return <Badge variant="info">Not called yet</Badge>;
  return (
    <a className="flex flex-col hover:underline" href={href("calls", null, { q: match ?? "" })}>
      <Badge variant="secondary">
        {count} {count === 1 ? "call" : "calls"}
      </Badge>
      {last_date && <span className="text-muted-foreground text-xs">last {fmtDate(last_date)}</span>}
    </a>
  );
}

/** Opportunities still at the "new" stage in Twenty, with their point of contact's number: who to call next. */
export function LeadsPage({ route }: { route: Route }): React.ReactElement {
  const q = route.query.get("q") ?? "";
  const owner = route.query.get("owner") ?? "";
  const uncalled = route.query.get("uncalled") === "1";
  const setQuery = (patch: { q?: string; owner?: string; uncalled?: string }) =>
    navigate(href("leads", null, { owner, q, uncalled: uncalled ? "1" : "", ...patch }), { replace: true });

  const [search, setSearch] = React.useState(q);
  React.useEffect(() => setSearch(q), [q]);
  React.useEffect(() => {
    if (search === q) return;
    const t = window.setTimeout(() => setQuery({ q: search }), 250);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const { data, error, loading, setData } = useApi<CrmLeads>("/api/crm/leads");
  const [refreshing, setRefreshing] = React.useState(false);
  const refresh = async () => {
    setRefreshing(true);
    try {
      setData(await api<CrmLeads>("/api/crm/leads?refresh=1"));
    } finally {
      setRefreshing(false);
    }
  };

  const leads = data?.leads ?? [];
  const owners = [...new Set(leads.map((l) => l.owner).filter((o): o is string => !!o))].sort();
  const ownerItems = [{ label: "All owners", value: "all" }, ...owners.map((o) => ({ label: o, value: o }))];
  const needle = q.trim().toLowerCase();
  const needleDigits = digits(q);
  const shown = leads.filter((l) => {
    if (owner && l.owner !== owner) return false;
    if (uncalled && l.calls.count) return false;
    if (!needle) return true;
    const text = [l.name, l.contact?.name, l.contact?.city, l.company].join(" ").toLowerCase();
    return (
      text.includes(needle) ||
      (needleDigits.length >= 3 && (l.contact?.phones ?? []).some((p) => digits(p).includes(needleDigits)))
    );
  });
  const notCalled = leads.filter((l) => !l.calls.count).length;
  const hasFilters = !!(q || owner || uncalled);

  return (
    <>
      <PageHeader
        actions={
          <Button disabled={refreshing || loading} onClick={refresh} variant="outline">
            <RefreshCwIcon aria-hidden="true" className={refreshing ? "animate-spin" : undefined} />
            Refresh
          </Button>
        }
        description="Opportunities at the New stage in the CRM, newest first, with the number of their point of contact."
        title="Leads to call"
      />

      {error && (
        <Alert variant="error">
          <AlertTitle>Couldn't load the leads</AlertTitle>
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      )}

      {data && !data.configured ? (
        <Empty className="rounded-xl border md:py-16">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <PhoneOutgoingIcon />
            </EmptyMedia>
            <EmptyTitle>The CRM isn't connected</EmptyTitle>
            <EmptyDescription>Add your Twenty API key (CRM_API_KEY) in Settings to list the leads.</EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button render={<a href={href("settings")} />} variant="outline">
              Open Settings
            </Button>
          </EmptyContent>
        </Empty>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <InputGroup className="w-full sm:w-72">
              <InputGroupInput
                aria-label="Search leads"
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search name, number or city"
                type="search"
                value={search}
              />
              <InputGroupAddon>
                <SearchIcon aria-hidden="true" />
              </InputGroupAddon>
            </InputGroup>
            {owners.length > 1 && (
              <Select
                items={ownerItems}
                onValueChange={(v) => setQuery({ owner: v === "all" ? "" : (v as string) })}
                value={owner || "all"}
              >
                <SelectTrigger aria-label="Owner" className="w-auto">
                  <SelectValue />
                </SelectTrigger>
                <SelectPopup>
                  {ownerItems.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectPopup>
              </Select>
            )}
            <Label className="flex items-center gap-2 px-1 font-normal text-sm">
              <Switch checked={uncalled} onCheckedChange={(on) => setQuery({ uncalled: on ? "1" : "" })} />
              Not called yet
            </Label>
            {hasFilters && (
              <Button onClick={() => navigate(href("leads"), { replace: true })} variant="ghost">
                <XIcon aria-hidden="true" />
                Reset
              </Button>
            )}
          </div>

          <CardFrame>
            <CardFrameHeader className="flex min-h-14 flex-row items-center py-3">
              <div className="text-muted-foreground text-sm">
                {data
                  ? `${numberFmt.format(shown.length)} of ${numberFmt.format(leads.length)} new ${leads.length === 1 ? "lead" : "leads"} · ${numberFmt.format(notCalled)} not called yet`
                  : "Loading leads from the CRM…"}
              </div>
            </CardFrameHeader>
            <Table variant="card">
              <TableHeader>
                <TableRow>
                  <TableHead className="min-w-56">Lead</TableHead>
                  <TableHead>Number</TableHead>
                  <TableHead>Owner</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead>Our calls</TableHead>
                  <TableHead className="w-10">
                    <span className="sr-only">Open in CRM</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {!data && loading
                  ? Array.from({ length: 8 }, (_, i) => (
                      <TableRow key={i}>
                        <TableCell colSpan={6}>
                          <Skeleton className="h-5 w-full" />
                        </TableCell>
                      </TableRow>
                    ))
                  : shown.map((lead) => (
                      <TableRow className="align-top" key={lead.id}>
                        <TableCell className="whitespace-normal">
                          <Bidi className="font-medium" text={lead.contact?.name ?? "No point of contact"} />
                          <Bidi className="text-muted-foreground text-xs" text={lead.name} />
                          {lead.contact?.city && <div className="text-muted-foreground text-xs">{lead.contact.city}</div>}
                        </TableCell>
                        <TableCell className="whitespace-nowrap">
                          {lead.contact?.phones.length ? (
                            <div className="flex flex-col gap-0.5">
                              {lead.contact.phones.map((phone) => (
                                <span className="flex items-center gap-1" key={phone}>
                                  <a
                                    className="font-medium tabular-nums hover:underline"
                                    dir="ltr"
                                    href={`tel:${phone.replace(/\s/g, "")}`}
                                  >
                                    {phone}
                                  </a>
                                  <CopyNumber number={phone} />
                                </span>
                              ))}
                            </div>
                          ) : (
                            <span className="text-muted-foreground">No number</span>
                          )}
                        </TableCell>
                        <TableCell className="whitespace-nowrap">{lead.owner ?? "–"}</TableCell>
                        <TableCell className="whitespace-nowrap">
                          {lead.created_at ? (
                            <Tooltip>
                              <TooltipTrigger render={<span />}>{fmtRelative(lead.created_at)}</TooltipTrigger>
                              <TooltipPopup>{fmtDateTime(lead.created_at)}</TooltipPopup>
                            </Tooltip>
                          ) : (
                            "–"
                          )}
                        </TableCell>
                        <TableCell className="whitespace-nowrap">
                          <OurCalls lead={lead} />
                        </TableCell>
                        <TableCell>
                          <Button
                            aria-label="Open in CRM"
                            render={<a href={lead.url} rel="noreferrer" target="_blank" />}
                            size="icon-sm"
                            variant="ghost"
                          >
                            <ExternalLinkIcon aria-hidden="true" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                {data && shown.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={6}>
                      <Empty className="md:py-12">
                        <EmptyHeader>
                          <EmptyMedia variant="icon">
                            <PhoneOutgoingIcon />
                          </EmptyMedia>
                          <EmptyTitle>{hasFilters ? "No lead matches" : "No new leads"}</EmptyTitle>
                          <EmptyDescription>
                            {hasFilters
                              ? "Try a different search or filter."
                              : "Every opportunity in the CRM has moved past the New stage."}
                          </EmptyDescription>
                        </EmptyHeader>
                      </Empty>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
            {data?.truncated && (
              <CardFrameFooter className="py-3">
                <p className="text-muted-foreground text-sm">
                  Showing the newest {numberFmt.format(leads.length)} new leads; the CRM has more.
                </p>
              </CardFrameFooter>
            )}
          </CardFrame>
        </>
      )}
    </>
  );
}
