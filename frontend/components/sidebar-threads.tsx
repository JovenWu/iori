"use client";

import { useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuBadge,
  SidebarMenuItem,
  SidebarMenuButton,
} from "@/components/ui/sidebar";
import { Skeleton } from "@/components/ui/skeleton";
import {
  CalendarClockIcon,
  ChevronRightIcon,
  HistoryIcon,
  Loader2Icon,
  MessageCircleIcon,
  MoreHorizontalIcon,
  SquarePlus,
  TimerIcon,
} from "lucide-react";
import type { Thread } from "@/lib/api";
import { markdownToPlainText } from "@/lib/markdown";
import { ThreadActionsMenu } from "@/components/thread-actions-menu";
import { ThreadActionDialogs } from "@/components/thread-action-dialogs";
import { useThreadActions } from "@/hooks/use-thread-actions";
import { copy } from "@/lib/aksi";
import { useSettings } from "@/lib/settings";
import { useAksiStore } from "@/lib/stores/aksi";
import { useChatStore } from "@/lib/stores/chat";
import {
  getTimestamp,
  useThreadsStore,
  type ListedThread,
} from "@/lib/stores/threads";

function threadTitle(thread: Thread): string {
  return (
    thread.title ??
    (markdownToPlainText(thread.first_answer_preview ?? "") || "Untitled")
  );
}

function ThreadRow({
  thread,
  isActive,
  actions,
}: {
  thread: ListedThread;
  isActive: boolean;
  actions: ReturnType<typeof useThreadActions>;
}) {
  const title = threadTitle(thread);
  return (
    <SidebarMenuItem className="[&:has([data-sidebar=menu-action]:hover)_[data-sidebar=menu-button]]:bg-transparent [&:has([data-sidebar=menu-action]:hover)_[data-sidebar=menu-button]]:text-sidebar-foreground">
      <SidebarMenuButton
        asChild
        isActive={isActive}
        tooltip={title}
        // Let the title use the full width; only reserve room for the
        // actions button (or the pending spinner) when it's actually
        // visible, so titles aren't truncated early.
        className={`h-7 py-1.5 group-hover/menu-item:pr-8 group-focus-within/menu-item:pr-8${
          thread.isPending ? " pr-8" : ""
        }`}
      >
        <Link
          href={`/threads/${thread.id}`}
          className="flex min-w-0 items-center gap-1.5"
        >
          {thread.scheduled && (
            <TimerIcon
              className="size-3.5 shrink-0 text-muted-foreground"
              aria-label="Scheduled job thread"
            />
          )}
          <span className="min-w-0 flex-1 truncate">{title}</span>
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
          onRename={() => actions.openRename({ threadId: thread.id, title })}
          onDelete={() => actions.openDelete({ threadId: thread.id, title })}
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
}

export function SidebarThreads() {
  const RECENT_LIMIT = 20;
  const pathname = usePathname();
  const threads = useThreadsStore((s) => s.threads);
  const loaded = useThreadsStore((s) => s.loaded);
  const hasMore = useThreadsStore((s) => s.nextCursor !== null);

  // First fetch + resume watching threads whose first turn may still be in
  // flight. The store owns the list, watchers, and pending flags from here.
  useEffect(() => {
    useThreadsStore.getState().init();
  }, []);

  const urgentCount = useAksiStore((s) => s.urgentCount);
  const aksiLabel = copy[useSettings().settings.language].sidebarLabel;
  useEffect(() => {
    void useAksiStore.getState().refreshBadge();
  }, []);

  const threadActions = useThreadActions();

  // Starred threads pin to Favorites, oldest first so positions stay stable;
  // they drop out of Recent entirely (mirrors the header switcher's buckets).
  const starredThreads = threads
    .filter((t) => t.starred)
    .sort((a, b) => getTimestamp(a.updated_at) - getTimestamp(b.updated_at));
  const recentThreads = threads
    .filter((t) => !t.starred)
    .slice(0, RECENT_LIMIT);
  // More rows may exist server-side even when only page one is loaded.
  const shouldShowViewAll = hasMore || threads.length > RECENT_LIMIT;

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
                  // Already on "/" — the router won't navigate a same-URL
                  // link, so tell the open ChatView to reset itself.
                  if (pathname === "/") {
                    useChatStore.getState().reset();
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
          <SidebarMenuItem>
            <SidebarMenuButton
              asChild
              tooltip={aksiLabel}
              isActive={pathname === "/action"}
              className="h-10 px-4"
            >
              <Link href="/action">
                <CalendarClockIcon />
                <span className="group-data-[collapsible=icon]:hidden">
                  {aksiLabel}
                </span>
              </Link>
            </SidebarMenuButton>
            {urgentCount > 0 && (
              <SidebarMenuBadge className="font-mono">{urgentCount}</SidebarMenuBadge>
            )}
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton
              asChild
              tooltip="Schedules"
              isActive={pathname === "/schedules"}
              className="h-10 px-4"
            >
              <Link href="/schedules">
                <TimerIcon />
                <span className="group-data-[collapsible=icon]:hidden">
                  Schedules
                </span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>

        <div className="flex min-h-0 flex-1 flex-col gap-2 group-data-[collapsible=icon]:hidden">
          {!loaded ? (
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
            <>
              {starredThreads.length > 0 && (
                <>
                  <div className="px-2 pt-1">
                    <span className="text-xs font-medium text-muted-foreground/70">
                      Favorites
                    </span>
                  </div>
                  {/* Bounded so a long favorites list can't starve Recent. */}
                  <SidebarMenu className="max-h-[35%] gap-0.5 overflow-y-auto [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden">
                    {starredThreads.map((thread) => (
                      <ThreadRow
                        key={thread.id}
                        thread={thread}
                        isActive={pathname === `/threads/${thread.id}`}
                        actions={threadActions}
                      />
                    ))}
                  </SidebarMenu>
                </>
              )}

              <div className="px-2 pt-1">
                <span className="text-xs font-medium text-muted-foreground/70">
                  Recent
                </span>
              </div>
              <SidebarMenu className="min-h-0 flex-1 gap-0.5 overflow-y-auto [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden">
                {recentThreads.map((thread) => (
                  <ThreadRow
                    key={thread.id}
                    thread={thread}
                    isActive={pathname === `/threads/${thread.id}`}
                    actions={threadActions}
                  />
                ))}
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
            </>
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
        preventCloseAutoFocus
      />
    </SidebarGroup>
  );
}
