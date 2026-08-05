import type { AnswerResponse } from '../types/api';
import {
  assessAnswerTrust,
  formatVerificationIssues,
  getAnswerVerificationPresentation,
} from './answerTrust';

interface AnswerPanelProps {
  answer: AnswerResponse;
}

export function AnswerPanel({ answer }: AnswerPanelProps) {
  const verification = getAnswerVerificationPresentation(answer.verdict);
  const trustAlert = assessAnswerTrust(
    answer.verdict,
    answer.grounding_score,
    answer.citations.length,
  );
  const readableIssues = formatVerificationIssues(answer.verification_issues);

  return (
    <section className="query-entity-card query-answer">
      <div className="card__header">
        <div>
          <div className="card__title">Respuesta</div>
          <p className="query-panel-note">{answer.plan_type}</p>
        </div>
        <span className={`badge badge--${verification.tone}`}>{verification.label}</span>
      </div>

      <p className="query-panel-note">{verification.description}</p>
      {trustAlert ? (
        <div
          className={`answer-trust-alert answer-trust-alert--${trustAlert.tone}`}
          role={trustAlert.tone === 'error' ? 'alert' : 'status'}
        >
          <span className="answer-trust-alert__icon" aria-hidden="true">!</span>
          <span><strong>{trustAlert.title}:</strong> {trustAlert.message}</span>
        </div>
      ) : null}

      <p className="query-answer__body">{answer.answer}</p>

      <div className="query-answer__grid">
        <div className="query-answer__metric">
          <div className="query-answer__label">Verificación</div>
          <div className="query-answer__value">{verification.label}</div>
        </div>
        <div className="query-answer__metric">
          <div className="query-answer__label">Fundamento</div>
          <div className="query-answer__value">{answer.grounding_score.toFixed(3)}</div>
        </div>
        <div className="query-answer__metric">
          <div className="query-answer__label">Ruta</div>
          <div className="query-answer__value">{answer.route_mode}</div>
        </div>
        <div className="query-answer__metric">
          <div className="query-answer__label">Intencion</div>
          <div className="query-answer__value">{answer.intent}</div>
        </div>
        <div className="query-answer__metric">
          <div className="query-answer__label">Motivo ruta</div>
          <div className="query-answer__value query-answer__value--truncate" title={answer.route_reason}>{answer.route_reason}</div>
        </div>
        <div className="query-answer__metric">
          <div className="query-answer__label">Idioma</div>
          <div className="query-answer__value">{answer.language}</div>
        </div>
        <div className="query-answer__metric">
          <div className="query-answer__label">Consulta</div>
          <div className="query-answer__value query-answer__value--truncate" title={answer.normalized_query}>{answer.normalized_query}</div>
        </div>
      </div>

      {readableIssues.length > 0 ? (
        <div className="answer-trust-issues" aria-label="Aspectos de la respuesta que requieren revisión">
          <strong>Qué debes revisar</strong>
          <ul>
            {readableIssues.map(issue => <li key={issue}>{issue}</li>)}
          </ul>
        </div>
      ) : null}

      <div className="query-answer__footer">
        <span className="query-chip">ID {answer.query_id}</span>
        <span className="query-chip">Coleccion {answer.collection_id}</span>
        <span className="query-chip">Prompt {answer.prompt_version}</span>
      </div>
    </section>
  );
}
