import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ArrowUpRight, Boxes, Info } from "lucide-react";

import { EmptyState } from "@/components/empty-state";
import { HoverTip } from "@/components/hover-tip";
import { HuggingFaceMark } from "@/components/huggingface-mark";
import { LabMark } from "@/components/lab-mark";
import { ModalityMarks } from "@/components/modality-mark";
import { CatalogHead } from "@/components/page-head";
import { ScoreRing } from "@/components/score-ring";
import { UnderlineTabs } from "@/components/underline-tabs";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { agentPackageHref } from "@/lib/agent-models";
import { suiteDetailPath } from "@/components/suite-inspector";
import { decodeDatasetId } from "@/lib/api";
import { getToken } from "@/lib/auth";
import {
  collectModelAppearances,
  type ModelAppearance,
} from "@/lib/model-appearances";
import {
  compactTokens,
  directoryPrice,
  formatModalities,
  fmtPrice,
  LAB_INFO,
  loadModelPin,
  modalityBadges,
  modelModalities,
} from "@/lib/model-pin";
import { formatScore } from "@/lib/utils";

type ModelDetailTab = "overview" | "performance";

function parseTab(raw: string | null): ModelDetailTab {
  return raw === "performance" ? "performance" : "overview";
}

export function ModelDetailPage() {
  const { modelId: rawId } = useParams();
  const canonical = decodeDatasetId(rawId || "");
  const pin = loadModelPin();
  const info = pin.models[canonical];
  const lab = info?.lab || canonical.split("/")[0] || "";
  const token = getToken();
  const [searchParams, setSearchParams] = useSearchParams();
  const pageTab = parseTab(searchParams.get("tab"));
  const [appearances, setAppearances] = useState<ModelAppearance[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    void collectModelAppearances(token)
      .then((rows) => {
        if (cancelled) return;
        setAppearances(rows.filter((row) => row.canonical === canonical));
      })
      .catch(() => {
        if (!cancelled) setAppearances([]);
      });
    return () => {
      cancelled = true;
    };
  }, [canonical, token]);

  const price = useMemo(
    () => directoryPrice(canonical, canonical, pin),
    [canonical, pin],
  );

  function setTab(next: ModelDetailTab) {
    const n = new URLSearchParams(searchParams);
    if (next === "overview") n.delete("tab");
    else n.set("tab", next);
    setSearchParams(n, { replace: true });
  }

  if (!info) {
    return (
      <>
        <CatalogHead
          title="Models"
          crumbs={[{ label: "Models", href: "/models" }, { label: canonical || "Unknown" }]}
        />
        <EmptyState
          icon={Boxes}
          glyph="models"
          title="Unknown model"
          caption="No pin row for this id. Overlay invoke ids still run as written."
        />
      </>
    );
  }

  const badges = modalityBadges(modelModalities(info));
  const mods = modelModalities(info);
  const labName = pin.labs[lab]?.name || lab;
  const labInfo = LAB_INFO[lab];
  const effort = (info.reasoning_options || []).find(
    (option) => option.type === "effort",
  );
  const hfHref = (info.weights || "").includes("huggingface.co/")
    ? info.weights
    : null;

  return (
    <>
      <CatalogHead
        title="Models"
        crumbs={[
          { label: "Models", href: "/models" },
          { label: info.name },
        ]}
      />
      <div className="space-y-6">
        <section className="space-y-3">
          <div className="flex items-start gap-3">
            <LabMark lab={lab} size={36} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-xl font-semibold tracking-tight text-ink">
                  {info.name}
                </h2>
                {badges.length ? <ModalityMarks kinds={badges} /> : null}
                {hfHref ? (
                  <a
                    href={hfHref}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-link hover:text-link-deep focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-link/70"
                  >
                    <HuggingFaceMark size={16} />
                    <span className="text-xs">{hfRepo(hfHref)}</span>
                  </a>
                ) : null}
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-mute">
                <span>{canonical}</span>
                <span aria-hidden>·</span>
                {labInfo?.website ? (
                  <a
                    href={labInfo.website}
                    target="_blank"
                    rel="noreferrer"
                    title={labInfo.website}
                    className="inline-flex items-center gap-0.5 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-link/70"
                  >
                    {labName}
                    <ArrowUpRight className="size-3" aria-hidden />
                  </a>
                ) : (
                  <span>{labName}</span>
                )}
                {info.family ? (
                  <>
                    <span aria-hidden>·</span>
                    <span>{info.family}</span>
                  </>
                ) : null}
              </div>
            </div>
          </div>
          <p className="text-sm text-body">
            {info.description || "No description in the pin."}
          </p>
        </section>

        <UnderlineTabs
          ariaLabel="Model sections"
          value={pageTab}
          onChange={setTab}
          items={[
            { id: "overview", label: "Overview" },
            { id: "performance", label: "Performance" },
          ]}
        />

        {pageTab === "overview" ? (
          <section>
            <div className="blob-panel overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="w-[12rem]">Attribute</TableHead>
                    <TableHead>Value</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <FactRow label="Canonical">{canonical}</FactRow>
                  <FactRow label="Family">{info.family || "—"}</FactRow>
                  <FactRow label="Released">{info.release_date || "—"}</FactRow>
                  {info.last_updated && info.last_updated !== info.release_date ? (
                    <FactRow label="Updated">{info.last_updated}</FactRow>
                  ) : null}
                  {info.knowledge ? (
                    <FactRow
                      label="Knowledge"
                      hint="Knowledge cutoff date."
                    >
                      {info.knowledge}
                    </FactRow>
                  ) : null}
                  <FactRow label="Context">{tokenFact(info.context)}</FactRow>
                  {info.input_limit != null ? (
                    <FactRow label="Input">{tokenFact(info.input_limit)}</FactRow>
                  ) : null}
                  <FactRow label="Output">{tokenFact(info.output)}</FactRow>
                  <FactRow label="Price">
                    {price ? (
                      <span>
                        <span className="tabular-nums">
                          ${fmtPrice(price.input)} / ${fmtPrice(price.output)}
                        </span>
                        <span className="text-mute"> per MTok</span>
                      </span>
                    ) : (
                      <span className="text-mute">—</span>
                    )}
                  </FactRow>
                  <FactRow label="Weights">
                    {hfHref ? (
                      <a
                        href={hfHref}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex min-w-0 items-center gap-1.5 text-link hover:text-link-deep hover:underline underline-offset-2"
                      >
                        <HuggingFaceMark size={16} />
                        <span className="truncate">{hfRepo(hfHref)}</span>
                      </a>
                    ) : info.open_weights ? (
                      "Open"
                    ) : (
                      <span className="text-mute">Closed</span>
                    )}
                  </FactRow>
                  <FactRow label="Modalities">{formatModalities(mods)}</FactRow>
                  <FactRow label="Reasoning">{yn(info.reasoning)}</FactRow>
                  <FactRow label="Tool call">{yn(info.tool_call)}</FactRow>
                  <FactRow
                    label="Attachment"
                    hint="File attachments in input."
                  >
                    {yn(info.attachment)}
                  </FactRow>
                  {info.structured_output != null ? (
                    <FactRow
                      label="Structured"
                      hint="JSON / schema-constrained output."
                    >
                      {yn(info.structured_output)}
                    </FactRow>
                  ) : null}
                  {info.temperature != null ? (
                    <FactRow
                      label="Temperature"
                      hint="Sampling temperature."
                    >
                      {yn(info.temperature)}
                    </FactRow>
                  ) : null}
                  {effort?.values?.length ? (
                    <FactRow label="Reasoning effort">
                      {effort.values.join(" / ")}
                    </FactRow>
                  ) : null}
                </TableBody>
              </Table>
            </div>
          </section>
        ) : null}

        {pageTab === "performance" ? (
          <section className="space-y-2">
            <p className="text-xs text-mute">
              Consented Agent Performance on this canonical. Observational
              metrics only — PASS stays on the independent evaluator.
            </p>
            {appearances === null ? (
              <p className="text-sm text-mute">Loading performance…</p>
            ) : appearances.length === 0 ? (
              <div className="blob-panel p-6">
                <p className="text-sm font-medium text-ink">
                  No consented Performance yet
                </p>
                <p className="mt-1 text-sm text-mute">
                  Rows appear after a harness collects a public complete suite
                  that ran this model.
                </p>
              </div>
            ) : (
              <div className="blob-panel overflow-hidden">
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead>Harness</TableHead>
                      <TableHead>Dataset</TableHead>
                      <TableHead>Overlay</TableHead>
                      <TableHead className="text-right">Pass</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {appearances.map((row) => (
                      <TableRow
                        key={`${row.packageId}:${row.suiteRunId}:${row.overlay}`}
                      >
                        <TableCell>
                          <Link
                            to={agentPackageHref(row.packageId, row.overlay)}
                            className="text-link hover:text-link-deep hover:underline underline-offset-2"
                          >
                            {row.packageId}
                          </Link>
                        </TableCell>
                        <TableCell>
                          <Link
                            to={suiteDetailPath(row.datasetId, row.suiteRunId)}
                            className="text-link hover:text-link-deep hover:underline underline-offset-2"
                          >
                            {row.datasetId}
                          </Link>
                        </TableCell>
                        <TableCell className="text-body">{row.overlay}</TableCell>
                        <TableCell className="text-right tabular-nums">
                          {row.passRate != null ? (
                            <ScoreRing value={row.passRate}>
                              {formatScore(row.passRate)}
                            </ScoreRing>
                          ) : (
                            <span className="text-mute">—</span>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </section>
        ) : null}
      </div>
    </>
  );
}

function FactRow({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <TableRow>
      <TableCell className="w-[12rem] align-middle">
        <span className="inline-flex items-center gap-1 text-sm font-medium text-ink">
          {label}
          {hint ? (
            <HoverTip content={hint}>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`About ${label}`}
                className="h-5 w-5 text-mute hover:text-ink"
              >
                <Info className="size-3.5" aria-hidden />
              </Button>
            </HoverTip>
          ) : null}
        </span>
      </TableCell>
      <TableCell className="text-sm text-ink">{children}</TableCell>
    </TableRow>
  );
}

function yn(value: boolean): ReactNode {
  return value ? "yes" : <span className="text-mute">no</span>;
}

function tokenFact(n: number | null | undefined): ReactNode {
  if (n == null) return "—";
  return (
    <span>
      <span className="tabular-nums">{compactTokens(n)}</span>
      <span className="text-mute"> · {n.toLocaleString()} tok</span>
    </span>
  );
}

function hfRepo(url: string): string {
  try {
    const path = new URL(url).pathname.replace(/^\/+|\/+$/g, "");
    return path || url;
  } catch {
    return url;
  }
}
