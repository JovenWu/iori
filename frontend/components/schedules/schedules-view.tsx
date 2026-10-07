"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Loader2Icon,
  PencilIcon,
  PlayIcon,
  PlusIcon,
  TimerIcon,
  Trash2Icon,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  ApiError,
  type ScheduleInput,
  type ScheduleJob,
} from "@/lib/api";
import { TimePicker } from "@/components/schedules/time-picker";
import { useSchedulesStore } from "@/lib/stores/schedules";
import { cn } from "@/lib/utils";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function formatCadence(job: ScheduleJob): string {
  const t = job.run_time.slice(0, 5);
  if (job.frequency === "daily") return `Daily ${t}`;
  if (job.frequency === "weekdays") return `Weekdays ${t}`;
  if (job.frequency === "weekly")
    return `${WEEKDAYS[job.weekday ?? 0]} ${t}`;
  return `Day ${job.day_of_month} · ${t}`;
}

function formatWhen(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function JobCard({
  job,
  busy,
  onToggle,
  onEdit,
  onDelete,
  onRunNow,
}: {
  job: ScheduleJob;
  busy: boolean;
  onToggle: (job: ScheduleJob, enabled: boolean) => void;
  onEdit: (job: ScheduleJob) => void;
  onDelete: (job: ScheduleJob) => void;
  onRunNow: (job: ScheduleJob) => void;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-border bg-card px-4 py-3 transition-opacity",
        !job.enabled && "opacity-60",
      )}
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Link
              href={`/threads/${job.thread_id}`}
              className="truncate text-sm font-medium text-foreground hover:text-primary"
              title="Open the job's thread"
            >
              {job.name}
            </Link>
            <span className="shrink-0 rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 font-mono text-[11px] text-primary">
              {formatCadence(job)}
            </span>
          </div>
          <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
            {job.prompt}
          </p>
          <p className="mt-1.5 text-[11px] text-muted-foreground/70">
            Next run {formatWhen(job.next_run_at)}
            {job.last_run_at && ` · last ran ${formatWhen(job.last_run_at)}`}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Switch
            checked={job.enabled}
            disabled={busy}
            onCheckedChange={(v) => onToggle(job, v)}
            aria-label={job.enabled ? "Pause job" : "Resume job"}
          />
          <Button
            size="icon"
            variant="ghost"
            className="size-8"
            disabled={busy}
            onClick={() => onRunNow(job)}
            title="Run now"
          >
            <PlayIcon className="size-3.5" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            className="size-8"
            disabled={busy}
            onClick={() => onEdit(job)}
            title="Edit"
          >
            <PencilIcon className="size-3.5" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            className="size-8 text-muted-foreground hover:text-destructive"
            disabled={busy}
            onClick={() => onDelete(job)}
            title="Delete (thread stays)"
          >
            <Trash2Icon className="size-3.5" />
          </Button>
        </div>
      </div>
    </div>
  );
}

/** Form fields live here — `key` remounts it per edit target, so state
 * seeds itself from props without a reset effect. */
function JobForm({
  job,
  busy,
  onSubmit,
}: {
  job: ScheduleJob | null; // null = create
  busy: boolean;
  onSubmit: (input: ScheduleInput) => void;
}) {
  const [name, setName] = useState(job?.name ?? "");
  const [prompt, setPrompt] = useState(job?.prompt ?? "");
  const [frequency, setFrequency] = useState<ScheduleInput["frequency"]>(
    job?.frequency ?? "daily",
  );
  const [weekday, setWeekday] = useState(job?.weekday ?? 0);
  const [dayOfMonth, setDayOfMonth] = useState(job?.day_of_month ?? 1);
  const [runTime, setRunTime] = useState(
    (job?.run_time ?? "17:00:00").slice(0, 5),
  );

  const valid = name.trim().length > 0 && prompt.trim().length > 0;

  return (
    <>
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="sched-name">Name</Label>
          <Input
            id="sched-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Nightly holdings scan"
            maxLength={120}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="sched-prompt">Prompt</Label>
          <Textarea
            id="sched-prompt"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Scan my holdings for new corporate actions and summarize what changed"
            rows={3}
            maxLength={8000}
          />
          <p className="text-[11px] text-muted-foreground/70">
            The agent runs this as a full turn on its own thread — tools,
            memory and all.
          </p>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label>Frequency</Label>
          <div className="flex gap-1 rounded-lg border border-border p-1">
            {(["daily", "weekdays", "weekly", "monthly"] as const).map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setFrequency(f)}
                className={cn(
                  "flex-1 rounded-md px-3 py-1.5 text-xs font-medium capitalize transition-colors",
                  frequency === f
                    ? "bg-secondary text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {f}
              </button>
            ))}
          </div>
        </div>
        {frequency === "weekly" && (
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between">
              <Label>Day</Label>
              <span className="text-[10px] text-muted-foreground">GMT+7</span>
            </div>
            <div className="flex gap-1">
              {WEEKDAYS.map((d, i) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => setWeekday(i)}
                  className={cn(
                    "flex-1 rounded-md border px-1 py-1.5 text-[11px] font-medium transition-colors",
                    weekday === i
                      ? "border-primary/50 bg-primary/10 text-primary"
                      : "border-border text-muted-foreground hover:text-foreground",
                  )}
                >
                  {d}
                </button>
              ))}
            </div>
          </div>
        )}
        {frequency === "monthly" && (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="sched-dom">Day of month (1–28)</Label>
            <Input
              id="sched-dom"
              type="number"
              min={1}
              max={28}
              value={dayOfMonth}
              onChange={(e) =>
                setDayOfMonth(
                  Math.max(1, Math.min(28, Number(e.target.value) || 1)),
                )
              }
              className="w-24"
            />
          </div>
        )}
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between">
            <Label>Time</Label>
            <span className="text-[10px] text-muted-foreground">
              WIB · GMT+7
            </span>
          </div>
          <div>
            <TimePicker value={runTime} onChange={setRunTime} />
          </div>
        </div>
      </div>
      <DialogFooter>
        <Button
          disabled={!valid || busy}
          onClick={() =>
            onSubmit({
              name: name.trim(),
              prompt: prompt.trim(),
              frequency,
              run_time: runTime || null,
              weekday: frequency === "weekly" ? weekday : null,
              day_of_month: frequency === "monthly" ? dayOfMonth : null,
            })
          }
        >
          {busy && <Loader2Icon className="size-3.5 animate-spin" />}
          {job ? "Save" : "Create"}
        </Button>
      </DialogFooter>
    </>
  );
}

