import { useEffect, useMemo, useState } from "react";
import { Link, Navigate } from "react-router-dom";

import { PageHead } from "@/components/page-head";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { toast } from "@/components/ui/toast";
import {
  decideRequests,
  encodeDatasetId,
  listInbox,
  type ResourceRequest,
  RegistryHttpError,
} from "@/lib/api";
import { getToken } from "@/lib/auth";
import { rememberReturnPath } from "@/lib/return-path";

export function InboxPage() {
  const token = getToken();
  const [rows, setRows] = useState<ResourceRequest[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setLoading(true);
    listInbox(token)
      .then((items) => {
        if (cancelled) return;
        setRows(items);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof RegistryHttpError) {
          setError(`${err.code}: ${err.message}`);
        } else {
          setError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const allIds = useMemo(() => rows.map((r) => r.request_id), [rows]);

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

  async function decide(action: "approve" | "reject") {
    const ids = [...selected];
    if (!ids.length) return;
    setBusy(true);
    setError(null);
    try {
      await decideRequests(ids, action, token);
      setRows((prev) => prev.filter((r) => !ids.includes(r.request_id)));
      setSelected(new Set());
      toast(action === "approve" ? "Requests approved" : "Requests rejected");
    } catch (err) {
      if (err instanceof RegistryHttpError) {
        setError(`${err.code}: ${err.message}`);
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHead
        title="Inbox"
        sub="Pending listing and appearance requests you can decide."
        actions={
          <div className="flex items-center gap-2">
            <Button
              type="button"
              size="sm"
              disabled={busy || selected.size === 0}
              onClick={() => void decide("approve")}
            >
              Approve
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={busy || selected.size === 0}
              onClick={() => void decide("reject")}
            >
              Reject
            </Button>
          </div>
        }
      />
      {error ? <p className="text-sm font-mono text-error">{error}</p> : null}
      {loading ? (
        <p className="text-sm text-mute">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-mute">No pending requests.</p>
      ) : (
        <div className="overflow-hidden rounded-[8px] border border-hairline">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">
                  <input
                    type="checkbox"
                    aria-label="Select all"
                    checked={selected.size === allIds.length && allIds.length > 0}
                    onChange={() => {
                      setSelected((prev) =>
                        prev.size === allIds.length ? new Set() : new Set(allIds),
                      );
                    }}
                  />
                </TableHead>
                <TableHead>Kind</TableHead>
                <TableHead>Dataset</TableHead>
                <TableHead>Suite</TableHead>
                <TableHead>Applicant</TableHead>
                <TableHead>Agent</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.request_id}>
                  <TableCell>
                    <input
                      type="checkbox"
                      aria-label={`Select ${row.request_id}`}
                      checked={selected.has(row.request_id)}
                      onChange={() => toggle(row.request_id)}
                    />
                  </TableCell>
                  <TableCell className="font-mono text-xs">{row.kind}</TableCell>
                  <TableCell className="font-mono text-xs">
                    <Link
                      to={`/datasets/${encodeDatasetId(row.dataset_id)}?tab=leaderboard&suite=${encodeURIComponent(row.suite_run_id)}`}
                      className="hover:underline underline-offset-2"
                    >
                      {row.dataset_id}
                    </Link>
                  </TableCell>
                  <TableCell className="font-mono text-xs">{row.suite_run_id}</TableCell>
                  <TableCell className="font-mono text-xs">{row.applicant}</TableCell>
                  <TableCell className="font-mono text-xs">
                    {row.agent_ref || "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
