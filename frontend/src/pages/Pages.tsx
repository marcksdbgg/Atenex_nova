/* Page stubs for routing */
import { useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent } from 'react';

import { AnswerPanel } from '../components/AnswerPanel';
import { CitationSidebar } from '../components/CitationSidebar';
import { EvidenceCard } from '../components/EvidenceCard';
import { PageViewer } from '../components/PageViewer';
import { api } from '../services/api';
import type {
  AnswerResponse,
  Citation,
  Collection,
  Document,
  DocumentEvidenceResponse,
  EvaluationRunResponse,
  PipelineAuditEntry,
  QueryHit,
  QueryHistoryResponse,
  QuerySearchResponse,
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

function mapHistoryToTurn(item: QueryHistoryResponse): ChatTurn {
  return {
    id: item.query_id,
    queryId: item.query_id,
    query: item.query,
    answerId: item.answer_id ?? undefined,
    routeMode: item.route_mode,
    intent: item.intent,
    language: item.language,
    createdAt: item.created_at,
    kind: item.answer ? 'answer' : 'search',
    answer: item.answer ?? undefined,
    verdict: item.verdict ?? undefined,
    groundingScore: item.grounding_score ?? undefined,
    citationsCount: item.citations_count,
  };
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
  };
}

function mapAnswerResultToTurn(response: AnswerResponse): ChatTurn {
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
    hits: response.evidence,
    citations: response.citations,
  };
}

