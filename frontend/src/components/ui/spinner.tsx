import { Loader2Icon } from "lucide-react";
import type React from "react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";

export function Spinner({
  className,
  ...props
}: React.ComponentProps<typeof Loader2Icon>): React.ReactElement {
  return (
    <Loader2Icon
      aria-label={t("ui.loading")}
      className={cn("animate-spin", className)}
      role="status"
      {...props}
    />
  );
}
