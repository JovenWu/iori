# Design

Dark product system. Single accent, four-step surface ladder, hairline borders, Inter + JetBrains Mono.

## Tokens

| Role | Value |
|---|---|
| canvas | `#010102` |
| surface-1 / 2 / 3 | `#0f1011` / `#141516` / `#18191a` |
| hairline / strong | `#23252a` / `#34343a` |
| ink / muted / subtle / tertiary | `#f7f8f8` / `#d0d6e0` / `#8a8f98` / `#62666d` |
| primary / hover / focus | `#5e6ad2` / `#828fff` / `#5e69d1` |
| success | `#27a644` |
| danger | `#eb5757` |

## Type

- Display/body: **Inter**, tracking −0.02em on headings, 0 at body.
- Mono: **JetBrains Mono** — tool names, step counts, timestamps, `step n` meta.
- Body 14–16px, captions 12px.

## Shape & layout

- Radius: 8px controls, 12px cards, 16px main chat panel.
- Sidebar: shadcn `variant="inset"` — sidebar on canvas, content floats as a rounded surface-1 panel with a hairline border (the "inset" look).
- Hairlines over shadows; no drop shadows on dark.
- Composer: surface-1 rounded box, hairline border, focus ring in lavender.

## Components

- **AgentStatus (Spark system)** — status line: 18px slot (8-point spark / × / finale), shimmering verb, `step n` side meta, right chevron opens the rail graph (1px rail, 7px done nodes, 6px ghost, 11px ×). Finale `sparkDone` fires once on success only. Keyframes live in `globals.css`; tokens bound to this palette: `--fg`→ink, `--muted`→ink-subtle, `--rail`→ink @ 16%, `--danger`→danger.
- **Messages** — user right-aligned surface-1 bubble; agent rows are plain text with the status block beneath.
- **Buttons** — primary lavender 8px; secondary surface-1 + hairline; ghost for icon actions (lucide, 16–18px).
