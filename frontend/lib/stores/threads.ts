"use client";

import { create } from "zustand";
import {
  fetchThreadStream,
  getAccessToken,
  listThreads,
  type Thread,
} from "@/lib/api";

export interface ListedThread extends Thread {
  /** A turn is still generating — the row shows a spinner instead of actions. */
  isPending?: boolean;
}

/** A backgrounded run finished — the layout notifier turns this into a toast. */
export interface FinishedRun {
  threadId: string;
  title: string | null;
  at: number;
}

interface ThreadsStore {
  threads: ListedThread[];
  /** False until the first listThreads fetch resolves. */
  loaded: boolean;
  /** Keyset cursor for the next page — null once every thread is loaded. */
  nextCursor: string | null;
  /** Server-side thread count — null until the first page lands. */
  total: number | null;
  loadingMore: boolean;
  finishedRun: FinishedRun | null;
  /** First-load fetch, then probe preview-less threads for live runs. */
  init: () => void;
  /** Refetch the first page; keeps already-loaded deeper pages in place. */
  refresh: () => Promise<void>;
  /** Fetch the next page and append it — no-op when done or in flight. */
  loadMore: () => Promise<void>;
  /** Refetch now, then twice more — the LLM title is written just after the
   * run closes, so delayed fetches land it without a manual refresh. */
  refetchSoon: () => void;
  applyCreated: (threadId: string, title: string) => void;
  applyRenamed: (threadId: string, title: string) => void;
  applyDeleted: (threadId: string) => void;
  patchThread: (threadId: string, patch: Partial<ListedThread>) => void;
  /** A live page reports stream state — it owns the run, so any background
   * watcher steps down. False clears the loader and settles the row. */
  setStreaming: (threadId: string, streaming: boolean) => void;
  /** Verify the thread still generates server-side; if so, hold a background
   * SSE connection open until the run ends, then flag it for the notifier. */
  watchRun: (threadId: string) => void;
  /** A backgrounded run ended cleanly — flag it for the notifier and for the
   * open thread page to reload its messages. */
  finishRun: (threadId: string) => void;
}

export function getTimestamp(value: string) {
  const time = new Date(value).getTime();
  return Number.isNaN(time) ? 0 : time;
}

function sortThreadsByUpdatedAt(threads: ListedThread[]) {
  return [...threads].sort(
    (a, b) => getTimestamp(b.updated_at) - getTimestamp(a.updated_at),
  );
}

/** Watchers live outside the store: AbortControllers aren't renderable state,
 * and the map must survive component unmounts (mobile sheet, route changes). */
const watchers = new Map<string, AbortController>();
const refetchTimers = new Set<number>();
let probed = false;

const PAGE_SIZE = 20;

const initialState = {
  threads: [] as ListedThread[],
  loaded: false,
  nextCursor: null as string | null,
  total: null as number | null,
  loadingMore: false,
  finishedRun: null as FinishedRun | null,
};

