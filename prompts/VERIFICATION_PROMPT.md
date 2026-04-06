# Verification Prompt

Query: {{QUERY}}

Evidence:
{{EVIDENCE}}

Task:
- Check whether every claim in the answer is supported by the evidence.
- If the answer overreaches, mark it as partially grounded or conflicting.
- Return a concise verdict and grounding score.