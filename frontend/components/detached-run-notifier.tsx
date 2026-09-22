"use client";

import { useEffect, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import { CircleCheckIcon } from "lucide-react";
import { toast } from "sonner";

import { useSettings } from "@/lib/settings";
import { useThreadsStore } from "@/lib/stores/threads";

/**
 * Toasts "Response ready" when a backgrounded run finishes. Lives in the
 * (chat) layout rather than the sidebar so it keeps working when the mobile
 * sheet is unmounted — the store's watcher owns the run either way.
 */
export function DetachedRunNotifier() {
  const finished = useThreadsStore((s) => s.finishedRun);
  const { settings } = useSettings();
  const router = useRouter();
  const pathname = usePathname();
  // Guard against re-firing: the effect also re-runs on pathname changes.
  const seenRef = useRef(0);

  useEffect(() => {
    if (!finished || finished.at <= seenRef.current) return;
    seenRef.current = finished.at;
    if (!settings.notifyOnDone) return;
    // No notification for the thread the user is already watching.
    if (pathname === `/threads/${finished.threadId}`) return;

    const { threadId, title } = finished;
    toast.custom((t) => (
      <button
        type="button"
        onClick={() => {
          toast.dismiss(t);
          router.push(`/threads/${threadId}`);
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
  }, [finished, settings.notifyOnDone, pathname, router]);

  return null;
}
