import { HarnessLabel } from "@ageval/shared/components/harness-label";
import { HoverTip } from "@ageval/shared/components/hover-tip";
import { ModelLabel } from "@ageval/shared/components/model-label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@ageval/shared/components/ui/table";
import type { Trial } from "@ageval/shared/lib/trial-types";

/** Actors: Role | Harness | Model | Time | Usage — observational ≠ PASS */
export function ActorsTable({
  actors,
  harnessTo,
  modelTo,
}: {
  actors: NonNullable<Trial["actors"]>;
  /** Hub catalog jump. Viewer omits this (icons only). */
  harnessTo?: (agent: string) => string | undefined;
  modelTo?: (model: string | null | undefined) => string | undefined;
}) {
  if (actors.length === 0) return null;

  return (
    <div className="space-y-1.5">
      <div className="blob-panel overflow-hidden overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Role</TableHead>
              <TableHead>Harness</TableHead>
              <TableHead>Model</TableHead>
              <TableHead>Time</TableHead>
              <TableHead>Usage</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {actors.map((a) => (
              <TableRow key={a.profile_id || `${a.role}-${a.agent}`}>
                <TableCell className="font-medium">
                  {a.role}
                </TableCell>
                <TableCell className="text-body">
                  <HarnessLabel value={a.agent} to={harnessTo?.(a.agent)} />
                </TableCell>
                <TableCell className="text-mute">
                  <ModelLabel
                    value={a.model}
                    effort={a.reasoning_effort}
                    to={modelTo?.(a.model)}
                  />
                </TableCell>
                <TableCell className="tabular-nums text-body">
                  {a.time_label || "-"}
                </TableCell>
                <TableCell className="text-mute max-w-[36ch]">
                  {a.usage_label ? (
                    <HoverTip content="Observational usage (tokens/cost); not PASS authority. Cache hit = cached_read / input when present. Session-last invoke for cumulative fields.">
                      <span className="block truncate">{a.usage_label}</span>
                    </HoverTip>
                  ) : (
                    "-"
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <p className="text-xs text-mute">
        Time sums inv latency. Usage is last-invoke session snapshot
        (tokens/cost); trajectory and usage are not PASS.
      </p>
    </div>
  );
}
