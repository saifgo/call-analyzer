import type * as React from "react";
import { AppShell } from "@/components/app-shell";
import { Softphone } from "@/components/softphone";
import { AnchoredToastProvider, ToastProvider } from "@/components/ui/toast";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AlertsProvider } from "@/lib/alerts";
import { GoVoiceProvider } from "@/lib/govoice";
import { JobProvider } from "@/lib/jobs";
import { MeProvider, useMe } from "@/lib/me";
import { useRoute } from "@/lib/router";
import { InboundProvider } from "@/lib/inbound";
import { SoftphoneProvider } from "@/lib/softphone";
import { WorkersProvider } from "@/lib/workers";
import { AgentsPage } from "@/pages/agents";
import { BusinessPage } from "@/pages/business";
import { CallsPage } from "@/pages/calls";
import { ContactsPage } from "@/pages/contacts";
import { CrmSetupPage } from "@/pages/crm-setup";
import { DashboardPage } from "@/pages/dashboard";
import { FeedbackPage } from "@/pages/feedback";
import { LeadsPage } from "@/pages/leads";
import { LoginPage } from "@/pages/login";
import { OperationsPage } from "@/pages/operations";
import { PipelinePage } from "@/pages/pipeline";
import { ReportsPage } from "@/pages/reports";
import { SettingsPage } from "@/pages/settings";
import { UsersPage } from "@/pages/users";
import { WallboardPage } from "@/pages/wallboard";
import { t, useT } from "@/lib/i18n";

/** Pages agent accounts can open; the others fall back to the dashboard (the server refuses them anyway). */
const AGENT_PAGES = new Set(["dashboard", "operations", "calls", "feedback", "reports"]);

function Pages() {
  const route = useRoute();
  const { isAdmin } = useMe();
  let page: React.ReactNode;
  let crumb: string | null = null;
  switch (isAdmin || AGENT_PAGES.has(route.page) ? route.page : "dashboard") {
    case "operations":
      page = <OperationsPage route={route} />;
      break;
    case "calls":
      page = <CallsPage route={route} />;
      break;
    case "feedback":
      page = <FeedbackPage route={route} />;
      break;
    case "leads":
      page = <LeadsPage route={route} />;
      break;
    case "contacts":
      page = <ContactsPage route={route} />;
      crumb = route.param ? t("crm.contact") : null;
      break;
    case "crm-setup":
      page = <CrmSetupPage />;
      break;
    case "pipeline":
      page = <PipelinePage />;
      break;
    case "agents":
      page = <AgentsPage />;
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
      page = <DashboardPage route={route} />;
  }
  return (
    <AppShell crumb={crumb} route={route}>
      {page}
    </AppShell>
  );
}

function SignedIn() {
  const { isAdmin } = useMe();
  const route = useRoute();
  // Remount the pages on a language switch so text computed outside useT() updates too; the providers
  // (and a call in progress) stay as they are.
  const { locale } = useT();
  // The wallboard runs on its own (e.g. on a TV): no menu, and no softphone that would take the phone from a desk tab.
  if (isAdmin && route.page === "wallboard") return <WallboardPage key={locale} />;
  return (
    <GoVoiceProvider enabled={isAdmin}>
      <JobProvider enabled={isAdmin}>
        <WorkersProvider enabled={isAdmin}>
          <AlertsProvider enabled={isAdmin}>
            <SoftphoneProvider>
              <InboundProvider>
                <Pages key={locale} />
                <Softphone />
              </InboundProvider>
            </SoftphoneProvider>
          </AlertsProvider>
        </WorkersProvider>
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
