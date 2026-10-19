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
import { fmtDate } from "@/lib/format";
import { t, type TKey } from "@/lib/i18n";
import { useMe } from "@/lib/me";
import type { Account, AgentInfo, CrmMembers, Role } from "@/lib/types";

const ROLES: { label: TKey; value: Role; help: TKey }[] = [
  { help: "users.role.agentHelp", label: "shell.agent", value: "agent" },
  { help: "users.role.adminHelp", label: "shell.admin", value: "admin" },
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
                  <span className="font-medium tabular-nums">{t("phone.extension", { extension: a.agent })}</span>
                  <span className="text-muted-foreground text-xs">
                    {t("desk.nCalls", { count: a.calls })}
                    {others.length > 0 && ` · ${t("users.alsoLinked", { names: others.join(", ") })}`}
                  </span>
                </span>
              </Label>
            );
          })}
        </div>
      )}
      <div className="flex gap-2">
        <Input
          aria-label={t("users.otherExtension")}
          onChange={(e) => setExtra(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder={t("users.otherExtensionPlaceholder")}
          type="text"
          value={extra}
        />
        <Button disabled={!extra.trim()} onClick={add} variant="outline">
          <PlusIcon aria-hidden="true" />
          {t("whatsapp.add")}
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
    { label: t("users.notLinked"), value: NO_CRM_USER },
    ...(members?.members ?? []).map((m) => ({ label: m.email ? `${m.name} (${m.email})` : m.name, value: m.id })),
  ];
  // A linked user the CRM no longer lists still shows, so saving doesn't silently unlink them.
  if (members && !items.some((i) => i.value === value)) items.push({ label: t("users.unknownCrmUser"), value });
  return (
    <Field>
      <FieldLabel>{t("users.crmUser")}</FieldLabel>
      {error ? (
        <p className="text-destructive-foreground text-sm">{t("users.crmUsersFailed", { error })}</p>
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
      <FieldDescription>{t("users.crmUserHint")}</FieldDescription>
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
  const roleItems = ROLES.map((r) => ({ help: t(r.help), label: t(r.label), value: r.value }));

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (role === "agent" && agents.length === 0) {
      setError(t("users.linkExtension"));
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
        description: password && editing ? t("users.signedOutEverywhere") : undefined,
        title: editing ? t("users.updated") : t("users.created"),
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
        <DialogTitle>{editing ? t("whatsapp.editLabel", { label: account.username }) : t("users.add")}</DialogTitle>
        <DialogDescription>{editing ? t("users.editHint") : t("users.addHint")}</DialogDescription>
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
            <FieldLabel>{t("login.username")}</FieldLabel>
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
            {!editing && <FieldDescription>{t("users.usernameHint")}</FieldDescription>}
          </Field>
          <Field>
            <FieldLabel>{t("campaigns.name")}</FieldLabel>
            <Input
              dir="auto"
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder={t("users.namePlaceholder")}
              type="text"
              value={displayName}
            />
          </Field>
        </div>
        <Field>
          <FieldLabel>{t("users.role")}</FieldLabel>
          <Select disabled={isSelf} items={roleItems} onValueChange={(v) => setRole(v as Role)} value={role}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectPopup>
              {roleItems.map((item) => (
                <SelectItem key={item.value} value={item.value}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectPopup>
          </Select>
          <FieldDescription>{isSelf ? t("users.ownAdmin") : roleItems.find((i) => i.value === role)?.help}</FieldDescription>
        </Field>
        {role === "agent" && (
          <div className="flex flex-col gap-2">
            <span className="font-medium text-sm">{t("users.agentExtensions")}</span>
            <p className="text-muted-foreground text-xs">{t("users.agentExtensionsHint")}</p>
            {known ? (
              <AgentPicker known={known} onChange={setAgents} username={account?.username ?? ""} value={agents} />
            ) : (
              <Skeleton className="h-24 w-full rounded-lg" />
            )}
          </div>
        )}
        <CrmUserField error={crmError?.message} members={crmMembers} onChange={setCrmMember} value={crmMember} />
        <div className="flex flex-col gap-2">
          <span className="font-medium text-sm">{t("users.phone")}</span>
          <p className="text-muted-foreground text-xs">{t("users.phoneHint")}</p>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel>{t("dashboard.extension")}</FieldLabel>
              <Input
                autoComplete="off"
                inputMode="numeric"
                onChange={(e) => {
                  // GoVoice accounts are named after their extension (user100), unless the admin typed another one.
                  if (!govoiceUser || govoiceUser === `user${phoneExt.trim()}`) setGovoiceUser(`user${e.target.value.trim()}`);
                  setPhoneExt(e.target.value);
                }}
                pattern="\d{1,6}"
                placeholder={t("users.eg", { example: agents[0] ?? "100" })}
                type="text"
                value={phoneExt}
              />
            </Field>
            <Field>
              <FieldLabel>{t("users.govoiceUsername")}</FieldLabel>
              <Input
                autoComplete="off"
                disabled={!phoneExt.trim()}
                onChange={(e) => setGovoiceUser(e.target.value)}
                placeholder={t("users.eg", { example: `user${phoneExt.trim() || "100"}` })}
                required={!!phoneExt.trim()}
                type="text"
                value={govoiceUser}
              />
            </Field>
          </div>
          <Field>
            <FieldLabel>{t("users.govoicePassword")}</FieldLabel>
            <Input
              autoComplete="new-password"
              disabled={!phoneExt.trim()}
              onChange={(e) => setAccountPassword(e.target.value)}
              placeholder={phone?.govoice_user ? t("users.keepEmpty") : undefined}
              required={!!phoneExt.trim() && !phone?.govoice_user}
              type="password"
              value={accountPassword}
            />
            <FieldDescription>{t("users.govoicePasswordHint")}</FieldDescription>
          </Field>
        </div>
        <Field>
          <FieldLabel>{editing ? t("password.new") : t("login.password")}</FieldLabel>
          <Input
            autoComplete="new-password"
            minLength={MIN_PASSWORD_LENGTH}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={editing ? t("users.keepPassword") : undefined}
            required={!editing}
            type="password"
            value={password}
          />
          <FieldDescription>{t("users.passwordHint", { count: MIN_PASSWORD_LENGTH })}</FieldDescription>
        </Field>
      </DialogPanel>
      <DialogFooter>
        <DialogClose render={<Button variant="ghost" />}>{t("common.cancel")}</DialogClose>
        <Button loading={saving} type="submit">
          {editing ? t("common.save") : t("users.create")}
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
      toastManager.add({ title: t("users.deleted", { name: account.username }), type: "success" });
      onDeleted();
      onOpenChange(false);
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: t("users.deleteFailed"), type: "error" });
    } finally {
      setBusy(false);
    }
  };
  return (
    <AlertDialog onOpenChange={onOpenChange} open={!!account}>
      <AlertDialogPopup>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("users.deleteTitle", { name: account?.username })}</AlertDialogTitle>
          <AlertDialogDescription>{t("users.deleteHint")}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogClose render={<Button variant="ghost" />}>{t("common.cancel")}</AlertDialogClose>
          <Button loading={busy} onClick={remove} variant="destructive">
            {t("users.deleteUser")}
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
      {t("users.add")}
    </Button>
  );

  return (
    <>
      <PageHeader
        actions={addButton}
        description={t("users.description")}
        title={t("nav.users")}
      />

      {unlinked.length > 0 && (
        <Alert variant="info">
          <UsersIcon aria-hidden="true" />
          <AlertTitle>{t("users.unlinked", { count: unlinked.length })}</AlertTitle>
          <AlertDescription>
            {unlinked.map((a) => `${a.agent} (${t("desk.nCalls", { count: a.calls })})`).join(", ")}
          </AlertDescription>
          <AlertAction>
            <Button onClick={openNew} size="sm" variant="outline">
              {t("users.add")}
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
              <EmptyTitle>{t("users.none")}</EmptyTitle>
              <EmptyDescription>{t("users.noneHint")}</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>{addButton}</EmptyContent>
          </Empty>
        </Card>
      ) : (
        <CardFrame>
          <CardFrameHeader>
            <CardFrameTitle>{t("users.accounts")}</CardFrameTitle>
            <CardFrameDescription>{t("users.accountCount", { count: accounts.length })}</CardFrameDescription>
          </CardFrameHeader>
          <Table variant="card">
            <TableHeader>
              <TableRow>
                <TableHead>{t("users.user")}</TableHead>
                <TableHead>{t("users.role")}</TableHead>
                <TableHead>{t("users.extensions")}</TableHead>
                <TableHead className="max-sm:hidden">{t("users.phone")}</TableHead>
                <TableHead className="max-lg:hidden">{t("users.crmUser")}</TableHead>
                <TableHead className="max-md:hidden">{t("leads.created")}</TableHead>
                <TableHead className="w-10">
                  <span className="sr-only">{t("board.actions")}</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {accounts.map((a) => (
                <TableRow className="cursor-pointer" key={a.username} onClick={() => openEdit(a)}>
                  <TableCell>
                    <div className="font-medium" dir="auto">
                      {a.display_name || a.username}
                      {a.username === me.user && <span className="ms-1.5 font-normal text-muted-foreground">{t("users.you")}</span>}
                    </div>
                    {a.display_name && <div className="text-muted-foreground text-xs">{a.username}</div>}
                  </TableCell>
                  <TableCell>
                    <Badge variant={a.role === "admin" ? "info" : "secondary"}>{a.role === "admin" ? t("shell.admin") : t("shell.agent")}</Badge>
                  </TableCell>
                  <TableCell>
                    {a.role === "admin" ? (
                      <span className="text-muted-foreground text-sm">{t("pipeline.all")}</span>
                    ) : a.agents.length ? (
                      <div className="flex flex-wrap gap-1">
                        {a.agents.map((ext) => (
                          <Badge className="tabular-nums" key={ext} variant="outline">
                            {ext}
                          </Badge>
                        ))}
                      </div>
                    ) : (
                      <Badge variant="warning">{t("users.noneLinked")}</Badge>
                    )}
                  </TableCell>
                  <TableCell className="max-sm:hidden">
                    {phones?.[a.username] ? (
                      <Badge className="tabular-nums" variant="outline">
                        <PhoneIcon aria-hidden="true" />
                        {phones[a.username].extension}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground text-sm">{t("detail.none")}</span>
                    )}
                  </TableCell>
                  <TableCell className="max-lg:hidden">
                    {a.crm_member_id ? (
                      <span className="text-sm" dir="auto">
                        {crmMembers?.members.find((m) => m.id === a.crm_member_id)?.name ?? t("users.linked")}
                      </span>
                    ) : (
                      <span className="text-muted-foreground text-sm">{t("detail.none")}</span>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground max-md:hidden">{fmtDate(a.created_at)}</TableCell>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <Menu>
                      <MenuTrigger render={<Button aria-label={t("users.actionsFor", { name: a.username })} size="icon-sm" variant="ghost" />}>
                        <EllipsisIcon aria-hidden="true" />
                      </MenuTrigger>
                      <MenuPopup align="end">
                        <MenuItem onClick={() => openEdit(a)}>
                          <PencilIcon aria-hidden="true" />
                          {t("common.edit")}
                        </MenuItem>
                        <MenuSeparator />
                        <MenuItem disabled={a.username === me.user} onClick={() => setDeleting(a)} variant="destructive">
                          <Trash2Icon aria-hidden="true" />
                          {t("common.delete")}
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
