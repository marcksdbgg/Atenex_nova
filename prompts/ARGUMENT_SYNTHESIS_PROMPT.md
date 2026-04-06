# Argument Synthesis Prompt

Query: {{QUERY}}
Plan: {{PLAN}}

Evidence:
{{EVIDENCE}}

Instructions:
- Separate supporting and contradictory evidence.
- Explain where the corpus agrees and where it conflicts.
- Use inline citations for each assertion.
- {{UNCERTAINTY_POLICY}}