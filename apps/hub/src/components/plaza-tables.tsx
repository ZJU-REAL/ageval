import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { BrandMark } from "@/components/brand-mark";
import { DatasetOrgHead } from "@/components/dataset-org-tables";
import {
  GroupedTables,
  type GroupedTableGroup,
} from "@/components/grouped-tables";
import { LabGroupHead } from "@/components/lab-group-head";
import { LeaderboardPareto } from "@/components/leaderboard-pareto";
import { LeaderboardWaffle } from "@/components/leaderboard-waffle";
import { HarnessLabel } from "@/components/harness-label";
import { ModelLabel } from "@/components/model-label";
import { OfficialMark } from "@/components/official-mark";
import { ScoreRing } from "@/components/score-ring";
import {
  SortableHead,
  nextSort,
  sortRows,
  type SortDir,
} from "@/components/sortable-head";
import { suiteDetailPath } from "@/components/suite-inspector";
import {
  TableBody,
  TableCell,
  TableHead,
  TableRow,
} from "@/components/ui/table";
import { agentPackageHref } from "@/lib/agent-models";
import { INTERNAL_LINK_CLASS, harnessHref, modelCatalogHref } from "@/lib/links";
import { comparePerformances } from "@/lib/agent-performances";
import {
  encodeDatasetId,
  latestPackageByDataset,
  splitPackageId,
  uniqueAgentRefs,
  type AgentPerformance,
  type OrgRow,
  type PackageRelease,
  type SuiteRow,
} from "@/lib/api";
import { markFromPackage, resolveEntityMark } from "@/lib/brand-marks";
import type { BoardChart, ParetoAxis } from "@/lib/leaderboard-charts";
import { performanceCanonical } from "@/lib/model-appearances";
import { loadModelPin } from "@/lib/model-pin";
import { displayLabelsFromOverlay, formatDate, formatScore } from "@/lib/utils";

export const PLAZA_CHROME_ID = "leaderboard-chrome";
export const PLAZA_PIN_SLOT_ID = "leaderboard-pin";

const STICKY_TH =
  "sticky z-10 bg-canvas-soft top-[var(--leaderboard-stick-top,0px)]";

function defaultScoreCompare(
  a: { pass_rate?: number | null; mean_score?: number | null; created_at?: number | string },
  b: { pass_rate?: number | null; mean_score?: number | null; created_at?: number | string },
): number {
  const pr = (b.pass_rate ?? -1) - (a.pass_rate ?? -1);
  if (pr !== 0) return pr;
  const ms = (b.mean_score ?? -1) - (a.mean_score ?? -1);
  if (ms !== 0) return ms;
  return (Number(b.created_at) || 0) - (Number(a.created_at) || 0);
}

function usePlazaSort(defaultKey = "pass_rate", defaultDir: SortDir = "desc") {
  const [sortKey, setSortKey] = useState<string | null>(defaultKey);
  const [sortDir, setSortDir] = useState<SortDir>(defaultDir);

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

  return { sortKey, sortDir, head };
}

function orgNameOf(orgId: string, orgs: Map<string, OrgRow>): string {
  return orgs.get(orgId)?.display_name || orgs.get(orgId)?.name || orgId;
}

function sortOrgIds(
  ids: string[],
  orgs: Map<string, OrgRow>,
  officialOf: (orgId: string) => boolean,
): string[] {
  return [...ids].sort((a, b) => {
    if (a === "_builtin" && b !== "_builtin") return -1;
    if (b === "_builtin" && a !== "_builtin") return 1;
    const byOfficial = (officialOf(a) ? 0 : 1) - (officialOf(b) ? 0 : 1);
    if (byOfficial !== 0) return byOfficial;
    const an = a && a !== "_builtin" ? orgNameOf(a, orgs) : "Builtin";
    const bn = b && b !== "_builtin" ? orgNameOf(b, orgs) : "Builtin";
    return an.localeCompare(bn);
  });
}

function datasetLeaf(
  datasetId: string,
  packs: Map<string, PackageRelease>,
): string {
  const row = packs.get(datasetId);
  return row?.display_name?.trim() || splitPackageId(datasetId).name || datasetId;
}

function suiteDatasetId(suite: SuiteRow): string {
  return suite.dataset_id || "";
}

