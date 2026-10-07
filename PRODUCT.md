# Product

## Register

product

## Users

Hackathon judges and the developer demoing at Sectors Hackathon Indonesia 2026. Context: a live demo and technical review — the interface must make the agent's behavior legible (tool calls, data freshness, reasoning) rather than hide it.

## Product Purpose

A chat client for an agentic IDX market-analysis backend. Users ask questions in English or Indonesian; the agent routes (JEV), calls Sectors tools when needed, streams the answer, and shows its work. Success = a judge can watch a question turn into tool calls, cached data, and a sourced answer in one screen. Information and analysis only — never financial advice, never trade execution.

## Brand Personality

Quiet, precise, technical. Software-craft documentation energy — a dark canvas, one teal accent, dense hairline panels. Three words: calm, exact, engineered.

## Design don'ts

- Warm or bright accents, light-first theming — the accent is teal, the canvas is dark.
- Playful/blobby agent indicators — this product uses the Spark status system.
- Saturated AI-chat gradients, purple-on-purple glassmorphism, glowing orb avatars.
- Marketing-page flourish — this is a working tool, not a landing page.

## Design Principles

- **Work is visible.** Tool calls, freshness, and run state surface as first-class UI, not hidden behind a spinner.
- **One accent, spent carefully.** Lavender marks the brand, the primary action, and focus — never decoration.
- **The dark canvas is the whitespace.** Hierarchy comes from the surface ladder and hairlines, not shadows or color fills.
- **Calm motion.** The Spark system narrates a run in one line; celebration is a single pop at the end, never a loop.

## Accessibility & Inclusion

- WCAG AA contrast on all text; muted tiers only for non-essential meta.
- `prefers-reduced-motion` honored — spark rests lit, shimmer becomes plain text.
- Status line is a `div` with `role="button"` when expandable (`role="status"` otherwise); the live verb sits in `aria-live` territory.
- Keyboard: composer submits on Enter, newline on Shift+Enter; sidebar collapsible via keyboard.
