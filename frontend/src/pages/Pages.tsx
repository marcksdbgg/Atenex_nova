/* Page stubs for routing */
import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent, type KeyboardEvent } from 'react';

import { ConversationThread } from '../components/ConversationThread';
import { AnswerPanel } from '../components/AnswerPanel';
import { CitationSidebar } from '../components/CitationSidebar';
import { normalizeAssistantText } from '../components/chatMessageText';
import { EvidenceCard } from '../components/EvidenceCard';
import { PageViewer } from '../components/PageViewer';
import { api } from '../services/api';
import type {
  AnswerResponse,
  Citation,
  Chunk,
  Collection,
  CollectionPipelineStatus,
  Document,
  DocumentNode,
  DocumentPage,
  DocumentEvidenceResponse,
  EvaluationReportResponse,
  EvaluationRunResponse,
  PipelineAuditEntry,
  Proposition,
  QueryHit,
  QueryHistoryResponse,
  QuerySearchResponse,
  Chat,
} from '../types/api';

type UploadStatus = 'queued' | 'uploading' | 'done' | 'error';

type UploadCandidate = {
  file: File;
  relativePath?: string;
};

type UploadQueueItem = {
  id: string;
  file: File;
  status: UploadStatus;
  collectionPath?: string;
  displayTitle?: string;
  message?: string;
  document?: Document;
};

type FolderWizardState = {
  collectionId: string;
  candidates: UploadCandidate[];
  baseCollectionPath: string;
  rootMappings: Record<string, string>;
  preserveHierarchy: boolean;
};

type FileSystemEntryLike = {
  isFile: boolean;
  isDirectory: boolean;
  name: string;
};

type FileSystemFileEntryLike = FileSystemEntryLike & {
  file: (callback: (file: File) => void) => void;
};

type FileSystemDirectoryEntryLike = FileSystemEntryLike & {
  createReader: () => {
    readEntries: (callback: (entries: FileSystemEntryLike[]) => void) => void;
  };
};

type DataTransferItemWithEntry = DataTransferItem & {
  webkitGetAsEntry?: () => FileSystemEntryLike | null;
};

type ChatTurn = {
  id: string;
  queryId: string;
  query: string;
  answerId?: string;
  routeMode: string;
  intent: string;
  language: string;
  createdAt: string;
  kind: 'search' | 'answer';
  answer?: string;
  verdict?: string;
  groundingScore?: number;
  citationsCount?: number;
  hits?: QueryHit[];
  citations?: Citation[];
  totalHits?: number;
  isPending?: boolean;
};

const MAX_VISIBLE_DOCUMENTS = 6;
const INVENTORY_PAGE_SIZE_OPTIONS = [25, 50, 100] as const;
type InventoryStatusFilter = 'all' | 'ready' | 'active' | 'failed';
type AuditStatusFilter = 'all' | 'succeeded' | 'failed' | 'running';

const DOCUMENT_PIPELINE = [
  { key: 'registered', label: 'En cola', detail: 'Documento recibido y pendiente de análisis', tone: 'accent', progress: 12 },
  { key: 'parsed', label: 'Leyendo', detail: 'Extrayendo texto y estructura', tone: 'info', progress: 28 },
  { key: 'normalized', label: 'Normalizando', detail: 'Limpiando y unificando contenido', tone: 'warning', progress: 42 },
  { key: 'segmented', label: 'Segmentando', detail: 'Dividiendo en fragmentos útiles', tone: 'accent', progress: 58 },
  { key: 'embedded', label: 'Vectores', detail: 'Calculando embeddings', tone: 'info', progress: 72 },
  { key: 'indexed', label: 'Indexando', detail: 'Insertando en el índice vectorial', tone: 'warning', progress: 86 },
  { key: 'ready', label: 'Listo', detail: 'Disponible para consulta', tone: 'success', progress: 100 },
  { key: 'failed', label: 'Error', detail: 'Requiere revisión manual', tone: 'error', progress: 100 },
] as const;

const AUDIT_ENTITY_TYPES = ['document', 'query', 'collection', 'answer', 'job'] as const;

const INVENTORY_STATUS_FILTERS: Array<{ value: InventoryStatusFilter; label: string }> = [
  { value: 'all', label: 'Todos' },
  { value: 'ready', label: 'Listos' },
  { value: 'active', label: 'Activos' },
  { value: 'failed', label: 'Errores' },
];

const AUDIT_STATUS_FILTERS: Array<{ value: AuditStatusFilter; label: string }> = [
  { value: 'all', label: 'Todos' },
  { value: 'succeeded', label: 'Succeeded' },
  { value: 'failed', label: 'Failed' },
  { value: 'running', label: 'Running' },
];

