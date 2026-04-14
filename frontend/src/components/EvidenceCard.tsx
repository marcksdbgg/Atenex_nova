import type { QueryHit } from '../types/api';

interface EvidenceCardProps {
  evidence: QueryHit;
}

export function EvidenceCard({ evidence }: EvidenceCardProps) {
  return (
    <article className="query-evidence">
      <div className="query-evidence__top">
        <div className="query-evidence__title-wrap">
          <span className="badge badge--accent">#{evidence.rank}</span>
          <span className="badge badge--info">{evidence.source_type}</span>
          <span className="query-evidence__title" title={evidence.title || 'Fuente sin título'}>{evidence.title || 'Fuente sin título'}</span>
        </div>
        <span className="query-evidence__score">Puntuación {evidence.score.toFixed(3)}</span>
      </div>

      <p className="query-evidence__snippet">{evidence.snippet}</p>

      <div className="query-evidence__footer">
        {evidence.document_id ? <span className="query-chip">Documento {evidence.document_id}</span> : null}
        {evidence.page_number !== null && evidence.page_number !== undefined ? <span className="query-chip">Página {evidence.page_number}</span> : null}
        <span className="query-chip">Origen {evidence.source_id}</span>
        {evidence.metadata ? Object.entries(evidence.metadata).slice(0, 2).map(([key, value]) => (
          <span key={key} className="query-chip">{key}: {value}</span>
        )) : null}
      </div>
    </article>
  );
}