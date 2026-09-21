"use client";

/* Spark agent status — one shimmering status line narrates the run; the work
   graph is opt-in behind the chevron. Steps have no total: they arrive as
   dispatched, so the side count reads "step n", never "n/total". */

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

export type ToolStatus = "running" | "done" | "error" | "skipped";

export interface ToolActivity {
  tool: string;
  /** Verb phrase for the status line ("Fetching daily prices…"). */
  label: string;
  /** Optional mono caption next to the label. */
  detail?: string | null;
  status: ToolStatus;
  duration_ms?: number | null;
}

/** The user's open/closed choice, shared across runs — the graph shows only
 * when manually opened; that choice persists to later turns. */
let agentGraphOpen = false;

const SPARK_DWELL_MS = 400; // a step holds ≥400ms before settling — faster is flicker
const SPARK_SETTLE_MS = 900; // reply lands first, the line folds a beat later
const SPARK_MAX_ROWS = 8; // beyond this, fold the oldest rows in the open graph

type StepState = "active" | "done" | "fail" | "skipped";

interface DisplayStep {
  key: string;
  label: string;
  detail: string | null;
  state: StepState;
  durationMs: number | null;
}

/** Ticking elapsed readout. `since` anchors it to a wall-clock start (the
 * server's run started_at) so the number survives remounts — e.g. leaving and
 * returning to the thread mid-run. */
function LiveElapsed({ since }: { since?: number | null }) {
  const [ms, setMs] = useState(0);
  useEffect(() => {
    const t0 = since ?? Date.now();
    const id = window.setInterval(
      () => setMs(Math.max(0, Date.now() - t0)),
      100,
    );
    return () => window.clearInterval(id);
  }, [since]);
  return <>{`${(ms / 1000).toFixed(1)}s`}</>;
}

function Spark({ once = false }: { once?: boolean }) {
  return (
    <span
      className={once ? "t-spark once" : "t-spark"}
      role={once ? undefined : "status"}
      aria-label={once ? undefined : "Working"}
      aria-hidden={once || undefined}
    >
      <i />
      <b />
      <b />
      <b />
    </span>
  );
}

function XMark() {
  return (
    <svg className="xmark" viewBox="0 0 12 12" aria-hidden="true">
      <path d="M3 3l6 6M9 3l-6 6" />
    </svg>
  );
}

/** Status-line text — swaps in place (.15s fade/rise-out, .22s in from below).
 * The surrounding row never moves. */
function SwapText({
  text,
  shimmer,
  doneLabel,
}: {
  text: string;
  shimmer?: boolean;
  doneLabel?: boolean;
}) {
  const [shown, setShown] = useState(text);
  const leaving = shown !== text;

  useEffect(() => {
    if (shown === text) return;
    const t = window.setTimeout(() => setShown(text), 150);
    return () => window.clearTimeout(t);
  }, [text, shown]);

  return (
    <span
      role="status"
      aria-live="polite"
      className={cn(
        "swap",
        shimmer && "shimmer",
        doneLabel && "done-label",
        leaving ? "swap-out" : "swap-in",
      )}
    >
      {shown}
    </span>
  );
}

function StepRow({ step }: { step: DisplayStep }) {
  const live = step.state === "active";
  return (
    <li className="step" data-state={step.state}>
      <span className="rail">
        {live ? (
          <Spark />
        ) : step.state === "fail" ? (
          <XMark />
        ) : (
          <span className={cn("node", step.state === "skipped" && "ghost")} />
        )}
      </span>
      <span className="step-main">
        <span className={cn("step-label", live && "shimmer")}>
          {live ? `${step.label}…` : step.label}
        </span>
        {step.state === "skipped" ? (
          <span className="step-note">not reached</span>
        ) : step.detail ? (
          <span className={cn("step-tool", live && "shimmer")}>
            {step.detail}
          </span>
        ) : null}
      </span>
      <span className="step-time">
        {live ? (
          <LiveElapsed />
        ) : step.durationMs != null ? (
          `${(step.durationMs / 1000).toFixed(1)}s`
        ) : (
          ""
        )}
      </span>
      {step.state === "fail" && step.detail ? (
        <span className="step-detail">{step.detail}</span>
      ) : null}
    </li>
  );
}

