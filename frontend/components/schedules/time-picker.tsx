"use client";

import { useEffect, useRef, useState } from "react";
import { ClockIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

const HOURS = Array.from({ length: 24 }, (_, i) => i);
const MINUTES = Array.from({ length: 60 }, (_, i) => i);

function pad(n: number): string {
  return n.toString().padStart(2, "0");
}

function TimeColumn({
  label,
  values,
  selected,
  onSelect,
}: {
  label: string;
  values: number[];
  selected: number;
  onSelect: (v: number) => void;
}) {
  const selectedRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: "center" });
  }, []);

  return (
    <div className="flex flex-col">
      <p className="px-1 pb-1 text-center text-[10px] font-medium tracking-wider text-muted-foreground uppercase">
        {label}
      </p>
      <div className="flex max-h-44 flex-col gap-0.5 overflow-y-auto px-0.5 [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden">
        {values.map((v) => (
          <button
            key={v}
            ref={v === selected ? selectedRef : undefined}
            type="button"
            onClick={() => onSelect(v)}
            className={cn(
              "rounded-md px-3 py-1 font-mono text-xs tabular-nums transition-colors",
              v === selected
                ? "bg-primary/15 font-medium text-primary"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            {pad(v)}
          </button>
        ))}
      </div>
    </div>
  );
}

/** WIB (GMT+7) clock picker — the value is always "HH:MM" 24-hour. */
export function TimePicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [hour, minute] = value.split(":").map((n) => Number(n) || 0);

  return (
    // modal — registers the popover as its own scroll layer so the columns
    // can scroll inside the Dialog's scroll lock.
    <Popover open={open} onOpenChange={setOpen} modal>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          aria-expanded={open}
          className="w-36 justify-between gap-2 font-normal"
        >
          <span className="flex items-center gap-2 font-mono text-sm tabular-nums">
            <ClockIcon className="size-3.5 text-muted-foreground" />
            {pad(hour)}:{pad(minute)}
          </span>
          <span className="text-[10px] text-muted-foreground">GMT+7</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-auto gap-0 p-2">
        <div className="flex items-stretch">
          <TimeColumn
            label="Hour"
            values={HOURS}
            selected={hour}
            onSelect={(h) => onChange(`${pad(h)}:${pad(minute)}`)}
          />
          <div className="mx-1 w-px bg-border" />
          <TimeColumn
            label="Min"
            values={MINUTES}
            selected={minute}
            onSelect={(m) => {
              onChange(`${pad(hour)}:${pad(m)}`);
              setOpen(false);
            }}
          />
        </div>
        <p className="mt-1.5 border-t border-border px-1 pt-1.5 text-[10px] text-muted-foreground">
          Western Indonesia Time · GMT+7
        </p>
      </PopoverContent>
    </Popover>
  );
}
