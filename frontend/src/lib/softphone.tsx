// Browser softphone: registers the account's GoVoice extension over WebRTC (GoVoice is Asterisk; JsSIP talks SIP
// over its WebSocket) so agents make and take calls in the app. The server only hands out the SIP sign-in
// (see call_analyzer/softphone.py). Only one tab registers at a time; the others wait for it to close.
import * as JsSIP from "jssip";
import type { EndEvent, RTCSession } from "jssip/lib/RTCSession";
import type { RTCSessionEvent } from "jssip/lib/UA";
import * as React from "react";
import { toastManager } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { type AudioSettings, CallAudio, loadAudioSettings, preloadCallAudio, saveAudioSettings } from "@/lib/call-audio";

export type SoftphoneConfig =
  | {
      enabled: true;
      ws_url: string;
      domain: string;
      uri: string;
      sip_user: string;
      password: string;
      /** GoVoice's access token for the account: it only puts calls through that carry it (X-Custom-Header). */
      access_token: string;
      extension: string;
      display_name: string;
      ice_servers: RTCIceServer[];
    }
  | { enabled: false; reason: string };

/** off: no extension / not started; elsewhere: another tab has the phone. */
export type PhoneStatus = "off" | "unsupported" | "elsewhere" | "connecting" | "registered" | "failed";

export type ActiveCall = {
  direction: "incoming" | "outgoing";
  number: string;
  name: string;
  /** ringing: incoming, not answered yet; calling: outgoing, not answered yet. */
  state: "ringing" | "calling" | "active";
  answeredAt: number | null;
  muted: boolean;
  held: boolean;
};

export type CallEnd = { answered: boolean; cause: string; seconds: number };
export type CallHandlers = { onAnswered?: () => void; onEnded?: (end: CallEnd) => void };

type SoftphoneContextValue = {
  config: SoftphoneConfig | null;
  status: PhoneStatus;
  /** Why registering failed (wrong password, GoVoice unreachable...). */
  error: string;
  /** Registered and free: call() will dial. */
  ready: boolean;
  active: ActiveCall | null;
  call: (number: string, handlers?: CallHandlers) => boolean;
  answer: () => void;
  hangup: () => void;
  toggleMute: () => void;
  toggleHold: () => void;
  sendDtmf: (tone: string) => void;
  /** Noise reduction settings (this browser), applied live to the current call. */
  audio: AudioSettings;
  setAudio: (patch: Partial<AudioSettings>) => void;
  /** The current call's audio chain (level meter), null when there's no call. */
  callAudio: CallAudio | null;
};

const SoftphoneContext = React.createContext<SoftphoneContextValue | null>(null);
const LOCK = "call-analyzer-softphone";
// The microphone, WebRTC and tab locks only work over HTTPS (or on localhost).
const SUPPORTED = window.isSecureContext && !!navigator.locks && !!window.RTCPeerConnection;

export function useSoftphone(): SoftphoneContextValue {
  const ctx = React.useContext(SoftphoneContext);
  if (!ctx) throw new Error("useSoftphone must be used within SoftphoneProvider");
  return ctx;
}

/** What to send GoVoice: local Tunisian numbers are dialed with their 8 digits, other countries with 00. */
export function dialable(number: string): string {
  const cleaned = number.replace(/[^\d+*#]/g, "");
  if (/^(\+|00)216\d{8}$/.test(cleaned)) return cleaned.slice(-8);
  return cleaned.replace(/^\+/, "00");
}

/** n random lowercase letters and digits. */
function randomToken(n: number): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(n)), (b) => (b % 36).toString(36)).join("");
}

/** A soft two-tone ring through WebAudio (no sound file to ship); returns stop(). */
function startRingtone(): () => void {
  let ctx: AudioContext;
  try {
    ctx = new AudioContext();
  } catch {
    return () => {};
  }
  const ring = () => {
    const t = ctx.currentTime;
    for (const [freq, start] of [
      [440, 0],
      [480, 0],
    ] as const) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0, t + start);
      gain.gain.linearRampToValueAtTime(0.08, t + start + 0.05);
      gain.gain.setValueAtTime(0.08, t + start + 1.2);
      gain.gain.linearRampToValueAtTime(0, t + start + 1.3);
      osc.connect(gain).connect(ctx.destination);
      osc.start(t + start);
      osc.stop(t + start + 1.35);
    }
  };
  ring();
  const timer = window.setInterval(ring, 3000);
  return () => {
    window.clearInterval(timer);
    void ctx.close();
  };
}

