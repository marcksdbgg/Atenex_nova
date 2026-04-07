/* Top bar component */
import { useHealth } from '../hooks/useHealth';

interface TopBarProps {
  navigationCollapsed: boolean;
  onOpenNavigation: () => void;
  onToggleNavigation: () => void;
  title: string;
}

export function TopBar({ navigationCollapsed, onOpenNavigation, onToggleNavigation, title }: TopBarProps) {
  const { connected, version, checking } = useHealth();

  return (
    <header className="topbar">
      <div className="topbar__left">
        <button
          aria-label="Abrir navegación"
          className="topbar__nav-btn topbar__nav-btn--mobile"
          onClick={onOpenNavigation}
          type="button"
        >
          <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
            <path d="M4 7h16M4 12h16M4 17h16" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" />
          </svg>
        </button>
        <button
          aria-label={navigationCollapsed ? 'Expandir panel lateral' : 'Contraer panel lateral'}
          className="topbar__nav-btn topbar__nav-btn--desktop"
          onClick={onToggleNavigation}
          type="button"
        >
          <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
            <path d={navigationCollapsed ? 'M8 6h8M8 12h8M8 18h8M4 4v16' : 'M8 6h8M8 12h8M8 18h8M20 4v16'} stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" />
          </svg>
        </button>
        <h1 className="topbar__title">{title}</h1>
      </div>
      <div className="topbar__status">
        {checking ? (
          <span className="animate-pulse">Comprobando API...</span>
        ) : (
          <>
            <span className={`status-dot${connected ? '' : ' status-dot--error'}`} />
            <span>{connected ? `API v${version}` : 'Desconectada'}</span>
          </>
        )}
      </div>
    </header>
  );
}
