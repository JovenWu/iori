"use client";

import { create } from "zustand";
import { toast } from "sonner";

import type { ToolActivity } from "@/components/agent-status";
import { copy, type AksiEvent, type AksiStreamEvent, type Brief, type Finding, type Holding, type PublicEvent, type Report } from "@/lib/aksi";
import { loadSettings } from "@/lib/settings";
import {
  ApiError,
  getHoldings,
  getLatestReport,
  putHoldings,
  resumeAksiCheck,
  stopAksiCheck,
  streamAksiCheck,
} from "@/lib/api";
import { detailFor, verbFor } from "@/lib/tool-labels";

type Mode = "live" | "replay";

const DEMO_REPLAY_DATE = "2025-07-10"; // WIFI rights-issue window — see the plan's Task 0

interface AksiStore {
  holdings: Holding[];
  holdingsLoaded: boolean;
  /** Bumped on load/save — remounts the editor with fresh initial rows. */
  holdingsVersion: number;
  mode: Mode;
  asOf: string;
  running: boolean;
  failed: boolean;
  stopped: boolean;
  runStartedAt: number | null;
  durationMs?: number;
  tools: ToolActivity[];
  credits: { used: number; budget: number } | null;
  reportId: string | null;
  reportMode: Mode | null;
  reportAsOf: string | null;
  events: Record<string, AksiEvent>;
  order: string[];
  /** Live events whose next deadline is ≤ 7 days away — sidebar badge. */
  urgentCount: number;
  loadHoldings: () => Promise<void>;
  saveHoldings: (holdings: Holding[]) => Promise<boolean>;
  setMode: (mode: Mode) => void;
  setAsOf: (day: string) => void;
  loadLatest: (mode?: Mode) => Promise<void>;
  refreshBadge: () => Promise<void>;
  /** Reattach to a check still running server-side after a refresh — its
   * replay buffer resends every event, rebuilding the board. False = no
   * active run (the caller loads the latest report instead). */
  reattach: () => Promise<boolean>;
  run: () => void;
  stop: () => void;
}

let controller: AbortController | null = null;

function fromReport(r: Report) {
  const events: Record<string, AksiEvent> = {};
  const order: string[] = [];
  for (const re of r.events) {
    if (re.event.event_id in events) continue;
    events[re.event.event_id] = { ...re.event, figures: re.figures, findings: re.findings, brief: re.brief };
    order.push(re.event.event_id);
  }
  return { events, order };
}

function countUrgent(events: Record<string, AksiEvent>, order: string[]) {
  return order.filter((id) => {
    const u = events[id]?.urgency;
    return u !== null && u !== undefined && u <= 7;
  }).length;
}

function applyTool(tools: ToolActivity[], d: Record<string, unknown>): ToolActivity[] {
  const name = String(d.name);
  if (d.status === "call") {
    return [
      ...tools,
      { tool: name, label: verbFor(name), detail: detailFor(d.args as Record<string, unknown>), status: "running" },
    ];
  }
  const outcome: ToolActivity["status"] = d.status === "error" ? "error" : "done";
  const next = [...tools];
  for (let i = next.length - 1; i >= 0; i--) {
    if (next[i].status === "running" && next[i].tool === name) {
      next[i] = { ...next[i], status: outcome };
      break;
    }
  }
  return next;
}

/* Pipeline nodes that emit no `tool` events get a step row of their own so
   the status line narrates them instead of idling on "Thinking…". */
const STEP_TOOLS: Record<string, string> = {
  calculate: "aksi_calc",
  investigate: "aksi_investigate",
  brief: "aksi_brief",
};

