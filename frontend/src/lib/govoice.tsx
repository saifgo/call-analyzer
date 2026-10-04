// GoVoice sign-in: when the saved GoVoice session is missing or expired, ask the user to log in to GoVoice
// in a new tab. The server captures the session from that login (see web/govoice_login.py) and saves it.
import { ExternalLinkIcon, RefreshCwIcon } from "lucide-react";
import * as React from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogPanel,
  DialogPopup,
  DialogTitle,
} from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";
import { toastManager } from "@/components/ui/toast";
import { api } from "@/lib/api";
import type { GoVoiceStatus } from "@/lib/types";

const LOGIN_URL = "/govoice-login/";

type GoVoiceContextValue = {
  status: GoVoiceStatus | null;
  /** Re-test the saved session against GoVoice. */
  refresh: () => Promise<GoVoiceStatus | null>;
  /** Show the login dialog; `then` runs once GoVoice is connected (e.g. retry a job). */
  promptLogin: (reason?: string, then?: () => void) => void;
  /** True when GoVoice is usable (or unreachable, which isn't a login problem); otherwise prompts to log in. */
  ensureConnected: (then?: () => void) => Promise<boolean>;
};

const GoVoiceContext = React.createContext<GoVoiceContextValue | null>(null);

export function useGoVoice(): GoVoiceContextValue {
  const ctx = React.useContext(GoVoiceContext);
  if (!ctx) throw new Error("useGoVoice must be used within GoVoiceProvider");
  return ctx;
}

/** `enabled={false}` for agent accounts: they can't use GoVoice, so nothing is fetched. */
export function GoVoiceProvider({
  children,
  enabled = true,
}: {
  children: React.ReactNode;
  enabled?: boolean;
}): React.ReactElement {
  const [status, setStatus] = React.useState<GoVoiceStatus | null>(null);
  const [open, setOpen] = React.useState(false);
  const [reason, setReason] = React.useState("");
  const [waiting, setWaiting] = React.useState(false);
  const [checking, setChecking] = React.useState(false);
  const [resumes, setResumes] = React.useState(false);
  const pending = React.useRef<(() => void) | undefined>(undefined);
  const popup = React.useRef<Window | null>(null);

  const fetchStatus = React.useCallback(async (refresh: boolean) => {
    try {
      const next = await api<GoVoiceStatus>(`/api/govoice/status${refresh ? "?refresh=1" : ""}`);
      setStatus(next);
      return next;
    } catch {
      return null;
    }
  }, []);

  React.useEffect(() => {
    if (enabled) fetchStatus(false);
  }, [fetchStatus, enabled]);

  const connected = React.useCallback((next: GoVoiceStatus) => {
    setOpen(false);
    setWaiting(false);
    setStatus(next);
    try {
      popup.current?.close();
    } catch {
      // already closed
    }
    toastManager.add({ description: next.message, title: "Connected to GoVoice", type: "success" });
    const then = pending.current;
    pending.current = undefined;
    then?.();
  }, []);

  // While the login tab is open, watch for the sign-in: the tab posts a message when it's done,
  // and the status is polled in case the message can't get through (tab opened by hand, etc.).
  React.useEffect(() => {
    if (!open || !waiting) return;
    let done = false;
    const finish = async () => {
      const next = await fetchStatus(false);
      if (!done && next?.connected) {
        done = true;
        connected(next);
      }
    };
    const onMessage = (e: MessageEvent) => {
      if (e.origin === location.origin && e.data?.type === "govoice-connected") finish();
    };
    window.addEventListener("message", onMessage);
    const timer = window.setInterval(finish, 3000);
    return () => {
      done = true;
      window.removeEventListener("message", onMessage);
      window.clearInterval(timer);
    };
  }, [open, waiting, fetchStatus, connected]);

  const promptLogin = React.useCallback((why?: string, then?: () => void) => {
    pending.current = then;
    setResumes(!!then);
    setReason(why ?? "");
    setWaiting(false);
    setOpen(true);
  }, []);

  const ensureConnected = React.useCallback(
    async (then?: () => void) => {
      const next = await fetchStatus(true);
      if (next?.connected !== false) return true;
      promptLogin(next.message, then);
      return false;
    },
    [fetchStatus, promptLogin],
  );

  const openLogin = () => {
    const w = 520;
    const h = 720;
    const left = window.screenX + Math.max(0, (window.outerWidth - w) / 2);
    const top = window.screenY + Math.max(0, (window.outerHeight - h) / 2);
    popup.current = window.open(LOGIN_URL, "govoice-login", `popup,width=${w},height=${h},left=${left},top=${top}`);
    // Popup blocked: fall back to a normal tab.
    if (!popup.current) popup.current = window.open(LOGIN_URL, "_blank");
    setWaiting(true);
  };

  const checkAgain = async () => {
    setChecking(true);
    const next = await fetchStatus(true);
    setChecking(false);
    if (next?.connected) connected(next);
    else toastManager.add({ description: next?.message, title: "Still not connected", type: "warning" });
  };

  const onOpenChange = (value: boolean) => {
    setOpen(value);
    if (!value) {
      setWaiting(false);
      pending.current = undefined;
    }
  };

  const value = React.useMemo(
    () => ({ ensureConnected, promptLogin, refresh: () => fetchStatus(true), status }),
    [ensureConnected, promptLogin, fetchStatus, status],
  );

  return (
    <GoVoiceContext.Provider value={value}>
      {children}
      <Dialog onOpenChange={onOpenChange} open={open}>
        <DialogPopup className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Log in to GoVoice</DialogTitle>
            <DialogDescription>
              {reason ? `${reason}. ` : ""}Sign in to your GoVoice account in the tab that opens; Call Analyzer saves the
              session automatically{resumes ? " and continues where you left off" : ""}.
            </DialogDescription>
          </DialogHeader>
          <DialogPanel>
            {waiting ? (
              <div className="flex items-center gap-3 rounded-lg border bg-muted/50 p-3 text-sm">
                <Spinner className="size-4 shrink-0" />
                <span>
                  Waiting for you to sign in to GoVoice… Tab didn't open?{" "}
                  <a className="underline underline-offset-2" href={LOGIN_URL} rel="noopener" target="_blank">
                    Open the login page
                  </a>
                  .
                </span>
              </div>
            ) : (
              <p className="text-muted-foreground text-sm">
                You can also paste a cookie copied from your browser in Settings → <code>GOVOICE_COOKIE</code>.
              </p>
            )}
          </DialogPanel>
          <DialogFooter>
            <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
            <Button loading={checking} onClick={checkAgain} variant="outline">
              <RefreshCwIcon aria-hidden="true" />
              Check again
            </Button>
            <Button onClick={openLogin}>
              <ExternalLinkIcon aria-hidden="true" />
              {waiting ? "Open again" : "Open GoVoice login"}
            </Button>
          </DialogFooter>
        </DialogPopup>
      </Dialog>
    </GoVoiceContext.Provider>
  );
}
