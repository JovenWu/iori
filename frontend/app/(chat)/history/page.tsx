"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  CheckIcon,
  ChevronsUpDownIcon,
  Clock3Icon,
  MessageSquareIcon,
  MoreHorizontalIcon,
  SearchIcon,
  SquarePenIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandGroup,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { Thread } from "@/lib/api";
import { markdownToPlainText } from "@/lib/markdown";
import { ThreadActionsMenu } from "@/components/thread-actions-menu";
import { ThreadActionDialogs } from "@/components/thread-action-dialogs";
import { useThreadActions } from "@/hooks/use-thread-actions";
import { useThreadsStore } from "@/lib/stores/threads";

type SortOption = "newest" | "oldest";

const SORT_OPTIONS: { value: SortOption; label: string }[] = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
];

function SortCombobox({
  value,
  onChange,
}: {
  value: SortOption;
  onChange: (value: SortOption) => void;
}) {
  const [open, setOpen] = useState(false);
  const selected = SORT_OPTIONS.find((option) => option.value === value);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className="h-10 w-40 shrink-0 justify-between rounded-xl font-normal"
        >
          {selected?.label ?? "Newest first"}
          <ChevronsUpDownIcon className="size-4 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-40 p-0">
        <Command>
          <CommandList>
            <CommandGroup>
              {SORT_OPTIONS.map((option) => (
                <CommandItem
                  key={option.value}
                  value={option.value}
                  onSelect={(currentValue) => {
                    onChange(currentValue as SortOption);
                    setOpen(false);
                  }}
                >
                  {option.label}
                  <CheckIcon
                    className={cn(
                      "ml-auto size-4",
                      value === option.value ? "opacity-100" : "opacity-0",
                    )}
                  />
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

const timeFormatter = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
});
const dateFormatter = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
});
const monthFormatter = new Intl.DateTimeFormat("en-US", {
  month: "long",
  year: "numeric",
});

function startOfDay(timestamp: number) {
  const date = new Date(timestamp);
  date.setHours(0, 0, 0, 0);
  return date.getTime();
}

/** Compact timestamp for the row's right edge: time today, date otherwise. */
function formatRowTimestamp(value: string, now: number) {
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return "";

  if (startOfDay(timestamp) === startOfDay(now)) {
    return timeFormatter.format(new Date(timestamp));
  }
  return dateFormatter.format(new Date(timestamp));
}

/** Bucket label for a thread, newest buckets first. */
function groupLabelFor(value: string, now: number) {
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return "Older";

  const dayDiff = Math.round(
    (startOfDay(now) - startOfDay(timestamp)) / DAY,
  );

  if (dayDiff <= 0) return "Today";
  if (dayDiff === 1) return "Yesterday";
  if (dayDiff < 7) return "Previous 7 days";
  if (dayDiff < 30) return "Previous 30 days";
  return monthFormatter.format(new Date(timestamp));
}

function groupThreads(threads: Thread[], now: number) {
  const buckets = new Map<string, Thread[]>();
  const ordered: { label: string; threads: Thread[] }[] = [];

  // Starred threads pin above every date bucket (mirrors the sidebar's
  // Favorites section) regardless of the active sort direction.
  const favorites = threads.filter((t) => t.starred);
  if (favorites.length) ordered.push({ label: "Favorites", threads: favorites });

  // Threads arrive pre-sorted, so first-seen bucket order already matches the
  // active sort direction for both the fixed buckets and the month buckets.
  for (const thread of threads) {
    if (thread.starred) continue;
    const label = groupLabelFor(thread.updated_at, now);
    const bucket = buckets.get(label);
    if (bucket) {
      bucket.push(thread);
    } else {
      const next: Thread[] = [thread];
      buckets.set(label, next);
      ordered.push({ label, threads: next });
    }
  }

  return ordered;
}

function titleOf(thread: Thread): string {
  return thread.title ?? "Untitled";
}

