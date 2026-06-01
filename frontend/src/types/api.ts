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
  collection_path?: string;
  status: string;
  language: string;
  version: number;
  error_message?: string;
  created_at: string;
  updated_at: string;
}

export interface ImportLocalFolderResponse {
  imported: number;
  source_folder: string;
  collection_path: string;
  document_ids: string[];
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
  bbox?: Record<string, unknown> | null;
}

export interface Chunk {
  id: string;
  document_id: string;
  text: string;
  summary: string;
  token_count: number;
  node_ids: string[];
  embedding_ref?: string | null;
  sparse_ref?: string | null;
  metadata: Record<string, unknown>;
}

export interface Proposition {
  id: string;
  document_id: string;
  source_chunk_id: string;
  text: string;
  kind: string;
  embedding_ref?: string | null;
}

export interface DocumentPage {
  id: string;
  document_id: string;
  collection_id: string;
  page_number: number;
  title: string;
  text: string;
  is_complex: boolean;
  image_path?: string | null;
  metadata: Record<string, unknown>;
}

export interface DependencyHealth {
  name: string;
  endpoint: string;
  available: boolean;
  detail?: string | null;
}

export interface RuntimeHealthStatus {
  status: string;
  version: string;
  dependencies: DependencyHealth[];
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

export interface PipelineAuditEntry {
  id: string;
  run_id: string;
  entity_type: string;
  entity_id: string;
  pipeline: string;
  stage: string;
  status: string;
  started_at: string;
  completed_at?: string | null;
  duration_ms?: number | null;
  metrics: Record<string, unknown>;
  context: Record<string, unknown>;
}

export interface DocumentEvidenceResponse {
  entity_type: string;
  entity_id: string;
  document: Document;
  jobs: Job[];
  audit_events: PipelineAuditEntry[];
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
  metadata?: Record<string, unknown> | null;
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
  bbox?: Record<string, unknown> | null;
  heading_path?: string[];
  page_asset_path?: string | null;
}

export interface AnswerRequest {
  collection_id: string;
  query: string;
  mode?: string;
  generation_profile?: string;
  chat_id?: string | null;
}

export interface EvidenceTrace {
  route_reason?: string;
  evidence_groups?: Record<string, unknown>;
  excluded_evidence_count?: number;
  selected_count?: number;
  selected_evidence?: QueryHit[];
  generation_attempts?: number;
  [key: string]: unknown;
}

export interface PromptTrace {
  prompt_version?: string;
  template_id?: string;
  template_name?: string;
  variables?: Record<string, unknown>;
  messages?: Array<Record<string, unknown>>;
  [key: string]: unknown;
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
  route_reason: string;
  plan_type: string;
  answer: string;
  verdict: string;
  grounding_score: number;
  prompt_version: string;
  prompt_trace?: PromptTrace | null;
  verification_issues: string[];
  evidence_trace: EvidenceTrace;
  selected_evidence?: QueryHit[];
  citations: Citation[];
  evidence: QueryHit[];
  full_prompt?: string | null;
  input_token_count?: number | null;
  output_token_count?: number | null;
  chat_history_used?: boolean | null;
  chat_history_json?: string | null;
}

export interface QuerySearchResponse {
  query_id: string;
  collection_id: string;
  query: string;
  normalized_query: string;
  language: string;
  intent: string;
  route_mode: string;
  route_reason: string;
  total_hits: number;
  hits: QueryHit[];
}

export type QueryHistoryResponse = QueryHistoryItem;

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
}

export interface EvaluationReportResponse extends EvaluationRunResponse {
  previous_run_id?: string | null;
  cases: EvaluationCase[];
}

export interface HealthStatus {
  status: string;
  version: string;
}

export interface ApiError {
  code: string;
  message: string;
}

export interface Chat {
  id: string;
  collection_id: string;
  title: string;
  created_at: string;
}

export interface ChatMessage {
  id: string;
  chat_id: string;
  role: string;
  content: string;
  created_at: string;
}

export interface CreateChatRequest {
  collection_id: string;
  title: string;
}
