"use client";

import { useRef, useState } from "react";
import { ArrowUp, Square } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useSettings } from "@/lib/settings";

export function ChatInput({
  running,
  disabled,
  onSend,
  onStop,
}: {
  running: boolean;
  /** Greyed out + cannot submit — e.g. while a thread's history is loading. */
  disabled?: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
}) {
  const { settings } = useSettings();
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  function submit() {
    const text = value.trim();
    if (!text || running || disabled) return;
    onSend(text);
    setValue("");
    if (ref.current) {
      ref.current.style.height = "auto";
      ref.current.focus();
    }
  }

  function autosize(el: HTMLTextAreaElement) {
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }

  return (
    // Hairline + focus ring only — DESIGN.md bars drop shadows on dark.
    <div className="rounded-2xl border border-border bg-card transition-shadow focus-within:ring-2 focus-within:ring-ring/40">
      <Textarea
        ref={ref}
        value={value}
        disabled={disabled}
        aria-label="Message"
        onChange={(e) => {
          setValue(e.target.value);
          autosize(e.target);
        }}
        onKeyDown={(e) => {
          // isComposing: Enter confirms an IME candidate, not a send.
          if (e.key !== "Enter" || e.nativeEvent.isComposing) return;
          const wantsSend = settings.sendWithEnter
            ? !e.shiftKey
            : e.ctrlKey || e.metaKey;
          if (wantsSend) {
            e.preventDefault();
            submit();
          }
        }}
        placeholder="Ask about the IDX — prices, filings, movers, news…"
        rows={1}
        // text-base on mobile — <16px inputs trigger iOS auto-zoom on focus.
        className="max-h-[200px] min-h-0 resize-none border-0 bg-transparent px-3.5 py-3 text-base shadow-none focus-visible:ring-0 md:text-sm"
      />
      <div className="flex items-center justify-between px-3 pb-2.5">
        <span className="font-mono text-[11px] text-muted-foreground">
          {settings.sendWithEnter
            ? "Enter to send · Shift+Enter for a newline"
            : "Ctrl+Enter to send · Enter for a newline"}
        </span>
        {running ? (
          <Button
            size="icon"
            variant="secondary"
            onClick={onStop}
            aria-label="Stop generating"
            className="rounded-full"
          >
            <Square className="size-3.5 fill-current" />
          </Button>
        ) : (
          <Button
            size="icon"
            onClick={submit}
            disabled={!value.trim() || disabled}
            aria-label="Send"
            className="rounded-full"
          >
            <ArrowUp className="size-4" />
          </Button>
        )}
      </div>
    </div>
  );
}
