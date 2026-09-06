import { Inbox, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Navigate } from "react-router-dom";

import { EmptyState, LoadingState } from "@/components/empty-state";
import { PageHead } from "@/components/page-head";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { toast } from "@/components/ui/toast";
import { toastError } from "@/lib/toast-error";
import {
  decideRequests,
  hideInboxRequests,
  listInbox,
  type ResourceRequest,
} from "@/lib/api";
import { getToken } from "@/lib/auth";
import { rememberReturnPath } from "@/lib/return-path";
import { sortRows, useTableSort } from "@/components/sortable-head";
import { formatDate } from "@/lib/utils";
import { CanonicalSelect } from "@/components/canonical-select";
import { PeekHost, type PeekTarget } from "@/peek-host";

function matchesQuery(row: ResourceRequest, query: string): boolean {
  if (!query) return true;
  const hay = [
    row.kind,
    row.status,
    row.dataset_id,
    row.suite_run_id,
    row.applicant,
    row.agent_ref || "",
    row.owner_org_id,
  ]
    .join(" ")
    .toLowerCase();
  return hay.includes(query);
}

function kindLabel(kind: string): string {
  if (kind === "leaderboard_list") return "Listing";
  if (kind === "agent_performance") return "Performance";
  return kind;
}

function requestColumnValue(row: ResourceRequest, key: string): unknown {
  switch (key) {
    case "status":
      return row.status || "";
    case "kind":
      return kindLabel(row.kind);
    case "dataset":
      return row.dataset_id || "";
    case "suite":
      return row.suite_run_id || "";
    case "applicant":
      return row.applicant || "";
    case "agent":
      return row.agent_ref || "";
    case "decided":
      return row.decided_at ?? row.created_at ?? null;
    default:
      return null;
  }
}

function compareInboxHistory(a: ResourceRequest, b: ResourceRequest): number {
  return (
    (b.decided_at || b.created_at || 0) - (a.decided_at || a.created_at || 0)
  );
}

function PeekCell({
  label,
  onPeek,
}: {
  label: string;
  onPeek: () => void;
}) {
  return (
    <button
      type="button"
      className="text-link hover:text-link-deep hover:underline underline-offset-2"
      onClick={onPeek}
    >
      {label}
    </button>
  );
}

