import type { QueryHit } from '../types/api';
import { normalizeAssistantText } from './chatMessageText';

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

function TypingIndicator() {
  return (
    <div className="chat-typing" aria-hidden="true">
      <span />
      <span />
      <span />
    </div>
  );
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
  const isLowConfidenceAnswer = kind === 'answer'
    && typeof groundingScore === 'number'
    && groundingScore < 0.55
    && (citationsCount ?? 0) < 2;

  const rawAnswer = answer?.trim() ?? '';
  const assistantText = kind === 'answer'
    ? (loading
      ? 'Gemma 4 está generando una respuesta fundamentada.'
      : (rawAnswer ? normalizeAssistantText(rawAnswer, language) : 'La respuesta está disponible en el panel lateral.'))
    : (loading
      ? 'Recuperando evidencia del corpus.'
      : `Encontré ${totalHits ?? hits?.length ?? 0} evidencias para esta búsqueda en modo ${routeMode}.`);

  const handleSelect = () => {
    onSelect(id);
  };

  return (
    <li className={`conversation-turn${active ? ' conversation-turn--active' : ''}${loading ? ' conversation-turn--pending' : ''}`} role="listitem">
      <article
        className="conversation-turn__surface"
        role="button"
        tabIndex={0}
        aria-pressed={active}
        aria-label={`Abrir detalles del turno ${query}`}
        onClick={handleSelect}
        onKeyDown={event => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            handleSelect();
          }
        }}
      >
        <div className="chat-row chat-row--user">
          <div className="chat-row__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm0 2c-4.6 0-8 2.1-8 5v1h16v-1c0-2.9-3.4-5-8-5Z" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div className="chat-bubble chat-bubble--user">
            <div className="chat-bubble__meta">
              <span>Usuario</span>
              <span>{loading ? 'Enviado ahora' : formatTurnDate(createdAt)}</span>
            </div>
            <p>{query}</p>
          </div>
        </div>

        <div className="chat-row chat-row--assistant">
          <div className="chat-row__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              <rect x="4" y="4" width="16" height="13" rx="3" stroke="currentColor" strokeWidth="1.7" />
              <path d="m9 20 3-3 3 3" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
              <circle cx="9" cy="10" r="1" fill="currentColor" />
              <circle cx="15" cy="10" r="1" fill="currentColor" />
            </svg>
          </div>
          <div className="chat-bubble chat-bubble--assistant">
            <div className="chat-bubble__meta">
              <span>Asistente IA</span>
              <span>{loading ? 'Escribiendo...' : kind === 'answer' ? 'Respuesta' : 'Búsqueda'}</span>
            </div>
            <div className="chat-bubble__text">
              {loading ? (
                <div className="chat-message__loading-state">
                  <span>{assistantText}</span>
                  <TypingIndicator />
                </div>
              ) : (
                <>
                  {isLowConfidenceAnswer && (
                    <div className="warning-banner" style={{
                      background: 'rgba(239, 68, 68, 0.08)',
                      border: '1px solid rgba(239, 68, 68, 0.25)',
                      color: '#b91c1c',
                      padding: '8px 12px',
                      borderRadius: '4px',
                      fontSize: '0.75rem',
                      marginBottom: '8px',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px'
                    }}>
                      <span>⚠️</span>
                      <span><strong>Baja confianza:</strong> Esta respuesta carece de evidencia sólida. Valídala con las citas del panel lateral.</span>
                    </div>
                  )}
                  <div style={{ whiteSpace: 'pre-wrap' }}>{assistantText}</div>
                </>
              )}
            </div>
          </div>
        </div>

        <div className="conversation-turn__chips">
          <span className="tag tag--info">{routeMode}</span>
          <span className="tag tag--soft">{intent}</span>
          <span className="tag tag--soft">{language}</span>
          {kind === 'answer' ? (
            <>
              <span className="tag tag--success">Grounding {groundingScore?.toFixed(3) ?? '-'}</span>
              <span className="tag tag--warning">{citationsCount ?? 0} citas</span>
              {isLowConfidenceAnswer ? <span className="tag tag--danger">Baja confianza</span> : null}
            </>
          ) : null}
        </div>
      </article>
    </li>
  );
}
