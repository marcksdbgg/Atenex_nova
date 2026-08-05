import type { Citation } from '../types/api';

interface CitationSidebarProps {
  citations: Citation[];
  expectedCount?: number;
  hydrationFailed?: boolean;
  documentTitles?: Readonly<Record<string, string>>;
  selectedDocumentId?: string;
  onSelectDocument?: (documentId: string, pageNumber?: number | null) => void;
}

function compactDocumentId(documentId: string): string {
  return documentId.length > 12 ? `${documentId.slice(0, 8)}…` : documentId;
}

export function CitationSidebar({
  citations,
  expectedCount = citations.length,
  hydrationFailed = false,
  documentTitles = {},
  selectedDocumentId,
  onSelectDocument,
}: CitationSidebarProps) {
  const hasHydrationFailure = hydrationFailed && expectedCount > 0 && citations.length === 0;

  return (
    <aside className="query-entity-card query-citation-panel">
      <div className="card__header">
        <div>
          <div className="card__title">Fuentes</div>
          <p className="query-panel-note">Citas exactas devueltas por el generador.</p>
        </div>
        <span className="badge badge--accent">{hasHydrationFailure ? `${expectedCount}?` : citations.length}</span>
      </div>

      {hasHydrationFailure ? (
        <p className="query-panel-note">
          Falló la carga del detalle: el historial reporta citas, pero no se pudo recuperar el paquete completo.
        </p>
      ) : citations.length === 0 ? (
        <p className="query-panel-note">No se generaron citas para esta respuesta.</p>
      ) : (
        <div className="query-citation-list">
          {citations.map(citation => {
            const documentTitle = documentTitles[citation.document_id]?.trim()
              || `Documento ${compactDocumentId(citation.document_id)}`;
            const selected = citation.document_id === selectedDocumentId;

            return (
              <article
                key={citation.id}
                className={`query-citation${selected ? ' query-source-card--selected' : ''}`}
                aria-label={`Cita de ${documentTitle}`}
              >
                <div className="query-citation__top">
                  <span className="badge badge--accent">
                    {citation.page_number !== null && citation.page_number !== undefined
                      ? `Página ${citation.page_number}`
                      : 'Cita textual'}
                  </span>
                  {onSelectDocument ? (
                    <button
                      type="button"
                      className="query-source-button"
                      onClick={() => onSelectDocument(citation.document_id, citation.page_number)}
                      aria-pressed={selected}
                      aria-controls="query-document-inspector"
                      aria-label={`Seleccionar ${documentTitle} en el inspector documental`}
                    >
                      <span className="query-source-button__title">{documentTitle}</span>
                      <span className="query-source-button__id" title={citation.document_id}>
                        ID {compactDocumentId(citation.document_id)}
                      </span>
                    </button>
                  ) : (
                    <span className="query-citation__meta">{documentTitle}</span>
                  )}
                </div>
                <p className="query-citation__snippet">{citation.snippet}</p>
                {citation.heading_path && citation.heading_path.length > 0 ? (
                  <div className="query-citation__footer">
                    <span className="query-chip">Sección {citation.heading_path.join(' / ')}</span>
                  </div>
                ) : null}
                <div className="query-citation__footer">
                  {citation.node_id ? <span className="query-chip">Nodo {citation.node_id}</span> : null}
                  {citation.char_start !== null && citation.char_start !== undefined && citation.char_end !== null && citation.char_end !== undefined ? (
                    <span className="query-chip">Caracteres {citation.char_start}–{citation.char_end}</span>
                  ) : null}
                  {citation.page_asset_path ? <span className="query-chip">Página visual disponible</span> : null}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </aside>
  );
}
