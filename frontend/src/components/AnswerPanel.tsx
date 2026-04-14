import type { AnswerResponse } from '../types/api';

interface AnswerPanelProps {
  answer: AnswerResponse;
}

export function AnswerPanel({ answer }: AnswerPanelProps) {
  return (
    <section className="query-entity-card query-answer">
      <div className="card__header">
        <div>
          <div className="card__title">Respuesta</div>
          <p className="query-panel-note">{answer.plan_type}</p>
        </div>
        <span className="badge badge--accent">{answer.verdict}</span>
      </div>

      <p className="query-answer__body">{answer.answer}</p>

      <div className="query-answer__grid">
        <div className="query-answer__metric">
          <div className="query-answer__label">Veredicto</div>
          <div className="query-answer__value">{answer.verdict}</div>
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
          <div className="query-answer__label">Intención</div>
          <div className="query-answer__value">{answer.intent}</div>
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

      <div className="query-answer__footer">
        <span className="query-chip">ID {answer.query_id}</span>
        <span className="query-chip">Colección {answer.collection_id}</span>
      </div>
    </section>
  );
}