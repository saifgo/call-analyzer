import type * as React from "react";
import { AppShell } from "@/components/app-shell";
import { AnchoredToastProvider, ToastProvider } from "@/components/ui/toast";
import { TooltipProvider } from "@/components/ui/tooltip";
import { GoVoiceProvider } from "@/lib/govoice";
import { JobProvider } from "@/lib/jobs";
import { MeProvider, useMe } from "@/lib/me";
import { useRoute } from "@/lib/router";
import { BusinessPage } from "@/pages/business";
import { CallsPage } from "@/pages/calls";
import { DashboardPage } from "@/pages/dashboard";
import { FeedbackPage } from "@/pages/feedback";
import { LoginPage } from "@/pages/login";
import { PipelinePage } from "@/pages/pipeline";
import { ReportsPage } from "@/pages/reports";
import { SettingsPage } from "@/pages/settings";
import { UsersPage } from "@/pages/users";

/** Pages agent accounts can open; the others fall back to the dashboard (the server refuses them anyway). */
const AGENT_PAGES = new Set(["dashboard", "calls", "feedback", "reports"]);

function Pages() {
  const route = useRoute();
  const { isAdmin } = useMe();
  let page: React.ReactNode;
  let crumb: string | null = null;
  switch (isAdmin || AGENT_PAGES.has(route.page) ? route.page : "dashboard") {
    case "calls":
      page = <CallsPage route={route} />;
      break;
    case "feedback":
      page = <FeedbackPage route={route} />;
      break;
    case "pipeline":
      page = <PipelinePage />;
      break;
    case "reports":
      page = <ReportsPage route={route} />;
      crumb = route.param?.replace(/\.md$/, "") ?? null;
      break;
    case "business":
      page = <BusinessPage />;
      break;
    case "settings":
      page = <SettingsPage />;
      break;
    case "users":
      page = <UsersPage />;
      break;
    default:
      page = <DashboardPage />;
  }
  return (
    <AppShell crumb={crumb} route={route}>
      {page}
    </AppShell>
  );
}

function SignedIn() {
  const { isAdmin } = useMe();
  return (
    <GoVoiceProvider enabled={isAdmin}>
      <JobProvider enabled={isAdmin}>
        <Pages />
      </JobProvider>
    </GoVoiceProvider>
  );
}

export default function App(): React.ReactElement {
  return (
    <ToastProvider>
      <AnchoredToastProvider>
        <TooltipProvider>
          {location.pathname === "/login" ? (
            <LoginPage />
          ) : (
            <MeProvider>
              <SignedIn />
            </MeProvider>
          )}
        </TooltipProvider>
      </AnchoredToastProvider>
    </ToastProvider>
  );
}
