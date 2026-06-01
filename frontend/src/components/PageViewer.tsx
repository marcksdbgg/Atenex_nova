import { useEffect, useMemo, useState } from 'react';

import { API_BASE, api } from '../services/api';
import type { DocumentPage, QueryHit } from '../types/api';

interface PageViewerProps {
  evidence: QueryHit[];
}

type PageRef = {
  key: string;
  documentId: string;
  pageNumber: number;
  title: string;
  snippet: string;
  score: number;
};

type PageLoadState = {
  ref: PageRef;
  page?: DocumentPage;
  error?: string;
};

function collectPageRefs(evidence: QueryHit[]): PageRef[] {
  const refs = new Map<string, PageRef>();

  for (const item of evidence) {
    if (!item.document_id || item.page_number === null || item.page_number === undefined) {
      continue;
    }

    const key = `${item.document_id}:${item.page_number}`;
    if (!refs.has(key)) {
      refs.set(key, {
        key,
        documentId: item.document_id,
        pageNumber: item.page_number,
        title: item.title,
        snippet: item.snippet,
        score: item.score,
      });
    }
  }

  return Array.from(refs.values());
}

function isImageAssetPath(path: string): boolean {
  const normalized = path.split(/[?#]/)[0].toLowerCase();
  return /\.(png|jpe?g|webp|gif|svg)$/.test(normalized);
}

function resolveVisualAssetUrl(path?: string | null): string | null {
  const trimmed = path?.trim();
  if (!trimmed || !isImageAssetPath(trimmed)) {
    return null;
  }

  if (/^(https?:|data:|blob:)/i.test(trimmed)) {
    return trimmed;
  }

  if (trimmed.startsWith('/')) {
    return `${API_BASE}${trimmed}`;
  }

  if (/^[a-z]:[\\/]/i.test(trimmed)) {
    return `file:///${trimmed.replace(/\\/g, '/')}`;
  }

  return `${API_BASE}/${trimmed.replace(/^\/+/, '')}`;
}

function getUnavailableMessage(state: PageLoadState, imageFailed: boolean): string {
  if (state.error) {
    return 'Strict unavailable: no se pudo hidratar la pagina visual desde la API.';
  }

  if (!state.page?.image_path) {
    return 'Strict unavailable: el endpoint no entrego un asset visual para esta pagina.';
  }

  if (!isImageAssetPath(state.page.image_path)) {
    return 'Strict unavailable: el asset registrado no es una imagen renderizable.';
  }

  if (imageFailed) {
    return 'Strict unavailable: el navegador no pudo cargar el asset visual.';
  }

  return 'Strict unavailable: evidencia visual no disponible.';
}

export function PageViewer({ evidence }: PageViewerProps) {
  const pageRefs = useMemo(() => collectPageRefs(evidence), [evidence]);
  const [pagesByKey, setPagesByKey] = useState<Record<string, PageLoadState>>({});
  const [imageFailures, setImageFailures] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (pageRefs.length === 0) {
      return;
    }

    let active = true;
    Promise.allSettled(
      pageRefs.map(async ref => ({
        ref,
        page: await api.getDocumentPage(ref.documentId, ref.pageNumber),
      })),
    ).then(results => {
      if (!active) return;

      const next: Record<string, PageLoadState> = {};
      results.forEach((result, index) => {
        const ref = pageRefs[index];
        if (!ref) return;

        if (result.status === 'fulfilled') {
          next[ref.key] = { ref, page: result.value.page };
          return;
        }

        next[ref.key] = {
          ref,
          error: result.reason instanceof Error ? result.reason.message : 'No se pudo cargar la pagina visual.',
        };
      });
      setPagesByKey(next);
    });

    return () => {
      active = false;
    };
  }, [pageRefs]);

  if (pageRefs.length === 0) {
    return null;
  }

  return (
    <section className="query-entity-card query-pages">
      <div className="card__header">
        <div>
          <div className="card__title">Visor de paginas</div>
          <p className="query-panel-note">Evidencia visual hidratada por documento y pagina.</p>
        </div>
        <span className="badge badge--info">{pageRefs.length}</span>
      </div>

      <div className="query-pages__list">
        {pageRefs.map(ref => {
          const state = pagesByKey[ref.key] ?? { ref };
          const page = state.page;
          const imageFailed = page ? imageFailures[page.id] ?? false : false;
          const assetUrl = resolveVisualAssetUrl(page?.image_path);
          const canRenderAsset = Boolean(assetUrl && !imageFailed);

          return (
            <article key={ref.key} className="query-page-card">
              <div className="query-page-card__header">
                <span className="badge badge--info">Pagina {page?.page_number ?? ref.pageNumber}</span>
                <span className="query-page-card__title">{page?.title ?? ref.title}</span>
              </div>

              {!page && !state.error ? (
                <div className="query-page-card__snippet">Cargando asset visual...</div>
              ) : canRenderAsset ? (
                <div className="query-page-card__asset">
                  <img
                    src={assetUrl ?? undefined}
                    alt={`Pagina visual ${page?.page_number ?? ref.pageNumber} de ${page?.title ?? ref.title}`}
                    onError={() => {
                      if (!page) return;
                      setImageFailures(current => ({ ...current, [page.id]: true }));
                    }}
                  />
                </div>
              ) : (
                <div className="query-page-card__unavailable">
                  <strong>{getUnavailableMessage(state, imageFailed)}</strong>
                  <span>{ref.documentId} / pagina {ref.pageNumber}</span>
                </div>
              )}

              <div className="query-citation__footer">
                <span className="query-chip">doc {ref.documentId}</span>
                <span className="query-chip">score {ref.score.toFixed(3)}</span>
                {page?.is_complex ? <span className="query-chip">visual complejo</span> : null}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