export function SchedulesView() {
  const jobs = useSchedulesStore((s) => s.jobs);
  const loaded = useSchedulesStore((s) => s.loaded);
  const [busy, setBusy] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<ScheduleJob | null>(null);
  const [runningId, setRunningId] = useState<string | null>(null);

  useEffect(() => {
    void useSchedulesStore.getState().refresh();
  }, []);

  const submit = async (input: ScheduleInput) => {
    setBusy(true);
    try {
      const store = useSchedulesStore.getState();
      if (editing) await store.update(editing.id, input);
      else await store.create(input);
      setDialogOpen(false);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (job: ScheduleJob, enabled: boolean) => {
    try {
      await useSchedulesStore.getState().toggle(job, enabled);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Update failed");
    }
  };

  const remove = async (job: ScheduleJob) => {
    if (!window.confirm(`Delete "${job.name}"? Its thread stays in history.`))
      return;
    setBusy(true);
    try {
      await useSchedulesStore.getState().remove(job.id);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Delete failed");
    } finally {
      setBusy(false);
    }
  };

  const runNow = async (job: ScheduleJob) => {
    setRunningId(job.id);
    try {
      const status = await useSchedulesStore.getState().runNow(job);
      if (status === "fired")
        toast.success(`"${job.name}" is running — see its thread.`);
      else toast(`Couldn't start now (${status}) — try again shortly.`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Run failed");
    } finally {
      setRunningId(null);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-3">
        <SidebarTrigger />
        <h1 className="min-w-0 truncate text-sm font-medium tracking-tight">
          Schedules
        </h1>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <Button
            size="sm"
            onClick={() => {
              setEditing(null);
              setDialogOpen(true);
            }}
          >
            <PlusIcon className="size-3.5" />
            <span className="hidden sm:inline">New schedule</span>
          </Button>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-3 px-4 py-6">
          {!loaded ? (
            <>
              <Skeleton className="h-20 w-full rounded-xl" />
              <Skeleton className="h-20 w-full rounded-xl" />
            </>
          ) : jobs.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-16 text-center">
              <TimerIcon className="size-8 text-muted-foreground/50" />
              <p className="text-sm text-muted-foreground">
                No scheduled jobs yet.
              </p>
              <p className="max-w-sm text-xs text-muted-foreground/70">
                Create one here, or ask the agent — e.g. “every weekday at
                5pm, scan my holdings for corporate actions”.
              </p>
            </div>
          ) : (
            jobs.map((job) => (
              <JobCard
                key={job.id}
                job={job}
                busy={busy || runningId === job.id}
                onToggle={toggle}
                onEdit={(j) => {
                  setEditing(j);
                  setDialogOpen(true);
                }}
                onDelete={remove}
                onRunNow={runNow}
              />
            ))
          )}
        </div>
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {editing ? "Edit schedule" : "New schedule"}
            </DialogTitle>
          </DialogHeader>
          <JobForm
            key={editing?.id ?? "new"}
            job={editing}
            busy={busy}
            onSubmit={submit}
          />
        </DialogContent>
      </Dialog>
    </div>
  );
}
