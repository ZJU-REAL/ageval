import {
  latestPackageByDataset,
  listPackages,
  listPackageVersionsWithPerformances,
  type AgentPerformance,
} from "@/lib/api";
import { joinOverlay, loadModelPin } from "@ageval/shared/lib/model-pin";

export type ModelAppearance = {
  canonical: string | null;
  overlay: string;
  packageId: string;
  datasetId: string;
  suiteRunId: string;
  passRate: number | null;
};

export function performanceCanonical(row: AgentPerformance): string | null {
  const stored = (row.canonical_model || "").trim();
  if (stored) return stored;
  return joinOverlay(row.model || "", loadModelPin()).canonical;
}

export async function collectModelAppearances(
  token: string | null,
): Promise<ModelAppearance[]> {
  const pin = loadModelPin();
  const packages = await listPackages(token, {
    packageKind: "agent",
    visibility: "public",
  });
  const latest = latestPackageByDataset(packages);
  const out: ModelAppearance[] = [];
  await Promise.all(
    latest.map(async (row) => {
      const pack = await listPackageVersionsWithPerformances(row.dataset_id, token, {
        packageKind: "agent",
      });
      for (const perf of pack.performances) {
        const overlay = (perf.model || "").trim();
        const stored = (perf.canonical_model || "").trim();
        const canonical = stored || joinOverlay(overlay, pin).canonical;
        out.push({
          canonical,
          overlay,
          packageId: perf.package_id || row.dataset_id,
          datasetId: perf.dataset_id,
          suiteRunId: perf.suite_run_id,
          passRate: perf.pass_rate ?? null,
        });
      }
    }),
  );
  return out;
}

export function appearancesByCanonical(
  rows: ModelAppearance[],
): Map<string, ModelAppearance[]> {
  const map = new Map<string, ModelAppearance[]>();
  for (const row of rows) {
    if (!row.canonical) continue;
    const list = map.get(row.canonical) ?? [];
    list.push(row);
    map.set(row.canonical, list);
  }
  return map;
}