function applyStep(tools: ToolActivity[], d: Record<string, unknown>): ToolActivity[] {
  // A new node settles the previous node's step row.
  const settled = tools.map((t) =>
    t.status === "running" && t.tool.startsWith("aksi_") ? { ...t, status: "done" as const } : t,
  );
  const tool = STEP_TOOLS[String(d.node)];
  if (!tool) return settled;
  const eventId = typeof d.event_id === "string" ? d.event_id : "";
  return [
    ...settled,
    { tool, label: verbFor(tool), detail: eventId.split(":")[0] || null, status: "running" },
  ];
}

const initialState = {
  holdings: [] as Holding[],
  holdingsLoaded: false,
  holdingsVersion: 0,
  mode: "live" as Mode,
  asOf: DEMO_REPLAY_DATE,
  running: false,
  failed: false,
  stopped: false,
  runStartedAt: null as number | null,
  tools: [] as ToolActivity[],
  credits: null as { used: number; budget: number } | null,
  reportId: null as string | null,
  reportMode: null as Mode | null,
  reportAsOf: null as string | null,
  events: {} as Record<string, AksiEvent>,
  order: [] as string[],
  urgentCount: 0,
};

export const useAksiStore = create<AksiStore>()((set, get) => {
  const patch = (id: unknown, fn: (e: AksiEvent) => Partial<AksiEvent>) =>
    set((s) => {
      const key = String(id);
      const e = s.events[key];
      return e ? { events: { ...s.events, [key]: { ...e, ...fn(e) } } } : {};
    });

  const settle = (status: ToolActivity["status"]) =>
    set((s) => ({
      tools: s.tools.map((t) => (t.status === "running" ? { ...t, status } : t)),
      durationMs: s.runStartedAt ? Date.now() - s.runStartedAt : undefined,
    }));

  const handleEvent = (ev: AksiStreamEvent) => {
    const d = (ev.data ?? {}) as Record<string, unknown>;
    switch (ev.type) {
      case "started":
        set({
          reportId: String(d.report_id),
          reportMode: d.mode as Mode,
          reportAsOf: String(d.as_of),
          runStartedAt: Number(d.started_at) || Date.now(),
        });
        break;
      case "step":
        set((s) => ({ tools: applyStep(s.tools, d) }));
        break;
      case "tool":
        set((s) => ({ tools: applyTool(s.tools, d) }));
        break;
      case "event_found": {
        const pe = d as unknown as PublicEvent;
        set((s) =>
          // Re-emitted ids (buffer replay, duplicate rows) must not push a
          // second order entry or wipe already-collected findings.
          s.order.includes(pe.event_id)
            ? {}
            : {
                events: { ...s.events, [pe.event_id]: { ...pe, findings: [] } },
                order: [...s.order, pe.event_id],
              });
        break;
      }
      case "numbers":
        patch(d.event_id, () => ({ figures: d.figures as AksiEvent["figures"] }));
        break;
      case "finding":
        patch(d.event_id, (e) => ({ findings: [...e.findings, d as unknown as Finding] }));
        break;
      case "brief":
        patch(d.event_id, () => ({ brief: d as unknown as Brief }));
        break;
      case "budget":
        set({ credits: { used: Number(d.credits_used), budget: Number(d.budget) } });
        break;
      case "done":
        settle("done");
        break;
      case "stopped":
        settle("skipped");
        set({ stopped: true });
        break;
      case "error":
        settle("error");
        set({ failed: true });
        toast.error(String(ev.data));
        break;
    }
  };

  const beginRun = (ctrl: AbortController) => {
    controller = ctrl;
    set({
      running: true, failed: false, stopped: false, tools: [], credits: null,
      events: {}, order: [], reportId: null, reportMode: null, reportAsOf: null,
      runStartedAt: null, durationMs: undefined,
    });
  };

  const consume = async (
    stream: AsyncGenerator<AksiStreamEvent>,
    ctrl: AbortController,
  ) => {
    try {
      for await (const ev of stream) handleEvent(ev);
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        settle("error");
        set({ failed: true });
        toast.error(err instanceof ApiError ? err.message : copy[loadSettings().language].checkFailed);
      }
    } finally {
      if (controller === ctrl) controller = null;
      set((s) => ({
        running: false,
        ...(s.reportMode === "live" ? { urgentCount: countUrgent(s.events, s.order) } : {}),
      }));
    }
  };

  return {
    ...initialState,

    loadHoldings: async () => {
      try {
        const { holdings } = await getHoldings();
        set((s) => ({ holdings, holdingsLoaded: true, holdingsVersion: s.holdingsVersion + 1 }));
      } catch {
        set({ holdingsLoaded: true });
        toast.error(copy[loadSettings().language].loadFailed);
      }
    },

    saveHoldings: async (holdings) => {
      try {
        const saved = await putHoldings(holdings);
        set((s) => ({ holdings: saved.holdings, holdingsVersion: s.holdingsVersion + 1 }));
        return true;
      } catch (err) {
        toast.error(err instanceof ApiError ? err.message : copy[loadSettings().language].saveFailed);
        return false;
      }
    },

    setMode: (mode) => {
      if (get().running) return;
      set({ mode });
      void get().loadLatest(mode);
    },

    setAsOf: (day) =>
      set((s) => ({
        asOf: day,
        // A replay board is only meaningful for its own date — clear it the
        // moment a different date is picked instead of showing stale data.
        ...(s.reportMode === "replay" && s.reportAsOf?.slice(0, 10) !== day
          ? { events: {}, order: [], reportId: null, reportMode: null, reportAsOf: null }
          : {}),
      })),

    loadLatest: async (mode) => {
      const m = mode ?? get().mode;
      try {
        const r = await getLatestReport(m, m === "replay" ? get().asOf : undefined);
        if (get().running) return;
        if (m === "replay" && r.as_of.slice(0, 10) !== get().asOf) {
          // The picked replay date has no matching report — empty board,
          // never another date's data.
          set({ events: {}, order: [], reportId: null, reportMode: null, reportAsOf: null });
          return;
        }
        const { events, order } = fromReport(r);
        set({
          events,
          order,
          reportId: r.id,
          reportMode: r.mode,
          reportAsOf: r.as_of,
          tools: [],
          credits: null,
          ...(r.mode === "live" ? { urgentCount: countUrgent(events, order) } : {}),
        });
      } catch {
        if (!get().running) set({ events: {}, order: [], reportId: null, reportMode: null, reportAsOf: null });
      }
    },

    refreshBadge: async () => {
      try {
        const r = await getLatestReport("live");
        const { events, order } = fromReport(r);
        set({ urgentCount: countUrgent(events, order) });
      } catch {
        /* no live report yet */
      }
    },

    reattach: async () => {
      if (get().running || controller) return false;
      const ctrl = new AbortController();
      controller = ctrl; // claim before the await — a second caller must bail
      let stream: AsyncGenerator<AksiStreamEvent> | null;
      try {
        stream = await resumeAksiCheck(ctrl.signal);
      } catch {
        if (controller === ctrl) controller = null;
        return false; // probe failed (network/401) — the caller loads the report
      }
      if (!stream) {
        if (controller === ctrl) controller = null;
        return false; // 404 — no active run
      }
      beginRun(ctrl);
      void consume(stream, ctrl);
      return true;
    },

    run: () => {
      if (get().running || controller) return;
      const { mode, asOf } = get();
      const ctrl = new AbortController();
      beginRun(ctrl);
      void consume(
        streamAksiCheck({ as_of: mode === "replay" ? asOf : null }, ctrl.signal),
        ctrl,
      );
    },

    stop: () => {
      stopAksiCheck().catch(() => {});
      settle("skipped");
      set({ stopped: true });
      controller?.abort();
    },
  };
});

/** Abort a live stream and drop all state — called on logout/session-death
 * so holdings and reports never leak into the next session. */
export function resetAksiStore() {
  controller?.abort();
  controller = null;
  useAksiStore.setState(initialState);
}
