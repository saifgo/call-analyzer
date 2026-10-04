import * as React from "react";
import { cn } from "@/lib/utils";

/** Scrolling log output that sticks to the bottom while new lines arrive, unless the user scrolled up. */
export function JobLog({ lines, className, empty = "No job has run yet." }: { lines: string[]; className?: string; empty?: string }) {
  const ref = React.useRef<HTMLPreElement>(null);
  const stick = React.useRef(true);

  React.useLayoutEffect(() => {
    const el = ref.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [lines]);

  return (
    <pre
      className={cn(
        "max-h-[60vh] min-h-48 overflow-auto whitespace-pre-wrap break-words rounded-xl border bg-muted/48 p-4 font-mono text-xs leading-relaxed",
        !lines.length && "text-muted-foreground",
        className,
      )}
      onScroll={(e) => {
        const el = e.currentTarget;
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
      }}
      ref={ref}
    >
      {lines.length
        ? lines.map((line, i) => (
            <div className={cn(line.startsWith("$ ") && "mt-2 font-medium text-foreground first:mt-0")} key={i}>
              {line || " "}
            </div>
          ))
        : empty}
    </pre>
  );
}
