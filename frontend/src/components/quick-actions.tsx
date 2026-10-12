// The call desk's quick actions: WhatsApp messages sent to the contact in one click (set up in Settings > WhatsApp).
import { CheckIcon, MessageCircleIcon } from "lucide-react";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { Card, CardPanel } from "@/components/ui/card";
import { Select, SelectItem, SelectPopup, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toastManager } from "@/components/ui/toast";
import { api, useApi } from "@/lib/api";
import { fmtTime } from "@/lib/format";
import type { OpCall, WaActions, WaMessage } from "@/lib/types";

export function QuickActions({ op }: { op: OpCall }) {
  const { data: config } = useApi<WaActions>("/api/whatsapp/actions");
  const { data: messages, setData: setMessages } = useApi<WaMessage[]>(`/api/operations/${op.id}/whatsapp`);
  const phones = op.lead?.contact?.phones ?? [];
  const [phone, setPhone] = React.useState(phones[0] ?? "");
  const [sending, setSending] = React.useState<number | null>(null);

  if (!config?.configured || !config.actions.length || !phones.length) return null;

  const send = async (actionId: number, label: string) => {
    setSending(actionId);
    try {
      const res = await api<{ messages: WaMessage[] }>(`/api/operations/${op.id}/whatsapp`, {
        body: { action_id: actionId, phone },
        method: "POST",
      });
      setMessages(res.messages);
      toastManager.add({ title: `"${label}" sent on WhatsApp`, type: "success" });
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: `"${label}" wasn't sent`, type: "error" });
    } finally {
      setSending(null);
    }
  };

  const lastSent = (actionId: number) => messages?.filter((m) => m.action_id === actionId && m.status === "sent").at(-1);
  const phoneItems = phones.map((p) => ({ label: p, value: p }));

  return (
    <Card>
      <CardPanel className="flex flex-col gap-3 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="flex items-center gap-1.5 font-medium text-sm">
            <MessageCircleIcon aria-hidden="true" className="size-4 text-success" />
            Send on WhatsApp
          </span>
          {phones.length > 1 && (
            <Select items={phoneItems} onValueChange={(v) => setPhone(v as string)} value={phone}>
              <SelectTrigger className="w-auto" size="sm">
                <SelectValue />
              </SelectTrigger>
              <SelectPopup>
                {phoneItems.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    <span dir="ltr">{item.label}</span>
                  </SelectItem>
                ))}
              </SelectPopup>
            </Select>
          )}
        </div>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
          {config.actions.map((a) => {
            const sent = lastSent(a.id);
            return (
              <Button
                className="h-auto justify-start py-2 text-start"
                disabled={sending !== null}
                key={a.id}
                loading={sending === a.id}
                onClick={() => send(a.id, a.label)}
                variant="outline"
              >
                {sent && <CheckIcon aria-hidden="true" className="text-success" />}
                <span className="flex min-w-0 flex-col">
                  <span className="truncate" dir="auto">
                    {a.label}
                  </span>
                  {sent && <span className="font-normal text-muted-foreground text-xs">Sent at {fmtTime(sent.sent_at)} · send again</span>}
                </span>
              </Button>
            );
          })}
        </div>
      </CardPanel>
    </Card>
  );
}
