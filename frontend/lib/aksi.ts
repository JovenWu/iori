/* Aksi Korporasi types + formatting. Shapes come from backend/app/aksi —
   keep in sync. Numbers are only formatted here, never computed. */

export type Lang = "id" | "en";

export type Holding = { symbol: string; shares: number; avg_price?: number | null };

export type FigureUnit = "IDR" | "shares" | "rights" | "ratio" | "days" | "date";

export type Figure = {
  key: string;
  value: number | string | null;
  unit: FigureUnit;
  formula: string;
  inputs: Record<string, unknown>;
  gap: string | null;
};

export type Finding = {
  id: string;
  kind: string;
  text_id: string;
  text_en: string;
  values: Record<string, unknown>;
  source_tool: string;
  fetched_at: string | null;
};

export type Brief = {
  headline_id: string;
  headline_en: string;
  summary_id: string;
  summary_en: string;
  verify_id: string[];
  verify_en: string[];
  context_ids: string[];
  gate: { passed: boolean; reasons: string[]; template: boolean };
};

export type EventKind = "right_issue" | "dividend" | "warrant";

export type PublicEvent = {
  event_id: string;
  symbol: string;
  kind: EventKind;
  phase: string;
  shares: number;
  urgency: number | null;
  row: Record<string, string | number | null>;
};

export type AksiEvent = PublicEvent & {
  figures?: Record<string, Figure>;
  findings: Finding[];
  brief?: Brief;
};

export type ReportEvent = {
  event: PublicEvent;
  figures: Record<string, Figure>;
  findings: Finding[];
  brief: Brief;
};

export type Report = {
  id: string;
  mode: "live" | "replay";
  as_of: string;
  status: string;
  holdings_snapshot: Holding[];
  events: ReportEvent[];
  credits_spent: number;
  created_at: string;
  updated_at: string;
};

export type AksiStreamEvent = {
  seq: number;
  type:
    | "started"
    | "step"
    | "tool"
    | "event_found"
    | "numbers"
    | "finding"
    | "brief"
    | "budget"
    | "done"
    | "stopped"
    | "error";
  data: unknown;
};

export const KIND_LABEL: Record<EventKind, Record<Lang, string>> = {
  right_issue: { en: "Rights issue (HMETD)", id: "HMETD (rights issue)" },
  dividend: { en: "Cash dividend", id: "Dividen tunai" },
  warrant: { en: "Warrant", id: "Waran" },
};

const SOURCE_LABEL: Record<string, Record<Lang, string>> = {
  sectors_insider_filings: { en: "Insider filings", id: "Laporan orang dalam" },
  sectors_daily_prices: { en: "Daily prices", id: "Harga harian" },
  sectors_shareholders: { en: "Shareholders", id: "Pemegang saham" },
  sectors_corporate_actions: { en: "Corporate actions", id: "Aksi korporasi" },
  sectors_company_corporate_actions: { en: "Corporate actions", id: "Aksi korporasi" },
  sectors_company_report: { en: "Company report", id: "Laporan emiten" },
  sectors_news: { en: "News", id: "Berita" },
  sectors_broker_top: { en: "Top brokers", id: "Broker teratas" },
};

