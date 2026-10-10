import { useEffect, useState } from "react";

import { FieldLabel } from "@/components/field-label";
import { SignInLink } from "@/components/sign-in-button";
import { Button } from "@ageval/shared/components/ui/button";
import { ConfirmDialog } from "@ageval/shared/components/ui/confirm-dialog";
import { Input } from "@ageval/shared/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@ageval/shared/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@ageval/shared/components/ui/table";
import { formatDay } from "@ageval/shared/lib/utils";
import {
  createOrgSecret,
  deleteOrgSecret,
  listOrgSecrets,
  type OrgSecret,
} from "@/lib/api";
import { getGithubUser } from "@/lib/auth";
import { toastError } from "@/lib/toast-error";

function canDeleteSecret(row: OrgSecret, role: string | undefined): boolean {
  if ((role || "").toLowerCase() === "owner") return true;
  const login = getGithubUser();
  return Boolean(login && row.created_by.toLowerCase() === login.toLowerCase());
}

export function OrgSecrets({
  orgId,
  role,
  token,
}: {
  orgId: string;
  role?: string;
  token: string | null;
}) {
  const [rows, setRows] = useState<OrgSecret[]>([]);
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"model" | "provider">("model");
  const [locator, setLocator] = useState("");
  const [provider, setProvider] = useState<"e2b" | "daytona">("e2b");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<OrgSecret | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    listOrgSecrets(orgId, token)
      .then((items) => {
        if (!cancelled) setRows(items);
      })
      .catch((err: unknown) => {
        if (!cancelled) toastError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [orgId, token]);

  if (!token) {
    return (
      <p className="text-sm text-body">
        <SignInLink /> to manage org secrets.
      </p>
    );
  }

  async function create() {
    const secretName = name.trim();
    const secretValue = value;
    if (!secretName || !secretValue.trim()) {
      toastError(new Error("Name and value are required"));
      return;
    }
    if (kind === "model" && !locator.trim()) {
      toastError(new Error("A model secret needs a locator such as OPENAI_API_KEY"));
      return;
    }
    setBusy(true);
    try {
      const created = await createOrgSecret(
        orgId,
        kind === "model"
          ? { name: secretName, kind, value: secretValue, locator: locator.trim() }
          : { name: secretName, kind, value: secretValue, provider },
        token,
      );
      setRows((current) => [created, ...current.filter((row) => row.secret_id !== created.secret_id)]);
      setValue("");
      setName("");
    } catch (err) {
      toastError(err);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!pending) return;
    setBusy(true);
    try {
      await deleteOrgSecret(orgId, pending.secret_id, token);
      setRows((current) => current.filter((row) => row.secret_id !== pending.secret_id));
      setPending(null);
    } catch (err) {
      toastError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <p className="text-sm text-body">
        A model secret is the inference key. Profiles keep only its locator,
        such as <code className="font-mono">{"${OPENAI_API_KEY}"}</code>. A
        provider secret opens the e2b or daytona sandbox and stays on the
        worker. The value is stored once and is not shown again.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <FieldLabel htmlFor="secret-name">Name</FieldLabel>
          <Input
            id="secret-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="mt-1.5 text-sm"
            autoComplete="off"
          />
        </div>
        <div>
          <FieldLabel>Kind</FieldLabel>
          <Select
            value={kind}
            onValueChange={(next) => {
              if (next === "model" || next === "provider") setKind(next);
            }}
          >
            <SelectTrigger className="mt-1.5 h-9 min-w-0 w-full text-sm" aria-label="Secret kind">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="model">model</SelectItem>
              <SelectItem value="provider">provider</SelectItem>
            </SelectContent>
          </Select>
        </div>
        {kind === "model" ? (
          <div>
            <FieldLabel htmlFor="secret-locator">Locator</FieldLabel>
            <Input
              id="secret-locator"
              value={locator}
              onChange={(event) => setLocator(event.target.value)}
              placeholder="OPENAI_API_KEY"
              className="mt-1.5 text-sm"
              autoComplete="off"
            />
          </div>
        ) : (
          <div>
            <FieldLabel>Provider</FieldLabel>
            <Select
              value={provider}
              onValueChange={(next) => {
                if (next === "e2b" || next === "daytona") setProvider(next);
              }}
            >
              <SelectTrigger className="mt-1.5 h-9 min-w-0 w-full text-sm" aria-label="Provider">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="e2b">e2b</SelectItem>
                <SelectItem value="daytona">daytona</SelectItem>
              </SelectContent>
            </Select>
          </div>
        )}
        <div>
          <FieldLabel htmlFor="secret-value">Value</FieldLabel>
          <Input
            id="secret-value"
            type="password"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            className="mt-1.5 text-sm"
            autoComplete="new-password"
          />
        </div>
        <div className="sm:col-span-2">
          <Button type="button" disabled={busy} onClick={() => void create()}>
            {busy ? "Saving…" : "Save secret"}
          </Button>
        </div>
      </div>

      {loading ? (
        <p className="text-sm text-mute">Loading secrets…</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-mute">No secrets stored.</p>
      ) : (
        <div className="blob-panel overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Name</TableHead>
                <TableHead>Kind</TableHead>
                <TableHead>Locator</TableHead>
                <TableHead>Created</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.secret_id}>
                  <TableCell className="font-medium">{row.name}</TableCell>
                  <TableCell>{row.kind === "provider" ? row.provider || row.kind : row.kind}</TableCell>
                  <TableCell>{row.locator}</TableCell>
                  <TableCell className="text-mute">{formatDay(row.created_at)}</TableCell>
                  <TableCell>
                    {canDeleteSecret(row, role) ? (
                      <Button
                        type="button"
                        variant="dangerOutline"
                        size="sm"
                        onClick={() => setPending(row)}
                      >
                        Delete
                      </Button>
                    ) : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <ConfirmDialog
        open={pending !== null}
        title="Delete secret"
        description={
          pending
            ? `Delete ${pending.name}. Hosted jobs that already stored this id will fail when a worker opens it.`
            : ""
        }
        confirmLabel="Delete"
        busy={busy}
        onCancel={() => {
          if (!busy) setPending(null);
        }}
        onConfirm={() => void remove()}
      />
    </div>
  );
}
