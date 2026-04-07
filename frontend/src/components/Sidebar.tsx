/* Sidebar navigation component */
import { NavLink } from 'react-router-dom';

type NavIcon = 'panel' | 'collections' | 'query' | 'observability' | 'evaluation' | 'jobs';

const NAV_ITEMS = [
  { path: '/', label: 'Panel', icon: 'panel' as NavIcon },
  { path: '/collections', label: 'Colecciones', icon: 'collections' as NavIcon },
  { path: '/query', label: 'Consulta', icon: 'query' as NavIcon },
  { path: '/observability', label: 'Observabilidad', icon: 'observability' as NavIcon },
  { path: '/evaluation', label: 'Evaluación', icon: 'evaluation' as NavIcon },
  { path: '/jobs', label: 'Tareas', icon: 'jobs' as NavIcon },
];

interface SidebarProps {
  collapsed: boolean;
  mobileOpen: boolean;
  onToggleCollapsed: () => void;
  onCloseMobile: () => void;
}

function SidebarIcon({ icon }: { icon: NavIcon }) {
  switch (icon) {
    case 'panel':
      return (
        <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
          <path d="M4 5h7v6H4V5zm9 0h7v3h-7V5zM4 13h7v6H4v-6zm9-3h7v9h-7v-9z" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" />
        </svg>
      );
    case 'collections':
      return (
        <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
          <path d="M4 4h7v7H4V4zm9 0h7v7h-7V4zM4 13h7v7H4v-7zm9 0h7v7h-7v-7z" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" />
        </svg>
      );
    case 'query':
      return (
        <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
          <path d="m21 21-4.35-4.35M10.5 18a7.5 7.5 0 1 1 0-15 7.5 7.5 0 0 1 0 15Z" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" />
        </svg>
      );
    case 'observability':
      return (
        <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
          <path d="M4 18V6m5 12v-8m5 8V8m5 10V4" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" />
        </svg>
      );
    case 'evaluation':
      return (
        <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
          <path d="M12 3v18M3 12h18M6.5 6.5l11 11m0-11-11 11" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" />
        </svg>
      );
    case 'jobs':
      return (
        <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
          <path d="M21 12a9 9 0 1 1-2.64-6.36M21 4v6h-6" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" />
        </svg>
      );
    default:
      return null;
  }
}

export function Sidebar({ collapsed, mobileOpen, onToggleCollapsed, onCloseMobile }: SidebarProps) {
  return (
    <aside className={`sidebar${collapsed ? ' sidebar--collapsed' : ''}${mobileOpen ? ' sidebar--mobile-open' : ''}`}>
      <div className="sidebar__brand">
        <div className="sidebar__brand-icon">A</div>
        <span className="sidebar__brand-text">Atenex Nova</span>
        <button
          aria-label={collapsed ? 'Expandir panel izquierdo' : 'Contraer panel izquierdo'}
          className="sidebar__collapse-btn"
          onClick={onToggleCollapsed}
          type="button"
        >
          <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
            <path d={collapsed ? 'm9 6 6 6-6 6' : 'm15 6-6 6 6 6'} stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.9" />
          </svg>
        </button>
      </div>
      <nav className="sidebar__nav">
        {NAV_ITEMS.map(item => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            onClick={onCloseMobile}
            className={({ isActive }) =>
              `sidebar__link${isActive ? ' sidebar__link--active' : ''}`
            }
          >
            <span className="sidebar__link-icon"><SidebarIcon icon={item.icon} /></span>
            <span className="sidebar__link-label">{item.label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="sidebar__footer">
        <span className="sidebar__footer-text">Atenex Nova v0.1.0</span>
      </div>
    </aside>
  );
}
