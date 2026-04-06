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
  status: string;
  language: string;
  version: number;
  error_message?: string;
  created_at: string;
  updated_at: string;
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

export interface HealthStatus {
  status: string;
  version: string;
}

export interface ApiError {
  code: string;
  message: string;
}
