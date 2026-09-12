import { ChartScatter, Grid3x3, Table2, type LucideIcon } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  BOARD_CHARTS,
  PARETO_AXES,
  type BoardChart,
  type ParetoAxis,
} from "@/lib/leaderboard-charts";

const BOARD_CHART_ICONS: Record<BoardChart, LucideIcon> = {
  table: Table2,
  pareto: ChartScatter,
  waffle: Grid3x3,
};

function BoardChartIcon({ id }: { id: BoardChart }) {
  const Icon = BOARD_CHART_ICONS[id];
  return <Icon className="h-3.5 w-3.5 text-mute" aria-hidden />;
}

/** Same Table / Pareto / Waffle Select as Dataset Leaderboard. */
export function BoardChartControls({
  chart,
  axis,
  onChart,
  onAxis,
}: {
  chart: BoardChart;
  axis: ParetoAxis;
  onChart: (next: BoardChart) => void;
  onAxis: (next: ParetoAxis) => void;
}) {
  return (
    <>
      <Select
        value={chart}
        onValueChange={(next) => {
          if (next === "table" || next === "pareto" || next === "waffle") {
            onChart(next);
          }
        }}
      >
        <SelectTrigger
          aria-label="Leaderboard chart"
          className="h-9 w-auto min-w-[8.5rem]"
        >
          <span className="inline-flex items-center gap-2">
            <BoardChartIcon id={chart} />
            <SelectValue />
          </span>
        </SelectTrigger>
        <SelectContent className="w-max min-w-[var(--radix-select-trigger-width)]">
          {BOARD_CHARTS.map((item) => (
            <SelectItem
              key={item.id}
              value={item.id}
              mono={false}
              leading={<BoardChartIcon id={item.id} />}
            >
              {item.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {chart === "pareto" ? (
        <Select
          value={axis}
          onValueChange={(next) => {
            if (next === "cost" || next === "tokens" || next === "time") {
              onAxis(next);
            }
          }}
        >
          <SelectTrigger
            aria-label="Pareto axis"
            className="h-9 w-auto min-w-[7.5rem]"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PARETO_AXES.map((item) => (
              <SelectItem key={item.id} value={item.id} mono={false}>
                {item.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : null}
    </>
  );
}
