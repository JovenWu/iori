"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  ChevronDownIcon,
  CopyIcon,
  MoreHorizontalIcon,
  PencilIcon,
  PlusIcon,
  StarIcon,
  Trash2Icon,
} from "lucide-react";
import { toast } from "sonner";

import type { Message } from "@/components/chat-messages";
import { ThreadActionDialogs } from "@/components/thread-action-dialogs";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from "@/components/ui/command";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { useThreadActions } from "@/hooks/use-thread-actions";
import { listThreads, type Thread } from "@/lib/api";
import {
  NEW_THREAD_EVENT,
  THREAD_CREATED_EVENT,
  THREAD_DELETED_EVENT,
  THREAD_RENAMED_EVENT,
  emitThreadEvent,
  type ThreadCreatedEventDetail,
  type ThreadDeletedEventDetail,
  type ThreadRenamedEventDetail,
} from "@/lib/thread-events";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** Compact recency for the switcher rows: now / Nm / Nh / Nd / Nw / Nmo / Ny. */
function relativeTime(value: string, now: number) {
  const diff = now - new Date(value).getTime();
  if (Number.isNaN(diff) || diff < MINUTE) return "now";
  const mins = Math.floor(diff / MINUTE);
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d`;
  if (days < 30) return `${Math.floor(days / 7)}w`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo`;
  return `${Math.floor(months / 12)}y`;
}

function startOfDay(timestamp: number) {
  const date = new Date(timestamp);
  date.setHours(0, 0, 0, 0);
  return date.getTime();
}

function switcherGroupFor(value: string, now: number) {
  const dayDiff = Math.round(
    (startOfDay(now) - startOfDay(new Date(value).getTime())) / DAY,
  );
  if (dayDiff <= 0) return "Today";
  if (dayDiff === 1) return "Yesterday";
  return "Older";
}

function threadLabel(thread: Thread) {
  return thread.title ?? thread.first_answer_preview ?? "Untitled";
}

interface ThreadSwitcherProps {
  /** The thread currently on screen — gets the "Current" badge. */
  currentThreadId: string | null;
  title: string;
}

