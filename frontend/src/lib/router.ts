// Tiny hash router: "#calls/123?agent=101" -> { page: "calls", param: "123", query: {agent: "101"} }.
import { useSyncExternalStore } from "react";

export type Route = { page: string; param: string | null; query: URLSearchParams };

function subscribe(onChange: () => void) {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

export function parseHash(hash: string): Route {
  const [path, search = ""] = hash.replace(/^#/, "").split("?");
  const [page, ...rest] = path.split("/");
  return {
    page: page || "dashboard",
    param: rest.length ? decodeURIComponent(rest.join("/")) : null,
    query: new URLSearchParams(search),
  };
}

export function useHash(): string {
  return useSyncExternalStore(subscribe, () => location.hash);
}

export function useRoute(): Route {
  return parseHash(useHash());
}

export function href(page: string, param?: string | null, query?: Record<string, string>): string {
  const q = query ? new URLSearchParams(Object.entries(query).filter(([, v]) => v)).toString() : "";
  return `#${page}${param ? `/${encodeURIComponent(param)}` : ""}${q ? `?${q}` : ""}`;
}

export function navigate(to: string, { replace = false } = {}): void {
  if (replace) {
    history.replaceState(null, "", to);
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  } else {
    location.hash = to;
  }
}
