import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { BrandMark } from "@/components/brand-mark";
import {
  GroupedTables,
  type GroupedTableGroup,
} from "@/components/grouped-tables";
import { OfficialMark } from "@/components/official-mark";
import {
  SortableHead,
  nextSort,
  sortRows,
  type SortDir,
} from "@/components/sortable-head";
import {
  TableBody,
  TableCell,
  TableHead,
  TableRow,
} from "@/components/ui/table";
import { resolveEntityMark } from "@/lib/brand-marks";
import {
  encodeDatasetId,
  splitPackageId,
  type OrgRow,
  type PackageRelease,
} from "@/lib/api";
import { INTERNAL_LINK_CLASS } from "@/lib/links";
import { formatDay } from "@/lib/utils";

const CELL_MUTE = "whitespace-nowrap text-sm text-mute tabular-nums";
const CELL_INK = "whitespace-nowrap text-sm text-ink tabular-nums";

function datasetLeaf(row: PackageRelease): string {
  return row.display_name?.trim() || splitPackageId(row.dataset_id).name;
}

export const DATASET_ORG_CHROME_ID = "datasets-chrome";
export const DATASET_ORG_PIN_SLOT_ID = "datasets-org-pin";

const COLS_3 = (
  <colgroup>
    <col className="w-[22%]" />
    <col className="w-[68%]" />
    <col className="w-[10%]" />
  </colgroup>
);
const COLS_4 = (
  <colgroup>
    <col className="w-[22%]" />
    <col className="w-[50%]" />
    <col className="w-[10%]" />
    <col className="w-[18%]" />
  </colgroup>
);

const STICKY_TH =
  "sticky z-10 bg-canvas-soft top-[var(--datasets-stick-top,0px)]";

export function DatasetOrgHead({
  orgId,
  name,
  info,
  official,
  count,
}: {
  orgId: string;
  name: string;
  info?: OrgRow;
  official: boolean;
  count: number;
}) {
  const mark = resolveEntityMark({
    iconKey: info?.icon_key,
    iconGithub: info?.icon_github,
    displayName: name,
  });
  return (
    <div className="flex items-center gap-2">
      <BrandMark mark={mark} size={22} title={name} />
      <h3 className="text-base font-semibold text-ink">
        {orgId ? (
          <Link
            to={`/organizations/${encodeURIComponent(orgId)}`}
            className="inline-flex items-center gap-1 hover:text-link-deep focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-link/70"
          >
            {name}
          </Link>
        ) : (
          name
        )}
      </h3>
      {orgId && official ? <OfficialMark kind="org" /> : null}
      {info?.description ? (
        <span className="hidden min-w-0 flex-1 truncate text-sm text-mute sm:block">
          {info.description}
        </span>
      ) : null}
      <span className="ml-auto text-xs text-mute tabular-nums">{count}</span>
    </div>
  );
}

function sortValue(row: PackageRelease, key: string): string | number | null {
  if (key === "dataset") return datasetLeaf(row);
  if (key === "tasks")
    return typeof row.task_count === "number" ? row.task_count : null;
  if (key === "updated") return row.created_at ?? null;
  return null;
}

function fallback(a: PackageRelease, b: PackageRelease): number {
  const cmp = datasetLeaf(a).localeCompare(datasetLeaf(b));
  return cmp !== 0 ? cmp : a.dataset_id.localeCompare(b.dataset_id);
}

