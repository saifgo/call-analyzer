import {
  CircleAlertIcon,
  EllipsisIcon,
  PencilIcon,
  PhoneIcon,
  PlusIcon,
  Trash2Icon,
  UserPlusIcon,
  UsersIcon,
} from "lucide-react";
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
import type { Account, AgentInfo, CrmMembers, Role } from "@/lib/types";

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
/** An account's softphone: its GoVoice extension and the GoVoice login its SIP password is fetched with. */
type Phone = { extension: string; govoice_user: string };

function UserDialog({
  account,
  phone,
  open,
  onOpenChange,
  onSaved,
}: {
  account: Account | null;
  /** The account's softphone, null for none. */
  phone: Phone | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogPopup className="sm:max-w-lg">
        {/* Mounted on every open, so the form starts from the account's current values. */}
        <UserForm account={account} onDone={() => onOpenChange(false)} onSaved={onSaved} phone={phone} />
      </DialogPopup>
    </Dialog>
  );
}

const NO_CRM_USER = "__none";

/** Which CRM user the account is: the leads they add from the call desk are theirs in the CRM. */
function CrmUserField({
  members,
  error,
  value,
  onChange,
}: {
  members: CrmMembers | undefined;
  error: string | undefined;
  value: string;
  onChange: (id: string) => void;
}) {
  if (members && !members.configured) return null;
  const items = [
    { label: "Not linked", value: NO_CRM_USER },
    ...(members?.members ?? []).map((m) => ({ label: m.email ? `${m.name} (${m.email})` : m.name, value: m.id })),
  ];
  // A linked user the CRM no longer lists still shows, so saving doesn't silently unlink them.
  if (members && !items.some((i) => i.value === value)) items.push({ label: "Unknown CRM user", value });
  return (
    <Field>
      <FieldLabel>CRM user</FieldLabel>
      {error ? (
        <p className="text-destructive-foreground text-sm">Couldn't load the CRM users: {error}</p>
      ) : members ? (
        <Select items={items} onValueChange={(v) => onChange(v as string)} value={value}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectPopup>
            {items.map((item) => (
              <SelectItem key={item.value} value={item.value}>
                {item.label}
              </SelectItem>
            ))}
          </SelectPopup>
        </Select>
      ) : (
        <Skeleton className="h-9 w-full rounded-lg" />
      )}
      <FieldDescription>Contacts this account adds from the call desk are owned by this CRM user.</FieldDescription>
    </Field>
  );
}

