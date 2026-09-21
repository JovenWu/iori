"use client";

import { type ReactNode } from "react";
import { Pencil, Trash2 } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface ThreadActionsMenuProps {
  trigger: ReactNode;
  onRename: () => void;
  onDelete: () => void;
  align?: "start" | "center" | "end";
  showIcons?: boolean;
}

export function ThreadActionsMenu({
  trigger,
  onRename,
  onDelete,
  align = "end",
  showIcons = false,
}: ThreadActionsMenuProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
      <DropdownMenuContent align={align} className="w-36">
        <DropdownMenuItem onSelect={onRename}>
          {showIcons ? <Pencil /> : null}
          Rename
        </DropdownMenuItem>
        <DropdownMenuItem variant="destructive" onSelect={onDelete}>
          {showIcons ? <Trash2 /> : null}
          Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