export function DatasetOrgTables({
  rows,
  orgs,
  showUpdated,
}: {
  rows: PackageRelease[];
  orgs: Map<string, OrgRow>;
  showUpdated: boolean;
}) {
  const [sortKey, setSortKey] = useState<string | null>("dataset");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  function onSort(key: string) {
    const next = nextSort(sortKey, sortDir, key);
    setSortKey(next.dir ? next.key : null);
    setSortDir(next.dir);
  }

  function head(key: string, label: string) {
    return (
      <SortableHead
        label={label}
        active={sortKey === key}
        dir={sortKey === key ? sortDir : null}
        onClick={() => onSort(key)}
      />
    );
  }

  useEffect(() => {
    if (sortKey === "updated" && !showUpdated) {
      setSortKey("dataset");
      setSortDir("asc");
    }
  }, [showUpdated, sortKey]);

  const orgName = (orgId: string) =>
    orgs.get(orgId)?.display_name || orgs.get(orgId)?.name || orgId;

  const byOrg = new Map<string, PackageRelease[]>();
  for (const row of rows) {
    const org = row.org_id || "";
    const list = byOrg.get(org) ?? [];
    list.push(row);
    byOrg.set(org, list);
  }
  const orgIds = [...byOrg.keys()].sort((a, b) => {
    const officialOf = (orgId: string) =>
      orgs.get(orgId)?.official ||
      (byOrg.get(orgId) ?? []).some((row) => row.official) ||
      false;
    const byOfficial = (officialOf(a) ? 0 : 1) - (officialOf(b) ? 0 : 1);
    if (byOfficial !== 0) return byOfficial;
    return (a ? orgName(a) : "Unmatched").localeCompare(b ? orgName(b) : "Unmatched");
  });

  const colgroup = showUpdated ? COLS_4 : COLS_3;

  const groups: GroupedTableGroup[] = orgIds.map((orgId) => {
    const items = byOrg.get(orgId) || [];
    const sorted = sortRows(items, sortKey, sortDir, sortValue, fallback);
    const name = orgId ? orgName(orgId) : "Unmatched";
    const info = orgId ? orgs.get(orgId) : undefined;
    const official = info?.official || items.some((row) => row.official) || false;
    return {
      id: orgId || "unmatched",
      count: sorted.length,
      head: (count: number) => (
        <DatasetOrgHead
          orgId={orgId}
          name={name}
          info={info}
          official={official}
          count={count}
        />
      ),
      columns: (
        <>
          <TableHead className={STICKY_TH}>{head("dataset", "Dataset")}</TableHead>
          <TableHead className={STICKY_TH}>Description</TableHead>
          <TableHead className={`${STICKY_TH} tabular-nums`}>
            {head("tasks", "Tasks")}
          </TableHead>
          {showUpdated ? (
            <TableHead className={STICKY_TH}>{head("updated", "Updated")}</TableHead>
          ) : null}
        </>
      ),
      colgroup,
      body: (
        <TableBody>
          {sorted.map((row) => (
            <TableRow key={`${row.dataset_id}@${row.version}`}>
              <TableCell className="whitespace-normal overflow-visible">
                <span className="flex min-w-0 flex-col items-start gap-0.5">
                  <span className="flex min-w-0 flex-wrap items-center gap-2">
                    <Link
                      to={`/datasets/${encodeDatasetId(row.dataset_id)}`}
                      className={`shrink-0 font-medium ${INTERNAL_LINK_CLASS}`}
                    >
                      {datasetLeaf(row)}
                    </Link>
                  </span>
                  <span className="max-w-full truncate text-[13px] text-mute">
                    {row.dataset_id}
                  </span>
                </span>
              </TableCell>
              <TableCell
                className="whitespace-normal text-sm"
                title={row.description || undefined}
              >
                {row.description ? (
                  <span className="line-clamp-2 text-body">{row.description}</span>
                ) : (
                  <span className="text-mute">—</span>
                )}
              </TableCell>
              <TableCell className={CELL_INK}>
                {typeof row.task_count === "number"
                  ? row.task_count.toLocaleString()
                  : "—"}
              </TableCell>
              {showUpdated ? (
                <TableCell className={CELL_MUTE}>
                  {typeof row.created_at === "number"
                    ? formatDay(row.created_at * 1000)
                    : "—"}
                </TableCell>
              ) : null}
            </TableRow>
          ))}
        </TableBody>
      ),
    };
  });

  return (
    <GroupedTables
      chromeId={DATASET_ORG_CHROME_ID}
      pinSlotId={DATASET_ORG_PIN_SLOT_ID}
      groups={groups}
    />
  );
}
