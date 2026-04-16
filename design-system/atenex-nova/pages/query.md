# Query Page Overrides

> **PROJECT:** Atenex Nova
> **Generated:** 2026-04-07 09:47:12
> **Page Type:** Workspace

> ⚠️ **IMPORTANT:** Rules in this file override `design-system/atenex-nova/MASTER.md` for the consulta workspace.

---

## Page-Specific Rules

### Layout Overrides

- **Structure:** Notebook-style single chat workspace with one primary conversation pane and one sticky right rail.
- **Order:** 1. Chat header + controls, 2. Conversation thread, 3. Composer fixed in the main pane, 4. Side card for citations/fragments, 5. Side card for technical details.
- **Behavior:** Message send should behave like regular chat (`Enter` sends, `Shift+Enter` newline).
- **Scrolling:** Main thread scrolls independently; side rail stays sticky on desktop and collapses to toggleable stack on mobile.

### Spacing Overrides

- Use the master spacing scale.
- Keep the composer and hero separated from the workspace with one clear vertical gap.

### Typography Overrides

- Headings use the master heading font.
- Query text, snippets, and metadata should use clear hierarchy with tight labels and relaxed body text.

### Color Overrides

- Preserve the warm cream palette from the master, but give the query workspace slightly lighter, higher-contrast surfaces.
- Evidence and citations should use muted surface cards instead of dark blocks.

### Component Overrides

- **Chat header:** compact title, active collection, and session counters.
- **Controls:** keep only essentials visible (collection + panel toggle). Route and output mode stay behind an explicit "opciones avanzadas" toggle.
- **Conversation stream:** regular user/assistant bubble pairs; each turn remains selectable to hydrate side details.
- **Conversation quality:** hide redundant search-only turns when there is an equivalent answer turn for the same query to avoid noisy duplicated history.
- **Confidence signaling:** when grounding is low and citations are weak, show explicit low-confidence labels in the turn chips.
- **Prompt assist:** add lightweight quick-suggestion pills above the thread to help users start focused literary questions faster.
- **Citations & fragments panel:** citation list and top evidence snippets for the selected turn.
- **Technical panel:** context tags, metrics (grounding/citations/evidence/docs), compact context-used summary, recent memory, and export actions.
- **Quality guardrails:** show short alert bullets in the technical panel when the answer lacks citations, has low grounding, or shows language/template mismatch.
- **Pending query state:** while a new request is running, both side cards must show "consulta en curso" messaging for the latest prompt instead of stale previous-turn details.

---

## Recommendations

- Keep backend metadata visible in compact chips or secondary text so the UI stays complete without becoming dense.
- Prefer surface cards with subtle borders and shadows over nested heavy cards.
- Use sticky side rails only on large screens; on smaller screens, let the workspace stack naturally.