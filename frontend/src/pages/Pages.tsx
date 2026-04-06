/* Page stubs for routing */

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
  return (
    <div className="animate-fade-in-up">
      <h2 style={{ fontSize: 'var(--font-xl)', fontWeight: 'var(--font-weight-bold)', marginBottom: 'var(--space-6)' }}>Query Workspace</h2>
      <div className="card" style={{ padding: 'var(--space-8)' }}>
        <input
          type="text"
          placeholder="Ask a question about your documents..."
          style={{
            width: '100%', padding: 'var(--space-4) var(--space-5)',
            background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius-lg)', color: 'var(--color-text-primary)',
            fontSize: 'var(--font-md)',
          }}
        />
      </div>
      <div className="empty-state" style={{ paddingTop: 'var(--space-12)' }}>
        <div className="empty-state__icon">⌕</div>
        <div className="empty-state__title">Ready to search</div>
        <p>Enter a query to search across your document collections.</p>
      </div>
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
