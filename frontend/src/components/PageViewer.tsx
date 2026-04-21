import type { QueryHit } from '../types/api';

interface PageViewerProps {
  evidence: QueryHit[];
}

export function PageViewer({ evidence }: PageViewerProps) {
  const pages = evidence.filter(item => item.page_number !== null && item.page_number !== undefined);

  if (pages.length === 0) {
    return null;
  }

  return (
    <section className="query-entity-card query-pages">
      <div className="card__header">
        <div>
          <div className="card__title">Visor de paginas</div>
          <p className="query-panel-note">Fragmentos anclados a paginas detectadas en la evidencia.</p>
        </div>
        <span className="badge badge--info">{pages.length}</span>
      </div>

      <div className="query-pages__list">
        {pages.map(page => (
          <article key={page.id} className="query-page-card">
            <div className="query-page-card__header">
              <span className="badge badge--info">Pagina {page.page_number}</span>
              <span className="query-page-card__title">{page.title}</span>
            </div>
            {typeof page.metadata?.image_path === 'string' ? (
              <div className="query-page-card__snippet">
                <a href={page.metadata.image_path} target="_blank" rel="noreferrer">Abrir asset visual</a>
              </div>
            ) : null}
            <div className="query-page-card__snippet">{page.snippet}</div>
          </article>
        ))}
      </div>
    </section>
  );
}