export function sourceLabel(tool: string, lang: Lang): string {
  const hit = SOURCE_LABEL[tool];
  if (hit) return hit[lang];
  const words = tool.replace(/^sectors_/, "").replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/* Evidence drawer — figure keys, formula/input variable names, and gap
   strings ship as code identifiers; these maps render them as words. */

const FIGURE_LABEL: Record<string, Record<Lang, string>> = {
  rights_entitled: { en: "Rights entitled (HMETD)", id: "HMETD yang diperoleh" },
  dilution_if_ignored: { en: "Dilution if ignored", id: "Dilusi jika dibiarkan" },
  cost_to_exercise_all: { en: "Cost to exercise all", id: "Dana untuk tebus semua" },
  terp: { en: "TERP (theoretical)", id: "TERP (teoretis)" },
  right_value: { en: "Value per right", id: "Nilai per HMETD" },
  rights_value_total: { en: "Theoretical rights value", id: "Nilai teoretis hak" },
  value_if_ignored: { en: "Position value if ignored", id: "Nilai posisi jika dibiarkan" },
  value_if_exercised: { en: "Position value if exercised", id: "Nilai posisi jika ditebus" },
  discount_to_market: { en: "Exercise price vs market", id: "Harga tebus vs pasar" },
  deadline: { en: "Deadline", id: "Tenggat" },
  days_to_deadline: { en: "Days to deadline", id: "Hari menuju tenggat" },
  days_to_cum: { en: "Days to cum date", id: "Hari menuju tanggal cum" },
  gross_dividend: { en: "Gross dividend", id: "Dividen bruto" },
  yield_on_cost: { en: "Yield on cost", id: "Yield atas modal" },
  intrinsic_per_warrant: { en: "Intrinsic value per warrant", id: "Nilai intrinsik per waran" },
};

const VAR_LABEL: Record<string, Record<Lang, string>> = {
  shares: { en: "shares", id: "lembar" },
  old_ratio: { en: "old ratio", id: "rasio lama" },
  new_ratio: { en: "new ratio", id: "rasio baru" },
  price: { en: "exercise price", id: "harga tebus" },
  p_cum: { en: "cum price", id: "harga cum" },
  p_now: { en: "current price", id: "harga kini" },
  terp: { en: "TERP", id: "TERP" },
  right_value: { en: "right value", id: "nilai HMETD" },
  rights_entitled: { en: "rights", id: "HMETD" },
  dividend_amount: { en: "dividend per share", id: "dividen per saham" },
  avg_price: { en: "avg price", id: "harga rata-rata" },
  today: { en: "today", id: "hari ini" },
  target: { en: "target date", id: "tanggal tujuan" },
  deadline: { en: "deadline", id: "tenggat" },
  date: { en: "date", id: "tanggal" },
  cum_date: { en: "cum date", id: "tanggal cum" },
  ex_per_end: { en: "exercise end", id: "akhir pelaksanaan" },
  maturity_date: { en: "maturity", id: "jatuh tempo" },
  trading_period_end: { en: "rights deadline", id: "batas HMETD" },
};

export function figureLabel(key: string, lang: Lang, kind?: EventKind): string {
  const tile = kind ? copy[lang].tiles[kind].find((x) => x.key === key) : undefined;
  const label = tile?.label ?? FIGURE_LABEL[key]?.[lang];
  if (label) return label;
  const words = key.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function inputLabel(key: string, lang: Lang): string {
  return VAR_LABEL[key]?.[lang] ?? key.replaceAll("_", " ");
}

export function humanizeVars(text: string, lang: Lang): string {
  return text.replace(/[a-z_]+/g, (m) => VAR_LABEL[m]?.[lang] ?? m.replaceAll("_", " "));
}

export function gapText(gap: string, lang: Lang): string {
  const fields = gap.replace(/^missing:\s*/i, "");
  return `${copy[lang].missingFields} ${humanizeVars(fields, lang)}`;
}

export function formatInputValue(v: unknown, lang: Lang): string {
  const n = typeof v === "number" ? v : Number(v);
  if (v !== null && v !== "" && !Number.isNaN(n)) {
    return new Intl.NumberFormat(lang === "id" ? "id-ID" : "en-US", {
      maximumFractionDigits: 2,
    }).format(n);
  }
  return String(v);
}

const MONTHS: Record<Lang, string[]> = {
  id: ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"],
  en: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
};

function nf(lang: Lang, digits: number) {
  return new Intl.NumberFormat(lang === "id" ? "id-ID" : "en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatIdr(v: number, lang: Lang = "id"): string {
  const abs = Math.abs(v);
  const digits = abs < 1000 && !Number.isInteger(abs) ? 2 : 0;
  return `${v < 0 ? "−" : ""}Rp${nf(lang, digits).format(abs)}`;
}

export function formatPct(ratio: number, lang: Lang = "id"): string {
  return `${nf(lang, 2).format(ratio * 100)}%`;
}

export function formatDate(iso: string, lang: Lang = "id"): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${d} ${MONTHS[lang][m - 1]} ${y}`;
}

export function formatFigure(f: Figure | undefined, lang: Lang = "id"): string {
  if (!f || f.value === null || f.value === undefined) return "—";
  switch (f.unit) {
    case "IDR":
      return formatIdr(Number(f.value), lang);
    case "ratio":
      return formatPct(Number(f.value), lang);
    case "date":
      return formatDate(String(f.value), lang);
    case "days":
      return lang === "id" ? `${f.value} hari` : `${f.value} days`;
    default:
      return nf(lang, 0).format(Number(f.value));
  }
}

export function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

/** The deadline an event's `urgency` counts down to — mirrors the backend's
 * `_urgency` target per kind. Returns "YYYY-MM-DD" or null. */
export function deadlineOf(ev: AksiEvent, asOf: string | null): string | null {
  const row = ev.row;
  let raw: unknown;
  if (ev.kind === "right_issue") raw = row.trading_period_end;
  else if (ev.kind === "warrant") raw = row.ex_per_end ?? row.maturity_date;
  else {
    const cum = row.cum_date ? String(row.cum_date).slice(0, 10) : "";
    raw = cum && (!asOf || asOf <= cum) ? row.cum_date : row.payment_date;
  }
  const s = raw ? String(raw).slice(0, 10) : "";
  return /^\d{4}-\d{2}-\d{2}$/.test(s) ? s : null;
}

/** "YYYY-MM-DD" → local Date (no UTC shift). */
export function parseDay(iso: string): Date {
  return new Date(`${iso.slice(0, 10)}T00:00:00`);
}

/** local Date → "YYYY-MM-DD" (no UTC shift). */
export function toDayIso(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

/* UI copy, keyed by display language. The global toggle switches both
   chrome and brief content (briefs/findings ship both languages). */

export type AksiCopy = {
  title: string;
  sidebarLabel: string;
  modeToday: string;
  modeReplay: string;
  check: string;
  stop: string;
  replayBannerPre: string;
  replayBannerPost: string;
  empty: string;
  asOf: string;
  holdingsTitle: string;
  holdingsDesc: string;
  save: string;
  saving: string;
  colTicker: string;
  colShares: string;
  colAvgPrice: string;
  ariaTicker: string;
  ariaShares: string;
  ariaAvgPrice: string;
  removeRow: string;
  addHolding: string;
  holdingsEmpty: string;
  holdingsEmptyCta: string;
  holdingsCount: (n: number) => string;
  editHoldings: string;
  filteredTo: string;
  clearFilter: string;
  pickReplayDate: string;
  toggleDetails: string;
  actSoon: string;
  upcoming: string;
  noDeadline: string;
  emptyForSymbol: (symbol: string) => string;
  errTicker: string;
  errShares: string;
  errDuplicate: string;
  savedToast: string;
  loadFailed: string;
  saveFailed: string;
  checkFailed: string;
  timelineAria: string;
  today: string;
  inDays: (n: number) => string;
  deadlineLabel: string;
  noReplayFor: (date: string) => string;
  ratio: string;
  exercisePrice: string;
  dividendPerShare: string;
  dilutionBefore: string;
  dilutionAfter: string;
  scenariosHeading: string;
  scenarioExercise: string;
  scenarioSell: string;
  scenarioLapse: string;
  scenarioExerciseRest: (cost: string) => string;
  scenarioSellRest: (value: string, dilution: string) => string;
  scenarioLapseRest: (deadline: string, value: string) => string;
  verify: string;
  cardDisclaimer: string;
  disclaimer: string;
  sources: string;
  sourcesTitle: string;
  sourcesDesc: string;
  figuresHeading: string;
  contextHeading: string;
  fetched: string;
  missingFields: string;
  rawHeading: string;
  limitations: string;
  tiles: Record<EventKind, { key: string; label: string }[]>;
  timelineLabels: Record<EventKind, { key: string; label: string }[]>;
};

export const copy: Record<Lang, AksiCopy> = {
  en: {
    title: "Corporate Actions",
    sidebarLabel: "Corporate Actions",
    modeToday: "Today",
    modeReplay: "Replay",
    check: "Check corporate actions",
    stop: "Stop",
    replayBannerPre: "Historical replay — data as of",
    replayBannerPost: "Not current data.",
    empty: "No corporate actions for your holdings in the last 30 days or the next 60 days",
    asOf: "as of",
    holdingsTitle: "Your holdings",
    holdingsDesc: "Share counts in shares (1 lot = 100 shares).",
    save: "Save",
    saving: "Saving…",
    colTicker: "Ticker",
    colShares: "Shares",
    colAvgPrice: "Avg price (optional)",
    ariaTicker: "Ticker",
    ariaShares: "Shares",
    ariaAvgPrice: "Average price",
    removeRow: "Remove row",
    addHolding: "Add holding",
    holdingsEmpty: "No holdings yet.",
    holdingsEmptyCta: "Add a holding",
    holdingsCount: (n) => `${n} holding${n === 1 ? "" : "s"}`,
    editHoldings: "Edit holdings",
    filteredTo: "Showing",
    clearFilter: "Clear ticker filter",
    pickReplayDate: "Pick replay date",
    toggleDetails: "Toggle details",
    actSoon: "Due soon",
    upcoming: "Upcoming",
    noDeadline: "No deadline set",
    emptyForSymbol: (s) => `No corporate actions for ${s}`,
    errTicker: "Ticker must be 4 letters, e.g. BBCA.",
    errShares: "Shares must be a whole number ≥ 1.",
    errDuplicate: "Duplicate tickers are not allowed.",
    savedToast: "Holdings saved",
    loadFailed: "Couldn't load holdings",
    saveFailed: "Couldn't save holdings",
    checkFailed: "Check failed",
    timelineAria: "Timeline",
    today: "Today",
    inDays: (n) => (n === 1 ? "in 1 day" : `in ${n} days`),
    deadlineLabel: "Deadline",
    noReplayFor: (d) => `No replay for ${d} yet — run a check.`,
    ratio: "Ratio",
    exercisePrice: "Exercise price",
    dividendPerShare: "Dividend per share",
    dilutionBefore: "If the rights lapse, your ownership falls",
    dilutionAfter: ".",
    scenariosHeading: "Three scenarios (theoretical, before transaction costs):",
    scenarioExercise: "Exercise all",
    scenarioSell: "Sell the rights",
    scenarioLapse: "Let lapse",
    scenarioExerciseRest: (cost) => `pay ${cost}, ownership unchanged.`,
    scenarioSellRest: (value, dilution) => `theoretical value ±${value}, ownership falls ${dilution}.`,
    scenarioLapseRest: (deadline, value) => `rights expire after ${deadline}, theoretical value of ${value} lost.`,
    verify: "What to verify",
    cardDisclaimer: "Educational information, not investment advice.",
    disclaimer: "Educational information, not investment advice. Verify against official IDX disclosures and the prospectus.",
    sources: "View data sources",
    sourcesTitle: "data sources",
    sourcesDesc: "Every figure is computed by code from Sectors data — not by AI.",
    figuresHeading: "Figures & formulas",
    contextHeading: "Context",
    fetched: "fetched",
    missingFields: "Missing data:",
    rawHeading: "Raw corporate-action data",
    limitations: "Limitations: calendar data does not include announcement dates; replay mode only uses data up to the replay date; the controlling-shareholder name comes from the latest ownership data.",
    tiles: {
      right_issue: [
        { key: "rights_entitled", label: "Your rights (HMETD)" },
        { key: "cost_to_exercise_all", label: "Cost to exercise all" },
        { key: "terp", label: "TERP (theoretical)" },
        { key: "rights_value_total", label: "Theoretical rights value" },
      ],
      dividend: [
        { key: "gross_dividend", label: "Your gross dividend" },
        { key: "yield_on_cost", label: "Yield on cost" },
        { key: "days_to_cum", label: "Days to cum date" },
      ],
      warrant: [
        { key: "intrinsic_per_warrant", label: "Intrinsic value / warrant" },
        { key: "days_to_deadline", label: "Days to exercise deadline" },
      ],
    },
    timelineLabels: {
      right_issue: [
        { key: "cum_date", label: "Cum" },
        { key: "ex_date", label: "Ex" },
        { key: "recording_date", label: "Recording" },
        { key: "trading_period_start", label: "Rights trading starts" },
        { key: "trading_period_end", label: "Rights deadline" },
      ],
      dividend: [
        { key: "cum_date", label: "Cum" },
        { key: "ex_date", label: "Ex" },
        { key: "recording_date", label: "Recording" },
        { key: "payment_date", label: "Payment" },
      ],
      warrant: [
        { key: "trading_period_start", label: "Trading starts" },
        { key: "ex_per_start", label: "Exercise starts" },
        { key: "ex_per_end", label: "Exercise ends" },
        { key: "maturity_date", label: "Maturity" },
      ],
    },
  },
  id: {
    title: "Aksi Korporasi",
    sidebarLabel: "Aksi Korporasi",
    modeToday: "Hari ini",
    modeReplay: "Replay",
    check: "Cek aksi korporasi",
    stop: "Stop",
    replayBannerPre: "Replay historis — data per",
    replayBannerPost: "Bukan data terkini.",
    empty: "Belum ada aksi korporasi untuk saham kamu dalam 30 hari terakhir atau 60 hari ke depan",
    asOf: "per",
    holdingsTitle: "Saham kamu",
    holdingsDesc: "Jumlah dalam lembar (1 lot = 100 lembar).",
    save: "Simpan",
    saving: "Menyimpan…",
    colTicker: "Saham",
    colShares: "Lembar",
    colAvgPrice: "Harga rata-rata (opsional)",
    ariaTicker: "Saham",
    ariaShares: "Jumlah lembar",
    ariaAvgPrice: "Harga rata-rata",
    removeRow: "Hapus baris",
    addHolding: "Tambah saham",
    holdingsEmpty: "Belum ada saham.",
    holdingsEmptyCta: "Tambah saham",
    holdingsCount: (n) => `${n} saham`,
    editHoldings: "Ubah saham",
    filteredTo: "Menampilkan",
    clearFilter: "Hapus filter saham",
    pickReplayDate: "Pilih tanggal replay",
    toggleDetails: "Lihat detail",
    actSoon: "Mendesak",
    upcoming: "Mendatang",
    noDeadline: "Tanpa tenggat",
    emptyForSymbol: (s) => `Belum ada aksi korporasi untuk ${s}`,
    errTicker: "Ticker harus 4 huruf, mis. BBCA.",
    errShares: "Jumlah lembar harus bilangan bulat ≥ 1.",
    errDuplicate: "Ticker ganda tidak diperbolehkan.",
    savedToast: "Saham tersimpan",
    loadFailed: "Gagal memuat saham",
    saveFailed: "Gagal menyimpan saham",
    checkFailed: "Pengecekan gagal",
    timelineAria: "Linimasa",
    today: "Hari ini",
    inDays: (n) => `${n} hari lagi`,
    deadlineLabel: "Tenggat",
    noReplayFor: (d) => `Belum ada replay untuk ${d} — jalankan pengecekan.`,
    ratio: "Rasio",
    exercisePrice: "Harga pelaksanaan",
    dividendPerShare: "Dividen per saham",
    dilutionBefore: "Jika HMETD dibiarkan hangus, porsi kepemilikan turun",
    dilutionAfter: ".",
    scenariosHeading: "Tiga skenario (teoretis, sebelum biaya transaksi):",
    scenarioExercise: "Ditebus semua",
    scenarioSell: "HMETD dijual",
    scenarioLapse: "Dibiarkan",
    scenarioExerciseRest: (cost) => `bayar ${cost}, porsi kepemilikan tetap.`,
    scenarioSellRest: (value, dilution) => `nilai teoretis ±${value}, porsi turun ${dilution}.`,
    scenarioLapseRest: (deadline, value) => `hak hangus setelah ${deadline}, nilai teoretis hilang ${value}.`,
    verify: "Yang perlu kamu cek",
    cardDisclaimer: "Informasi edukatif, bukan rekomendasi investasi.",
    disclaimer: "Informasi edukatif, bukan rekomendasi investasi. Verifikasi pada keterbukaan resmi IDX dan prospektus.",
    sources: "Lihat sumber data",
    sourcesTitle: "sumber data",
    sourcesDesc: "Setiap angka dihitung oleh kode dari data Sectors — bukan oleh AI.",
    figuresHeading: "Angka & rumus",
    contextHeading: "Konteks",
    fetched: "diambil",
    missingFields: "Data tidak tersedia:",
    rawHeading: "Data mentah aksi korporasi",
    limitations: "Batasan: data kalender tidak memuat tanggal pengumuman; mode replay hanya memakai data sampai tanggal replay; nama pemegang saham utama berasal dari data kepemilikan terkini.",
    tiles: {
      right_issue: [
        { key: "rights_entitled", label: "HMETD kamu" },
        { key: "cost_to_exercise_all", label: "Dana untuk tebus semua" },
        { key: "terp", label: "TERP (teoretis)" },
        { key: "rights_value_total", label: "Nilai teoretis hak" },
      ],
      dividend: [
        { key: "gross_dividend", label: "Dividen bruto kamu" },
        { key: "yield_on_cost", label: "Yield on cost" },
        { key: "days_to_cum", label: "Menuju tanggal cum" },
      ],
      warrant: [
        { key: "intrinsic_per_warrant", label: "Nilai intrinsik / waran" },
        { key: "days_to_deadline", label: "Menuju batas pelaksanaan" },
      ],
    },
    timelineLabels: {
      right_issue: [
        { key: "cum_date", label: "Cum" },
        { key: "ex_date", label: "Ex" },
        { key: "recording_date", label: "Recording" },
        { key: "trading_period_start", label: "Mulai perdagangan HMETD" },
        { key: "trading_period_end", label: "Batas HMETD" },
      ],
      dividend: [
        { key: "cum_date", label: "Cum" },
        { key: "ex_date", label: "Ex" },
        { key: "recording_date", label: "Recording" },
        { key: "payment_date", label: "Pembayaran" },
      ],
      warrant: [
        { key: "trading_period_start", label: "Mulai perdagangan" },
        { key: "ex_per_start", label: "Mulai pelaksanaan" },
        { key: "ex_per_end", label: "Akhir pelaksanaan" },
        { key: "maturity_date", label: "Jatuh tempo" },
      ],
    },
  },
};
