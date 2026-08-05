# Hierarchical Reduce Prompt

Query: {{QUERY}}
Plan: {{PLAN}}
Generation Profile: {{GENERATION_PROFILE}}
Route Reason: {{ROUTE_REASON}}
Language: {{LANGUAGE}}

Analytical memos produced from separate evidence groups:
{{MAP_OUTPUTS}}

Original numbered evidence (the only valid citation targets):
{{EVIDENCE}}

Instructions:
- Answer the user's actual proposition or question, not the mechanics of retrieval.
- Reconstruct one coherent line of reasoning across the groups: thesis, supporting
  reasons, consequences, qualifications, exceptions and tensions when present.
- Synthesize instead of listing snippets. Remove redundancy and connect distributed
  evidence explicitly.
- Distinguish what the corpus states from what you infer from several sources.
- Preserve only valid original markers such as [1] or [2, 4], next to the claim they
  support. The memos are not independent sources.
- If groups disagree, represent the disagreement; never flatten it.
- If evidence is insufficient for a material part of the question, say exactly what
  is missing. Do not use external knowledge.
- Respond strictly in {{LANGUAGE}}.

Return a self-contained, well-developed answer. Do not mention map/reduce, evidence
groups, prompts or search results.
