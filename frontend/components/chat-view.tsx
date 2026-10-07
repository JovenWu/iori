"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";

import { ChatHeader } from "@/components/chat-header";
import { ChatInput } from "@/components/chat-input";
import { ChatMessages, ChatMessagesSkeleton } from "@/components/chat-messages";
import { SparkMark } from "@/components/spark-mark";
import { useChatStore } from "@/lib/stores/chat";

export function ChatView({ threadId }: { threadId: string | null }) {
  const router = useRouter();
  const pathname = usePathname();
  const messages = useChatStore((s) => s.messages);
  const running = useChatStore((s) => s.running);
  const activeThreadId = useChatStore((s) => s.threadId);
  const title = useChatStore((s) => s.title);
  const starred = useChatStore((s) => s.starred);
  const loading = useChatStore((s) => s.loading);

  // Claim the shared view for this mounted page; releasing it hands any live
  // run to the threads-store watcher so generation survives navigation.
  useEffect(() => {
    let live = true;
    void useChatStore
      .getState()
      .mountView(threadId)
      .then((ok) => {
        if (!ok && live) router.replace("/");
      });
    return () => {
      live = false;
      useChatStore.getState().unmountView(threadId);
    };
  }, [threadId, router]);

  // `done` swaps the URL to /threads/{id} via history.replaceState — a URL
  // change only, no remount — so this instance keeps holding the finished
  // thread while the route prop stays null. Coming back to "/" (New Thread)
  // is only observable through pathname.
  useEffect(() => {
    useChatStore.getState().syncPathname(pathname);
  }, [pathname]);

  const isEmpty = messages.length === 0;
  const headerTitle = title ?? (threadId ? "" : "New thread");
  // The composer stays mounted through thread loads — disabled while history
  // is in flight so a send can't race the getThread message swap.
  const composer = (
    <>
      <ChatInput
        running={running}
        disabled={loading}
        onSend={(text) => useChatStore.getState().send(text)}
        onStop={() => useChatStore.getState().stop()}
      />
      <p className="mt-1 text-center text-[11px] text-muted-foreground">
        iori can make mistakes — verify figures against official
        IDX disclosures.
      </p>
    </>
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ChatHeader
        threadId={activeThreadId}
        title={headerTitle}
        loading={loading}
        starred={starred}
        messages={messages}
        onToggleStar={() => useChatStore.getState().toggleStar()}
      />
      {isEmpty ? (
        loading ? (
          <>
            <div className="relative flex min-h-0 flex-1 flex-col">
              <ChatMessagesSkeleton />
            </div>
            <div className="relative z-10 mx-auto w-full max-w-3xl px-4 pb-3">
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
            <ChatMessages
              messages={messages}
              onRetry={(id) => useChatStore.getState().retry(id)}
            />
            <div className="chat-fade" aria-hidden="true" />
          </div>
          {/* z-10 keeps the composer + its focus ring painted above the fade
              strip even where they touch. */}
          <div className="relative z-10 mx-auto w-full max-w-3xl px-4 pb-3">
            {composer}
          </div>
        </>
      )}
    </div>
  );
}
