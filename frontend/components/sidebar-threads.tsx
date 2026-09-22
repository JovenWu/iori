"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuItem,
  SidebarMenuButton,
} from "@/components/ui/sidebar";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ChevronRightIcon,
  CircleCheckIcon,
  HistoryIcon,
  Loader2Icon,
  MessageCircleIcon,
  MoreHorizontalIcon,
  SquarePlus,
} from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth";
import { useSettings } from "@/lib/settings";
import { fetchThreadStream, listThreads, type Thread } from "@/lib/api";
import { ThreadActionsMenu } from "@/components/thread-actions-menu";
import { ThreadActionDialogs } from "@/components/thread-action-dialogs";
import { useThreadActions } from "@/hooks/use-thread-actions";
import {
  THREAD_CREATED_EVENT,
  THREAD_STREAMING_STATE_EVENT,
  THREAD_STREAM_DETACHED_EVENT,
  THREAD_RENAMED_EVENT,
  THREAD_DELETED_EVENT,
  THREADS_REFRESH_EVENT,
  NEW_THREAD_EVENT,
  emitThreadEvent,
  type ThreadCreatedEventDetail,
  type ThreadStreamingStateEventDetail,
  type ThreadStreamDetachedEventDetail,
  type ThreadRenamedEventDetail,
  type ThreadDeletedEventDetail,
} from "@/lib/thread-events";

interface SidebarThread extends Thread {
  isPending?: boolean;
}

function getTimestamp(value: string) {
  const time = new Date(value).getTime();
  return Number.isNaN(time) ? 0 : time;
}

function sortThreadsByUpdatedAt(threads: SidebarThread[]) {
  return [...threads].sort(
    (left, right) =>
      getTimestamp(right.updated_at) - getTimestamp(left.updated_at),
  );
}

function threadTitle(thread: Thread): string {
  return thread.title ?? thread.first_answer_preview ?? "Untitled";
}

