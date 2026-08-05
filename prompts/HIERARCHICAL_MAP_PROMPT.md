# Hierarchical Map Prompt

Query: {{QUERY}}
Plan: {{PLAN}}
Generation Profile: {{GENERATION_PROFILE}}
Route Reason: {{ROUTE_REASON}}
Language: {{LANGUAGE}}
Evidence group: {{GROUP_LABEL}}

Evidence:
{{EVIDENCE}}

Instructions:
- Analyze only this evidence group; do not answer from prior knowledge.
- Recover the author's thesis, reasons, qualifications, examples and tensions that
  are relevant to the query.
- Separate explicit statements from reasonable inferences and identify missing
  support instead of filling gaps.
- Preserve the original evidence numbers and cite every mapped claim inline.
- Do not write a generic search-result summary and do not repeat metadata.
- Respond strictly in {{LANGUAGE}}.
- {{UNCERTAINTY_POLICY}}

Return a compact analytical memo for the reduce stage, not the final answer.
