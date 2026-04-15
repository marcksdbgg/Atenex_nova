import type { QueryHit } from '../types/api';

interface ChatMessageProps {
  id: string;
  active: boolean;
  loading: boolean;
  kind: 'search' | 'answer';
  query: string;
  answer?: string;
  routeMode: string;
  intent: string;
  language: string;
  groundingScore?: number;
  citationsCount?: number;
  totalHits?: number;
  hits?: QueryHit[];
  createdAt: string;
  onSelect: (id: string) => void;
}

function formatTurnDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat('es', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

export function ChatMessage({
  id,
  active,
  loading,
  kind,
  query,
  answer,
  routeMode,
  intent,
  language,
  groundingScore,
  citationsCount,
  totalHits,
  hits,
  createdAt,
  onSelect,
}: ChatMessageProps) {
  return (
    <li className="conversation-item" role="listitem">
      <button
        type="button"
        className={`conversation-card${active ? ' conversation-card--active' : ''}`}
        aria-pressed={active}
        aria-label={`Abrir turno ${query}`}
        onClick={() => onSelect(id)}
      >
        <div className="conversation-card__meta">
          <span className="tag tag--accent">{kind === 'answer' ? 'Turno completo' : 'Búsqueda'}</span>
          <span className="conversation-card__date">{formatTurnDate(createdAt)}</span>
        </div>

        <div className="message message--user">
          <div className="message__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm0 2c-4.6 0-8 2.1-8 5v1h16v-1c0-2.9-3.4-5-8-5Z" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div className="message__content">
            <div className="message__label">Usuario</div>
            <p>{query}</p>
          </div>
        </div>

        <div className="message message--assistant">
          <div className="message__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              <rect x="4" y="4" width="16" height="13" rx="3" stroke="currentColor" strokeWidth="1.7" />
              <path d="m9 20 3-3 3 3" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
              <circle cx="9" cy="10" r="1" fill="currentColor" />
              <circle cx="15" cy="10" r="1" fill="currentColor" />
            </svg>
          </div>
          <div className="message__content">
            <div className="message__label">Asistente</div>
            {kind === 'answer' ? (
              <p>{loading ? 'Cargando detalle de la respuesta...' : (answer || 'La respuesta está disponible en el panel de contexto.')}</p>
            ) : (
              <p>
                {loading
                  ? 'Recuperando evidencia del turno...'
                  : `El modo ${routeMode} devolvió ${totalHits ?? hits?.length ?? 0} evidencias para esta búsqueda.`}
              </p>
            )}
          </div>
        </div>

        <div className="conversation-card__tags">
          <span className="tag tag--info">{routeMode}</span>
          <span className="tag tag--soft">{intent}</span>
          <span className="tag tag--soft">{language}</span>
          {kind === 'answer' ? (
            <>
              <span className="tag tag--success">Grounding {groundingScore?.toFixed(3) ?? '—'}</span>
              <span className="tag tag--warning">{citationsCount ?? 0} citas</span>
            </>
          ) : null}
        </div>
      </button>
    </li>
  );
}