export function SidebarThreads() {
  const RECENT_LIMIT = 20;
  const pathname = usePathname();
  const router = useRouter();
  const { token } = useAuth();
  const { settings } = useSettings();
  const [threads, setThreads] = useState<SidebarThread[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  // Background watchers (one per backgrounded, still-generating thread) that
  // keep the sidebar loader accurate after navigating away mid-stream.
  const watchersRef = useRef<Map<string, AbortController>>(new Map());
  // Latest threads, read inside watcher callbacks without stale closures.
  const threadsRef = useRef(threads);
  useEffect(() => {
    threadsRef.current = threads;
  }, [threads]);
  // Same trick for the notification preference — watcher callbacks read the
  // ref so toggling the setting doesn't churn their effect dependencies.
  const notifyOnDoneRef = useRef(settings.notifyOnDone);
  useEffect(() => {
    notifyOnDoneRef.current = settings.notifyOnDone;
  }, [settings.notifyOnDone]);

  const fetchThreads = useCallback(async () => {
    if (!token) return;
    try {
      const data = await listThreads();
      // Titles can change under us (LLM naming, another tab's rename) — push
      // each change onto the bus so an open chat header never goes stale.
      const prevById = new Map(threadsRef.current.map((t) => [t.id, t]));
      for (const t of data.threads) {
        const before = prevById.get(t.id);
        if (before && t.title && before.title !== t.title) {
          emitThreadEvent<ThreadRenamedEventDetail>(THREAD_RENAMED_EVENT, {
            threadId: t.id,
            title: t.title,
          });
        }
      }
      setThreads((prev) => {
        const prevById = new Map(prev.map((thread) => [thread.id, thread]));
        const fetchedIds = new Set(data.threads.map((thread) => thread.id));

        // Keep rows that outrun the server list only while still pending —
        // anything else missing from the fetch was deleted elsewhere.
        const optimisticThreads = prev.filter(
          (thread) => !fetchedIds.has(thread.id) && thread.isPending,
        );

        const fetchedThreads: SidebarThread[] = data.threads.map((thread) => {
          const prev = prevById.get(thread.id);
          return {
            ...thread,
            // Server title can lag the optimistic one — keep ours until the
            // backend has a real one, so the row never flashes "Untitled".
            title: thread.title ?? prev?.title ?? null,
            isPending: prev?.isPending ?? false,
          };
        });

        return sortThreadsByUpdatedAt([...optimisticThreads, ...fetchedThreads]);
      });
    } catch (err) {
      console.error("Failed to fetch threads:", err);
    } finally {
      setIsLoading(false);
    }
  }, [token]);

  // Refetch now, then twice more — the LLM title is written by _post_turn
  // just after the run closes, so delayed fetches land it without a refresh.
  const refetchSoon = useCallback(() => {
    void fetchThreads();
    for (const ms of [2500, 6000]) {
      window.setTimeout(() => void fetchThreads(), ms);
    }
  }, [fetchThreads]);

  const clearThreadPending = useCallback((id: string) => {
    setThreads((prev) =>
      prev.map((thread) =>
        thread.id === id ? { ...thread, isPending: false } : thread,
      ),
    );
  }, []);

  // Verify whether a thread is still generating server-side and, if so, hold a
  // background SSE connection open until the run ends — then clear its loader.
  const verifyAndWatch = useCallback(
    async (id: string) => {
      if (!token) return;
      const watchers = watchersRef.current;
      if (watchers.has(id)) return; // already watching

      const controller = new AbortController();
      watchers.set(id, controller);
      let finished = false;
      try {
        const res = await fetchThreadStream(id, controller.signal);
        if (res.status === 404) {
          // No run for this thread — already finished or never started.
          finished = true;
        } else if (res.ok && res.body) {
          // Still generating: show the loader (matters for the post-refresh
          // probe, where isPending was lost) and drain until the server
          // closes the stream.
          setThreads((prev) =>
            prev.map((t) => (t.id === id ? { ...t, isPending: true } : t)),
          );
          const reader = res.body.getReader();
          while (true) {
            const { done } = await reader.read();
            if (done) break;
          }
          finished = true;
        }
      } catch {
        // Aborted (a live page took over) or a network error.
      } finally {
        watchers.delete(id);
        // Only clear if we weren't aborted by a page taking ownership.
        if (!controller.signal.aborted) {
          clearThreadPending(id);
          refetchSoon();

          // The detached run finished → notify, unless the user is now on
          // that thread (e.g. navigated back).
          if (
            finished &&
            notifyOnDoneRef.current &&
            typeof window !== "undefined" &&
            window.location.pathname !== `/threads/${id}`
          ) {
            const title = threadsRef.current.find(
              (thread) => thread.id === id,
            )?.title;
            toast.custom((t) => (
              <button
                type="button"
                onClick={() => {
                  toast.dismiss(t);
                  router.push(`/threads/${id}`);
                }}
                className="flex w-full cursor-pointer items-start gap-3 rounded-lg border border-border bg-popover px-4 py-3 text-left shadow-lg transition-colors hover:bg-muted"
              >
                <CircleCheckIcon className="mt-0.5 size-5 shrink-0 text-primary" />
                <div className="min-w-0">
                  <p className="text-sm font-medium text-popover-foreground">
                    Response ready
                  </p>
                  <p className="truncate text-xs text-muted-foreground">
                    {title
                      ? `"${title}" finished generating`
                      : "Your chat finished generating"}
                  </p>
                </div>
              </button>
            ));
          }
        }
      }
    },
    [token, clearThreadPending, refetchSoon, router],
  );

  useEffect(() => {
    const t = window.setTimeout(() => void fetchThreads(), 0);
    return () => window.clearTimeout(t);
  }, [fetchThreads]);

  // On mount, resume watching threads whose first turn may still be in flight
  // (no preview yet). A refresh mid-run loses isPending and the DETACHED
  // event — probing re-attaches so the LLM title still lands without a
  // manual refresh. Dead threads 404 quickly; each is probed once.
  const probedRef = useRef(false);
  useEffect(() => {
    if (probedRef.current || isLoading) return;
    probedRef.current = true;
    const timer = window.setTimeout(() => {
      for (const thread of threads) {
        if (!thread.first_answer_preview) void verifyAndWatch(thread.id);
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [isLoading, threads, verifyAndWatch]);

  useEffect(() => {
    const handleThreadCreated = (event: Event) => {
      const detail = (event as CustomEvent<ThreadCreatedEventDetail>).detail;
      if (!detail?.threadId) return;

      const now = new Date().toISOString();
      const fallbackTitle = detail.title?.trim() || "New thread";

      setThreads((prev) => {
        const existingThread = prev.find(
          (thread) => thread.id === detail.threadId,
        );

        if (existingThread) {
          const nextThreads = prev.map((thread) =>
            thread.id === detail.threadId
              ? {
                  ...thread,
                  title: thread.title || fallbackTitle,
                  updated_at: now,
                  isPending: true,
                }
              : thread,
          );

          return sortThreadsByUpdatedAt(nextThreads);
        }

        return sortThreadsByUpdatedAt([
          {
            id: detail.threadId,
            title: fallbackTitle,
            starred: false,
            first_answer_preview: null,
            created_at: now,
            updated_at: now,
            isPending: true,
          },
          ...prev,
        ]);
      });
    };

    const handleThreadStreamingState = (event: Event) => {
      const detail = (event as CustomEvent<ThreadStreamingStateEventDetail>).detail;
      if (!detail?.threadId) return;

      // A page reported its stream ended normally — it observed done/stopped/
      // error while the user was watching → clear the loader, no notification.
      if (!detail.isStreaming) {
        watchersRef.current.get(detail.threadId)?.abort();
        clearThreadPending(detail.threadId);
        // Settles a just-updated thread into its correct position (server
        // updated_at) and picks up the post-turn LLM title.
        refetchSoon();
        return;
      }

      // A live page is actively streaming this thread → show the loader and
      // stop any background watcher (the page owns it now).
      watchersRef.current.get(detail.threadId)?.abort();

      // The existence check lives inside the updater: created + streaming
      // events fire in the same tick, so threadsRef is still stale here and
      // checking it would double-insert the row (duplicate React key).
      let inserted = false;
      const now = new Date().toISOString();
      setThreads((prev) => {
        if (prev.some((t) => t.id === detail.threadId)) {
          // Only flag the pending loader — in place. Do NOT bump updated_at
          // or re-sort: opening or resuming a thread must not reorder.
          return prev.map((thread) =>
            thread.id === detail.threadId
              ? { ...thread, isPending: true }
              : thread,
          );
        }
        inserted = true;
        // Optimistic placeholder, then reconcile against the server for the
        // real title and ordering.
        return sortThreadsByUpdatedAt([
          {
            id: detail.threadId,
            title: "Thread",
            starred: false,
            first_answer_preview: null,
            created_at: now,
            updated_at: now,
            isPending: true,
          },
          ...prev,
        ]);
      });
      if (inserted) void fetchThreads();
    };

    // LLM-named titles (streamed to the open page) and manual renames land
    // here — update the row in place so the list never needs a refresh.
    const handleThreadRenamed = (event: Event) => {
      const detail = (event as CustomEvent<ThreadRenamedEventDetail>).detail;
      if (!detail?.threadId) return;
      setThreads((prev) =>
        prev.map((thread) =>
          thread.id === detail.threadId
            ? { ...thread, title: detail.title }
            : thread,
        ),
      );
    };

    // A live page navigated away while its turn was still generating → take
    // over watching it so the loader persists and we can notify on finish.
    const handleThreadDetached = (event: Event) => {
      const detail = (event as CustomEvent<ThreadStreamDetachedEventDetail>)
        .detail;
      if (!detail?.threadId) return;
      void verifyAndWatch(detail.threadId);
    };

    // Deleted on another surface (header menu, history) — drop the row.
    const handleThreadDeleted = (event: Event) => {
      const detail = (event as CustomEvent<ThreadDeletedEventDetail>).detail;
      if (!detail?.threadId) return;
      setThreads((prev) =>
        prev.filter((thread) => thread.id !== detail.threadId),
      );
    };

    // An optimistic delete was undone (or its commit failed) — re-pull so the
    // row comes back exactly as the server has it.
    const handleThreadsRefresh = () => void fetchThreads();

    window.addEventListener(
      THREAD_CREATED_EVENT,
      handleThreadCreated as EventListener,
    );
    window.addEventListener(
      THREAD_STREAMING_STATE_EVENT,
      handleThreadStreamingState as EventListener,
    );
    window.addEventListener(
      THREAD_STREAM_DETACHED_EVENT,
      handleThreadDetached as EventListener,
    );
    window.addEventListener(
      THREAD_RENAMED_EVENT,
      handleThreadRenamed as EventListener,
    );
    window.addEventListener(
      THREAD_DELETED_EVENT,
      handleThreadDeleted as EventListener,
    );
    window.addEventListener(
      THREADS_REFRESH_EVENT,
      handleThreadsRefresh as EventListener,
    );

    return () => {
      window.removeEventListener(
        THREAD_CREATED_EVENT,
        handleThreadCreated as EventListener,
      );
      window.removeEventListener(
        THREAD_STREAMING_STATE_EVENT,
        handleThreadStreamingState as EventListener,
      );
      window.removeEventListener(
        THREAD_STREAM_DETACHED_EVENT,
        handleThreadDetached as EventListener,
      );
      window.removeEventListener(
        THREAD_RENAMED_EVENT,
        handleThreadRenamed as EventListener,
      );
      window.removeEventListener(
        THREAD_DELETED_EVENT,
        handleThreadDeleted as EventListener,
      );
      window.removeEventListener(
        THREADS_REFRESH_EVENT,
        handleThreadsRefresh as EventListener,
      );
    };
  }, [fetchThreads, verifyAndWatch, clearThreadPending, refetchSoon]);

  // Abort all background watchers when the sidebar unmounts (e.g. logout).
  useEffect(() => {
    const watchers = watchersRef.current;
    return () => {
      for (const controller of watchers.values()) controller.abort();
      watchers.clear();
    };
  }, []);

  const threadActions = useThreadActions({
    onRenamed: (threadId, nextTitle) => {
      setThreads((prev) =>
        prev.map((thread) =>
          thread.id === threadId ? { ...thread, title: nextTitle } : thread,
        ),
      );
    },
    onDeleted: (threadId) => {
      setThreads((prev) =>
        prev.filter((thread) => thread.id !== threadId),
      );

      if (pathname === `/threads/${threadId}`) {
        router.push("/");
      }
    },
  });

  const recentThreads = threads.slice(0, RECENT_LIMIT);
  const shouldShowViewAll = threads.length > RECENT_LIMIT;

  return (
    <SidebarGroup className="h-full min-h-0">
      <SidebarGroupContent className="flex h-full min-h-0 flex-col gap-4">
        {/* New Thread + History */}
        <SidebarMenu className="gap-1.5">
          <SidebarMenuItem>
            <SidebarMenuButton
              asChild
              tooltip="New Thread"
              isActive={pathname === "/"}
              className="h-10 px-4 font-medium"
            >
              <Link
                href="/"
                onClick={() => {
                  // Already on "/" — the router won't navigate, so tell the
                  // open ChatView to reset itself.
                  if (pathname === "/") {
                    emitThreadEvent(NEW_THREAD_EVENT, {});
                  }
                }}
              >
                <SquarePlus className="text-primary" />
                <span className="group-data-[collapsible=icon]:hidden">
                  New Thread
                </span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton
              asChild
              tooltip="History"
              isActive={pathname === "/history"}
              className="h-10 px-4"
            >
              <Link href="/history">
                <HistoryIcon />
                <span className="group-data-[collapsible=icon]:hidden">
                  History
                </span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>

        <div className="flex min-h-0 flex-1 flex-col gap-2 group-data-[collapsible=icon]:hidden">
          <div className="px-2 pt-1">
            <span className="text-xs font-medium text-muted-foreground/70">
              Recent
            </span>
          </div>

          {isLoading ? (
            <div className="space-y-2 overflow-y-auto px-2 py-2 [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-8 w-full rounded-full" />
              ))}
            </div>
          ) : threads.length === 0 ? (
            <div className="flex flex-1 flex-col items-center gap-2 overflow-y-auto px-4 py-8 text-center [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden">
              <MessageCircleIcon className="size-8 text-muted-foreground/50" />
              <p className="text-sm text-muted-foreground">
                No conversations yet.
              </p>
              <p className="text-xs text-muted-foreground/70">
                Start a new thread to begin!
              </p>
            </div>
          ) : (
            <SidebarMenu className="min-h-0 flex-1 gap-0.5 overflow-y-auto [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden">
              {recentThreads.map((thread) => {
                const isActive = pathname === `/threads/${thread.id}`;
                const title = threadTitle(thread);
                return (
                  <SidebarMenuItem
                    key={thread.id}
                    className="[&:has([data-sidebar=menu-action]:hover)_[data-sidebar=menu-button]]:bg-transparent [&:has([data-sidebar=menu-action]:hover)_[data-sidebar=menu-button]]:text-sidebar-foreground"
                  >
                    <SidebarMenuButton
                      asChild
                      isActive={isActive}
                      tooltip={title}
                      // Let the title use the full width; only reserve room for
                      // the actions button (or the pending spinner) when it's
                      // actually visible, so titles aren't truncated early.
                      className={`h-7 py-1.5 group-hover/menu-item:pr-8 group-focus-within/menu-item:pr-8${
                        thread.isPending ? " pr-8" : ""
                      }`}
                    >
                      <Link
                        href={`/threads/${thread.id}`}
                        className="flex min-w-0 items-center"
                      >
                        <span className="min-w-0 flex-1 truncate">
                          {title}
                        </span>
                      </Link>
                    </SidebarMenuButton>

                    {thread.isPending ? (
                      <SidebarMenuAction
                        className="opacity-100 focus-visible:ring-0"
                        disabled
                        aria-hidden="true"
                      >
                        <Loader2Icon className="size-4 animate-spin text-muted-foreground" />
                        <span className="sr-only">Thread loading</span>
                      </SidebarMenuAction>
                    ) : (
                      <ThreadActionsMenu
                        showIcons
                        onRename={() =>
                          threadActions.openRename({
                            threadId: thread.id,
                            title,
                          })
                        }
                        onDelete={() =>
                          threadActions.openDelete({
                            threadId: thread.id,
                            title,
                          })
                        }
                        trigger={
                          <SidebarMenuAction
                            className="opacity-0 focus-visible:ring-0 group-hover/menu-item:opacity-100 data-[state=open]:opacity-100"
                            onClick={(e) => e.preventDefault()}
                          >
                            <MoreHorizontalIcon className="size-4" />
                            <span className="sr-only">Thread actions</span>
                          </SidebarMenuAction>
                        }
                      />
                    )}
                  </SidebarMenuItem>
                );
              })}
              {shouldShowViewAll ? (
                <SidebarMenuItem>
                  <SidebarMenuButton
                    asChild
                    className="h-7 text-xs font-normal text-muted-foreground hover:bg-transparent hover:text-muted-foreground active:bg-transparent active:text-foreground"
                  >
                    <Link
                      href="/history"
                      className="inline-flex items-center gap-1"
                    >
                      <span>View all</span>
                      <ChevronRightIcon className="size-3.5" />
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ) : null}
            </SidebarMenu>
          )}
        </div>
      </SidebarGroupContent>

      <ThreadActionDialogs
        renameTargetTitle={threadActions.renameTarget?.title}
        deleteTargetTitle={threadActions.deleteTarget?.title}
        renameValue={threadActions.renameValue}
        isRenaming={threadActions.isRenaming}
        isDeleting={threadActions.isDeleting}
        onRenameValueChange={threadActions.setRenameValue}
        onRenameOpenChange={(open) => {
          if (!open) threadActions.closeRename();
        }}
        onDeleteOpenChange={(open) => {
          if (!open) threadActions.closeDelete();
        }}
        onSubmitRename={threadActions.submitRename}
        onSubmitDelete={threadActions.submitDelete}
      />
    </SidebarGroup>
  );
}
