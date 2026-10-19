// Incoming calls: tells the server when the softphone rings, is picked up and ends (see call_analyzer/inbound.py),
// and keeps who's calling for the call card. Picking up opens a desk call for the caller; the desk is told to reload.
import * as React from "react";
import { toastManager } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { type PhoneEvent, useSoftphone } from "@/lib/softphone";
import type { InboundCaller, OpCall } from "@/lib/types";

/** Dispatched on window when the desk should reload (a call came in, or ended). */
export const DESK_REFRESH = "desk:refresh";

export type IncomingCall = {
  /** The softphone's call id (ActiveCall.id). */
  callId: number;
  caller: InboundCaller | null;
  /** The desk call opened when it was picked up. */
  op: OpCall | null;
};

const InboundContext = React.createContext<IncomingCall | null>(null);

/** The incoming call on the phone right now, with who's calling (once looked up). */
export function useIncoming(): IncomingCall | null {
  return React.useContext(InboundContext);
}

export function InboundProvider({ children }: { children: React.ReactNode }): React.ReactElement {
  const sp = useSoftphone();
  const [current, setCurrent] = React.useState<IncomingCall | null>(null);
  // Per call: the server's id for it, and its steps one after the other (so "ended" never overtakes "answered").
  const ids = React.useRef(new Map<number, number>());
  const chains = React.useRef(new Map<number, Promise<void>>());

  React.useEffect(() => {
    const step = (callId: number, run: () => Promise<void>) => {
      const next = (chains.current.get(callId) ?? Promise.resolve()).then(run).catch((err) => console.error(err));
      chains.current.set(callId, next);
    };
    const patch = (callId: number, changes: Partial<IncomingCall>) =>
      setCurrent((c) => (c?.callId === callId ? { ...c, ...changes } : c));

    return sp.subscribe((event: PhoneEvent) => {
      if (event.type === "busy") {
        void api("/api/inbound/busy", { body: { name: event.name, number: event.number }, method: "POST" }).catch(() => {});
        return;
      }
      const call = event.call;
      if (call.direction !== "incoming") return;
      const callId = call.id;
      if (event.type === "incoming") {
        setCurrent({ callId, caller: null, op: null });
        step(callId, async () => {
          const res = await api<{ id: number; caller: InboundCaller }>("/api/inbound", {
            body: { name: call.name, number: call.number },
            method: "POST",
          });
          ids.current.set(callId, res.id);
          patch(callId, { caller: res.caller });
        });
      } else if (event.type === "answered") {
        step(callId, async () => {
          const id = ids.current.get(callId);
          if (!id) return;
          try {
            const res = await api<{ current: OpCall }>(`/api/inbound/${id}/answer`, { method: "POST" });
            patch(callId, { op: res.current });
            window.dispatchEvent(new Event(DESK_REFRESH));
          } catch (err) {
            toastManager.add({ description: (err as Error).message, title: t("inbound.openFailed"), type: "error" });
          }
        });
      } else if (event.type === "ended") {
        const { end } = event;
        step(callId, async () => {
          const id = ids.current.get(callId);
          ids.current.delete(callId);
          chains.current.delete(callId);
          setCurrent((c) => (c?.callId === callId ? null : c));
          if (!id) return;
          await api(`/api/inbound/${id}/end`, {
            body: { answered: end.answered, declined: !end.answered && end.byMe, elsewhere: end.elsewhere },
            method: "POST",
          });
          window.dispatchEvent(new Event(DESK_REFRESH));
        });
      }
    });
  }, [sp.subscribe]);

  return <InboundContext.Provider value={current}>{children}</InboundContext.Provider>;
}
