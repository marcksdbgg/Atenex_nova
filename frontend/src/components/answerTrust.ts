export type AnswerTrustTone = 'success' | 'warning' | 'error' | 'neutral';

export interface AnswerVerificationPresentation {
  key: 'verified' | 'partially_verified' | 'unverified' | 'conflicting' | 'unavailable' | 'unknown';
  label: string;
  description: string;
  tone: AnswerTrustTone;
  requiresAlert: boolean;
}

export interface AnswerTrustAlert {
  title: string;
  message: string;
  tone: 'warning' | 'error';
}

const ISSUE_MESSAGES: Readonly<Record<string, string>> = {
  citation_mismatch: 'Una cita no coincide con la afirmación que pretende respaldar.',
  contradictory_evidence: 'Las fuentes relevantes presentan información contradictoria.',
  empty_answer: 'No se produjo texto de respuesta.',
  hallucination: 'La respuesta contiene información que no aparece respaldada por el corpus.',
  incomplete_answer: 'La respuesta no cubre todos los aspectos necesarios de la consulta.',
  insufficient_evidence: 'La evidencia recuperada no es suficiente para sostener la conclusión.',
  invalid_citation_markers: 'La respuesta contiene referencias a citas que no existen.',
  low_grounding: 'La relación entre la respuesta y la evidencia recuperada es débil.',
  missing_citations: 'No se generaron citas explícitas para respaldar la respuesta.',
  overclaiming: 'La respuesta afirma más de lo que permiten concluir las fuentes.',
  uncitable_evidence_references: 'Parte de la evidencia mencionada no puede vincularse a una cita exacta.',
  uncited_claims: 'Hay afirmaciones sin una cita explícita.',
  unresolved_citation_binding: 'Al menos una cita no pudo localizarse en el documento fuente.',
  unresolved_citation_markers: 'No todas las marcas de cita pudieron vincularse con una fuente.',
  unresolved_contradiction: 'La evidencia contiene una contradicción que la respuesta no resolvió.',
  unsupported_claims: 'Hay afirmaciones que no están respaldadas por la evidencia.',
  weak_claim_support: 'Algunas citas no respaldan con suficiente claridad las afirmaciones asociadas.',
  wrong_output_language: 'La respuesta se generó en un idioma distinto al de la consulta.',
};

const VERIFICATION_PRESENTATIONS: Readonly<Record<string, AnswerVerificationPresentation>> = {
  verified: {
    key: 'verified',
    label: 'Verificada',
    description: 'La respuesta superó la verificación con la evidencia recuperada.',
    tone: 'success',
    requiresAlert: false,
  },
  partially_verified: {
    key: 'partially_verified',
    label: 'Verificación parcial',
    description: 'Solo una parte de la respuesta quedó respaldada por la evidencia.',
    tone: 'warning',
    requiresAlert: false,
  },
  unverified: {
    key: 'unverified',
    label: 'No verificada',
    description: 'El verificador no pudo respaldar suficientemente esta respuesta.',
    tone: 'error',
    requiresAlert: true,
  },
  conflicting: {
    key: 'conflicting',
    label: 'Evidencia en conflicto',
    description: 'Las evidencias relevantes contienen contradicciones no resueltas.',
    tone: 'error',
    requiresAlert: true,
  },
};

export function getAnswerVerificationPresentation(
  verdict: string | null | undefined,
): AnswerVerificationPresentation {
  const normalized = verdict?.trim().toLowerCase();
  if (!normalized) {
    return {
      key: 'unavailable',
      label: 'Verificación no disponible',
      description: 'El detalle de verificación aún no está disponible para este turno.',
      tone: 'neutral',
      requiresAlert: false,
    };
  }

  return VERIFICATION_PRESENTATIONS[normalized] ?? {
    key: 'unknown',
    label: 'Veredicto desconocido',
    description: `Atenex devolvió un estado de verificación no reconocido: ${verdict}.`,
    tone: 'warning',
    requiresAlert: false,
  };
}

export function assessAnswerTrust(
  verdict: string | null | undefined,
  groundingScore: number | null | undefined,
  citationsCount: number | null | undefined,
): AnswerTrustAlert | null {
  const presentation = getAnswerVerificationPresentation(verdict);

  if (presentation.key === 'unverified') {
    return {
      title: presentation.label,
      message: 'No la trates como una conclusión del corpus hasta revisar las afirmaciones y sus fuentes.',
      tone: 'error',
    };
  }
  if (presentation.key === 'conflicting') {
    return {
      title: presentation.label,
      message: 'Las citas no eliminan el conflicto: revisa las fuentes antes de elegir una interpretación.',
      tone: 'error',
    };
  }
  if (presentation.key === 'partially_verified') {
    return {
      title: presentation.label,
      message: 'Distingue las partes respaldadas de las que todavía requieren comprobación.',
      tone: 'warning',
    };
  }
  if (typeof groundingScore === 'number' && groundingScore < 0.6) {
    return {
      title: 'Fundamento limitado',
      message: 'La correspondencia entre la respuesta y la evidencia es baja; valida los puntos importantes.',
      tone: 'warning',
    };
  }
  if (citationsCount === 0) {
    return {
      title: 'Sin citas explícitas',
      message: 'No hay citas visibles que permitan comprobar esta respuesta en el corpus.',
      tone: 'warning',
    };
  }
  return null;
}

export function formatVerificationIssue(issue: string): string | null {
  const normalized = issue.trim().toLowerCase();
  if (!normalized || normalized === 'none') return null;

  const knownMessage = ISSUE_MESSAGES[normalized];
  if (knownMessage) return knownMessage;

  const readable = issue.trim().replace(/[_-]+/g, ' ').replace(/\s+/g, ' ');
  if (!readable) return null;
  const sentence = `${readable.charAt(0).toUpperCase()}${readable.slice(1)}`;
  return `El verificador señaló: ${/[.!?]$/.test(sentence) ? sentence : `${sentence}.`}`;
}

export function formatVerificationIssues(issues: readonly string[] | null | undefined): string[] {
  const formatted: string[] = [];
  const seen = new Set<string>();

  for (const issue of issues ?? []) {
    const message = formatVerificationIssue(issue);
    if (!message) continue;
    const key = message.toLocaleLowerCase('es');
    if (seen.has(key)) continue;
    seen.add(key);
    formatted.push(message);
  }

  return formatted;
}
