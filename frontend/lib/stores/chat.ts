"use client";

import { create } from "zustand";
import { toast } from "sonner";

import type { ToolActivity } from "@/components/agent-status";
import type { Message } from "@/components/chat-messages";
import type { ChartSpec } from "@/lib/charts";
import {
  getThread,
  resumeThreadStream,
  stopThread,
  streamChat,
  updateThread,
  type ChatMessage,
  type StreamEvent,
} from "@/lib/api";
import { loadSettings } from "@/lib/settings";
import { detailFor, verbFor } from "@/lib/tool-labels";
import { useThreadsStore } from "@/lib/stores/threads";

let msgSeq = 0;
const nextId = (prefix: string) => `${prefix}-${Date.now()}-${++msgSeq}`;

/** Flat history — server messages map straight onto the UI model. Tool
 * names come back as a settled run so the work line + steps graph render
 * exactly like they did live. */
function toMessages(messages: ChatMessage[]): Message[] {
  return messages.map((m, i) => ({
    id: `h-${i}`,
    role: m.role === "user" ? "user" : "assistant",
    content: m.content,
    scheduled: m.scheduled,
    reasoning: m.reasoning,
    charts: m.charts,
    run: m.tools?.length
      ? {
          tools: m.tools.map((t) => ({
            tool: t.name,
            label: verbFor(t.name),
            detail: detailFor(t.args),
            status: "done" as const,
          })),
          active: false,
        }
      : undefined,
  }));
}

/** Freeze a live run: settle any running tools and stamp the final duration. */
function settleRun(
  msg: Message,
  toolStatus: ToolActivity["status"],
  toolDetail?: string,
): NonNullable<Message["run"]> {
  return {
    tools: (msg.run?.tools ?? []).map((t) =>
      t.status === "running"
        ? { ...t, status: toolStatus, ...(toolDetail ? { detail: toolDetail } : {}) }
        : t,
    ),
    active: false,
    durationMs: msg.run?.runStartedAt
      ? Date.now() - msg.run.runStartedAt
      : undefined,
    runStartedAt: msg.run?.runStartedAt,
  };
}

/**
 * The run currently writing to the view. `activeRun` doubles as ownership:
 * once a run is detached its view writes are dropped, but its stream keeps
 * draining so list-side bookkeeping (pending flags, finish notification)
 * still flows — no second watcher connection needed.
 */
interface ActiveRun {
  controller: AbortController;
  threadId: string | null;
  /** The run started from a fresh chat (no thread yet) — drives applyCreated. */
  wasNew: boolean;
  detached: boolean;
  announced: boolean;
  /** The assistant message this run streams into — lets stop() settle it
   * even when the abort races the server's `stopped` event. */
  assistantId: string;
  /** The prompt that started the run — feeds the placeholder title for
   * brand-new threads. Empty on reattach (wasNew is always false). */
  prompt: string;
}
let activeRun: ActiveRun | null = null;
/** Runs that outlived their view — kept so logout can abort them all. */
const detachedRuns = new Set<ActiveRun>();

interface ChatStore {
  /** The mounted page's route param — null for the "/" new-chat page. */
  routeId: string | null;
  /** The thread owning the on-screen messages — null on a fresh chat and
   * while a thread load is still in flight. */
  threadId: string | null;
  messages: Message[];
  title: string | null;
  starred: boolean;
  running: boolean;
  /** Thread history fetch in flight for the mounted view. */
  loading: boolean;
  /** Called by each mounted ChatView; resolves false when the thread load
   * failed so the page can route back to "/". */
  mountView: (routeId: string | null) => Promise<boolean>;
  /** View unmounting — a live run keeps streaming in the background. */
  unmountView: (routeId: string | null) => void;
  /** The "/" page survives replaceState'd URLs — a real return home shows up
   * only as a pathname flip, which becomes a view reset here. */
  syncPathname: (pathname: string) => void;
  load: (threadId: string) => Promise<boolean>;
  /** "New Thread" while already home — drop the view (and any live run). */
  reset: () => void;
  send: (text: string) => void;
  retry: (messageId: string) => void;
  stop: () => void;
  toggleStar: () => void;
  applyTitle: (threadId: string, title: string) => void;
  markDeleted: (threadId: string) => void;
}

const initialState = {
  routeId: null as string | null,
  threadId: null as string | null,
  messages: [] as Message[],
  title: null as string | null,
  starred: false,
  running: false,
  loading: false,
};

const blankView = {
  threadId: null as string | null,
  messages: [] as Message[],
  title: null as string | null,
  starred: false,
};

