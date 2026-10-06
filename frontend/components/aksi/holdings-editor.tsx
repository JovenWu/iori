"use client";

import { useState } from "react";
import { PlusIcon, Trash2Icon } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { copy, type AksiCopy, type Holding } from "@/lib/aksi";
import { useAksiStore } from "@/lib/stores/aksi";

type Row = { symbol: string; shares: string; avgPrice: string };

const SYMBOL_RE = /^[A-Z]{4}$/;
const BLANK: Row = { symbol: "", shares: "", avgPrice: "" };
const COLS = "grid grid-cols-[6rem_1fr_1fr_2rem] items-center gap-2";

function toRows(holdings: Holding[]): Row[] {
  return holdings.length
    ? holdings.map((h) => ({ symbol: h.symbol, shares: String(h.shares), avgPrice: h.avg_price ? String(h.avg_price) : "" }))
    : [BLANK];
}

function parse(rows: Row[]): { holdings: Holding[]; errorKey: keyof Pick<AksiCopy, "errTicker" | "errShares" | "errDuplicate"> | null } {
  const holdings = rows
    .filter((r) => r.symbol.trim() || r.shares.trim())
    .map((r) => ({
      symbol: r.symbol.trim().toUpperCase().replace(/\.JK$/, ""),
      shares: Number(r.shares),
      avg_price: r.avgPrice.trim() ? Number(r.avgPrice) : null,
    }));
  if (holdings.some((h) => !SYMBOL_RE.test(h.symbol))) return { holdings, errorKey: "errTicker" };
  if (holdings.some((h) => !Number.isInteger(h.shares) || h.shares < 1)) return { holdings, errorKey: "errShares" };
  if (new Set(holdings.map((h) => h.symbol)).size !== holdings.length) return { holdings, errorKey: "errDuplicate" };
  return { holdings, errorKey: null };
}

export function HoldingsEditor({ initial }: { initial: Holding[] }) {
  const [rows, setRows] = useState<Row[]>(() => toRows(initial));
  const [saving, setSaving] = useState(false);
  const running = useAksiStore((s) => s.running);
  const lang = useAksiStore((s) => s.lang);
  const t = copy[lang];
  const { holdings, errorKey } = parse(rows);
  const error = errorKey ? t[errorKey] : null;
  const normalizedInitial = initial.map((h) => ({ symbol: h.symbol, shares: h.shares, avg_price: h.avg_price ?? null }));
  const dirty = JSON.stringify(holdings) !== JSON.stringify(normalizedInitial);

  const update = (i: number, patch: Partial<Row>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const save = async () => {
    setSaving(true);
    const ok = await useAksiStore.getState().saveHoldings(holdings);
    setSaving(false);
    if (ok) toast.success(t.savedToast);
  };

  return (
    <section className="rounded-xl border border-border bg-card">
      <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div>
          <h2 className="text-sm font-medium tracking-tight">{t.holdingsTitle}</h2>
          <p className="text-xs text-muted-foreground">{t.holdingsDesc}</p>
        </div>
        <Button size="sm" variant="secondary" disabled={!dirty || !!error || saving || running} onClick={save}>
          {saving ? t.saving : t.save}
        </Button>
      </header>
      <div className="space-y-2 px-4 py-3">
        <div className={`${COLS} text-xs text-muted-foreground`}>
          <span>{t.colTicker}</span>
          <span>{t.colShares}</span>
          <span>{t.colAvgPrice}</span>
          <span />
        </div>
        {rows.map((r, i) => (
          <div key={i} className={COLS}>
            <Input aria-label={t.ariaTicker} value={r.symbol} maxLength={7} placeholder="BBCA"
              className="font-mono uppercase" onChange={(e) => update(i, { symbol: e.target.value })} />
            <Input aria-label={t.ariaShares} inputMode="numeric" value={r.shares} placeholder="1000"
              className="font-mono" onChange={(e) => update(i, { shares: e.target.value.replace(/[^\d]/g, "") })} />
            <Input aria-label={t.ariaAvgPrice} inputMode="decimal" value={r.avgPrice} placeholder="—"
              className="font-mono" onChange={(e) => update(i, { avgPrice: e.target.value.replace(/[^\d.]/g, "") })} />
            <Button size="icon-sm" variant="ghost" aria-label={t.removeRow}
              onClick={() => setRows((rs) => (rs.length > 1 ? rs.filter((_, j) => j !== i) : [BLANK]))}>
              <Trash2Icon className="size-4" />
            </Button>
          </div>
        ))}
        <div className="flex items-center justify-between gap-3">
          <Button size="sm" variant="ghost" disabled={rows.length >= 30} onClick={() => setRows((rs) => [...rs, BLANK])}>
            <PlusIcon className="size-4" />
            {t.addHolding}
          </Button>
          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>
      </div>
    </section>
  );
}