export function DashboardPage() {
  return (
    <div className="animate-fade-in-up">
      <h2 style={{ fontSize: 'var(--font-2xl)', fontWeight: 'var(--font-weight-bold)', marginBottom: 'var(--space-6)' }}>
        Bienvenido a <span style={{ background: 'var(--color-gradient-accent)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>Atenex Nova</span>
      </h2>
      <p style={{ color: 'var(--color-text-secondary)', maxWidth: '600px', lineHeight: 'var(--line-height-relaxed)' }}>
        Plataforma local de memoria documental y RAG de nueva generación.
        Carga documentos, construye memoria y obtén respuestas con grounding real.
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: 'var(--space-6)', marginTop: 'var(--space-8)' }}>
        {[
          { title: 'Colecciones', value: '—', icon: '▦', desc: 'Corpus documentales' },
          { title: 'Documentos', value: '—', icon: '📄', desc: 'Documentos indexados' },
          { title: 'Consultas', value: '—', icon: '⌕', desc: 'Consultas realizadas' },
          { title: 'Tareas', value: '—', icon: '⟳', desc: 'Trabajos procesados' },
        ].map(stat => (
          <div key={stat.title} className="card">
            <div className="card__header">
              <span style={{ fontSize: '1.5rem' }}>{stat.icon}</span>
              <span className="badge badge--accent">{stat.value}</span>
            </div>
            <div className="card__title">{stat.title}</div>
            <p style={{ fontSize: 'var(--font-sm)', color: 'var(--color-text-tertiary)', marginTop: 'var(--space-1)' }}>{stat.desc}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export function CollectionsPage() {
  const [collections, setCollections] = useState<Collection[]>([]);
  const [documentsByCollection, setDocumentsByCollection] = useState<Record<string, Document[]>>({});
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

  const queuedFileCount = useMemo(
    () =>
      Object.values(uploadQueues).reduce(
        (count, items) => count + items.filter(item => item.status === 'queued' || item.status === 'uploading').length,
        0,
      ),
    [uploadQueues],
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
          items.map(async collection => [collection.id, await api.listCollectionDocuments(collection.id)] as const),
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
      collectionIds.map(async collectionId => [collectionId, await api.listCollectionDocuments(collectionId)] as const),
    );
    const nextDocuments = Object.fromEntries(entries);
    setDocumentsByCollection(current => ({
      ...current,
      ...nextDocuments,
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

  const loadDocumentAudit = async (collectionId: string, document: Document) => {
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
  };

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
    setUploadQueues(current => ({
      ...current,
      [collectionId]: [...(current[collectionId] ?? []), ...batch],
    }));
    const collectionName = collections.find(collection => collection.id === collectionId)?.name ?? collectionId;
    setMessage(`Cola ampliada en ${collectionName}: ${batch.length} archivos añadidos.`);
    await processCollectionQueue(collectionId, batch);
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

  const processCollectionQueue = async (collectionId: string, initialBatch: UploadQueueItem[] = []) => {
    if (processingUploadsRef.current[collectionId]) return;

    setProcessingUploads(current => ({ ...current, [collectionId]: true }));

    try {
      let pendingBatch = initialBatch;
      while (true) {
        const queue = uploadQueuesRef.current[collectionId] ?? [];
        const batch = pendingBatch.length > 0 ? pendingBatch : queue.filter(item => item.status === 'queued').slice(0, 8);
        if (batch.length === 0) break;
        pendingBatch = [];

        await Promise.all(
          batch.map(async item => {
            updateQueueItem(collectionId, item.id, { status: 'uploading', message: 'Subiendo al servidor y registrando documento...' });
            try {
              const document = await api.uploadDocument(collectionId, item.file, {
                collectionPath: item.collectionPath,
                displayTitle: item.displayTitle,
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
      setMessage(`Carpeta importada: ${result.imported} archivos registrados sin duplicar bytes.`);
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
          <small>{erroredFileCount > 0 ? `${erroredFileCount} con error` : hasRebuildPolling ? 'rebuild en seguimiento' : 'sin actividad'}</small>
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
          <div className="empty-state__icon">▦</div>
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
                        <div className="empty-state__icon">⟲</div>
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
                        <div className="empty-state__icon">⌕</div>
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
                        <div className="empty-state__icon">⌕</div>
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
  const [loading, setLoading] = useState(false);
  const [loadingCollections, setLoadingCollections] = useState(true);
  const [loadingContext, setLoadingContext] = useState(false);
  const [error, setError] = useState('');
  const [activeAnswer, setActiveAnswer] = useState<AnswerResponse | null>(null);
  const [activeSearchHits, setActiveSearchHits] = useState<QueryHit[]>([]);

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

  useEffect(() => {
    if (!collectionId) return;
    let mounted = true;
    setLoadingContext(true);
    Promise.all([api.listCollectionDocuments(collectionId), api.listQueryHistory(collectionId, 12)])
      .then(([documents, history]) => {
        if (!mounted) return;
        setDocumentsByCollection(current => ({
          ...current,
          [collectionId]: documents,
        }));
        setHistoryByCollection(current => ({
          ...current,
          [collectionId]: history,
        }));
        const historyTurns = history.slice().reverse().map(mapHistoryToTurn);
        setTurns(historyTurns);
        const lastTurn = historyTurns.at(-1);
        setActiveTurnId(lastTurn?.id ?? '');
        if (lastTurn) {
          void hydrateTurn(lastTurn);
        } else {
          setActiveAnswer(null);
          setActiveSearchHits([]);
        }
      })
      .catch(() => {
        if (mounted) setError('No se pudo cargar la memoria de la colección.');
      })
      .finally(() => {
        if (mounted) setLoadingContext(false);
      });
    return () => {
      mounted = false;
    };
  }, [collectionId]);

  const currentCollection = useMemo(
    () => collections.find(collection => collection.id === collectionId) ?? null,
    [collections, collectionId],
  );

  const visibleDocuments = useMemo(
    () => (documentsByCollection[collectionId] ?? []).slice(0, MAX_VISIBLE_DOCUMENTS),
    [collectionId, documentsByCollection],
  );

  const recentMemory = useMemo(
    () => (historyByCollection[collectionId] ?? []).slice(0, 5),
    [collectionId, historyByCollection],
  );

  const activeTurn = useMemo(
    () => turns.find(turn => turn.id === activeTurnId) ?? turns.at(-1) ?? null,
    [activeTurnId, turns],
  );

  const hydrateTurn = async (turn: ChatTurn) => {
    setActiveTurnId(turn.id);
    if (turn.kind === 'answer' && turn.answerId) {
      try {
        const detail = await api.getAnswer(turn.answerId);
        setActiveAnswer(detail);
        setActiveSearchHits(detail.evidence);
        setTurns(current => current.map(item => (
          item.id === turn.id
            ? {
                ...item,
                answer: detail.answer,
                answerId: detail.answer_id,
                groundingScore: detail.grounding_score,
                verdict: detail.verdict,
                citationsCount: detail.citations.length,
                hits: detail.evidence,
                citations: detail.citations,
              }
            : item
        )));
        return;
      } catch {
        // fallback below
      }
    }

    setActiveAnswer(null);
    setActiveSearchHits(turn.hits ?? []);
  };

  const canSubmit = collectionId.length > 0 && query.trim().length > 0 && !loading && !loadingCollections;

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!collectionId || !query.trim()) return;
    setLoading(true);
    setError('');
    const prompt = query.trim();
    try {
      if (action === 'search') {
        const response = await api.searchQuery({
          collection_id: collectionId,
          query: prompt,
          mode,
        });
        const turn = mapSearchResultToTurn(response);
        setTurns(current => [...current, turn]);
        await hydrateTurn(turn);
      } else {
        const response = await api.answerQuery({
          collection_id: collectionId,
          query: prompt,
          mode,
          generation_profile: 'standard',
        });
        const turn = mapAnswerResultToTurn(response);
        setTurns(current => [...current, turn]);
        await hydrateTurn(turn);
      }
      setQuery('');
    } catch (submissionError) {
      setError(submissionError instanceof Error ? submissionError.message : 'La consulta falló.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="animate-fade-in-up" style={{ display: 'grid', gap: 'var(--space-6)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 'var(--space-4)', flexWrap: 'wrap' }}>
        <div>
          <h2 style={{ fontSize: 'var(--font-xl)', fontWeight: 'var(--font-weight-bold)' }}>Espacio de consulta</h2>
          <p style={{ color: 'var(--color-text-tertiary)', marginTop: 'var(--space-1)' }}>Chat con memoria por colección, respuestas fundamentadas y acceso rápido al corpus.</p>
        </div>
        <span className="badge badge--accent">{currentCollection?.name ?? 'Sin colección'} · {visibleDocuments.length} docs visibles</span>
      </div>

      <div className="card" style={{ display: 'grid', gap: 'var(--space-5)' }}>
        <div style={{ display: 'grid', gap: 'var(--space-3)', gridTemplateColumns: 'minmax(240px, 280px) minmax(0, 1fr) minmax(220px, 240px)' }}>
          <label style={{ display: 'grid', gap: 'var(--space-2)' }}>
            <span style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Colección</span>
            <select
              value={collectionId}
              onChange={event => setCollectionId(event.target.value)}
              disabled={loadingCollections}
              style={{ width: '100%', padding: 'var(--space-4)', background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-lg)', color: 'var(--color-text-primary)', fontSize: 'var(--font-md)' }}
            >
              {collections.length === 0 ? <option value="">No hay colecciones</option> : collections.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </label>

          <label style={{ display: 'grid', gap: 'var(--space-2)' }}>
            <span style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Modo de ruta</span>
            <select
              value={mode}
              onChange={event => setMode(event.target.value)}
              style={{ width: '100%', padding: 'var(--space-4)', background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-lg)', color: 'var(--color-text-primary)', fontSize: 'var(--font-md)' }}
            >
              {['auto', 'exact', 'factual_local', 'multi_hop', 'global', 'argumentative', 'visual'].map(item => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>

          <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'end', flexWrap: 'wrap' }}>
            {(['search', 'answer'] as const).map(item => (
              <button key={item} type="button" className={`btn ${action === item ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setAction(item)}>
                {item === 'search' ? 'Buscar memoria' : 'Responder en chat'}
              </button>
            ))}
          </div>
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'grid', gap: 'var(--space-4)' }}>
          <label style={{ display: 'grid', gap: 'var(--space-2)' }}>
            <span style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Escribe en lenguaje natural</span>
            <textarea
              value={query}
              onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setQuery(event.target.value)}
              rows={4}
              placeholder="Pregunta algo sobre tus documentos, como si fuera un chat."
              style={{ width: '100%', padding: 'var(--space-4) var(--space-5)', background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-lg)', color: 'var(--color-text-primary)', fontSize: 'var(--font-md)', resize: 'vertical', lineHeight: 'var(--line-height-relaxed)' }}
            />
          </label>

          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-4)', flexWrap: 'wrap' }}>
            <p style={{ color: 'var(--color-text-tertiary)', fontSize: 'var(--font-sm)' }}>
              {action === 'search'
                ? 'Buscar memoria devuelve evidencias ordenadas sin sintetizar la respuesta.'
                : 'Responder en chat devuelve una respuesta fundamentada con citas y evidencia.'}
            </p>
            <button className="btn btn-primary" type="submit" disabled={!canSubmit}>
              {loading ? (action === 'search' ? 'Buscando...' : 'Generando...') : action === 'search' ? 'Buscar' : 'Responder'}
            </button>
          </div>
        </form>
      </div>

      {error ? (
        <div className="card" style={{ borderColor: 'rgba(239,68,68,0.35)' }}>
          <p style={{ color: 'var(--color-error)' }}>{error}</p>
        </div>
      ) : null}

      <div className="query-workspace" style={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 320px) minmax(0, 1fr) minmax(320px, 380px)', gap: 'var(--space-6)', alignItems: 'start' }}>
        <aside className="card" style={{ display: 'grid', gap: 'var(--space-4)', position: 'sticky', top: 'calc(var(--topbar-height) + var(--space-6))' }}>
          <div className="card__header">
            <div className="card__title">Memoria</div>
            <span className="badge badge--accent">{recentMemory.length}</span>
          </div>
          <div style={{ display: 'grid', gap: 'var(--space-2)' }}>
            {recentMemory.length === 0 ? (
              <p style={{ color: 'var(--color-text-tertiary)' }}>Esta colección todavía no tiene memoria registrada.</p>
            ) : recentMemory.map(item => (
              <button key={item.query_id} type="button" className="card" style={{ textAlign: 'left', padding: 'var(--space-3)', background: 'var(--color-bg-primary)', borderColor: 'var(--color-border)' }} onClick={() => setQuery(item.query)}>
                <div style={{ fontSize: 'var(--font-sm)', fontWeight: 'var(--font-weight-medium)' }}>{item.query}</div>
                <div style={{ marginTop: 'var(--space-1)', color: 'var(--color-text-tertiary)', fontSize: 'var(--font-xs)' }}>{formatRelativeDate(item.created_at)}</div>
              </button>
            ))}
          </div>

          <div className="card" style={{ background: 'var(--color-bg-primary)', borderColor: 'var(--color-border)' }}>
            <div className="card__title">Documentos del contexto</div>
            <div style={{ display: 'grid', gap: 'var(--space-2)', marginTop: 'var(--space-3)' }}>
              {loadingContext ? <p style={{ color: 'var(--color-text-tertiary)' }}>Cargando documentos...</p> : null}
              {visibleDocuments.length === 0 && !loadingContext ? <p style={{ color: 'var(--color-text-tertiary)' }}>No hay documentos cargados en esta colección.</p> : null}
              {visibleDocuments.map(document => (
                <div key={document.id} style={{ display: 'flex', justifyContent: 'space-between', gap: 'var(--space-3)', alignItems: 'center', padding: 'var(--space-3)', borderRadius: 'var(--radius-md)', background: 'rgba(15,20,31,0.8)', border: '1px solid var(--color-border)' }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 'var(--font-weight-medium)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{document.title}</div>
                    <div style={{ color: 'var(--color-text-tertiary)', fontSize: 'var(--font-xs)' }}>{document.mime_type} · {document.status}</div>
                  </div>
                  <span className="badge badge--info">v{document.version}</span>
                </div>
              ))}
            </div>
          </div>
        </aside>

        <section className="card" style={{ display: 'grid', gap: 'var(--space-4)' }}>
          <div className="card__header">
            <div className="card__title">Conversación</div>
            <span className="badge badge--accent">{turns.length} turnos</span>
          </div>

          <div style={{ display: 'grid', gap: 'var(--space-4)' }}>
            {turns.length === 0 ? (
              <div className="empty-state" style={{ padding: 'var(--space-12) var(--space-4)' }}>
                <div className="empty-state__icon">💬</div>
                <div className="empty-state__title">Empieza una conversación</div>
                <p>Haz una pregunta para abrir la memoria de la colección.</p>
              </div>
            ) : (
              turns.map(turn => (
                <article
                  key={turn.id}
                  className="card"
                  style={{
                    padding: 'var(--space-4)',
                    borderColor: activeTurnId === turn.id ? 'rgba(99,102,241,0.55)' : 'var(--color-border)',
                    background: activeTurnId === turn.id ? 'linear-gradient(180deg, rgba(99,102,241,0.08), rgba(15,20,31,0.92))' : 'var(--color-bg-primary)',
                    cursor: 'pointer',
                  }}
                  onClick={() => {
                    void hydrateTurn(turn);
                  }}
                >
                  <div style={{ display: 'grid', gap: 'var(--space-3)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
                      <div>
                        <div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{turn.kind === 'answer' ? 'Usuario + asistente' : 'Recuperación de memoria'}</div>
                        <p style={{ marginTop: 'var(--space-1)', fontWeight: 'var(--font-weight-semibold)' }}>{turn.query}</p>
                      </div>
                      <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
                        <span className="badge badge--accent">{turn.routeMode}</span>
                        <span className="badge badge--info">{turn.intent}</span>
                      </div>
                    </div>

                    {turn.kind === 'answer' ? (
                      <div className="chat-bubble chat-bubble--assistant" style={{ display: 'grid', gap: 'var(--space-3)' }}>
                        <p style={{ whiteSpace: 'pre-wrap', lineHeight: 'var(--line-height-relaxed)' }}>{turn.answer || 'La respuesta completa se puede abrir desde el panel derecho.'}</p>
                        <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
                          <span className="badge badge--success">{turn.groundingScore?.toFixed(3) ?? '—'}</span>
                          <span className="badge badge--warning">{turn.citationsCount ?? 0} citas</span>
                        </div>
                      </div>
                    ) : (
                      <div className="chat-bubble chat-bubble--assistant" style={{ display: 'grid', gap: 'var(--space-3)' }}>
                        <p style={{ color: 'var(--color-text-secondary)' }}>El router devolvió {turn.totalHits ?? 0} evidencias para esta búsqueda.</p>
                        {turn.hits && turn.hits.length > 0 ? (
                          <div style={{ display: 'grid', gap: 'var(--space-3)' }}>
                            {turn.hits.slice(0, 3).map(hit => <EvidenceCard key={hit.id} evidence={hit} />)}
                          </div>
                        ) : null}
                      </div>
                    )}
                  </div>
                </article>
              ))
            )}
          </div>
        </section>

        <aside className="card" style={{ display: 'grid', gap: 'var(--space-4)', position: 'sticky', top: 'calc(var(--topbar-height) + var(--space-6))' }}>
          <div className="card__header">
            <div className="card__title">Evidencia</div>
            <span className="badge badge--accent">{activeTurn?.kind === 'answer' ? 'respuesta' : 'búsqueda'}</span>
          </div>

          {activeTurn ? (
            <>
              <div className="card" style={{ background: 'var(--color-bg-primary)', borderColor: 'var(--color-border)' }}>
                <div style={{ display: 'grid', gap: 'var(--space-2)' }}>
                  <div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Consulta activa</div>
                  <div style={{ fontWeight: 'var(--font-weight-semibold)' }}>{activeTurn.query}</div>
                </div>
              </div>

              {activeAnswer ? (
                <>
                  <AnswerPanel answer={activeAnswer} />
                  <PageViewer evidence={activeAnswer.evidence} />
                  <CitationSidebar citations={activeAnswer.citations} />
                  <div className="card" style={{ background: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', display: 'grid', gap: 'var(--space-3)' }}>
                    <div className="card__title">Exportar respuesta</div>
                    <div style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
                      <a className="btn btn-primary" href={api.exportAnswerMarkdown(activeAnswer.answer_id)} target="_blank" rel="noreferrer">Markdown</a>
                      <a className="btn btn-secondary" href={api.exportAnswerPdf(activeAnswer.answer_id)} target="_blank" rel="noreferrer">PDF</a>
                    </div>
                  </div>
                </>
              ) : (
                <div className="card" style={{ background: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', display: 'grid', gap: 'var(--space-3)' }}>
                  <div className="card__title">Resultados de memoria</div>
                  {activeSearchHits.length === 0 ? (
                    <p style={{ color: 'var(--color-text-tertiary)' }}>No hay evidencias detalladas para este turno todavía.</p>
                  ) : (
                    <div style={{ display: 'grid', gap: 'var(--space-3)' }}>
                      {activeSearchHits.slice(0, 5).map(hit => <EvidenceCard key={hit.id} evidence={hit} />)}
                    </div>
                  )}
                </div>
              )}
            </>
          ) : (
            <div className="empty-state" style={{ padding: 'var(--space-8) var(--space-4)' }}>
              <div className="empty-state__icon">⌕</div>
              <div className="empty-state__title">Selecciona un turno</div>
              <p>Abre una respuesta o búsqueda para ver sus citas y evidencias.</p>
            </div>
          )}
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

  const refreshJobs = async () => {
    setLoading(true);
    setError('');
    try {
      const items = await api.listJobs();
      setJobs(items);
      if (!selectedJobId && items[0]) {
        setSelectedJobId(items[0].id);
      }
    } catch (jobError) {
      setError(jobError instanceof Error ? jobError.message : 'No se pudieron cargar las tareas.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refreshJobs();
  }, []);

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
                <div className="empty-state__icon">⟳</div>
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
              <div className="empty-state__icon">⌕</div>
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

  const selectedAudit = auditEntries.find(entry => entry.id === selectedAuditId) ?? auditEntries[0] ?? null;

  const refreshAudit = async () => {
    setAuditLoading(true);
    setAuditError('');
    try {
      const nextLimit = Math.max(1, Math.min(100, Number(limit) || 40));
      const nextParams: { entityType?: string; entityId?: string; runId?: string; limit?: number } = { limit: nextLimit };

      if (runId.trim()) {
        nextParams.runId = runId.trim();
      } else if (entityType.trim() && entityType !== 'all' && entityId.trim()) {
        nextParams.entityType = entityType.trim();
        nextParams.entityId = entityId.trim();
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
  };

  useEffect(() => {
    void refreshAudit();
  }, []);

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
              <div className="empty-state__icon">⌬</div>
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
              <div className="empty-state__icon">⌬</div>
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
  const [report, setReport] = useState<EvaluationRunResponse | null>(null);
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
    Promise.all([api.listCollections(), api.listEvaluationDatasets(), api.listEvaluationRuns()])
      .then(async ([collectionItems, datasetItems, runItems]) => {
        if (!mounted) return;
        setCollections(collectionItems);
        setDatasets(datasetItems);
        setSelectedCollectionId(collectionItems[0]?.id ?? '');
        setSelectedDataset(datasetItems[0] ?? 'baseline');
        setRuns(runItems);
        if (runItems[0]) {
          const detail = await api.getEvaluationReport(runItems[0].id);
          if (mounted) setReport(detail);
        }
      })
      .catch(() => {
        if (mounted) setError('No se pudieron cargar los recursos de evaluación.');
      });
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
          <button className="btn btn-primary" onClick={handleRun} disabled={!selectedCollectionId || loading}>{loading ? 'Ejecutando...' : 'Ejecutar evaluación'}</button>
        </div>
        {error ? <p style={{ color: 'var(--color-error)' }}>{error}</p> : null}
      </div>

      {report ? (
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
          <div className="empty-state__icon">◌</div>
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
