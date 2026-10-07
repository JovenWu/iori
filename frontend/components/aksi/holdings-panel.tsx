"use client";

import { PencilIcon, PlusIcon } from "lucide-react";

import { HoldingsEditor } from "@/components/aksi/holdings-editor";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { copy, type Holding } from "@/lib/aksi";
import { useSettings } from "@/lib/settings";
import { cn } from "@/lib/utils";

type PanelProps = {
  holdings: Holding[];
  loaded: boolean;
  /** event count per symbol — drives the badge + filter affordance */
  counts: Record<string, number>;
  selected: string | null;
  onSelect: (symbol: string | null) => void;
  onEdit: () => void;
};

/** Fixed left rail: every holding, with an event-count badge and a
 * click-to-filter affordance so long portfolios stay navigable. */
export function HoldingsRail({ holdings, loaded, counts, selected, onSelect, onEdit }: PanelProps) {
  const lang = useSettings().settings.language;
  const t = copy[lang];
  const fmt = new Intl.NumberFormat(lang === "id" ? "id-ID" : "en-US");
  return (
    <aside className="hidden w-60 shrink-0 flex-col border-r border-border md:flex">
      <div className="px-2 pb-1 pt-3">
        {/* Same outer/inner padding as a row below, so the count + pencil
            land on the badge column's right edge. */}
        <div className="flex items-center gap-2 px-2 py-1">
          <h2 className="min-w-0 truncate text-sm font-medium tracking-tight">{t.holdingsTitle}</h2>
          {loaded && holdings.length > 0 && (
            <span className="ml-auto font-mono text-xs text-muted-foreground">
              {t.holdingsCount(holdings.length)}
            </span>
          )}
          <button
            type="button"
            aria-label={t.editHoldings}
            onClick={onEdit}
            className={cn(
              "grid size-5 shrink-0 place-items-center rounded text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground",
              !(loaded && holdings.length > 0) && "ml-auto",
            )}
          >
            <PencilIcon className="size-3.5" />
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3 pt-1">
        {!loaded && (
          <div className="space-y-1 px-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-full rounded-md" />
            ))}
          </div>
        )}
        {loaded && holdings.length === 0 && (
          <div className="space-y-2 px-2 py-3 text-xs text-muted-foreground">
            <p>{t.holdingsEmpty}</p>
            <Button size="sm" variant="secondary" onClick={onEdit}>
              <PlusIcon className="size-3.5" />
              {t.holdingsEmptyCta}
            </Button>
          </div>
        )}
        {loaded && holdings.length > 0 && (
          <ul className="space-y-0.5">
            {holdings.map((h) => {
              const count = counts[h.symbol] ?? 0;
              const active = selected === h.symbol;
              return (
                <li key={h.symbol}>
                  <button
                    type="button"
                    aria-pressed={active}
                    onClick={() => onSelect(active ? null : h.symbol)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors",
                      active ? "bg-accent text-foreground" : "text-ink-muted hover:bg-secondary hover:text-foreground",
                    )}
                  >
                    <span className="min-w-0 font-mono text-sm font-medium">{h.symbol}</span>
                    <span className="ml-auto font-mono text-xs text-ink-tertiary">{fmt.format(h.shares)}</span>
                    {count > 0 && (
                      <span className="rounded bg-primary/20 px-1.5 py-0.5 font-mono text-[10px] leading-none text-primary-hover">
                        {count}
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>
  );
}

/** Mobile fallback (<md): a horizontal chip strip above the event list. */
export function HoldingsStrip({ holdings, loaded, counts, selected, onSelect, onEdit }: PanelProps) {
  const lang = useSettings().settings.language;
  const t = copy[lang];
  if (!loaded) return null;
  return (
    <div className="flex items-center gap-1.5 overflow-x-auto pb-1 md:hidden">
      <button
        type="button"
        onClick={onEdit}
        className="flex shrink-0 items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        <PencilIcon className="size-3" />
        {holdings.length === 0 ? t.holdingsEmptyCta : t.editHoldings}
      </button>
      {holdings.map((h) => {
        const count = counts[h.symbol] ?? 0;
        const active = selected === h.symbol;
        return (
          <button
            key={h.symbol}
            type="button"
            aria-pressed={active}
            onClick={() => onSelect(active ? null : h.symbol)}
            className={cn(
              "flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-xs transition-colors",
              active
                ? "border-primary/50 bg-primary/10 text-foreground"
                : "border-border text-muted-foreground hover:text-foreground",
            )}
          >
            {h.symbol}
            {count > 0 && (
              <span className="rounded bg-primary/20 px-1 font-mono text-[10px] leading-4 text-primary-hover">
                {count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/** The row editor, hosted in a dialog so the list stays out of the way. */
export function HoldingsEditDialog({
  holdings,
  open,
  onOpenChange,
}: {
  holdings: Holding[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const lang = useSettings().settings.language;
  const t = copy[lang];
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t.holdingsTitle}</DialogTitle>
          <DialogDescription>{t.holdingsDesc}</DialogDescription>
        </DialogHeader>
        <HoldingsEditor initial={holdings} onSaved={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}
