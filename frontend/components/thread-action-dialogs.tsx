"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

const THREAD_TITLE_CHAR_LIMIT = 100;

interface ThreadActionDialogsProps {
  renameTargetTitle?: string;
  deleteTargetTitle?: string;
  renameValue?: string;
  isRenaming?: boolean;
  isDeleting: boolean;
  onRenameValueChange?: (value: string) => void;
  onRenameOpenChange?: (open: boolean) => void;
  onDeleteOpenChange: (open: boolean) => void;
  onSubmitRename?: () => void;
  onSubmitDelete: () => void;
  renameInputClassName?: string;
  renameDialogTitle?: string;
  deleteDialogTitle?: string;
  cancelLabel?: string;
  saveLabel?: string;
  deleteLabel?: string;
  deleteDescription?: (title: string) => string;
  preventCloseAutoFocus?: boolean;
}

export function ThreadActionDialogs({
  renameTargetTitle,
  deleteTargetTitle,
  renameValue = "",
  isRenaming = false,
  isDeleting,
  onRenameValueChange,
  onRenameOpenChange,
  onDeleteOpenChange,
  onSubmitRename,
  onSubmitDelete,
  renameInputClassName,
  renameDialogTitle = "Rename thread title",
  deleteDialogTitle = "Delete thread",
  cancelLabel = "Cancel",
  saveLabel = "Save",
  deleteLabel = "Delete",
  deleteDescription = (title) =>
    `Delete "${title}"? This action cannot be undone.`,
  preventCloseAutoFocus = false,
}: ThreadActionDialogsProps) {
  const noop = () => {};
  onRenameValueChange ??= noop;
  onRenameOpenChange ??= noop;
  onSubmitRename ??= noop;
  const dialogContentProps = preventCloseAutoFocus
    ? { onCloseAutoFocus: (e: Event) => e.preventDefault() }
    : {};

  const charCount = renameValue.length;
  const isCharLimitExceeded = charCount > THREAD_TITLE_CHAR_LIMIT;
  const canSubmit =
    !isRenaming && !isCharLimitExceeded && renameValue.trim().length > 0;

  return (
    <>
      <Dialog
        open={Boolean(renameTargetTitle)}
        onOpenChange={(open) => onRenameOpenChange(open)}
      >
        <DialogContent {...dialogContentProps}>
          <DialogHeader>
            <DialogTitle className="text-2xl">{renameDialogTitle}</DialogTitle>
          </DialogHeader>
          <div className="space-y-2">
            <Input
              value={renameValue}
              onChange={(e) => onRenameValueChange(e.target.value)}
              placeholder="Thread title"
              className={renameInputClassName}
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter" && canSubmit) {
                  e.preventDefault();
                  onSubmitRename();
                }
              }}
            />
            <div className="flex items-center justify-between">
              {isCharLimitExceeded ? (
                <p className="text-xs font-medium text-destructive">
                  Character limit exceeded (max {THREAD_TITLE_CHAR_LIMIT})
                </p>
              ) : (
                <p className="text-xs text-muted-foreground"></p>
              )}
              <span
                className={`text-xs font-medium ${
                  isCharLimitExceeded
                    ? "text-destructive"
                    : "text-muted-foreground"
                }`}
              >
                {charCount}/{THREAD_TITLE_CHAR_LIMIT}
              </span>
            </div>
          </div>
          <DialogFooter>
            <Button onClick={onSubmitRename} disabled={!canSubmit}>
              {isRenaming ? "Saving..." : saveLabel}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(deleteTargetTitle)}
        onOpenChange={(open) => onDeleteOpenChange(open)}
      >
        <DialogContent {...dialogContentProps}>
          <DialogHeader>
            <DialogTitle className="text-2xl">{deleteDialogTitle}</DialogTitle>
            <DialogDescription>
              {deleteDescription(deleteTargetTitle || "this thread")}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => onDeleteOpenChange(false)}
              disabled={isDeleting}
            >
              {cancelLabel}
            </Button>
            <Button
              variant="destructive"
              onClick={onSubmitDelete}
              disabled={isDeleting}
            >
              {isDeleting ? "Deleting..." : deleteLabel}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
