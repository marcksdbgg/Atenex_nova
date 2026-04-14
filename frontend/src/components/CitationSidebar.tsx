import type { Citation } from '../types/api';

interface CitationSidebarProps {
  citations: Citation[];
}

export function CitationSidebar({ citations }: CitationSidebarProps) {
  return (
    <aside className="query-entity-card query-citation-panel">
      <div className="card__header">
        <div>
          <div className="card__title">Fuentes</div>
          <p className="query-panel-note">Citas exactas devueltas por el generador.</p>
        </div>
        <span className="badge badge--accent">{citations.length}</span>
      </div>

      {citations.length === 0 ? (
        <p className="query-panel-note">No se generaron citas para esta respuesta.</p>
      ) : (
        <div className="query-citation-list">
          {citations.map(citation => (
            <article key={citation.id} className="query-citation">
              <div className="query-citation__top">
                <span className="badge badge--accent">{citation.page_number !== null && citation.page_number !== undefined ? `Página ${citation.page_number}` : 'Cita'}</span>
                <span className="query-citation__meta">{citation.document_id}</span>
              </div>
              <p className="query-citation__snippet">{citation.snippet}</p>
              <div className="query-citation__footer">
                {citation.node_id ? <span className="query-chip">Nodo {citation.node_id}</span> : null}
                {citation.char_start !== null && citation.char_start !== undefined && citation.char_end !== null && citation.char_end !== undefined ? (
                  <span className="query-chip">chars {citation.char_start}–{citation.char_end}</span>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      )}
    </aside>
  );
}