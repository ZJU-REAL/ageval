import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@ageval/shared/components/ui/select";
import { formatDate } from "@ageval/shared/lib/utils";

export type SlotHistoryEntry = {
  run_id?: string | null;
  status?: string | null;
  started_at?: string | null;
  replaced_at?: string | null;
};

function patchRows(
  currentRunId: string,
  previous: SlotHistoryEntry[] | undefined,
  currentAt?: string | null,
): Array<{ runId: string; patch: number; at: string | null }> {
  const hist = (previous ?? []).filter((p): p is SlotHistoryEntry & { run_id: string } =>
    Boolean(p.run_id && String(p.run_id).trim()),
  );
  const rows = hist.map((item, i) => ({
    runId: String(item.run_id),
    patch: i + 1,
    at: item.started_at ?? null,
  }));
  rows.push({
    runId: currentRunId,
    patch: hist.length + 1,
    at: currentAt ?? null,
  });
  return rows.reverse();
}

export function SlotHistorySelect({
  viewingRunId,
  currentRunId,
  previous,
  currentAt,
  onSelect,
}: {
  viewingRunId: string;
  currentRunId: string | null | undefined;
  previous: SlotHistoryEntry[] | undefined;
  currentAt?: string | null;
  onSelect: (runId: string) => void;
}) {
  if (!currentRunId) return null;
  const rows = patchRows(currentRunId, previous, currentAt);
  if (rows.length < 2) return null;

  return (
    <Select value={viewingRunId} onValueChange={onSelect}>
      <SelectTrigger aria-label="Slot version" className="min-w-0 w-auto">
        <SelectValue />
      </SelectTrigger>
      <SelectContent className="w-max min-w-0">
        {rows.map((row) => (
          <SelectItem
            key={row.runId}
            value={row.runId}
            trailing={row.at ? formatDate(row.at) : undefined}
          >
            {`patch ${row.patch}`}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
