import {
  BriefcaseBusinessIcon,
  ChevronsUpDownIcon,
  FileTextIcon,
  HeadsetIcon,
  KeyRoundIcon,
  LanguagesIcon,
  LayoutDashboardIcon,
  LogOutIcon,
  MessageSquareTextIcon,
  MonitorIcon,
  MonitorSmartphoneIcon,
  MoonIcon,
  PhoneIcon,
  PhoneOutgoingIcon,
  Settings2Icon,
  SunIcon,
  SquareIcon,
  UsersIcon,
  WorkflowIcon,
} from "lucide-react";
import * as React from "react";
import { ChangePasswordDialog } from "@/components/change-password-dialog";
import { JobLog } from "@/components/job-log";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import {
  Menu,
  MenuGroup,
  MenuGroupLabel,
  MenuItem,
  MenuPopup,
  MenuRadioGroup,
  MenuRadioItem,
  MenuSeparator,
  MenuTrigger,
} from "@/components/ui/menu";
import { Separator } from "@/components/ui/separator";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import { Sheet, SheetDescription, SheetFooter, SheetHeader, SheetPopup, SheetTitle } from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";
import { Tooltip, TooltipPopup, TooltipTrigger } from "@/components/ui/tooltip";
import { useAlerts } from "@/lib/alerts";
import { api } from "@/lib/api";
import { useGoVoice } from "@/lib/govoice";
import { fmtDateTime, fmtRelative } from "@/lib/format";
import { STEP_LABELS, useJob } from "@/lib/jobs";
import { useMe } from "@/lib/me";
import { href, type Route } from "@/lib/router";
import { type Theme, useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { liveAgents, stalledSteps, STEP_NAMES, useWorkers, WORKER_STEPS } from "@/lib/workers";
import { joinList, LOCALES, type Locale, labels, t, type TKey, useT } from "@/lib/i18n";

const NAV: { adminOnly?: boolean; items: { icon: typeof PhoneIcon; label: TKey; page: string }[]; label: TKey }[] = [
  {
    items: [{ icon: HeadsetIcon, label: "nav.callDesk", page: "operations" }],
    label: "nav.group.operations",
  },
  {
    items: [
      { icon: LayoutDashboardIcon, label: "nav.dashboard", page: "dashboard" },
      { icon: PhoneIcon, label: "nav.calls", page: "calls" },
      { icon: MessageSquareTextIcon, label: "nav.feedback", page: "feedback" },
      { icon: FileTextIcon, label: "nav.reports", page: "reports" },
    ],
    label: "nav.group.coaching",
  },
  {
    adminOnly: true,
    items: [{ icon: PhoneOutgoingIcon, label: "nav.leads", page: "leads" }],
    label: "nav.group.crm",
  },
  {
    adminOnly: true,
    items: [
      { icon: WorkflowIcon, label: "nav.pipeline", page: "pipeline" },
      { icon: MonitorSmartphoneIcon, label: "nav.agents", page: "agents" },
      { icon: BriefcaseBusinessIcon, label: "nav.business", page: "business" },
      { icon: UsersIcon, label: "nav.users", page: "users" },
      { icon: Settings2Icon, label: "nav.settings", page: "settings" },
    ],
    label: "nav.group.workspace",
  },
];

export const PAGE_TITLES: Record<string, string> = labels(
  Object.fromEntries(NAV.flatMap((g) => g.items.map((i) => [i.page, i.label]))) as Record<string, TKey>,
);
const ADMIN_PAGES = new Set(NAV.filter((g) => g.adminOnly).flatMap((g) => g.items.map((i) => i.page)));

function NavLinks({ route }: { route: Route }) {
  const { state } = useJob();
  const { state: workers } = useWorkers();
  const { isAdmin } = useMe();
  const agentsOnline = workers ? liveAgents(workers.workers).length : 0;
  const { alerts } = useAlerts();
  const critical = alerts?.some((a) => a.level === "critical");
  const { isMobile, setOpenMobile } = useSidebar();
  const { t } = useT();
  return NAV.filter((group) => isAdmin || !group.adminOnly).map((group) => (
    <SidebarGroup key={group.label}>
      <SidebarGroupLabel>{t(group.label)}</SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          {group.items.map((item) => (
            <SidebarMenuItem key={item.page}>
              <SidebarMenuButton
                isActive={route.page === item.page}
                onClick={() => isMobile && setOpenMobile(false)}
                render={<a href={href(item.page)} />}
                tooltip={t(item.label)}
              >
                <item.icon aria-hidden="true" />
                <span>{t(item.label)}</span>
              </SidebarMenuButton>
              {item.page === "pipeline" && state?.running && (
                <SidebarMenuBadge>
                  <Spinner className="size-3.5" />
                </SidebarMenuBadge>
              )}
              {item.page === "operations" && isAdmin && !!alerts?.length && (
                <SidebarMenuBadge
                  aria-label={t("shell.alertsOnDesk", { count: alerts.length })}
                  className={cn(
                    critical
                      ? "bg-destructive/16 text-destructive-foreground peer-hover/menu-button:text-destructive-foreground peer-data-[active=true]/menu-button:text-destructive-foreground"
                      : "bg-warning/16 text-warning-foreground peer-hover/menu-button:text-warning-foreground peer-data-[active=true]/menu-button:text-warning-foreground",
                  )}
                >
                  {alerts.length}
                </SidebarMenuBadge>
              )}
              {item.page === "agents" && agentsOnline > 0 && (
                <SidebarMenuBadge aria-label={t("shell.online", { count: agentsOnline })}>{agentsOnline}</SidebarMenuBadge>
              )}
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  ));
}

function UserMenu() {
  const me = useMe();
  const [theme, setTheme] = useTheme();
  const { t, locale, setLocale } = useT();
  const [passwordOpen, setPasswordOpen] = React.useState(false);
  const name = me.display_name || me.user;
  const subtitle = me.isAdmin
    ? t("shell.admin")
    : me.agents.length
      ? t("shell.agentExt", { ext: me.agents.join(", ") })
      : t("shell.agent");
  const signOut = async () => {
    await api("/api/logout", { method: "POST" });
    location.href = "/login";
  };
  return (
    <>
      <Menu>
        <MenuTrigger render={<SidebarMenuButton className="data-popup-open:bg-sidebar-accent" size="lg" />}>
          <Avatar className="size-8 rounded-lg">
            <AvatarFallback className="rounded-lg">{name.slice(0, 2).toUpperCase()}</AvatarFallback>
          </Avatar>
          <div className="grid flex-1 text-start text-sm leading-tight">
            <span className="truncate font-medium text-sidebar-accent-foreground">{name}</span>
            <span className="truncate text-xs">{subtitle}</span>
          </div>
          <ChevronsUpDownIcon aria-hidden="true" className="ms-auto" />
        </MenuTrigger>
        <MenuPopup align="start" className="w-(--anchor-width) min-w-60" side="top">
          <MenuGroup>
            <MenuGroupLabel>{t("shell.appearance")}</MenuGroupLabel>
            <MenuRadioGroup onValueChange={(v) => setTheme(v as Theme)} value={theme}>
              <MenuRadioItem value="light">
                <span className="flex items-center gap-2">
                  <SunIcon aria-hidden="true" />
                  {t("shell.theme.light")}
                </span>
              </MenuRadioItem>
              <MenuRadioItem value="dark">
                <span className="flex items-center gap-2">
                  <MoonIcon aria-hidden="true" />
                  {t("shell.theme.dark")}
                </span>
              </MenuRadioItem>
              <MenuRadioItem value="system">
                <span className="flex items-center gap-2">
                  <MonitorIcon aria-hidden="true" />
                  {t("shell.theme.system")}
                </span>
              </MenuRadioItem>
            </MenuRadioGroup>
          </MenuGroup>
          <MenuSeparator />
          <MenuGroup>
            <MenuGroupLabel className="flex items-center gap-2">
              <LanguagesIcon aria-hidden="true" className="size-3.5" />
              {t("shell.language")}
            </MenuGroupLabel>
            <MenuRadioGroup onValueChange={(v) => setLocale(v as Locale)} value={locale}>
              {LOCALES.map((l) => (
                <MenuRadioItem key={l.value} value={l.value}>
                  <span dir={l.dir} lang={l.value}>
                    {l.label}
                  </span>
                </MenuRadioItem>
              ))}
            </MenuRadioGroup>
          </MenuGroup>
          <MenuSeparator />
          <MenuItem onClick={() => setPasswordOpen(true)}>
            <KeyRoundIcon aria-hidden="true" />
            {t("shell.changePassword")}
          </MenuItem>
          <MenuItem onClick={signOut}>
            <LogOutIcon aria-hidden="true" />
            {t("shell.signOut")}
          </MenuItem>
        </MenuPopup>
      </Menu>
      <ChangePasswordDialog onOpenChange={setPasswordOpen} open={passwordOpen} />
    </>
  );
}

/** Shown when the saved GoVoice session is missing or expired. */
function GoVoiceAlert() {
  const { status, promptLogin } = useGoVoice();
  const { t } = useT();
  if (status?.connected !== false) return null;
  return (
    <Button onClick={() => promptLogin(status.message)} size="sm" variant="outline">
      <span aria-hidden="true" className="size-2 rounded-full bg-destructive" />
      {t("govoice.logIn")}
    </Button>
  );
}

/** Remote agents: warns when a step waits for an agent that isn't there, otherwise shows how many are online. */
function AgentsAlert() {
  const { state } = useWorkers();
  const { t } = useT();
  if (!state) return null;
  const stalled = stalledSteps(state);
  if (stalled.length) {
    return (
      <Tooltip>
        <TooltipTrigger render={<Button render={<a href={href("agents")} />} size="sm" variant="outline" />}>
          <span aria-hidden="true" className="size-2 rounded-full bg-warning" />
          {t("shell.noAgentOnline")}
        </TooltipTrigger>
        <TooltipPopup className="max-w-xs">
          {t("shell.stalledSteps", { count: stalled.length, steps: joinList(stalled.map((s) => STEP_NAMES[s])) })}
        </TooltipPopup>
      </Tooltip>
    );
  }
  const online = liveAgents(state.workers).length;
  const used = WORKER_STEPS.some((s) => state.runs_on[s] !== "host");
  if (!used || online === 0) return null;
  return (
    <Badge render={<a href={href("agents")} />} variant="success">
      {t("shell.agentsOnline", { count: online })}
    </Badge>
  );
}

/** "check" -> "Setup check"; drops the argument summary after the double space. */
function jobTitle(label: string | undefined) {
  const name = (label ?? "").split("  (")[0];
  return STEP_LABELS[name] ?? name;
}

function jobResult(code: number | null | undefined) {
  if (code === 0) return { label: t("shell.job.succeeded"), variant: "success" as const };
  if (code === -1) return { label: t("shell.job.stopped"), variant: "warning" as const };
  return { label: t("shell.job.failed"), variant: "error" as const };
}

/** Header button for the current or last job; opens the log drawer. */
function JobStatus({ onOpen }: { onOpen: () => void }) {
  const { state, lines } = useJob();
  const { t } = useT();
  if (!state?.started_at) return null;
  if (state.running) {
    return (
      <Tooltip>
        <TooltipTrigger render={<Button onClick={onOpen} size="sm" variant="outline" />}>
          <Spinner />
          <span className="max-w-48 truncate">{jobTitle(state.label)}</span>
        </TooltipTrigger>
        <TooltipPopup className="max-w-sm font-mono text-xs">{lines.at(-1) || t("shell.job.starting")}</TooltipPopup>
      </Tooltip>
    );
  }
  const ok = state.exit_code === 0;
  return (
    <Badge
      className="cursor-pointer"
      render={<button onClick={onOpen} type="button" />}
      variant={jobResult(state.exit_code).variant}
    >
      {ok ? t("shell.job.lastFinished") : state.exit_code === -1 ? t("shell.job.lastStopped") : t("shell.job.lastFailed")}
    </Badge>
  );
}

/** Live worker log of the current or last job, available from every page. */
function JobDrawer({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { state, lines, stop } = useJob();
  const { t, dir } = useT();
  const running = !!state?.running;
  const result = jobResult(state?.exit_code);
  return (
    <Sheet onOpenChange={onOpenChange} open={open}>
      <SheetPopup className="h-full max-w-2xl" side={dir === "rtl" ? "left" : "right"} variant="inset">
        <SheetHeader className="pe-12">
          <div className="flex items-center gap-2">
            {running && <Spinner className="size-4" />}
            <SheetTitle className="truncate text-lg">{jobTitle(state?.label) || t("shell.job.log")}</SheetTitle>
            {state?.started_at &&
              (running ? <Badge variant="info">{t("shell.job.running")}</Badge> : <Badge variant={result.variant}>{result.label}</Badge>)}
          </div>
          <SheetDescription>
            {running
              ? t("shell.job.runningSince", { time: fmtDateTime(state?.started_at) })
              : state?.finished_at
                ? t("shell.job.finishedAgo", { time: fmtRelative(state.finished_at) })
                : t("shell.job.empty")}
          </SheetDescription>
        </SheetHeader>
        <div className="flex min-h-0 flex-1 flex-col px-6 pb-6">
          <JobLog className="max-h-none flex-1" lines={lines} />
        </div>
        <SheetFooter>
          {running && (
            <Button className="sm:me-auto" onClick={stop} variant="destructive-outline">
              <SquareIcon aria-hidden="true" />
              {t("shell.job.stop")}
            </Button>
          )}
          <Button onClick={() => onOpenChange(false)} render={<a href={href("pipeline")} />} variant="outline">
            <WorkflowIcon aria-hidden="true" />
            {t("shell.job.openPipeline")}
          </Button>
        </SheetFooter>
      </SheetPopup>
    </Sheet>
  );
}

export function AppShell({
  route,
  crumb,
  children,
}: {
  route: Route;
  crumb?: string | null;
  children: React.ReactNode;
}): React.ReactElement {
  const { isAdmin } = useMe();
  const { t, dir } = useT();
  const title = (isAdmin || !ADMIN_PAGES.has(route.page) ? PAGE_TITLES[route.page] : null) ?? t("nav.dashboard");
  const [jobOpen, setJobOpen] = React.useState(false);
  return (
    <SidebarProvider>
      <Sidebar collapsible="icon" side={dir === "rtl" ? "right" : "left"} variant="inset">
        <SidebarHeader>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton render={<a href={href("dashboard")} />} size="lg">
                <img alt="" className="size-8 rounded-lg" src="/static/favicon.svg" />
                <div className="grid flex-1 text-start text-sm leading-tight">
                  <span className="truncate font-mono font-medium tracking-tighter text-sidebar-accent-foreground">kalma</span>
                  <span className="truncate text-xs">{t("shell.tagline")}</span>
                </div>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarHeader>
        <SidebarContent>
          <NavLinks route={route} />
        </SidebarContent>
        <SidebarFooter>
          <SidebarMenu>
            <SidebarMenuItem>
              <UserMenu />
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarFooter>
        <SidebarRail />
      </Sidebar>
      <SidebarInset className="min-w-0">
        <header className="sticky top-0 z-10 flex h-14 shrink-0 items-center gap-2 rounded-t-xl border-b bg-background/80 px-4 backdrop-blur-sm">
          <SidebarTrigger className="-ms-1" />
          <Separator className="me-1 h-4" orientation="vertical" />
          <Breadcrumb className="min-w-0 flex-1">
            <BreadcrumbList>
              {crumb ? (
                <>
                  <BreadcrumbItem className="max-sm:hidden">
                    <BreadcrumbLink href={href(route.page)}>{title}</BreadcrumbLink>
                  </BreadcrumbItem>
                  <BreadcrumbSeparator className="max-sm:hidden" />
                  <BreadcrumbItem className="min-w-0">
                    <BreadcrumbPage className="truncate">{crumb}</BreadcrumbPage>
                  </BreadcrumbItem>
                </>
              ) : (
                <BreadcrumbItem>
                  <BreadcrumbPage>{title}</BreadcrumbPage>
                </BreadcrumbItem>
              )}
            </BreadcrumbList>
          </Breadcrumb>
          {isAdmin && (
            <>
              <GoVoiceAlert />
              <AgentsAlert />
              <JobStatus onOpen={() => setJobOpen((o) => !o)} />
            </>
          )}
        </header>
        <div className="flex flex-1 flex-col gap-6 p-4 sm:p-6 lg:p-8">{children}</div>
      </SidebarInset>
      {isAdmin && <JobDrawer onOpenChange={setJobOpen} open={jobOpen} />}
    </SidebarProvider>
  );
}
