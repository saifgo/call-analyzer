// The signed-in account, loaded once. Admins see everything; agent accounts get a read-only view of their own calls.
import * as React from "react";
import { Spinner } from "@/components/ui/spinner";
import { useApi } from "@/lib/api";
import type { Me } from "@/lib/types";

const MeContext = React.createContext<(Me & { isAdmin: boolean }) | null>(null);

export function useMe(): Me & { isAdmin: boolean } {
  const ctx = React.useContext(MeContext);
  if (!ctx) throw new Error("useMe must be used within MeProvider");
  return ctx;
}

export function MeProvider({ children }: { children: React.ReactNode }): React.ReactElement {
  const { data } = useApi<Me>("/api/me");
  const value = React.useMemo(() => (data ? { ...data, isAdmin: data.role === "admin" } : null), [data]);
  if (!value) {
    return (
      <div className="flex min-h-svh items-center justify-center">
        <Spinner className="size-6 text-muted-foreground" />
      </div>
    );
  }
  return <MeContext.Provider value={value}>{children}</MeContext.Provider>;
}