interface StepMeta {
  at: number;
  verb: string;
}

/**
 * Agent run status — Spark system. While the turn streams, an 8-point spark
 * rides beside a shimmering verb that swaps in place as steps dispatch; the
 * right edge ticks elapsed seconds plus `step n`. On settle it folds to
 * `n steps · Xs`. The chevron opens a rail-and-node graph of every dispatched
 * step; the open choice persists across runs.
 */
export function AgentStatus({
  tools,
  active,
  failed,
  stopped,
  durationMs,
  runStartedAt,
  onRetry,
}: {
  tools: ToolActivity[];
  /** This turn is still streaming. */
  active: boolean;
  /** The run ended with a stream `error` event. */
  failed?: boolean;
  /** The user stopped generation before it finished. */
  stopped?: boolean;
  /** Whole-turn duration (ms) once the run is over. */
  durationMs?: number;
  /** Server-anchored epoch ms when this run started — keeps the live timer
   * honest across remounts (thread switches, resume). */
  runStartedAt?: number | null;
  onRetry?: () => void;
}) {
  const [open, setOpen] = useState(agentGraphOpen);

  // Dwell-held steps: index → the running verb to keep showing. A step that
  // settles <400ms after appearing stays visually active until the floor
  // passes — faster than that reads as flicker, not speed.
  const [held, setHeld] = useState<ReadonlyMap<number, string>>(new Map());
  // Last running verb — keeps the line narrating during the settle window.
  const [lastVerb, setLastVerb] = useState<string | null>(null);
  // Settle → summary: the reply lands first, the line folds a beat later.
  const [folded, setFolded] = useState(!active);

  // Per-step bookkeeping lives in an effect — render stays pure (no Date.now,
  // no ref reads), all timing is applied asynchronously.
  const metaRef = useRef(new Map<number, StepMeta>());
  useEffect(() => {
    const meta = metaRef.current;
    if (!active) {
      meta.clear();
      return;
    }
    let cancelled = false;
    let timer: number | undefined;
    const apply = () => {
      if (cancelled) return;
      const now = Date.now();
      const nextHeld = new Map<number, string>();
      let wait = Infinity;
      tools.forEach((a, i) => {
        let m = meta.get(i);
        if (!m) {
          m = { at: now, verb: a.label };
          meta.set(i, m);
        }
        if (a.status === "running") {
          m.verb = a.label;
          return;
        }
        const deadline = m.at + SPARK_DWELL_MS;
        if (now < deadline) {
          nextHeld.set(i, m.verb);
          wait = Math.min(wait, deadline - now);
        }
      });
      setHeld((prev) =>
        prev.size === nextHeld.size &&
        [...nextHeld.keys()].every((i) => prev.has(i))
          ? prev
          : nextHeld,
      );
      const running = [...tools].reverse().find((a) => a.status === "running");
      if (running) setLastVerb(running.label);
      if (wait !== Infinity) timer = window.setTimeout(apply, wait);
    };
    queueMicrotask(apply);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [tools, active]);

  // Fold the running line into the summary a beat after the turn ends.
  useEffect(() => {
    if (active) {
      queueMicrotask(() => setFolded(false));
      return;
    }
    const t = window.setTimeout(() => setFolded(true), SPARK_SETTLE_MS);
    return () => window.clearTimeout(t);
  }, [active]);
  const settled = !active && folded;

  const steps: DisplayStep[] = tools.map((a, i) => {
    const heldVerb = active ? held.get(i) : undefined;
    const state: StepState =
      heldVerb !== undefined || a.status === "running"
        ? "active"
        : a.status === "error"
          ? "fail"
          : a.status === "skipped"
            ? "skipped"
            : "done";
    return {
      key: `${a.tool}-${i}`,
      label: heldVerb ?? a.label,
      detail: a.detail ?? null,
      state,
      durationMs: heldVerb !== undefined ? null : (a.duration_ms ?? null),
    };
  });

  const liveStep = [...steps].reverse().find((s) => s.state === "active");
  const nSteps = steps.length;
  const lastFailIdx = steps.reduce(
    (acc, s, i) => (s.state === "fail" ? i : acc),
    -1,
  );
  const runFailed =
    !active && (failed === true || (nSteps > 0 && lastFailIdx === nSteps - 1));
  const phase: "running" | "fail" | "done" =
    active || !settled ? "running" : runFailed ? "fail" : "done";

  // A clean step-less run leaves nothing behind once it settles.
  if (phase !== "running" && nSteps === 0 && !runFailed && !stopped) return null;

  const secs =
    durationMs != null ? ` · ${(Math.max(0, durationMs) / 1000).toFixed(1)}s` : "";
  const lineText =
    phase === "running"
      ? liveStep
        ? `${liveStep.label}${liveStep.detail ? ` ${liveStep.detail}` : ""}…`
        : !active && lastVerb
          ? `${lastVerb}…`
          : "Thinking…"
      : phase === "fail"
        ? `Failed${lastFailIdx >= 0 ? ` at step ${lastFailIdx + 1}` : ""}${secs}`
        : stopped
          ? `Stopped${nSteps ? ` · ${nSteps} step${nSteps === 1 ? "" : "s"}` : ""}${secs}`
          : `Completed ${nSteps} step${nSteps === 1 ? "" : "s"}${secs}`;

  // Long runs: fold the oldest rows, keep the latest three (incl. the live one).
  const visibleSteps =
    steps.length > SPARK_MAX_ROWS ? steps.slice(-3) : steps;
  const foldedCount = steps.length - visibleSteps.length;

  const expandable = nSteps > 0;
  const toggle = () =>
    setOpen((o) => {
      agentGraphOpen = !o;
      return !o;
    });

  return (
    <div className={cn("agent-status work", open && "open")}>
      {phase === "fail" && onRetry ? (
        <button type="button" className="run-retry" onClick={onRetry}>
          Retry run
        </button>
      ) : null}
      {/* The whole line is the disclosure control — but only once a real step
          exists; a step-less ticker renders as a plain row. Always the same
          <div> element type — swapping div↔button when the first step arrived
          remounted the row and zeroed the live timer. */}
      <div
        role={expandable ? "button" : "status"}
        tabIndex={expandable ? 0 : undefined}
        aria-expanded={expandable ? open : undefined}
        onClick={expandable ? toggle : undefined}
        onKeyDown={
          expandable
            ? (e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  toggle();
                }
              }
            : undefined
        }
        className={cn(
          "work-status rounded-sm",
          phase === "fail" && "failed",
          expandable &&
            "cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        )}
      >
        <span className="slot">
          {phase === "running" ? (
            <Spark />
          ) : phase === "fail" ? (
            <XMark />
          ) : (
            <Spark once />
          )}
        </span>
        <SwapText
          text={lineText}
          shimmer={phase === "running"}
          doneLabel={phase !== "running"}
        />
        {phase === "running" ? (
          /* Live proof — seconds tick while the run is in flight; the step
             count rides beside it once a step has been dispatched. */
          <span className="status-side" aria-hidden="true">
            <LiveElapsed since={runStartedAt} />
            {nSteps > 0 ? ` · step ${nSteps}` : ""}
          </span>
        ) : nSteps > 0 ? (
          <span className="status-side">
            {open ? "Hide work" : "Show work"}
          </span>
        ) : null}
        {nSteps > 0 ? (
          <svg className="caret" viewBox="0 0 10 6" aria-hidden="true">
            <path d="M1 1l4 4 4-4" />
          </svg>
        ) : null}
      </div>
      {open && nSteps > 0 ? (
        <ol className="steps">
          {foldedCount > 0 ? (
            <li className="step" data-state="skipped">
              <span className="rail">
                <span className="node ghost" />
              </span>
              <span className="step-main">
                <span className="fold">
                  {foldedCount} earlier step{foldedCount === 1 ? "" : "s"}
                </span>
              </span>
              <span className="step-time" />
            </li>
          ) : null}
          {visibleSteps.map((step) => (
            <StepRow key={step.key} step={step} />
          ))}
        </ol>
      ) : null}
    </div>
  );
}
