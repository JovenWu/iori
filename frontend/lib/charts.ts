/* Chart spec shared by the SSE stream, history payloads, and components.
   Shape is produced by backend/app/sectors/charts.py — keep in sync. */

export type ChartKind =
  | "line"
  | "area"
  | "signed_area"
  | "bar"
  | "diverging_bar"
  | "grouped_bar"
  | "price_volume";

export type ChartRow = Record<string, string | number | null>;

export type ChartSpec = {
  id: string;
  tool: string;
  view: string;
  kind: ChartKind;
  title: string;
  x: { key: string; label: string; type: "time" | "category" };
  series: { key: string; label: string }[];
  data: ChartRow[];
  fetched_at: string;
  format?: "percent" | "percent_raw" | "idr" | "number";
};

export function formatChartValue(
  v: number | null | undefined,
  format?: ChartSpec["format"],
): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  switch (format) {
    case "percent":
      return `${(v * 100).toFixed(1)}%`;
    case "percent_raw":
      return `${v.toFixed(1)}%`;
    case "idr":
    case "number":
    default: {
      const abs = Math.abs(v);
      if (abs >= 1e12) return `${(v / 1e12).toFixed(1)}T`;
      if (abs >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
      if (abs >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
      if (abs >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
      return `${v}`;
    }
  }
}
