/* Sidebar navigation component */
import { NavLink } from 'react-router-dom';

const NAV_ITEMS = [
  { path: '/', label: 'Dashboard', icon: '◈' },
  { path: '/collections', label: 'Collections', icon: '▦' },
  { path: '/query', label: 'Query', icon: '⌕' },
  { path: '/jobs', label: 'Jobs', icon: '⟳' },
];

export function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar__brand">
        <div className="sidebar__brand-icon">A</div>
        <span className="sidebar__brand-text">Atenex Nova</span>
      </div>
      <nav className="sidebar__nav">
        {NAV_ITEMS.map(item => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            className={({ isActive }) =>
              `sidebar__link${isActive ? ' sidebar__link--active' : ''}`
            }
          >
            <span className="sidebar__link-icon">{item.icon}</span>
            {item.label}
          </NavLink>
        ))}
      </nav>
      <div style={{ padding: 'var(--space-4)', borderTop: '1px solid var(--color-border)', fontSize: 'var(--font-xs)', color: 'var(--color-text-muted)' }}>
        Atenex Nova v0.1.0
      </div>
    </aside>
  );
}
