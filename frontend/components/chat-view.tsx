"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { toast } from "sonner";

import { ChatHeader } from "@/components/chat-header";
import { ChatInput } from "@/components/chat-input";
import {
  ChatMessages,
  ChatMessagesSkeleton,
  type Message,
} from "@/components/chat-messages";
import { SparkMark } from "@/components/spark-mark";
import { getThread, stopThread, streamChat, updateThread } from "@/lib/api";
import { verbFor } from "@/lib/tool-labels";
import type { ToolActivity } from "@/components/agent-status";
import {
  THREAD_CREATED_EVENT,
  THREAD_STREAMING_STATE_EVENT,
  THREAD_STREAM_DETACHED_EVENT,
  THREAD_RENAMED_EVENT,
  type ThreadCreatedEventDetail,
  type ThreadStreamingStateEventDetail,
  type ThreadStreamDetachedEventDetail,
  type ThreadRenamedEventDetail,
  NEW_THREAD_EVENT,
  emitThreadEvent,
} from "@/lib/thread-events";

let msgSeq = 0;
const nextId = (prefix: string) => `${prefix}-${Date.now()}-${++msgSeq}`;

/** Flat history — server messages map straight onto the UI model. */
function toMessages(
  messages: { role: string; content: string }[],
): Message[] {
  return messages.map((m, i) => ({
    id: `h-${i}`,
    role: m.role === "user" ? "user" : "assistant",
    content: m.content,
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

export function ChatView({ threadId }: { threadId: string | null }) {
  const router = useRouter();
  const pathname = usePathname();
  const [messages, setMessages] = useState<Message[]>([]);
  const [running, setRunning] = useState(false);
  const [loadedThread, setLoadedThread] = useState<string | null>(null);
  const [title, setTitle] = useState<string | null>(null);
  const [starred, setStarred] = useState(false);
  const threadRef = useRef<string | null>(threadId);
  const runningRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  // True once the live run was handed to the sidebar's watcher — the aborted
  // stream's `finally` must not emit isStreaming=false and kill the handoff.
  const detachedRef = useRef(false);
  // Mirror of `title` for async callbacks — the title poll compares the
  // server's title against what's actually on screen after its await.
  const titleRef = useRef(title);
  useEffect(() => {
    titleRef.current = title;
  }, [title]);

  const [prevThread, setPrevThread] = useState(threadId);
  if (prevThread !== threadId) {
    setPrevThread(threadId);
    setMessages([]);
    setLoadedThread(null);
    setTitle(null);
    setStarred(false);
  }

  // `done` swaps the URL to /threads/{id} via history.replaceState — a URL
  // change only, no remount — so this instance keeps holding the finished
  // thread while the route prop stays null. Coming back to "/" (New Thread)
  // is only observable through pathname.
  const [prevPathname, setPrevPathname] = useState(pathname);
  if (pathname !== prevPathname) {
    setPrevPathname(pathname);
    if (pathname === "/" && loadedThread) {
      setMessages([]);
      setLoadedThread(null);
      setTitle(null);
      setStarred(false);
    }
  }
  useEffect(() => {
    if (pathname === "/") threadRef.current = null;
  }, [pathname]);

  useEffect(() => {
    threadRef.current = threadId;
    if (!threadId) return;
    getThread(threadId)
      .then((t) => {
        setMessages(toMessages(t.messages));
        const firstUserMsg = t.messages.find((m) => m.role === "user")?.content;
        setTitle(
          t.title ?? firstUserMsg?.trim().slice(0, 60) ?? "Untitled",
        );
        setStarred(t.starred);
        setLoadedThread(threadId);
      })
      .catch(() => {
        toast.error("Couldn't load that thread");
        router.replace("/");
      });
  }, [threadId, router]);

  /**
   * Pull the thread title directly once a run ends. The sidebar's refetch
   * chain only exists while it's mounted — on mobile the sheet unmounts when
   * closed, so nothing would push the post-turn LLM title to this header.
   * Re-emitting any change on the bus keeps the header and mounted lists on
   * the same path, and later ticks self-heal a fetch that raced a rename.
   */
  const pollTitle = useCallback((tid: string) => {
    let attempts = 0;
    const tick = async () => {
      if (threadRef.current !== tid) return; // user moved on
      attempts += 1;
      try {
        const { title: next } = await getThread(tid);
        if (next && next !== titleRef.current) {
          emitThreadEvent<ThreadRenamedEventDetail>(THREAD_RENAMED_EVENT, {
            threadId: tid,
            title: next,
          });
        }
      } catch {
        return; // thread deleted or transient error — stop polling
      }
      if (attempts < 4) window.setTimeout(tick, 2000);
    };
    void tick();
  }, []);

  /** Hand the live run to the sidebar's background watcher, then drop it. */
  const detachRun = useCallback(() => {
    const tid = threadRef.current;
    if (!tid || !runningRef.current) return;
    detachedRef.current = true;
    abortRef.current?.abort();
    emitThreadEvent<ThreadStreamDetachedEventDetail>(
      THREAD_STREAM_DETACHED_EVENT,
      { threadId: tid },
    );
  }, []);

  // Navigating away mid-run detaches the stream: the server keeps generating,
  // and the sidebar takes over watching so its loader/notification stay true.
  useEffect(() => detachRun, [detachRun]);

  // "New Thread" clicked while already on "/" — the router won't navigate a
  // same-URL link, so reset here (detaching a live run to the sidebar first).
  useEffect(() => {
    const onNewThread = () => {
      detachRun();
      threadRef.current = null;
      setMessages([]);
      setLoadedThread(null);
      setTitle(null);
      setStarred(false);
    };
    window.addEventListener(NEW_THREAD_EVENT, onNewThread);
    return () => window.removeEventListener(NEW_THREAD_EVENT, onNewThread);
  }, [detachRun]);

  // Renames can come from the sidebar or history while this thread is open —
  // keep the header title in sync.
  useEffect(() => {
    const onRenamed = (event: Event) => {
      const detail = (event as CustomEvent<ThreadRenamedEventDetail>).detail;
      if (detail?.threadId && detail.threadId === threadRef.current) {
        setTitle(detail.title);
      }
    };
    window.addEventListener(THREAD_RENAMED_EVENT, onRenamed as EventListener);
    return () =>
      window.removeEventListener(
        THREAD_RENAMED_EVENT,
        onRenamed as EventListener,
      );
  }, []);

  /** Patch one assistant message in place (live turns + retries). */
  const patchMessage = useCallback(
    (id: string, fn: (msg: Message) => Partial<Message>) => {
      setMessages((ms) =>
        ms.map((m) => (m.id === id ? { ...m, ...fn(m) } : m)),
      );
    },
    [],
  );

  const runStream = useCallback(
    async (text: string, assistantId: string) => {
      abortRef.current = new AbortController();
      detachedRef.current = false;
      let announced = false;

      const announceStreaming = (tid: string, isStreaming: boolean) => {
        emitThreadEvent<ThreadStreamingStateEventDetail>(THREAD_STREAMING_STATE_EVENT, {
          threadId: tid,
          isStreaming,
        });
      };

      try {
        for await (const ev of streamChat(
          text,
          threadRef.current,
          abortRef.current.signal,
        )) {
          const data = ev.data as Record<string, string>;
          switch (ev.type) {
            case "started": {
              const isNew = !threadRef.current;
              threadRef.current = data.thread_id;
              // Marks "these messages belong to thread X" — enables the
              // header's star/more actions mid-run and tells a later return
              // to "/" (New Thread) to reset.
              setLoadedThread(data.thread_id);
              // Backend sends started_at as epoch ms; accept ISO too.
              const raw = data.started_at;
              const startedAt =
                typeof raw === "number" || /^\d+$/.test(String(raw))
                  ? Number(raw)
                  : Date.parse(String(raw ?? ""));
              patchMessage(assistantId, () => ({
                run: {
                  tools: [],
                  active: true,
                  runStartedAt: Number.isNaN(startedAt) ? null : startedAt,
                },
              }));
              if (isNew) {
                const newTitle = text.trim().slice(0, 60) || "New thread";
                setTitle(newTitle);
                emitThreadEvent<ThreadCreatedEventDetail>(THREAD_CREATED_EVENT, {
                  threadId: data.thread_id,
                  title: newTitle,
                });
              }
              announced = true;
              announceStreaming(data.thread_id, true);
              break;
            }
            case "token":
              patchMessage(assistantId, (m) => ({
                content: m.content + (ev.data as string),
              }));
              break;
            case "tool":
              patchMessage(assistantId, (m) => {
                const tools = [...(m.run?.tools ?? [])];
                if (data.status === "call") {
                  tools.push({
                    tool: data.name,
                    label: verbFor(data.name),
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
            case "done":
              threadRef.current = data.thread_id;
              // Marks "these messages belong to thread X" so a later return
              // to "/" (New Thread) knows to reset — the route prop stays
              // null because replaceState never remounts this page.
              setLoadedThread(data.thread_id);
              window.history.replaceState(
                null,
                "",
                `/threads/${data.thread_id}`,
              );
              patchMessage(assistantId, (m) => ({
                content: data.answer || m.content,
                run: settleRun(m, "done"),
              }));
              announceStreaming(data.thread_id, false);
              break;
            case "stopped":
              patchMessage(assistantId, (m) => ({
                content: data.answer || m.content,
                run: { ...settleRun(m, "skipped"), stopped: true },
              }));
              if (threadRef.current) {
                announceStreaming(threadRef.current, false);
              }
              break;
            case "error":
              patchMessage(assistantId, (m) => ({
                run: {
                  ...settleRun(m, "error", String(ev.data)),
                  failed: true,
                },
              }));
              if (threadRef.current) {
                announceStreaming(threadRef.current, false);
              }
              break;
          }
        }
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          patchMessage(assistantId, (m) => ({
            run: { ...(m.run ?? { tools: [] }), active: false, failed: true },
          }));
          toast.error("Generation failed");
        }
      } finally {
        runningRef.current = false;
        setRunning(false);
        abortRef.current = null;
        // The loop can end without a terminal event (client abort, network
        // drop) — make sure the sidebar never sees a stale streaming flag.
        // Skipped after a detach: the sidebar watcher owns the run now.
        if (announced && threadRef.current && !detachedRef.current) {
          emitThreadEvent<ThreadStreamingStateEventDetail>(THREAD_STREAMING_STATE_EVENT, {
            threadId: threadRef.current,
            isStreaming: false,
          });
          // The LLM title lands post-turn — poll so the header updates even
          // when no sidebar is mounted to refetch the list.
          pollTitle(threadRef.current);
        }
      }
    },
    [patchMessage, pollTitle],
  );

  const send = useCallback(
    (text: string) => {
      if (runningRef.current) return;
      runningRef.current = true;
      setRunning(true);

      const assistantId = nextId("a");
      setMessages((ms) => [
        ...ms,
        { id: nextId("u"), role: "user", content: text },
        {
          id: assistantId,
          role: "assistant",
          content: "",
          prompt: text,
          run: { tools: [], active: true, runStartedAt: null },
        },
      ]);
      void runStream(text, assistantId);
    },
    [runStream],
  );

  const retry = useCallback(
    (messageId: string) => {
      if (runningRef.current) return;
      const msg = messages.find((m) => m.id === messageId);
      if (!msg?.prompt) return;
      runningRef.current = true;
      setRunning(true);
      patchMessage(messageId, () => ({
        content: "",
        run: { tools: [], active: true, runStartedAt: null },
      }));
      void runStream(msg.prompt, messageId);
    },
    [messages, patchMessage, runStream],
  );

  const stop = useCallback(() => {
    const tid = threadRef.current;
    if (tid) stopThread(tid).catch(() => {});
    abortRef.current?.abort();
  }, []);

  // The thread whose messages are on screen — drives the header's star,
  // menu, and the switcher's "Current" badge. Null on a fresh new chat and
  // while a /threads/[id] load is still in flight.
  const activeThreadId = loadedThread;

  const toggleStar = useCallback(() => {
    const tid = activeThreadId;
    if (!tid) return;
    const next = !starred;
    setStarred(next);
    updateThread(tid, { starred: next }).catch(() => {
      setStarred(!next);
      toast.error("Couldn't update the thread");
    });
  }, [activeThreadId, starred]);

  // The open thread was deleted (header menu / Ctrl+Delete): abort any live
  // stream, reset to a blank new chat, and land on "/" if not already there.
  const handleThreadDeleted = useCallback(() => {
    abortRef.current?.abort();
    threadRef.current = null;
    setMessages([]);
    setLoadedThread(null);
    setTitle(null);
    setStarred(false);
    if (pathname !== "/") router.push("/");
  }, [pathname, router]);

  const isEmpty = messages.length === 0;
  const isLoadingThread = !!threadId && loadedThread !== threadId;
  const headerTitle = title ?? (threadId ? "" : "New thread");
  // The composer stays mounted through thread loads — disabled while history
  // is in flight so a send can't race the getThread message swap.
  const composer = (
    <ChatInput
      running={running}
      disabled={isLoadingThread}
      onSend={send}
      onStop={stop}
    />
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ChatHeader
        threadId={activeThreadId}
        title={headerTitle}
        loading={isLoadingThread}
        starred={starred}
        messages={messages}
        onToggleStar={toggleStar}
        onDeleted={handleThreadDeleted}
      />
      {isEmpty ? (
        isLoadingThread ? (
          <>
            <div className="relative flex min-h-0 flex-1 flex-col">
              <ChatMessagesSkeleton />
            </div>
            <div className="relative z-10 mx-auto w-full max-w-3xl px-4 pb-4">
              {composer}
            </div>
          </>
        ) : (
          /* Fresh chat — Linear-style centered hero + composer. px-4 sits
             inside max-w-3xl so the box matches the bottom composer exactly. */
          <div className="flex min-h-0 flex-1 flex-col items-center justify-center pb-10">
            <div className="flex w-full max-w-3xl flex-col items-center px-4">
              <SparkMark animate className="size-7 text-primary" />
              <p className="mt-3 text-sm text-muted-foreground">
                Ask about IDX prices, filings, movers, or news.
              </p>
              <div className="mt-6 w-full">{composer}</div>
            </div>
          </div>
        )
      ) : (
        <>
          <div className="relative flex min-h-0 flex-1 flex-col">
            <ChatMessages messages={messages} onRetry={retry} />
            <div className="chat-fade" aria-hidden="true" />
          </div>
          {/* z-10 keeps the composer + its focus ring painted above the fade
              strip even where they touch. */}
          <div className="relative z-10 mx-auto w-full max-w-3xl px-4 pb-4">
            {composer}
          </div>
        </>
      )}
    </div>
  );
}
