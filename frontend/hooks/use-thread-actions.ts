"use client";

import { useCallback, useState } from "react";
import { toast } from "sonner";
import { deleteThread, updateThread } from "@/lib/api";
import {
  THREAD_DELETED_EVENT,
  THREAD_RENAMED_EVENT,
  THREADS_REFRESH_EVENT,
  emitThreadEvent,
  type ThreadDeletedEventDetail,
  type ThreadRenamedEventDetail,
} from "@/lib/thread-events";

const THREAD_TITLE_CHAR_LIMIT = 100;
/** How long the delete toast offers Undo before the DELETE request fires. */
const DELETE_UNDO_MS = 6000;

export interface ThreadActionTarget {
  threadId: string;
  title: string;
}

interface UseThreadActionsOptions {
  onRenamed: (threadId: string, nextTitle: string) => void;
  onDeleted: (threadId: string) => void;
}

export function useThreadActions(options: UseThreadActionsOptions) {
  const { onRenamed, onDeleted } = options;

  const [renameTarget, setRenameTarget] = useState<ThreadActionTarget | null>(
    null,
  );
  const [deleteTarget, setDeleteTarget] = useState<ThreadActionTarget | null>(
    null,
  );
  const [renameValue, setRenameValue] = useState("");
  const [isRenaming, setIsRenaming] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  const openRename = useCallback((target: ThreadActionTarget) => {
    setRenameTarget(target);
    setRenameValue(target.title);
  }, []);

  const openDelete = useCallback((target: ThreadActionTarget) => {
    setDeleteTarget(target);
  }, []);

  const closeRename = useCallback(() => {
    setRenameTarget(null);
  }, []);

  const closeDelete = useCallback(() => {
    setDeleteTarget(null);
  }, []);

  const applyTitle = useCallback(
    async (threadId: string, title: string) => {
      await updateThread(threadId, { title });
      emitThreadEvent<ThreadRenamedEventDetail>(THREAD_RENAMED_EVENT, {
        threadId,
        title,
      });
      onRenamed(threadId, title);
    },
    [onRenamed],
  );

  const restoreTitle = useCallback(
    async (threadId: string, title: string) => {
      try {
        await applyTitle(threadId, title);
      } catch (err) {
        console.error("Failed to restore thread title:", err);
        toast.error("Couldn't undo the rename");
      }
    },
    [applyTitle],
  );

  const submitRename = useCallback(async () => {
    if (!renameTarget || isRenaming) return;

    const nextTitle = renameValue.trim();
    if (!nextTitle || nextTitle === renameTarget.title) {
      closeRename();
      return;
    }

    if (nextTitle.length > THREAD_TITLE_CHAR_LIMIT) {
      console.error(
        `Thread title exceeds ${THREAD_TITLE_CHAR_LIMIT} character limit`,
      );
      return;
    }

    setIsRenaming(true);

    const { threadId, title: previousTitle } = renameTarget;

    try {
      await applyTitle(threadId, nextTitle);
      closeRename();
      toast.success("Renamed thread", {
        action: {
          label: "Undo",
          onClick: () => void restoreTitle(threadId, previousTitle),
        },
      });
    } catch (err) {
      console.error("Failed to rename thread:", err);
      toast.error("Couldn't rename the thread");
    } finally {
      setIsRenaming(false);
    }
  }, [
    renameTarget,
    isRenaming,
    renameValue,
    closeRename,
    applyTitle,
    restoreTitle,
  ]);

  const submitDelete = useCallback(async () => {
    if (!deleteTarget || isDeleting) return;

    setIsDeleting(true);
    const { threadId } = deleteTarget;

    // Optimistic: remove the row everywhere now. The actual DELETE only fires
    // once the toast closes — Undo within the window cancels it entirely.
    emitThreadEvent<ThreadDeletedEventDetail>(THREAD_DELETED_EVENT, {
      threadId,
    });
    onDeleted(threadId);
    closeDelete();
    setIsDeleting(false);

    let undone = false;
    let committed = false;
    // Sonner fires onAutoClose then onDismiss on expiry — commit must be
    // idempotent or the DELETE (and its potential error toast) runs twice.
    const commit = () => {
      if (undone || committed) return;
      committed = true;
      void deleteThread(threadId).catch((err) => {
        console.error("Failed to delete thread:", err);
        toast.error("Couldn't delete the thread");
        emitThreadEvent(THREADS_REFRESH_EVENT, {});
      });
    };
    toast.success("Deleted thread", {
      duration: DELETE_UNDO_MS,
      action: {
        label: "Undo",
        onClick: () => {
          undone = true;
          emitThreadEvent(THREADS_REFRESH_EVENT, {});
        },
      },
      onAutoClose: commit,
      onDismiss: commit,
    });
  }, [deleteTarget, isDeleting, onDeleted, closeDelete]);

  return {
    renameTarget,
    deleteTarget,
    renameValue,
    isRenaming,
    isDeleting,
    setRenameValue,
    openRename,
    openDelete,
    closeRename,
    closeDelete,
    submitRename,
    submitDelete,
  };
}