function endCause(e: EndEvent): string {
  switch (e.cause) {
    case JsSIP.C.causes.BUSY:
      return "The line is busy";
    case JsSIP.C.causes.REJECTED:
      return "The call was declined";
    case JsSIP.C.causes.UNAVAILABLE:
    case JsSIP.C.causes.NOT_FOUND:
      return "The number can't be reached";
    case JsSIP.C.causes.NO_ANSWER:
      return "No answer";
    case JsSIP.C.causes.USER_DENIED_MEDIA_ACCESS:
      return "The browser isn't allowed to use the microphone";
    case JsSIP.C.causes.CONNECTION_ERROR:
    case JsSIP.C.causes.REQUEST_TIMEOUT:
      return "Lost the connection to GoVoice";
    default:
      return e.cause;
  }
}

export function SoftphoneProvider({ children }: { children: React.ReactNode }): React.ReactElement {
  const [config, setConfig] = React.useState<SoftphoneConfig | null>(null);
  const [status, setStatus] = React.useState<PhoneStatus>("off");
  const [error, setError] = React.useState("");
  const [active, setActive] = React.useState<ActiveCall | null>(null);
  const ua = React.useRef<JsSIP.UA | null>(null);
  const session = React.useRef<RTCSession | null>(null);
  const handlers = React.useRef<CallHandlers>({});
  const audio = React.useRef<HTMLAudioElement | null>(null);
  const stopRing = React.useRef<(() => void) | null>(null);
  const [audioSettings, setAudioSettings] = React.useState(loadAudioSettings);
  const audioSettingsRef = React.useRef(audioSettings);
  // The microphone of the call being set up or on: opened on dial / answer, closed when the call ends.
  const callAudio = React.useRef<CallAudio | null>(null);
  const [liveAudio, setLiveAudio] = React.useState<CallAudio | null>(null);
  const [opening, setOpening] = React.useState(false);
  const openingRef = React.useRef(false);

  const setAudio = React.useCallback((patch: Partial<AudioSettings>) => {
    const next = { ...audioSettingsRef.current, ...patch };
    audioSettingsRef.current = next;
    setAudioSettings(next);
    saveAudioSettings(next);
    void callAudio.current?.apply(next);
  }, []);

  const setCallAudio = React.useCallback((next: CallAudio | null) => {
    if (callAudio.current !== next) callAudio.current?.close();
    callAudio.current = next;
    setLiveAudio(next);
  }, []);

  React.useEffect(() => {
    api<SoftphoneConfig>("/api/softphone")
      .then(setConfig)
      .catch(() => setConfig({ enabled: false, reason: "Couldn't load the softphone settings" }));
  }, []);

  const update = React.useCallback((patch: Partial<ActiveCall>) => {
    setActive((current) => (current ? { ...current, ...patch } : current));
  }, []);

  /** Wire a new call (either direction): its audio, its state, and the clean-up when it ends. */
  const track = React.useCallback(
    (s: RTCSession, call: ActiveCall) => {
      session.current = s;
      setActive(call);
      const playRemote = (pc: RTCPeerConnection) => {
        pc.addEventListener("track", (e) => {
          const stream = e.streams[0];
          if (!audio.current || !stream) return;
          if (callAudio.current) callAudio.current.attachRemote(stream, audio.current);
          else audio.current.srcObject = stream;
        });
      };
      if (s.connection) playRemote(s.connection as unknown as RTCPeerConnection);
      s.on("peerconnection", (e) => playRemote(e.peerconnection as unknown as RTCPeerConnection));
      // JsSIP only sends the INVITE (or the answer) once ICE gathering is complete, which never comes on some PCs
      // (virtual network adapters: WSL, Hyper-V, VPN). Like SIP.js in GoVoice's web phone, stop waiting shortly after
      // the public address (srflx) is known, or after a few seconds anyway. GoVoice is on a public IP.
      let iceTimer: number | undefined;
      s.on("icecandidate", ({ candidate, ready }) => {
        if (candidate.type === "srflx") {
          window.clearTimeout(iceTimer);
          iceTimer = window.setTimeout(ready, 300);
        } else if (iceTimer === undefined) {
          iceTimer = window.setTimeout(ready, 3000);
        }
      });
      s.on("confirmed", () => {
        stopRing.current?.();
        update({ state: "active", answeredAt: Date.now() });
        handlers.current.onAnswered?.();
      });
      s.on("hold", () => update({ held: true }));
      s.on("unhold", () => update({ held: false }));
      s.on("muted", () => update({ muted: true }));
      s.on("unmuted", () => update({ muted: false }));
      const finish = (e: EndEvent) => {
        if (session.current !== s) return;
        stopRing.current?.();
        stopRing.current = null;
        session.current = null;
        setCallAudio(null);
        if (audio.current) {
          audio.current.srcObject = null;
          audio.current.muted = false;
        }
        const answered = !!s.start_time;
        const seconds = answered ? Math.round((Date.now() - s.start_time.getTime()) / 1000) : 0;
        if (!answered && e.originator !== "local" && call.direction === "outgoing") {
          toastManager.add({ description: endCause(e), title: "Call not connected", type: "warning" });
        } else if (!answered && e.originator === "remote" && call.direction === "incoming") {
          toastManager.add({ description: call.name || call.number, title: "Missed call", type: "info" });
        }
        handlers.current.onEnded?.({ answered, cause: e.cause, seconds });
        handlers.current = {};
        setActive(null);
      };
      s.on("ended", finish);
      s.on("failed", finish);
    },
    [setCallAudio, update],
  );

  // Register while this tab holds the lock; another tab gets the phone once this one closes.
  React.useEffect(() => {
    if (!config?.enabled || !SUPPORTED) return;
    const abort = new AbortController();
    let release: (() => void) | undefined;
    let granted = false;
    void navigator.locks.query().then((state) => {
      if (!granted && state.held?.some((l) => l.name === LOCK)) setStatus("elsewhere");
    });
    navigator.locks
      .request(LOCK, { signal: abort.signal }, () => {
        granted = true;
        const phone = new JsSIP.UA({
          authorization_user: config.sip_user,
          // transport=wss like GoVoice's own web phone (SIP.js hackWssInTransport): JsSIP's default ws makes
          // Asterisk look for a plain WebSocket when it sends us calls.
          contact_uri: `sip:${randomToken(8)}@${randomToken(12)}.invalid;transport=wss`,
          display_name: config.display_name,
          password: config.password,
          register: true,
          register_expires: 120,
          session_timers: false,
          sockets: [new JsSIP.WebSocketInterface(config.ws_url)],
          uri: config.uri,
          user_agent: "Call Analyzer",
        });
        phone.on("connecting", () => setStatus("connecting"));
        phone.on("disconnected", () => {
          setStatus("connecting");
          setError("Can't reach GoVoice, retrying…");
        });
        phone.on("registered", () => {
          setStatus("registered");
          setError("");
          preloadCallAudio(audioSettingsRef.current);
        });
        phone.on("unregistered", () => setStatus("connecting"));
        phone.on("registrationFailed", (e) => {
          setStatus("failed");
          setError(
            e.cause === JsSIP.C.causes.AUTHENTICATION_ERROR
              ? `GoVoice refused extension ${config.extension}: check its SIP password in Users`
              : `GoVoice refused to sign in the phone (${e.cause})`,
          );
        });
        phone.on("newRTCSession", (e: RTCSessionEvent) => {
          if (e.originator !== "remote") return;
          if (session.current) {
            e.session.terminate({ status_code: 486, reason_phrase: "Busy Here" });
            return;
          }
          const remote = e.session.remote_identity;
          stopRing.current = startRingtone();
          track(e.session, {
            answeredAt: null,
            direction: "incoming",
            held: false,
            muted: false,
            name: remote.display_name || "",
            number: remote.uri.user,
            state: "ringing",
          });
        });
        phone.start();
        ua.current = phone;
        setStatus("connecting");
        return new Promise<void>((resolve) => {
          release = resolve;
        });
      })
      .catch(() => {}); // aborted while waiting for the lock
    return () => {
      abort.abort();
      session.current?.terminate();
      ua.current?.stop();
      ua.current = null;
      release?.();
      setStatus("off");
    };
  }, [config, track]);

  // Leaving the page drops the call: ask first.
  React.useEffect(() => {
    if (!active) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [active]);

  const pcConfig = React.useMemo(() => ({ iceServers: config?.enabled ? config.ice_servers : [] }), [config]);

  /** Open the microphone (cleaned per the audio settings) for a call; null when the browser refuses it. */
  const openMic = React.useCallback(async (): Promise<CallAudio | null> => {
    try {
      return await CallAudio.open(audioSettingsRef.current);
    } catch (err) {
      const denied = err instanceof DOMException && (err.name === "NotAllowedError" || err.name === "SecurityError");
      toastManager.add({
        description: denied ? "The browser isn't allowed to use the microphone" : `The microphone didn't start (${String(err)})`,
        title: "Call not connected",
        type: "error",
      });
      return null;
    }
  }, []);

  const call = React.useCallback(
    (number: string, callHandlers: CallHandlers = {}) => {
      const target = dialable(number);
      if (!config?.enabled || !ua.current || status !== "registered" || session.current || openingRef.current || !target)
        return false;
      handlers.current = callHandlers;
      openingRef.current = true;
      setOpening(true);
      // The microphone opens first (a moment, or the browser's permission prompt); the call is placed with it.
      void (async () => {
        const mic = await openMic();
        openingRef.current = false;
        setOpening(false);
        const phone = ua.current;
        if (!mic || !phone || session.current) {
          mic?.close();
          const ended = handlers.current.onEnded;
          handlers.current = {};
          ended?.({ answered: false, cause: JsSIP.C.causes.USER_DENIED_MEDIA_ACCESS, seconds: 0 });
          return;
        }
        try {
          const s = phone.call(`sip:${target}@${config.domain}`, {
            extraHeaders: config.access_token ? [`X-Custom-Header: ${config.access_token}`] : [],
            mediaStream: mic.stream,
            pcConfig,
          });
          setCallAudio(mic);
          track(s, {
            answeredAt: null,
            direction: "outgoing",
            held: false,
            muted: false,
            name: "",
            number: target,
            state: "calling",
          });
        } catch (err) {
          mic.close();
          const ended = handlers.current.onEnded;
          handlers.current = {};
          toastManager.add({ description: String(err), title: "Couldn't place the call", type: "error" });
          ended?.({ answered: false, cause: JsSIP.C.causes.INTERNAL_ERROR, seconds: 0 });
        }
      })();
      return true;
    },
    [config, openMic, pcConfig, setCallAudio, status, track],
  );

  const answer = React.useCallback(() => {
    const s = session.current;
    if (!s || openingRef.current) return;
    stopRing.current?.();
    openingRef.current = true;
    setOpening(true);
    void (async () => {
      const mic = await openMic();
      openingRef.current = false;
      setOpening(false);
      if (!mic) {
        s.terminate({ reason_phrase: "Temporarily Unavailable", status_code: 480 });
        return;
      }
      if (session.current !== s || s.isEnded()) {
        mic.close(); // the caller hung up while the microphone was starting
        return;
      }
      setCallAudio(mic);
      s.answer({ mediaStream: mic.stream, pcConfig });
    })();
  }, [openMic, pcConfig, setCallAudio]);

  const shown: PhoneStatus = SUPPORTED ? status : "unsupported";
  const value = React.useMemo<SoftphoneContextValue>(
    () => ({
      active,
      answer,
      audio: audioSettings,
      call,
      callAudio: liveAudio,
      config,
      error,
      hangup: () => session.current?.terminate(),
      ready: status === "registered" && !active && !opening,
      sendDtmf: (tone) =>
        session.current?.sendDTMF(tone, { transportType: JsSIP.C.DTMF_TRANSPORT.RFC2833 }),
      setAudio,
      status: shown,
      toggleHold: () => {
        const s = session.current;
        if (!s?.isEstablished()) return;
        if (s.isOnHold().local) s.unhold();
        else s.hold();
      },
      toggleMute: () => {
        const s = session.current;
        if (!s) return;
        if (s.isMuted().audio) s.unmute({ audio: true });
        else s.mute({ audio: true });
      },
    }),
    [active, answer, audioSettings, call, config, error, liveAudio, opening, setAudio, shown, status],
  );

  return (
    <SoftphoneContext.Provider value={value}>
      {children}
      <audio autoPlay hidden ref={audio} />
    </SoftphoneContext.Provider>
  );
}