export default function HistoryPage() {
  const threads = useThreadsStore((s) => s.threads);
  const loaded = useThreadsStore((s) => s.loaded);
  const hasMore = useThreadsStore((s) => s.nextCursor !== null);
  const total = useThreadsStore((s) => s.total);
  const loadingMore = useThreadsStore((s) => s.loadingMore);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortOption>("newest");
  // Tick once a minute so day buckets and timestamps stay honest without
  // re-rendering the whole list every second.
  const [now, setNow] = useState(() => Date.now());

  const threadActions = useThreadActions();

  // Fresh pull on mount; later edits (rename/delete/undo) arrive through the
  // shared store, so no listener wiring lives here.
  useEffect(() => {
    void useThreadsStore.getState().refresh();
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), MINUTE);
    return () => window.clearInterval(timer);
  }, []);

  // If the loaded pages can't fill the viewport there's no scrollbar to
  // trigger the next fetch — pull it eagerly instead.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && hasMore && !loadingMore && el.scrollHeight <= el.clientHeight) {
      void useThreadsStore.getState().loadMore();
    }
  }, [threads, hasMore, loadingMore]);

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 240) {
      void useThreadsStore.getState().loadMore();
    }
  };

  const filteredThreads = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();

    const searched = normalizedSearch
      ? threads.filter((thread) => {
          const title = titleOf(thread).toLowerCase();
          const preview = (thread.first_answer_preview || "").toLowerCase();
          return (
            title.includes(normalizedSearch) ||
            preview.includes(normalizedSearch)
          );
        })
      : threads;

    return [...searched].sort((a, b) => {
      const left = new Date(a.updated_at).getTime();
      const right = new Date(b.updated_at).getTime();
      return sort === "newest" ? right - left : left - right;
    });
  }, [search, sort, threads]);

  const groups = useMemo(
    () => groupThreads(filteredThreads, now),
    [filteredThreads, now],
  );

  const isSearching = search.trim().length > 0;

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div className="pointer-events-none absolute inset-x-0 top-0 z-40">
        <div className="flex h-16 items-center px-4">
          <SidebarTrigger className="pointer-events-auto bg-secondary/70 backdrop-blur-sm" />
        </div>
      </div>

      {/* SidebarInset is h-svh + overflow-hidden — this is the scroll region.
          Full width so the scrollbar sits at the viewport edge, not the
          centered column's. */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="min-h-0 flex-1 overflow-y-auto"
      >
        <div className="mx-auto flex w-full max-w-2xl flex-col px-4 pb-16 pt-20 md:pt-24">
        {/* Header */}
        <div className="flex items-end justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">History</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {!loaded
                ? "Loading your conversations…"
                : threads.length === 0
                  ? "Your past conversations live here"
                  : `${filteredThreads.length} of ${total ?? threads.length} conversation${(total ?? threads.length) === 1 ? "" : "s"}`}
            </p>
          </div>
        </div>

        {/* Toolbar: search + sort */}
        <div className="mt-5 flex items-center gap-2">
          <div className="relative min-w-0 flex-1">
            <SearchIcon className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search conversations"
              aria-label="Search conversations"
              className="h-10 w-full rounded-xl border border-border/70 bg-background pl-10 pr-4 text-sm outline-none transition-colors placeholder:text-muted-foreground/80 focus:border-border"
            />
          </div>
          <SortCombobox value={sort} onChange={setSort} />
        </div>

        {/* List */}
        {!loaded ? (
          <div className="mt-8 space-y-8">
            {[3, 2].map((rows, group) => (
              <div key={group}>
                <Skeleton className="h-3.5 w-24 rounded" />
                <div className="mt-3 space-y-1">
                  {Array.from({ length: rows }).map((_, i) => (
                    <Skeleton key={i} className="h-14 w-full rounded-xl" />
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : filteredThreads.length === 0 ? (
          <div className="mt-8 flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-border/70 px-6 py-16 text-center">
            <div className="flex size-11 items-center justify-center rounded-full bg-secondary">
              {isSearching ? (
                <SearchIcon className="size-5 text-muted-foreground" />
              ) : (
                <MessageSquareIcon className="size-5 text-muted-foreground" />
              )}
            </div>
            {isSearching ? (
              <>
                <p className="text-sm font-medium">
                  No results for &ldquo;{search.trim()}&rdquo;
                </p>
                <p className="max-w-60 text-xs leading-relaxed text-muted-foreground">
                  Try a different title or a word from the reply.
                </p>
                <Button
                  variant="outline"
                  className="mt-1"
                  onClick={() => setSearch("")}
                >
                  Clear search
                </Button>
              </>
            ) : (
              <>
                <p className="text-sm font-medium">No conversations yet</p>
                <p className="max-w-60 text-xs leading-relaxed text-muted-foreground">
                  Threads you start will show up here, grouped by day.
                </p>
                <Button className="mt-1" asChild>
                  <Link href="/">
                    <SquarePenIcon className="size-4" />
                    Start a new thread
                  </Link>
                </Button>
              </>
            )}
          </div>
        ) : (
          <div className="mt-8 space-y-7">
            {groups.map((group) => (
              <section key={group.label}>
                <h2 className="px-3 text-xs font-medium text-muted-foreground">
                  {group.label}
                </h2>
                <div className="mt-1.5">
                  {group.threads.map((thread) => (
                    <div
                      key={thread.id}
                      className="group relative flex items-center gap-1 rounded-xl transition-colors hover:bg-muted/60"
                    >
                      <Link
                        href={`/threads/${thread.id}`}
                        className="min-w-0 flex-1 px-3 py-2.5"
                      >
                        <div className="flex items-baseline justify-between gap-3">
                          <span className="min-w-0 truncate text-sm font-medium text-foreground">
                            {titleOf(thread)}
                          </span>
                          <span className="inline-flex shrink-0 items-center gap-1 text-xs tabular-nums text-muted-foreground">
                            <Clock3Icon className="size-3" />
                            {formatRowTimestamp(thread.updated_at, now)}
                          </span>
                        </div>
                        <p className="mt-0.5 truncate pr-8 text-[13px] leading-snug text-muted-foreground">
                          {markdownToPlainText(
                            thread.first_answer_preview ?? "",
                          ) || "No preview available."}
                        </p>
                      </Link>

                      <ThreadActionsMenu
                        showIcons
                        onRename={() =>
                          threadActions.openRename({
                            threadId: thread.id,
                            title: titleOf(thread),
                          })
                        }
                        onDelete={() =>
                          threadActions.openDelete({
                            threadId: thread.id,
                            title: titleOf(thread),
                          })
                        }
                        trigger={
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            className="absolute right-2 top-1/2 -translate-y-1/2 bg-background/80 text-muted-foreground backdrop-blur-sm transition-opacity hover:bg-secondary hover:text-foreground focus-visible:opacity-100 data-[state=open]:opacity-100 sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100"
                            aria-label="Thread actions"
                          >
                            <MoreHorizontalIcon className="size-4" />
                          </Button>
                        }
                      />
                    </div>
                  ))}
                </div>
              </section>
            ))}
            {loadingMore && (
              <div className="space-y-1" role="status" aria-label="Loading more">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-14 w-full rounded-xl" />
                ))}
              </div>
            )}
          </div>
        )}
        </div>
      </div>

      <ThreadActionDialogs
        renameTargetTitle={threadActions.renameTarget?.title}
        deleteTargetTitle={threadActions.deleteTarget?.title}
        renameValue={threadActions.renameValue}
        isRenaming={threadActions.isRenaming}
        isDeleting={threadActions.isDeleting}
        onRenameValueChange={threadActions.setRenameValue}
        onRenameOpenChange={(open) => {
          if (!open) {
            threadActions.closeRename();
          }
        }}
        onDeleteOpenChange={(open) => {
          if (!open) {
            threadActions.closeDelete();
          }
        }}
        onSubmitRename={threadActions.submitRename}
        onSubmitDelete={threadActions.submitDelete}
        renameInputClassName="focus-visible:border-input focus-visible:ring-1"
        cancelLabel="Nevermind"
      />
    </div>
  );
}