function createFileId(file: File): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2)}`;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function normalizeCollectionPath(path: string | undefined | null): string {
  if (!path) return '';
  const normalized = path.replace(/\\/g, '/').trim().replace(/^\/+|\/+$/g, '');
  if (!normalized) return '';
  return normalized
    .split('/')
    .map(part => part.trim())
    .filter(part => part.length > 0 && part !== '.' && part !== '..')
    .join('/');
}

function joinCollectionPaths(...segments: Array<string | undefined | null>): string {
  return segments
    .map(segment => normalizeCollectionPath(segment))
    .filter(Boolean)
    .join('/');
}

function inferRelativePath(file: File): string {
  const webkitRelativePath = (file as File & { webkitRelativePath?: string }).webkitRelativePath;
  return normalizeCollectionPath(webkitRelativePath || file.name) || file.name;
}

function getRootFolder(relativePath: string): string {
  const normalized = normalizeCollectionPath(relativePath);
  if (!normalized.includes('/')) return '';
  return normalized.split('/')[0] ?? '';
}

function getCollectionDisplayTitle(document: Document): string {
  const collectionPath = normalizeCollectionPath(document.collection_path || document.title);
  if (!collectionPath) return document.title;
  const parts = collectionPath.split('/');
  return parts[parts.length - 1] || document.title;
}

async function readDirectoryEntries(entry: FileSystemDirectoryEntryLike): Promise<FileSystemEntryLike[]> {
  const reader = entry.createReader();
  const allEntries: FileSystemEntryLike[] = [];
  while (true) {
    const chunk = await new Promise<FileSystemEntryLike[]>(resolve => {
      reader.readEntries(resolve);
    });
    if (chunk.length === 0) break;
    allEntries.push(...chunk);
  }
  return allEntries;
}

async function collectEntryFiles(entry: FileSystemEntryLike, parentPath = ''): Promise<UploadCandidate[]> {
  if (entry.isFile) {
    const fileEntry = entry as FileSystemFileEntryLike;
    const file = await new Promise<File>(resolve => {
      fileEntry.file(resolve);
    });
    const relativePath = joinCollectionPaths(parentPath, file.name) || file.name;
    return [{ file, relativePath }];
  }

  if (!entry.isDirectory) {
    return [];
  }

  const directoryEntry = entry as FileSystemDirectoryEntryLike;
  const nextPath = joinCollectionPaths(parentPath, entry.name);
  const children = await readDirectoryEntries(directoryEntry);
  const nested = await Promise.all(children.map(child => collectEntryFiles(child, nextPath)));
  return nested.flat();
}

async function collectDroppedCandidates(dataTransfer: DataTransfer): Promise<UploadCandidate[]> {
  const items = Array.from(dataTransfer.items || []);
  const entryItems = items
    .filter(item => item.kind === 'file')
    .map(item => (item as DataTransferItemWithEntry).webkitGetAsEntry?.())
    .filter(Boolean) as FileSystemEntryLike[];

  if (entryItems.length > 0) {
    const nested = await Promise.all(entryItems.map(entry => collectEntryFiles(entry)));
    const files = nested.flat();
    if (files.length > 0) {
      return files;
    }
  }

  return Array.from(dataTransfer.files || []).map(file => ({
    file,
    relativePath: inferRelativePath(file),
  }));
}

function normalizeSearchValue(value: string): string {
  return value.trim().toLowerCase();
}

function formatRelativeDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('es', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function getDocumentPipeline(status: string) {
  return DOCUMENT_PIPELINE.find(step => step.key === status) ?? DOCUMENT_PIPELINE[0];
}

function matchesInventoryStatus(document: Document, filter: InventoryStatusFilter): boolean {
  if (filter === 'all') return true;
  if (filter === 'ready') return document.status === 'ready';
  if (filter === 'failed') return document.status === 'failed';
  return document.status !== 'ready' && document.status !== 'failed';
}

function matchesAuditStatus(status: string, filter: AuditStatusFilter): boolean {
  return filter === 'all' ? true : status === filter;
}

function formatAuditValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return value.length === 0 ? '[]' : value.map(item => formatAuditValue(item)).join(', ');
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function pickDocumentByPriority(documents: Document[]): Document | null {
  return documents.find(document => document.status !== 'failed') ?? documents[0] ?? null;
}
function mapSearchResultToTurn(response: QuerySearchResponse): ChatTurn {
  return {
    id: response.query_id,
    queryId: response.query_id,
    query: response.query,
    routeMode: response.route_mode,
    intent: response.intent,
    language: response.language,
    createdAt: new Date().toISOString(),
    kind: 'search',
    totalHits: response.total_hits,
    hits: response.hits,
    isPending: false,
  };
}

function getAnswerEvidence(response: AnswerResponse): QueryHit[] {
  const selectedEvidence = response.selected_evidence ?? response.evidence_trace.selected_evidence;
  return selectedEvidence && selectedEvidence.length > 0
    ? selectedEvidence
    : response.evidence;
}

function mapAnswerResultToTurn(response: AnswerResponse): ChatTurn {
  const evidence = getAnswerEvidence(response);

  return {
    id: response.query_id,
    queryId: response.query_id,
    query: response.query,
    answerId: response.answer_id,
    routeMode: response.route_mode,
    intent: response.intent,
    language: response.language,
    createdAt: new Date().toISOString(),
    kind: 'answer',
    answer: response.answer,
    verdict: response.verdict,
    groundingScore: response.grounding_score,
    citationsCount: response.citations.length,
    hits: evidence,
    citations: response.citations,
    isPending: false,
  };
}

function createPendingTurn(prompt: string, mode: string, action: 'search' | 'answer'): ChatTurn {
  const now = new Date().toISOString();
  return {
    id: `pending-${now}-${Math.random().toString(36).slice(2)}`,
    queryId: `pending-${now}`,
    query: prompt,
    routeMode: mode,
    intent: action === 'answer' ? 'response_pendiente' : 'evidencia_pendiente',
    language: 'es',
    createdAt: now,
    kind: action,
    totalHits: 0,
    isPending: true,
  };
}

type DashboardGlyphName = 'collections' | 'documents' | 'queries' | 'jobs';

function DashboardGlyph({ name }: { name: DashboardGlyphName }) {
  if (name === 'collections') {
    return (
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M4 4h7v7H4V4Zm9 0h7v7h-7V4ZM4 13h7v7H4v-7Zm9 0h7v7h-7v-7Z" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }

  if (name === 'documents') {
    return (
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M7 3h7l5 5v13H7V3Zm7 0v5h5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }

  if (name === 'queries') {
    return (
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="m21 21-4.4-4.4M10.5 18a7.5 7.5 0 1 1 0-15 7.5 7.5 0 0 1 0 15Z" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M21 12a9 9 0 1 1-2.6-6.3M21 4v6h-6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

type EmptyStateGlyphName = 'grid' | 'refresh' | 'search' | 'target' | 'pulse';

function EmptyStateGlyph({ name }: { name: EmptyStateGlyphName }) {
  if (name === 'grid') {
    return (
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M4 4h7v7H4V4Zm9 0h7v7h-7V4ZM4 13h7v7H4v-7Zm9 0h7v7h-7v-7Z" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }

  if (name === 'refresh') {
    return (
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M21 12a9 9 0 1 1-2.6-6.3M21 4v6h-6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }

  if (name === 'search') {
    return (
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="m21 21-4.4-4.4M10.5 18a7.5 7.5 0 1 1 0-15 7.5 7.5 0 0 1 0 15Z" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }

  if (name === 'target') {
    return (
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <circle cx="12" cy="12" r="8" stroke="currentColor" strokeWidth="1.7" />
        <circle cx="12" cy="12" r="4" stroke="currentColor" strokeWidth="1.7" />
        <circle cx="12" cy="12" r="1.6" fill="currentColor" />
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="8" stroke="currentColor" strokeWidth="1.7" />
      <path d="M12 6v6l4 2" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function DashboardPage() {
  const stats: Array<{ title: string; value: string; icon: DashboardGlyphName; desc: string }> = [
    { title: 'Colecciones', value: '—', icon: 'collections', desc: 'Corpus documentales activos' },
    { title: 'Documentos', value: '—', icon: 'documents', desc: 'Inventario indexado por colección' },
    { title: 'Consultas', value: '—', icon: 'queries', desc: 'Turnos de búsqueda y respuesta' },
    { title: 'Tareas', value: '—', icon: 'jobs', desc: 'Pipeline de procesamiento en segundo plano' },
  ];

  return (
    <div className="dashboard-page animate-fade-in-up">
      <section className="dashboard-hero card">
        <span className="dashboard-hero__eyebrow">Atenex Nova Workspace</span>
        <h2 className="dashboard-hero__title">Centro operativo documental</h2>
        <p className="dashboard-hero__description">
          Organiza colecciones, ejecuta consultas con grounding y monitoriza el pipeline completo desde una sola superficie.
        </p>
      </section>

      <section className="dashboard-stats" aria-label="Estado general">
        {stats.map(stat => (
          <article key={stat.title} className="card dashboard-stat">
            <div className="card__header">
              <span className="dashboard-stat__icon">
                <DashboardGlyph name={stat.icon} />
              </span>
              <span className="badge badge--accent">{stat.value}</span>
            </div>
            <div className="card__title">{stat.title}</div>
            <p className="dashboard-stat__desc">{stat.desc}</p>
          </article>
        ))}
      </section>
    </div>
  );
}

export function CollectionsPage() {
  const [collections, setCollections] = useState<Collection[]>([]);
  const [documentsByCollection, setDocumentsByCollection] = useState<Record<string, Document[]>>({});
  const [pipelineStatusByCollection, setPipelineStatusByCollection] = useState<Record<string, CollectionPipelineStatus>>({});
  const [uploadQueues, setUploadQueues] = useState<Record<string, UploadQueueItem[]>>({});
  const [localSourcePaths, setLocalSourcePaths] = useState<Record<string, string>>({});
  const [localFolderPaths, setLocalFolderPaths] = useState<Record<string, string>>({});
  const [localFolderCollectionPaths, setLocalFolderCollectionPaths] = useState<Record<string, string>>({});
  const [processingUploads, setProcessingUploads] = useState<Record<string, boolean>>({});
  const [selectedTraceDocumentIds, setSelectedTraceDocumentIds] = useState<Record<string, string>>({});
  const [auditEventsByDocument, setAuditEventsByDocument] = useState<Record<string, PipelineAuditEntry[]>>({});
  const [auditLoadingByDocument, setAuditLoadingByDocument] = useState<Record<string, boolean>>({});
  const [auditErrorByDocument, setAuditErrorByDocument] = useState<Record<string, string>>({});
  const [collectionAuditByCollection, setCollectionAuditByCollection] = useState<Record<string, PipelineAuditEntry[]>>({});
  const [collectionAuditLoadingByCollection, setCollectionAuditLoadingByCollection] = useState<Record<string, boolean>>({});
  const [collectionAuditErrorByCollection, setCollectionAuditErrorByCollection] = useState<Record<string, string>>({});
  const [evidenceLoadingByDocument, setEvidenceLoadingByDocument] = useState<Record<string, boolean>>({});
  const [busyCollectionId, setBusyCollectionId] = useState('');
  const [refreshingDocumentsByCollection, setRefreshingDocumentsByCollection] = useState<Record<string, boolean>>({});
  const [importingLocalByCollection, setImportingLocalByCollection] = useState<Record<string, boolean>>({});
  const [importingLocalFolderByCollection, setImportingLocalFolderByCollection] = useState<Record<string, boolean>>({});
  const [inventorySearchByCollection, setInventorySearchByCollection] = useState<Record<string, string>>({});
  const [inventoryStatusByCollection, setInventoryStatusByCollection] = useState<Record<string, InventoryStatusFilter>>({});
  const [inventoryPageByCollection, setInventoryPageByCollection] = useState<Record<string, number>>({});
  const [inventoryPageSizeByCollection, setInventoryPageSizeByCollection] = useState<Record<string, number>>({});
  const [collectionAuditSearchByCollection, setCollectionAuditSearchByCollection] = useState<Record<string, string>>({});
  const [collectionAuditStatusByCollection, setCollectionAuditStatusByCollection] = useState<Record<string, AuditStatusFilter>>({});
  const [traceAuditSearchByCollection, setTraceAuditSearchByCollection] = useState<Record<string, string>>({});
  const [traceAuditStatusByCollection, setTraceAuditStatusByCollection] = useState<Record<string, AuditStatusFilter>>({});
  const [collapsedCollectionLogsByCollection, setCollapsedCollectionLogsByCollection] = useState<Record<string, boolean>>({});
  const [collapsedTraceByCollection, setCollapsedTraceByCollection] = useState<Record<string, boolean>>({});
  const [deletingCollectionId, setDeletingCollectionId] = useState('');
  const [folderWizard, setFolderWizard] = useState<FolderWizardState | null>(null);
  const [message, setMessage] = useState('');
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newCollectionName, setNewCollectionName] = useState('');
  const [newCollectionDescription, setNewCollectionDescription] = useState('');
  const [newCollectionLanguage, setNewCollectionLanguage] = useState('auto');
  const [dragOverCollectionId, setDragOverCollectionId] = useState('');
  const uploadQueuesRef = useRef(uploadQueues);
  const documentsByCollectionRef = useRef(documentsByCollection);
  const processingUploadsRef = useRef(processingUploads);
  const rebuildPollingTimersRef = useRef<Record<string, number>>({});
  const [rebuildPollingByCollection, setRebuildPollingByCollection] = useState<Record<string, boolean>>({});

  useEffect(() => {
    uploadQueuesRef.current = uploadQueues;
  }, [uploadQueues]);

  useEffect(() => {
    documentsByCollectionRef.current = documentsByCollection;
  }, [documentsByCollection]);

  useEffect(() => {
    processingUploadsRef.current = processingUploads;
  }, [processingUploads]);

  useEffect(
    () => () => {
      Object.values(rebuildPollingTimersRef.current).forEach(timerId => window.clearTimeout(timerId));
      rebuildPollingTimersRef.current = {};
    },
    [],
  );

  const totalDocuments = useMemo(
    () => Object.values(documentsByCollection).reduce((count, docs) => count + docs.length, 0),
    [documentsByCollection],
  );

  const activeDocumentCount = useMemo(
    () =>
      Object.values(documentsByCollection).reduce(
        (count, docs) => count + docs.filter(document => document.status !== 'ready' && document.status !== 'failed').length,
        0,
      ),
    [documentsByCollection],
  );

  const realJobQueueCount = useMemo(
    () =>
      Object.values(pipelineStatusByCollection).reduce((count, status) => {
        const pending = status.jobs_by_status.pending ?? 0;
        const running = status.jobs_by_status.running ?? 0;
        return count + pending + running;
      }, 0),
    [pipelineStatusByCollection],
  );

  const queuedFileCount = useMemo(
    () =>
      realJobQueueCount +
      Object.values(uploadQueues).reduce(
        (count, items) => count + items.filter(item => item.status === 'queued' || item.status === 'uploading').length,
        0,
      ),
    [uploadQueues, realJobQueueCount],
  );

  const erroredFileCount = useMemo(
    () => Object.values(uploadQueues).reduce((count, items) => count + items.filter(item => item.status === 'error').length, 0),
    [uploadQueues],
  );

  const hasRebuildPolling = useMemo(
    () => Object.values(rebuildPollingByCollection).some(Boolean),
    [rebuildPollingByCollection],
  );

  useEffect(() => {
    setSelectedTraceDocumentIds(current => {
      let changed = false;
      const next = { ...current };

      for (const collection of collections) {
        const documents = documentsByCollection[collection.id] ?? [];
        if (documents.length === 0) {
          if (next[collection.id]) {
            delete next[collection.id];
            changed = true;
          }
          continue;
        }

        const selectedId = next[collection.id];
        const selectedExists = selectedId ? documents.some(document => document.id === selectedId) : false;
        if (!selectedExists) {
          next[collection.id] = pickDocumentByPriority(documents)?.id ?? documents[0].id;
          changed = true;
        }
      }

      return changed ? next : current;
    });
  }, [collections, documentsByCollection]);

  useEffect(() => {
    let mounted = true;
    api.listCollections()
      .then(async items => {
        if (!mounted) return;
        setCollections(items);
        const documentEntries = await Promise.all(
          items.map(async collection => [collection.id, await api.listAllCollectionDocuments(collection.id)] as const),
        );
        if (mounted) {
          setDocumentsByCollection(Object.fromEntries(documentEntries));
        }
      })
      .catch(() => {
        if (mounted) setMessage('No se pudieron cargar las colecciones.');
      });
    return () => {
      mounted = false;
    };
  }, []);

  const syncCollectionDocuments = async (collectionIds: string[]) => {
    if (collectionIds.length === 0) return;
    const entries = await Promise.all(
      collectionIds.map(async collectionId => [collectionId, await api.listAllCollectionDocuments(collectionId)] as const),
    );
    const pipelineEntries = await Promise.all(
      collectionIds.map(async collectionId => [collectionId, await api.getCollectionPipelineStatus(collectionId)] as const),
    );
    const nextDocuments = Object.fromEntries(entries);
    setDocumentsByCollection(current => ({
      ...current,
      ...nextDocuments,
    }));
    setPipelineStatusByCollection(current => ({
      ...current,
      ...Object.fromEntries(pipelineEntries),
    }));
    setUploadQueues(current => {
      const next = { ...current };
      for (const [collectionId, docs] of entries) {
        next[collectionId] = (next[collectionId] ?? []).map(item => {
          if (!item.document) return item;
          const document = docs.find(candidate => candidate.id === item.document?.id);
          if (!document) return item;
          const pipeline = getDocumentPipeline(document.status);
          return {
            ...item,
            document,
            status: pipeline.key === 'failed' ? 'error' : pipeline.key === 'ready' ? 'done' : 'uploading',
            message: `${pipeline.label} · ${pipeline.detail}`,
          };
        });
      }
      return next;
    });
  };

  const syncCollectionAudits = async (collectionIds: string[]) => {
    if (collectionIds.length === 0) return;
    setCollectionAuditLoadingByCollection(current => {
      const next = { ...current };
      for (const collectionId of collectionIds) {
        next[collectionId] = true;
      }
      return next;
    });
    try {
      const entries = await Promise.all(
        collectionIds.map(async collectionId => [collectionId, await api.listPipelineAudit({ entityType: 'collection', entityId: collectionId, limit: 8 })] as const),
      );

      setCollectionAuditByCollection(current => ({
        ...current,
        ...Object.fromEntries(entries),
      }));

      setCollectionAuditErrorByCollection(current => {
        const next = { ...current };
        for (const [collectionId] of entries) {
          delete next[collectionId];
        }
        return next;
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'No se pudo cargar la bitácora de la colección.';
      setCollectionAuditErrorByCollection(current => {
        const next = { ...current };
        for (const collectionId of collectionIds) {
          next[collectionId] = message;
        }
        return next;
      });
    } finally {
      setCollectionAuditLoadingByCollection(current => {
        const next = { ...current };
        for (const collectionId of collectionIds) {
          delete next[collectionId];
        }
        return next;
      });
    }
  };

  const hasLiveProcessing = useMemo(
    () =>
      Object.values(documentsByCollection).some(docs => docs.some(doc => doc.status !== 'ready' && doc.status !== 'failed')) ||
      Object.values(uploadQueues).some(items => items.some(item => item.status !== 'done' && item.status !== 'error')),
    [documentsByCollection, uploadQueues],
  );

  useEffect(() => {
    if (collections.length === 0) return;
    let mounted = true;

    const runSync = async () => {
      try {
        const collectionIds = collections.map(collection => collection.id);
        await Promise.all([syncCollectionDocuments(collectionIds), syncCollectionAudits(collectionIds)]);
      } catch {
        if (mounted) {
          setMessage('No se pudo actualizar el estado de los documentos.');
        }
      }
    };

    void runSync();
    const intervalMs = hasLiveProcessing || hasRebuildPolling ? 3500 : 12000;
    const timer = window.setInterval(() => {
      void runSync();
    }, intervalMs);

    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, [collections, hasLiveProcessing, hasRebuildPolling]);

  const refreshAllCollections = async () => {
    if (collections.length === 0) return;
    setMessage('');
    try {
      const collectionIds = collections.map(collection => collection.id);
      await Promise.all([syncCollectionDocuments(collectionIds), syncCollectionAudits(collectionIds)]);
      setMessage('Inventario sincronizado.');
    } catch {
      setMessage('No se pudo sincronizar el inventario.');
    }
  };

  const refreshCollectionDocuments = async (collectionId: string, options: { silent?: boolean } = {}) => {
    if (refreshingDocumentsByCollection[collectionId]) return;

    setRefreshingDocumentsByCollection(current => ({ ...current, [collectionId]: true }));
    if (!options.silent) {
      setMessage('');
    }

    try {
      await syncCollectionDocuments([collectionId]);
      void syncCollectionAudits([collectionId]).catch(() => undefined);
      if (!options.silent) {
        setMessage('Inventario actualizado.');
      }
    } catch (error) {
      if (!options.silent) {
        setMessage(error instanceof Error ? error.message : 'No se pudo actualizar el inventario.');
      }
      throw error;
    } finally {
      setRefreshingDocumentsByCollection(current => {
        const next = { ...current };
        delete next[collectionId];
        return next;
      });
    }
  };

  const updateQueueItem = (collectionId: string, itemId: string, patch: Partial<UploadQueueItem>) => {
    setUploadQueues(current => ({
      ...current,
      [collectionId]: (current[collectionId] ?? []).map(item => (item.id === itemId ? { ...item, ...patch } : item)),
    }));
  };

  const handleLocalDocumentImport = async (collectionId: string) => {
    const sourcePath = (localSourcePaths[collectionId] ?? '').trim();
    if (!sourcePath) return;

    if (importingLocalByCollection[collectionId]) return;

    setImportingLocalByCollection(current => ({ ...current, [collectionId]: true }));
    setMessage('');
    try {
      const document = await api.importLocalDocument(collectionId, sourcePath);
      setDocumentsByCollection(current => ({
        ...current,
        [collectionId]: [document, ...(current[collectionId] ?? []).filter(existing => existing.id !== document.id)],
      }));
      setLocalSourcePaths(current => ({ ...current, [collectionId]: '' }));
      setMessage(`Ruta local registrada para ${document.title}. El pipeline continúa sin duplicar bytes.`);
      await syncCollectionDocuments([collectionId]);
      void syncCollectionAudits([collectionId]).catch(() => undefined);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'No se pudo registrar la ruta local.');
    } finally {
      setImportingLocalByCollection(current => {
        const next = { ...current };
        delete next[collectionId];
        return next;
      });
    }
  };

  const loadDocumentAudit = useCallback(async (collectionId: string, document: Document) => {
    if (auditLoadingByDocument[document.id]) return;

    setSelectedTraceDocumentIds(current => ({ ...current, [collectionId]: document.id }));
    setAuditLoadingByDocument(current => ({ ...current, [document.id]: true }));
    setAuditErrorByDocument(current => {
      const next = { ...current };
      delete next[document.id];
      return next;
    });

    try {
      const events = await api.listPipelineAudit({ entityType: 'document', entityId: document.id, limit: 25 });
      setAuditEventsByDocument(current => ({ ...current, [document.id]: events }));
    } catch (error) {
      setAuditErrorByDocument(current => ({
        ...current,
        [document.id]: error instanceof Error ? error.message : 'No se pudo cargar la auditoría.',
      }));
    } finally {
      setAuditLoadingByDocument(current => ({ ...current, [document.id]: false }));
    }
  }, [auditLoadingByDocument]);

  const copyDocumentEvidence = async (document: Document) => {
    if (evidenceLoadingByDocument[document.id]) return;

    setEvidenceLoadingByDocument(current => ({ ...current, [document.id]: true }));
    try {
      const evidence: DocumentEvidenceResponse = await api.getDocumentEvidence(document.id);
      await navigator.clipboard.writeText(JSON.stringify(evidence, null, 2));
      setMessage(`Evidencia JSON copiada para ${document.title}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'No se pudo copiar la evidencia.');
    } finally {
      setEvidenceLoadingByDocument(current => ({ ...current, [document.id]: false }));
    }
  };

  const enqueueUploadBatch = async (collectionId: string, batch: UploadQueueItem[]) => {
    let importSessionId: string | undefined;
    try {
      const importSession = await api.startImportSession(collectionId, {
        source_kind: 'upload_batch',
        discovered_count: batch.length,
      });
      importSessionId = importSession.id;
    } catch {
      importSessionId = undefined;
    }

    setUploadQueues(current => ({
      ...current,
      [collectionId]: [...(current[collectionId] ?? []), ...batch],
    }));
    const collectionName = collections.find(collection => collection.id === collectionId)?.name ?? collectionId;
    setMessage(`Cola ampliada en ${collectionName}: ${batch.length} archivos añadidos.`);
    await processCollectionQueue(collectionId, batch, importSessionId);
  };

  const openFolderWizard = (collectionId: string, candidates: UploadCandidate[]) => {
    const roots = new Set(
      candidates
        .map(candidate => getRootFolder(candidate.relativePath || candidate.file.name))
        .filter(Boolean),
    );

    setFolderWizard({
      collectionId,
      candidates,
      baseCollectionPath: '',
      rootMappings: Object.fromEntries(Array.from(roots).map(root => [root, root])),
      preserveHierarchy: true,
    });
  };

  const finalizeFolderWizard = async () => {
    if (!folderWizard) return;

    const { collectionId, candidates, baseCollectionPath, preserveHierarchy, rootMappings } = folderWizard;
    const normalizedBasePath = normalizeCollectionPath(baseCollectionPath);

    const batch: UploadQueueItem[] = candidates.map(candidate => {
      const fallbackFileName = candidate.file.name;
      const relativePath = normalizeCollectionPath(candidate.relativePath || fallbackFileName) || fallbackFileName;
      const root = getRootFolder(relativePath);

      let scopedPath = relativePath;
      if (root) {
        const mappedRoot = normalizeCollectionPath(rootMappings[root] ?? root);
        if (preserveHierarchy) {
          const rest = relativePath.split('/').slice(1).join('/');
          scopedPath = joinCollectionPaths(mappedRoot, rest || fallbackFileName) || fallbackFileName;
        } else {
          scopedPath = joinCollectionPaths(mappedRoot, fallbackFileName) || fallbackFileName;
        }
      } else if (!preserveHierarchy) {
        scopedPath = fallbackFileName;
      }

      const collectionPath = joinCollectionPaths(normalizedBasePath, scopedPath) || fallbackFileName;
      return {
        id: createFileId(candidate.file),
        file: candidate.file,
        status: 'queued',
        collectionPath,
        displayTitle: collectionPath,
      };
    });

    setFolderWizard(null);
    await enqueueUploadBatch(collectionId, batch);
  };

  const cancelFolderWizard = () => {
    setFolderWizard(null);
    setMessage('Carga por carpeta cancelada.');
  };

  const processCollectionQueue = async (
    collectionId: string,
    initialBatch: UploadQueueItem[] = [],
    importSessionId?: string,
  ) => {
    if (processingUploadsRef.current[collectionId]) return;

    setProcessingUploads(current => ({ ...current, [collectionId]: true }));

    try {
      let remainingInitial = [...initialBatch];
      while (true) {
        const queue = uploadQueuesRef.current[collectionId] ?? [];
        const batch =
          remainingInitial.length > 0
            ? remainingInitial.slice(0, 8)
            : queue.filter(item => item.status === 'queued').slice(0, 8);
        if (remainingInitial.length > 0) {
          remainingInitial = remainingInitial.slice(8);
        }
        if (batch.length === 0) break;

        await Promise.all(
          batch.map(async item => {
            updateQueueItem(collectionId, item.id, { status: 'uploading', message: 'Subiendo al servidor y registrando documento...' });
            try {
              const document = await api.uploadDocument(collectionId, item.file, {
                collectionPath: item.collectionPath,
                displayTitle: item.displayTitle,
                importSessionId,
              });
              updateQueueItem(collectionId, item.id, {
                status: 'done',
                message: 'Documento registrado. Esperando lectura, segmentación e indexación...',
                document,
              });
              setDocumentsByCollection(current => ({
                ...current,
                [collectionId]: [document, ...(current[collectionId] ?? []).filter(existing => existing.id !== document.id)],
              }));
            } catch (error) {
              updateQueueItem(collectionId, item.id, {
                status: 'error',
                message: error instanceof Error ? error.message : 'No se pudo subir el archivo.',
              });
            }
          }),
        );

        await syncCollectionDocuments([collectionId]);
        setUploadQueues(current => ({
          ...current,
          [collectionId]: (current[collectionId] ?? []).filter(item => item.status !== 'done'),
        }));
      }
      if (importSessionId) {
        try {
          await api.finalizeImportSession(importSessionId);
        } catch {
          // Session may auto-finalize when all items are recorded.
        }
      }
    } finally {
      setProcessingUploads(current => ({ ...current, [collectionId]: false }));
    }
  };

  const handleCollectionFiles = async (
    collectionId: string,
    input: FileList | File[] | UploadCandidate[],
  ) => {
    const candidates: UploadCandidate[] =
      Array.isArray(input) && input.length > 0 && 'file' in input[0]
        ? (input as UploadCandidate[])
        : Array.from(input as FileList | File[]).map(file => ({
            file,
            relativePath: inferRelativePath(file),
          }));

    if (candidates.length === 0) return;

    const hasFolderStructure = candidates.some(candidate => normalizeCollectionPath(candidate.relativePath).includes('/'));
    if (hasFolderStructure) {
      openFolderWizard(collectionId, candidates);
      return;
    }

    const batch: UploadQueueItem[] = candidates.map(candidate => {
      const collectionPath = normalizeCollectionPath(candidate.relativePath || candidate.file.name) || candidate.file.name;
      return {
        id: createFileId(candidate.file),
        file: candidate.file,
        status: 'queued',
        collectionPath,
        displayTitle: candidate.file.name,
      };
    });

    await enqueueUploadBatch(collectionId, batch);
  };

  const handleLocalFolderImport = async (collectionId: string) => {
    const sourceFolder = (localFolderPaths[collectionId] ?? '').trim();
    if (!sourceFolder) return;
    if (importingLocalFolderByCollection[collectionId]) return;

    const collectionPath = (localFolderCollectionPaths[collectionId] ?? '').trim();
    setImportingLocalFolderByCollection(current => ({ ...current, [collectionId]: true }));
    setMessage('');
    try {
      const result = await api.importLocalFolder(collectionId, sourceFolder, collectionPath || undefined, true);
      setMessage(
        `Carpeta importada: ${result.discovered_count} descubiertos, ${result.created_count} creados, ${result.deduplicated_count} duplicados${result.failed_count ? `, ${result.failed_count} fallidos` : ''}.`,
      );
      setLocalFolderPaths(current => ({ ...current, [collectionId]: '' }));
      setLocalFolderCollectionPaths(current => ({ ...current, [collectionId]: '' }));
      await syncCollectionDocuments([collectionId]);
      void syncCollectionAudits([collectionId]).catch(() => undefined);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'No se pudo importar la carpeta local.');
    } finally {
      setImportingLocalFolderByCollection(current => {
        const next = { ...current };
        delete next[collectionId];
        return next;
      });
    }
  };

  const handleCreateCollection = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!newCollectionName.trim()) return;
    setCreating(true);
    setMessage('');
    try {
      const created = await api.createCollection({
        name: newCollectionName.trim(),
        description: newCollectionDescription.trim() || undefined,
        language_profile: newCollectionLanguage,
      });
      setCollections(current => [created, ...current]);
      setDocumentsByCollection(current => ({ ...current, [created.id]: [] }));
      setMessage(`Colección creada: ${created.name}`);
      setNewCollectionName('');
      setNewCollectionDescription('');
      setNewCollectionLanguage('auto');
      setShowCreateForm(false);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'No se pudo crear la colección.');
    } finally {
      setCreating(false);
    }
  };

  const clearCollectionState = (collectionId: string) => {
    setDocumentsByCollection(current => {
      const next = { ...current };
      delete next[collectionId];
      return next;
    });
    setUploadQueues(current => {
      const next = { ...current };
      delete next[collectionId];
      return next;
    });
    setLocalSourcePaths(current => {
      const next = { ...current };
      delete next[collectionId];
      return next;
    });
    setLocalFolderPaths(current => {
      const next = { ...current };
      delete next[collectionId];
      return next;
    });
    setLocalFolderCollectionPaths(current => {
      const next = { ...current };
      delete next[collectionId];
      return next;
    });
    setProcessingUploads(current => {
      const next = { ...current };
      delete next[collectionId];
      return next;
    });
    setSelectedTraceDocumentIds(current => {
      const next = { ...current };
      delete next[collectionId];
      return next;
    });
    setCollectionAuditByCollection(current => {
      const next = { ...current };
      delete next[collectionId];
      return next;
    });
    setCollectionAuditLoadingByCollection(current => {
      const next = { ...current };
      delete next[collectionId];
      return next;
    });
    setCollectionAuditErrorByCollection(current => {
      const next = { ...current };
      delete next[collectionId];
      return next;
    });
    setInventorySearchByCollection(current => {
      const next = { ...current };
      delete next[collectionId];
      return next;
    });
    setInventoryStatusByCollection(current => {
      const next = { ...current };
      delete next[collectionId];
      return next;
    });
    setInventoryPageByCollection(current => {
      const next = { ...current };
      delete next[collectionId];
      return next;
    });
    setInventoryPageSizeByCollection(current => {
      const next = { ...current };
      delete next[collectionId];
      return next;
    });
    setCollectionAuditSearchByCollection(current => {
      const next = { ...current };
      delete next[collectionId];
      return next;
    });
    setCollectionAuditStatusByCollection(current => {
      const next = { ...current };
      delete next[collectionId];
      return next;
    });
    setTraceAuditSearchByCollection(current => {
      const next = { ...current };
      delete next[collectionId];
      return next;
    });
    setTraceAuditStatusByCollection(current => {
      const next = { ...current };
      delete next[collectionId];
      return next;
    });
    setCollapsedCollectionLogsByCollection(current => {
      const next = { ...current };
      delete next[collectionId];
      return next;
    });
    setCollapsedTraceByCollection(current => {
      const next = { ...current };
      delete next[collectionId];
      return next;
    });
    setRefreshingDocumentsByCollection(current => {
      const next = { ...current };
      delete next[collectionId];
      return next;
    });
    setImportingLocalByCollection(current => {
      const next = { ...current };
      delete next[collectionId];
      return next;
    });
    setImportingLocalFolderByCollection(current => {
      const next = { ...current };
      delete next[collectionId];
      return next;
    });
    setRebuildPollingByCollection(current => {
      const next = { ...current };
      delete next[collectionId];
      return next;
    });

    const timerId = rebuildPollingTimersRef.current[collectionId];
    if (timerId) {
      window.clearTimeout(timerId);
      delete rebuildPollingTimersRef.current[collectionId];
    }

    setFolderWizard(current => (current?.collectionId === collectionId ? null : current));
  };

  const handleDeleteCollection = async (collection: Collection) => {
    if (deletingCollectionId === collection.id) return;

    const confirmed = window.confirm(
      `Eliminar la colección "${collection.name}" borrará índices, embeddings, auditoría y metadatos. Los archivos de origen no se borran. ¿Continuar?`,
    );
    if (!confirmed) return;

    setDeletingCollectionId(collection.id);
    setMessage('');
    try {
      await api.deleteCollection(collection.id);
      setCollections(current => current.filter(item => item.id !== collection.id));
      clearCollectionState(collection.id);
      setMessage(`Colección eliminada: ${collection.name}. Se conservaron los archivos de origen.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'No se pudo eliminar la colección.');
    } finally {
      setDeletingCollectionId('');
    }
  };

  const handleRebuild = async (collectionId: string) => {
    setBusyCollectionId(collectionId);
    setMessage('');
    try {
      const response = await api.rebuildCollection(collectionId);
      setMessage(`Reprocesado completo en cola: ${response.job_id}`);
      setRebuildPollingByCollection(current => ({ ...current, [collectionId]: true }));
      const previousTimerId = rebuildPollingTimersRef.current[collectionId];
      if (previousTimerId) {
        window.clearTimeout(previousTimerId);
      }
      rebuildPollingTimersRef.current[collectionId] = window.setTimeout(() => {
        setRebuildPollingByCollection(current => {
          const next = { ...current };
          delete next[collectionId];
          return next;
        });
        delete rebuildPollingTimersRef.current[collectionId];
      }, 60000);
      await refreshCollectionDocuments(collectionId, { silent: true });
      void syncCollectionAudits([collectionId]).catch(() => undefined);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'No se pudo lanzar el reprocesado.');
    } finally {
      setBusyCollectionId('');
    }
  };

  useEffect(() => {
    collections.forEach(collection => {
      const documents = documentsByCollection[collection.id] ?? [];
      if (documents.length === 0) return;

      const selectedId = selectedTraceDocumentIds[collection.id];
      const selectedDocument = documents.find(document => document.id === selectedId) ?? pickDocumentByPriority(documents);
      if (!selectedDocument) return;

      if (auditEventsByDocument[selectedDocument.id] || auditLoadingByDocument[selectedDocument.id] || auditErrorByDocument[selectedDocument.id]) {
        return;
      }

      void loadDocumentAudit(collection.id, selectedDocument);
    });
  }, [
    collections,
    documentsByCollection,
    selectedTraceDocumentIds,
    auditEventsByDocument,
    auditLoadingByDocument,
    auditErrorByDocument,
    loadDocumentAudit,
  ]);

  return (
    <div className="animate-fade-in-up">
      <section className="collections-page-header card">
        <div className="collections-page-header__copy">
          <div className="collections-page-header__eyebrow">Corpus y reconstrucción</div>
          <h2 className="collections-page-header__title">Colecciones</h2>
          <p className="collections-page-header__description">Ingesta en lote, control por archivo y reconstrucción completa del corpus con estado visible de cada cola.</p>
        </div>
        <div className="collections-page-header__actions">
          <button className="btn btn-secondary" type="button" onClick={() => void refreshAllCollections()} disabled={collections.length === 0}>Actualizar inventario</button>
          <button className="btn btn-primary" type="button" onClick={() => setShowCreateForm(current => !current)}>+ Nueva colección</button>
        </div>
      </section>

      <div className="collections-page-metrics">
        <div className="collections-page-metric card">
          <span>Colecciones</span>
          <strong>{collections.length}</strong>
        </div>
        <div className="collections-page-metric card">
          <span>Documentos</span>
          <strong>{totalDocuments}</strong>
        </div>
        <div className="collections-page-metric card">
          <span>Activos</span>
          <strong>{activeDocumentCount}</strong>
        </div>
        <div className="collections-page-metric card">
          <span>Cola</span>
          <strong>{queuedFileCount}</strong>
          <small>
            {realJobQueueCount > 0
              ? `${realJobQueueCount} jobs reales`
              : erroredFileCount > 0
                ? `${erroredFileCount} con error`
                : hasRebuildPolling
                  ? 'rebuild en seguimiento'
                  : 'sin actividad'}
          </small>
        </div>
      </div>

      {message ? (
        <div className="collections-page-message card" style={{ marginBottom: 'var(--space-5)' }}>
          <p style={{ color: 'var(--color-text-secondary)' }}>{message}</p>
        </div>
      ) : null}
      {showCreateForm ? (
        <form className="card" style={{ display: 'grid', gap: 'var(--space-4)', marginBottom: 'var(--space-6)' }} onSubmit={handleCreateCollection}>
          <div className="card__header">
            <div className="card__title">Crear colección</div>
            <span className="badge badge--accent">Nuevo</span>
          </div>
          <div style={{ display: 'grid', gap: 'var(--space-4)', gridTemplateColumns: 'minmax(220px, 1.2fr) minmax(220px, 1fr) minmax(180px, 220px)' }}>
            <label style={{ display: 'grid', gap: 'var(--space-2)' }}>
              <span style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Nombre</span>
              <input
                value={newCollectionName}
                onChange={event => setNewCollectionName(event.target.value)}
                placeholder="Memoria legal, soporte, investigación..."
                style={{ width: '100%', padding: 'var(--space-4)', background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-lg)', color: 'var(--color-text-primary)', fontSize: 'var(--font-md)' }}
              />
            </label>
            <label style={{ display: 'grid', gap: 'var(--space-2)' }}>
              <span style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Descripción</span>
              <input
                value={newCollectionDescription}
                onChange={event => setNewCollectionDescription(event.target.value)}
                placeholder="Describe el propósito de la colección"
                style={{ width: '100%', padding: 'var(--space-4)', background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-lg)', color: 'var(--color-text-primary)', fontSize: 'var(--font-md)' }}
              />
            </label>
            <label style={{ display: 'grid', gap: 'var(--space-2)' }}>
              <span style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Idioma</span>
              <select
                value={newCollectionLanguage}
                onChange={event => setNewCollectionLanguage(event.target.value)}
                style={{ width: '100%', padding: 'var(--space-4)', background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-lg)', color: 'var(--color-text-primary)', fontSize: 'var(--font-md)' }}
              >
                <option value="auto">auto</option>
                <option value="es">es</option>
                <option value="en">en</option>
                <option value="pt">pt</option>
              </select>
            </label>
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-3)' }}>
            <button type="button" className="btn" onClick={() => setShowCreateForm(false)}>Cancelar</button>
            <button type="submit" className="btn btn-primary" disabled={creating || !newCollectionName.trim()}>{creating ? 'Creando...' : 'Crear colección'}</button>
          </div>
        </form>
      ) : null}
      {collections.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state__icon" aria-hidden="true"><EmptyStateGlyph name="grid" /></div>
          <div className="empty-state__title">Todavía no hay colecciones</div>
          <p>Crea la primera colección para empezar a construir memoria documental.</p>
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 'var(--space-4)' }}>
          {collections.map(collection => {
            const collectionDocuments = documentsByCollection[collection.id] ?? [];
            const collectionQueue = uploadQueues[collection.id] ?? [];
            const liveDocuments = collectionDocuments.filter(document => document.status !== 'ready' && document.status !== 'failed');
            const readyCount = collectionDocuments.filter(document => document.status === 'ready').length;
            const failedCount = collectionDocuments.filter(document => document.status === 'failed').length;
            const collectionAudit = collectionAuditByCollection[collection.id] ?? [];
            const pipelineStatus = pipelineStatusByCollection[collection.id];
            const collectionAuditLoading = collectionAuditLoadingByCollection[collection.id] ?? false;
            const collectionAuditError = collectionAuditErrorByCollection[collection.id] ?? '';
            const isRebuilding = busyCollectionId === collection.id || rebuildPollingByCollection[collection.id];
            const logsCollapsed = collapsedCollectionLogsByCollection[collection.id] ?? false;
            const traceCollapsed = collapsedTraceByCollection[collection.id] ?? false;
            const activeFolderWizard = folderWizard?.collectionId === collection.id ? folderWizard : null;
            const selectedTraceDocument = collectionDocuments.find(document => document.id === selectedTraceDocumentIds[collection.id]) ?? pickDocumentByPriority(collectionDocuments);
            const selectedTraceAudit = selectedTraceDocument ? auditEventsByDocument[selectedTraceDocument.id] ?? [] : [];
            const selectedTraceLoading = selectedTraceDocument ? auditLoadingByDocument[selectedTraceDocument.id] ?? false : false;
            const selectedTraceError = selectedTraceDocument ? auditErrorByDocument[selectedTraceDocument.id] ?? '' : '';
            const inventorySearch = normalizeSearchValue(inventorySearchByCollection[collection.id] ?? '');
            const inventoryStatus = inventoryStatusByCollection[collection.id] ?? 'all';
            const inventoryPageSize = inventoryPageSizeByCollection[collection.id] ?? INVENTORY_PAGE_SIZE_OPTIONS[0];
            const currentPage = inventoryPageByCollection[collection.id] ?? 1;

            const filteredInventoryDocuments = collectionDocuments
              .filter(document => {
                const matchesStatus = matchesInventoryStatus(document, inventoryStatus);
                if (!matchesStatus) return false;
                if (!inventorySearch) return true;
                const collectionPath = normalizeCollectionPath(document.collection_path || document.title);
                return (
                  document.title.toLowerCase().includes(inventorySearch)
                  || collectionPath.toLowerCase().includes(inventorySearch)
                  || document.mime_type.toLowerCase().includes(inventorySearch)
                  || document.status.toLowerCase().includes(inventorySearch)
                );
              })
              .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());

            const totalInventoryPages = Math.max(1, Math.ceil(filteredInventoryDocuments.length / inventoryPageSize));
            const safeInventoryPage = Math.min(currentPage, totalInventoryPages);
            const pagedInventoryDocuments = filteredInventoryDocuments.slice(
              (safeInventoryPage - 1) * inventoryPageSize,
              safeInventoryPage * inventoryPageSize,
            );

            const collectionAuditSearch = normalizeSearchValue(collectionAuditSearchByCollection[collection.id] ?? '');
            const collectionAuditStatus = collectionAuditStatusByCollection[collection.id] ?? 'all';
            const visibleCollectionAudit = collectionAudit.filter(event => {
              if (!matchesAuditStatus(event.status, collectionAuditStatus)) return false;
              if (!collectionAuditSearch) return true;
              return `${event.stage} ${event.pipeline} ${event.entity_id}`.toLowerCase().includes(collectionAuditSearch);
            });

            const traceAuditSearch = normalizeSearchValue(traceAuditSearchByCollection[collection.id] ?? '');
            const traceAuditStatus = traceAuditStatusByCollection[collection.id] ?? 'all';
            const visibleTraceAudit = selectedTraceAudit.filter(event => {
              if (!matchesAuditStatus(event.status, traceAuditStatus)) return false;
              if (!traceAuditSearch) return true;
              return `${event.stage} ${event.pipeline} ${event.entity_id} ${event.run_id}`.toLowerCase().includes(traceAuditSearch);
            });

            return (
            <article key={collection.id} className="card collection-card" style={{ display: 'grid', gap: 'var(--space-5)' }}>
              <div className="collection-card__header">
                <div>
                  <div className="card__title">{collection.name}</div>
                  <p style={{ color: 'var(--color-text-tertiary)', marginTop: 'var(--space-1)' }}>{collection.description || 'Sin descripción'}</p>
                </div>
                <div className="collection-card__meta">
                  <span className="badge badge--accent">{collection.language_profile}</span>
                  <span className="badge badge--info">{collectionDocuments.length} documentos</span>
                  <span className={`badge badge--${failedCount > 0 ? 'error' : 'success'}`}>{failedCount > 0 ? `${failedCount} con error` : 'estable'}</span>
                  <button
                    className="btn btn-secondary collection-card__action"
                    onClick={() => void handleRebuild(collection.id)}
                    disabled={isRebuilding}
                    type="button"
                  >
                    {isRebuilding ? 'Reprocesando...' : 'Reprocesar corpus'}
                  </button>
                  <button
                    className="btn btn-danger collection-card__action"
                    onClick={() => void handleDeleteCollection(collection)}
                    disabled={deletingCollectionId === collection.id}
                    type="button"
                  >
                    {deletingCollectionId === collection.id ? 'Eliminando...' : 'Eliminar colección'}
                  </button>
                </div>
              </div>
              {pipelineStatus ? (
                <div className="collection-activity-panel card">
                  <div className="card__header">
                    <div>
                      <div className="card__title">Estado real del pipeline</div>
                      <p style={{ color: 'var(--color-text-tertiary)', marginTop: 'var(--space-1)' }}>
                        Jobs y documentos desde la base de datos (no cola local).
                      </p>
                    </div>
                    <span className="badge badge--info">{pipelineStatus.candidate_backend_default}</span>
                  </div>
                  <div style={{ display: 'grid', gap: 'var(--space-3)', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))' }}>
                    <div><strong>{pipelineStatus.jobs_by_status.pending ?? 0}</strong><small> pending</small></div>
                    <div><strong>{pipelineStatus.jobs_by_status.running ?? 0}</strong><small> running</small></div>
                    <div><strong>{pipelineStatus.jobs_by_status.failed ?? 0}</strong><small> failed</small></div>
                    <div><strong>{pipelineStatus.stale_running_jobs}</strong><small> stale</small></div>
                    <div><strong>{readyCount}</strong><small> ready</small></div>
                    <div><strong>{liveDocuments.length}</strong><small> activos</small></div>
                  </div>
                  {pipelineStatus.recent_import_sessions?.length ? (
                    <div style={{ marginTop: 'var(--space-3)' }}>
                      <strong>Import sessions recientes</strong>
                      <ul style={{ margin: 'var(--space-2) 0 0', paddingLeft: 'var(--space-5)' }}>
                        {pipelineStatus.recent_import_sessions.slice(0, 3).map(session => (
                          <li key={session.id}>
                            {session.source_kind}: {session.discovered_count} descubiertos, {session.created_count} creados, {session.deduplicated_count} duplicados
                            {session.failed_count > 0 ? `, ${session.failed_count} fallidos` : ''}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  <p style={{ color: 'var(--color-text-tertiary)', marginTop: 'var(--space-3)', fontSize: 'var(--font-xs)' }}>
                    Logs de colección abajo muestran solo los últimos 8 eventos.
                  </p>
                </div>
              ) : null}
              <div className="collection-activity-panel card">
                <div className="card__header">
                  <div>
                    <div className="card__title">Logs de colección</div>
                    <p style={{ color: 'var(--color-text-tertiary)', marginTop: 'var(--space-1)' }}>Eventos reales del backend para esta colección.</p>
                  </div>
                  <div className="collection-panel-actions">
                    <div className="collection-activity-panel__status">
                      <span className={`collection-live-indicator ${isRebuilding ? 'collection-live-indicator--active' : ''}`} />
                      <span className="badge badge--accent">{visibleCollectionAudit.length}</span>
                    </div>
                    <button
                      className="btn btn-ghost panel-toggle-btn"
                      onClick={() => setCollapsedCollectionLogsByCollection(current => ({ ...current, [collection.id]: !logsCollapsed }))}
                      type="button"
                    >
                      {logsCollapsed ? 'Expandir' : 'Minimizar'}
                    </button>
                  </div>
                </div>
                {logsCollapsed ? null : (
                  <>
                    {isRebuilding ? (
                      <div className="collection-processing-banner">
                        <span className="collection-processing-banner__dot" />
                        <div>
                          <strong>Reprocesando corpus</strong>
                          <p>La colección está reconstruyendo texto, segmentos, embeddings y auditoría en vivo.</p>
                        </div>
                      </div>
                    ) : null}
                    <div className="trace-toolbar">
                      <input
                        className="inventory-search"
                        onChange={event => setCollectionAuditSearchByCollection(current => ({ ...current, [collection.id]: event.target.value }))}
                        placeholder="Buscar por stage, pipeline o entidad..."
                        value={collectionAuditSearchByCollection[collection.id] ?? ''}
                      />
                      <div className="trace-toolbar__filters">
                        <select
                          className="trace-select"
                          onChange={event => setCollectionAuditStatusByCollection(current => ({ ...current, [collection.id]: event.target.value as AuditStatusFilter }))}
                          value={collectionAuditStatusByCollection[collection.id] ?? 'all'}
                        >
                          {AUDIT_STATUS_FILTERS.map(option => (
                            <option key={option.value} value={option.value}>{option.label}</option>
                          ))}
                        </select>
                      </div>
                    </div>
                    {collectionAuditLoading ? (
                      <div className="empty-state" style={{ padding: 'var(--space-4)' }}>
                        <div className="empty-state__icon" aria-hidden="true"><EmptyStateGlyph name="refresh" /></div>
                        <div className="empty-state__title">Cargando logs</div>
                        <p>Actualizando eventos de la colección.</p>
                      </div>
                    ) : collectionAuditError ? (
                      <div style={{ padding: 'var(--space-3)', borderRadius: 'var(--radius-md)', background: 'rgba(239, 68, 68, 0.12)', border: '1px solid rgba(239, 68, 68, 0.35)', color: 'var(--color-error)' }}>
                        {collectionAuditError}
                      </div>
                    ) : visibleCollectionAudit.length === 0 ? (
                      <p style={{ color: 'var(--color-text-tertiary)' }}>No hay eventos para los filtros actuales.</p>
                    ) : (
                      <div className="trace-list trace-list--bounded">
                        {visibleCollectionAudit.map(event => (
                          <article key={event.id} className="trace-entry">
                            <div className="trace-entry__header">
                              <div>
                                <div className="trace-entry__title">{event.stage}</div>
                                <div className="trace-entry__meta">{event.pipeline} · {formatRelativeDate(event.started_at)}</div>
                              </div>
                              <div style={{ display: 'inline-flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
                                <span className={`badge badge--${event.status === 'failed' ? 'error' : event.status === 'succeeded' ? 'success' : 'warning'}`}>{event.status}</span>
                                <span className="badge badge--info">{event.duration_ms !== null && event.duration_ms !== undefined ? `${event.duration_ms.toFixed(1)} ms` : 'sin duración'}</span>
                              </div>
                            </div>
                            <div className="trace-entry__body">
                              <div>Run: {event.run_id}</div>
                              <div>Entidad: {event.entity_type}/{event.entity_id}</div>
                              <details style={{ marginTop: 'var(--space-2)' }}>
                                <summary style={{ cursor: 'pointer' }}>Ver métricas y contexto</summary>
                                <pre className="trace-entry__json">métricas: {formatAuditValue(event.metrics)}{`\n`}contexto: {formatAuditValue(event.context)}</pre>
                              </details>
                            </div>
                          </article>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>
              <div className="collection-ingest-grid">
                <section className="collection-ingest-primary">
                  <div
                    className={`collection-dropzone ${dragOverCollectionId === collection.id ? 'collection-dropzone--active' : ''}`}
                    onDragOver={event => {
                      event.preventDefault();
                      setDragOverCollectionId(collection.id);
                    }}
                    onDragLeave={() => setDragOverCollectionId(current => (current === collection.id ? '' : current))}
                    onDrop={async event => {
                      event.preventDefault();
                      setDragOverCollectionId('');
                      const candidates = await collectDroppedCandidates(event.dataTransfer);
                      await handleCollectionFiles(collection.id, candidates);
                    }}
                  >
                    <div className="collection-dropzone__copy">
                      <span className="collection-dropzone__eyebrow">Carga masiva</span>
                      <h3 className="collection-dropzone__title">Arrastra el lote completo aquí</h3>
                      <div className="collection-dropzone__actions">
                        <label className="btn btn-primary collection-dropzone__button" htmlFor={`upload-${collection.id}`}>
                          Seleccionar archivos
                        </label>
                        <label className="btn btn-secondary collection-dropzone__button" htmlFor={`upload-folder-${collection.id}`}>
                          Seleccionar carpeta
                        </label>
                      </div>

                      {activeFolderWizard ? (
                        <div className="folder-wizard">
                          <div className="folder-wizard__header">
                            <strong>Asistente de carpetas</strong>
                            <span className="badge badge--accent">{activeFolderWizard.candidates.length} archivos</span>
                          </div>
                          <p className="folder-wizard__description">Mapea carpetas origen a carpetas destino dentro de esta colección antes de subir.</p>
                          <label className="folder-wizard__field">
                            <span>Ruta base en colección (opcional)</span>
                            <input
                              className="collection-dropzone__local-input"
                              value={activeFolderWizard.baseCollectionPath}
                              onChange={event => {
                                const value = event.target.value;
                                setFolderWizard(current => {
                                  if (!current || current.collectionId !== collection.id) return current;
                                  return { ...current, baseCollectionPath: value };
                                });
                              }}
                              placeholder="ej: legal/2026"
                            />
                          </label>
                          {Object.keys(activeFolderWizard.rootMappings).length > 0 ? (
                            <div className="folder-wizard__roots">
                              {Object.entries(activeFolderWizard.rootMappings).map(([root, mapped]) => (
                                <label className="folder-wizard__field" key={root}>
                                  <span>{root}</span>
                                  <input
                                    className="collection-dropzone__local-input"
                                    value={mapped}
                                    onChange={event => {
                                      const value = event.target.value;
                                      setFolderWizard(current => {
                                        if (!current || current.collectionId !== collection.id) return current;
                                        return {
                                          ...current,
                                          rootMappings: {
                                            ...current.rootMappings,
                                            [root]: value,
                                          },
                                        };
                                      });
                                    }}
                                    placeholder="Subcarpeta destino"
                                  />
                                </label>
                              ))}
                            </div>
                          ) : null}
                          <label className="folder-wizard__toggle">
                            <input
                              checked={activeFolderWizard.preserveHierarchy}
                              onChange={event => {
                                const checked = event.target.checked;
                                setFolderWizard(current => {
                                  if (!current || current.collectionId !== collection.id) return current;
                                  return { ...current, preserveHierarchy: checked };
                                });
                              }}
                              type="checkbox"
                            />
                            <span>Conservar jerarquía interna</span>
                          </label>
                          <div className="folder-wizard__actions">
                            <button className="btn btn-ghost" type="button" onClick={cancelFolderWizard}>Cancelar</button>
                            <button className="btn btn-primary" type="button" onClick={() => void finalizeFolderWizard()}>Aplicar y subir</button>
                          </div>
                        </div>
                      ) : null}

                      <div className="collection-dropzone__local">
                        <label className="collection-dropzone__local-label">
                          <span className="collection-dropzone__local-caption">
                            Importar archivo local
                          </span>
                          <input
                            value={localSourcePaths[collection.id] ?? ''}
                            onChange={event => setLocalSourcePaths(current => ({ ...current, [collection.id]: event.target.value }))}
                            placeholder="C:\\ruta\\al\\archivo.txt o ./storage/uploads/archivo.txt"
                            className="collection-dropzone__local-input"
                          />
                        </label>
                        <div className="collection-dropzone__local-actions">
                          <button
                            className="btn btn-secondary"
                            type="button"
                            onClick={() => void handleLocalDocumentImport(collection.id)}
                            disabled={!localSourcePaths[collection.id]?.trim() || importingLocalByCollection[collection.id]}
                          >
                            {importingLocalByCollection[collection.id] ? 'Registrando...' : 'Registrar ruta local'}
                          </button>
                          <span className="collection-dropzone__helper">
                            Reutiliza el archivo ya existente en disco y sólo encola el pipeline.
                          </span>
                        </div>
                      </div>

                      <div className="collection-dropzone__local">
                        <label className="collection-dropzone__local-label">
                          <span className="collection-dropzone__local-caption">
                            Importar carpeta local
                          </span>
                          <input
                            value={localFolderPaths[collection.id] ?? ''}
                            onChange={event => setLocalFolderPaths(current => ({ ...current, [collection.id]: event.target.value }))}
                            placeholder="C:\\ruta\\a\\carpeta"
                            className="collection-dropzone__local-input"
                          />
                        </label>
                        <label className="collection-dropzone__local-label">
                          <span className="collection-dropzone__local-caption">Subcarpeta destino (opcional)</span>
                          <input
                            value={localFolderCollectionPaths[collection.id] ?? ''}
                            onChange={event => setLocalFolderCollectionPaths(current => ({ ...current, [collection.id]: event.target.value }))}
                            placeholder="ej: litigios/2026"
                            className="collection-dropzone__local-input"
                          />
                        </label>
                        <div className="collection-dropzone__local-actions">
                          <button
                            className="btn btn-secondary"
                            type="button"
                            onClick={() => void handleLocalFolderImport(collection.id)}
                            disabled={!localFolderPaths[collection.id]?.trim() || importingLocalFolderByCollection[collection.id]}
                          >
                            {importingLocalFolderByCollection[collection.id] ? 'Importando carpeta...' : 'Importar carpeta local'}
                          </button>
                          <span className="collection-dropzone__helper">
                            Registra toda la carpeta y conserva la estructura interna sin mover ni duplicar archivos origen.
                          </span>
                        </div>
                      </div>
                    </div>

                    <input
                      id={`upload-${collection.id}`}
                      className="collection-dropzone__input"
                      type="file"
                      multiple
                      accept="*/*"
                      onChange={event => {
                        const files = event.target.files;
                        if (!files || files.length === 0) return;
                        void handleCollectionFiles(collection.id, files);
                        event.target.value = '';
                      }}
                    />
                    <input
                      id={`upload-folder-${collection.id}`}
                      className="collection-dropzone__input"
                      type="file"
                      multiple
                      {...({ webkitdirectory: '', directory: '' } as Record<string, string>)}
                      onChange={event => {
                        const files = event.target.files;
                        if (!files || files.length === 0) return;
                        void handleCollectionFiles(collection.id, files);
                        event.target.value = '';
                      }}
                    />
                  </div>

                  <div className="collection-summary-strip">
                    <div>
                      <span>Documentos</span>
                      <strong>{collectionDocuments.length}</strong>
                    </div>
                    <div>
                      <span>Indexados</span>
                      <strong>{readyCount}</strong>
                    </div>
                    <div>
                      <span>Procesando</span>
                      <strong>{liveDocuments.length}</strong>
                    </div>
                    <div>
                      <span>Con error</span>
                      <strong>{failedCount}</strong>
                    </div>
                  </div>

                  {collectionQueue.length > 0 ? (
                    <div className="collection-queue-panel card" style={{ background: 'var(--color-bg-primary)', borderColor: 'var(--color-border)' }}>
                      <div className="card__header">
                        <div>
                          <div className="card__title">Cola viva</div>
                          <p style={{ color: 'var(--color-text-tertiary)', marginTop: 'var(--space-1)' }}>Se muestra solo mientras existan archivos en tránsito.</p>
                        </div>
                        <span className="badge badge--accent">{collectionQueue.length}</span>
                      </div>

                      <div style={{ display: 'grid', gap: 'var(--space-3)' }}>
                        {collectionQueue.map(item => {
                          const pipeline = item.document ? getDocumentPipeline(item.document.status) : null;
                          const progress = pipeline?.progress ?? (item.status === 'done' ? 100 : item.status === 'error' ? 100 : item.status === 'uploading' ? 24 : 8);
                          const tone = item.status === 'done' ? 'success' : item.status === 'error' ? 'error' : item.status === 'uploading' ? 'warning' : 'accent';
                          return (
                            <article key={item.id} className="queue-item">
                              <div className="queue-item__top">
                                <div className="queue-item__title-wrap">
                                  <div className="queue-item__title">{item.file.name}</div>
                                  <div className="queue-item__meta">{item.collectionPath ? `${item.collectionPath} · ` : ''}{formatBytes(item.file.size)} · {item.file.type || 'tipo desconocido'}</div>
                                </div>
                                <span className={`badge badge--${tone}`}>{pipeline?.label ?? (item.status === 'uploading' ? 'Subiendo' : item.status === 'error' ? 'Error' : 'En cola')}</span>
                              </div>
                              <div className="progress-track" aria-label={`Progreso ${item.file.name}`}>
                                <div className={`progress-fill progress-fill--${tone}`} style={{ width: `${progress}%` }} />
                              </div>
                              <div className="queue-item__bottom">
                                <span className="queue-item__stage">{pipeline?.detail ?? (item.status === 'uploading' ? 'Registrando documento' : item.status === 'error' ? 'Falló la subida' : 'Esperando procesamiento')}</span>
                                <span className="queue-item__status">{item.document?.status ?? item.status}</span>
                              </div>
                              {item.message ? <p className="queue-item__message">{item.message}</p> : null}
                            </article>
                          );
                        })}
                      </div>
                    </div>
                  ) : null}

                  <section className="collection-trace-panel card">
                    <div className="card__header">
                      <div>
                        <div className="card__title">Trazabilidad avanzada</div>
                        <p style={{ color: 'var(--color-text-tertiary)', marginTop: 'var(--space-1)' }}>Detalle de documento, estado y línea de eventos filtrable.</p>
                      </div>
                      <div className="collection-panel-actions">
                        <span className="badge badge--accent">{selectedTraceDocument ? selectedTraceDocument.status : 'sin selección'}</span>
                        <button
                          className="btn btn-ghost panel-toggle-btn"
                          onClick={() => setCollapsedTraceByCollection(current => ({ ...current, [collection.id]: !traceCollapsed }))}
                          type="button"
                        >
                          {traceCollapsed ? 'Expandir' : 'Minimizar'}
                        </button>
                      </div>
                    </div>

                    {traceCollapsed ? null : selectedTraceDocument ? (
                      <>
                        <div className="trace-detail-card">
                          <div className="trace-detail-title">{getCollectionDisplayTitle(selectedTraceDocument)}</div>
                          <div className="trace-detail-path">{normalizeCollectionPath(selectedTraceDocument.collection_path || selectedTraceDocument.title) || selectedTraceDocument.source_path || 'Ruta no disponible'}</div>
                          <div style={{ display: 'inline-flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
                            <span className="badge badge--info">{selectedTraceDocument.mime_type}</span>
                            <span className="badge badge--accent">v{selectedTraceDocument.version}</span>
                            <span className={`badge badge--${getDocumentPipeline(selectedTraceDocument.status).tone}`}>{selectedTraceDocument.status}</span>
                          </div>
                          {selectedTraceDocument.error_message ? (
                            <div style={{ padding: 'var(--space-3)', borderRadius: 'var(--radius-md)', background: 'rgba(181, 66, 60, 0.12)', border: '1px solid rgba(181, 66, 60, 0.3)', color: 'var(--color-error)' }}>
                              {selectedTraceDocument.error_message}
                            </div>
                          ) : null}
                        </div>

                        <div style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
                          <button className="btn btn-primary" type="button" onClick={() => void copyDocumentEvidence(selectedTraceDocument)} disabled={evidenceLoadingByDocument[selectedTraceDocument.id]}>
                            {evidenceLoadingByDocument[selectedTraceDocument.id] ? 'Copiando...' : 'Copiar evidencia JSON'}
                          </button>
                          <button
                            className="btn btn-secondary"
                            type="button"
                            onClick={() => void refreshCollectionDocuments(collection.id)}
                            disabled={refreshingDocumentsByCollection[collection.id]}
                          >
                            {refreshingDocumentsByCollection[collection.id] ? 'Refrescando...' : 'Refrescar inventario'}
                          </button>
                        </div>

                        <div className="trace-toolbar">
                          <input
                            className="inventory-search"
                            onChange={event => setTraceAuditSearchByCollection(current => ({ ...current, [collection.id]: event.target.value }))}
                            placeholder="Buscar stage, pipeline, run..."
                            value={traceAuditSearchByCollection[collection.id] ?? ''}
                          />
                          <div className="trace-toolbar__filters">
                            <select
                              className="trace-select"
                              onChange={event => setTraceAuditStatusByCollection(current => ({ ...current, [collection.id]: event.target.value as AuditStatusFilter }))}
                              value={traceAuditStatusByCollection[collection.id] ?? 'all'}
                            >
                              {AUDIT_STATUS_FILTERS.map(option => (
                                <option key={option.value} value={option.value}>{option.label}</option>
                              ))}
                            </select>
                          </div>
                        </div>

                        {selectedTraceLoading ? (
                          <p style={{ color: 'var(--color-text-tertiary)' }}>Cargando auditoría del documento...</p>
                        ) : selectedTraceError ? (
                          <div style={{ padding: 'var(--space-3)', borderRadius: 'var(--radius-md)', background: 'rgba(181, 66, 60, 0.1)', border: '1px solid rgba(181, 66, 60, 0.25)', color: 'var(--color-error)' }}>
                            {selectedTraceError}
                          </div>
                        ) : visibleTraceAudit.length === 0 ? (
                          <p style={{ color: 'var(--color-text-tertiary)' }}>Sin eventos para los filtros actuales.</p>
                        ) : (
                          <div className="trace-list trace-list--bounded">
                            {visibleTraceAudit.slice(0, 20).map(event => (
                              <article key={event.id} className="trace-entry">
                                <div className="trace-entry__header">
                                  <div>
                                    <div className="trace-entry__title">{event.stage}</div>
                                    <div className="trace-entry__meta">{event.pipeline} · {event.entity_type}/{event.entity_id}</div>
                                  </div>
                                  <div style={{ display: 'inline-flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
                                    <span className={`badge badge--${event.status === 'failed' ? 'error' : event.status === 'succeeded' ? 'success' : 'warning'}`}>{event.status}</span>
                                    <span className="badge badge--info">{event.duration_ms !== null && event.duration_ms !== undefined ? `${event.duration_ms.toFixed(1)} ms` : 'sin duración'}</span>
                                  </div>
                                </div>
                                <div className="trace-entry__body">
                                  <div>Run: {event.run_id}</div>
                                  <div>Inicio: {formatRelativeDate(event.started_at)}</div>
                                  {event.completed_at ? <div>Fin: {formatRelativeDate(event.completed_at)}</div> : null}
                                  <pre className="trace-entry__json">métricas: {formatAuditValue(event.metrics)}{`\n`}contexto: {formatAuditValue(event.context)}</pre>
                                </div>
                              </article>
                            ))}
                          </div>
                        )}
                      </>
                    ) : (
                      <div className="empty-state" style={{ padding: 'var(--space-6) var(--space-4)' }}>
                        <div className="empty-state__icon" aria-hidden="true"><EmptyStateGlyph name="search" /></div>
                        <div className="empty-state__title">Sin documento seleccionado</div>
                        <p>Selecciona una fila del inventario para abrir su detalle completo.</p>
                      </div>
                    )}
                  </section>
                </section>

                <aside className="collection-doc-panel card">
                  <div className="card__header">
                    <div>
                      <div className="card__title">Inventario documental escalable</div>
                      <p style={{ color: 'var(--color-text-tertiary)', marginTop: 'var(--space-1)' }}>
                        Busca, filtra, pagina y abre detalle sin saturar la vista cuando hay miles de archivos.
                      </p>
                    </div>
                    <span className="badge badge--info">{filteredInventoryDocuments.length}</span>
                  </div>

                  <div className="inventory-toolbar">
                    <div className="inventory-toolbar__row">
                      <input
                        className="inventory-search"
                        onChange={event => {
                          const value = event.target.value;
                          setInventorySearchByCollection(current => ({ ...current, [collection.id]: value }));
                          setInventoryPageByCollection(current => ({ ...current, [collection.id]: 1 }));
                        }}
                        placeholder="Buscar por nombre, tipo MIME o estado"
                        value={inventorySearchByCollection[collection.id] ?? ''}
                      />
                      <select
                        className="inventory-page-size"
                        onChange={event => {
                          setInventoryPageSizeByCollection(current => ({ ...current, [collection.id]: Number(event.target.value) }));
                          setInventoryPageByCollection(current => ({ ...current, [collection.id]: 1 }));
                        }}
                        value={inventoryPageSizeByCollection[collection.id] ?? INVENTORY_PAGE_SIZE_OPTIONS[0]}
                      >
                        {INVENTORY_PAGE_SIZE_OPTIONS.map(size => (
                          <option key={size} value={size}>{size} por página</option>
                        ))}
                      </select>
                      <button
                        className="btn btn-secondary"
                        type="button"
                        onClick={() => void refreshCollectionDocuments(collection.id)}
                        disabled={refreshingDocumentsByCollection[collection.id]}
                      >
                        {refreshingDocumentsByCollection[collection.id] ? 'Refrescando...' : 'Actualizar'}
                      </button>
                    </div>
                    <div className="inventory-filter-strip">
                      {INVENTORY_STATUS_FILTERS.map(filter => (
                        <button
                          key={filter.value}
                          className={`inventory-filter-chip${(inventoryStatusByCollection[collection.id] ?? 'all') === filter.value ? ' inventory-filter-chip--active' : ''}`}
                          onClick={() => {
                            setInventoryStatusByCollection(current => ({ ...current, [collection.id]: filter.value }));
                            setInventoryPageByCollection(current => ({ ...current, [collection.id]: 1 }));
                          }}
                          type="button"
                        >
                          {filter.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="inventory-table" role="table" aria-label={`Inventario de ${collection.name}`}>
                    <div className="inventory-table__head" role="row">
                      <span>Documento</span>
                      <span>Estado</span>
                      <span>Tipo</span>
                      <span>Actualizado</span>
                    </div>
                    {pagedInventoryDocuments.map(document => {
                      const pipeline = getDocumentPipeline(document.status);
                      const isSelected = selectedTraceDocument?.id === document.id;
                      const collectionPath = normalizeCollectionPath(document.collection_path || document.title);
                      const displayTitle = getCollectionDisplayTitle(document);
                      return (
                        <button
                          key={document.id}
                          className={`inventory-table__row${isSelected ? ' inventory-table__row--selected' : ''}`}
                          onClick={() => {
                            void loadDocumentAudit(collection.id, document);
                          }}
                          type="button"
                        >
                          <div style={{ minWidth: 0 }}>
                            <div className="inventory-name" title={displayTitle}>{displayTitle}</div>
                            <div className="inventory-meta" title={(collectionPath || document.source_path) ?? undefined}>{collectionPath || document.source_path || 'Ruta no disponible'}</div>
                          </div>
                          <span className={`badge badge--${pipeline.tone}`}>{pipeline.label}</span>
                          <span className="inventory-meta">{document.mime_type}</span>
                          <span className="inventory-meta">{formatRelativeDate(document.updated_at)}</span>
                        </button>
                      );
                    })}
                    {pagedInventoryDocuments.length === 0 ? (
                      <div className="empty-state" style={{ padding: 'var(--space-6) var(--space-4)' }}>
                        <div className="empty-state__icon" aria-hidden="true"><EmptyStateGlyph name="search" /></div>
                        <div className="empty-state__title">Sin resultados</div>
                        <p>Ajusta filtros o búsqueda para localizar documentos.</p>
                      </div>
                    ) : null}
                  </div>

                  <div className="inventory-pagination">
                    <span>
                      Mostrando {(safeInventoryPage - 1) * inventoryPageSize + (pagedInventoryDocuments.length > 0 ? 1 : 0)}-
                      {(safeInventoryPage - 1) * inventoryPageSize + pagedInventoryDocuments.length} de {filteredInventoryDocuments.length}
                    </span>
                    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                      <button
                        className="btn btn-secondary"
                        disabled={safeInventoryPage <= 1}
                        onClick={() => setInventoryPageByCollection(current => ({ ...current, [collection.id]: Math.max(1, safeInventoryPage - 1) }))}
                        type="button"
                      >
                        Anterior
                      </button>
                      <span style={{ minWidth: 90, textAlign: 'center' }}>Página {safeInventoryPage}/{totalInventoryPages}</span>
                      <button
                        className="btn btn-secondary"
                        disabled={safeInventoryPage >= totalInventoryPages}
                        onClick={() => setInventoryPageByCollection(current => ({ ...current, [collection.id]: Math.min(totalInventoryPages, safeInventoryPage + 1) }))}
                        type="button"
                      >
                        Siguiente
                      </button>
                    </div>
                  </div>

                </aside>
              </div>
            </article>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function QueryPage() {
  const [collections, setCollections] = useState<Collection[]>([]);
  const [collectionId, setCollectionId] = useState('');
  const [documentsByCollection, setDocumentsByCollection] = useState<Record<string, Document[]>>({});
  const [historyByCollection, setHistoryByCollection] = useState<Record<string, QueryHistoryResponse[]>>({});
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [activeTurnId, setActiveTurnId] = useState('');
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState('auto');
  const [action, setAction] = useState<'search' | 'answer'>('answer');
  const [showAdvancedControls, setShowAdvancedControls] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingCollections, setLoadingCollections] = useState(true);
  const [loadingContext, setLoadingContext] = useState(false);
  const [hydratingTurnId, setHydratingTurnId] = useState('');
  const [hydrationFailedByTurnId, setHydrationFailedByTurnId] = useState<Record<string, boolean>>({});
  const [contextMobileOpen, setContextMobileOpen] = useState(false);
  const [pendingQuery, setPendingQuery] = useState('');
  const [pendingTurnId, setPendingTurnId] = useState('');
  const [error, setError] = useState('');
  const [activeAnswer, setActiveAnswer] = useState<AnswerResponse | null>(null);
  const [activeSearchHits, setActiveSearchHits] = useState<QueryHit[]>([]);
  const [inspectorDocumentId, setInspectorDocumentId] = useState('');
  const [inspectorNodes, setInspectorNodes] = useState<DocumentNode[]>([]);
  const [inspectorChunks, setInspectorChunks] = useState<Chunk[]>([]);
  const [inspectorPropositions, setInspectorPropositions] = useState<Proposition[]>([]);
  const [inspectorPage, setInspectorPage] = useState<DocumentPage | null>(null);
  const [inspectorLoading, setInspectorLoading] = useState(false);
  const [inspectorError, setInspectorError] = useState('');
  
  // Chats & RAG Audit States
  const [chats, setChats] = useState<Chat[]>([]);
  const [activeChatId, setActiveChatId] = useState<string>('');
  const [newChatTitle, setNewChatTitle] = useState<string>('');
  const [loadingChats, setLoadingChats] = useState<boolean>(false);
  const [technicalTab, setTechnicalTab] = useState<'summary' | 'rag_audit'>('summary');
  const [isLargeScreen, setIsLargeScreen] = useState(typeof window !== 'undefined' ? window.innerWidth > 1280 : true);
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const handleResize = () => setIsLargeScreen(window.innerWidth > 1280);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const answerDetailByTurnIdRef = useRef<Record<string, AnswerResponse>>({});
  const composerFormRef = useRef<HTMLFormElement | null>(null);
  const composerInputRef = useRef<HTMLTextAreaElement | null>(null);
  const threadViewportRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let mounted = true;
    api.listCollections()
      .then(items => {
        if (!mounted) return;
        setCollections(items);
        setCollectionId(items[0]?.id ?? '');
      })
      .catch(() => {
        if (mounted) setError('No se pudieron cargar las colecciones.');
      })
      .finally(() => {
        if (mounted) setLoadingCollections(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const hydrateTurn = useCallback(async (turn: ChatTurn) => {
    setHydratingTurnId(turn.id);
    setActiveTurnId(turn.id);
    setError('');
    setHydrationFailedByTurnId(current => ({ ...current, [turn.id]: false }));

    try {
      if (turn.kind === 'answer' && turn.answerId) {
        const cachedDetail = answerDetailByTurnIdRef.current[turn.id];
        if (cachedDetail) {
          setActiveAnswer(cachedDetail);
          setActiveSearchHits(getAnswerEvidence(cachedDetail));
          return;
        }

        try {
          const detail = await api.getAnswer(turn.answerId);
          setActiveAnswer(detail);
          const evidence = getAnswerEvidence(detail);
          setActiveSearchHits(evidence);
          answerDetailByTurnIdRef.current[turn.id] = detail;
          setTurns(current => current.map(item => (
            item.id === turn.id
              ? {
                  ...item,
                  answer: detail.answer,
                  answerId: detail.answer_id,
                  groundingScore: detail.grounding_score,
                  verdict: detail.verdict,
                  citationsCount: detail.citations.length,
                  hits: evidence,
                  citations: detail.citations,
                }
              : item
          )));
        } catch {
          setActiveAnswer(null);
          setActiveSearchHits(turn.hits ?? []);
          setHydrationFailedByTurnId(current => ({ ...current, [turn.id]: true }));
          setError('No se pudo cargar el detalle completo de este turno. Mostrando datos disponibles.');
        }
        return;
      }

      setActiveAnswer(null);
      setActiveSearchHits(turn.hits ?? []);
    } finally {
      setHydratingTurnId('');
    }
  }, []);

  // Load documents for collection
  useEffect(() => {
    if (!collectionId) {
      setDocumentsByCollection(current => ({ ...current, [collectionId]: [] }));
      return;
    }

    let mounted = true;
    setLoadingContext(true);

    api.listAllCollectionDocuments(collectionId)
      .then(docs => {
        if (!mounted) return;
        setDocumentsByCollection(current => ({
          ...current,
          [collectionId]: docs,
        }));
      })
      .catch(() => {
        if (mounted) setError('No se pudieron cargar los documentos de la colección.');
      })
      .finally(() => {
        if (mounted) setLoadingContext(false);
      });

    return () => {
      mounted = false;
    };
  }, [collectionId]);

  // Load chat threads when collectionId changes
  useEffect(() => {
    if (!collectionId) {
      setChats([]);
      setActiveChatId('');
      setTurns([]);
      return;
    }

    let mounted = true;
    setLoadingChats(true);
    api.listChats(collectionId)
      .then(items => {
        if (!mounted) return;
        setChats(items);
        if (items.length > 0) {
          setActiveChatId(items[0].id);
        } else {
          setActiveChatId('');
          setTurns([]);
          setActiveTurnId('');
          setActiveAnswer(null);
          setActiveSearchHits([]);
        }
      })
      .catch(() => {
        if (mounted) setError('No se pudieron cargar las conversaciones.');
      })
      .finally(() => {
        if (mounted) setLoadingChats(false);
      });

    return () => {
      mounted = false;
    };
  }, [collectionId]);

  // Load messages when activeChatId changes
  useEffect(() => {
    if (!activeChatId) {
      setTurns([]);
      setActiveTurnId('');
      setActiveAnswer(null);
      setActiveSearchHits([]);
      return;
    }

    let mounted = true;
    api.getChatMessages(activeChatId, 50)
      .then(messages => {
        if (!mounted) return;

        const chatTurns: ChatTurn[] = [];
        for (let i = 0; i < messages.length; i++) {
          const msg = messages[i];
          if (msg.role === 'user') {
            const nextMsg = messages[i + 1];
            const hasAssistant = nextMsg && nextMsg.role === 'assistant';
            const assistantContent = hasAssistant ? nextMsg.content : undefined;
            const assistantId = hasAssistant ? nextMsg.id : undefined;

            chatTurns.push({
              id: msg.id,
              queryId: msg.id,
              query: msg.content,
              answerId: assistantId,
              routeMode: 'auto',
              intent: 'user_chat',
              language: 'es',
              createdAt: msg.created_at,
              kind: 'answer',
              answer: assistantContent,
              isPending: false,
            });

            if (hasAssistant) {
              i++;
            }
          }
        }

        setTurns(chatTurns);
        setHydrationFailedByTurnId({});
        const lastTurn = chatTurns.at(-1) ?? null;

        if (!lastTurn) {
          setActiveTurnId('');
          setActiveAnswer(null);
          setActiveSearchHits([]);
        } else {
          void hydrateTurn(lastTurn);
        }
      })
      .catch(() => {
        if (mounted) setError('No se pudieron cargar los mensajes de esta conversación.');
      });

    return () => {
      mounted = false;
    };
  }, [activeChatId, hydrateTurn]);

  const handleCreateChat = async (e: FormEvent) => {
    e.preventDefault();
    if (!collectionId || !newChatTitle.trim()) return;
    try {
      const chat = await api.createChat({
        collection_id: collectionId,
        title: newChatTitle.trim(),
      });
      setChats(current => [chat, ...current]);
      setActiveChatId(chat.id);
      setNewChatTitle('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo crear la conversación.');
    }
  };

  const handleDeleteChat = async (chatId: string) => {
    if (!window.confirm('¿Seguro que deseas eliminar esta conversación y todo su historial?')) return;
    try {
      await api.deleteChat(chatId);
      setChats(current => current.filter(c => c.id !== chatId));
      if (activeChatId === chatId) {
        const remaining = chats.filter(c => c.id !== chatId);
        if (remaining.length > 0) {
          setActiveChatId(remaining[0].id);
        } else {
          setActiveChatId('');
          setTurns([]);
          setActiveTurnId('');
          setActiveAnswer(null);
          setActiveSearchHits([]);
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo eliminar la conversación.');
    }
  };


  const collectionDocuments = useMemo(
    () => documentsByCollection[collectionId] ?? [],
    [collectionId, documentsByCollection],
  );

  const visibleDocuments = useMemo(
    () => collectionDocuments.slice(0, MAX_VISIBLE_DOCUMENTS),
    [collectionDocuments],
  );

  const recentMemory = useMemo(
    () => {
      const items = historyByCollection[collectionId] ?? [];
      const answered = items.filter(item => Boolean(item.answer_id));
      return (answered.length > 0 ? answered : items).slice(0, 5);
    },
    [collectionId, historyByCollection],
  );

  const visibleTurns = useMemo(() => {
    const normalizedAnswerQueries = new Set(
      turns
        .filter(turn => turn.kind === 'answer')
        .map(turn => turn.query.trim().toLowerCase()),
    );

    return turns.filter(turn => {
      if (turn.id === activeTurnId) {
        return true;
      }

      if (turn.kind === 'answer') {
        return true;
      }

      const normalizedQuery = turn.query.trim().toLowerCase();
      return !normalizedAnswerQueries.has(normalizedQuery);
    });
  }, [activeTurnId, turns]);

  const activeTurn = useMemo(
    () => visibleTurns.find(turn => turn.id === activeTurnId) ?? visibleTurns.at(-1) ?? null,
    [activeTurnId, visibleTurns],
  );

  const activeEvidence = useMemo(
    () => activeAnswer ? getAnswerEvidence(activeAnswer) : activeSearchHits,
    [activeAnswer, activeSearchHits],
  );

  const activeCitations = useMemo(
    () => activeAnswer?.citations ?? activeTurn?.citations ?? [],
    [activeAnswer, activeTurn],
  );

  const activeCitationHydrationFailed = Boolean(
    activeTurn
    && hydrationFailedByTurnId[activeTurn.id]
    && (activeTurn.citationsCount ?? 0) > 0
    && activeCitations.length === 0,
  );

  useEffect(() => {
    const candidateIds = [
      activeCitations.find(item => item.document_id)?.document_id ?? '',
      activeEvidence.find(item => item.document_id)?.document_id ?? '',
      collectionDocuments[0]?.id ?? '',
    ].filter(Boolean);
    const nextId = candidateIds[0] ?? '';
    if (!nextId) {
      setInspectorDocumentId('');
      return;
    }
    setInspectorDocumentId(current => (current && candidateIds.includes(current) ? current : nextId));
  }, [activeCitations, activeEvidence, collectionDocuments]);

  useEffect(() => {
    if (!inspectorDocumentId) {
      setInspectorNodes([]);
      setInspectorChunks([]);
      setInspectorPropositions([]);
      setInspectorPage(null);
      setInspectorError('');
      return;
    }

    let mounted = true;
    const candidatePageNumber = activeCitations.find(item => item.document_id === inspectorDocumentId)?.page_number
      ?? activeEvidence.find(item => item.document_id === inspectorDocumentId)?.page_number
      ?? null;

    setInspectorLoading(true);
    setInspectorError('');

    Promise.allSettled([
      api.getDocumentStructure(inspectorDocumentId),
      api.getDocumentChunks(inspectorDocumentId),
      api.getDocumentPropositions(inspectorDocumentId),
      candidatePageNumber ? api.getDocumentPage(inspectorDocumentId, candidatePageNumber) : Promise.resolve(null),
    ])
      .then(([structureResult, chunkResult, propositionResult, pageResult]) => {
        if (!mounted) return;
        setInspectorNodes(structureResult.status === 'fulfilled' ? structureResult.value : []);
        setInspectorChunks(chunkResult.status === 'fulfilled' ? chunkResult.value : []);
        setInspectorPropositions(propositionResult.status === 'fulfilled' ? propositionResult.value : []);
        setInspectorPage(pageResult.status === 'fulfilled' ? pageResult.value : null);
        if (
          structureResult.status === 'rejected'
          || chunkResult.status === 'rejected'
          || propositionResult.status === 'rejected'
        ) {
          setInspectorError('No se pudo cargar por completo el inspector documental.');
        }
      })
      .finally(() => {
        if (mounted) setInspectorLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, [activeCitations, activeEvidence, inspectorDocumentId]);

  const technicalTags = useMemo(() => {
    if (!activeTurn) return [] as string[];

    const tags = new Set<string>();
    tags.add(activeTurn.routeMode);
    tags.add(activeTurn.intent);
    tags.add(activeTurn.language);

    if (activeTurn.verdict) {
      tags.add(activeTurn.verdict);
    }

    activeEvidence.slice(0, 4).forEach(item => {
      tags.add(item.source_type);
    });

    return Array.from(tags).slice(0, 8);
  }, [activeEvidence, activeTurn]);

  const activeContextSummary = useMemo(() => {
    if (!activeTurn) {
      return 'Sin turno activo.';
    }

    if (activeEvidence.length === 0) {
      return 'No se recuperó evidencia para este turno.';
    }

    const sources = new Set(activeEvidence.map(item => item.source_type));
    const documents = new Set(activeEvidence.map(item => item.document_id).filter(Boolean));
    return `Se usaron ${activeEvidence.length} evidencias, ${documents.size} documentos y fuentes tipo ${Array.from(sources).join(', ')}.`;
  }, [activeEvidence, activeTurn]);

  const lastTurnAnswer = visibleTurns.at(-1)?.answer;
  useEffect(() => {
    const viewport = threadViewportRef.current;
    if (!viewport) return;
    viewport.scrollTop = viewport.scrollHeight;

    const timer = setTimeout(() => {
      viewport.scrollTop = viewport.scrollHeight;
    }, 50);

    return () => clearTimeout(timer);
  }, [visibleTurns.length, pendingTurnId, loading, lastTurnAnswer]);

  const canSubmit = collectionId.length > 0 && query.trim().length > 0 && !loading && !loadingCollections;
  const routeModes = ['auto', 'exact', 'factual_local', 'multi_hop', 'global', 'argumentative', 'visual'];


  const quickQuerySuggestions = useMemo(() => {
    const defaults = [
      'Resume la idea principal del corpus en 4 líneas con citas.',
      '¿Qué postura crítica se repite en los documentos y con qué evidencia?',
      'Extrae 3 conceptos literarios clave y su fragmento más representativo.',
      'Compara dos enfoques presentes en la colección y justifica con citas.',
    ];

    const memoryBased = recentMemory
      .map(item => item.query.trim())
      .filter(Boolean)
      .slice(0, 2)
      .map(item => `Reformula y sintetiza: ${item}`);

    return Array.from(new Set([...memoryBased, ...defaults])).slice(0, 5);
  }, [recentMemory]);

  const qualityAlerts = useMemo(() => {
    if (!activeTurn || activeTurn.kind !== 'answer') {
      return [] as string[];
    }

    const alerts: string[] = [];
    const citationsCount = activeTurn.citationsCount ?? 0;
    const citationsInPanel = activeCitations.length;
    const groundingScore = activeTurn.groundingScore;
    const answerText = (activeAnswer?.answer ?? activeTurn.answer ?? '').trim();

    if (citationsCount === 0) {
      alerts.push('La respuesta no incluye citas explícitas en el turno activo.');
    }

    if (typeof groundingScore === 'number' && groundingScore < 0.6) {
      alerts.push('El grounding es bajo para este turno; valida la respuesta con las evidencias del panel.');
    }

    if (activeTurn.language.startsWith('es') && /^(the evidence supports|i could not|corpus-level synthesis|visual grounding|hierarchical synthesis)/i.test(answerText)) {
      alerts.push('La respuesta parece usar una plantilla en ingles, posible desalineacion de idioma.');
    }

    if (activeEvidence.length === 0) {
      alerts.push('No se recuperaron evidencias para respaldar el resultado actual.');
    }

    if (citationsCount > 0 && citationsInPanel === 0) {
      alerts.push('Hay citas reportadas pero no visibles en el panel; posible fallo de hidratacion del detalle.');
    }

    if ((groundingScore ?? 0) >= 0.75 && activeEvidence.length === 0) {
      alerts.push('Grounding alto sin evidencias visibles: no confies en esta respuesta hasta rehidratar el turno.');
    }

    return alerts.slice(0, 3);
  }, [activeAnswer, activeCitations, activeEvidence, activeTurn]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!collectionId || !query.trim()) return;
    setLoading(true);
    setError('');
    const prompt = query.trim();

    let chatIdToUse = activeChatId;
    if (!chatIdToUse && action === 'answer') {
      try {
        const newChat = await api.createChat({
          collection_id: collectionId,
          title: prompt.slice(0, 30) + (prompt.length > 30 ? '...' : ''),
        });
        setChats(current => [newChat, ...current]);
        setActiveChatId(newChat.id);
        chatIdToUse = newChat.id;
      } catch {
        setError('No se pudo inicializar un chat nuevo.');
        setLoading(false);
        return;
      }
    }

    const pendingTurn = createPendingTurn(prompt, mode, action);
    setQuery('');
    setPendingQuery(prompt);
    setPendingTurnId(pendingTurn.id);
    setActiveTurnId('');
    setActiveAnswer(null);
    setActiveSearchHits([]);
    setTurns(current => [...current, pendingTurn]);
    try {
      let submittedTurn: ChatTurn;

      if (action === 'search') {
        const response = await api.searchQuery({
          collection_id: collectionId,
          query: prompt,
          mode,
        });

        submittedTurn = mapSearchResultToTurn(response);
        setActiveAnswer(null);
        setActiveSearchHits(response.hits);
      } else {
        const response = await api.answerQuery({
          collection_id: collectionId,
          query: prompt,
          mode,
          generation_profile: 'standard',
          chat_id: chatIdToUse || null,
        });

        submittedTurn = mapAnswerResultToTurn(response);
        const evidence = getAnswerEvidence(response);
        setActiveAnswer(response);
        setActiveSearchHits(evidence);
        answerDetailByTurnIdRef.current[submittedTurn.id] = response;
      }

      setTurns(current => current.map(turn => (turn.id === pendingTurn.id ? submittedTurn : turn)));
      setActiveTurnId(submittedTurn.id);
      setPendingTurnId('');

      const historyEntry: QueryHistoryResponse = {
        query_id: submittedTurn.queryId,
        collection_id: collectionId,
        query: submittedTurn.query,
        answer_id: submittedTurn.answerId ?? null,
        answer: submittedTurn.answer ?? null,
        route_mode: submittedTurn.routeMode,
        intent: submittedTurn.intent,
        language: submittedTurn.language,
        verdict: submittedTurn.verdict ?? null,
        grounding_score: submittedTurn.groundingScore ?? null,
        created_at: submittedTurn.createdAt,
        citations_count: submittedTurn.citationsCount ?? 0,
      };

      setHistoryByCollection(current => ({
        ...current,
        [collectionId]: [historyEntry, ...(current[collectionId] ?? [])].slice(0, 20),
      }));

      setPendingQuery('');
    } catch (submissionError) {
      setTurns(current => current.filter(turn => turn.id !== pendingTurn.id));
      setPendingQuery('');
      setPendingTurnId('');
      setError(submissionError instanceof Error ? submissionError.message : 'La consulta falló.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="query-chat-page animate-fade-in-up">
      <div className="query-chat-layout" style={{ display: 'grid', gridTemplateColumns: isLargeScreen ? '240px minmax(0, 1fr) minmax(320px, 420px)' : '1fr', gap: 'var(--space-4)' }}>
        {/* Sidebar de Chats/Conversaciones */}
        <aside className="query-threads-sidebar card" style={{ padding: 'var(--space-3)', display: 'grid', gridTemplateRows: 'auto auto 1fr', gap: 'var(--space-3)', background: 'rgba(255, 252, 246, 0.55)', minWidth: 0, height: '100%' }}>
          <div className="card__title" style={{ fontSize: 'var(--font-sm)', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-text-tertiary)' }}>Conversaciones</div>
          
          <form onSubmit={handleCreateChat} style={{ display: 'flex', gap: 'var(--space-2)' }}>
            <input
              type="text"
              placeholder="Nueva conversación..."
              value={newChatTitle}
              onChange={e => setNewChatTitle(e.target.value)}
              className="query-select"
              style={{ flex: 1, padding: '0.4rem 0.6rem', fontSize: 'var(--font-xs)', border: '1px solid rgba(120,76,43,0.25)' }}
            />
            <button type="submit" className="btn btn-primary" style={{ padding: '0.4rem 0.6rem', fontSize: 'var(--font-xs)' }}>+</button>
          </form>

          <div style={{ overflowY: 'auto', display: 'grid', gap: 'var(--space-2)', alignContent: 'start', height: '100%' }}>
            {loadingChats ? (
              <p className="query-panel-note">Cargando...</p>
            ) : chats.length === 0 ? (
              <p className="query-panel-note">No hay chats creados.</p>
            ) : (
              chats.map(c => {
                const isActive = c.id === activeChatId;
                return (
                  <div
                    key={c.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: 'var(--space-2)',
                      borderRadius: 'var(--radius-md)',
                      background: isActive ? 'rgba(99, 102, 241, 0.12)' : 'transparent',
                      border: isActive ? '1px solid rgba(99, 102, 241, 0.35)' : '1px solid transparent',
                      cursor: 'pointer',
                    }}
                    onClick={() => setActiveChatId(c.id)}
                  >
                    <span style={{ fontSize: 'var(--font-xs)', fontWeight: isActive ? 'bold' : 'normal', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, paddingRight: '0.5rem' }}>
                      {c.title}
                    </span>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        void handleDeleteChat(c.id);
                      }}
                      style={{
                        background: 'transparent',
                        border: 'none',
                        color: 'var(--color-error)',
                        cursor: 'pointer',
                        padding: '0 0.2rem',
                        fontSize: 'var(--font-xs)'
                      }}
                    >
                      ✕
                    </button>
                  </div>
                );
              })
            )}
          </div>
        </aside>

        <section className="query-chat" aria-label="Chat principal de consulta">
          <header className="query-chat__header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--space-3)', paddingBottom: 'var(--space-3)', borderBottom: '1px solid rgba(120, 76, 43, 0.12)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
              <label className="query-field" style={{ margin: 0, flexDirection: 'row', alignItems: 'center', gap: 'var(--space-2)' }}>
                <span className="query-label" style={{ fontWeight: 'bold', fontSize: 'var(--font-sm)', color: 'var(--color-text-secondary)' }}>Colección:</span>
                <select
                  value={collectionId}
                  onChange={event => setCollectionId(event.target.value)}
                  disabled={loadingCollections}
                  className="query-select"
                  style={{ minWidth: '180px', padding: '0.4rem 0.6rem' }}
                >
                  {collections.length === 0 ? <option value="">No hay colecciones</option> : collections.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
                </select>
              </label>

              <button
                type="button"
                className="btn btn-secondary query-advanced-toggle"
                onClick={() => setShowAdvancedControls(current => !current)}
                aria-expanded={showAdvancedControls}
                style={{ padding: '0.4rem 0.8rem', fontSize: 'var(--font-xs)' }}
              >
                {showAdvancedControls ? 'Ocultar opciones avanzadas' : 'Opciones avanzadas'}
              </button>

              <button
                type="button"
                className="btn btn-secondary query-context-toggle"
                onClick={() => setContextMobileOpen(current => !current)}
                style={{ padding: '0.4rem 0.8rem', fontSize: 'var(--font-xs)' }}
              >
                {contextMobileOpen ? 'Ocultar panel lateral' : 'Ver panel lateral'}
              </button>
            </div>

            <div className="query-chat__meta" aria-label="Resumen de sesión">
              <span className="query-chip" style={{ background: 'rgba(160, 90, 44, 0.08)', color: 'var(--color-text-accent)' }}>{collectionDocuments.length} documentos</span>
              <span className="query-chip" style={{ background: 'rgba(160, 90, 44, 0.08)', color: 'var(--color-text-accent)' }}>{visibleTurns.length} turnos</span>
            </div>
          </header>

          {showAdvancedControls ? (
            <div className="query-advanced-panel" role="group" aria-label="Opciones avanzadas" style={{ border: '1px dashed rgba(120, 76, 43, 0.24)', borderRadius: 'var(--radius-lg)', background: 'rgba(255, 255, 255, 0.42)', padding: 'var(--space-3)', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 'var(--space-3)' }}>
              <label className="query-field">
                <span className="query-label">Ruta de recuperación</span>
                <select
                  value={mode}
                  onChange={event => setMode(event.target.value)}
                  className="query-select"
                >
                  {routeModes.map(item => <option key={item} value={item}>{item}</option>)}
                </select>
              </label>

              <label className="query-field">
                <span className="query-label">Tipo de salida</span>
                <div className="query-action-switch" role="tablist" aria-label="Tipo de salida">
                  <button
                    type="button"
                    className={`query-action-btn${action === 'answer' ? ' query-action-btn--active' : ''}`}
                    aria-selected={action === 'answer'}
                    onClick={() => setAction('answer')}
                  >
                    Respuesta final
                  </button>
                  <button
                    type="button"
                    className={`query-action-btn${action === 'search' ? ' query-action-btn--active' : ''}`}
                    aria-selected={action === 'search'}
                    onClick={() => setAction('search')}
                  >
                    Solo evidencia
                  </button>
                </div>
              </label>
            </div>
          ) : null}

          <section className="query-chat__quick-prompts" aria-label="Sugerencias rápidas de consulta">
            <div className="query-panel-heading">Sugerencias rápidas</div>
            <div className="query-suggestion-list">
              {quickQuerySuggestions.map(suggestion => (
                <button
                  key={suggestion}
                  type="button"
                  className="query-suggestion-pill"
                  onClick={() => {
                    setQuery(suggestion);
                    composerInputRef.current?.focus();
                  }}
                  disabled={loading || loadingCollections}
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </section>

          {error ? (
            <div className="query-alert" role="alert">
              <p>{error}</p>
            </div>
          ) : null}

          <div className="query-chat__thread" ref={threadViewportRef}>
            {loadingContext ? <p className="query-panel-note">Cargando contexto de colección...</p> : null}
            <ConversationThread
              turns={visibleTurns}
              activeTurnId={activeTurnId}
              hydratingTurnId={hydratingTurnId}
              pendingTurnId={pendingTurnId}
              onSelectTurn={(turnId: string) => {
                const selected = visibleTurns.find(turn => turn.id === turnId);
                if (!selected) return;
                void hydrateTurn(selected);
              }}
            />
          </div>

          <form ref={composerFormRef} onSubmit={handleSubmit} className="query-chat__composer">
            <textarea
              ref={composerInputRef}
              value={query}
              onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setQuery(event.target.value)}
              onKeyDown={(event: KeyboardEvent<HTMLTextAreaElement>) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  if (canSubmit) {
                    composerFormRef.current?.requestSubmit();
                  }
                }
              }}
              rows={2}
              maxLength={1200}
              placeholder="Escribe tu pregunta. Enter envia, Shift+Enter nueva linea."
              className="query-textarea query-textarea--chat"
              aria-label="Caja de mensaje"
            />

            <div className="query-chat__composer-footer">
              <button className="btn btn-primary" type="submit" disabled={!canSubmit}>
                {loading ? (action === 'search' ? 'Buscando...' : 'Generando...') : action === 'search' ? 'Buscar evidencia' : 'Enviar'}
              </button>
            </div>
          </form>
        </section>

        <aside className={`query-side-rail${contextMobileOpen ? ' query-side-rail--open' : ''}`}>
          <section className="query-side-card card" aria-label="Panel de citas y fragmentos">
            <div className="card__header">
              <div>
                <div className="card__title">Citas y fragmentos</div>
                <p className="query-panel-note">Evidencia que fundamenta el turno seleccionado.</p>
              </div>
              <span className="badge badge--accent">{activeCitations.length}</span>
            </div>

            {!activeTurn ? (
              <p className="query-panel-note">
                {pendingQuery
                  ? `Procesando la consulta actual: "${pendingQuery}". Aquí aparecerán citas y fragmentos en cuanto termine.`
                  : 'Selecciona un turno para revisar citas y fragmentos.'}
              </p>
            ) : (
              <>
                <div className="query-context__block">
                  <div className="query-panel-heading">Citas exactas</div>
                  <CitationSidebar
                    citations={activeCitations}
                    expectedCount={activeTurn.citationsCount ?? activeCitations.length}
                    hydrationFailed={activeCitationHydrationFailed}
                  />
                </div>

                <div className="query-context__block">
                  <div className="query-panel-heading">Fragmentos recuperados</div>
                  {activeEvidence.length === 0 ? (
                    <p className="query-panel-note">No hay fragmentos para este turno.</p>
                  ) : (
                    <div className="query-turn__evidence-list">
                      {activeEvidence.slice(0, 5).map(hit => (
                        <div
                          key={hit.id}
                          style={{ cursor: hit.document_id ? 'pointer' : 'default' }}
                          onClick={() => {
                            if (hit.document_id) setInspectorDocumentId(hit.document_id);
                          }}
                        >
                          <EvidenceCard evidence={hit} />
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <div className="query-context__block">
                  <div className="query-panel-heading">Visual evidence</div>
                  <PageViewer evidence={activeEvidence} />
                </div>
              </>
            )}
          </section>

          <section className="query-side-card card" aria-label="Panel técnico de contexto" style={{ display: 'grid', gap: 'var(--space-4)' }}>
            <div className="card__header" style={{ display: 'flex', flexDirection: 'column', alignItems: 'stretch', gap: 'var(--space-2)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <div className="card__title">Detalles técnicos</div>
                  <p className="query-panel-note">Contexto, RAG Audit y métricas.</p>
                </div>
                <span className="badge badge--info">{activeTurn?.kind === 'answer' ? 'respuesta' : 'búsqueda'}</span>
              </div>

              {/* Selector de pestañas */}
              <div style={{ display: 'flex', gap: 'var(--space-2)', borderBottom: '1px solid rgba(255,255,255,0.08)', marginTop: 'var(--space-2)' }}>
                <button
                  type="button"
                  onClick={() => setTechnicalTab('summary')}
                  style={{
                    padding: 'var(--space-2) var(--space-3)',
                    background: 'transparent',
                    border: 'none',
                    borderBottom: technicalTab === 'summary' ? '2px solid rgba(99,102,241,0.85)' : '2px solid transparent',
                    color: technicalTab === 'summary' ? 'var(--color-text-primary)' : 'var(--color-text-tertiary)',
                    fontWeight: technicalTab === 'summary' ? 'bold' : 'normal',
                    cursor: 'pointer',
                    fontSize: 'var(--font-xs)',
                  }}
                >
                  Resumen General
                </button>
                <button
                  type="button"
                  onClick={() => setTechnicalTab('rag_audit')}
                  style={{
                    padding: 'var(--space-2) var(--space-3)',
                    background: 'transparent',
                    border: 'none',
                    borderBottom: technicalTab === 'rag_audit' ? '2px solid rgba(99,102,241,0.85)' : '2px solid transparent',
                    color: technicalTab === 'rag_audit' ? 'var(--color-text-primary)' : 'var(--color-text-tertiary)',
                    fontWeight: technicalTab === 'rag_audit' ? 'bold' : 'normal',
                    cursor: 'pointer',
                    fontSize: 'var(--font-xs)',
                  }}
                >
                  RAG Audit (Trace)
                </button>
              </div>
            </div>

            {activeTurn ? (
              technicalTab === 'summary' ? (
                <>
                  <section className="query-context__block query-active-turn">
                    <div className="query-panel-heading">Turno activo</div>
                    <p className="query-turn__query">{activeTurn.query}</p>
                    <div className="query-turn__stats">
                      {technicalTags.map(tag => <span key={tag} className="query-chip">{tag}</span>)}
                    </div>
                  </section>

                  <section className="query-context__block">
                    <div className="query-panel-heading">Métricas</div>
                    <div className="query-answer__grid">
                      <div className="query-answer__metric">
                        <div className="query-answer__label">Grounding</div>
                        <div className="query-answer__value">{activeTurn.groundingScore?.toFixed(3) ?? '—'}</div>
                      </div>
                      <div className="query-answer__metric">
                        <div className="query-answer__label">Citas</div>
                        <div className="query-answer__value">{activeTurn.citationsCount ?? 0}</div>
                      </div>
                      <div className="query-answer__metric">
                        <div className="query-answer__label">Evidencias</div>
                        <div className="query-answer__value">{activeEvidence.length}</div>
                      </div>
                      <div className="query-answer__metric">
                        <div className="query-answer__label">Documentos</div>
                        <div className="query-answer__value">{collectionDocuments.length}</div>
                      </div>
                    </div>
                  </section>

                  <section className="query-context__block">
                    <div className="query-panel-heading">Contexto usado</div>
                    <p className="query-panel-note">{activeContextSummary}</p>
                  </section>

                  {activeTurn.kind === 'answer' ? (
                    <>
                      {activeAnswer ? (
                        <section className="query-context__block query-answer">
                          <AnswerPanel answer={activeAnswer} />
                        </section>
                      ) : null}
                      <section className="query-context__block query-answer">
                        <div className="query-panel-heading">Respuesta completa</div>
                        <p className="query-answer__body">
                          {normalizeAssistantText(activeAnswer?.answer ?? activeTurn.answer ?? '', activeTurn.language) || 'Sin respuesta textual disponible para este turno.'}
                        </p>
                      </section>
                    </>
                  ) : null}

                  {qualityAlerts.length > 0 ? (
                    <section className="query-context__block">
                      <div className="query-panel-heading">Alertas de calidad</div>
                      <ul className="query-alert-list">
                        {qualityAlerts.map(alert => <li key={alert}>{alert}</li>)}
                      </ul>
                    </section>
                  ) : null}

                  {activeAnswer ? (
                    <section className="query-context__block">
                      <div className="query-panel-heading">Exportación</div>
                      <div className="query-export__actions">
                        <a className="btn btn-primary" href={api.exportAnswerMarkdown(activeAnswer.answer_id)} target="_blank" rel="noreferrer">Markdown</a>
                        <a className="btn btn-secondary" href={api.exportAnswerPdf(activeAnswer.answer_id)} target="_blank" rel="noreferrer">PDF</a>
                      </div>
                      {Object.keys(activeAnswer.evidence_trace ?? {}).length > 0 ? (
                        <pre style={{ marginTop: 'var(--space-3)', whiteSpace: 'pre-wrap', background: 'rgba(255,255,255,0.03)', borderRadius: 'var(--radius-md)', padding: 'var(--space-3)', color: 'var(--color-text-secondary)', fontSize: 'var(--font-xs)', lineHeight: 'var(--line-height-relaxed)' }}>
                          {JSON.stringify(activeAnswer.evidence_trace, null, 2)}
                        </pre>
                      ) : null}
                    </section>
                  ) : null}

                  <section className="query-context__block">
                    <div className="query-panel-heading">Memoria reciente</div>
                    <div className="query-rail__list">
                      {recentMemory.length === 0 ? (
                        <p className="query-panel-note">No hay consultas previas para esta colección.</p>
                      ) : (
                        recentMemory.map(item => (
                          <button
                            key={item.query_id}
                            type="button"
                            className="query-rail__item query-rail__item--button"
                            onClick={() => setQuery(item.query)}
                          >
                            <div className="query-rail__item-title">{item.query}</div>
                            <div className="query-rail__item-meta">{formatRelativeDate(item.created_at)} · {item.route_mode}</div>
                          </button>
                        ))
                      )}
                    </div>
                  </section>

                  <section className="query-context__block">
                    <div className="query-panel-heading">Documentos en contexto</div>
                    <p className="query-panel-note">Mostrando {visibleDocuments.length} de {collectionDocuments.length} documentos.</p>
                    <div className="query-rail__list">
                      {visibleDocuments.length === 0 ? (
                        <p className="query-panel-note">No hay documentos disponibles en esta colección.</p>
                      ) : (
                        visibleDocuments.map(document => {
                          const pipeline = getDocumentPipeline(document.status);
                          const collectionPath = normalizeCollectionPath(document.collection_path || document.title);
                          return (
                            <article
                              key={document.id}
                              className="query-rail__item"
                              role="button"
                              tabIndex={0}
                              onClick={() => setInspectorDocumentId(document.id)}
                              onKeyDown={event => {
                                  if (event.key === 'Enter' || event.key === ' ') {
                                    event.preventDefault();
                                    setInspectorDocumentId(document.id);
                                  }
                              }}
                              style={{
                                cursor: 'pointer',
                                borderColor: inspectorDocumentId === document.id ? 'rgba(99,102,241,0.55)' : undefined,
                              }}
                            >
                              <div className="query-rail__item-top">
                                <div className="query-rail__item-title" title={getCollectionDisplayTitle(document)}>{getCollectionDisplayTitle(document)}</div>
                                <span className={`badge badge--${pipeline.tone}`}>{pipeline.label}</span>
                              </div>
                              <div className="query-rail__item-meta" title={(collectionPath || document.source_path) ?? undefined}>{collectionPath || document.source_path || 'Ruta no disponible'}</div>
                            </article>
                          );
                        })
                      )}
                    </div>
                  </section>
                  <section className="query-context__block">
                    <div className="query-panel-heading">Inspector documental</div>
                    {!inspectorDocumentId ? (
                      <p className="query-panel-note">Selecciona un documento del corpus o de la evidencia para inspeccionarlo.</p>
                    ) : inspectorLoading ? (
                      <p className="query-panel-note">Cargando estructura, chunks y proposiciones...</p>
                    ) : (
                      <div style={{ display: 'grid', gap: 'var(--space-3)' }}>
                        <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
                          <span className="query-chip">Documento {inspectorDocumentId}</span>
                          <span className="query-chip">Nodos {inspectorNodes.length}</span>
                          <span className="query-chip">Chunks {inspectorChunks.length}</span>
                          <span className="query-chip">Proposiciones {inspectorPropositions.length}</span>
                          {inspectorPage ? <span className="query-chip">Pagina {inspectorPage.page_number}</span> : null}
                        </div>
                        {inspectorError ? <p className="query-panel-note" style={{ color: 'var(--color-error)' }}>{inspectorError}</p> : null}
                        {inspectorPage ? (
                          <div className="card" style={{ background: 'rgba(10,14,23,0.96)', borderColor: 'var(--color-border)' }}>
                            <div className="card__title">{inspectorPage.title}</div>
                            <p className="query-panel-note" style={{ marginTop: 'var(--space-2)' }}>{inspectorPage.text}</p>
                            {inspectorPage.image_path ? (
                              <a href={inspectorPage.image_path} target="_blank" rel="noreferrer">Abrir pagina visual</a>
                            ) : null}
                          </div>
                        ) : null}
                        <div className="card" style={{ background: 'rgba(10,14,23,0.96)', borderColor: 'var(--color-border)' }}>
                          <div className="card__title">Estructura</div>
                          <pre style={{ marginTop: 'var(--space-3)', whiteSpace: 'pre-wrap', fontSize: 'var(--font-xs)', color: 'var(--color-text-secondary)' }}>
                            {JSON.stringify(inspectorNodes.slice(0, 6), null, 2)}
                          </pre>
                        </div>
                        <div className="card" style={{ background: 'rgba(10,14,23,0.96)', borderColor: 'var(--color-border)' }}>
                          <div className="card__title">Chunks y proposiciones</div>
                          <pre style={{ marginTop: 'var(--space-3)', whiteSpace: 'pre-wrap', fontSize: 'var(--font-xs)', color: 'var(--color-text-secondary)' }}>
                            {JSON.stringify({ chunks: inspectorChunks.slice(0, 4), propositions: inspectorPropositions.slice(0, 4) }, null, 2)}
                          </pre>
                        </div>
                      </div>
                    )}
                  </section>
                </>
              ) : (
                <div className="rag-audit-trace" style={{ display: 'grid', gap: 'var(--space-4)', color: 'var(--color-text-primary)' }}>
                  {/* Paso 1: Router */}
                  <div className="card" style={{ background: 'rgba(255,255,255,0.02)', padding: 'var(--space-3)', borderColor: 'rgba(255,255,255,0.06)' }}>
                    <div style={{ fontWeight: 'var(--font-weight-bold)', display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                      <span style={{ display: 'inline-flex', width: '1.4rem', height: '1.4rem', background: 'rgba(99,102,241,0.85)', borderRadius: '50%', color: '#fff', alignItems: 'center', justifyContent: 'center', fontSize: 'var(--font-xs)' }}>1</span>
                      Router & Planificación
                    </div>
                    <div style={{ marginTop: 'var(--space-2)', fontSize: 'var(--font-sm)', display: 'grid', gap: 'var(--space-2)' }}>
                      <div><strong>Modo seleccionado:</strong> <span className="query-chip" style={{ background: 'rgba(99,102,241,0.2)', color: '#818cf8', display: 'inline-block', margin: '0 0.2rem' }}>{activeTurn.routeMode}</span></div>
                      <div><strong>Intento detectado:</strong> <code>{activeTurn.intent}</code></div>
                      <div><strong>Razón del enrutamiento:</strong> {activeAnswer?.route_reason || 'Selección de ruta basada en la densidad y el formato de la consulta.'}</div>
                    </div>
                  </div>

                  {/* Paso 2: Hybrid Retrieval */}
                  <div className="card" style={{ background: 'rgba(255,255,255,0.02)', padding: 'var(--space-3)', borderColor: 'rgba(255,255,255,0.06)' }}>
                    <div style={{ fontWeight: 'var(--font-weight-bold)', display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                      <span style={{ display: 'inline-flex', width: '1.4rem', height: '1.4rem', background: 'rgba(99,102,241,0.85)', borderRadius: '50%', color: '#fff', alignItems: 'center', justifyContent: 'center', fontSize: 'var(--font-xs)' }}>2</span>
                      Recuperación Híbrida & RRF
                    </div>
                    <div style={{ marginTop: 'var(--space-2)', display: 'grid', gap: 'var(--space-2)', maxHeight: '200px', overflow: 'auto', paddingRight: 'var(--space-1)' }}>
                      {activeSearchHits.length === 0 ? (
                        <p className="query-panel-note">No hay evidencias recuperadas en este turno.</p>
                      ) : (
                        activeSearchHits.map((hit, idx) => {
                          const denseScore = hit.metadata?.dense_score ?? hit.metadata?.vector_score;
                          const sparseScore = hit.metadata?.sparse_score ?? hit.metadata?.bm25_score;
                          return (
                            <div key={hit.id} style={{ fontSize: 'var(--font-xs)', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: 'var(--space-2)' }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 'var(--font-weight-semibold)' }}>
                                <span>#{idx + 1} - {hit.title.slice(0, 30)}... ({hit.source_type})</span>
                                <span style={{ color: '#818cf8' }}>Rank: {hit.rank}</span>
                              </div>
                              <div style={{ color: 'var(--color-text-tertiary)', marginTop: '0.15rem' }}>
                                <span>Score RRF: {hit.score.toFixed(4)}</span>
                                {denseScore !== undefined && <span> | Vector: {Number(denseScore).toFixed(4)}</span>}
                                {sparseScore !== undefined && <span> | Sparse: {Number(sparseScore).toFixed(4)}</span>}
                              </div>
                            </div>
                          );
                        })
                      )}
                    </div>
                  </div>

                  {/* Paso 3: Reranker */}
                  <div className="card" style={{ background: 'rgba(255,255,255,0.02)', padding: 'var(--space-3)', borderColor: 'rgba(255,255,255,0.06)' }}>
                    <div style={{ fontWeight: 'var(--font-weight-bold)', display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                      <span style={{ display: 'inline-flex', width: '1.4rem', height: '1.4rem', background: 'rgba(99,102,241,0.85)', borderRadius: '50%', color: '#fff', alignItems: 'center', justifyContent: 'center', fontSize: 'var(--font-xs)' }}>3</span>
                      Reranker Neuronal (Cross-Encoder)
                    </div>
                    <div style={{ marginTop: 'var(--space-2)', fontSize: 'var(--font-xs)' }}>
                      {activeSearchHits.some(hit => hit.metadata?.rerank_score !== undefined) ? (
                        <div style={{ display: 'grid', gap: 'var(--space-2)' }}>
                          <p className="query-panel-note" style={{ color: 'var(--color-success)', margin: 0 }}>Reranking neuronal ejecutado con CUDA float16.</p>
                          {activeSearchHits.slice(0, 3).map((hit) => {
                            const rerankScore = hit.metadata?.rerank_score;
                            const originalScore = typeof hit.metadata?.original_score === 'number' ? hit.metadata.original_score : hit.score;
                            return (
                              <div key={hit.id}>
                                <strong>{hit.title.slice(0, 15)}...</strong>: original: {originalScore.toFixed(4)} → neural: {Number(rerankScore).toFixed(4)}
                              </div>
                            );
                          })}
                        </div>
                      ) : (
                        <p className="query-panel-note" style={{ margin: 0 }}>Reranker no activo o sin cambios para este tipo de búsqueda.</p>
                      )}
                    </div>
                  </div>

                  {/* Paso 4: Prompt Final */}
                  <div className="card" style={{ background: 'rgba(255,255,255,0.02)', padding: 'var(--space-3)', borderColor: 'rgba(255,255,255,0.06)' }}>
                    <div style={{ fontWeight: 'var(--font-weight-bold)', display: 'flex', alignItems: 'center', gap: 'var(--space-2)', justifyContent: 'space-between' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                        <span style={{ display: 'inline-flex', width: '1.4rem', height: '1.4rem', background: 'rgba(99,102,241,0.85)', borderRadius: '50%', color: '#fff', alignItems: 'center', justifyContent: 'center', fontSize: 'var(--font-xs)' }}>4</span>
                        Prompt Final (LLM Input)
                      </div>
                      {activeAnswer?.full_prompt && (
                        <button
                          type="button"
                          className="btn btn-secondary"
                          style={{ padding: '0.1rem 0.4rem', fontSize: 'var(--font-xs)' }}
                          onClick={() => {
                            navigator.clipboard.writeText(activeAnswer.full_prompt || '');
                            alert('Copiado al portapapeles');
                          }}
                        >
                          Copiar
                        </button>
                      )}
                    </div>
                    <div style={{ marginTop: 'var(--space-2)' }}>
                      {activeAnswer?.full_prompt ? (
                        <pre style={{ margin: 0, padding: 'var(--space-2)', background: 'rgba(0,0,0,0.3)', borderRadius: 'var(--radius-md)', maxHeight: '180px', overflow: 'auto', whiteSpace: 'pre-wrap', fontSize: 'var(--font-xs)', color: 'var(--color-text-secondary)', fontFamily: 'monospace' }}>
                          {activeAnswer.full_prompt}
                        </pre>
                      ) : (
                        <p className="query-panel-note" style={{ margin: 0 }}>El prompt final no está cacheado para este turno.</p>
                      )}
                    </div>
                  </div>

                  {/* Paso 5: Métricas */}
                  <div className="card" style={{ background: 'rgba(255,255,255,0.02)', padding: 'var(--space-3)', borderColor: 'rgba(255,255,255,0.06)' }}>
                    <div style={{ fontWeight: 'var(--font-weight-bold)', display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                      <span style={{ display: 'inline-flex', width: '1.4rem', height: '1.4rem', background: 'rgba(99,102,241,0.85)', borderRadius: '50%', color: '#fff', alignItems: 'center', justifyContent: 'center', fontSize: 'var(--font-xs)' }}>5</span>
                      Métricas & Tokens
                    </div>
                    <div style={{ marginTop: 'var(--space-2)', display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 'var(--space-2)' }}>
                      <div className="query-answer__metric" style={{ background: 'rgba(0,0,0,0.2)', border: 'none' }}>
                        <div className="query-answer__label">Input Tokens</div>
                        <div className="query-answer__value">{activeAnswer?.input_token_count ?? '—'}</div>
                      </div>
                      <div className="query-answer__metric" style={{ background: 'rgba(0,0,0,0.2)', border: 'none' }}>
                        <div className="query-answer__label">Output Tokens</div>
                        <div className="query-answer__value">{activeAnswer?.output_token_count ?? '—'}</div>
                      </div>
                      <div className="query-answer__metric" style={{ background: 'rgba(0,0,0,0.2)', border: 'none', gridColumn: 'span 2' }}>
                        <div className="query-answer__label">Chat History Usado</div>
                        <div className="query-answer__value">{activeAnswer?.chat_history_used ? 'Sí' : 'No'}</div>
                      </div>
                      {activeAnswer?.chat_history_json && (
                        <div style={{ gridColumn: 'span 2' }}>
                          <span style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)' }}>Turns serializados:</span>
                          <pre style={{ margin: '0.2rem 0 0 0', padding: 'var(--space-2)', background: 'rgba(0,0,0,0.3)', borderRadius: 'var(--radius-sm)', maxHeight: '80px', overflow: 'auto', whiteSpace: 'pre-wrap', fontSize: 'var(--font-xs)' }}>
                            {activeAnswer.chat_history_json}
                          </pre>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Paso 6: Calidad */}
                  <div className="card" style={{ background: 'rgba(255,255,255,0.02)', padding: 'var(--space-3)', borderColor: 'rgba(255,255,255,0.06)' }}>
                    <div style={{ fontWeight: 'var(--font-weight-bold)', display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                      <span style={{ display: 'inline-flex', width: '1.4rem', height: '1.4rem', background: 'rgba(99,102,241,0.85)', borderRadius: '50%', color: '#fff', alignItems: 'center', justifyContent: 'center', fontSize: 'var(--font-xs)' }}>6</span>
                      Grounding & Auditoría
                    </div>
                    <div style={{ marginTop: 'var(--space-2)', fontSize: 'var(--font-sm)', display: 'grid', gap: 'var(--space-2)' }}>
                      <div><strong>Verdict:</strong> <span className={`badge badge--${activeTurn.verdict === 'verified' ? 'success' : activeTurn.verdict === 'partially_verified' ? 'warning' : 'error'}`} style={{ marginLeft: '0.3rem' }}>{activeTurn.verdict}</span></div>
                      <div><strong>Score Grounding:</strong> <code>{activeTurn.groundingScore?.toFixed(3) ?? '—'}</code></div>
                      {activeAnswer?.verification_issues && activeAnswer.verification_issues.length > 0 ? (
                        <div>
                          <strong style={{ color: 'var(--color-error)' }}>Problemas hallados:</strong>
                          <ul style={{ margin: '0.2rem 0 0 0', paddingLeft: '1.1rem', color: 'var(--color-text-secondary)', fontSize: 'var(--font-xs)' }}>
                            {activeAnswer.verification_issues.map((issue, idx) => <li key={idx}>{issue}</li>)}
                          </ul>
                        </div>
                      ) : (
                        <div style={{ color: 'var(--color-success)', fontWeight: 'var(--font-weight-semibold)', fontSize: 'var(--font-xs)' }}>✓ Grounding verificado sin problemas.</div>
                      )}
                    </div>
                  </div>
                </div>
              )
            ) : (
              <p className="query-panel-note">
                {pendingQuery
                  ? `Consulta en curso: "${pendingQuery}". Los detalles técnicos se actualizarán automáticamente.`
                  : 'Inicia una conversación para ver detalles técnicos.'}
              </p>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}

export function JobsPage() {
  const [jobs, setJobs] = useState<import('../types/api').Job[]>([]);
  const [selectedJobId, setSelectedJobId] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const selectedJobIdRef = useRef('');

  useEffect(() => {
    selectedJobIdRef.current = selectedJobId;
  }, [selectedJobId]);

  const refreshJobs = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const items = await api.listJobs();
      setJobs(items);
      setSelectedJobId(current => current || selectedJobIdRef.current || items[0]?.id || '');
    } catch (jobError) {
      setError(jobError instanceof Error ? jobError.message : 'No se pudieron cargar las tareas.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshJobs();
  }, [refreshJobs]);

  useEffect(() => {
    if (selectedJobId || jobs.length === 0) return;
    setSelectedJobId(jobs[0].id);
  }, [jobs, selectedJobId]);

  const selectedJob = jobs.find(job => job.id === selectedJobId) ?? jobs[0] ?? null;

  return (
    <div className="animate-fade-in-up">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-6)' }}>
        <div>
          <h2 style={{ fontSize: 'var(--font-xl)', fontWeight: 'var(--font-weight-bold)' }}>Tareas</h2>
          <p style={{ color: 'var(--color-text-tertiary)', marginTop: 'var(--space-1)' }}>Estado vivo del pipeline, errores persistidos y reintentos.</p>
        </div>
        <button className="btn btn-primary" type="button" onClick={() => void refreshJobs()} disabled={loading}>
          {loading ? 'Actualizando...' : 'Refrescar'}
        </button>
      </div>

      {error ? (
        <div className="card" style={{ marginBottom: 'var(--space-5)' }}>
          <p style={{ color: 'var(--color-error)' }}>{error}</p>
        </div>
      ) : null}

      <div className="jobs-grid" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.2fr) minmax(320px, 0.8fr)', gap: 'var(--space-5)' }}>
        <section className="card" style={{ display: 'grid', gap: 'var(--space-4)' }}>
          <div className="card__header">
            <div>
              <div className="card__title">Jobs recientes</div>
              <p style={{ color: 'var(--color-text-tertiary)', marginTop: 'var(--space-1)' }}>Parseo, embeddings, summaries, visual indexing y rebuilds.</p>
            </div>
            <span className="badge badge--accent">{jobs.length}</span>
          </div>

          <div style={{ display: 'grid', gap: 'var(--space-3)' }}>
            {jobs.length === 0 ? (
              <div className="empty-state" style={{ padding: 'var(--space-6) var(--space-4)' }}>
                <div className="empty-state__icon" aria-hidden="true"><EmptyStateGlyph name="refresh" /></div>
                <div className="empty-state__title">No hay tareas todavía</div>
                <p>Cuando un documento entra en el pipeline, aparecerá aquí con su estado real.</p>
              </div>
            ) : (
              jobs.map(job => {
                const isSelected = selectedJob?.id === job.id;
                const hasError = Boolean(job.error);
                const tone = job.status === 'failed' || hasError ? 'error' : job.status === 'succeeded' ? 'success' : job.status === 'running' ? 'warning' : 'accent';
                const badgeLabel = job.status === 'pending' && hasError ? 'Con error' : job.status;
                return (
                  <article
                    key={job.id}
                    className="card"
                    role="button"
                    tabIndex={0}
                    onClick={() => setSelectedJobId(job.id)}
                    onKeyDown={event => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        setSelectedJobId(job.id);
                      }
                    }}
                    style={{
                      cursor: 'pointer',
                      padding: 'var(--space-4)',
                      background: isSelected ? 'linear-gradient(180deg, rgba(99,102,241,0.08), rgba(15,20,31,0.92))' : 'var(--color-bg-primary)',
                      borderColor: isSelected ? 'rgba(99,102,241,0.55)' : 'var(--color-border)',
                    }}
                  >
                    <div className="card__header" style={{ marginBottom: 'var(--space-3)' }}>
                      <div>
                        <div className="card__title">{job.job_type}</div>
                        <p style={{ color: 'var(--color-text-tertiary)', marginTop: 'var(--space-1)' }}>{job.target_id}</p>
                      </div>
                      <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                        <span className={`badge badge--${tone}`}>{badgeLabel}</span>
                        <span className="badge badge--info">{job.retries} reintentos</span>
                      </div>
                    </div>
                    <div className="progress-track">
                      <div className={`progress-fill progress-fill--${tone}`} style={{ width: job.status === 'succeeded' ? '100%' : job.status === 'running' ? '70%' : job.status === 'failed' ? '100%' : '15%' }} />
                    </div>
                    <div className="queue-item__bottom" style={{ marginTop: 'var(--space-3)' }}>
                      <span className="queue-item__stage">{hasError ? 'Error persistido' : job.started_at ? `Inicio ${formatRelativeDate(job.started_at)}` : 'Pendiente de inicio'}</span>
                      <span className="queue-item__status">{job.completed_at ? `Fin ${formatRelativeDate(job.completed_at)}` : hasError ? 'con error' : 'Activo'}</span>
                    </div>
                    {job.error ? <p style={{ marginTop: 'var(--space-2)', color: 'var(--color-error)', lineHeight: 'var(--line-height-relaxed)' }}>{job.error}</p> : null}
                  </article>
                );
              })
            )}
          </div>
        </section>

        <aside className="card" style={{ display: 'grid', gap: 'var(--space-4)', background: 'var(--color-bg-primary)', borderColor: 'var(--color-border)' }}>
          <div className="card__header">
            <div>
              <div className="card__title">Detalle del job</div>
              <p style={{ color: 'var(--color-text-tertiary)', marginTop: 'var(--space-1)' }}>Útil para ver por qué un archivo falló o se quedó atascado.</p>
            </div>
            <span className="badge badge--accent">{selectedJob ? selectedJob.status : 'sin selección'}</span>
          </div>

          {selectedJob ? (
            <>
              <div className="card" style={{ background: 'rgba(10,14,23,0.96)', borderColor: 'var(--color-border)' }}>
                <div style={{ display: 'grid', gap: 'var(--space-2)' }}>
                  <div style={{ fontWeight: 'var(--font-weight-semibold)' }}>{selectedJob.job_type}</div>
                  <div style={{ color: 'var(--color-text-tertiary)', fontSize: 'var(--font-xs)' }}>{selectedJob.target_id}</div>
                  <div style={{ color: 'var(--color-text-tertiary)', fontSize: 'var(--font-xs)' }}>Job ID: {selectedJob.id}</div>
                  <div style={{ color: 'var(--color-text-tertiary)', fontSize: 'var(--font-xs)' }}>Reintentos: {selectedJob.retries}</div>
                  {selectedJob.error ? (
                    <div style={{ padding: 'var(--space-3)', borderRadius: 'var(--radius-md)', background: 'rgba(239, 68, 68, 0.12)', border: '1px solid rgba(239, 68, 68, 0.35)', color: 'var(--color-error)', lineHeight: 'var(--line-height-relaxed)' }}>
                      {selectedJob.error}
                    </div>
                  ) : (
                    <p style={{ color: 'var(--color-text-tertiary)' }}>No hay error persistido para este job.</p>
                  )}
                </div>
              </div>

              <div className="card" style={{ background: 'rgba(10,14,23,0.96)', borderColor: 'var(--color-border)' }}>
                <div className="card__title">Timestamps</div>
                <div style={{ display: 'grid', gap: 'var(--space-2)', marginTop: 'var(--space-3)' }}>
                  <div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)' }}>Creado: {formatRelativeDate(selectedJob.created_at)}</div>
                  <div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)' }}>Iniciado: {selectedJob.started_at ? formatRelativeDate(selectedJob.started_at) : '—'}</div>
                  <div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)' }}>Completado: {selectedJob.completed_at ? formatRelativeDate(selectedJob.completed_at) : '—'}</div>
                </div>
              </div>
            </>
          ) : (
            <div className="empty-state" style={{ padding: 'var(--space-8) var(--space-4)' }}>
              <div className="empty-state__icon" aria-hidden="true"><EmptyStateGlyph name="search" /></div>
              <div className="empty-state__title">Selecciona un job</div>
              <p>Verás el error, los reintentos y las marcas temporales aquí.</p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

export function ObservabilityPage() {
  const [entityType, setEntityType] = useState('');
  const [entityId, setEntityId] = useState('');
  const [runId, setRunId] = useState('');
  const [limit, setLimit] = useState('40');
  const [auditEntries, setAuditEntries] = useState<PipelineAuditEntry[]>([]);
  const [selectedAuditId, setSelectedAuditId] = useState('');
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState('');
  const [evidence, setEvidence] = useState<DocumentEvidenceResponse | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState('');
  const [message, setMessage] = useState('');
  const auditFiltersRef = useRef({
    entityType: '',
    entityId: '',
    runId: '',
    limit: '40',
  });

  const selectedAudit = auditEntries.find(entry => entry.id === selectedAuditId) ?? auditEntries[0] ?? null;

  useEffect(() => {
    auditFiltersRef.current = {
      entityType,
      entityId,
      runId,
      limit,
    };
  }, [entityType, entityId, runId, limit]);

  const refreshAudit = useCallback(async () => {
    setAuditLoading(true);
    setAuditError('');
    try {
      const currentFilters = auditFiltersRef.current;
      const nextLimit = Math.max(1, Math.min(100, Number(currentFilters.limit) || 40));
      const nextParams: { entityType?: string; entityId?: string; runId?: string; limit?: number } = { limit: nextLimit };

      if (currentFilters.runId.trim()) {
        nextParams.runId = currentFilters.runId.trim();
      } else if (currentFilters.entityType.trim() && currentFilters.entityType !== 'all' && currentFilters.entityId.trim()) {
        nextParams.entityType = currentFilters.entityType.trim();
        nextParams.entityId = currentFilters.entityId.trim();
      }

      const items = await api.listPipelineAudit(nextParams);
      setAuditEntries(items);
      setSelectedAuditId(current => (items.some(entry => entry.id === current) ? current : items[0]?.id ?? ''));
    } catch (error) {
      setAuditError(error instanceof Error ? error.message : 'No se pudo cargar la observabilidad.');
      setAuditEntries([]);
      setSelectedAuditId('');
    } finally {
      setAuditLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshAudit();
  }, [refreshAudit]);

  useEffect(() => {
    if (!selectedAudit) {
      setEvidence(null);
      return;
    }

    if (selectedAudit.entity_type !== 'document') {
      setEvidence(null);
      setEvidenceError('');
      return;
    }

    let active = true;
    setEvidenceLoading(true);
    setEvidenceError('');
    api.getDocumentEvidence(selectedAudit.entity_id)
      .then(result => {
        if (!active) return;
        setEvidence(result);
      })
      .catch(error => {
        if (!active) return;
        setEvidence(null);
        setEvidenceError(error instanceof Error ? error.message : 'No se pudo cargar la evidencia del documento.');
      })
      .finally(() => {
        if (active) setEvidenceLoading(false);
      });

    return () => {
      active = false;
    };
  }, [selectedAudit]);

  const summary = useMemo(() => {
    const total = auditEntries.length;
    const failed = auditEntries.filter(entry => entry.status === 'failed').length;
    const averageDuration = total === 0 ? 0 : auditEntries.reduce((acc, entry) => acc + (entry.duration_ms ?? 0), 0) / total;
    const pipelines = new Set(auditEntries.map(entry => entry.pipeline));
    return { total, failed, averageDuration, pipelines: pipelines.size };
  }, [auditEntries]);

  const copyEvidence = async () => {
    if (!evidence) return;
    await navigator.clipboard.writeText(JSON.stringify(evidence, null, 2));
    setMessage(`Evidencia copiada para ${evidence.document.title}.`);
  };

  return (
    <div className="animate-fade-in-up">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 'var(--space-4)', marginBottom: 'var(--space-6)', flexWrap: 'wrap' }}>
        <div>
          <h2 style={{ fontSize: 'var(--font-xl)', fontWeight: 'var(--font-weight-bold)' }}>Observabilidad</h2>
          <p style={{ color: 'var(--color-text-tertiary)', marginTop: 'var(--space-1)' }}>Audita eventos del pipeline, revisa métricas y abre la evidencia de un documento desde una sola pantalla.</p>
        </div>
        <button className="btn btn-primary" type="button" onClick={() => void refreshAudit()} disabled={auditLoading}>
          {auditLoading ? 'Actualizando...' : 'Refrescar'}
        </button>
      </div>

      {message ? (
        <div className="card" style={{ marginBottom: 'var(--space-5)' }}>
          <p style={{ color: 'var(--color-text-secondary)' }}>{message}</p>
        </div>
      ) : null}

      <div className="card" style={{ display: 'grid', gap: 'var(--space-4)', marginBottom: 'var(--space-6)' }}>
        <div className="card__header">
          <div>
            <div className="card__title">Filtros</div>
            <p style={{ color: 'var(--color-text-tertiary)', marginTop: 'var(--space-1)' }}>Puedes filtrar por `run_id` o por `entity_type` + `entity_id`.</p>
          </div>
          <span className="badge badge--accent">{summary.total} eventos</span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(160px, 180px) minmax(220px, 1fr) minmax(220px, 1fr) minmax(120px, 140px)', gap: 'var(--space-3)' }}>
          <select value={entityType} onChange={event => setEntityType(event.target.value)} style={{ width: '100%', padding: 'var(--space-4)', background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-lg)', color: 'var(--color-text-primary)' }}>
            <option value="">Todos los tipos</option>
            {AUDIT_ENTITY_TYPES.map(type => <option key={type} value={type}>{type}</option>)}
          </select>
          <input value={entityId} onChange={event => setEntityId(event.target.value)} placeholder="entity_id" style={{ width: '100%', padding: 'var(--space-4)', background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-lg)', color: 'var(--color-text-primary)' }} />
          <input value={runId} onChange={event => setRunId(event.target.value)} placeholder="run_id" style={{ width: '100%', padding: 'var(--space-4)', background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-lg)', color: 'var(--color-text-primary)' }} />
          <input value={limit} onChange={event => setLimit(event.target.value)} type="number" min="1" max="100" style={{ width: '100%', padding: 'var(--space-4)', background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-lg)', color: 'var(--color-text-primary)' }} />
        </div>

        <div style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
          <button className="btn btn-primary" type="button" onClick={() => void refreshAudit()} disabled={auditLoading}>Aplicar filtros</button>
          <button
            className="btn"
            type="button"
            onClick={() => {
              auditFiltersRef.current = {
                entityType: '',
                entityId: '',
                runId: '',
                limit: '40',
              };
              setEntityType('');
              setEntityId('');
              setRunId('');
              setLimit('40');
              setMessage('');
              void refreshAudit();
            }}
          >
            Limpiar
          </button>
          <span style={{ color: 'var(--color-text-tertiary)', alignSelf: 'center', fontSize: 'var(--font-xs)' }}>
            Si no rellenas `entity_id`, la vista mostrará los eventos recientes.
          </span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 'var(--space-4)', marginBottom: 'var(--space-6)' }}>
        <div className="card">
          <div className="card__title">Eventos</div>
          <p style={{ marginTop: 'var(--space-2)', fontSize: 'var(--font-2xl)', fontWeight: 'var(--font-weight-bold)' }}>{summary.total}</p>
        </div>
        <div className="card">
          <div className="card__title">Fallos</div>
          <p style={{ marginTop: 'var(--space-2)', fontSize: 'var(--font-2xl)', fontWeight: 'var(--font-weight-bold)' }}>{summary.failed}</p>
        </div>
        <div className="card">
          <div className="card__title">Pipelines</div>
          <p style={{ marginTop: 'var(--space-2)', fontSize: 'var(--font-2xl)', fontWeight: 'var(--font-weight-bold)' }}>{summary.pipelines}</p>
        </div>
        <div className="card">
          <div className="card__title">Duración media</div>
          <p style={{ marginTop: 'var(--space-2)', fontSize: 'var(--font-2xl)', fontWeight: 'var(--font-weight-bold)' }}>{summary.averageDuration.toFixed(1)} ms</p>
        </div>
      </div>

      {auditError ? (
        <div className="card" style={{ marginBottom: 'var(--space-5)' }}>
          <p style={{ color: 'var(--color-error)' }}>{auditError}</p>
        </div>
      ) : null}

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.15fr) minmax(340px, 0.85fr)', gap: 'var(--space-5)' }}>
        <section className="card" style={{ display: 'grid', gap: 'var(--space-3)' }}>
          <div className="card__header">
            <div>
              <div className="card__title">Eventos recientes</div>
              <p style={{ color: 'var(--color-text-tertiary)', marginTop: 'var(--space-1)' }}>Ordenados por hora de inicio, con el estado y las métricas capturadas.</p>
            </div>
            <span className="badge badge--accent">{auditEntries.length}</span>
          </div>

          {auditEntries.length === 0 ? (
            <div className="empty-state" style={{ padding: 'var(--space-6) var(--space-4)' }}>
              <div className="empty-state__icon" aria-hidden="true"><EmptyStateGlyph name="target" /></div>
              <div className="empty-state__title">Sin eventos</div>
              <p>Afina los filtros o espera a que el pipeline genere actividad.</p>
            </div>
          ) : (
            auditEntries.map(entry => {
              const isSelected = selectedAudit?.id === entry.id;
              const tone = entry.status === 'failed' ? 'error' : entry.status === 'succeeded' ? 'success' : 'warning';
              return (
                <article
                  key={entry.id}
                  className="card"
                  role="button"
                  tabIndex={0}
                  onClick={() => setSelectedAuditId(entry.id)}
                  onKeyDown={event => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      setSelectedAuditId(entry.id);
                    }
                  }}
                  style={{
                    cursor: 'pointer',
                    background: isSelected ? 'linear-gradient(180deg, rgba(99,102,241,0.08), rgba(15,20,31,0.92))' : 'var(--color-bg-primary)',
                    borderColor: isSelected ? 'rgba(99,102,241,0.55)' : 'var(--color-border)',
                  }}
                >
                  <div className="card__header" style={{ marginBottom: 'var(--space-2)' }}>
                    <div>
                      <div className="card__title">{entry.stage}</div>
                      <p style={{ color: 'var(--color-text-tertiary)', marginTop: 'var(--space-1)' }}>{entry.pipeline} · {entry.entity_type}/{entry.entity_id}</p>
                    </div>
                    <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                      <span className={`badge badge--${tone}`}>{entry.status}</span>
                      <span className="badge badge--info">{entry.duration_ms !== null && entry.duration_ms !== undefined ? `${entry.duration_ms.toFixed(1)} ms` : 'sin duración'}</span>
                    </div>
                  </div>
                  <div style={{ display: 'grid', gap: 'var(--space-2)' }}>
                    <div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)' }}>Run: {entry.run_id}</div>
                    <div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)' }}>Inicio: {formatRelativeDate(entry.started_at)}</div>
                    <div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)' }}>Fin: {entry.completed_at ? formatRelativeDate(entry.completed_at) : '—'}</div>
                  </div>
                </article>
              );
            })
          )}
        </section>

        <aside className="card" style={{ display: 'grid', gap: 'var(--space-4)', background: 'var(--color-bg-primary)', borderColor: 'var(--color-border)' }}>
          <div className="card__header">
            <div>
              <div className="card__title">Detalle</div>
              <p style={{ color: 'var(--color-text-tertiary)', marginTop: 'var(--space-1)' }}>Métricas, contexto y evidencia vinculada al evento seleccionado.</p>
            </div>
            <span className="badge badge--accent">{selectedAudit ? selectedAudit.status : 'sin selección'}</span>
          </div>

          {selectedAudit ? (
            <>
              <div className="card" style={{ background: 'rgba(10,14,23,0.96)', borderColor: 'var(--color-border)' }}>
                <div style={{ display: 'grid', gap: 'var(--space-2)' }}>
                  <div style={{ fontWeight: 'var(--font-weight-semibold)' }}>{selectedAudit.pipeline} · {selectedAudit.stage}</div>
                  <div style={{ color: 'var(--color-text-tertiary)', fontSize: 'var(--font-xs)' }}>{selectedAudit.entity_type}/{selectedAudit.entity_id}</div>
                  <div style={{ color: 'var(--color-text-tertiary)', fontSize: 'var(--font-xs)' }}>Run ID: {selectedAudit.run_id}</div>
                  <div style={{ color: 'var(--color-text-tertiary)', fontSize: 'var(--font-xs)' }}>Duración: {selectedAudit.duration_ms !== null && selectedAudit.duration_ms !== undefined ? `${selectedAudit.duration_ms.toFixed(1)} ms` : '—'}</div>
                </div>
              </div>

              <div className="card" style={{ background: 'rgba(10,14,23,0.96)', borderColor: 'var(--color-border)' }}>
                <div className="card__title">Métricas</div>
                <pre style={{ margin: 'var(--space-3) 0 0', whiteSpace: 'pre-wrap', background: 'rgba(255,255,255,0.03)', borderRadius: 'var(--radius-md)', padding: 'var(--space-3)', color: 'var(--color-text-secondary)', fontSize: 'var(--font-xs)', lineHeight: 'var(--line-height-relaxed)' }}>
                  {JSON.stringify(selectedAudit.metrics, null, 2)}
                </pre>
              </div>

              <div className="card" style={{ background: 'rgba(10,14,23,0.96)', borderColor: 'var(--color-border)' }}>
                <div className="card__title">Contexto</div>
                <pre style={{ margin: 'var(--space-3) 0 0', whiteSpace: 'pre-wrap', background: 'rgba(255,255,255,0.03)', borderRadius: 'var(--radius-md)', padding: 'var(--space-3)', color: 'var(--color-text-secondary)', fontSize: 'var(--font-xs)', lineHeight: 'var(--line-height-relaxed)' }}>
                  {JSON.stringify(selectedAudit.context, null, 2)}
                </pre>
              </div>

              <div className="card" style={{ background: 'rgba(10,14,23,0.96)', borderColor: 'var(--color-border)' }}>
                <div className="card__title">Evidencia del documento</div>
                {selectedAudit.entity_type === 'document' ? (
                  evidenceLoading ? (
                    <p style={{ marginTop: 'var(--space-3)', color: 'var(--color-text-tertiary)' }}>Cargando evidencia...</p>
                  ) : evidenceError ? (
                    <p style={{ marginTop: 'var(--space-3)', color: 'var(--color-error)' }}>{evidenceError}</p>
                  ) : evidence ? (
                    <div style={{ display: 'grid', gap: 'var(--space-3)', marginTop: 'var(--space-3)' }}>
                      <div>
                        <div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)' }}>Documento</div>
                        <div style={{ fontWeight: 'var(--font-weight-semibold)' }}>{evidence.document.title}</div>
                        <div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)' }}>{evidence.document.status} · {evidence.document.mime_type}</div>
                      </div>
                      <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
                        <span className="badge badge--info">{evidence.jobs.length} jobs</span>
                        <span className="badge badge--info">{evidence.audit_events.length} eventos</span>
                      </div>
                      <button className="btn btn-primary" type="button" onClick={() => void copyEvidence()}>
                        Copiar evidencia JSON
                      </button>
                      <pre style={{ margin: 0, whiteSpace: 'pre-wrap', background: 'rgba(255,255,255,0.03)', borderRadius: 'var(--radius-md)', padding: 'var(--space-3)', color: 'var(--color-text-secondary)', fontSize: 'var(--font-xs)', lineHeight: 'var(--line-height-relaxed)', maxHeight: '260px', overflow: 'auto' }}>
{JSON.stringify({ document: evidence.document, jobs: evidence.jobs.slice(0, 2), audit_events: evidence.audit_events.slice(0, 2) }, null, 2)}
                      </pre>
                    </div>
                  ) : (
                    <p style={{ marginTop: 'var(--space-3)', color: 'var(--color-text-tertiary)' }}>Selecciona un evento de documento para ver su paquete de evidencia.</p>
                  )
                ) : (
                  <p style={{ marginTop: 'var(--space-3)', color: 'var(--color-text-tertiary)' }}>La evidencia detallada sólo se genera para eventos de documentos.</p>
                )}
              </div>
            </>
          ) : (
            <div className="empty-state" style={{ padding: 'var(--space-8) var(--space-4)' }}>
              <div className="empty-state__icon" aria-hidden="true"><EmptyStateGlyph name="target" /></div>
              <div className="empty-state__title">Selecciona un evento</div>
              <p>Verás métricas, contexto y la evidencia del documento asociado aquí.</p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

export function EvaluationPage() {
  const [collections, setCollections] = useState<Collection[]>([]);
  const [datasets, setDatasets] = useState<string[]>([]);
  const [runs, setRuns] = useState<EvaluationRunResponse[]>([]);
  const [selectedCollectionId, setSelectedCollectionId] = useState('');
  const [selectedDataset, setSelectedDataset] = useState('baseline');
  const [report, setReport] = useState<EvaluationReportResponse | null>(null);
  const [bootstrapping, setBootstrapping] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const refreshRuns = async () => {
    const items = await api.listEvaluationRuns();
    setRuns(items);
    if (!report && items[0]) {
      const detail = await api.getEvaluationReport(items[0].id);
      setReport(detail);
    }
  };

  useEffect(() => {
    let mounted = true;

    const bootstrap = async () => {
      setBootstrapping(true);
      setError('');

      const [collectionsResult, datasetsResult, runsResult] = await Promise.allSettled([
        api.listCollections(),
        api.listEvaluationDatasets(),
        api.listEvaluationRuns(),
      ]);

      if (!mounted) return;

      const errors: string[] = [];

      if (collectionsResult.status === 'fulfilled') {
        setCollections(collectionsResult.value);
        setSelectedCollectionId(current => current || collectionsResult.value[0]?.id || '');
      } else {
        errors.push('colecciones');
      }

      if (datasetsResult.status === 'fulfilled') {
        setDatasets(datasetsResult.value);
        setSelectedDataset(current => current || datasetsResult.value[0] || 'baseline');
      } else {
        errors.push('datasets');
      }

      if (runsResult.status === 'fulfilled') {
        const runItems = runsResult.value;
        setRuns(runItems);
        if (runItems[0]) {
          try {
            const detail = await api.getEvaluationReport(runItems[0].id);
            if (mounted) setReport(detail);
          } catch {
            if (mounted) setReport(null);
          }
        } else {
          setReport(null);
        }
      } else {
        errors.push('ejecuciones');
      }

      if (errors.length > 0) {
        setError(`No se pudieron cargar: ${errors.join(', ')}.`);
      }

      setBootstrapping(false);
    };

    void bootstrap();

    return () => {
      mounted = false;
    };
  }, []);

  const handleRun = async () => {
    if (!selectedCollectionId) return;
    setLoading(true);
    setError('');
    try {
      const response = await api.runEvaluation({ collection_id: selectedCollectionId, dataset_name: selectedDataset });
      setReport(response);
      await refreshRuns();
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : 'La evaluación falló.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="animate-fade-in-up">
      <h2 style={{ fontSize: 'var(--font-xl)', fontWeight: 'var(--font-weight-bold)', marginBottom: 'var(--space-6)' }}>Evaluación</h2>
      <div className="card" style={{ display: 'grid', gap: 'var(--space-4)', marginBottom: 'var(--space-6)' }}>
        <div style={{ display: 'grid', gap: 'var(--space-3)', gridTemplateColumns: 'minmax(220px, 280px) minmax(220px, 280px) auto' }}>
          <select value={selectedCollectionId} onChange={event => setSelectedCollectionId(event.target.value)} style={{ width: '100%', padding: 'var(--space-4)', background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-lg)', color: 'var(--color-text-primary)' }}>
            {collections.length === 0 ? <option value="">No hay colecciones</option> : collections.map(collection => <option key={collection.id} value={collection.id}>{collection.name}</option>)}
          </select>
          <select value={selectedDataset} onChange={event => setSelectedDataset(event.target.value)} style={{ width: '100%', padding: 'var(--space-4)', background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-lg)', color: 'var(--color-text-primary)' }}>
            {datasets.map(dataset => <option key={dataset} value={dataset}>{dataset}</option>)}
          </select>
          <button className="btn btn-primary" onClick={handleRun} disabled={!selectedCollectionId || loading || bootstrapping}>{loading ? 'Ejecutando...' : 'Ejecutar evaluación'}</button>
        </div>
        {error ? <p style={{ color: 'var(--color-error)' }}>{error}</p> : null}
      </div>

      {bootstrapping ? (
        <div className="empty-state">
          <div className="empty-state__icon" aria-hidden="true"><EmptyStateGlyph name="pulse" /></div>
          <div className="empty-state__title">Cargando evaluación</div>
          <p>Consultando colecciones, datasets y ejecuciones recientes.</p>
        </div>
      ) : report ? (
        <div style={{ display: 'grid', gap: 'var(--space-6)' }}>
          <div className="card" style={{ display: 'grid', gap: 'var(--space-4)' }}>
            <div className="card__header">
              <div className="card__title">Última ejecución</div>
              <span className="badge badge--accent">{report.dataset_name}</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 'var(--space-4)' }}>
              <div><div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)' }}>Recall@k</div><div style={{ fontWeight: 'var(--font-weight-semibold)' }}>{report.retrieval_recall_at_k.toFixed(3)}</div></div>
              <div><div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)' }}>MRR</div><div style={{ fontWeight: 'var(--font-weight-semibold)' }}>{report.retrieval_mrr.toFixed(3)}</div></div>
              <div><div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)' }}>nDCG</div><div style={{ fontWeight: 'var(--font-weight-semibold)' }}>{report.retrieval_ndcg.toFixed(3)}</div></div>
              <div><div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)' }}>Fundamento</div><div style={{ fontWeight: 'var(--font-weight-semibold)' }}>{report.answer_grounding_score.toFixed(3)}</div></div>
              <div><div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)' }}>Relevancia</div><div style={{ fontWeight: 'var(--font-weight-semibold)' }}>{report.answer_relevance_score.toFixed(3)}</div></div>
              <div><div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)' }}>Claves delta</div><div style={{ fontWeight: 'var(--font-weight-semibold)' }}>{Object.keys(report.regression_delta).length}</div></div>
            </div>
          </div>

          <div className="card" style={{ display: 'grid', gap: 'var(--space-4)' }}>
            <div className="card__title">Resultados por caso</div>
            <div style={{ display: 'grid', gap: 'var(--space-4)' }}>
              {report.cases?.map(item => (
                <article key={item.id} className="card" style={{ background: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', display: 'grid', gap: 'var(--space-3)' }}>
                  <div className="card__header">
                    <div>
                      <div className="card__title">{item.category}</div>
                      <p style={{ color: 'var(--color-text-tertiary)', marginTop: 'var(--space-1)' }}>{item.question}</p>
                    </div>
                    <span className="badge badge--info">{item.route_mode}</span>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 'var(--space-3)' }}>
                    <div><div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)' }}>Cobertura</div><div>{item.retrieval_metrics.recall_at_k.toFixed(3)}</div></div>
                    <div><div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)' }}>Fundamento</div><div>{(item.answer_metrics.grounding ?? 0).toFixed(3)}</div></div>
                    <div><div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)' }}>Relevancia</div><div>{(item.answer_metrics.relevance ?? 0).toFixed(3)}</div></div>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className="empty-state">
          <div className="empty-state__icon" aria-hidden="true"><EmptyStateGlyph name="pulse" /></div>
          <div className="empty-state__title">Aún no hay ejecuciones</div>
          <p>Elige una colección y ejecuta el dataset base.</p>
        </div>
      )}

      {runs.length > 0 ? (
        <div className="card" style={{ marginTop: 'var(--space-6)', display: 'grid', gap: 'var(--space-4)' }}>
          <div className="card__title">Ejecuciones recientes</div>
          <div style={{ display: 'grid', gap: 'var(--space-3)' }}>
            {runs.map(run => (
              <button
                key={run.id}
                type="button"
                className="card"
                style={{ textAlign: 'left', background: 'var(--color-bg-primary)', borderColor: 'var(--color-border)' }}
                onClick={async () => setReport(await api.getEvaluationReport(run.id))}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
                  <span>{run.id}</span>
                  <span className="badge badge--accent">{run.dataset_name}</span>
                </div>
                <p style={{ marginTop: 'var(--space-2)', color: 'var(--color-text-tertiary)' }}>{run.created_at}</p>
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
