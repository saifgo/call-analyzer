import {
  BellIcon,
  BellRingIcon,
  CalendarClockIcon,
  CheckCircle2Icon,
  CoffeeIcon,
  PhoneIncomingIcon,
  PhoneMissedIcon,
  TimerIcon,
  TrendingDownIcon,
} from "lucide-react";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardFrame, CardFrameAction, CardFrameHeader, CardFrameTitle, CardPanel } from "@/components/ui/card";
import { type DeskAlertKind, useAlerts } from "@/lib/alerts";
import { fmtRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";

const ICON: Record<DeskAlertKind, typeof BellIcon> = {
  callback_overdue: CalendarClockIcon,
  contact_rate_drop: TrendingDownIcon,
  idle: CoffeeIcon,
  long_call: TimerIcon,
  missed_call: PhoneIncomingIcon,
  no_answer_streak: PhoneMissedIcon,
};

function useNotificationPermission(): [NotificationPermission | null, () => void] {
  const supported = "Notification" in window;
  const [permission, setPermission] = React.useState(supported ? Notification.permission : null);
  const ask = React.useCallback(() => {
    if (supported) Notification.requestPermission().then(setPermission);
  }, [supported]);
  return [permission, ask];
}

/** The team board's alerts: what needs a supervisor's eye right now (see lib/alerts.tsx). The thresholds are in
 * Settings > Call desk. */
export function DeskAlerts(): React.ReactElement | null {
  const { alerts } = useAlerts();
  const [permission, askPermission] = useNotificationPermission();
  if (!alerts) return null;
  return (
    <CardFrame>
      <CardFrameHeader>
        <CardFrameTitle className="flex items-center gap-2">
          {t("deskAlerts.title")}
          {alerts.length > 0 && <Badge variant="secondary">{alerts.length}</Badge>}
        </CardFrameTitle>
        {permission === "default" && (
          <CardFrameAction>
            <Button onClick={askPermission} size="xs" variant="outline">
              <BellRingIcon aria-hidden="true" />
              {t("deskAlerts.notifyMe")}
            </Button>
          </CardFrameAction>
        )}
      </CardFrameHeader>
      <Card>
        <CardPanel className="p-0">
          {alerts.length === 0 ? (
            <div className="flex items-center gap-2 px-4 py-3 text-muted-foreground text-sm">
              <CheckCircle2Icon aria-hidden="true" className="size-4 text-success" />
              {t("deskAlerts.allClear")}
            </div>
          ) : (
            <ul className="divide-y">
              {alerts.map((a) => {
                const Icon = ICON[a.kind] ?? BellIcon;
                return (
                  <li className="flex items-start gap-3 px-4 py-3" key={a.id}>
                    <Icon
                      aria-hidden="true"
                      className={cn(
                        "mt-0.5 size-4 shrink-0",
                        a.level === "critical" ? "text-destructive-foreground" : "text-warning-foreground",
                      )}
                    />
                    <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <span className="font-medium text-sm">{a.title}</span>
                      <span className="text-muted-foreground text-xs">{a.detail}</span>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1">
                      <Badge variant={a.level === "critical" ? "error" : "warning"}>
                        {a.level === "critical" ? t("deskAlerts.critical") : t("deskAlerts.warning")}
                      </Badge>
                      <span className="text-muted-foreground text-xs">{fmtRelative(a.since)}</span>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </CardPanel>
      </Card>
    </CardFrame>
  );
}