export const useChatStore = create<ChatStore>()((set, get) => {
  /** Patch one assistant message in place (live turns + retries). */
  function patchMessage(id: string, fn: (msg: Message) => Partial<Message>) {
    set((s) => ({
      messages: s.messages.map((m) => (m.id === id ? { ...m, ...fn(m) } : m)),
    }));
  }

  /** Release the live run to the background: it keeps draining (pending flag,
   * finish notification) but can no longer write to the view. */
  function detachRun() {
    const run = activeRun;
    if (!run || !get().running) return;
    run.detached = true;
    detachedRuns.add(run);
    activeRun = null;
    set({ running: false });
  }

  /**
   * Pull the thread title once a run ends — the LLM name lands post-turn, so
   * a few spaced checks pick it up without any list being mounted. A change
   * goes through applyRenamed so the header and every list stay on one path.
   */
  function pollTitle(tid: string) {
    let attempts = 0;
    const tick = async () => {
      if (get().threadId !== tid) return; // user moved on
      attempts += 1;
      try {
        const { title: next } = await getThread(tid);
        if (next && next !== get().title) {
          get().applyTitle(tid, next);
          useThreadsStore.getState().applyRenamed(tid, next);
        }
      } catch {
        return; // thread deleted or transient error — stop polling
      }
      if (attempts < 4) window.setTimeout(tick, 2000);
    };
    void tick();
  }

  /**
   * Drain one run's event stream into the view. Shared by live turns
   * (POST /chat/stream) and reattach (GET /threads/{id}/stream) — the
   * replayed buffer emits the same event types, so a remount rebuilds
   * thinking, tool steps and elapsed time identically to watching live.
   */
  async function consumeRun(run: ActiveRun, events: AsyncGenerator<StreamEvent>) {
    const owns = () => activeRun === run;
    const patch = (fn: (msg: Message) => Partial<Message>) => {
      if (owns()) patchMessage(run.assistantId, fn);
    };
    // `announced` mirrors the last state reported — a terminal event clears
    // it, so the finally only re-announces when the loop ended silently.
    const announce = (tid: string, streaming: boolean) => {
      run.announced = streaming;
      useThreadsStore.getState().setStreaming(tid, streaming);
    };

    let endedCleanly = false;
    try {
      for await (const ev of events) {
        const data = (ev.data ?? {}) as Record<string, string>;
        switch (ev.type) {
          case "started": {
            // A malformed frame can carry no thread_id — stream what we can
            // but don't write undefined into thread-scoped state.
            const tid =
              typeof data.thread_id === "string" && data.thread_id
                ? data.thread_id
                : null;
            if (tid) run.threadId = tid;
            const raw = data.started_at;
            const startedAt =
              typeof raw === "number" || /^\d+$/.test(String(raw))
                ? Number(raw)
                : Date.parse(String(raw ?? ""));
            if (owns()) {
              if (tid) set({ threadId: tid });
              patch(() => ({
                run: {
                  tools: [],
                  active: true,
                  runStartedAt: Number.isNaN(startedAt) ? null : startedAt,
                },
              }));
            }
            if (tid && run.wasNew) {
              const newTitle = run.prompt.trim().slice(0, 60) || "New thread";
              if (owns()) set({ title: newTitle });
              useThreadsStore.getState().applyCreated(tid, newTitle);
            }
            if (tid) announce(tid, true);
            break;
          }
          case "reasoning":
            patch((m) => ({
              reasoning: (m.reasoning ?? "") + (ev.data as string),
            }));
            break;
          case "token":
            patch((m) => ({ content: m.content + (ev.data as string) }));
            break;
          case "tool":
            patch((m) => {
              const tools = [...(m.run?.tools ?? [])];
              if (data.status === "call") {
                const args = (data as { args?: Record<string, unknown> }).args;
                tools.push({
                  tool: data.name,
                  label: verbFor(data.name),
                  detail: detailFor(args),
                  status: "running",
                });
              } else {
                for (let i = tools.length - 1; i >= 0; i--) {
                  if (tools[i].status === "running" && tools[i].tool === data.name) {
                    tools[i] = { ...tools[i], status: "done" };
                    break;
                  }
                }
              }
              return { run: { ...m.run!, tools } };
            });
            break;
          case "chart":
            patch((m) => ({
              charts: [...(m.charts ?? []), ev.data as ChartSpec],
            }));
            break;
          case "done": {
            const tid =
              typeof data.thread_id === "string" && data.thread_id
                ? data.thread_id
                : run.threadId;
            if (tid) run.threadId = tid;
            if (owns()) {
              if (tid) {
                set({ threadId: tid });
                // A URL change only, no remount — this view keeps holding the
                // finished thread while the route prop stays null.
                window.history.replaceState(null, "", `/threads/${tid}`);
              }
              patch((m) => ({
                content: data.answer || m.content,
                run: settleRun(m, "done"),
              }));
            }
            if (tid) announce(tid, false);
            break;
          }
          case "stopped":
            patch((m) => ({
              content: data.answer || m.content,
              run: { ...settleRun(m, "skipped"), stopped: true },
            }));
            if (run.threadId) announce(run.threadId, false);
            break;
          case "error":
            patch((m) => ({
              run: { ...settleRun(m, "error", String(ev.data)), failed: true },
            }));
            if (run.threadId) announce(run.threadId, false);
            break;
        }
      }
      endedCleanly = true;
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        patch((m) => ({
          run: { ...(m.run ?? { tools: [] }), active: false, failed: true },
        }));
        toast.error("Generation failed");
      }
    } finally {
      detachedRuns.delete(run);
      if (owns()) {
        activeRun = null;
        set({ running: false });
        // The loop can end without a terminal event (client abort, network
        // drop) — never leave a stale streaming flag behind. Terminal events
        // already cleared `announced`, so this only fires on silent ends.
        const tid = run.threadId;
        if (run.announced && tid) announce(tid, false);
        if (tid) pollTitle(tid);
      } else if (run.detached && run.threadId) {
        // Nobody was watching — settle the row and flag the finish toast.
        if (run.announced) announce(run.threadId, false);
        if (endedCleanly) useThreadsStore.getState().finishRun(run.threadId);
      }
    }
  }

  async function runStream(text: string, assistantId: string) {
    // A detached consumer may still be draining this thread's previous run —
    // abort it before the new stream starts so its terminal announce(false)
    // can't land after our announce(true) and clear the pending flag. The
    // server-side supersede then finishes quiescing it.
    const tid = get().threadId;
    if (tid) {
      for (const r of detachedRuns) {
        if (r.threadId === tid) r.controller.abort();
      }
    }
    const run: ActiveRun = {
      controller: new AbortController(),
      threadId: null,
      wasNew: get().threadId === null,
      detached: false,
      announced: false,
      assistantId,
      prompt: text,
    };
    activeRun = run;
    await consumeRun(
      run,
      streamChat(
        text,
        get().threadId,
        run.controller.signal,
        loadSettings().language,
      ),
    );
  }

  /**
   * Reattach to a run still generating on the server — replaying the buffer
   * rebuilds reasoning, tool steps and the elapsed-time anchor the same way
   * watching live would. No-op when the thread has no live run.
   */
  async function reattachStream(threadId: string) {
    const controller = new AbortController();
    let events: AsyncGenerator<StreamEvent> | null = null;
    try {
      events = await resumeThreadStream(threadId, controller.signal);
    } catch {
      return; // transient — the view still has its loaded history
    }
    // No live run, the view moved on, or this view already owns a run.
    if (
      events === null ||
      get().routeId !== threadId ||
      get().threadId !== threadId ||
      activeRun !== null
    ) {
      controller.abort();
      return;
    }
    // Supersede the detached consumer that kept draining this run while the
    // view was away. Abort BEFORE replaying `started` so its finally's
    // announce(false) can't clobber our announce(true).
    for (const r of detachedRuns) {
      if (r.threadId === threadId) r.controller.abort();
    }
    // A mid-turn checkpoint can already serialize a partial assistant entry
    // (tool steps with no answer yet — content stays empty until the closing
    // node) — replace it so replayed events don't render the same work twice.
    // A content-bearing tail is a settled prior answer and must be kept.
    const history = [...get().messages];
    let prompt = "";
    const tail = history.at(-1);
    if (tail?.role === "assistant" && tail.content === "") {
      prompt = tail.prompt ?? "";
      history.pop();
    } else {
      prompt = history.findLast((m) => m.role === "user")?.content ?? "";
    }
    const assistantId = nextId("a");
    const run: ActiveRun = {
      controller,
      threadId,
      wasNew: false,
      detached: false,
      announced: false,
      assistantId,
      prompt,
    };
    activeRun = run;
    set({
      running: true,
      messages: [
        ...history,
        {
          id: assistantId,
          role: "assistant",
          content: "",
          prompt,
          run: { tools: [], active: true, runStartedAt: null },
        },
      ],
    });
    await consumeRun(run, events);
  }

  return {
    ...initialState,

    mountView: async (routeId) => {
      detachRun(); // a live run can only belong to the view being replaced
      set({ routeId });
      if (routeId === null) {
        // The new-chat page — any previous view's messages are done with.
        set({ ...blankView, loading: false });
        return true;
      }
      set({ ...blankView, loading: true });
      return get().load(routeId);
    },

    unmountView: (routeId) => {
      if (get().routeId !== routeId) return;
      detachRun();
    },

    syncPathname: (pathname) => {
      if (pathname !== "/" || get().routeId !== null) return;
      if (get().threadId === null) return;
      detachRun();
      set(blankView);
    },

    load: async (threadId) => {
      try {
        const t = await getThread(threadId);
        // The view moved on while the fetch was in flight — drop the result.
        if (get().routeId !== threadId) return true;
        const firstUserMsg = t.messages.find((m) => m.role === "user")?.content;
        set({
          messages: toMessages(t.messages),
          title: t.title ?? firstUserMsg?.trim().slice(0, 60) ?? "Untitled",
          starred: t.starred,
          threadId,
          loading: false,
        });
        // Opening the thread marks it read server-side — clear the sidebar
        // dot optimistically rather than waiting for the next list refresh.
        useThreadsStore.getState().patchThread(threadId, { unread: false });
        // A run outlived the last visit — rebuild its live bubble from the
        // replay buffer instead of showing a silent in-flight turn.
        if (t.has_active_run) void reattachStream(threadId);
        return true;
      } catch {
        if (get().routeId !== threadId) return true;
        set({ loading: false });
        return false;
      }
    },

    reset: () => {
      detachRun();
      set(blankView);
    },

    send: (text) => {
      const s = get();
      if (s.running) return;
      const assistantId = nextId("a");
      set({
        running: true,
        messages: [
          ...s.messages,
          { id: nextId("u"), role: "user", content: text },
          {
            id: assistantId,
            role: "assistant",
            content: "",
            prompt: text,
            run: { tools: [], active: true, runStartedAt: null },
          },
        ],
      });
      void runStream(text, assistantId);
    },

    retry: (messageId) => {
      const s = get();
      if (s.running) return;
      const msg = s.messages.find((m) => m.id === messageId);
      if (!msg?.prompt) return;
      set({ running: true });
      patchMessage(messageId, () => ({
        content: "",
        reasoning: "", // the new run re-derives its own
        charts: [],
        run: { tools: [], active: true, runStartedAt: null },
      }));
      void runStream(msg.prompt, messageId);
    },

    stop: () => {
      const tid = get().threadId;
      if (tid) stopThread(tid).catch(() => {});
      const run = activeRun;
      if (run) {
        // The abort can race the server's `stopped` event — settle now so
        // status/charts aren't stuck mid-flight if the event never lands.
        patchMessage(run.assistantId, (m) => ({
          run: { ...settleRun(m, "skipped"), stopped: true },
        }));
        run.controller.abort();
      }
    },

    toggleStar: () => {
      const tid = get().threadId;
      if (!tid) return;
      const next = !get().starred;
      set({ starred: next });
      useThreadsStore.getState().patchThread(tid, { starred: next });
      updateThread(tid, { starred: next }).catch(() => {
        set({ starred: !next });
        useThreadsStore.getState().patchThread(tid, { starred: !next });
        toast.error("Couldn't update the thread");
      });
    },

    applyTitle: (threadId, title) => {
      if (get().threadId === threadId) set({ title });
    },

    // The open thread was deleted: abort any live run, reset to a blank new
    // chat — the caller routes home if the page is still showing it.
    markDeleted: (threadId) => {
      if (get().threadId !== threadId) return;
      activeRun?.controller.abort();
      set({ ...blankView, running: false, loading: false });
    },
  };
});

useThreadsStore.subscribe((state, prev) => {
  const s = useChatStore.getState();

  // List-side renames (manual rename, LLM naming landing via refresh) keep
  // the open header on the same path — every surface reads the one store.
  const viewed = s.threadId;
  if (viewed) {
    const next = state.threads.find((t) => t.id === viewed)?.title;
    const before = prev.threads.find((t) => t.id === viewed)?.title;
    if (next && next !== before) useChatStore.setState({ title: next });
  }

  // A backgrounded run finished — if its thread page is open, pull the final
  // answer so the view doesn't stay frozen at the pre-detach cutoff.
  const finished = state.finishedRun;
  if (
    finished &&
    finished !== prev.finishedRun &&
    s.routeId === finished.threadId &&
    !s.running &&
    !s.loading
  ) {
    void s.load(finished.threadId);
  }
});

/** Abort every run — live and detached — and drop all state (logout). */
export function resetChatStore() {
  activeRun?.controller.abort();
  activeRun = null;
  for (const run of detachedRuns) run.controller.abort();
  detachedRuns.clear();
  useChatStore.setState(initialState);
}
