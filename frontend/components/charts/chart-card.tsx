"use client";

import type { ReactNode } from "react";

/** Shared frame: title + data-freshness caption + chart area. */
export function ChartCard({
  title,
  fetchedAt,
  children,
}: {
  title: string;
  fetchedAt?: string;
  children: ReactNode;
}) {
  const stamp = fetchedAt
    ? new Date(fetchedAt).toLocaleString("en-GB", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;
  return (
    <figure className="rounded-xl border border-border bg-card/50 p-4">
      <figcaption className="mb-3 flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium text-foreground">{title}</span>
        {stamp && (
          <span className="shrink-0 text-[11px] text-ink-tertiary">
            data {stamp}
          </span>
        )}
      </figcaption>
      <div className="h-56 w-full">{children}</div>
    </figure>
  );
}
