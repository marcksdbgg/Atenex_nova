/* API client for Atenex Nova backend */
import type {
  AnswerRequest,
  AnswerResponse,
  CollectionRebuildResponse,
  Collection,
  CreateCollectionRequest,
  Document,
  DocumentNode,
  EvaluationRunRequest,
  EvaluationRunResponse,
  HealthStatus,
  Job,
  QueryHistoryResponse,
  QuerySearchRequest,
  QuerySearchResponse,
} from '../types/api';

export const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

class ApiClient {
  private base: string;

  constructor(base: string) {
    this.base = base;
  }

  private async request<T>(path: string, options?: RequestInit): Promise<T> {
    const res = await fetch(`${this.base}${path}`, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...options?.headers },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: res.statusText }));
      throw new Error(err.message || `API error: ${res.status}`);
    }
    if (res.status === 204) return undefined as T;
    return res.json();
  }

  /* Health */
  health = () => this.request<HealthStatus>('/health');

  /* Collections */
  listCollections = () => this.request<Collection[]>('/collections');
  getCollection = (id: string) => this.request<Collection>(`/collections/${id}`);
  createCollection = (data: CreateCollectionRequest) =>
    this.request<Collection>('/collections', { method: 'POST', body: JSON.stringify(data) });
  deleteCollection = (id: string) =>
    this.request<void>(`/collections/${id}`, { method: 'DELETE' });

  /* Documents */
  uploadDocument = async (collectionId: string, file: File): Promise<Document> => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${this.base}/collections/${collectionId}/documents`, {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json();
  };
  listCollectionDocuments = (collectionId: string) =>
    this.request<Document[]>(`/collections/${collectionId}/documents`);
  importLocalDocument = (collectionId: string, sourcePath: string, title?: string, mimeType?: string) =>
    this.request<Document>(`/collections/${collectionId}/documents/import`, {
      method: 'POST',
      body: JSON.stringify({
        source_path: sourcePath,
        title,
        mime_type: mimeType,
      }),
    });
  getDocument = (id: string) => this.request<Document>(`/documents/${id}`);
  getDocumentNodes = (id: string) => this.request<DocumentNode[]>(`/documents/${id}/nodes`);

  /* Jobs */
  listJobs = () => this.request<Job[]>('/jobs');
  getJob = (id: string) => this.request<Job>(`/jobs/${id}`);

  /* Queries */
  searchQuery = (data: QuerySearchRequest) =>
    this.request<QuerySearchResponse>('/queries/search', {
      method: 'POST',
      body: JSON.stringify(data),
    });

  answerQuery = (data: AnswerRequest) =>
    this.request<AnswerResponse>('/queries/answer', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  getAnswer = (answerId: string) => this.request<AnswerResponse>(`/answers/${answerId}`);
  listQueryHistory = (collectionId: string, limit = 20) =>
    this.request<QueryHistoryResponse[]>(`/queries/history?collection_id=${encodeURIComponent(collectionId)}&limit=${limit}`);

  exportAnswerMarkdown = (answerId: string) => `${this.base}/answers/${answerId}/export/markdown`;
  exportAnswerPdf = (answerId: string) => `${this.base}/answers/${answerId}/export/pdf`;

  /* Collections hardening */
  rebuildCollection = (collectionId: string) =>
    this.request<CollectionRebuildResponse>(`/collections/${collectionId}/rebuild`, {
      method: 'POST',
    });

  /* Evaluation */
  listEvaluationDatasets = () => this.request<string[]>('/evaluation/datasets');
  runEvaluation = (data: EvaluationRunRequest) =>
    this.request<EvaluationRunResponse>('/evaluation/runs', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  listEvaluationRuns = () => this.request<EvaluationRunResponse[]>('/evaluation/runs');
  getEvaluationReport = (id: string) => this.request<EvaluationRunResponse>(`/evaluation/reports/${id}`);
}

export const api = new ApiClient(API_BASE);
