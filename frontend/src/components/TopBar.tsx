/* Top bar component */
import { useHealth } from '../hooks/useHealth';

interface TopBarProps {
  title: string;
}

export function TopBar({ title }: TopBarProps) {
  const { connected, version, checking } = useHealth();

  return (
    <header className="topbar">
      <h1 className="topbar__title">{title}</h1>
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
