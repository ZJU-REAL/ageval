import { CircleMinus, Settings, Share2, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { AgentSearchModal, attachSpecFromPackage } from "@/components/agent-search-modal";
import { FieldLabel } from "@/components/field-label";
import { LabMark } from "@/components/lab-mark";
import { ModelSearchModal } from "@/components/model-search-modal";
import { BrandMark } from "@/components/brand-mark";
import { Button } from "@/components/ui/button";
import { DashButton, DashMenuItem } from "@/components/ui/dash-button";
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
  latestPackageByDataset,
  listPackages,
  listPackageVersionsWithPerformances,
  listResultShares,
  listSuiteRequests,
  packageDisplayTitle,
  removeResultShare,
  setResultVisibility,
  type JobOverlay,
  type PackageRelease,
  type ResourceRequest,
  type ResultShare,
  type SuiteRow,
  RegistryHttpError,
} from "@/lib/api";
import {
  ATTACH_ROLE_ALL,
  attachSpecBody,
  composeAttachSpec,
  defaultAttachChoice,
  overlayModelsForAttach,
  overlayRoles,
} from "@/lib/agent-attach";
import { markFromPackage } from "@/lib/brand-marks";
import { joinOverlay, loadModelPin, pinnedModel } from "@/lib/model-pin";
import { overlayHarnessIds } from "@/lib/utils";

function SentenceBlank({
  value,
  placeholder,
  icon,
  onClick,
  disabled,
  menu,
}: {
  value: string;
  placeholder: string;
  icon?: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  menu?: ReactNode;
}) {
  const empty = !value.trim();
  return (
    <DashButton
      empty={empty}
      onClick={onClick}
      disabled={disabled}
      menu={menu}
    >
      {icon}
      <span className="truncate">{empty ? placeholder : value}</span>
    </DashButton>
  );
}

function agentSpecId(spec: string): string {
  return attachSpecBody(spec).split("@")[0]?.trim() || "";
}

function agentBlankLabel(spec: string, catalog: PackageRelease[]): string {
  const body = attachSpecBody(spec);
  if (!body) return "";
  const id = body.split("@")[0]?.trim() || body;
  const hit = catalog.find((row) => row.dataset_id === id);
  if (hit) return packageDisplayTitle(hit.dataset_id, hit.display_name);
  return id;
}

function modelBlankLabel(canonical: string): string {
  const id = canonical.trim();
  if (!id) return "";
  return pinnedModel(id, loadModelPin())?.name || id;
}

function agentBlankIcon(spec: string, catalog: PackageRelease[]): ReactNode {
  const body = attachSpecBody(spec);
  if (!body) return null;
  const id = body.split("@")[0]?.trim() || body;
  const hit = catalog.find((row) => row.dataset_id === id);
  if (!hit) return null;
  return <BrandMark mark={markFromPackage(hit)} size={16} />;
}

function modelBlankIcon(canonical: string): ReactNode {
  const info = pinnedModel(canonical.trim(), loadModelPin());
  if (!info?.lab) return null;
  return <LabMark lab={info.lab} size={16} />;
}

