# Hierarchical Map Prompt

Query: {{QUERY}}
Plan: {{PLAN}}
Generation Profile: {{GENERATION_PROFILE}}
Language: {{LANGUAGE}}

Evidence:
{{EVIDENCE}}

Instructions:
- Group evidence by document or theme.
- Produce a structured synthesis with citations inline.
- Respond strictly in {{LANGUAGE}}.
- {{UNCERTAINTY_POLICY}}

Return a mapped synthesis with a few compact paragraphs.