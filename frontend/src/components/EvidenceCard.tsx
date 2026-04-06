import type { QueryHit } from '../types/api';

interface EvidenceCardProps {
  evidence: QueryHit;
}

export function EvidenceCard({ evidence }: EvidenceCardProps) {
  return (
    <article className="card" style={{ background: 'var(--color-bg-primary)', borderColor: 'var(--color-border)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center', flexWrap: 'wrap' }}>
          <span className="badge badge--accent">#{evidence.rank}</span>
          <span className="badge badge--info">{evidence.source_type}</span>
          <span style={{ color: 'var(--color-text-secondary)' }}>{evidence.title || 'Untitled source'}</span>
        </div>
        <span style={{ color: 'var(--color-text-tertiary)', fontSize: 'var(--font-sm)' }}>Score {evidence.score.toFixed(3)}</span>
      </div>
      <p style={{ color: 'var(--color-text-primary)', lineHeight: 'var(--line-height-relaxed)', marginTop: 'var(--space-3)' }}>
        {evidence.snippet}
      </p>
      <div style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap', marginTop: 'var(--space-3)', fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)' }}>
        {evidence.document_id ? <span>Document {evidence.document_id}</span> : null}
        {evidence.page_number !== null && evidence.page_number !== undefined ? <span>Page {evidence.page_number}</span> : null}
        <span>Source {evidence.source_id}</span>
      </div>
    </article>
  );
}