/* Atenex Nova — Main App with routing */
import { useState } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';

import { Sidebar } from './components/Sidebar';
import { TopBar } from './components/TopBar';
import { DashboardPage, CollectionsPage, QueryPage, JobsPage, ObservabilityPage, EvaluationPage } from './pages/Pages';

const ROUTES = [
  { path: '/', element: <DashboardPage />, title: 'Panel' },
  { path: '/collections', element: <CollectionsPage />, title: 'Colecciones' },
  { path: '/query', element: <QueryPage />, title: 'Espacio de consulta' },
  { path: '/observability', element: <ObservabilityPage />, title: 'Observabilidad' },
  { path: '/evaluation', element: <EvaluationPage />, title: 'Evaluación' },
  { path: '/jobs', element: <JobsPage />, title: 'Tareas' },
];

function AppShell() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  return (
    <div className={`app-shell${sidebarCollapsed ? ' app-shell--sidebar-collapsed' : ''}${mobileNavOpen ? ' app-shell--mobile-nav-open' : ''}`}>
      <Sidebar
        collapsed={sidebarCollapsed}
        mobileOpen={mobileNavOpen}
        onToggleCollapsed={() => setSidebarCollapsed(current => !current)}
        onCloseMobile={() => setMobileNavOpen(false)}
      />
      {mobileNavOpen ? (
        <button
          aria-label="Cerrar navegación"
          className="app-shell__backdrop"
          onClick={() => setMobileNavOpen(false)}
          type="button"
        />
      ) : null}
      <main className={`main-content${sidebarCollapsed ? ' main-content--collapsed' : ''}`}>
        <Routes>
          {ROUTES.map(r => (
            <Route
              key={r.path}
              path={r.path}
              element={
                <>
                  <TopBar
                    navigationCollapsed={sidebarCollapsed}
                    onOpenNavigation={() => setMobileNavOpen(true)}
                    onToggleNavigation={() => setSidebarCollapsed(current => !current)}
                    title={r.title}
                  />
                  <div className="page-content">{r.element}</div>
                </>
              }
            />
          ))}
        </Routes>
      </main>
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AppShell />
    </BrowserRouter>
  );
}

export default App;
