import { useId, useState } from 'react';
import type { QueryHit } from '../types/api';

interface EvidenceCardProps {
  evidence: QueryHit;
  documentTitle?: string;
  selected?: boolean;
  onSelectDocument?: (documentId: string, pageNumber?: number | null) => void;
}

const SOURCE_LABELS: Readonly<Record<string, string>> = {
  chunk: 'Fragmento',
  graph_edge: 'Relación del grafo',
  proposition: 'Proposición',
  summary: 'Resumen',
  visual_page: 'Página visual',
};

function formatSourceType(sourceType: string): string {
  const normalized = sourceType.trim().toLowerCase();
  if (SOURCE_LABELS[normalized]) return SOURCE_LABELS[normalized];
  const readable = sourceType.replace(/[_-]+/g, ' ').trim();
  return readable ? `${readable.charAt(0).toUpperCase()}${readable.slice(1)}` : 'Evidencia';
}

function compactIdentifier(identifier: string): string {
  return identifier.length > 12 ? `${identifier.slice(0, 8)}…` : identifier;
}

export function EvidenceCard({
  evidence,
  documentTitle,
  selected = false,
  onSelectDocument,
}: EvidenceCardProps) {
  const isGraph = evidence.source_type === 'graph_edge';
  const [isExpanded, setIsExpanded] = useState(false);
  const snippetId = useId();
  const snippet = evidence.snippet || '';
  const shouldTruncate = snippet.length > 240;
  const resolvedDocumentTitle = documentTitle?.trim()
    || evidence.title?.trim()
    || (isGraph ? 'Relación entre fuentes del corpus' : 'Fuente sin título');
  const headingPath = Array.isArray(evidence.metadata?.heading_path)
    ? evidence.metadata.heading_path.map(item => String(item)).filter(Boolean)
    : [];
  const visibleMetadata = Object.entries(evidence.metadata ?? {})
    .filter(([key]) => !['heading_path', 'document_title', 'title'].includes(key))
    .slice(0, 2);

  const displayText = shouldTruncate && !isExpanded
    ? `${snippet.slice(0, 240).trim()}...`
    : snippet;

  return (
    <article className={`query-evidence${isGraph ? ' query-evidence--graph' : ''}${selected ? ' query-source-card--selected' : ''}`}>
      <div className="query-evidence__top">
        <div className="query-evidence__title-wrap">
          <span className="badge badge--accent">#{evidence.rank}</span>
          <span className={`badge ${isGraph ? 'badge--warning' : 'badge--info'}`}>
            {formatSourceType(evidence.source_type)}
          </span>
          {evidence.document_id && onSelectDocument ? (
            <button
              type="button"
              className="query-source-button query-source-button--inline"
              onClick={() => onSelectDocument(evidence.document_id as string, evidence.page_number)}
              aria-pressed={selected}
              aria-controls="query-document-inspector"
              aria-label={`Seleccionar ${resolvedDocumentTitle} en el inspector documental`}
            >
              <span className="query-source-button__title">{resolvedDocumentTitle}</span>
            </button>
          ) : (
            <span className="query-evidence__title" title={resolvedDocumentTitle}>
              {resolvedDocumentTitle}
            </span>
          )}
        </div>
        <span className="query-evidence__score" title="Puntuación de recuperación antes de la verificación">
          Relevancia {evidence.score.toFixed(3)}
        </span>
      </div>

      <div className="query-evidence__body">
        <p id={snippetId} className="query-evidence__snippet" style={{ whiteSpace: 'pre-wrap' }}>
          {displayText}
        </p>
        {shouldTruncate && (
          <button
            type="button"
            aria-expanded={isExpanded}
            aria-controls={snippetId}
            onClick={(e) => {
              e.stopPropagation();
              setIsExpanded(!isExpanded);
            }}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--color-primary, #6366f1)',
              cursor: 'pointer',
              fontSize: 'var(--font-xs)',
              fontWeight: 'bold',
              padding: '0',
              marginTop: 'var(--space-1)',
              display: 'block'
            }}
          >
            {isExpanded ? 'Ver menos' : 'Leer fragmento completo'}
          </button>
        )}
      </div>

      <div className="query-evidence__footer">
        {evidence.document_id ? (
          <span className="query-chip" title={evidence.document_id}>
            Documento {resolvedDocumentTitle} · {compactIdentifier(evidence.document_id)}
          </span>
        ) : null}
        {evidence.page_number !== null && evidence.page_number !== undefined ? <span className="query-chip">Página {evidence.page_number}</span> : null}
        <span className="query-chip" title={evidence.source_id}>Origen {compactIdentifier(evidence.source_id)}</span>
        {headingPath.length > 0 ? (
          <span className="query-chip">Sección {headingPath.join(' / ')}</span>
        ) : null}
        {visibleMetadata.map(([key, value]) => (
          <span key={key} className="query-chip">{key}: {typeof value === 'object' ? JSON.stringify(value) : String(value)}</span>
        ))}
      </div>
    </article>
  );
}

