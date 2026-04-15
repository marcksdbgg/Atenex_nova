import { ChatMessage } from './ChatMessage';
import type { QueryHit } from '../types/api';

export interface ConversationThreadTurn {
  id: string;
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
}

interface ConversationThreadProps {
  turns: ConversationThreadTurn[];
  activeTurnId: string;
  hydratingTurnId: string;
  onSelectTurn: (id: string) => void;
}

export function ConversationThread({ turns, activeTurnId, hydratingTurnId, onSelectTurn }: ConversationThreadProps) {
  if (turns.length === 0) {
    return (
      <div className="query-empty-state" role="status" aria-live="polite">
        <div className="query-empty-state__icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none">
            <path d="m21 21-4.4-4.4M10.5 18a7.5 7.5 0 1 1 0-15 7.5 7.5 0 0 1 0 15Z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <h3 className="query-empty-state__title">Empieza una conversación</h3>
        <p>Haz una pregunta para abrir memoria, evidencia y citas en esta colección.</p>
      </div>
    );
  }

  return (
    <ul className="conversation-thread" role="list" aria-live="polite">
      {turns.map(turn => (
        <ChatMessage
          key={turn.id}
          id={turn.id}
          active={activeTurnId === turn.id}
          loading={hydratingTurnId === turn.id}
          kind={turn.kind}
          query={turn.query}
          answer={turn.answer}
          routeMode={turn.routeMode}
          intent={turn.intent}
          language={turn.language}
          groundingScore={turn.groundingScore}
          citationsCount={turn.citationsCount}
          totalHits={turn.totalHits}
          hits={turn.hits}
          createdAt={turn.createdAt}
          onSelect={onSelectTurn}
        />
      ))}
    </ul>
  );
}
