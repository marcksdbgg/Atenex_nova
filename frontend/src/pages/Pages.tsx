/* Page stubs for routing */
import { useEffect, useState, type FormEvent } from 'react';

import { AnswerPanel } from '../components/AnswerPanel';
import { CitationSidebar } from '../components/CitationSidebar';
import { EvidenceCard } from '../components/EvidenceCard';
import { PageViewer } from '../components/PageViewer';
import { api } from '../services/api';
import type { AnswerResponse, Collection, QuerySearchResponse } from '../types/api';

export function DashboardPage() {
  return (
    <div className="animate-fade-in-up">
      <h2 style={{ fontSize: 'var(--font-2xl)', fontWeight: 'var(--font-weight-bold)', marginBottom: 'var(--space-6)' }}>
        Welcome to <span style={{ background: 'var(--color-gradient-accent)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>Atenex Nova</span>
      </h2>
      <p style={{ color: 'var(--color-text-secondary)', maxWidth: '600px', lineHeight: 'var(--line-height-relaxed)' }}>
        Plataforma local de memoria documental y RAG de nueva generación.
        Carga documentos, construye memoria y obtén respuestas con grounding real.
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: 'var(--space-6)', marginTop: 'var(--space-8)' }}>
        {[
          { title: 'Collections', value: '—', icon: '▦', desc: 'Corpus documentales' },
          { title: 'Documents', value: '—', icon: '📄', desc: 'Documentos indexados' },
          { title: 'Queries', value: '—', icon: '⌕', desc: 'Consultas realizadas' },
          { title: 'Jobs', value: '—', icon: '⟳', desc: 'Trabajos procesados' },
        ].map(stat => (
          <div key={stat.title} className="card">
            <div className="card__header">
              <span style={{ fontSize: '1.5rem' }}>{stat.icon}</span>
              <span className="badge badge--accent">{stat.value}</span>
            </div>
            <div className="card__title">{stat.title}</div>
            <p style={{ fontSize: 'var(--font-sm)', color: 'var(--color-text-tertiary)', marginTop: 'var(--space-1)' }}>{stat.desc}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export function CollectionsPage() {
  return (
    <div className="animate-fade-in-up">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-6)' }}>
        <h2 style={{ fontSize: 'var(--font-xl)', fontWeight: 'var(--font-weight-bold)' }}>Collections</h2>
        <button className="btn btn-primary">+ New Collection</button>
      </div>
      <div className="empty-state">
        <div className="empty-state__icon">▦</div>
        <div className="empty-state__title">No collections yet</div>
        <p>Create your first collection to start building document memory.</p>
      </div>
    </div>
  );
}

export function QueryPage() {
  const [collections, setCollections] = useState<Collection[]>([]);
  const [collectionId, setCollectionId] = useState('');
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState('auto');
  const [action, setAction] = useState<'search' | 'answer'>('answer');
  const [searchResult, setSearchResult] = useState<QuerySearchResponse | null>(null);
  const [answerResult, setAnswerResult] = useState<AnswerResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingCollections, setLoadingCollections] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let mounted = true;
    api.listCollections()
      .then(items => {
        if (!mounted) return;
        setCollections(items);
        setCollectionId(items[0]?.id ?? '');
      })
      .catch(() => {
        if (mounted) setError('Unable to load collections.');
      })
      .finally(() => {
        if (mounted) setLoadingCollections(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const canSearch = collectionId.length > 0 && query.trim().length > 0 && !loading && !loadingCollections;

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!collectionId || !query.trim()) return;
    setLoading(true);
    setError('');
    try {
      if (action === 'search') {
        const response = await api.searchQuery({
          collection_id: collectionId,
          query: query.trim(),
          mode,
        });
        setSearchResult(response);
        setAnswerResult(null);
      } else {
        const response = await api.answerQuery({
          collection_id: collectionId,
          query: query.trim(),
          mode,
          generation_profile: 'standard',
        });
        setAnswerResult(response);
        setSearchResult(null);
      }
    } catch (submissionError) {
      setError(submissionError instanceof Error ? submissionError.message : 'Search failed.');
      setSearchResult(null);
      setAnswerResult(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="animate-fade-in-up">
      <h2 style={{ fontSize: 'var(--font-xl)', fontWeight: 'var(--font-weight-bold)', marginBottom: 'var(--space-6)' }}>Query Workspace</h2>
      <form className="card" style={{ padding: 'var(--space-8)', display: 'grid', gap: 'var(--space-5)' }} onSubmit={handleSubmit}>
        <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
          {(['search', 'answer'] as const).map(item => (
            <button
              key={item}
              type="button"
              className={`btn ${action === item ? 'btn-primary' : ''}`}
              onClick={() => setAction(item)}
            >
              {item === 'search' ? 'Search' : 'Answer'}
            </button>
          ))}
        </div>

        <div style={{ display: 'grid', gap: 'var(--space-3)', gridTemplateColumns: 'minmax(220px, 280px) 1fr' }}>
          <label style={{ display: 'grid', gap: 'var(--space-2)' }}>
            <span style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Collection</span>
            <select
              value={collectionId}
              onChange={event => setCollectionId(event.target.value)}
              disabled={loadingCollections}
              style={{
                width: '100%', padding: 'var(--space-4)', background: 'var(--color-bg-primary)',
                border: '1px solid var(--color-border)', borderRadius: 'var(--radius-lg)',
                color: 'var(--color-text-primary)', fontSize: 'var(--font-md)',
              }}
            >
              {collections.length === 0 ? (
                <option value="">No collections available</option>
              ) : (
                collections.map(item => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))
              )}
            </select>
          </label>

          <label style={{ display: 'grid', gap: 'var(--space-2)' }}>
            <span style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Route mode</span>
            <select
              value={mode}
              onChange={event => setMode(event.target.value)}
              style={{
                width: '100%', padding: 'var(--space-4)', background: 'var(--color-bg-primary)',
                border: '1px solid var(--color-border)', borderRadius: 'var(--radius-lg)',
                color: 'var(--color-text-primary)', fontSize: 'var(--font-md)',
              }}
            >
              {['auto', 'exact', 'factual_local', 'multi_hop', 'global', 'argumentative', 'visual'].map(item => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label style={{ display: 'grid', gap: 'var(--space-2)' }}>
          <span style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Question</span>
          <textarea
            value={query}
            onChange={event => setQuery(event.target.value)}
            rows={4}
            placeholder="Ask a question about your documents..."
            style={{
              width: '100%', padding: 'var(--space-4) var(--space-5)',
              background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-lg)', color: 'var(--color-text-primary)',
              fontSize: 'var(--font-md)', resize: 'vertical', lineHeight: 'var(--line-height-relaxed)',
            }}
          />
        </label>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-4)', flexWrap: 'wrap' }}>
          <p style={{ color: 'var(--color-text-tertiary)', fontSize: 'var(--font-sm)' }}>
            {action === 'search'
              ? 'The router will choose a retrieval mode when auto is selected.'
              : 'The answer flow reuses the same router and adds grounded synthesis with citations.'}
          </p>
          <button className="btn btn-primary" type="submit" disabled={!canSearch}>
            {loading ? (action === 'search' ? 'Searching...' : 'Answering...') : action === 'search' ? 'Search' : 'Answer'}
          </button>
        </div>
      </form>

      {error ? (
        <div className="card" style={{ marginTop: 'var(--space-6)', borderColor: 'rgba(239,68,68,0.35)' }}>
          <p style={{ color: 'var(--color-error)' }}>{error}</p>
        </div>
      ) : null}

      {searchResult ? (
        <div style={{ display: 'grid', gap: 'var(--space-6)', marginTop: 'var(--space-6)' }}>
          <div className="card" style={{ display: 'grid', gap: 'var(--space-3)' }}>
            <div className="card__header">
              <div className="card__title">Routing Summary</div>
              <span className="badge badge--accent">{searchResult.route_mode}</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 'var(--space-4)' }}>
              <div>
                <div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)', textTransform: 'uppercase' }}>Intent</div>
                <div style={{ marginTop: 'var(--space-1)', fontWeight: 'var(--font-weight-semibold)' }}>{searchResult.intent}</div>
              </div>
              <div>
                <div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)', textTransform: 'uppercase' }}>Language</div>
                <div style={{ marginTop: 'var(--space-1)', fontWeight: 'var(--font-weight-semibold)' }}>{searchResult.language}</div>
              </div>
              <div>
                <div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)', textTransform: 'uppercase' }}>Hits</div>
                <div style={{ marginTop: 'var(--space-1)', fontWeight: 'var(--font-weight-semibold)' }}>{searchResult.total_hits}</div>
              </div>
            </div>
          </div>

          <div className="card" style={{ display: 'grid', gap: 'var(--space-4)' }}>
            <div className="card__title">Ranked Evidence</div>
            {searchResult.hits.length === 0 ? (
              <div className="empty-state" style={{ padding: 'var(--space-10) var(--space-4)' }}>
                <div className="empty-state__icon">⌕</div>
                <div className="empty-state__title">No hits</div>
                <p>No evidence matched the current query.</p>
              </div>
            ) : (
              <div style={{ display: 'grid', gap: 'var(--space-4)' }}>
                {searchResult.hits.map(hit => (
                  <EvidenceCard key={hit.id} evidence={hit} />
                ))}
              </div>
            )}
          </div>
        </div>
      ) : answerResult ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 2fr) minmax(280px, 1fr)', gap: 'var(--space-6)', marginTop: 'var(--space-6)' }}>
          <div style={{ display: 'grid', gap: 'var(--space-6)' }}>
            <AnswerPanel answer={answerResult} />
            <PageViewer evidence={answerResult.evidence} />
            <div className="card" style={{ display: 'grid', gap: 'var(--space-4)' }}>
              <div className="card__title">Evidence Pack</div>
              <div style={{ display: 'grid', gap: 'var(--space-4)' }}>
                {answerResult.evidence.map(hit => (
                  <EvidenceCard key={hit.id} evidence={hit} />
                ))}
              </div>
            </div>
          </div>
          <CitationSidebar citations={answerResult.citations} />
        </div>
      ) : (
        <div className="empty-state" style={{ paddingTop: 'var(--space-12)' }}>
          <div className="empty-state__icon">⌕</div>
          <div className="empty-state__title">Ready to search</div>
          <p>Enter a query to search across your document collections.</p>
        </div>
      )}
    </div>
  );
}

export function JobsPage() {
  return (
    <div className="animate-fade-in-up">
      <h2 style={{ fontSize: 'var(--font-xl)', fontWeight: 'var(--font-weight-bold)', marginBottom: 'var(--space-6)' }}>Jobs</h2>
      <div className="empty-state">
        <div className="empty-state__icon">⟳</div>
        <div className="empty-state__title">No jobs</div>
        <p>Background processing tasks will appear here.</p>
      </div>
    </div>
  );
}
