"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { ChatInput } from "@/components/chat-input";
import { ChatMessages, type Message } from "@/components/chat-messages";
import { getThread, stopThread, streamChat } from "@/lib/api";
import { verbFor } from "@/lib/tool-labels";
import type { ToolActivity } from "@/components/agent-status";
import {
  THREAD_CREATED_EVENT,
  THREAD_STREAMING_STATE_EVENT,
  THREAD_STREAM_DETACHED_EVENT,
  type ThreadCreatedEventDetail,
  type ThreadStreamingStateEventDetail,
  type ThreadStreamDetachedEventDetail,
} from "@/lib/thread-events";

let msgSeq = 0;
const nextId = (prefix: string) => `${prefix}-${Date.now()}-${++msgSeq}`;

function emit<T>(type: string, detail: T) {
  window.dispatchEvent(new CustomEvent<T>(type, { detail }));
}

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
  const [messages, setMessages] = useState<Message[]>([]);
  const [running, setRunning] = useState(false);
  const [loadedThread, setLoadedThread] = useState<string | null>(null);
  const threadRef = useRef<string | null>(threadId);
  const runningRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  const [prevThread, setPrevThread] = useState(threadId);
  if (prevThread !== threadId) {
    setPrevThread(threadId);
    setMessages([]);
    setLoadedThread(null);
  }

  useEffect(() => {
    threadRef.current = threadId;
    if (!threadId) return;
    getThread(threadId)
      .then((t) => {
        setMessages(toMessages(t.messages));
        setLoadedThread(threadId);
      })
      .catch(() => {
        toast.error("Couldn't load that thread");
        router.replace("/");
      });
  }, [threadId, router]);

  // Navigating away mid-run detaches the stream: the server keeps generating,
  // and the sidebar takes over watching so its loader/notification stay true.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      const tid = threadRef.current;
      if (tid && runningRef.current) {
        emit<ThreadStreamDetachedEventDetail>(THREAD_STREAM_DETACHED_EVENT, {
          threadId: tid,
        });
      }
    };
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
      let announced = false;

      const announceStreaming = (tid: string, isStreaming: boolean) => {
        emit<ThreadStreamingStateEventDetail>(THREAD_STREAMING_STATE_EVENT, {
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
                emit<ThreadCreatedEventDetail>(THREAD_CREATED_EVENT, {
                  threadId: data.thread_id,
                  title: text.trim().slice(0, 60) || "New thread",
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
        if (announced && threadRef.current) {
          emit<ThreadStreamingStateEventDetail>(THREAD_STREAMING_STATE_EVENT, {
            threadId: threadRef.current,
            isStreaming: false,
          });
        }
      }
    },
    [patchMessage],
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

  const showComposer = !threadId || loadedThread === threadId;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="relative flex min-h-0 flex-1 flex-col">
        <ChatMessages messages={messages} onRetry={retry} />
        <div className="chat-fade" aria-hidden="true" />
      </div>
      {/* z-10 keeps the composer + its focus ring painted above the fade
          strip even where they touch. */}
      <div className="relative z-10 mx-auto w-full max-w-3xl px-4 pb-4">
        {showComposer && (
          <ChatInput running={running} onSend={send} onStop={stop} />
        )}
      </div>
    </div>
  );
}
