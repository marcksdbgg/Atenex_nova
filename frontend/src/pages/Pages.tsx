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
  EvaluationRunResponse,
  QueryHit,
  QueryHistoryResponse,
  QuerySearchResponse,
} from '../types/api';

type UploadStatus = 'queued' | 'uploading' | 'done' | 'error';

type UploadQueueItem = {
  id: string;
  file: File;
  status: UploadStatus;
  message?: string;
  document?: Document;
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
  const [processingUploads, setProcessingUploads] = useState<Record<string, boolean>>({});
  const [busyCollectionId, setBusyCollectionId] = useState('');
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

  useEffect(() => {
    uploadQueuesRef.current = uploadQueues;
  }, [uploadQueues]);

  useEffect(() => {
    documentsByCollectionRef.current = documentsByCollection;
  }, [documentsByCollection]);

  useEffect(() => {
    processingUploadsRef.current = processingUploads;
  }, [processingUploads]);

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
        await syncCollectionDocuments(collections.map(collection => collection.id));
      } catch {
        if (mounted) {
          setMessage('No se pudo actualizar el estado de los documentos.');
        }
      }
    };

    void runSync();

    if (!hasLiveProcessing) return () => {
      mounted = false;
    };

    const timer = window.setInterval(() => {
      void runSync();
    }, 3500);

    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, [collections, hasLiveProcessing]);

  const refreshCollectionDocuments = async (collectionId: string) => {
    await syncCollectionDocuments([collectionId]);
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
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'No se pudo registrar la ruta local.');
    }
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
              const document = await api.uploadDocument(collectionId, item.file);
              updateQueueItem(collectionId, item.id, {
                status: 'uploading',
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
      }
    } finally {
      setProcessingUploads(current => ({ ...current, [collectionId]: false }));
    }
  };

  const handleCollectionFiles = async (collectionId: string, fileList: FileList | File[]) => {
    const files = Array.from(fileList);
    if (files.length === 0) return;

    const batch = files.map(file => ({
      id: createFileId(file),
      file,
      status: 'queued' as const,
    }));

    setUploadQueues(current => ({
      ...current,
      [collectionId]: [...(current[collectionId] ?? []), ...batch],
    }));
    const collectionName = collections.find(collection => collection.id === collectionId)?.name ?? collectionId;
    setMessage(`Cola ampliada en ${collectionName}: ${batch.length} archivos añadidos.`);
    await processCollectionQueue(collectionId, batch);
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

  const handleRebuild = async (collectionId: string) => {
    setBusyCollectionId(collectionId);
    setMessage('');
    try {
      const response = await api.rebuildCollection(collectionId);
      setMessage(`Reprocesado completo en cola: ${response.job_id}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'No se pudo lanzar el reprocesado.');
    } finally {
      setBusyCollectionId('');
    }
  };

  return (
    <div className="animate-fade-in-up">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-6)' }}>
        <div>
          <h2 style={{ fontSize: 'var(--font-xl)', fontWeight: 'var(--font-weight-bold)' }}>Colecciones</h2>
          <p style={{ color: 'var(--color-text-tertiary)', marginTop: 'var(--space-1)' }}>Ingesta en lote, control por archivo y reconstrucción completa del corpus.</p>
        </div>
        <button className="btn btn-primary" type="button" onClick={() => setShowCreateForm(current => !current)}>+ Nueva colección</button>
      </div>
      {message ? (
        <div className="card" style={{ marginBottom: 'var(--space-5)' }}>
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
            const queuedCount = collectionQueue.filter(item => item.status === 'queued').length;
            const runningCount = collectionQueue.filter(item => item.status === 'uploading').length;
            const errorCount = collectionQueue.filter(item => item.status === 'error').length;

            return (
            <article key={collection.id} className="card" style={{ display: 'grid', gap: 'var(--space-5)' }}>
              <div className="card__header">
                <div>
                  <div className="card__title">{collection.name}</div>
                  <p style={{ color: 'var(--color-text-tertiary)', marginTop: 'var(--space-1)' }}>{collection.description || 'Sin descripción'}</p>
                </div>
                <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                  <span className="badge badge--accent">{collection.language_profile}</span>
                  <span className="badge badge--info">{(documentsByCollection[collection.id] ?? []).length} documentos</span>
                </div>
              </div>
              <div className="collection-ingest-grid" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.3fr) minmax(280px, 0.9fr)', gap: 'var(--space-5)' }}>
                <section style={{ display: 'grid', gap: 'var(--space-4)' }}>
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
                      await handleCollectionFiles(collection.id, event.dataTransfer.files);
                    }}
                  >
                    <div className="collection-dropzone__copy">
                      <span className="collection-dropzone__eyebrow">Carga masiva</span>
                      <h3 className="collection-dropzone__title">Arrastra un lote o abre el selector propio</h3>
                      <p className="collection-dropzone__body">
                        Sube más de 100 archivos de una vez. Cada uno entra en la cola, se analiza y el estado se actualiza solo mientras progresa.
                      </p>
                      <div className="collection-dropzone__actions">
                        <label className="btn btn-primary collection-dropzone__button" htmlFor={`upload-${collection.id}`}>
                          Seleccionar archivos
                        </label>
                        <button
                          className="btn btn-secondary"
                          onClick={() => handleRebuild(collection.id)}
                          disabled={busyCollectionId === collection.id}
                          type="button"
                        >
                          {busyCollectionId === collection.id ? 'Reprocesando...' : 'Reprocesar corpus'}
                        </button>
                      </div>

                      <div style={{ display: 'grid', gap: 'var(--space-3)', marginTop: 'var(--space-4)' }}>
                        <label style={{ display: 'grid', gap: 'var(--space-2)' }}>
                          <span style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                            Importar por ruta local
                          </span>
                          <input
                            value={localSourcePaths[collection.id] ?? ''}
                            onChange={event => setLocalSourcePaths(current => ({ ...current, [collection.id]: event.target.value }))}
                            placeholder="C:\\ruta\\al\\archivo.txt o ./storage/uploads/archivo.txt"
                            style={{ width: '100%', padding: 'var(--space-4)', background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-lg)', color: 'var(--color-text-primary)', fontSize: 'var(--font-md)' }}
                          />
                        </label>
                        <div style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'center', flexWrap: 'wrap' }}>
                          <button
                            className="btn btn-secondary"
                            type="button"
                            onClick={() => handleLocalDocumentImport(collection.id)}
                            disabled={!localSourcePaths[collection.id]?.trim()}
                          >
                            Registrar ruta local
                          </button>
                          <span style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)', lineHeight: 'var(--line-height-relaxed)' }}>
                            Reutiliza el archivo ya existente en disco y sólo encola el pipeline.
                          </span>
                        </div>
                      </div>
                    </div>

                    <div className="collection-dropzone__stats">
                      <div className="collection-dropzone__metric">
                        <span>Listos</span>
                        <strong>{readyCount}</strong>
                      </div>
                      <div className="collection-dropzone__metric">
                        <span>Activos</span>
                        <strong>{liveDocuments.length}</strong>
                      </div>
                      <div className="collection-dropzone__metric">
                        <span>En cola</span>
                        <strong>{queuedCount + runningCount}</strong>
                      </div>
                      <div className="collection-dropzone__metric">
                        <span>Errores</span>
                        <strong>{errorCount}</strong>
                      </div>
                    </div>

                    <input
                      id={`upload-${collection.id}`}
                      className="collection-dropzone__input"
                      type="file"
                      multiple
                      accept="*/*"
                      onChange={async (event: ChangeEvent<HTMLInputElement>) => {
                        const files = event.target.files;
                        if (!files || files.length === 0) return;
                        await handleCollectionFiles(collection.id, files);
                        event.target.value = '';
                      }}
                    />
                  </div>

                  <div className="collection-summary-strip">
                    <div>
                      <span>Documentos visibles</span>
                      <strong>{collectionDocuments.length}</strong>
                    </div>
                    <div>
                      <span>Procesando</span>
                      <strong>{liveDocuments.length}</strong>
                    </div>
                    <div>
                      <span>Rebuild</span>
                      <strong>{busyCollectionId === collection.id ? 'Activo' : 'Listo'}</strong>
                    </div>
                    <div>
                      <span>Auto-sync</span>
                      <strong>{hasLiveProcessing ? 'Encendido' : 'En reposo'}</strong>
                    </div>
                  </div>

                  <div className="collection-queue-panel card" style={{ background: 'var(--color-bg-primary)', borderColor: 'var(--color-border)' }}>
                    <div className="card__header">
                      <div>
                        <div className="card__title">Cola viva</div>
                        <p style={{ color: 'var(--color-text-tertiary)', marginTop: 'var(--space-1)' }}>Cada archivo muestra el estado exacto del pipeline.</p>
                      </div>
                      <span className="badge badge--accent">{collectionQueue.length}</span>
                    </div>

                    <div style={{ display: 'grid', gap: 'var(--space-3)' }}>
                      {collectionQueue.length === 0 ? (
                        <div className="empty-state" style={{ padding: 'var(--space-6) var(--space-4)' }}>
                          <div className="empty-state__icon">⟲</div>
                          <div className="empty-state__title">Sin archivos en la cola</div>
                          <p>Selecciona un lote para empezar a procesar.</p>
                        </div>
                      ) : (
                        collectionQueue.map(item => {
                          const pipeline = item.document ? getDocumentPipeline(item.document.status) : null;
                          const progress = pipeline?.progress ?? (item.status === 'done' ? 100 : item.status === 'error' ? 100 : item.status === 'uploading' ? 24 : 8);
                          const tone = item.status === 'done' ? 'success' : item.status === 'error' ? 'error' : item.status === 'uploading' ? 'warning' : 'accent';
                          return (
                            <article key={item.id} className="queue-item">
                              <div className="queue-item__top">
                                <div className="queue-item__title-wrap">
                                  <div className="queue-item__title">{item.file.name}</div>
                                  <div className="queue-item__meta">{formatBytes(item.file.size)} · {item.file.type || 'tipo desconocido'}</div>
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
                        })
                      )}
                    </div>
                  </div>
                </section>

                <aside className="collection-doc-panel card" style={{ background: 'var(--color-bg-primary)', borderColor: 'var(--color-border)' }}>
                  <div className="card__header">
                    <div>
                      <div className="card__title">Inventario vivo</div>
                      <p style={{ color: 'var(--color-text-tertiary)', marginTop: 'var(--space-1)' }}>Se refresca solo mientras hay documentos en proceso.</p>
                    </div>
                    <span className="badge badge--info">{collectionDocuments.length}</span>
                  </div>

                  <div style={{ display: 'grid', gap: 'var(--space-2)' }}>
                    {collectionDocuments.slice(0, MAX_VISIBLE_DOCUMENTS).map(document => {
                      const pipeline = getDocumentPipeline(document.status);
                      return (
                        <div key={document.id} className="document-row">
                          <div className="document-row__top">
                            <div className="document-row__title-wrap">
                              <div className="document-row__title">{document.title}</div>
                              <div className="document-row__meta" title={document.source_path ?? undefined}>
                                {document.mime_type} · v{document.version}{document.source_path ? ' · origen local' : ''}
                              </div>
                            </div>
                            <span className={`badge badge--${pipeline.tone}`}>{pipeline.label}</span>
                          </div>
                          <div className="progress-track">
                            <div className={`progress-fill progress-fill--${pipeline.tone}`} style={{ width: `${pipeline.progress}%` }} />
                          </div>
                          <div className="document-row__bottom">
                            <span>{pipeline.detail}</span>
                            <span>{document.status}</span>
                          </div>
                        </div>
                      );
                    })}

                    {collectionDocuments.length === 0 ? (
                      <div className="empty-state" style={{ padding: 'var(--space-6) var(--space-4)' }}>
                        <div className="empty-state__icon">📄</div>
                        <div className="empty-state__title">Sin documentos todavía</div>
                        <p>Sube el primer lote para construir memoria documental.</p>
                      </div>
                    ) : null}

                    {collectionDocuments.length > MAX_VISIBLE_DOCUMENTS ? (
                      <p style={{ color: 'var(--color-text-tertiary)', fontSize: 'var(--font-sm)' }}>
                        + {collectionDocuments.length - MAX_VISIBLE_DOCUMENTS} documentos más en esta colección.
                      </p>
                    ) : null}
                  </div>

                  <button className="btn btn-secondary" type="button" onClick={() => refreshCollectionDocuments(collection.id)}>
                    Refrescar inventario
                  </button>
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
  return (
    <div className="animate-fade-in-up">
      <h2 style={{ fontSize: 'var(--font-xl)', fontWeight: 'var(--font-weight-bold)', marginBottom: 'var(--space-6)' }}>Tareas</h2>
      <div className="empty-state">
        <div className="empty-state__icon">⟳</div>
        <div className="empty-state__title">No hay tareas</div>
        <p>Las tareas de procesamiento en segundo plano aparecerán aquí.</p>
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
