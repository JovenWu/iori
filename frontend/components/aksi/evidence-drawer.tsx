"use client";

import { DatabaseIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { type AksiEvent, copy, formatDate, formatFigure } from "@/lib/aksi";
import { useSettings } from "@/lib/settings";

export function EvidenceDrawer({ event }: { event: AksiEvent }) {
  const lang = useSettings().settings.language;
  const t = copy[lang];
  const figures = Object.values(event.figures ?? {});
  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button size="sm" variant="ghost">
          <DatabaseIcon className="size-3.5" />
          {t.sources}
        </Button>
      </SheetTrigger>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle className="font-mono">{event.symbol} · {t.sourcesTitle}</SheetTitle>
          <SheetDescription>
            {t.sourcesDesc}
          </SheetDescription>
        </SheetHeader>
        <div className="space-y-6 px-4 pb-6 text-sm">
          <section>
            <h4 className="mb-2 text-xs font-medium text-muted-foreground">{t.figuresHeading}</h4>
            <div className="divide-y divide-border rounded-lg border border-border">
              {figures.map((f) => (
                <div key={f.key} className="space-y-1 px-3 py-2">
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-mono text-xs text-muted-foreground">{f.key}</span>
                    <span className="font-mono">{formatFigure(f, lang)}</span>
                  </div>
                  <div className="font-mono text-[11px] text-muted-foreground">{f.formula}</div>
                  {Object.keys(f.inputs).length > 0 && (
                    <div className="font-mono text-[11px] text-muted-foreground">
                      {JSON.stringify(f.inputs)}
                    </div>
                  )}
                  {f.gap && <div className="text-[11px] text-destructive">{f.gap}</div>}
                </div>
              ))}
            </div>
          </section>
          {event.findings.length > 0 && (
            <section>
              <h4 className="mb-2 text-xs font-medium text-muted-foreground">{t.contextHeading}</h4>
              <ul className="space-y-2">
                {event.findings.map((f) => (
                  <li key={f.id} className="text-xs">
                    <span className="font-mono text-muted-foreground">{f.source_tool}</span>
                    {f.fetched_at && (
                      <span className="text-muted-foreground"> · {t.fetched} {formatDate(f.fetched_at, lang)}</span>
                    )}
                    <div className="mt-0.5 text-ink-muted">{lang === "id" ? f.text_id : f.text_en}</div>
                  </li>
                ))}
              </ul>
            </section>
          )}
          <section>
            <h4 className="mb-2 text-xs font-medium text-muted-foreground">{t.rawHeading}</h4>
            <pre className="overflow-x-auto rounded-lg bg-secondary p-3 font-mono text-[11px]">
              {JSON.stringify(event.row, null, 2)}
            </pre>
          </section>
          <p className="text-xs text-muted-foreground">
            {t.limitations}
          </p>
        </div>
      </SheetContent>
    </Sheet>
  );
}
