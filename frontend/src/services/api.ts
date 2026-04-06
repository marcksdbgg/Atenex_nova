/* API client for Atenex Nova backend */
import type { Collection, CreateCollectionRequest, Document, DocumentNode, Job, HealthStatus } from '../types/api';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

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
  getDocument = (id: string) => this.request<Document>(`/documents/${id}`);
  getDocumentNodes = (id: string) => this.request<DocumentNode[]>(`/documents/${id}/nodes`);

  /* Jobs */
  listJobs = () => this.request<Job[]>('/jobs');
  getJob = (id: string) => this.request<Job>(`/jobs/${id}`);
}

export const api = new ApiClient(API_BASE);
