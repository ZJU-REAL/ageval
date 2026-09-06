import { CircleMinus, Settings, Share2, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog, Modal } from "@/components/ui/confirm-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast";
import { toastError } from "@/lib/toast-error";
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
  deleteResult,
  isBuiltinPackage,
  listPackageVersionsWithPerformances,
  listResultShares,
  listSuiteRequests,
  removeResultShare,
  setResultVisibility,
  type JobOverlay,
  type ResourceRequest,
  type ResultShare,
  type SuiteRow,
  RegistryHttpError,
} from "@/lib/api";
import { CanonicalSelect } from "@/components/canonical-select";
import {
  ATTACH_ROLE_ALL,
  composeAttachSpec,
  defaultAttachChoice,
  overlayModelsForAttach,
  overlayRoles,
} from "@/lib/agent-attach";
import { joinOverlay, loadModelPin } from "@/lib/model-pin";
import { overlayHarnessIds } from "@/lib/utils";

/** Compare Hub Performance specs: optional `role=`, ignore `+digest`. */
function performanceKey(value: string | undefined): string {
  let text = (value || "").trim();
  if (!text) return "";
  const eq = text.indexOf("=");
  if (eq > 0 && /^[A-Za-z_][A-Za-z0-9_-]*$/.test(text.slice(0, eq).trim())) {
    text = text.slice(eq + 1).trim();
  }
  const plus = text.indexOf("+");
  if (plus >= 0) text = text.slice(0, plus).trim();
  return text.toLowerCase();
}

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
  jobOverlay,
  variant = "menu",
  canDetachPerformance = false,
  onRemovePerformance,
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
  jobOverlay?: JobOverlay | null;
  /** `menu` = overflow + share modal. `panel` = inline share form. `delete` = overflow delete only. */
  variant?: "menu" | "panel" | "delete";
  canDetachPerformance?: boolean;
  onRemovePerformance?: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [shares, setShares] = useState<ResultShare[]>([]);
  const [requests, setRequests] = useState<ResourceRequest[]>([]);
  const [targetType, setTargetType] = useState<"org" | "user">("org");
  const [targetId, setTargetId] = useState("");
  const [shareOpen, setShareOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmDetach, setConfirmDetach] = useState(false);
  const [withAttempts, setWithAttempts] = useState(false);
  const [agentRef, setAgentRef] = useState("");
  const [attachRole, setAttachRole] = useState(ATTACH_ROLE_ALL);
  const [attachCanonical, setAttachCanonical] = useState("");
  const [harnessAgents, setHarnessAgents] = useState<Record<string, string>>(
    {},
  );

  const loadShares = variant === "panel" || shareOpen;

  useEffect(() => {
    if (!loadShares || !canManage || !token || !resultId) {
      return;
    }
    let cancelled = false;
    setShares([]);
    setRequests([]);
    setAgentRef("");
    setAttachRole(ATTACH_ROLE_ALL);
    setAttachCanonical("");
    setHarnessAgents({});
    const roles = kind === "suite" ? overlayRoles(jobOverlay) : [];
    const ids = kind === "suite" ? overlayHarnessIds(jobOverlay) : [];
    const builtinLoad =
      ids.length > 0
        ? Promise.all(
            ids.map((id) =>
              listPackageVersionsWithPerformances(id, token, {
                packageKind: "agent",
              })
                .then((listed) => listed.items.find(isBuiltinPackage) ?? null)
                .catch(() => null),
            ),
          ).then((rows) => {
            const map: Record<string, string> = {};
            ids.forEach((id, index) => {
              const hit = rows[index];
              const agentId = hit?.dataset_id?.trim();
              if (agentId) map[id] = agentId;
            });
            const choice = defaultAttachChoice(
              roles,
              (harness) => map[harness] || "",
            );
            if (!cancelled) {
              setHarnessAgents(map);
              setAttachRole(choice.role);
              setAgentRef(choice.agent);
            }
          })
        : Promise.resolve();
    const shareLoad = listResultShares(kind, resultId, token)
      .then((rows) => {
        if (!cancelled) setShares(rows);
      })
      .catch(() => {
        if (!cancelled) setShares([]);
      });
    const requestLoad =
      kind === "suite"
        ? listSuiteRequests(resultId, token)
            .then((rows) => {
              if (!cancelled) setRequests(rows);
            })
            .catch(() => {
              if (!cancelled) setRequests([]);
            })
        : Promise.resolve();
    void Promise.all([shareLoad, requestLoad, builtinLoad]);
    return () => {
      cancelled = true;
    };
  }, [loadShares, canManage, kind, resultId, token, jobOverlay]);

  const pendingPerformance = useMemo(
    () =>
      requests.filter(
        (row) => row.kind === "agent_performance" && row.status === "pending",
      ),
    [requests],
  );
  const pendingListing = useMemo(
    () =>
      requests.find(
        (row) => row.kind === "leaderboard_list" && row.status === "pending",
      ) ?? null,
    [requests],
  );
  const matchingPerformance = useMemo(
    () => {
      const want = performanceKey(agentRef);
      if (!want) return undefined;
      return pendingPerformance.find((row) => performanceKey(row.agent_ref) === want);
    },
    [pendingPerformance, agentRef],
  );
  const roleChoices = useMemo(
    () => (kind === "suite" ? overlayRoles(jobOverlay) : []),
    [kind, jobOverlay],
  );
  const attachModelHits = useMemo(() => {
    const pin = loadModelPin();
    const hits = new Set<string>();
    for (const overlay of overlayModelsForAttach(jobOverlay, attachRole)) {
      const joined = joinOverlay(overlay, pin).canonical;
      if (joined) hits.add(joined);
    }
    return [...hits];
  }, [jobOverlay, attachRole]);

  useEffect(() => {
    setAttachCanonical((prev) => {
      if (attachModelHits.length === 1 && attachModelHits[0]) {
        return attachModelHits[0];
      }
      if (attachModelHits.includes(prev)) return prev;
      return "";
    });
  }, [attachModelHits]);

  if ((!canManage && !canDetachPerformance) || !token) return null;
  const authToken = token;

  function fail(err: unknown) {
    toastError(err);
  }

  async function reloadRequests() {
    if (kind !== "suite") return;
    try {
      setRequests(await listSuiteRequests(resultId, authToken));
    } catch {
      /* keep last */
    }
  }

  async function changeVisibility(next: "public" | "private") {
    if (next === visibility) return;
    setBusy(true);
    try {
      await setResultVisibility(kind, resultId, next, authToken);
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
    try {
      const row = await addResultShare(
        kind,
        resultId,
        { type: targetType, id },
        authToken,
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
    try {
      await removeResultShare(
        kind,
        resultId,
        { type: row.target_type as "org" | "user", id: row.target_id },
        authToken,
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
    if (kind !== "suite" || pendingListing) return;
    setBusy(true);
    try {
      await applyRequest(
        { kind: "leaderboard_list", suite_run_id: resultId },
        authToken,
      );
      await reloadRequests();
      toast("Listing requested");
    } catch (err) {
      if (err instanceof RegistryHttpError && err.code === "conflict") {
        await reloadRequests();
        toast("Listing request already pending");
      } else {
        fail(err);
      }
    } finally {
      setBusy(false);
    }
  }

  function agentForRole(role: string): string {
    if (role === ATTACH_ROLE_ALL) {
      if (roleChoices.length === 0) return "";
      const first = harnessAgents[roleChoices[0]?.harness || ""];
      if (!first) return "";
      return roleChoices.every(
        (row) => (harnessAgents[row.harness] || "") === first,
      )
        ? first
        : "";
    }
    const hit = roleChoices.find((row) => row.id === role);
    return hit ? harnessAgents[hit.harness] || "" : "";
  }

  function onAttachRoleChange(next: string) {
    setAttachRole(next);
    const agent = agentForRole(next);
    if (agent) setAgentRef(agent);
  }

  async function attachOrRequest() {
    const spec = composeAttachSpec(attachRole, agentRef);
    if (!spec || kind !== "suite" || matchingPerformance) return;
    setBusy(true);
    try {
      const row = await applyRequest(
        {
          kind: "agent_performance",
          suite_run_id: resultId,
          agent: spec,
          ...(attachCanonical ? { canonical_model: attachCanonical } : {}),
        },
        authToken,
      );
      if (row.direct_attach || row.attached) {
        onAttached?.(row as Partial<SuiteRow>);
        toast("Agent attached");
        setAgentRef("");
      } else {
        await reloadRequests();
        toast("Performance requested");
      }
    } catch (err) {
      if (err instanceof RegistryHttpError && err.code === "conflict") {
        await reloadRequests();
        toast("Performance request already pending");
      } else {
        fail(err);
      }
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await deleteResult(kind, resultId, authToken, {
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

  const shareForm = (
    <div className="space-y-4">
      <div className="space-y-2">
        <p className="text-xs font-medium text-mute uppercase tracking-wide">
          Visibility
        </p>
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
            className="h-8 min-w-0 w-auto text-xs"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="public">public</SelectItem>
            <SelectItem value="private">private</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {kind === "suite" ? (
        <div className="space-y-2">
          <p className="text-xs font-medium text-mute uppercase tracking-wide">
            Attach agent
          </p>
          <div className="space-y-2">
            {roleChoices.length > 0 ? (
              <Select
                value={attachRole}
                onValueChange={onAttachRoleChange}
                disabled={busy}
              >
                <SelectTrigger
                  aria-label="Attach role"
                  className="h-8 min-w-0 w-auto shrink-0 text-xs"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ATTACH_ROLE_ALL} mono={false}>
                    all
                  </SelectItem>
                  {roleChoices.map((row) => (
                    <SelectItem key={row.id} value={row.id} mono={false}>
                      {row.id}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : null}
            <CanonicalSelect
              value={attachCanonical}
              onChange={setAttachCanonical}
              hits={attachModelHits}
              allowEmpty={attachModelHits.length !== 1}
              includePin
              allowCustom
              variant="panel"
              disabled={busy}
            />
            <div className="flex flex-wrap items-center gap-2">
              <Input
                value={agentRef}
                onChange={(e) => setAgentRef(e.target.value)}
                placeholder="org/name@version"
                className="h-8 min-w-0 flex-1 text-xs"
                disabled={busy}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void attachOrRequest();
                }}
              />
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={busy || !agentRef.trim() || Boolean(matchingPerformance)}
                onClick={() => void attachOrRequest()}
              >
                {matchingPerformance ? "Pending" : "Attach"}
              </Button>
            </div>
          </div>
          {matchingPerformance ? (
            <p className="text-xs text-body">
              Performance request pending for{" "}
              <span>{matchingPerformance.agent_ref}</span>
              . Waiting on the agent org owner.
            </p>
          ) : pendingPerformance.length > 0 ? (
            <ul className="space-y-1 text-xs text-body">
              {pendingPerformance.map((row) => (
                <li key={row.request_id}>
                  Pending:{" "}
                  <span>
                    {row.agent_ref || "agent"}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {kind === "suite" &&
      ((complete && boundKind === "release" && !boardListed) ||
        pendingListing) ? (
        <div className="space-y-2">
          <p className="text-xs font-medium text-mute uppercase tracking-wide">
            Public board
          </p>
          {pendingListing ? (
            <p className="text-xs text-pretty break-words text-body">
              Listing request pending. Waiting on the dataset org owner.
            </p>
          ) : (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => void requestListing()}
            >
              Request listing
            </Button>
          )}
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
            <SelectTrigger className="h-8 min-w-0 w-auto text-xs">
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
            className="h-8 min-w-0 flex-1 text-xs"
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
          <ul className="divide-y divide-hairline rounded-[14px] border border-hairline bg-canvas">
            {shares.map((row) => (
              <li
                key={`${row.target_type}:${row.target_id}`}
                className="flex items-center justify-between gap-2 px-3 py-1.5"
              >
                <span className="text-xs text-body">
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
    </div>
  );

  if (variant === "panel") return shareForm;

  const showShare = variant === "menu";

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Job settings"
            aria-haspopup="menu"
            className="h-8 w-8 text-mute"
          >
            <Settings className="h-4 w-4" aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {showShare && canManage ? (
            <DropdownMenuItem
              onSelect={() => {
                setShareOpen(true);
              }}
            >
              <Share2 className="h-3.5 w-3.5" aria-hidden />
              Share
            </DropdownMenuItem>
          ) : null}
          {canDetachPerformance && onRemovePerformance ? (
            <DropdownMenuItem
              onSelect={() => {
                setConfirmDetach(true);
              }}
            >
              <CircleMinus className="h-3.5 w-3.5" aria-hidden />
              Remove
            </DropdownMenuItem>
          ) : null}
          {showShare && canManage ? <DropdownMenuSeparator /> : null}
          {canManage ? (
            <DropdownMenuItem
              className="text-error focus:text-error data-[highlighted]:text-error"
              onSelect={() => {
                setConfirmDelete(true);
              }}
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden />
              Delete
            </DropdownMenuItem>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>

      {showShare ? (
      <Modal
        open={shareOpen}
        title="Share"
        description={
          kind === "suite"
            ? "Who can see this suite, and whether it is listed."
            : "Who can see this attempt."
        }
        onClose={() => {
          if (!busy) {
            setShareOpen(false);
          }
        }}
      >
        {shareForm}
      </Modal>
      ) : null}

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
        onCancel={() => {
          if (!busy) {
            setConfirmDelete(false);
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

      <ConfirmDialog
        open={confirmDetach}
        title="Remove"
        description="Un-attach this role. You can attach it again. Plaza collection still follows the Collect setting. Listing and PASS are unchanged."
        confirmLabel="Remove"
        confirmVariant="default"
        busy={busy}
        onCancel={() => {
          if (!busy) setConfirmDetach(false);
        }}
        onConfirm={() => {
          setConfirmDetach(false);
          onRemovePerformance?.();
        }}
      />
    </>
  );
}
