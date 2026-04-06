import type { AnswerResponse } from '../types/api';

interface AnswerPanelProps {
  answer: AnswerResponse;
}

export function AnswerPanel({ answer }: AnswerPanelProps) {
  return (
    <section className="card" style={{ display: 'grid', gap: 'var(--space-5)' }}>
      <div className="card__header">
        <div className="card__title">Answer</div>
        <span className="badge badge--accent">{answer.plan_type}</span>
      </div>
      <p style={{ color: 'var(--color-text-primary)', lineHeight: 'var(--line-height-relaxed)', whiteSpace: 'pre-wrap' }}>{answer.answer}</p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 'var(--space-4)' }}>
        <div>
          <div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)', textTransform: 'uppercase' }}>Verdict</div>
          <div style={{ marginTop: 'var(--space-1)', fontWeight: 'var(--font-weight-semibold)' }}>{answer.verdict}</div>
        </div>
        <div>
          <div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)', textTransform: 'uppercase' }}>Grounding</div>
          <div style={{ marginTop: 'var(--space-1)', fontWeight: 'var(--font-weight-semibold)' }}>{answer.grounding_score.toFixed(3)}</div>
        </div>
        <div>
          <div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)', textTransform: 'uppercase' }}>Route</div>
          <div style={{ marginTop: 'var(--space-1)', fontWeight: 'var(--font-weight-semibold)' }}>{answer.route_mode}</div>
        </div>
        <div>
          <div style={{ fontSize: 'var(--font-xs)', color: 'var(--color-text-tertiary)', textTransform: 'uppercase' }}>Intent</div>
          <div style={{ marginTop: 'var(--space-1)', fontWeight: 'var(--font-weight-semibold)' }}>{answer.intent}</div>
        </div>
      </div>
    </section>
  );
}