export const useThreadsStore = create<ThreadsStore>()((set, get) => ({
  ...initialState,

  init: () => {
    void get()
      .refresh()
      .then(() => {
        // Resume watching threads whose first turn may still be in flight —
        // a refresh mid-run loses the live page and its pending flags. Dead
        // threads 404 quickly; each is probed once.
        if (probed) return;
        probed = true;
        for (const thread of get().threads) {
          if (!thread.first_answer_preview) get().watchRun(thread.id);
        }
      });
  },

  refresh: async () => {
    if (!getAccessToken()) return;
    try {
      const data = await listThreads({ limit: PAGE_SIZE });
      set((s) => {
        const prevById = new Map(s.threads.map((t) => [t.id, t]));
        // Page one carries every starred thread alongside the recency page —
        // dedup the overlap so a recent favorite isn't listed twice.
        const pageRows = [...data.starred, ...data.threads];
        const fetchedIds = new Set(pageRows.map((t) => t.id));
        const hasMore = data.next_cursor !== null;
        const cutoff = getTimestamp(data.threads.at(-1)?.updated_at ?? "");
        // Rows missing from page one survive only if still pending, or if they
        // sit below the page cutoff — i.e. they came from deeper loadMore
        // pages. Anything else missing was deleted elsewhere.
        const keepers = s.threads.filter(
          (t) =>
            !fetchedIds.has(t.id) &&
            (t.isPending || (hasMore && getTimestamp(t.updated_at) < cutoff)),
        );
        const fetched: ListedThread[] = [
          ...new Map(pageRows.map((t) => [t.id, t])).values(),
        ].map((t) => ({
          ...t,
          // The server title can lag the optimistic one — keep ours until the
          // backend has a real one so the row never flashes "Untitled".
          title: t.title ?? prevById.get(t.id)?.title ?? null,
          isPending: prevById.get(t.id)?.isPending ?? false,
        }));
        return {
          threads: sortThreadsByUpdatedAt([...keepers, ...fetched]),
          loaded: true,
          nextCursor: data.next_cursor,
          total: data.total,
        };
      });
    } catch (err) {
      console.error("Failed to fetch threads:", err);
      set({ loaded: true });
    }
  },

  loadMore: async () => {
    const { nextCursor, loadingMore } = get();
    if (nextCursor === null || loadingMore || !getAccessToken()) return;
    set({ loadingMore: true });
    try {
      const data = await listThreads({ limit: PAGE_SIZE, cursor: nextCursor });
      set((s) => {
        const byId = new Map(s.threads.map((t) => [t.id, t]));
        for (const t of data.threads) {
          // Re-fetched rows may overlap page one after reordering — upsert.
          byId.set(t.id, {
            ...t,
            title: t.title ?? byId.get(t.id)?.title ?? null,
            isPending: byId.get(t.id)?.isPending ?? false,
          });
        }
        return {
          threads: sortThreadsByUpdatedAt([...byId.values()]),
          nextCursor: data.next_cursor,
          total: data.total,
          loadingMore: false,
        };
      });
    } catch (err) {
      console.error("Failed to load more threads:", err);
      set({ loadingMore: false });
    }
  },

  refetchSoon: () => {
    void get().refresh();
    for (const ms of [2500, 6000]) {
      const timer = window.setTimeout(() => {
        refetchTimers.delete(timer);
        void get().refresh();
      }, ms);
      refetchTimers.add(timer);
    }
  },

  applyCreated: (threadId, title) => {
    const now = new Date().toISOString();
    const fallbackTitle = title.trim() || "New thread";
    set((s) => ({
      // A brand-new row bumps the server total optimistically; updating an
      // existing pending row doesn't.
      total:
        s.total !== null && !s.threads.some((t) => t.id === threadId)
          ? s.total + 1
          : s.total,
      threads: sortThreadsByUpdatedAt(
        s.threads.some((t) => t.id === threadId)
          ? s.threads.map((t) =>
              t.id === threadId
                ? {
                    ...t,
                    title: t.title || fallbackTitle,
                    updated_at: now,
                    isPending: true,
                  }
                : t,
            )
          : [
              {
                id: threadId,
                title: fallbackTitle,
                starred: false,
                first_answer_preview: null,
                created_at: now,
                updated_at: now,
                isPending: true,
              },
              ...s.threads,
            ],
      ),
    }));
  },

  applyRenamed: (threadId, title) => {
    get().patchThread(threadId, { title });
  },

  applyDeleted: (threadId) => {
    watchers.get(threadId)?.abort();
    set((s) => ({
      threads: s.threads.filter((t) => t.id !== threadId),
      total:
        s.total !== null && s.threads.some((t) => t.id === threadId)
          ? s.total - 1
          : s.total,
    }));
  },

  patchThread: (threadId, patch) => {
    set((s) => ({
      threads: s.threads.map((t) =>
        t.id === threadId ? { ...t, ...patch } : t,
      ),
    }));
  },

  setStreaming: (threadId, streaming) => {
    watchers.get(threadId)?.abort();
    if (!streaming) {
      get().patchThread(threadId, { isPending: false });
      get().refetchSoon();
      return;
    }
    if (get().threads.some((t) => t.id === threadId)) {
      // Only flag the pending loader — in place. Do NOT bump updated_at or
      // re-sort: opening or resuming a thread must not reorder.
      get().patchThread(threadId, { isPending: true });
      return;
    }
    const now = new Date().toISOString();
    set((s) => ({
      threads: sortThreadsByUpdatedAt([
        {
          id: threadId,
          title: "Thread",
          starred: false,
          first_answer_preview: null,
          created_at: now,
          updated_at: now,
          isPending: true,
        },
        ...s.threads,
      ]),
    }));
    // Optimistic placeholder — reconcile against the server for the real
    // title and ordering.
    void get().refresh();
  },

  watchRun: (threadId) => {
    if (watchers.has(threadId) || !getAccessToken()) return;
    const controller = new AbortController();
    watchers.set(threadId, controller);
    let observed = false;
    void (async () => {
      try {
        const res = await fetchThreadStream(threadId, controller.signal);
        if (res.ok && res.body) {
          // Still generating: show the loader (matters for the post-refresh
          // probe, where isPending was lost) and drain until the server
          // closes the stream.
          observed = true;
          get().patchThread(threadId, { isPending: true });
          const reader = res.body.getReader();
          while (!(await reader.read()).done) {
            // Drain — the run's progress isn't needed, only its end.
          }
        }
      } catch {
        // Aborted (a live page took over) or a network error.
      } finally {
        watchers.delete(threadId);
        // Only settle if we weren't aborted by a page taking ownership.
        if (!controller.signal.aborted) {
          get().patchThread(threadId, { isPending: false });
          get().refetchSoon();
          if (observed) get().finishRun(threadId);
        }
      }
    })();
  },

  finishRun: (threadId) => {
    // A finish landing after logout must not toast into the next session.
    if (!getAccessToken()) return;
    const title = get().threads.find((t) => t.id === threadId)?.title ?? null;
    set({ finishedRun: { threadId, title, at: Date.now() } });
  },
}));

/** Abort every watcher and drop all state — called on logout so a second
 * session never sees the previous user's threads. */
export function resetThreadsStore() {
  for (const controller of watchers.values()) controller.abort();
  watchers.clear();
  for (const timer of refetchTimers) window.clearTimeout(timer);
  refetchTimers.clear();
  probed = false;
  useThreadsStore.setState(initialState);
}
