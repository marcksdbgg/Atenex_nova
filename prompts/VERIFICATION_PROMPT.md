# Verification Prompt

Query: {{QUERY}}

Answer:
{{ANSWER}}

Evidence:
{{EVIDENCE}}

Task:
- Split the answer into material claims.
- For each claim, inspect only the evidence numbers cited next to that claim; a
  citation elsewhere in the answer does not support it.
- Check entailment, contradiction and whether an inference is a reasonable
  synthesis of the cited evidence.
- Treat uncited claims, invalid markers and evidence that is merely topically
  related as unsupported.
- If any material claim overreaches, mark the answer partially verified or
  unverified. If cited evidence conflicts, return conflicting.
- Return exactly these lines:
- VERDICT: verified | partially_verified | unverified | conflicting
- GROUNDING_SCORE: 0.0-1.0
- ISSUES: comma-separated issue codes or none
