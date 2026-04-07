/* API client types matching backend DTOs */

export interface Collection {
  id: string;
  name: string;
  description: string;
  language_profile: string;
  default_generation_profile: string;
  default_retrieval_profile: string;
  created_at: string;
  updated_at: string;
}

export interface CreateCollectionRequest {
  name: string;
  description?: string;
  language_profile?: string;
}

export interface Document {
  id: string;
  collection_id: string;
  title: string;
  mime_type: string;
  source_path?: string | null;
  status: string;
  language: string;
  version: number;
  error_message?: string;
  created_at: string;
  updated_at: string;
}

export interface QueryHistoryItem {
  query_id: string;
  answer_id?: string | null;
  collection_id: string;
  query: string;
  answer?: string | null;
  route_mode: string;
  intent: string;
  language: string;
  verdict?: string | null;
  grounding_score?: number | null;
  created_at: string;
  citations_count: number;
}

export interface DocumentNode {
  id: string;
  document_id: string;
  node_type: string;
  raw_text: string;
  normalized_text: string;
  parent_id?: string;
  page_number?: number;
  order_index: number;
  metadata_json?: string;
}

export interface Job {
  id: string;
  job_type: string;
  target_id: string;
  status: string;
  error?: string;
  retries: number;
  created_at: string;
  started_at?: string;
  completed_at?: string;
}

export interface QuerySearchRequest {
  collection_id: string;
  query: string;
  mode?: string;
}

export interface QueryHit {
  id: string;
  source_type: string;
  source_id: string;
  document_id?: string | null;
  title: string;
  snippet: string;
  score: number;
  rank: number;
  page_number?: number | null;
  metadata?: Record<string, string> | null;
}

export interface Citation {
  id: string;
  answer_id: string;
  document_id: string;
  page_number?: number | null;
  node_id?: string | null;
  char_start?: number | null;
  char_end?: number | null;
  snippet: string;
}

export interface AnswerRequest {
  collection_id: string;
  query: string;
  mode?: string;
  generation_profile?: string;
}

export interface AnswerResponse {
  answer_id: string;
  query_id: string;
  collection_id: string;
  query: string;
  normalized_query: string;
  language: string;
  intent: string;
  route_mode: string;
  plan_type: string;
  answer: string;
  verdict: string;
  grounding_score: number;
  citations: Citation[];
  evidence: QueryHit[];
}

export interface QuerySearchResponse {
  query_id: string;
  collection_id: string;
  query: string;
  normalized_query: string;
  language: string;
  intent: string;
  route_mode: string;
  total_hits: number;
  hits: QueryHit[];
}

export interface QueryHistoryResponse extends QueryHistoryItem {}

export interface CollectionRebuildResponse {
  job_id: string;
  status: string;
}

export interface EvaluationRunRequest {
  collection_id: string;
  dataset_name?: string;
}

export interface EvaluationCase {
  id: string;
  category: string;
  question: string;
  expected_answer: string;
  expected_keywords: string[];
  route_mode: string;
  retrieval_metrics: Record<string, number>;
  answer_metrics: Record<string, number>;
  retrieved: Array<Record<string, string | number>>;
  answer_id?: string | null;
}

export interface EvaluationRunResponse {
  id: string;
  dataset_name: string;
  collection_id: string;
  retrieval_recall_at_k: number;
  retrieval_mrr: number;
  retrieval_ndcg: number;
  answer_grounding_score: number;
  answer_relevance_score: number;
  regression_delta: Record<string, number>;
  summary: Record<string, string | number>;
  created_at: string;
  previous_run_id?: string | null;
  cases?: EvaluationCase[];
}

export interface HealthStatus {
  status: string;
  version: string;
}

export interface ApiError {
  code: string;
  message: string;
}
