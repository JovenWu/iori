"use client"

import { useState, useEffect, useCallback } from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { BrainIcon, Trash2Icon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useAuth } from "@/lib/auth"
import { deleteMemory, listMemories, type Memory } from "@/lib/api"

interface MemoryModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

const memoryDateFormatter = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
})

function formatMemoryDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return memoryDateFormatter.format(date)
}

export function MemoryModal({ open, onOpenChange }: MemoryModalProps) {
  const { token } = useAuth()
  const [memories, setMemories] = useState<Memory[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  // The memory awaiting delete confirmation (null = no confirmation showing).
  const [confirmTarget, setConfirmTarget] = useState<Memory | null>(null)

  const fetchMemories = useCallback(async () => {
    if (!token) return
    setIsLoading(true)
    try {
      const data = await listMemories()
      setMemories(data.memories)
    } catch (err) {
      console.error("Failed to fetch memories:", err)
    } finally {
      setIsLoading(false)
    }
  }, [token])

  // Fetch when modal opens — deferred a tick so the loading state update
  // doesn't run synchronously inside the effect body.
  useEffect(() => {
    if (!open) return
    const timeoutId = window.setTimeout(() => void fetchMemories(), 0)
    return () => window.clearTimeout(timeoutId)
  }, [open, fetchMemories])

  const confirmDelete = async () => {
    if (!confirmTarget) return
    const memoryId = confirmTarget.id
    setDeletingId(memoryId)
    try {
      await deleteMemory(memoryId)
      setMemories((prev) => prev.filter((m) => m.id !== memoryId))
      setConfirmTarget(null)
    } catch (err) {
      console.error("Failed to delete memory:", err)
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <>
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="h-[min(32rem,calc(100vh-2rem))] w-[min(36rem,calc(100vw-2rem))] grid-rows-[auto_minmax(0,1fr)_auto] gap-0 overflow-hidden p-0 sm:max-w-none">
        <DialogHeader className="gap-2 border-b border-border/60 px-6 py-5 pr-12">
          <DialogTitle className="flex items-center gap-2.5">
            <span className="flex size-8 items-center justify-center rounded-lg bg-secondary">
              <BrainIcon className="size-4" />
            </span>
            Memory
            {!isLoading && memories.length > 0 && (
              <span className="rounded-full bg-secondary px-2 py-0.5 text-xs font-medium text-secondary-foreground">
                {memories.length}
              </span>
            )}
          </DialogTitle>
          <DialogDescription>
            Things the assistant has learned about you during conversations.
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-0 overflow-y-auto px-6 py-4">
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full rounded-lg" />
              ))}
            </div>
          ) : memories.length === 0 ? (
            <div className="flex h-full min-h-[14rem] flex-col items-center justify-center gap-2.5 text-center">
              <div className="flex size-11 items-center justify-center rounded-full bg-secondary">
                <BrainIcon className="size-5 text-muted-foreground" />
              </div>
              <p className="text-sm font-medium">No memories yet</p>
              <p className="max-w-64 text-xs leading-relaxed text-muted-foreground">
                As you chat, the assistant saves details like your watchlist,
                sector preferences, and analysis style.
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {memories.map((memory) => {
                const savedAt = formatMemoryDate(
                  memory.updated_at || memory.created_at,
                )
                return (
                <div
                  key={memory.id}
                  className="group flex items-start gap-3 rounded-xl border border-border/50 p-3 transition-colors hover:bg-muted/50"
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-sm leading-relaxed">
                      {memory.content}
                    </p>
                    {savedAt && (
                      <p className="mt-1.5 text-xs text-muted-foreground">
                        Saved {savedAt}
                      </p>
                    )}
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-7 shrink-0 text-muted-foreground transition-opacity hover:text-destructive focus-visible:opacity-100 sm:opacity-0 sm:group-hover:opacity-100"
                    onClick={() => setConfirmTarget(memory)}
                    aria-label="Delete memory"
                  >
                    <Trash2Icon className="size-3.5" />
                  </Button>
                </div>
                )
              })}
            </div>
          )}
        </div>

        <div className="border-t border-border/60 px-6 py-3">
          <p className="text-xs text-muted-foreground">
            Memory updates automatically as you chat. Deleting a memory removes
            it from future conversations.
          </p>
        </div>
      </DialogContent>
    </Dialog>

    {/* Delete confirmation — stacked over the memory list */}
    <Dialog
      open={Boolean(confirmTarget)}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && !deletingId) setConfirmTarget(null)
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="text-2xl">Delete memory</DialogTitle>
          <DialogDescription>
            Delete this memory? This action cannot be undone.
          </DialogDescription>
        </DialogHeader>
        {confirmTarget && (
          <p className="rounded-lg border border-border/50 bg-muted/40 p-3 text-sm leading-relaxed text-muted-foreground">
            {confirmTarget.content}
          </p>
        )}
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => setConfirmTarget(null)}
            disabled={Boolean(deletingId)}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={confirmDelete}
            disabled={Boolean(deletingId)}
          >
            {deletingId ? "Deleting..." : "Delete memory"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
    </>
  )
}
