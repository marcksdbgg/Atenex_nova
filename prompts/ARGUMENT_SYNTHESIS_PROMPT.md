# Argument Synthesis Prompt

Query: {{QUERY}}
Plan: {{PLAN}}
Route Reason: {{ROUTE_REASON}}
Language: {{LANGUAGE}}

Evidence:
{{EVIDENCE}}

Instructions:
- Separate supporting and contradictory evidence.
- Explain where the corpus agrees and where it conflicts.
- Use inline citations for each assertion.
- Respond strictly in {{LANGUAGE}}.
- {{UNCERTAINTY_POLICY}}
