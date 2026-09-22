"use client";

import { memo } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  Brush,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { ChartCard } from "@/components/charts/chart-card";
import { formatChartValue, type ChartSpec } from "@/lib/charts";

const AXIS = {
  stroke: "var(--muted-foreground)",
  fontSize: 11,
  tickLine: false,
  axisLine: false,
} as const;
const GRID = {
  stroke: "var(--border)",
  strokeDasharray: "3 3",
  vertical: false,
} as const;
const TIP = {
  contentStyle: {
    background: "var(--popover)",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius-sm)",
    fontSize: 12,
    color: "var(--popover-foreground)",
  },
  labelStyle: { color: "var(--muted-foreground)" },
} as const;

const SERIES_COLORS = [
  "var(--primary)",
  "#8b93e8",
  "#a7b0f2",
  "#6ee7d8",
  "#f2a0c0",
];

function fmtValue(spec: ChartSpec) {
  return (v: unknown) => formatChartValue(v as number, spec.format);
}

function Frame({
  spec,
  children,
}: {
  spec: ChartSpec;
  children: React.ReactNode;
}) {
  return (
    <ChartCard title={spec.title} fetchedAt={spec.fetched_at}>
      <ResponsiveContainer width="100%" height="100%">
        {children}
      </ResponsiveContainer>
    </ChartCard>
  );
}

/** Zoom brush on long time series — drag to window, scroll inside it. */
function ZoomBrush({ spec }: { spec: ChartSpec }) {
  if (spec.x.type !== "time" || spec.data.length <= 15) return null;
  return (
    <Brush dataKey={spec.x.key} height={18} stroke="var(--primary)"
           travellerWidth={8} />
  );
}

function SeriesChart({
  spec,
  variant,
}: {
  spec: ChartSpec;
  variant: "line" | "area";
}) {
  const Chart = variant === "area" ? AreaChart : LineChart;
  const Series = variant === "area" ? Area : Line;
  return (
    <Frame spec={spec}>
      <Chart
        data={spec.data}
        margin={{ left: 8, right: 8, top: 4, bottom: 0 }}
      >
        <CartesianGrid {...GRID} />
        <XAxis dataKey={spec.x.key} {...AXIS} />
        <YAxis tickFormatter={fmtValue(spec)} width={56} {...AXIS} />
        <Tooltip formatter={fmtValue(spec)} {...TIP} />
        {spec.series.map((s, i) => (
          <Series
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label}
            stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
            fill={SERIES_COLORS[i % SERIES_COLORS.length]}
            fillOpacity={variant === "area" ? 0.15 : 0}
            strokeWidth={2}
            dot={false}
            connectNulls
          />
        ))}
        <ZoomBrush spec={spec} />
      </Chart>
    </Frame>
  );
}

function SignedArea({ spec }: { spec: ChartSpec }) {
  // Split gradient at y=0 — positive flow lavender, negative destructive.
  const s = spec.series[0];
  const vals = spec.data.map((r) => Number(r[s.key] ?? 0));
  const max = Math.max(...vals, 0);
  const min = Math.min(...vals, 0);
  const off = max === min ? 1 : max / (max - min);
  const gradId = `split-${spec.id}`;
  return (
    <Frame spec={spec}>
      <AreaChart
        data={spec.data}
        margin={{ left: 8, right: 8, top: 4, bottom: 0 }}
      >
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop
              offset={off}
              stopColor="var(--primary)"
              stopOpacity={0.4}
            />
            <stop
              offset={off}
              stopColor="var(--destructive)"
              stopOpacity={0.4}
            />
          </linearGradient>
        </defs>
        <CartesianGrid {...GRID} />
        <XAxis dataKey={spec.x.key} {...AXIS} />
        <YAxis tickFormatter={fmtValue(spec)} width={56} {...AXIS} />
        <Tooltip formatter={fmtValue(spec)} {...TIP} />
        <ReferenceLine y={0} stroke="var(--border)" />
        <Area
          type="monotone"
          dataKey={s.key}
          name={s.label}
          stroke="var(--primary)"
          strokeWidth={2}
          fill={`url(#${gradId})`}
          dot={false}
          connectNulls
        />
        <ZoomBrush spec={spec} />
      </AreaChart>
    </Frame>
  );
}

