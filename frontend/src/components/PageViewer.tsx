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
    <section className="card" style={{ display: 'grid', gap: 'var(--space-4)' }}>
      <div className="card__title">Page Viewer</div>
      <div style={{ display: 'grid', gap: 'var(--space-4)' }}>
        {pages.map(page => (
          <article
            key={page.id}
            className="card"
            style={{
              background: 'linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.02))',
              borderColor: 'var(--color-border)',
              display: 'grid',
              gap: 'var(--space-3)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
              <span className="badge badge--info">Page {page.page_number}</span>
              <span style={{ color: 'var(--color-text-tertiary)', fontSize: 'var(--font-xs)' }}>{page.title}</span>
            </div>
            <div
              style={{
                padding: 'var(--space-5)',
                borderRadius: 'var(--radius-lg)',
                border: '1px solid var(--color-border)',
                background: 'rgba(0,0,0,0.18)',
                minHeight: '140px',
                lineHeight: 'var(--line-height-relaxed)',
              }}
            >
              {page.snippet}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}