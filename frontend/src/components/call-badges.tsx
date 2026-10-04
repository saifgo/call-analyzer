import type * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipPopup, TooltipTrigger } from "@/components/ui/tooltip";
import { humanize } from "@/lib/format";
import type { CallSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

export function scoreVariant(score: number): "success" | "warning" | "error" {
  return score >= 7 ? "success" : score >= 5 ? "warning" : "error";
}

export function ScoreBadge({ score, size }: { score: number | null | undefined; size?: "sm" | "lg" }) {
  if (score === null || score === undefined) return <span className="text-muted-foreground">–</span>;
  return (
    <Badge className="tabular-nums" size={size} variant={scoreVariant(score)}>
      {score}/10
    </Badge>
  );
}

const STATUS: Record<string, { label: string; dot: string }> = {
  new: { dot: "bg-muted-foreground/48", label: "Not downloaded" },
  downloaded: { dot: "bg-muted-foreground", label: "Downloaded" },
  transcribed: { dot: "bg-info", label: "Transcribed" },
  analyzed: { dot: "bg-success", label: "Analyzed" },
  stale: { dot: "bg-warning", label: "Needs re-analysis" },
};

function Dot({ className }: { className: string }) {
  return <span aria-hidden="true" className={cn("size-1.5 rounded-full", className)} />;
}

export function StatusBadge({ call }: { call: Pick<CallSummary, "status" | "error"> }): React.ReactElement {
  if (call.error) {
    return (
      <Tooltip>
        <TooltipTrigger render={<Badge variant="outline" />}>
          <Dot className="bg-destructive" />
          Error
        </TooltipTrigger>
        <TooltipPopup className="max-w-xs">{call.error}</TooltipPopup>
      </Tooltip>
    );
  }
  const s = STATUS[call.status] ?? { dot: "bg-muted-foreground", label: call.status };
  return (
    <Badge variant="outline">
      <Dot className={s.dot} />
      {s.label}
    </Badge>
  );
}

const OUTCOME_VARIANT: Record<string, "success" | "info" | "error" | "secondary"> = {
  appointment_or_next_step: "success",
  callback_requested: "info",
  not_interested: "error",
  sale: "success",
};

export function OutcomeBadge({ outcome }: { outcome: string | null | undefined }) {
  if (!outcome) return <span className="text-muted-foreground">–</span>;
  return <Badge variant={OUTCOME_VARIANT[outcome] ?? "secondary"}>{humanize(outcome)}</Badge>;
}

export const OUTCOME_COLOR: Record<string, string> = {
  appointment_or_next_step: "bg-success",
  callback_requested: "bg-info",
  not_interested: "bg-destructive",
  sale: "bg-success",
};
