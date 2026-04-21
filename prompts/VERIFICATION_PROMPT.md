# Verification Prompt

Query: {{QUERY}}

Answer:
{{ANSWER}}

Evidence:
{{EVIDENCE}}

Task:
- Check whether every claim in the answer is supported by the evidence.
- If the answer overreaches, mark it as partially grounded or conflicting.
- Return exactly these lines:
- VERDICT: verified | partially_verified | unverified | conflicting
- GROUNDING_SCORE: 0.0-1.0
- ISSUES: comma-separated issue codes or none
