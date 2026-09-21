"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { AgentStatus, type ToolActivity } from "@/components/agent-status";
import { cn } from "@/lib/utils";

export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  /** Live/completed run state — absent on messages loaded from history. */
  run?: {
    tools: ToolActivity[];
    active: boolean;
    failed?: boolean;
    stopped?: boolean;
    durationMs?: number;
    runStartedAt?: number | null;
  };
  /** The prompt that produced this assistant message — used for retry. */
  prompt?: string;
};

const markdownClasses =
  "prose-sm max-w-none text-sm leading-6 text-ink-muted [&_table]:w-full [&_table]:border-collapse [&_td]:border-b [&_td]:border-border [&_td]:px-2 [&_td]:py-1.5 [&_th]:border-b [&_th]:border-border [&_th]:px-2 [&_th]:py-1.5 [&_th]:text-left [&_th]:font-medium [&_a]:text-primary [&_code]:rounded [&_code]:bg-secondary [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-xs [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-secondary [&_pre]:p-3 [&_pre_code]:bg-transparent [&_pre_code]:p-0";

function UserBubble({ content }: { content: string }) {
  const [expanded, setExpanded] = useState(false);
  const [clamped, setClamped] = useState(false);
  const textRef = useRef<HTMLParagraphElement>(null);

  // Measure whether the text actually overflows the clamp — only then offer
  // the expand affordance.
  useEffect(() => {
    const el = textRef.current;
    if (!el) return;
    setClamped(el.scrollHeight > el.clientHeight + 1);
  }, [content]);

  return (
    <div
      className={cn(
        "ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-md border border-transparent bg-bubble px-3.5 py-2 text-sm text-bubble-foreground",
        clamped && !expanded && "cursor-pointer",
      )}
      onClick={() => {
        if (clamped) setExpanded((v) => !v);
      }}
      title={clamped ? (expanded ? "Collapse" : "Show more") : undefined}
    >
      <p
        ref={textRef}
        className={cn(
          "whitespace-pre-wrap break-words",
          !expanded && "line-clamp-3",
        )}
      >
        {content}
      </p>
      {clamped && !expanded && (
        <span className="mt-0.5 block text-[11px] font-medium text-muted-foreground">
          Show more
        </span>
      )}
    </div>
  );
}

function AssistantMessage({
  msg,
  onRetry,
}: {
  msg: Message;
  onRetry?: (messageId: string) => void;
}) {
  return (
    <div className="min-w-0">
      {msg.run && (
        <AgentStatus
          tools={msg.run.tools}
          active={msg.run.active}
          failed={msg.run.failed}
          stopped={msg.run.stopped}
          durationMs={msg.run.durationMs}
          runStartedAt={msg.run.runStartedAt}
          onRetry={
            msg.run.failed && onRetry ? () => onRetry(msg.id) : undefined
          }
        />
      )}
      {msg.content && (
        <div className={markdownClasses}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {msg.content}
          </ReactMarkdown>
        </div>
      )}
    </div>
  );
}

export function ChatMessages({
  messages,
  onRetry,
}: {
  messages: Message[];
  onRetry?: (messageId: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  // Pinned to bottom while streaming, until the user scrolls away.
  const pinnedRef = useRef(true);

  // When a new user message lands, scroll it to the top of the viewport so
  // the incoming answer reads top-down. Assistant messages pin to bottom.
  const lastId = messages[messages.length - 1]?.id;
  useEffect(() => {
    const container = containerRef.current;
    if (!container || !lastId) return;
    const last = messages[messages.length - 1];
    if (last.role === "user") {
      const el = container.querySelector<HTMLElement>(`[data-msg="${last.id}"]`);
      if (el) {
        // Rect math — correct no matter which ancestor ends up positioned.
        container.scrollTop =
          el.getBoundingClientRect().top -
          container.getBoundingClientRect().top +
          container.scrollTop -
          16;
        pinnedRef.current = true;
        return;
      }
    }
    endRef.current?.scrollIntoView({ block: "end" });
    pinnedRef.current = true;
  }, [lastId]); // eslint-disable-line react-hooks/exhaustive-deps

  // While streaming, keep the tail in view only if the user hasn't scrolled up.
  const lastContent = messages[messages.length - 1]?.content;
  useEffect(() => {
    const container = containerRef.current;
    if (!container || !pinnedRef.current) return;
    container.scrollTop = container.scrollHeight;
  }, [lastContent]);

  return (
    <div
      ref={containerRef}
      // Reserve the scrollbar gutter on BOTH edges so the centered column
      // keeps the same center + width as the input below it — no sideways
      // shift when content grows from short to overflowing.
      className="flex min-h-0 w-full flex-1 flex-col overflow-y-auto [scrollbar-gutter:stable_both-edges]"
      onScroll={(e) => {
        const el = e.currentTarget;
        pinnedRef.current =
          el.scrollHeight - el.scrollTop - el.clientHeight < 48;
      }}
    >
      {/* 46rem < input's max-w-3xl (48rem) — the text column sits a touch
          inside the composer edges. */}
      <div className="mx-auto flex w-full max-w-[46rem] flex-col gap-8 px-4 py-6">
        {messages.map((msg) => (
          <div key={msg.id} data-msg={msg.id}>
            {msg.role === "user" ? (
              <UserBubble content={msg.content} />
            ) : (
              <AssistantMessage msg={msg} onRetry={onRetry} />
            )}
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  );
}
