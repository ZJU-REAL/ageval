import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  addResultShare,
  applyRequest,
  attachSuiteAgent,
  deleteResult,
  listResultShares,
  removeResultShare,
  setResultVisibility,
  type ResultShare,
  type SuiteRow,
  RegistryHttpError,
} from "@/lib/api";

export function ResultOwnerOps({
  kind,
  resultId,
  visibility,
  complete,
  boundKind,
  boardListed,
  canManage,
  token,
  onVisibility,
  onDeleted,
  onAttached,
}: {
  kind: "attempt" | "suite";
  resultId: string;
  visibility?: string;
  complete?: boolean;
  boundKind?: string;
  boardListed?: boolean;
  canManage: boolean;
  token: string | null;
  onVisibility?: (next: "public" | "private") => void;
  onDeleted?: () => void;
  onAttached?: (suite: Partial<SuiteRow>) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [shares, setShares] = useState<ResultShare[]>([]);
  const [targetType, setTargetType] = useState<"org" | "user">("org");
  const [targetId, setTargetId] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [withAttempts, setWithAttempts] = useState(false);
  const [agentRef, setAgentRef] = useState("");

  useEffect(() => {
    if (!canManage || !token || !resultId) {
      setShares([]);
      return;
    }
    let cancelled = false;
    listResultShares(kind, resultId, token)
      .then((rows) => {
        if (!cancelled) setShares(rows);
      })
      .catch(() => {
        if (!cancelled) setShares([]);
      });
    return () => {
      cancelled = true;
    };
  }, [canManage, kind, resultId, token]);

  if (!canManage || !token) return null;

  function fail(err: unknown) {
    if (err instanceof RegistryHttpError) {
      setError(`${err.code}: ${err.message}`);
    } else {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function changeVisibility(next: "public" | "private") {
    if (next === visibility) return;
    setBusy(true);
    setError(null);
    try {
      await setResultVisibility(kind, resultId, next, token);
      onVisibility?.(next);
      toast(`Visibility set to ${next}`);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function share() {
    const id = targetId.trim();
    if (!id) return;
    setBusy(true);
    setError(null);
    try {
      const row = await addResultShare(
        kind,
        resultId,
        { type: targetType, id },
        token,
      );
      setShares((prev) => [...prev, row]);
      setTargetId("");
      toast("Share added");
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function unshare(row: ResultShare) {
    setBusy(true);
    setError(null);
    try {
      await removeResultShare(
        kind,
        resultId,
        { type: row.target_type as "org" | "user", id: row.target_id },
        token,
      );
      setShares((prev) =>
        prev.filter(
          (s) =>
            !(s.target_type === row.target_type && s.target_id === row.target_id),
        ),
      );
      toast("Share removed");
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function requestListing() {
    if (kind !== "suite") return;
    setBusy(true);
    setError(null);
    try {
      await applyRequest(
        { kind: "leaderboard_list", suite_run_id: resultId },
        token,
      );
      toast("Listing requested");
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function requestAppearance() {
    const spec = agentRef.trim();
    if (!spec || kind !== "suite") return;
    setBusy(true);
    setError(null);
    try {
      const row = await applyRequest(
        { kind: "agent_appearance", suite_run_id: resultId, agent: spec },
        token,
      );
      if (row.direct_attach || row.attached) {
        onAttached?.(row);
        toast("Agent ref attached");
      } else {
        toast("Appearance requested");
      }
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function attachAgent() {
    const spec = agentRef.trim();
    if (!spec || kind !== "suite") return;
    setBusy(true);
    setError(null);
    try {
      const row = await attachSuiteAgent(resultId, spec, token);
      onAttached?.(row);
      toast(row.idempotent ? "Agent ref already attached" : "Agent ref attached");
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await deleteResult(kind, resultId, token, {
        withAttempts: kind === "suite" && withAttempts,
      });
      setConfirmDelete(false);
      toast("Result deleted");
      onDeleted?.();
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  const current = visibility === "public" ? "public" : "private";

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={current}
          onValueChange={(value) => {
            if (value === "public" || value === "private") {
              void changeVisibility(value);
            }
          }}
          disabled={busy}
        >
          <SelectTrigger
            aria-label="Result visibility"
            className="h-8 min-w-0 w-auto font-mono text-xs"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="public">public</SelectItem>
            <SelectItem value="private">private</SelectItem>
          </SelectContent>
        </Select>
        <Button
          type="button"
          size="sm"
          variant="dangerOutline"
          disabled={busy}
          onClick={() => {
            setError(null);
            setConfirmDelete(true);
          }}
        >
          Delete
        </Button>
      </div>
      <ConfirmDialog
        open={confirmDelete}
        title={kind === "suite" ? "Delete suite result" : "Delete attempt"}
        description={
          kind === "suite"
            ? "This removes the suite row from the Registry. Linked Attempts stay unless you also delete them below."
            : "This removes this Attempt result and its uploaded evidence from the Registry."
        }
        confirmLabel="Delete"
        busy={busy}
        error={error}
        onCancel={() => {
          if (!busy) {
            setConfirmDelete(false);
            setError(null);
          }
        }}
        onConfirm={() => void remove()}
      >
        {kind === "suite" ? (
          <label className="flex items-center gap-2 text-sm text-body">
            <input
              type="checkbox"
              checked={withAttempts}
              disabled={busy}
              onChange={(e) => setWithAttempts(e.target.checked)}
            />
            Also delete linked Attempts
          </label>
        ) : null}
      </ConfirmDialog>

      {kind === "suite" ? (
        <div className="space-y-2">
          <p className="text-xs font-medium text-mute uppercase tracking-wide">
            Attach published agent
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              value={agentRef}
              onChange={(e) => setAgentRef(e.target.value)}
              placeholder="org/name@version"
              className="h-8 w-56 font-mono text-xs"
              disabled={busy}
              onKeyDown={(e) => {
                if (e.key === "Enter") void attachAgent();
              }}
            />
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={busy || !agentRef.trim()}
              onClick={() => void attachAgent()}
            >
              Attach
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={busy || !agentRef.trim()}
              onClick={() => void requestAppearance()}
            >
              Request appearance
            </Button>
          </div>
          {complete && boundKind === "release" && !boardListed ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => void requestListing()}
            >
              Request listing
            </Button>
          ) : null}
          <p className="text-xs text-mute">
            Attach stamps provenance on the stored overlay. Listing and
            appearance requests go to the Dataset or Agent org owner Inbox.
            Does not rewrite lock or fingerprint.
          </p>
        </div>
      ) : null}

      <div className="space-y-2">
        <p className="text-xs font-medium text-mute uppercase tracking-wide">
          Share with
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={targetType}
            onValueChange={(value) => {
              if (value === "org" || value === "user") setTargetType(value);
            }}
            disabled={busy}
          >
            <SelectTrigger className="h-8 min-w-0 w-auto font-mono text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="org">org</SelectItem>
              <SelectItem value="user">user</SelectItem>
            </SelectContent>
          </Select>
          <Input
            value={targetId}
            onChange={(e) => setTargetId(e.target.value)}
            placeholder={targetType === "org" ? "org-id" : "github-login"}
            className="h-8 w-40 font-mono text-xs"
            disabled={busy}
            onKeyDown={(e) => {
              if (e.key === "Enter") void share();
            }}
          />
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={busy || !targetId.trim()}
            onClick={() => void share()}
          >
            Share
          </Button>
        </div>
        {shares.length === 0 ? (
          <p className="text-xs text-mute">Not shared with anyone yet.</p>
        ) : (
          <ul className="divide-y divide-hairline rounded-[6px] border border-hairline">
            {shares.map((row) => (
              <li
                key={`${row.target_type}:${row.target_id}`}
                className="flex items-center justify-between gap-2 px-3 py-1.5"
              >
                <span className="font-mono text-xs text-body">
                  {row.target_type}/{row.target_id}
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={() => void unshare(row)}
                >
                  Revoke
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
      {error ? <p className="text-xs font-mono text-error">{error}</p> : null}
    </div>
  );
}
