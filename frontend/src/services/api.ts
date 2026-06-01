/* API client for Atenex Nova backend */
import type {
  AnswerRequest,
  AnswerResponse,
  Chunk,
  CollectionRebuildResponse,
  Collection,
  CreateCollectionRequest,
  Document,
  DocumentPage,
  DocumentNode,
  DocumentEvidenceResponse,
  EvaluationRunRequest,
  EvaluationReportResponse,
  EvaluationRunResponse,
  HealthStatus,
  ImportLocalFolderResponse,
  Job,
  PipelineAuditEntry,
  Proposition,
  QueryHistoryResponse,
  QuerySearchRequest,
  QuerySearchResponse,
  RuntimeHealthStatus,
  Chat,
  ChatMessage,
  CreateChatRequest,
} from '../types/api';

const DEFAULT_TIMEOUT_MS = 15_000;
const SEARCH_TIMEOUT_MS = 60_000;
const ANSWER_TIMEOUT_MS = 180_000;
const EVALUATION_TIMEOUT_MS = 180_000;

type RequestConfig = RequestInit & {
  timeoutMs?: number;
  timeoutMessage?: string;
};

function resolveApiBase(): string {
  const configured = (import.meta.env.VITE_API_URL as string | undefined)?.trim();
  if (configured) {
    return configured;
  }

  if (typeof window !== 'undefined') {
    const protocol = window.location.protocol || 'http:';
    const hostname = window.location.hostname || 'localhost';
    return `${protocol}//${hostname}:8000`;
  }

  return 'http://localhost:8000';
}

export const API_BASE = resolveApiBase();

function formatApiError(status: number, payload: unknown): string {
  if (payload && typeof payload === 'object') {
    const data = payload as { message?: unknown; detail?: unknown };
    if (typeof data.message === 'string' && data.message.trim()) {
      return data.message;
    }
    if (typeof data.detail === 'string' && data.detail.trim()) {
      return data.detail;
    }
    if (data.detail && typeof data.detail === 'object') {
      const detail = data.detail as { message?: unknown; code?: unknown };
      if (typeof detail.message === 'string' && detail.message.trim()) {
        return detail.message;
      }
      if (typeof detail.code === 'string' && detail.code.trim()) {
        return `Error ${detail.code}`;
      }
    }
  }
  return `API error: ${status}`;
}

class ApiClient {
  private base: string;

  constructor(base: string) {
    this.base = base;
  }

  private async request<T>(path: string, options?: RequestConfig): Promise<T> {
    const timeoutMs = options?.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs);

    const timeoutMessage = options?.timeoutMessage;
    const requestOptions: RequestInit = { ...(options ?? {}) };
    delete (requestOptions as RequestConfig).timeoutMs;
    delete (requestOptions as RequestConfig).timeoutMessage;

    let res: Response;
    try {
      res = await fetch(`${this.base}${path}`, {
        ...requestOptions,
        headers: { 'Content-Type': 'application/json', ...requestOptions.headers },
        signal: controller.signal,
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        const fallbackSeconds = Math.round(timeoutMs / 1000);
        throw new Error(timeoutMessage ?? `La API tardó demasiado en responder (${fallbackSeconds}s).`);
      }
      throw error;
    } finally {
      window.clearTimeout(timeout);
    }

    if (!res.ok) {
      const err = await res.json().catch(() => null);
      throw new Error(formatApiError(res.status, err));
    }
    if (res.status === 204) return undefined as T;
    return res.json();
  }

