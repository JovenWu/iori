"use client";

import { useState } from "react";
import { PlusIcon, Trash2Icon } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Holding } from "@/lib/aksi";
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

function parse(rows: Row[]): { holdings: Holding[]; error: string | null } {
  const holdings = rows
    .filter((r) => r.symbol.trim() || r.shares.trim())
    .map((r) => ({
      symbol: r.symbol.trim().toUpperCase().replace(/\.JK$/, ""),
      shares: Number(r.shares),
      avg_price: r.avgPrice.trim() ? Number(r.avgPrice) : null,
    }));
  if (holdings.some((h) => !SYMBOL_RE.test(h.symbol))) return { holdings, error: "Ticker harus 4 huruf, misalnya BBCA." };
  if (holdings.some((h) => !Number.isInteger(h.shares) || h.shares < 1)) return { holdings, error: "Jumlah saham harus bilangan bulat ≥ 1 (lembar)." };
  if (new Set(holdings.map((h) => h.symbol)).size !== holdings.length) return { holdings, error: "Ticker tidak boleh ganda." };
  return { holdings, error: null };
}

export function HoldingsEditor({ initial }: { initial: Holding[] }) {
  const [rows, setRows] = useState<Row[]>(() => toRows(initial));
  const [saving, setSaving] = useState(false);
  const running = useAksiStore((s) => s.running);
  const { holdings, error } = parse(rows);
  const normalizedInitial = initial.map((h) => ({ symbol: h.symbol, shares: h.shares, avg_price: h.avg_price ?? null }));
  const dirty = JSON.stringify(holdings) !== JSON.stringify(normalizedInitial);

  const update = (i: number, patch: Partial<Row>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const save = async () => {
    setSaving(true);
    const ok = await useAksiStore.getState().saveHoldings(holdings);
    setSaving(false);
    if (ok) toast.success("Portofolio tersimpan");
  };

  return (
    <section className="rounded-xl border border-border bg-card">
      <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div>
          <h2 className="text-sm font-medium tracking-tight">Saham yang kamu pegang</h2>
          <p className="text-xs text-muted-foreground">Jumlah dalam lembar (1 lot = 100 lembar).</p>
        </div>
        <Button size="sm" variant="secondary" disabled={!dirty || !!error || saving || running} onClick={save}>
          {saving ? "Menyimpan…" : "Simpan"}
        </Button>
      </header>
      <div className="space-y-2 px-4 py-3">
        <div className={`${COLS} text-xs text-muted-foreground`}>
          <span>Ticker</span>
          <span>Jumlah (lembar)</span>
          <span>Harga rata-rata (opsional)</span>
          <span />
        </div>
        {rows.map((r, i) => (
          <div key={i} className={COLS}>
            <Input aria-label="Ticker" value={r.symbol} maxLength={7} placeholder="BBCA"
              className="font-mono uppercase" onChange={(e) => update(i, { symbol: e.target.value })} />
            <Input aria-label="Jumlah lembar" inputMode="numeric" value={r.shares} placeholder="1000"
              className="font-mono" onChange={(e) => update(i, { shares: e.target.value.replace(/[^\d]/g, "") })} />
            <Input aria-label="Harga rata-rata" inputMode="decimal" value={r.avgPrice} placeholder="—"
              className="font-mono" onChange={(e) => update(i, { avgPrice: e.target.value.replace(/[^\d.]/g, "") })} />
            <Button size="icon-sm" variant="ghost" aria-label="Hapus baris"
              onClick={() => setRows((rs) => (rs.length > 1 ? rs.filter((_, j) => j !== i) : [BLANK]))}>
              <Trash2Icon className="size-4" />
            </Button>
          </div>
        ))}
        <div className="flex items-center justify-between gap-3">
          <Button size="sm" variant="ghost" disabled={rows.length >= 30} onClick={() => setRows((rs) => [...rs, BLANK])}>
            <PlusIcon className="size-4" />
            Tambah saham
          </Button>
          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>
      </div>
    </section>
  );
}
