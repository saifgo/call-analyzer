import { CircleAlertIcon, EllipsisIcon, PencilIcon, PlusIcon, Trash2Icon, UserPlusIcon, UsersIcon } from "lucide-react";
import * as React from "react";
import { MIN_PASSWORD_LENGTH } from "@/components/change-password-dialog";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogPopup,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardFrame, CardFrameDescription, CardFrameHeader, CardFrameTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
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
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Form } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Menu, MenuItem, MenuPopup, MenuSeparator, MenuTrigger } from "@/components/ui/menu";
import { Select, SelectItem, SelectPopup, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toastManager } from "@/components/ui/toast";
import { api, useApi } from "@/lib/api";
import { fmtDate, numberFmt } from "@/lib/format";
import { useMe } from "@/lib/me";
import type { Account, AgentInfo, Role } from "@/lib/types";

const ROLE_ITEMS: { label: string; value: Role; help: string }[] = [
  { help: "Sees only the calls, feedback and reports of the extensions below. Read-only.", label: "Agent", value: "agent" },
  { help: "Sees everything and manages the pipeline, settings and users.", label: "Admin", value: "admin" },
];

function AgentPicker({
  value,
  onChange,
  known,
  username,
}: {
  value: string[];
  onChange: (agents: string[]) => void;
  known: AgentInfo[];
  username: string;
}) {
  const [extra, setExtra] = React.useState("");
  // Extensions linked to this account but with no calls yet still need a checkbox.
  const all = [...known, ...value.filter((a) => !known.some((k) => k.agent === a)).map((agent) => ({ accounts: [], agent, calls: 0 }))];
  const toggle = (agent: string, on: boolean) =>
    onChange(on ? [...new Set([...value, agent])].sort() : value.filter((a) => a !== agent));
  const add = () => {
    const agent = extra.trim();
    if (agent) toggle(agent, true);
    setExtra("");
  };

  return (
    <div className="flex flex-col gap-3">
      {all.length > 0 && (
        <div className="grid max-h-60 gap-2 overflow-y-auto rounded-lg border p-3 sm:grid-cols-2">
          {all.map((a) => {
            const others = a.accounts.filter((u) => u !== username);
            return (
              <Label className="items-start font-normal" key={a.agent}>
                <Checkbox checked={value.includes(a.agent)} onCheckedChange={(on) => toggle(a.agent, on)} />
                <span className="flex flex-col gap-0.5">
                  <span className="font-medium tabular-nums">Extension {a.agent}</span>
                  <span className="text-muted-foreground text-xs">
                    {numberFmt.format(a.calls)} {a.calls === 1 ? "call" : "calls"}
                    {others.length > 0 && ` · also linked to ${others.join(", ")}`}
                  </span>
                </span>
              </Label>
            );
          })}
        </div>
      )}
      <div className="flex gap-2">
        <Input
          aria-label="Other extension"
          onChange={(e) => setExtra(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder="Other extension, e.g. 110"
          type="text"
          value={extra}
        />
        <Button disabled={!extra.trim()} onClick={add} variant="outline">
          <PlusIcon aria-hidden="true" />
          Add
        </Button>
      </div>
    </div>
  );
}

/** Create an account (account = null) or edit one. */
function UserDialog({
  account,
  open,
  onOpenChange,
  onSaved,
}: {
  account: Account | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogPopup className="sm:max-w-lg">
        {/* Mounted on every open, so the form starts from the account's current values. */}
        <UserForm account={account} onDone={() => onOpenChange(false)} onSaved={onSaved} />
      </DialogPopup>
    </Dialog>
  );
}

function UserForm({ account, onDone, onSaved }: { account: Account | null; onDone: () => void; onSaved: () => void }) {
  const me = useMe();
  const { data: known } = useApi<AgentInfo[]>("/api/agents");
  const editing = account !== null;
  const [username, setUsername] = React.useState(account?.username ?? "");
  const [displayName, setDisplayName] = React.useState(account?.display_name ?? "");
  const [role, setRole] = React.useState<Role>(account?.role ?? "agent");
  const [agents, setAgents] = React.useState<string[]>(account?.agents ?? []);
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  const isSelf = account?.username === me.user;

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (role === "agent" && agents.length === 0) {
      setError("Link at least one extension, or the agent won't see any calls.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const body = { agents, display_name: displayName, role };
      if (editing) {
        await api(`/api/users/${encodeURIComponent(account.username)}`, {
          body: { ...body, password: password || null },
          method: "PATCH",
        });
      } else {
        await api("/api/users", { body: { ...body, password, username: username.trim() }, method: "POST" });
      }
      toastManager.add({
        description: password && editing ? "They were signed out everywhere." : undefined,
        title: editing ? "User updated" : "User created",
        type: "success",
      });
      onSaved();
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Form className="contents" onSubmit={onSubmit}>
      <DialogHeader>
        <DialogTitle>{editing ? `Edit ${account.username}` : "Add user"}</DialogTitle>
        <DialogDescription>
          {editing
            ? "Changing the role signs the user out everywhere."
            : "Give each agent their own account so they can sign in and see their calls, feedback and reports."}
        </DialogDescription>
      </DialogHeader>
      <DialogPanel className="flex flex-col gap-5">
        {error && (
          <Alert variant="error">
            <CircleAlertIcon aria-hidden="true" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field>
            <FieldLabel>Username</FieldLabel>
            <Input
              autoComplete="off"
              disabled={editing}
              maxLength={64}
              onChange={(e) => setUsername(e.target.value)}
              pattern="[\w.@\-]+"
              required
              type="text"
              value={username}
            />
            {!editing && <FieldDescription>Letters, digits and . _ @ -</FieldDescription>}
          </Field>
          <Field>
            <FieldLabel>Name</FieldLabel>
            <Input
              dir="auto"
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Optional, e.g. Ali Ben Salah"
              type="text"
              value={displayName}
            />
          </Field>
        </div>
        <Field>
          <FieldLabel>Role</FieldLabel>
          <Select disabled={isSelf} items={ROLE_ITEMS} onValueChange={(v) => setRole(v as Role)} value={role}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectPopup>
              {ROLE_ITEMS.map((item) => (
                <SelectItem key={item.value} value={item.value}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectPopup>
          </Select>
          <FieldDescription>
            {isSelf ? "You can't remove your own admin access." : ROLE_ITEMS.find((i) => i.value === role)?.help}
          </FieldDescription>
        </Field>
        {role === "agent" && (
          <div className="flex flex-col gap-2">
            <span className="font-medium text-sm">Agent extensions</span>
            <p className="text-muted-foreground text-xs">
              The account sees the calls of every extension ticked here, and their coaching reports.
            </p>
            {known ? (
              <AgentPicker known={known} onChange={setAgents} username={account?.username ?? ""} value={agents} />
            ) : (
              <Skeleton className="h-24 w-full rounded-lg" />
            )}
          </div>
        )}
        <Field>
          <FieldLabel>{editing ? "New password" : "Password"}</FieldLabel>
          <Input
            autoComplete="new-password"
            minLength={MIN_PASSWORD_LENGTH}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={editing ? "Leave empty to keep the current password" : undefined}
            required={!editing}
            type="password"
            value={password}
          />
          <FieldDescription>
            At least {MIN_PASSWORD_LENGTH} characters. Users can change it themselves from their account menu.
          </FieldDescription>
        </Field>
      </DialogPanel>
      <DialogFooter>
        <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
        <Button loading={saving} type="submit">
          {editing ? "Save" : "Create user"}
        </Button>
      </DialogFooter>
    </Form>
  );
}

function DeleteUserDialog({
  account,
  onOpenChange,
  onDeleted,
}: {
  account: Account | null;
  onOpenChange: (open: boolean) => void;
  onDeleted: () => void;
}) {
  const [busy, setBusy] = React.useState(false);
  const remove = async () => {
    if (!account) return;
    setBusy(true);
    try {
      await api(`/api/users/${encodeURIComponent(account.username)}`, { method: "DELETE" });
      toastManager.add({ title: `Deleted ${account.username}`, type: "success" });
      onDeleted();
      onOpenChange(false);
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: "Couldn't delete the user", type: "error" });
    } finally {
      setBusy(false);
    }
  };
  return (
    <AlertDialog onOpenChange={onOpenChange} open={!!account}>
      <AlertDialogPopup>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete {account?.username}?</AlertDialogTitle>
          <AlertDialogDescription>
            They are signed out and can no longer sign in. Their calls, feedback and reports are kept.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogClose render={<Button variant="ghost" />}>Cancel</AlertDialogClose>
          <Button loading={busy} onClick={remove} variant="destructive">
            Delete user
          </Button>
        </AlertDialogFooter>
      </AlertDialogPopup>
    </AlertDialog>
  );
}

export function UsersPage(): React.ReactElement {
  const me = useMe();
  const { data: accounts, reload } = useApi<Account[]>("/api/users");
  const { data: known, reload: reloadAgents } = useApi<AgentInfo[]>("/api/agents");
  const [editing, setEditing] = React.useState<Account | null>(null);
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [deleting, setDeleting] = React.useState<Account | null>(null);

  const refresh = () => {
    reload();
    reloadAgents();
  };
  const openNew = () => {
    setEditing(null);
    setDialogOpen(true);
  };
  const openEdit = (account: Account) => {
    setEditing(account);
    setDialogOpen(true);
  };

  const unlinked = (known ?? []).filter((a) => a.accounts.length === 0 && a.calls > 0);
  const addButton = (
    <Button onClick={openNew}>
      <UserPlusIcon aria-hidden="true" />
      Add user
    </Button>
  );

  return (
    <>
      <PageHeader
        actions={addButton}
        description="Who can sign in. Agents only see their own calls, AI feedback and coaching reports."
        title="Users"
      />

      {unlinked.length > 0 && (
        <Alert variant="info">
          <UsersIcon aria-hidden="true" />
          <AlertTitle>
            {unlinked.length === 1 ? "1 extension has" : `${unlinked.length} extensions have`} no account yet
          </AlertTitle>
          <AlertDescription>
            {unlinked.map((a) => `${a.agent} (${numberFmt.format(a.calls)} calls)`).join(", ")}
          </AlertDescription>
          <AlertAction>
            <Button onClick={openNew} size="sm" variant="outline">
              Add user
            </Button>
          </AlertAction>
        </Alert>
      )}

      {!accounts ? (
        <Skeleton className="h-64 rounded-2xl" />
      ) : accounts.length === 0 ? (
        <Card>
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <UsersIcon />
              </EmptyMedia>
              <EmptyTitle>No users</EmptyTitle>
              <EmptyDescription>Add an account for each agent.</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>{addButton}</EmptyContent>
          </Empty>
        </Card>
      ) : (
        <CardFrame>
          <CardFrameHeader>
            <CardFrameTitle>Accounts</CardFrameTitle>
            <CardFrameDescription>
              {accounts.length} {accounts.length === 1 ? "account" : "accounts"}
            </CardFrameDescription>
          </CardFrameHeader>
          <Table variant="card">
            <TableHeader>
              <TableRow>
                <TableHead>User</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Extensions</TableHead>
                <TableHead className="max-md:hidden">Created</TableHead>
                <TableHead className="w-10">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {accounts.map((a) => (
                <TableRow className="cursor-pointer" key={a.username} onClick={() => openEdit(a)}>
                  <TableCell>
                    <div className="font-medium" dir="auto">
                      {a.display_name || a.username}
                      {a.username === me.user && <span className="ms-1.5 font-normal text-muted-foreground">(you)</span>}
                    </div>
                    {a.display_name && <div className="text-muted-foreground text-xs">{a.username}</div>}
                  </TableCell>
                  <TableCell>
                    <Badge variant={a.role === "admin" ? "info" : "secondary"}>{a.role === "admin" ? "Admin" : "Agent"}</Badge>
                  </TableCell>
                  <TableCell>
                    {a.role === "admin" ? (
                      <span className="text-muted-foreground text-sm">All</span>
                    ) : a.agents.length ? (
                      <div className="flex flex-wrap gap-1">
                        {a.agents.map((ext) => (
                          <Badge className="tabular-nums" key={ext} variant="outline">
                            {ext}
                          </Badge>
                        ))}
                      </div>
                    ) : (
                      <Badge variant="warning">None linked</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground max-md:hidden">{fmtDate(a.created_at)}</TableCell>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <Menu>
                      <MenuTrigger render={<Button aria-label={`Actions for ${a.username}`} size="icon-sm" variant="ghost" />}>
                        <EllipsisIcon aria-hidden="true" />
                      </MenuTrigger>
                      <MenuPopup align="end">
                        <MenuItem onClick={() => openEdit(a)}>
                          <PencilIcon aria-hidden="true" />
                          Edit
                        </MenuItem>
                        <MenuSeparator />
                        <MenuItem disabled={a.username === me.user} onClick={() => setDeleting(a)} variant="destructive">
                          <Trash2Icon aria-hidden="true" />
                          Delete
                        </MenuItem>
                      </MenuPopup>
                    </Menu>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardFrame>
      )}

      <UserDialog account={editing} onOpenChange={setDialogOpen} onSaved={refresh} open={dialogOpen} />
      <DeleteUserDialog account={deleting} onDeleted={refresh} onOpenChange={(open) => !open && setDeleting(null)} />
    </>
  );
}