function suiteCreatedAt(suite: SuiteRow): number | null {
  const n = Number(suite.created_at);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function sortDatasetIds(
  ids: string[],
  packs: Map<string, PackageRelease>,
): string[] {
  return [...ids].sort((a, b) => {
    if (!a && b) return 1;
    if (a && !b) return -1;
    const pa = packs.get(a);
    const pb = packs.get(b);
    const byOfficial = (pa?.official ? 0 : 1) - (pb?.official ? 0 : 1);
    if (byOfficial !== 0) return byOfficial;
    const byName = datasetLeaf(a, packs).localeCompare(datasetLeaf(b, packs));
    if (byName !== 0) return byName;
    return a.localeCompare(b);
  });
}

function PlazaDatasetHead({
  datasetId,
  pack,
  count,
}: {
  datasetId: string;
  pack?: PackageRelease;
  count: number;
}) {
  const name = datasetId
    ? pack?.display_name?.trim() || splitPackageId(datasetId).name || datasetId
    : "Unmatched";
  const description = pack?.description?.trim() || "";
  const mark = pack
    ? markFromPackage(pack)
    : resolveEntityMark({ displayName: name, packageId: datasetId || undefined });
  return (
    <div className="flex items-center gap-2">
      <BrandMark mark={mark} size={22} title={name} />
      <h3 className="text-base font-semibold text-ink">
        {datasetId ? (
          <Link
            to={`/datasets/${encodeDatasetId(datasetId)}?tab=leaderboard`}
            className={`inline-flex items-center gap-1 ${INTERNAL_LINK_CLASS}`}
          >
            {name}
          </Link>
        ) : (
          name
        )}
      </h3>
      {pack?.official ? <OfficialMark kind="dataset" /> : null}
      {description ? (
        <span
          className="hidden min-w-0 flex-1 truncate text-sm text-mute sm:block"
          title={description}
        >
          {description}
        </span>
      ) : null}
      <span className="ml-auto text-xs text-mute tabular-nums">{count}</span>
    </div>
  );
}

function HarnessCells({ suite }: { suite: SuiteRow }) {
  const derived = displayLabelsFromOverlay(suite.job_overlay);
  const agentText = derived.agent || suite.agent_label || "";
  const modelText = derived.model || suite.model_label || "";
  const runtimeLinks = uniqueAgentRefs(suite.agent_refs);
  return (
    <>
      {runtimeLinks.length ? (
        <TableCell className="max-w-[12rem] overflow-hidden">
          <span className="flex min-w-0 flex-col gap-0.5">
            {runtimeLinks.map((ref) => (
              <HarnessLabel
                key={ref.package_id}
                value={ref.package_id}
                to={agentPackageHref(ref.package_id)}
              />
            ))}
          </span>
        </TableCell>
      ) : (
        <TableCell className="max-w-[12rem] overflow-hidden">
          <HarnessLabel value={agentText} to={harnessHref(agentText)} empty="—" />
        </TableCell>
      )}
      <TableCell className="max-w-[12rem] overflow-hidden">
        <ModelLabel value={modelText} to={modelCatalogHref(modelText)} />
      </TableCell>
    </>
  );
}

function PassMeanCells({
  passRate,
  meanScore,
  passAsPercent,
}: {
  passRate?: number | null;
  meanScore?: number | null;
  passAsPercent?: boolean;
}) {
  return (
    <>
      <TableCell className="tabular-nums">
        <ScoreRing value={passRate}>
          {passRate == null
            ? "—"
            : passAsPercent
              ? `${(Number(passRate) * 100).toFixed(1)}%`
              : formatScore(passRate)}
        </ScoreRing>
      </TableCell>
      <TableCell className="tabular-nums">
        <ScoreRing value={meanScore}>{formatScore(meanScore)}</ScoreRing>
      </TableCell>
    </>
  );
}

export function PlazaDatasetTables({
  suites,
  datasets,
  chart = "table",
  axis = "cost",
}: {
  suites: SuiteRow[];
  datasets: PackageRelease[];
  chart?: BoardChart;
  axis?: ParetoAxis;
}) {
  const navigate = useNavigate();
  const { sortKey, sortDir, head } = usePlazaSort();
  const packs = useMemo(() => {
    const map = new Map<string, PackageRelease>();
    for (const row of latestPackageByDataset(datasets)) {
      map.set(row.dataset_id, row);
    }
    return map;
  }, [datasets]);
  const showUploaded = suites.some((row) => suiteCreatedAt(row) != null);

  function sortValue(row: SuiteRow, key: string): unknown {
    if (key === "pass_rate") return row.pass_rate ?? null;
    if (key === "mean_score") return row.mean_score ?? null;
    if (key === "created_at") return suiteCreatedAt(row);
    if (key === "harness") {
      return uniqueAgentRefs(row.agent_refs)
        .map((ref) => ref.package_id)
        .join(" ") || displayLabelsFromOverlay(row.job_overlay).agent || row.agent_label || "";
    }
    if (key === "model") {
      return displayLabelsFromOverlay(row.job_overlay).model || row.model_label || "";
    }
    return null;
  }

  const byDataset = new Map<string, SuiteRow[]>();
  for (const suite of suites) {
    const datasetId = suiteDatasetId(suite);
    const list = byDataset.get(datasetId) ?? [];
    list.push(suite);
    byDataset.set(datasetId, list);
  }
  const datasetIds = sortDatasetIds([...byDataset.keys()], packs);

  const groups: GroupedTableGroup[] = datasetIds.map((datasetId) => {
    const raw = byDataset.get(datasetId) || [];
    const items =
      chart === "table"
        ? sortRows(raw, sortKey, sortDir, sortValue, defaultScoreCompare)
        : raw;
    const pack = packs.get(datasetId);
    const headNode = (count: number) => (
      <PlazaDatasetHead datasetId={datasetId} pack={pack} count={count} />
    );
    const openSuite = (id: string | null) => {
      if (!id) return;
      navigate(suiteDetailPath(datasetId, id));
    };
    if (chart === "waffle") {
      return {
        id: datasetId || "unmatched",
        count: items.length,
        head: headNode,
        body: (
          <LeaderboardWaffle
            suites={items}
            datasetId={datasetId}
            showCaption={false}
            onOpenSuite={openSuite}
          />
        ),
      };
    }
    if (chart === "pareto") {
      return {
        id: datasetId || "unmatched",
        count: items.length,
        head: headNode,
        body: (
          <LeaderboardPareto
            suites={items}
            axis={axis}
            onOpenSuite={openSuite}
          />
        ),
      };
    }
    return {
      id: datasetId || "unmatched",
      count: items.length,
      head: headNode,
      columns: (
        <>
          <TableHead className={STICKY_TH}>{head("harness", "Harness")}</TableHead>
          <TableHead className={STICKY_TH}>{head("model", "Model")}</TableHead>
          <TableHead className={STICKY_TH}>{head("pass_rate", "Pass rate")}</TableHead>
          <TableHead className={STICKY_TH}>{head("mean_score", "Mean")}</TableHead>
          {showUploaded ? (
            <TableHead className={STICKY_TH}>{head("created_at", "Uploaded")}</TableHead>
          ) : null}
        </>
      ),
      body: (
        <TableBody>
          {items.map((suite) => (
            <TableRow
              key={suite.suite_run_id}
              className="cursor-pointer"
              onClick={() =>
                navigate(suiteDetailPath(suiteDatasetId(suite), suite.suite_run_id))
              }
              role="link"
              aria-label="Open suite run"
            >
              <HarnessCells suite={suite} />
              <PassMeanCells
                passRate={suite.pass_rate}
                meanScore={suite.mean_score}
                passAsPercent
              />
              {showUploaded ? (
                <TableCell className="whitespace-nowrap text-sm text-mute tabular-nums">
                  {suiteCreatedAt(suite) != null ? formatDate(suite.created_at) : "—"}
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
      chromeId={PLAZA_CHROME_ID}
      pinSlotId={PLAZA_PIN_SLOT_ID}
      groups={groups}
    />
  );
}

function isBuiltinAgentId(packageId: string): boolean {
  return !packageId.includes("/");
}

function agentHref(packageId: string): string {
  return `/agents/${encodeDatasetId(packageId)}?tab=performance`;
}

export function PlazaAgentTables({
  rows,
  agents,
  orgs,
}: {
  rows: AgentPerformance[];
  agents: PackageRelease[];
  orgs: Map<string, OrgRow>;
}) {
  const navigate = useNavigate();
  const { sortKey, sortDir, head } = usePlazaSort();
  const packs = useMemo(() => {
    const map = new Map<string, PackageRelease>();
    for (const row of latestPackageByDataset(agents)) {
      map.set(row.dataset_id, row);
    }
    return map;
  }, [agents]);

  function sortValue(row: AgentPerformance, key: string): unknown {
    if (key === "agent") return row.package_id || "";
    if (key === "dataset_id") return row.dataset_id || "";
    if (key === "role") return row.role || "";
    if (key === "model") return row.model || "";
    if (key === "pass_rate") return row.pass_rate ?? null;
    if (key === "mean_score") return row.mean_score ?? null;
    return null;
  }

  const byOrg = new Map<string, AgentPerformance[]>();
  for (const row of rows) {
    const pid = row.package_id || "";
    const org = isBuiltinAgentId(pid)
      ? "_builtin"
      : packs.get(pid)?.org_id || splitPackageId(pid).org || "";
    const list = byOrg.get(org) ?? [];
    list.push(row);
    byOrg.set(org, list);
  }
  const orgIds = sortOrgIds([...byOrg.keys()], orgs, (orgId) => {
    if (orgId === "_builtin") return false;
    return (
      orgs.get(orgId)?.official ||
      (byOrg.get(orgId) ?? []).some((row) => packs.get(row.package_id)?.official) ||
      false
    );
  });

  const groups: GroupedTableGroup[] = orgIds.map((orgId) => {
    const items = sortRows(
      byOrg.get(orgId) || [],
      sortKey,
      sortDir,
      sortValue,
      comparePerformances,
    );
    const builtin = orgId === "_builtin";
    const name = builtin ? "Builtin" : orgId ? orgNameOf(orgId, orgs) : "Unmatched";
    const info = !builtin && orgId ? orgs.get(orgId) : undefined;
    const official =
      !builtin &&
      (info?.official ||
        items.some((row) => packs.get(row.package_id)?.official) ||
        false);
    return {
      id: orgId || "unmatched",
      count: items.length,
      head: (count: number) =>
        builtin ? (
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold text-ink">Builtin</h3>
            <span className="ml-auto text-xs text-mute tabular-nums">{count}</span>
          </div>
        ) : (
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
          <TableHead className={STICKY_TH}>{head("agent", "Agent")}</TableHead>
          <TableHead className={STICKY_TH}>{head("dataset_id", "Dataset")}</TableHead>
          <TableHead className={STICKY_TH}>{head("role", "Role")}</TableHead>
          <TableHead className={STICKY_TH}>{head("model", "Model")}</TableHead>
          <TableHead className={STICKY_TH}>{head("pass_rate", "Pass rate")}</TableHead>
          <TableHead className={STICKY_TH}>{head("mean_score", "Mean")}</TableHead>
        </>
      ),
      body: (
        <TableBody>
          {items.map((row) => (
            <TableRow
              key={`${row.suite_run_id}:${row.role}:${row.package_id}`}
              className="cursor-pointer"
              onClick={() =>
                navigate(
                  suiteDetailPath(row.dataset_id, row.suite_run_id, {
                    agent: row.package_id,
                    role: row.role,
                  }),
                )
              }
              role="link"
              aria-label="Open suite run"
            >
              <TableCell className="max-w-[12rem] overflow-hidden">
                <HarnessLabel
                  value={row.package_id}
                  to={agentHref(row.package_id)}
                  pack={packs.get(row.package_id)}
                  onClick={(event) => event.stopPropagation()}
                />
              </TableCell>
              <TableCell>
                <Link
                  to={`/datasets/${encodeDatasetId(row.dataset_id)}?tab=leaderboard`}
                  className={INTERNAL_LINK_CLASS}
                  onClick={(event) => event.stopPropagation()}
                >
                  {row.dataset_id}
                </Link>
              </TableCell>
              <TableCell>{row.role}</TableCell>
              <TableCell className="max-w-[12rem] overflow-hidden">
                <ModelLabel value={row.model} empty="—" />
              </TableCell>
              <PassMeanCells passRate={row.pass_rate} meanScore={row.mean_score} />
            </TableRow>
          ))}
        </TableBody>
      ),
    };
  });

  return (
    <GroupedTables
      chromeId={PLAZA_CHROME_ID}
      pinSlotId={PLAZA_PIN_SLOT_ID}
      groups={groups}
    />
  );
}

type ModelPlazaRow = AgentPerformance & { canonical: string };

export function PlazaModelTables({
  rows,
  agents = [],
}: {
  rows: AgentPerformance[];
  agents?: PackageRelease[];
}) {
  const navigate = useNavigate();
  const { sortKey, sortDir, head } = usePlazaSort();
  const pin = loadModelPin();
  const packs = useMemo(() => {
    const map = new Map<string, PackageRelease>();
    for (const row of latestPackageByDataset(agents)) {
      map.set(row.dataset_id, row);
    }
    return map;
  }, [agents]);

  const joined = useMemo(() => {
    const out: ModelPlazaRow[] = [];
    for (const row of rows) {
      const canonical = performanceCanonical(row);
      if (!canonical) continue;
      out.push({ ...row, canonical });
    }
    return out;
  }, [rows]);

  function sortValue(row: ModelPlazaRow, key: string): unknown {
    if (key === "model") return pin.models[row.canonical]?.name || row.canonical;
    if (key === "harness") return row.package_id || "";
    if (key === "dataset_id") return row.dataset_id || "";
    if (key === "overlay") return row.model || "";
    if (key === "pass_rate") return row.pass_rate ?? null;
    return null;
  }

  const byLab = new Map<string, ModelPlazaRow[]>();
  for (const row of joined) {
    const lab = pin.models[row.canonical]?.lab ?? "";
    const list = byLab.get(lab) ?? [];
    list.push(row);
    byLab.set(lab, list);
  }
  const labs = [...byLab.entries()].sort(([a], [b]) =>
    (pin.labs[a]?.name || a).localeCompare(pin.labs[b]?.name || b),
  );

  const groups: GroupedTableGroup[] = labs.map(([lab, items]) => {
    const sorted = sortRows(items, sortKey, sortDir, sortValue, comparePerformances);
    const name = pin.labs[lab]?.name || lab || "Unmatched";
    return {
      id: lab || "unmatched",
      count: sorted.length,
      head: (count: number) => <LabGroupHead lab={lab} name={name} count={count} />,
      columns: (
        <>
          <TableHead className={STICKY_TH}>{head("model", "Model")}</TableHead>
          <TableHead className={STICKY_TH}>{head("harness", "Harness")}</TableHead>
          <TableHead className={STICKY_TH}>{head("dataset_id", "Dataset")}</TableHead>
          <TableHead className={STICKY_TH}>{head("overlay", "Overlay")}</TableHead>
          <TableHead className={STICKY_TH}>{head("pass_rate", "Pass")}</TableHead>
        </>
      ),
      body: (
        <TableBody>
          {sorted.map((row) => {
            const info = pin.models[row.canonical];
            return (
              <TableRow
                key={`${row.canonical}:${row.package_id}:${row.suite_run_id}:${row.role}`}
                className="cursor-pointer"
                onClick={() =>
                  navigate(suiteDetailPath(row.dataset_id, row.suite_run_id))
                }
                role="link"
                aria-label="Open suite run"
              >
                <TableCell>
                  <Link
                    to={`/models/${encodeDatasetId(row.canonical)}?tab=performance`}
                    className={`font-medium ${INTERNAL_LINK_CLASS}`}
                    onClick={(event) => event.stopPropagation()}
                  >
                    {info?.name || row.canonical}
                  </Link>
                  <div className="truncate text-[13px] text-mute">{row.canonical}</div>
                </TableCell>
                <TableCell className="max-w-[12rem] overflow-hidden">
                  <HarnessLabel
                    value={row.package_id}
                    to={agentPackageHref(row.package_id, row.model)}
                    pack={packs.get(row.package_id)}
                    onClick={(event) => event.stopPropagation()}
                  />
                </TableCell>
                <TableCell>
                  <Link
                    to={`/datasets/${encodeDatasetId(row.dataset_id)}?tab=leaderboard`}
                    className={INTERNAL_LINK_CLASS}
                    onClick={(event) => event.stopPropagation()}
                  >
                    {row.dataset_id}
                  </Link>
                </TableCell>
                <TableCell className="text-body">{row.model || "—"}</TableCell>
                <TableCell className="tabular-nums">
                  <ScoreRing value={row.pass_rate}>
                    {formatScore(row.pass_rate)}
                  </ScoreRing>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      ),
    };
  });

  return (
    <GroupedTables
      chromeId={PLAZA_CHROME_ID}
      pinSlotId={PLAZA_PIN_SLOT_ID}
      groups={groups}
    />
  );
}

export function plazaModelRowCount(rows: AgentPerformance[]): number {
  return rows.reduce((n, row) => n + (performanceCanonical(row) ? 1 : 0), 0);
}
