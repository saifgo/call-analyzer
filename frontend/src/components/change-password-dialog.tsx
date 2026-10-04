import { CircleAlertIcon } from "lucide-react";
import * as React from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
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
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Form } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { toastManager } from "@/components/ui/toast";
import { api } from "@/lib/api";

export const MIN_PASSWORD_LENGTH = 8;

/** Change the signed-in account's own password. Other devices are signed out; this one stays signed in. */
export function ChangePasswordDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}): React.ReactElement {
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const next = String(form.get("new_password"));
    if (next !== form.get("repeat_password")) {
      setError("The new passwords don't match");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api("/api/me/password", {
        body: { current_password: form.get("current_password"), new_password: next },
        method: "PUT",
      });
      toastManager.add({ description: "Other devices were signed out.", title: "Password changed", type: "success" });
      onOpenChange(false);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      onOpenChange={(value) => {
        onOpenChange(value);
        if (!value) setError(null);
      }}
      open={open}
    >
      <DialogPopup className="sm:max-w-sm">
        <Form className="contents" onSubmit={onSubmit}>
          <DialogHeader>
            <DialogTitle>Change password</DialogTitle>
            <DialogDescription>You stay signed in here; other devices are signed out.</DialogDescription>
          </DialogHeader>
          <DialogPanel className="flex flex-col gap-4">
            {error && (
              <Alert variant="error">
                <CircleAlertIcon aria-hidden="true" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            <Field>
              <FieldLabel>Current password</FieldLabel>
              <Input autoComplete="current-password" name="current_password" required type="password" />
            </Field>
            <Field>
              <FieldLabel>New password</FieldLabel>
              <Input autoComplete="new-password" minLength={MIN_PASSWORD_LENGTH} name="new_password" required type="password" />
              <FieldDescription>At least {MIN_PASSWORD_LENGTH} characters.</FieldDescription>
            </Field>
            <Field>
              <FieldLabel>Repeat new password</FieldLabel>
              <Input autoComplete="new-password" name="repeat_password" required type="password" />
            </Field>
          </DialogPanel>
          <DialogFooter>
            <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
            <Button loading={saving} type="submit">
              Change password
            </Button>
          </DialogFooter>
        </Form>
      </DialogPopup>
    </Dialog>
  );
}
