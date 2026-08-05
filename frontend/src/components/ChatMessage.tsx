import type { QueryHit } from '../types/api';
import {
  assessAnswerTrust,
  formatVerificationIssues,
  getAnswerVerificationPresentation,
} from './answerTrust';
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
  verdict?: string;
  verificationIssues?: string[];
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
  language,
  verdict,
  verificationIssues,
  groundingScore,
  citationsCount,
  totalHits,
  hits,
  createdAt,
  onSelect,
}: ChatMessageProps) {
  const verification = getAnswerVerificationPresentation(verdict);
  const trustAlert = kind === 'answer'
    ? assessAnswerTrust(verdict, groundingScore, citationsCount)
    : null;
  const readableIssues = formatVerificationIssues(verificationIssues);

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
    <li className={`conversation-turn${active ? ' conversation-turn--active' : ''}${loading ? ' conversation-turn--pending' : ''}`} role="listitem" data-turn-id={id}>
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
          <div className="chat-bubble chat-bubble--user">
            <div className="chat-bubble__meta">
              <span>{loading ? 'Enviado ahora' : formatTurnDate(createdAt)}</span>
            </div>
            <p>{query}</p>
          </div>
        </div>

        <div className="chat-row chat-row--assistant">
          <div className="chat-bubble chat-bubble--assistant">
            <div className="chat-bubble__meta">
              <span>Atenex</span>
              <span>{loading ? 'Escribiendo...' : kind === 'answer' ? 'Respuesta' : 'Búsqueda'}</span>
            </div>
            {kind === 'answer' && !loading ? (
              <div
                className={`answer-trust-summary answer-trust-summary--${verification.tone}`}
                role="status"
                aria-label={`Estado de verificación: ${verification.label}`}
              >
                <span className={`badge badge--${verification.tone}`}>{verification.label}</span>
                <span className="answer-trust-summary__description">{verification.description}</span>
                {typeof groundingScore === 'number' ? (
                  <span className="answer-trust-summary__score">
                    Fundamento {(groundingScore * 100).toFixed(0)}%
                  </span>
                ) : null}
              </div>
            ) : null}
            <div className="chat-bubble__text">
              {loading ? (
                <div className="chat-message__loading-state">
                  <span>{assistantText}</span>
                  <TypingIndicator />
                </div>
              ) : (
                <>
                  {trustAlert ? (
                    <div
                      className={`answer-trust-alert answer-trust-alert--${trustAlert.tone}`}
                      role={trustAlert.tone === 'error' ? 'alert' : 'status'}
                      aria-live={trustAlert.tone === 'error' ? 'assertive' : 'polite'}
                    >
                      <span className="answer-trust-alert__icon" aria-hidden="true">!</span>
                      <span>
                        <strong>{trustAlert.title}:</strong>{' '}
                        {trustAlert.message}
                      </span>
                    </div>
                  ) : null}
                  <div style={{ whiteSpace: 'pre-wrap' }}>{assistantText}</div>
                  {readableIssues.length > 0 ? (
                    <div className="answer-trust-issues" aria-label="Aspectos de la respuesta que requieren revisión">
                      <strong>Qué debes revisar</strong>
                      <ul>
                        {readableIssues.map(issue => <li key={issue}>{issue}</li>)}
                      </ul>
                    </div>
                  ) : null}
                </>
              )}
            </div>
          </div>
        </div>
      </article>
    </li>
  );
}