function Bars({ spec }: { spec: ChartSpec }) {
  return (
    <Frame spec={spec}>
      <BarChart
        data={spec.data}
        margin={{ left: 8, right: 8, top: 4, bottom: 0 }}
      >
        <CartesianGrid {...GRID} />
        <XAxis dataKey={spec.x.key} {...AXIS} />
        <YAxis tickFormatter={fmtValue(spec)} width={56} {...AXIS} />
        <Tooltip formatter={fmtValue(spec)} {...TIP} />
        {spec.series.map((s, i) => (
          <Bar
            key={s.key}
            dataKey={s.key}
            name={s.label}
            fill={SERIES_COLORS[i % SERIES_COLORS.length]}
            radius={[4, 4, 0, 0]}
          />
        ))}
      </BarChart>
    </Frame>
  );
}

function DivergingBars({ spec }: { spec: ChartSpec }) {
  const s = spec.series[0];
  const hasGroups = spec.data.some((r) => r.group);
  const groups = hasGroups
    ? [...new Set(spec.data.map((r) => String(r.group ?? "")))]
    : [""];
  return (
    <Frame spec={spec}>
      <div className="flex h-full flex-col gap-3 overflow-y-auto">
        {groups.map((g) => {
          const rows = spec.data.filter(
            (r) => String(r.group ?? "") === g,
          );
          return (
            <div key={g || "all"} className="flex min-h-0 flex-1 flex-col">
              {g && (
                <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-ink-tertiary">
                  {g}
                </div>
              )}
              <div className="min-h-0 flex-1">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={rows}
                    layout="vertical"
                    margin={{ left: 8, right: 24, top: 0, bottom: 0 }}
                  >
                    <CartesianGrid
                      {...GRID}
                      vertical={true}
                      horizontal={false}
                    />
                    <XAxis
                      type="number"
                      tickFormatter={fmtValue(spec)}
                      {...AXIS}
                    />
                    <YAxis
                      type="category"
                      dataKey={spec.x.key}
                      width={56}
                      {...AXIS}
                    />
                    <Tooltip formatter={fmtValue(spec)} {...TIP} />
                    <ReferenceLine x={0} stroke="var(--border)" />
                    <Bar
                      dataKey={s.key}
                      name={s.label}
                      radius={[0, 4, 4, 0]}
                    >
                      {rows.map((r, i) => (
                        <Cell
                          key={i}
                          fill={
                            Number(r[s.key] ?? 0) >= 0
                              ? "var(--primary)"
                              : "var(--destructive)"
                          }
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          );
        })}
      </div>
    </Frame>
  );
}

function PriceVolume({ spec }: { spec: ChartSpec }) {
  const [price, volume] = spec.series;
  return (
    <Frame spec={spec}>
      <ComposedChart
        data={spec.data}
        margin={{ left: 8, right: 8, top: 4, bottom: 0 }}
      >
        <CartesianGrid {...GRID} />
        <XAxis dataKey={spec.x.key} {...AXIS} />
        <YAxis
          yAxisId="price"
          tickFormatter={fmtValue(spec)}
          width={56}
          {...AXIS}
        />
        <YAxis
          yAxisId="vol"
          orientation="right"
          tickFormatter={(v) => formatChartValue(v as number, "number")}
          width={48}
          {...AXIS}
        />
        <Tooltip formatter={fmtValue(spec)} {...TIP} />
        {volume && (
          <Bar
            yAxisId="vol"
            dataKey={volume.key}
            name={volume.label}
            fill="var(--muted-foreground)"
            fillOpacity={0.25}
          />
        )}
        <Line
          yAxisId="price"
          type="monotone"
          dataKey={price.key}
          name={price.label}
          stroke="var(--primary)"
          strokeWidth={2}
          dot={false}
          connectNulls
        />
        <ZoomBrush spec={spec} />
      </ComposedChart>
    </Frame>
  );
}

export const ChartBlock = memo(function ChartBlock({
  spec,
}: {
  spec: ChartSpec;
}) {
  if (!spec?.data?.length) return null;
  switch (spec.kind) {
    case "area":
      return <SeriesChart spec={spec} variant="area" />;
    case "signed_area":
      return <SignedArea spec={spec} />;
    case "bar":
    case "grouped_bar":
      return <Bars spec={spec} />;
    case "diverging_bar":
      return <DivergingBars spec={spec} />;
    case "price_volume":
      return <PriceVolume spec={spec} />;
    case "line":
    default:
      return <SeriesChart spec={spec} variant="line" />;
  }
});
