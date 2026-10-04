import { InfoIcon } from "lucide-react";
import * as React from "react";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardFooter, CardPanel } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { toastManager } from "@/components/ui/toast";
import { api, useApi } from "@/lib/api";
import { textDir } from "@/lib/bidi";

export function BusinessPage(): React.ReactElement {
  const { data } = useApi<{ text: string }>("/api/business");
  const [original, setOriginal] = React.useState<string | null>(null);
  const [text, setText] = React.useState("");
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    if (data && original === null) {
      setOriginal(data.text);
      setText(data.text);
    }
  }, [data, original]);

  const dirty = original !== null && text !== original;

  const save = async () => {
    setSaving(true);
    try {
      await api("/api/business", { body: { text }, method: "PUT" });
      setOriginal(text);
      toastManager.add({ title: "Business context saved", type: "success" });
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: "Couldn't save", type: "error" });
    } finally {
      setSaving(false);
    }
  };

  // Ctrl/Cmd+S saves.
  const onKeyDown = (e: React.KeyboardEvent) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "s") {
      e.preventDefault();
      if (dirty) save();
    }
  };

  return (
    <>
      <PageHeader
        description="What you sell, your ideal call, common objections and who is on which extension. Analysis judges every call against this."
        title="Business context"
      />
      <Alert variant="info">
        <InfoIcon aria-hidden="true" />
        <AlertDescription>
          After changing it, re-analyze calls (Pipeline → Analyze with “Redo”) so existing feedback is updated.
        </AlertDescription>
      </Alert>
      <Card>
        <CardPanel className="pt-6">
          {original === null ? (
            <Skeleton className="h-[60vh] w-full rounded-lg" />
          ) : (
            <Textarea
              aria-label="Business context (Markdown)"
              className="min-h-[60vh] font-mono text-sm leading-relaxed"
              dir={textDir(text)}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={onKeyDown}
              value={text}
            />
          )}
        </CardPanel>
        <CardFooter className="justify-end gap-2">
          {dirty && (
            <>
              <Badge className="me-auto" variant="warning">
                Unsaved changes
              </Badge>
              <Button onClick={() => setText(original ?? "")} variant="ghost">
                Discard
              </Button>
            </>
          )}
          <Button disabled={!dirty} loading={saving} onClick={save}>
            Save
          </Button>
        </CardFooter>
      </Card>
    </>
  );
}
