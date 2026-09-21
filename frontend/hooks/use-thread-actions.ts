"use client";

import { useCallback, useState } from "react";
import { deleteThread, renameThread } from "@/lib/api";

const THREAD_TITLE_CHAR_LIMIT = 100;

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

    try {
      await renameThread(renameTarget.threadId, nextTitle);
      onRenamed(renameTarget.threadId, nextTitle);
      closeRename();
    } catch (err) {
      console.error("Failed to rename thread:", err);
    } finally {
      setIsRenaming(false);
    }
  }, [renameTarget, isRenaming, renameValue, onRenamed, closeRename]);

  const submitDelete = useCallback(async () => {
    if (!deleteTarget || isDeleting) return;

    setIsDeleting(true);

    try {
      await deleteThread(deleteTarget.threadId);
      onDeleted(deleteTarget.threadId);
      closeDelete();
    } catch (err) {
      console.error("Failed to delete thread:", err);
    } finally {
      setIsDeleting(false);
    }
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
