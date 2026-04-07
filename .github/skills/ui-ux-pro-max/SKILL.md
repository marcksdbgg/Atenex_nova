---
name: ui-ux-pro-max
description: "Use when designing, reviewing, or implementing polished UI/UX in Atenex Nova with the ui-ux-pro-max prompt workflow, design-system generation, and stack-specific best practices."
---

# ui-ux-pro-max

Use this skill for UI and UX work that needs the curated prompt workflow in [PROMPT.md](../../prompts/ui-ux-pro-max/PROMPT.md).

## Workflow

1. Start with a design-system search.
2. Add a domain search when you need more detail.
3. Add a stack search for implementation guidance.
4. Persist to `design-system/MASTER.md` and page overrides when the UI needs reusable rules.

## Commands

```bash
python3 prompts/ui-ux-pro-max/scripts/search.py "<product_type> <industry> <keywords>" --design-system -p "Project Name"
python3 prompts/ui-ux-pro-max/scripts/search.py "<keyword>" --domain ux
python3 prompts/ui-ux-pro-max/scripts/search.py "<keyword>" --stack react
python3 prompts/ui-ux-pro-max/scripts/search.py "<query>" --design-system --persist -p "Project Name" --page "dashboard"
```

## Use When

- You need a cohesive visual direction for a page or feature.
- You want stack-specific implementation guidance for React, Next.js, Vue, Svelte, or the other bundled stacks.
- You want to keep the design system as reusable repository knowledge instead of re-deriving it each time.

## References

- [PROMPT.md](../../prompts/ui-ux-pro-max/PROMPT.md)
- [scripts/search.py](../../prompts/ui-ux-pro-max/scripts/search.py)
- [scripts/design_system.py](../../prompts/ui-ux-pro-max/scripts/design_system.py)