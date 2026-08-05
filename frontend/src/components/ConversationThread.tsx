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
  verdict?: string;
  verificationIssues?: string[];
  groundingScore?: number;
  citationsCount?: number;
  totalHits?: number;
  hits?: QueryHit[];
  createdAt: string;
  isPending?: boolean;
}

interface ConversationThreadProps {
  turns: ConversationThreadTurn[];
  activeTurnId: string;
  hydratingTurnId: string;
  pendingTurnId: string;
  onSelectTurn: (id: string) => void;
}

export function ConversationThread({ turns, activeTurnId, hydratingTurnId, pendingTurnId, onSelectTurn }: ConversationThreadProps) {
  if (turns.length === 0) {
    return (
      <div className="query-empty-state" role="status" aria-live="polite">
        <h3 className="query-empty-state__title">Pregunta al corpus</h3>
        <p>Atenex buscará en todos los documentos y mostrará la respuesta aquí.</p>
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
          loading={hydratingTurnId === turn.id || pendingTurnId === turn.id || turn.isPending === true}
          kind={turn.kind}
          query={turn.query}
          answer={turn.answer}
          routeMode={turn.routeMode}
          intent={turn.intent}
          language={turn.language}
          verdict={turn.verdict}
          verificationIssues={turn.verificationIssues}
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