export function InboxPage() {
  const token = getToken();
  const [rows, setRows] = useState<ResourceRequest[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [kindFilter, setKindFilter] = useState("all");
  const [datasetFilter, setDatasetFilter] = useState("all");
  const [peek, setPeek] = useState<PeekTarget | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [confirmHide, setConfirmHide] = useState(false);
  const [approveCanonical, setApproveCanonical] = useState("");
  const pendingSort = useTableSort();
  const historySort = useTableSort("decided", "desc");

  const closePeek = useCallback(() => setPeek(null), []);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setLoading(true);
    listInbox(token)
      .then((items) => {
        if (cancelled) return;
        setRows(items);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        toastError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const needle = query.trim().toLowerCase();
  const filtered = useMemo(
    () =>
      rows.filter((row) => {
        if (!matchesQuery(row, needle)) return false;
        if (kindFilter !== "all" && row.kind !== kindFilter) return false;
        if (datasetFilter !== "all" && row.dataset_id !== datasetFilter) return false;
        return true;
      }),
    [rows, needle, kindFilter, datasetFilter],
  );
  const pending = useMemo(
    () =>
      sortRows(
        filtered.filter((row) => row.status === "pending"),
        pendingSort.sortKey,
        pendingSort.sortDir,
        requestColumnValue,
      ),
    [filtered, pendingSort.sortKey, pendingSort.sortDir],
  );
  const history = useMemo(
    () =>
      sortRows(
        filtered.filter((row) => row.status !== "pending"),
        historySort.sortKey,
        historySort.sortDir,
        requestColumnValue,
        compareInboxHistory,
      ),
    [filtered, historySort.sortKey, historySort.sortDir],
  );
  const pendingIds = useMemo(() => pending.map((r) => r.request_id), [pending]);
  const historyIds = useMemo(() => history.map((r) => r.request_id), [history]);
  const kindOptions = useMemo(() => {
    const set = new Set(rows.map((row) => row.kind).filter(Boolean));
    return [...set].sort();
  }, [rows]);
  const datasetOptions = useMemo(() => {
    const set = new Set(rows.map((row) => row.dataset_id).filter(Boolean));
    return [...set].sort();
  }, [rows]);
  const selectedPerformance = useMemo(
    () =>
      rows.filter(
        (row) =>
          selected.has(row.request_id) &&
          row.kind === "agent_performance" &&
          row.status === "pending",
      ),
    [rows, selected],
  );
  const selectedProposed = useMemo(() => {
    const hits = new Set<string>();
    for (const row of selectedPerformance) {
      const canonical = (row.canonical_model || "").trim();
      if (canonical) hits.add(canonical);
    }
    return [...hits];
  }, [selectedPerformance]);
  const needsCanonical = selectedPerformance.length > 0;
  const noneSelected = pendingIds.every((id) => !selected.has(id));

  useEffect(() => {
    setApproveCanonical((prev) => {
      if (selectedProposed.length === 1 && selectedProposed[0]) {
        return selectedProposed[0];
      }
      if (selectedProposed.includes(prev)) return prev;
      return "";
    });
  }, [selectedProposed]);

  if (!token) {
    rememberReturnPath("/inbox");
    return <Navigate to="/login" replace />;
  }

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function peekDataset(row: ResourceRequest) {
    setPeek({ type: "dataset", datasetId: row.dataset_id });
  }

  function peekSuite(row: ResourceRequest) {
    setPeek({
      type: "suite",
      datasetId: row.dataset_id,
      suiteRunId: row.suite_run_id,
    });
  }

  function peekApplicant(row: ResourceRequest) {
    setPeek({ type: "user", login: row.applicant });
  }

  async function decide(action: "approve" | "reject") {
    const ids = pendingIds.filter((id) => selected.has(id));
    if (!ids.length) return;
    setBusy(true);
    try {
      const payload = await decideRequests(
        ids,
        action,
        token,
        action === "approve" && approveCanonical
          ? { canonical_model: approveCanonical }
          : undefined,
      );
      const returned = payload.items || [];
      setRows((prev) => {
        const byId = new Map(returned.map((item) => [item.request_id, item]));
        return prev.map((row) => byId.get(row.request_id) || row);
      });
      setSelected(new Set());
      toast(action === "approve" ? "Requests approved" : "Requests rejected");
    } catch (err) {
      toastError(err);
    } finally {
      setBusy(false);
    }
  }

  async function hideHistory() {
    if (!historyIds.length) return;
    setBusy(true);
    try {
      await hideInboxRequests(historyIds, token);
      const drop = new Set(historyIds);
      setRows((prev) => prev.filter((row) => !drop.has(row.request_id)));
      setConfirmHide(false);
      toast("Hidden from your History");
    } catch (err) {
      toastError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHead
        title="Inbox"
        sub="Pending listing and Performance requests you can decide."
      />

      <div className="space-y-6">
        <div className="flex flex-wrap items-center gap-2">
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search requests"
            aria-label="Search requests"
            className="min-w-0 flex-1 basis-56"
          />
          <Select value={kindFilter} onValueChange={setKindFilter}>
            <SelectTrigger className="h-8 min-w-[8rem]" aria-label="Kind">
              <SelectValue placeholder="Kind" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all" mono={false}>
                All kinds
              </SelectItem>
              {kindOptions.map((kind) => (
                <SelectItem key={kind} value={kind} mono={false}>
                  {kindLabel(kind)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={datasetFilter} onValueChange={setDatasetFilter}>
            <SelectTrigger className="h-8 min-w-[10rem]" aria-label="Dataset">
              <SelectValue placeholder="Dataset" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all" mono={false}>
                All datasets
              </SelectItem>
              {datasetOptions.map((datasetId) => (
                <SelectItem key={datasetId} value={datasetId} mono={false}>
                  {datasetId}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="ml-auto flex items-center gap-2">
            <CanonicalSelect
              value={approveCanonical}
              onChange={setApproveCanonical}
              hits={selectedProposed}
              allowEmpty={!needsCanonical}
              includePin
              disabled={busy || noneSelected}
              label="Canonical model"
            />
            <Button
              type="button"
              size="sm"
              disabled={
                busy ||
                noneSelected ||
                (needsCanonical && !approveCanonical.trim())
              }
              onClick={() => void decide("approve")}
            >
              Approve
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={busy || noneSelected}
              onClick={() => void decide("reject")}
            >
              Reject
            </Button>
          </div>
        </div>

        {loading ? (
          <LoadingState label="Loading inbox" />
        ) : pending.length === 0 ? (
          <EmptyState
            icon={Inbox}
            glyph="inbox"
            title="No pending requests"
            caption="Listing and Performance requests show up here."
            className={history.length > 0 ? "min-h-0 flex-none py-10" : undefined}
          />
        ) : (
          <div className="blob-panel overflow-hidden">
            <Table className="table-auto">
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12 px-3 overflow-visible">
                    <input
                      type="checkbox"
                      aria-label="Select all pending"
                      checked={
                        pendingIds.length > 0 &&
                        pendingIds.every((id) => selected.has(id))
                      }
                      onChange={() => {
                        setSelected((prev) =>
                          prev.size === pendingIds.length ? new Set() : new Set(pendingIds),
                        );
                      }}
                    />
                  </TableHead>
                  <TableHead>{pendingSort.head("kind", "Kind")}</TableHead>
                  <TableHead>{pendingSort.head("dataset", "Dataset")}</TableHead>
                  <TableHead>{pendingSort.head("suite", "Suite")}</TableHead>
                  <TableHead>
                    {pendingSort.head("applicant", "Applicant")}
                  </TableHead>
                  <TableHead>{pendingSort.head("agent", "Agent")}</TableHead>
                  <TableHead>Model</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pending.map((row) => (
                  <TableRow key={row.request_id}>
                    <TableCell className="w-12 px-3 overflow-visible">
                      <input
                        type="checkbox"
                        aria-label={`Select ${row.request_id}`}
                        checked={selected.has(row.request_id)}
                        onChange={() => toggle(row.request_id)}
                      />
                    </TableCell>
                    <TableCell className="text-body">{kindLabel(row.kind)}</TableCell>
                    <TableCell>
                      <PeekCell label={row.dataset_id} onPeek={() => peekDataset(row)} />
                    </TableCell>
                    <TableCell>
                      <PeekCell label={row.suite_run_id} onPeek={() => peekSuite(row)} />
                    </TableCell>
                    <TableCell>
                      <PeekCell label={row.applicant} onPeek={() => peekApplicant(row)} />
                    </TableCell>
                    <TableCell>
                      {row.agent_ref || "—"}
                    </TableCell>
                    <TableCell className="text-body">
                      {row.canonical_model || "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        {history.length > 0 ? (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-medium text-ink">History</h2>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="ml-auto h-8 w-8 text-mute"
                aria-label="Hide processed requests from your inbox"
                disabled={busy}
                onClick={() => setConfirmHide(true)}
              >
                <Trash2 className="h-4 w-4" aria-hidden />
              </Button>
            </div>
            <div className="blob-panel overflow-hidden">
              <Table className="table-auto">
                <TableHeader>
                  <TableRow>
                    <TableHead>{historySort.head("status", "Status")}</TableHead>
                    <TableHead>{historySort.head("kind", "Kind")}</TableHead>
                    <TableHead>
                      {historySort.head("dataset", "Dataset")}
                    </TableHead>
                    <TableHead>{historySort.head("suite", "Suite")}</TableHead>
                    <TableHead>
                      {historySort.head("applicant", "Applicant")}
                    </TableHead>
                    <TableHead>{historySort.head("agent", "Agent")}</TableHead>
                    <TableHead>
                      {historySort.head("decided", "Decided")}
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {history.map((row) => (
                    <TableRow key={row.request_id}>
                      <TableCell className="text-body">{row.status}</TableCell>
                      <TableCell className="text-body">{kindLabel(row.kind)}</TableCell>
                      <TableCell>
                        <PeekCell label={row.dataset_id} onPeek={() => peekDataset(row)} />
                      </TableCell>
                      <TableCell>
                        <PeekCell label={row.suite_run_id} onPeek={() => peekSuite(row)} />
                      </TableCell>
                      <TableCell>
                        <PeekCell label={row.applicant} onPeek={() => peekApplicant(row)} />
                      </TableCell>
                      <TableCell>
                        {row.agent_ref || "—"}
                      </TableCell>
                      <TableCell className="text-mute">
                        {formatDate(row.decided_at ?? row.created_at)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        ) : null}

        <ConfirmDialog
          open={confirmHide}
          title="Hide History"
          description="Hide these processed requests from your inbox? Other owners still see them. Listing and attach are unchanged."
          confirmLabel="Hide"
          confirmVariant="default"
          busy={busy}
          onCancel={() => setConfirmHide(false)}
          onConfirm={() => void hideHistory()}
        />

        {peek ? <PeekHost peek={peek} onClose={closePeek} /> : null}
      </div>
    </>
  );
}
