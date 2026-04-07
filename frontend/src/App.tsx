/* Atenex Nova — Main App with routing */
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Sidebar } from './components/Sidebar';
import { TopBar } from './components/TopBar';
import { DashboardPage, CollectionsPage, QueryPage, JobsPage, EvaluationPage } from './pages/Pages';

const ROUTES = [
  { path: '/', element: <DashboardPage />, title: 'Panel' },
  { path: '/collections', element: <CollectionsPage />, title: 'Colecciones' },
  { path: '/query', element: <QueryPage />, title: 'Espacio de consulta' },
  { path: '/evaluation', element: <EvaluationPage />, title: 'Evaluación' },
  { path: '/jobs', element: <JobsPage />, title: 'Tareas' },
];

function AppShell() {
  return (
    <div className="app-shell">
      <Sidebar />
      <main className="main-content">
        <Routes>
          {ROUTES.map(r => (
            <Route
              key={r.path}
              path={r.path}
              element={
                <>
                  <TopBar title={r.title} />
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
