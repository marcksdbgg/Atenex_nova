import type { Citation } from '../types/api';

interface CitationSidebarProps {
  citations: Citation[];
}

export function CitationSidebar({ citations }: CitationSidebarProps) {
  return (
    <aside className="card" style={{ display: 'grid', gap: 'var(--space-4)', minHeight: '100%' }}>
      <div className="card__title">Fuentes</div>
      {citations.length === 0 ? (
        <p style={{ color: 'var(--color-text-tertiary)' }}>No se generaron citas para esta respuesta.</p>
      ) : (
        <div style={{ display: 'grid', gap: 'var(--space-3)' }}>
          {citations.map(citation => (
            <div key={citation.id} className="card" style={{ background: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', padding: 'var(--space-4)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
                <span className="badge badge--accent">{citation.page_number !== null && citation.page_number !== undefined ? `Página ${citation.page_number}` : 'Cita'}</span>
                <span style={{ color: 'var(--color-text-tertiary)', fontSize: 'var(--font-xs)' }}>{citation.document_id}</span>
              </div>
              <p style={{ marginTop: 'var(--space-3)', color: 'var(--color-text-secondary)', lineHeight: 'var(--line-height-relaxed)' }}>{citation.snippet}</p>
            </div>
          ))}
        </div>
      )}
    </aside>
  );
}