function AttachModelMenu({
  selected,
  hits,
  onPick,
}: {
  selected: string;
  hits: string[];
  onPick: (id: string) => void;
}) {
  const pin = loadModelPin();
  const hitSet = new Set(hits);
  const ids = [
    ...hits.filter((id) => pin.models[id]),
    ...Object.keys(pin.models).filter((id) => !hitSet.has(id)),
  ];
  if (!ids.length) {
    return <p className="px-2.5 py-2 text-sm text-mute">No models</p>;
  }
  return (
    <>
      {ids.map((id) => {
        const info = pin.models[id];
        return (
          <DashMenuItem
            key={id}
            selected={selected === id}
            onClick={() => onPick(id)}
          >
            {info?.lab ? <LabMark lab={info.lab} size={16} /> : null}
            <span className="truncate">{info?.name || id}</span>
          </DashMenuItem>
        );
      })}
    </>
  );
}

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
  const [agentCatalog, setAgentCatalog] = useState<PackageRelease[]>([]);
  const [pickAgentOpen, setPickAgentOpen] = useState(false);
  const [pickModelOpen, setPickModelOpen] = useState(false);

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
    listPackages(token, { packageKind: "agent" })
      .then((items) => {
        if (!cancelled) setAgentCatalog(latestPackageByDataset(items));
      })
      .catch(() => {
        if (!cancelled) setAgentCatalog([]);
      });
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
        <FieldLabel>Visibility</FieldLabel>
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
            className="h-8 min-w-0 w-auto"
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
          <FieldLabel
            hint="Which published agent and model this suite run used."
          >
            Attach agent
          </FieldLabel>
          <p className="text-sm leading-9 text-ink">
            Register{" "}
            <SentenceBlank
              value={attachRole || "all"}
              placeholder="role"
              disabled={busy}
              menu={
                <>
                  <DashMenuItem
                    selected={attachRole === ATTACH_ROLE_ALL}
                    onClick={() => onAttachRoleChange(ATTACH_ROLE_ALL)}
                  >
                    all
                  </DashMenuItem>
                  {roleChoices.map((row) => (
                    <DashMenuItem
                      key={row.id}
                      selected={attachRole === row.id}
                      onClick={() => onAttachRoleChange(row.id)}
                    >
                      {row.id}
                    </DashMenuItem>
                  ))}
                </>
              }
            />{" "}
            as{" "}
            <SentenceBlank
              value={agentBlankLabel(agentRef, agentCatalog)}
              placeholder="agent"
              icon={agentBlankIcon(agentRef, agentCatalog)}
              disabled={busy}
              onClick={() => setPickAgentOpen(true)}
              menu={
                agentCatalog.length ? (
                  agentCatalog.map((row) => (
                    <DashMenuItem
                      key={row.dataset_id}
                      selected={agentSpecId(agentRef) === row.dataset_id}
                      onClick={() =>
                        setAgentRef(attachSpecFromPackage(row))
                      }
                    >
                      <BrandMark mark={markFromPackage(row)} size={16} />
                      <span className="truncate">
                        {packageDisplayTitle(row.dataset_id, row.display_name)}
                      </span>
                    </DashMenuItem>
                  ))
                ) : (
                  <p className="px-2.5 py-2 text-sm text-mute">No agents</p>
                )
              }
            />
            &apos;s{" "}
            <SentenceBlank
              value={modelBlankLabel(attachCanonical)}
              placeholder="model"
              icon={modelBlankIcon(attachCanonical)}
              disabled={busy}
              onClick={() => setPickModelOpen(true)}
              menu={
                <AttachModelMenu
                  selected={attachCanonical}
                  hits={attachModelHits}
                  onPick={setAttachCanonical}
                />
              }
            />
            .
          </p>
          <div className="flex justify-end">
            <Button
              type="button"
              size="sm"
              disabled={
                busy || !agentRef.trim() || Boolean(matchingPerformance)
              }
              onClick={() => void attachOrRequest()}
            >
              {matchingPerformance ? "Pending" : "Apply"}
            </Button>
          </div>
          {matchingPerformance ? (
            <p className="text-sm text-body">
              Performance request pending for{" "}
              <span>{matchingPerformance.agent_ref}</span>
              . Waiting on the agent org owner.
            </p>
          ) : pendingPerformance.length > 0 ? (
            <ul className="space-y-1 text-sm text-body">
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
          <AgentSearchModal
            open={pickAgentOpen}
            onClose={() => setPickAgentOpen(false)}
            token={token}
            onPick={(spec) => setAgentRef(spec)}
          />
          <ModelSearchModal
            open={pickModelOpen}
            onClose={() => setPickModelOpen(false)}
            onPick={setAttachCanonical}
          />
        </div>
      ) : null}

      {kind === "suite" &&
      ((complete && boundKind === "release" && !boardListed) ||
        pendingListing) ? (
        <div className="space-y-2">
          <FieldLabel>Public board</FieldLabel>
          {pendingListing ? (
            <p className="text-sm text-pretty break-words text-body">
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
        <FieldLabel hint="Share this suite with an organization or GitHub user.">
          Share with
        </FieldLabel>
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
          kind === "suite" ? undefined : "Who can see this attempt."
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
