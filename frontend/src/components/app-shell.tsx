import {
  BriefcaseBusinessIcon,
  ChevronsUpDownIcon,
  FileTextIcon,
  KeyRoundIcon,
  LayoutDashboardIcon,
  LogOutIcon,
  MonitorIcon,
  MoonIcon,
  PhoneIcon,
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
import { api } from "@/lib/api";
import { useGoVoice } from "@/lib/govoice";
import { fmtDateTime, fmtRelative } from "@/lib/format";
import { STEP_LABELS, useJob } from "@/lib/jobs";
import { useMe } from "@/lib/me";
import { href, type Route } from "@/lib/router";
import { type Theme, useTheme } from "@/lib/theme";

const NAV = [
  {
    items: [
      { icon: LayoutDashboardIcon, label: "Dashboard", page: "dashboard" },
      { icon: PhoneIcon, label: "Calls", page: "calls" },
      { icon: FileTextIcon, label: "Reports", page: "reports" },
    ],
    label: "Coaching",
  },
  {
    adminOnly: true,
    items: [
      { icon: WorkflowIcon, label: "Pipeline", page: "pipeline" },
      { icon: BriefcaseBusinessIcon, label: "Business context", page: "business" },
      { icon: UsersIcon, label: "Users", page: "users" },
      { icon: Settings2Icon, label: "Settings", page: "settings" },
    ],
    label: "Workspace",
  },
];

export const PAGE_TITLES: Record<string, string> = Object.fromEntries(
  NAV.flatMap((g) => g.items.map((i) => [i.page, i.label])),
);
const ADMIN_PAGES = new Set(NAV.filter((g) => g.adminOnly).flatMap((g) => g.items.map((i) => i.page)));

function NavLinks({ route }: { route: Route }) {
  const { state } = useJob();
  const { isAdmin } = useMe();
  const { isMobile, setOpenMobile } = useSidebar();
  return NAV.filter((group) => isAdmin || !group.adminOnly).map((group) => (
    <SidebarGroup key={group.label}>
      <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          {group.items.map((item) => (
            <SidebarMenuItem key={item.page}>
              <SidebarMenuButton
                isActive={route.page === item.page}
                onClick={() => isMobile && setOpenMobile(false)}
                render={<a href={href(item.page)} />}
                tooltip={item.label}
              >
                <item.icon aria-hidden="true" />
                <span>{item.label}</span>
              </SidebarMenuButton>
              {item.page === "pipeline" && state?.running && (
                <SidebarMenuBadge>
                  <Spinner className="size-3.5" />
                </SidebarMenuBadge>
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
  const [passwordOpen, setPasswordOpen] = React.useState(false);
  const name = me.display_name || me.user;
  const subtitle = me.isAdmin ? "Admin" : me.agents.length ? `Agent ${me.agents.join(", ")}` : "Agent";
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
          <div className="grid flex-1 text-left text-sm leading-tight">
            <span className="truncate font-medium text-sidebar-accent-foreground">{name}</span>
            <span className="truncate text-xs">{subtitle}</span>
          </div>
          <ChevronsUpDownIcon aria-hidden="true" className="ms-auto" />
        </MenuTrigger>
        <MenuPopup align="start" className="w-(--anchor-width) min-w-60" side="top">
          <MenuGroup>
            <MenuGroupLabel>Appearance</MenuGroupLabel>
            <MenuRadioGroup onValueChange={(v) => setTheme(v as Theme)} value={theme}>
              <MenuRadioItem value="light">
                <span className="flex items-center gap-2">
                  <SunIcon aria-hidden="true" />
                  Light
                </span>
              </MenuRadioItem>
              <MenuRadioItem value="dark">
                <span className="flex items-center gap-2">
                  <MoonIcon aria-hidden="true" />
                  Dark
                </span>
              </MenuRadioItem>
              <MenuRadioItem value="system">
                <span className="flex items-center gap-2">
                  <MonitorIcon aria-hidden="true" />
                  System
                </span>
              </MenuRadioItem>
            </MenuRadioGroup>
          </MenuGroup>
          <MenuSeparator />
          <MenuItem onClick={() => setPasswordOpen(true)}>
            <KeyRoundIcon aria-hidden="true" />
            Change password
          </MenuItem>
          <MenuItem onClick={signOut}>
            <LogOutIcon aria-hidden="true" />
            Sign out
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
  if (status?.connected !== false) return null;
  return (
    <Button onClick={() => promptLogin(status.message)} size="sm" variant="outline">
      <span aria-hidden="true" className="size-2 rounded-full bg-destructive" />
      Log in to GoVoice
    </Button>
  );
}

/** "check" -> "Setup check"; drops the argument summary after the double space. */
function jobTitle(label: string | undefined) {
  const name = (label ?? "").split("  (")[0];
  return STEP_LABELS[name] ?? name;
}

function jobResult(code: number | null | undefined) {
  if (code === 0) return { label: "Succeeded", variant: "success" as const };
  if (code === -1) return { label: "Stopped", variant: "warning" as const };
  return { label: "Failed", variant: "error" as const };
}

/** Header button for the current or last job; opens the log drawer. */
function JobStatus({ onOpen }: { onOpen: () => void }) {
  const { state, lines } = useJob();
  if (!state?.started_at) return null;
  if (state.running) {
    return (
      <Tooltip>
        <TooltipTrigger render={<Button onClick={onOpen} size="sm" variant="outline" />}>
          <Spinner />
          <span className="max-w-48 truncate">{jobTitle(state.label)}</span>
        </TooltipTrigger>
        <TooltipPopup className="max-w-sm font-mono text-xs">{lines.at(-1) || "Starting…"}</TooltipPopup>
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
      {ok ? "Last job finished" : state.exit_code === -1 ? "Last job stopped" : "Last job failed"}
    </Badge>
  );
}

/** Live worker log of the current or last job, available from every page. */
function JobDrawer({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { state, lines, stop } = useJob();
  const running = !!state?.running;
  const result = jobResult(state?.exit_code);
  return (
    <Sheet onOpenChange={onOpenChange} open={open}>
      <SheetPopup className="h-full max-w-2xl" side="right" variant="inset">
        <SheetHeader className="pe-12">
          <div className="flex items-center gap-2">
            {running && <Spinner className="size-4" />}
            <SheetTitle className="truncate text-lg">{jobTitle(state?.label) || "Job log"}</SheetTitle>
            {state?.started_at &&
              (running ? <Badge variant="info">Running</Badge> : <Badge variant={result.variant}>{result.label}</Badge>)}
          </div>
          <SheetDescription>
            {running
              ? `Running since ${fmtDateTime(state?.started_at)}`
              : state?.finished_at
                ? `Finished ${fmtRelative(state.finished_at)}`
                : "Output of the current or last job appears here."}
          </SheetDescription>
        </SheetHeader>
        <div className="flex min-h-0 flex-1 flex-col px-6 pb-6">
          <JobLog className="max-h-none flex-1" lines={lines} />
        </div>
        <SheetFooter>
          {running && (
            <Button className="sm:me-auto" onClick={stop} variant="destructive-outline">
              <SquareIcon aria-hidden="true" />
              Stop
            </Button>
          )}
          <Button onClick={() => onOpenChange(false)} render={<a href={href("pipeline")} />} variant="outline">
            <WorkflowIcon aria-hidden="true" />
            Open pipeline
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
  const title = (isAdmin || !ADMIN_PAGES.has(route.page) ? PAGE_TITLES[route.page] : null) ?? "Dashboard";
  const [jobOpen, setJobOpen] = React.useState(false);
  return (
    <SidebarProvider>
      <Sidebar collapsible="icon" variant="inset">
        <SidebarHeader>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton render={<a href={href("dashboard")} />} size="lg">
                <img alt="" className="size-8 rounded-lg" src="/static/favicon.svg" />
                <div className="grid flex-1 text-left text-sm leading-tight">
                  <span className="truncate font-semibold text-sidebar-accent-foreground">Call Analyzer</span>
                  <span className="truncate text-xs">Sales call coaching</span>
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
