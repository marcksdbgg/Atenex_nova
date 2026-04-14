# Query Page Overrides

> **PROJECT:** Atenex Nova
> **Generated:** 2026-04-07 09:47:12
> **Page Type:** Workspace

> ⚠️ **IMPORTANT:** Rules in this file override `design-system/atenex-nova/MASTER.md` for the consulta workspace.

---

## Page-Specific Rules

### Layout Overrides

- **Structure:** Three-pane workspace with a stronger center column and sticky side rails.
- **Order:** 1. Hero summary, 2. Composer, 3. Memory rail, 4. Conversation stream, 5. Evidence rail.
- **Scrolling:** Side rails may stay sticky on wide screens; collapse to a single stack below 1280px.

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

- **Hero:** compact title, context chip row, and current collection summary.
- **Composer:** collection, routing mode, and action switch must remain visible together.
- **Memory rail:** recent turns with query, route mode, intent, verdict, grounding score, and citation count.
- **Conversation stream:** each turn is a selectable card with a concise summary and evidence preview.
- **Evidence rail:** active-turn summary, answer panel, page snippets, citations, and export actions.

---

## Recommendations

- Keep backend metadata visible in compact chips or secondary text so the UI stays complete without becoming dense.
- Prefer surface cards with subtle borders and shadows over nested heavy cards.
- Use sticky side rails only on large screens; on smaller screens, let the workspace stack naturally.