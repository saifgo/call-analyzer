import { CircleAlertIcon, EyeIcon, EyeOffIcon } from "lucide-react";
import * as React from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardPanel, CardTitle } from "@/components/ui/card";
import { Field, FieldLabel } from "@/components/ui/field";
import { Form } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group";
import { api } from "@/lib/api";

// Only follow same-site paths ("/..." but not "//other-site").
function nextTarget(): string {
  const next = new URLSearchParams(location.search).get("next");
  return next?.startsWith("/") && !next.startsWith("//") ? next : "/";
}

export function LoginPage(): React.ReactElement {
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [showPassword, setShowPassword] = React.useState(false);
  const passwordRef = React.useRef<HTMLInputElement>(null);

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setLoading(true);
    setError(null);
    try {
      await api("/api/login", {
        body: { password: form.get("password"), username: form.get("username") },
        method: "POST",
      });
      location.href = nextTarget();
    } catch (err) {
      setError(err instanceof TypeError ? "Can't reach the server" : (err as Error).message);
      if (passwordRef.current) {
        passwordRef.current.value = "";
        passwordRef.current.focus();
      }
      setLoading(false);
    }
  };

  return (
    <main className="flex min-h-svh flex-col items-center justify-center gap-6 bg-muted/40 p-6">
      <div className="flex items-center gap-2.5">
        <img alt="" className="size-9 rounded-lg" src="/static/favicon.svg" />
        <span className="font-heading font-semibold text-lg">Call Analyzer</span>
      </div>
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Sign in</CardTitle>
          <CardDescription>Use the account your manager created for you.</CardDescription>
        </CardHeader>
        <CardPanel>
          <Form className="flex w-full flex-col gap-4" onSubmit={onSubmit}>
            {error && (
              <Alert variant="error">
                <CircleAlertIcon aria-hidden="true" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            <Field>
              <FieldLabel>Username</FieldLabel>
              <Input autoComplete="username" autoFocus name="username" required type="text" />
            </Field>
            <Field>
              <FieldLabel>Password</FieldLabel>
              <InputGroup>
                <InputGroupInput
                  autoComplete="current-password"
                  name="password"
                  ref={passwordRef}
                  required
                  type={showPassword ? "text" : "password"}
                />
                <InputGroupAddon align="inline-end">
                  <Button
                    aria-label={showPassword ? "Hide password" : "Show password"}
                    onClick={() => setShowPassword((v) => !v)}
                    size="icon-xs"
                    variant="ghost"
                  >
                    {showPassword ? <EyeOffIcon aria-hidden="true" /> : <EyeIcon aria-hidden="true" />}
                  </Button>
                </InputGroupAddon>
              </InputGroup>
            </Field>
            <Button className="w-full" loading={loading} type="submit">
              Sign in
            </Button>
          </Form>
        </CardPanel>
      </Card>
    </main>
  );
}