/** Title button + chat-history popover: search, New thread, grouped threads. */
function ThreadSwitcher({ currentThreadId, title }: ThreadSwitcherProps) {
  const router = useRouter();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [threads, setThreads] = useState<Thread[] | null>(null);
  // Snapshot of "now" per open — group labels and row times read it.
  const [now, setNow] = useState(() => Date.now());

  // Fresh list on every open — cheap, and always reflects titles/stars.
  useEffect(() => {
    if (!open) return;
    let live = true;
    listThreads()
      .then((data) => live && setThreads(data.threads))
      .catch(() => live && setThreads([]));
    return () => {
      live = false;
    };
  }, [open]);

  // Keep an open popover live: new chats appear, renames land, deletes drop.
  useEffect(() => {
    if (!open) return;
    const onCreated = (event: Event) => {
      const detail = (event as CustomEvent<ThreadCreatedEventDetail>).detail;
      if (!detail?.threadId) return;
      const now = new Date().toISOString();
      setThreads((prev) =>
        prev && !prev.some((t) => t.id === detail.threadId)
          ? [
              {
                id: detail.threadId,
                title: detail.title?.trim() || "New thread",
                starred: false,
                first_answer_preview: null,
                created_at: now,
                updated_at: now,
              },
              ...prev,
            ]
          : prev,
      );
    };
    const onRenamed = (event: Event) => {
      const detail = (event as CustomEvent<ThreadRenamedEventDetail>).detail;
      if (!detail?.threadId) return;
      setThreads((prev) =>
        prev?.map((t) =>
          t.id === detail.threadId ? { ...t, title: detail.title } : t,
        ) ?? prev,
      );
    };
    const onDeleted = (event: Event) => {
      const detail = (event as CustomEvent<ThreadDeletedEventDetail>).detail;
      if (!detail?.threadId) return;
      setThreads(
        (prev) => prev?.filter((t) => t.id !== detail.threadId) ?? prev,
      );
    };
    window.addEventListener(THREAD_CREATED_EVENT, onCreated as EventListener);
    window.addEventListener(THREAD_RENAMED_EVENT, onRenamed as EventListener);
    window.addEventListener(THREAD_DELETED_EVENT, onDeleted as EventListener);
    return () => {
      window.removeEventListener(
        THREAD_CREATED_EVENT,
        onCreated as EventListener,
      );
      window.removeEventListener(
        THREAD_RENAMED_EVENT,
        onRenamed as EventListener,
      );
      window.removeEventListener(
        THREAD_DELETED_EVENT,
        onDeleted as EventListener,
      );
    };
  }, [open]);

  const groups = useMemo(() => {
    if (!threads) return [];
    const buckets = new Map<string, Thread[]>();
    for (const thread of threads) {
      const label = thread.starred
        ? "Starred"
        : switcherGroupFor(thread.updated_at, now);
      const bucket = buckets.get(label);
      if (bucket) bucket.push(thread);
      else buckets.set(label, [thread]);
    }
    const order = ["Starred", "Today", "Yesterday", "Older"];
    return order
      .filter((label) => buckets.has(label))
      .map((label) => ({ label, threads: buckets.get(label)! }));
  }, [threads, now]);

  const goNewChat = () => {
    setOpen(false);
    if (pathname === "/") {
      emitThreadEvent(NEW_THREAD_EVENT, {});
    } else {
      router.push("/");
    }
  };

  const goThread = (id: string) => {
    setOpen(false);
    if (id !== currentThreadId) router.push(`/threads/${id}`);
  };

  const onOpenChange = (next: boolean) => {
    setOpen(next);
    // Re-anchor relative times/buckets each time the popover opens.
    if (next) setNow(Date.now());
  };

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <h1 className="min-w-0">
        <PopoverTrigger asChild>
          <button
            type="button"
            className="group flex min-w-0 items-center gap-1 rounded-md px-1.5 py-1 text-left transition-colors hover:bg-muted"
          >
            {/* key remount replays the swap animation when a new title
                lands (LLM rename, manual rename). */}
            <span
              key={title}
              className="chat-title-in block min-w-0 truncate text-[0.8125rem] font-medium text-foreground"
            >
              {title}
            </span>
            <ChevronDownIcon className="size-3.5 shrink-0 text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
          </button>
        </PopoverTrigger>
      </h1>
      <PopoverContent align="start" className="w-[380px] p-0">
        <Command loop>
          <CommandInput placeholder="Chat history" autoFocus />
          <CommandList className="max-h-80">
            {threads !== null && (
              <CommandEmpty className="py-8 text-muted-foreground">
                No conversations found.
              </CommandEmpty>
            )}
            {currentThreadId && (
              <CommandGroup>
                <CommandItem
                  value="new thread"
                  onSelect={goNewChat}
                  className="cursor-pointer"
                >
                  <PlusIcon />
                  New thread
                </CommandItem>
              </CommandGroup>
            )}
            {threads === null ? (
              <div className="space-y-1 p-2">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div
                    key={i}
                    className="h-7 animate-pulse rounded-md bg-muted/60"
                  />
                ))}
              </div>
            ) : (
              groups.map((group) => (
                <CommandGroup key={group.label} heading={group.label}>
                  {group.threads.map((thread) => (
                    <CommandItem
                      key={thread.id}
                      value={thread.id}
                      keywords={[
                        threadLabel(thread),
                        thread.first_answer_preview ?? "",
                      ]}
                      onSelect={() => goThread(thread.id)}
                      className="cursor-pointer"
                    >
                      <span className="min-w-0 flex-1 truncate">
                        {threadLabel(thread)}
                      </span>
                      <CommandShortcut className="flex items-center gap-1.5 tracking-normal">
                        {thread.id === currentThreadId && (
                          <span className="rounded-md bg-muted px-1.5 py-px text-[11px] font-medium text-muted-foreground">
                            Current
                          </span>
                        )}
                        {relativeTime(thread.updated_at, now)}
                      </CommandShortcut>
                    </CommandItem>
                  ))}
                </CommandGroup>
              ))
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

function messagesToMarkdown(messages: Message[]) {
  return messages
    .filter((m) => m.content.trim())
    .map(
      (m) =>
        `**${m.role === "user" ? "User" : "Assistant"}:**\n\n${m.content.trim()}`,
    )
    .join("\n\n");
}

interface ChatHeaderProps {
  /** Loaded thread on screen (null = fresh new chat). */
  threadId: string | null;
  title: string;
  starred: boolean;
  messages: Message[];
  onToggleStar: () => void;
  /** Called after the open thread is deleted — parent resets chat state. */
  onDeleted: () => void;
}

export function ChatHeader({
  threadId,
  title,
  starred,
  messages,
  onToggleStar,
  onDeleted,
}: ChatHeaderProps) {
  const threadActions = useThreadActions({
    onRenamed: () => {},
    onDeleted,
  });
  const { openDelete: openDeleteDialog, openRename } = threadActions;

  const openDelete = useCallback(() => {
    if (threadId) openDeleteDialog({ threadId, title });
  }, [threadId, title, openDeleteDialog]);

  const openRenameDialog = useCallback(() => {
    if (threadId) openRename({ threadId, title });
  }, [threadId, title, openRename]);

  // Ctrl+Delete deletes the open thread — the shortcut shown in the menu.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Delete" || !event.ctrlKey) return;
      const el = event.target as HTMLElement | null;
      if (el?.closest("input, textarea, [contenteditable=true]")) return;
      event.preventDefault();
      openDelete();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openDelete]);

  const copyMarkdown = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(messagesToMarkdown(messages));
      toast.success("Copied as markdown");
    } catch {
      toast.error("Couldn't copy to clipboard");
    }
  }, [messages]);

  const canCopy = messages.some((m) => m.content.trim());

  return (
    <header className="flex h-12 shrink-0 items-center gap-1.5 border-b border-border/60 px-3">
      <SidebarTrigger className="-ml-1" />
      <ThreadSwitcher currentThreadId={threadId} title={title} />
      {threadId && (
        <>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={onToggleStar}
            aria-label={starred ? "Unstar thread" : "Star thread"}
            aria-pressed={starred}
          >
            <StarIcon
              className={
                starred ? "fill-primary text-primary" : "text-muted-foreground"
              }
            />
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Thread actions"
              >
                <MoreHorizontalIcon className="text-muted-foreground" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-48">
              <DropdownMenuItem onSelect={copyMarkdown} disabled={!canCopy}>
                <CopyIcon />
                Copy as markdown
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={openRenameDialog}>
                <PencilIcon />
                Rename
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" onSelect={openDelete}>
                <Trash2Icon />
                Delete
                <DropdownMenuShortcut>Ctrl Delete</DropdownMenuShortcut>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </>
      )}

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
    </header>
  );
}