  private async uploadForm<T>(path: string, formData: FormData): Promise<T> {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), DEFAULT_TIMEOUT_MS);

    let res: Response;
    try {
      res = await fetch(`${this.base}${path}`, {
        method: 'POST',
        body: formData,
        signal: controller.signal,
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw new Error('La subida tardó demasiado en responder.');
      }
      throw error;
    } finally {
      window.clearTimeout(timeout);
    }

    if (!res.ok) {
      const err = await res.json().catch(() => null);
      throw new Error(formatApiError(res.status, err));
    }
    return res.json();
  }

  /* Health */
  health = () => this.request<HealthStatus>('/health');
  healthDependencies = () => this.request<RuntimeHealthStatus>('/health/dependencies');

  /* Collections */
  listCollections = () => this.request<Collection[]>('/collections');
  getCollection = (id: string) => this.request<Collection>(`/collections/${id}`);
  createCollection = (data: CreateCollectionRequest) =>
    this.request<Collection>('/collections', { method: 'POST', body: JSON.stringify(data) });
  deleteCollection = (id: string) =>
    this.request<void>(`/collections/${id}`, { method: 'DELETE' });

  /* Documents */
  uploadDocument = async (
    collectionId: string,
    file: File,
    options: { collectionPath?: string; displayTitle?: string } = {},
  ): Promise<Document> => {
    const formData = new FormData();
    formData.append('file', file);
    if (options.collectionPath) {
      formData.append('collection_path', options.collectionPath);
    }
    if (options.displayTitle) {
      formData.append('display_title', options.displayTitle);
    }
    return this.uploadForm<Document>(`/collections/${collectionId}/documents`, formData);
  };
  listCollectionDocuments = (
    collectionId: string,
    params: { offset?: number; limit?: number; status?: string } = {},
  ) => {
    const query = new URLSearchParams();
    if (params.offset !== undefined) query.set('offset', String(params.offset));
    if (params.limit !== undefined) query.set('limit', String(params.limit));
    if (params.status) query.set('status', params.status);
    const suffix = query.toString() ? `?${query.toString()}` : '';
    return this.request<Document[]>(`/collections/${collectionId}/documents${suffix}`);
  };
  listAllCollectionDocuments = async (collectionId: string, pageSize = 500): Promise<Document[]> => {
    const normalizedPageSize = Math.max(1, Math.min(pageSize, 2000));
    const all: Document[] = [];
    let offset = 0;

    while (true) {
      const batch = await this.listCollectionDocuments(collectionId, {
        offset,
        limit: normalizedPageSize,
      });
      all.push(...batch);
      if (batch.length < normalizedPageSize) break;
      offset += batch.length;
    }

    return all;
  };
  importLocalDocument = (collectionId: string, sourcePath: string, title?: string, mimeType?: string) =>
    this.request<Document>(`/collections/${collectionId}/documents/import`, {
      method: 'POST',
      body: JSON.stringify({
        source_path: sourcePath,
        title,
        mime_type: mimeType,
      }),
    });
  importLocalFolder = (collectionId: string, sourceFolder: string, collectionPath?: string, recursive = true) =>
    this.request<ImportLocalFolderResponse>(
      `/collections/${collectionId}/documents/import-folder`,
      {
        method: 'POST',
        body: JSON.stringify({
          source_folder: sourceFolder,
          collection_path: collectionPath,
          recursive,
        }),
      },
    );
  getDocument = (id: string) => this.request<Document>(`/documents/${id}`);
  getDocumentNodes = (id: string) => this.request<DocumentNode[]>(`/documents/${id}/nodes`);
  getDocumentStructure = (id: string) => this.request<DocumentNode[]>(`/documents/${id}/structure`);
  getDocumentChunks = (id: string) => this.request<Chunk[]>(`/documents/${id}/chunks`);
  getDocumentPropositions = (id: string) => this.request<Proposition[]>(`/documents/${id}/propositions`);
  getDocumentPage = (id: string, pageNumber: number) =>
    this.request<DocumentPage>(`/documents/${id}/pages/${pageNumber}`);

  /* Jobs */
  listJobs = () => this.request<Job[]>('/jobs');
  getJob = (id: string) => this.request<Job>(`/jobs/${id}`);

  /* Observability */
  listPipelineAudit = (params: { entityType?: string; entityId?: string; runId?: string; limit?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.entityType) query.set('entity_type', params.entityType);
    if (params.entityId) query.set('entity_id', params.entityId);
    if (params.runId) query.set('run_id', params.runId);
    if (params.limit) query.set('limit', String(params.limit));
    const suffix = query.toString() ? `?${query.toString()}` : '';
    return this.request<PipelineAuditEntry[]>(`/observability/audit${suffix}`);
  };
  getDocumentEvidence = (documentId: string) =>
    this.request<DocumentEvidenceResponse>(`/observability/documents/${documentId}/evidence`);

  /* Queries */
  searchQuery = (data: QuerySearchRequest) =>
    this.request<QuerySearchResponse>('/queries/search', {
      method: 'POST',
      body: JSON.stringify(data),
      timeoutMs: SEARCH_TIMEOUT_MS,
      timeoutMessage: 'La búsqueda tardó demasiado en responder. Intenta de nuevo o reduce el alcance de la consulta.',
    });

  answerQuery = (data: AnswerRequest) =>
    this.request<AnswerResponse>('/queries/answer', {
      method: 'POST',
      body: JSON.stringify(data),
      timeoutMs: ANSWER_TIMEOUT_MS,
      timeoutMessage: 'La generación de respuesta tardó demasiado. El modelo local puede requerir más tiempo o estar saturado.',
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
    this.request<EvaluationReportResponse>('/evaluation/runs', {
      method: 'POST',
      body: JSON.stringify(data),
      timeoutMs: EVALUATION_TIMEOUT_MS,
      timeoutMessage: 'La evaluación sigue en proceso y tardó más de lo esperado en responder.',
    });
  listEvaluationRuns = () => this.request<EvaluationRunResponse[]>('/evaluation/runs');
  getEvaluationReport = (id: string) => this.request<EvaluationReportResponse>(`/evaluation/reports/${id}`);

  /* Chats */
  listChats = (collectionId: string, limit = 50) =>
    this.request<Chat[]>(`/collections/${encodeURIComponent(collectionId)}/chats?limit=${limit}`);
  createChat = (data: CreateChatRequest) =>
    this.request<Chat>('/chats', { method: 'POST', body: JSON.stringify(data) });
  getChatMessages = (chatId: string, limit = 50) =>
    this.request<ChatMessage[]>(`/chats/${encodeURIComponent(chatId)}/messages?limit=${limit}`);
  deleteChat = (chatId: string) =>
    this.request<void>(`/chats/${encodeURIComponent(chatId)}`, { method: 'DELETE' });
}

export const api = new ApiClient(API_BASE);