function UserForm({
  account,
  phone,
  onDone,
  onSaved,
}: {
  account: Account | null;
  phone: Phone | null;
  onDone: () => void;
  onSaved: () => void;
}) {
  const me = useMe();
  const { data: known } = useApi<AgentInfo[]>("/api/agents");
  const { data: crmMembers, error: crmError } = useApi<CrmMembers>("/api/crm/members");
  const editing = account !== null;
  const [username, setUsername] = React.useState(account?.username ?? "");
  const [displayName, setDisplayName] = React.useState(account?.display_name ?? "");
  const [role, setRole] = React.useState<Role>(account?.role ?? "agent");
  const [agents, setAgents] = React.useState<string[]>(account?.agents ?? []);
  const [crmMember, setCrmMember] = React.useState(account?.crm_member_id ?? NO_CRM_USER);
  const [password, setPassword] = React.useState("");
  const [phoneExt, setPhoneExt] = React.useState(phone?.extension ?? "");
  const [govoiceUser, setGovoiceUser] = React.useState(phone?.govoice_user ?? "");
  const [accountPassword, setAccountPassword] = React.useState("");
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
      const body = { agents, crm_member_id: crmMember === NO_CRM_USER ? "" : crmMember, display_name: displayName, role };
      if (editing) {
        await api(`/api/users/${encodeURIComponent(account.username)}`, {
          body: { ...body, password: password || null },
          method: "PATCH",
        });
      } else {
        await api("/api/users", { body: { ...body, password, username: username.trim() }, method: "POST" });
      }
      const phonePath = `/api/softphones/${encodeURIComponent(editing ? account.username : username.trim())}`;
      const phoneChanged =
        phoneExt.trim() !== phone?.extension || govoiceUser.trim() !== phone?.govoice_user || accountPassword !== "";
      if (phoneExt.trim() && phoneChanged) {
        await api(phonePath, {
          body: {
            account_password: accountPassword || null,
            extension: phoneExt.trim(),
            govoice_user: govoiceUser.trim(),
          },
          method: "PUT",
        });
      } else if (!phoneExt.trim() && phone) {
        await api(phonePath, { method: "DELETE" });
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
        <CrmUserField error={crmError?.message} members={crmMembers} onChange={setCrmMember} value={crmMember} />
        <div className="flex flex-col gap-2">
          <span className="font-medium text-sm">Phone</span>
          <p className="text-muted-foreground text-xs">
            The GoVoice extension this account makes and takes calls with in the browser, and the GoVoice account
            (My Account on otn.govoice.tn) its SIP password is fetched with. Leave the extension empty for no phone.
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel>Extension</FieldLabel>
              <Input
                autoComplete="off"
                inputMode="numeric"
                onChange={(e) => {
                  // GoVoice accounts are named after their extension (user100), unless the admin typed another one.
                  if (!govoiceUser || govoiceUser === `user${phoneExt.trim()}`) setGovoiceUser(`user${e.target.value.trim()}`);
                  setPhoneExt(e.target.value);
                }}
                pattern="\d{1,6}"
                placeholder={`e.g. ${agents[0] ?? "100"}`}
                type="text"
                value={phoneExt}
              />
            </Field>
            <Field>
              <FieldLabel>GoVoice username</FieldLabel>
              <Input
                autoComplete="off"
                disabled={!phoneExt.trim()}
                onChange={(e) => setGovoiceUser(e.target.value)}
                placeholder={`e.g. user${phoneExt.trim() || "100"}`}
                required={!!phoneExt.trim()}
                type="text"
                value={govoiceUser}
              />
            </Field>
          </div>
          <Field>
            <FieldLabel>GoVoice account password</FieldLabel>
            <Input
              autoComplete="new-password"
              disabled={!phoneExt.trim()}
              onChange={(e) => setAccountPassword(e.target.value)}
              placeholder={phone?.govoice_user ? "Leave empty to keep it" : undefined}
              required={!!phoneExt.trim() && !phone?.govoice_user}
              type="password"
              value={accountPassword}
            />
            <FieldDescription>The SIP password is fetched from GoVoice with it when you save.</FieldDescription>
          </Field>
        </div>
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
  const { data: phones, reload: reloadPhones } = useApi<Record<string, Phone>>("/api/softphones");
  const { data: crmMembers } = useApi<CrmMembers>("/api/crm/members");
  const [editing, setEditing] = React.useState<Account | null>(null);
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [deleting, setDeleting] = React.useState<Account | null>(null);

  const refresh = () => {
    reload();
    reloadAgents();
    reloadPhones();
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
                <TableHead className="max-sm:hidden">Phone</TableHead>
                <TableHead className="max-lg:hidden">CRM user</TableHead>
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
                  <TableCell className="max-sm:hidden">
                    {phones?.[a.username] ? (
                      <Badge className="tabular-nums" variant="outline">
                        <PhoneIcon aria-hidden="true" />
                        {phones[a.username].extension}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground text-sm">None</span>
                    )}
                  </TableCell>
                  <TableCell className="max-lg:hidden">
                    {a.crm_member_id ? (
                      <span className="text-sm" dir="auto">
                        {crmMembers?.members.find((m) => m.id === a.crm_member_id)?.name ?? "Linked"}
                      </span>
                    ) : (
                      <span className="text-muted-foreground text-sm">None</span>
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

      <UserDialog
        account={editing}
        onOpenChange={setDialogOpen}
        onSaved={refresh}
        open={dialogOpen}
        phone={editing ? (phones?.[editing.username] ?? null) : null}
      />
      <DeleteUserDialog account={deleting} onDeleted={refresh} onOpenChange={(open) => !open && setDeleting(null)} />
    </>
  );
}
