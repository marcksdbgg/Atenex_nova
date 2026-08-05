# Global Synthesis Prompt

Query: {{QUERY}}
Plan: {{PLAN}}
Route Reason: {{ROUTE_REASON}}
Language: {{LANGUAGE}}

Evidence:
{{EVIDENCE}}

Instructions:
- Answer the proposition behind the query and reconstruct the corpus-level line of
  reasoning rather than listing search results.
- Identify recurring theses, reasons, qualifications, exceptions and disagreements.
- Distinguish explicit evidence from cross-source inference.
- Cite every material claim with the supporting evidence inline.
- Respond strictly in {{LANGUAGE}}.
- {{UNCERTAINTY_POLICY}}
