import { useState } from 'react';
import type { QueryHit } from '../types/api';

interface EvidenceCardProps {
  evidence: QueryHit;
}

export function EvidenceCard({ evidence }: EvidenceCardProps) {
  const isGraph = evidence.source_type === 'graph_edge';
  const [isExpanded, setIsExpanded] = useState(false);
  const snippet = evidence.snippet || '';
  const shouldTruncate = snippet.length > 240;

  const displayText = shouldTruncate && !isExpanded
    ? `${snippet.slice(0, 240).trim()}...`
    : snippet;

  return (
    <article className={`query-evidence ${isGraph ? 'query-evidence--graph' : ''}`}>
      <div className="query-evidence__top">
        <div className="query-evidence__title-wrap">
          <span className="badge badge--accent">#{evidence.rank}</span>
          <span className={`badge ${isGraph ? 'badge--warning' : 'badge--info'}`}>
            {isGraph ? 'Grafo' : evidence.source_type}
          </span>
          <span className="query-evidence__title" title={isGraph ? 'Expansión de Grafo de Conocimiento' : (evidence.title || 'Fuente sin título')}>
            {isGraph ? 'Expansión de Grafo' : (evidence.title || 'Fuente sin título')}
          </span>
        </div>
        <span className="query-evidence__score">Puntuación {evidence.score.toFixed(3)}</span>
      </div>

      <div className="query-evidence__body">
        <p className="query-evidence__snippet" style={{ whiteSpace: 'pre-wrap' }}>
          {displayText}
        </p>
        {shouldTruncate && (
          <button
            type="button"
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
            {isExpanded ? 'Ver menos' : 'Leer más...'}
          </button>
        )}
      </div>

      <div className="query-evidence__footer">
        {evidence.document_id ? <span className="query-chip">Documento {evidence.document_id}</span> : null}
        {evidence.page_number !== null && evidence.page_number !== undefined ? <span className="query-chip">Pagina {evidence.page_number}</span> : null}
        <span className="query-chip">Origen {evidence.source_id}</span>
        {Array.isArray(evidence.metadata?.heading_path) && evidence.metadata.heading_path.length > 0 ? (
          <span className="query-chip">{String((evidence.metadata.heading_path as unknown[]).join(' / '))}</span>
        ) : null}
        {evidence.metadata ? Object.entries(evidence.metadata).slice(0, 2).map(([key, value]) => (
          <span key={key} className="query-chip">{key}: {typeof value === 'object' ? JSON.stringify(value) : String(value)}</span>
        )) : null}
      </div>
    </article>
  );
}

