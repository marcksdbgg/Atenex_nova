# Query Page Overrides

> **PROJECT:** Atenex Nova
> **Generated:** 2026-04-07 09:47:12
> **Page Type:** Workspace

> ⚠️ **IMPORTANT:** Rules in this file override `design-system/atenex-nova/MASTER.md` for the consulta workspace.

---

## Page-Specific Rules

### Layout Overrides

- **Structure:** Two clear zones: a compact conversation list and one primary chat surface. Evidence and technical details are hidden until requested.
- **Order:** 1. Conversation list, 2. Compact collection header, 3. Conversation thread, 4. Composer, 5. Optional sources/details region.
- **Behavior:** Message send should behave like regular chat (`Enter` sends, `Shift+Enter` newline).
- **Scrolling:** Main thread scrolls independently. A completed long answer opens at its beginning; pending output follows the latest message.

### Spacing Overrides

- Use the master spacing scale.
- Keep one divider between navigation, conversation, and composer; do not wrap each subsection in another card.

### Typography Overrides

- Headings use the master heading font.
- Query text, snippets, and metadata should use clear hierarchy with tight labels and relaxed body text.

### Color Overrides

- Preserve the warm cream palette from the master and use one continuous conversation surface.
- Evidence and citations use a separate on-demand region instead of permanent nested cards.

### Component Overrides

- **Chat header:** active collection, document/turn counts, `Ajustes`, and `Ver fuentes` only.
- **Controls:** route and output mode stay behind `Ajustes`.
- **Conversation stream:** a restrained user bubble followed by a plain assistant response; each turn remains selectable to hydrate details.
- **Conversation quality:** hide redundant search-only turns when there is an equivalent answer turn for the same query to avoid noisy duplicated history.
- **Confidence signaling:** show low-confidence warnings with the response; keep routine metadata out of the main stream.
- **Citations & fragments panel:** citation list and top evidence snippets for the selected turn.
- **Technical panel:** context tags, metrics (grounding/citations/evidence/docs), compact context-used summary, recent memory, and export actions.
- **Quality guardrails:** show short alert bullets in the technical panel when the answer lacks citations, has low grounding, or shows language/template mismatch.
- **Pending query state:** never remove the provisional turn because the HTTP transport failed. Reconcile the active chat and hydrate any answer persisted by the backend.

---

## Recommendations

- Keep backend metadata in the optional details region.
- Prefer whitespace and dividers over cards inside cards.
- Keep sources and technical audit closed by default at every breakpoint.
