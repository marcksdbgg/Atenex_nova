export function normalizeAssistantText(text: string, language: string): string {
  const normalized = text.trim();
  if (!normalized) return normalized;

  const cleaned = normalized
    .replace(/^\*{3,}\s*/gm, '')
    .replace(/^#{1,6}\s*/gm, '')
    .replace(/\r\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n');

  if (language.startsWith('es')) {
    if (/^the evidence supports\s*:/i.test(cleaned)) {
      return cleaned.replace(/^the evidence supports\s*:/i, 'Evidencia principal:').replace(/;\s*/g, ';\n');
    }
    if (/^i could not find grounded evidence for this query\.?$/i.test(cleaned)) {
      return 'No encontre evidencia suficiente para responder con fundamento.';
    }
    if (/^i could not produce a grounded answer\.?$/i.test(cleaned)) {
      return 'No pude producir una respuesta fundamentada con la evidencia disponible.';
    }
  }

  return cleaned.replace(/;\s*/g, ';\n');
}

export function summarizeAssistantText(text: string, language: string, maxLength = 260): string {
  const normalized = normalizeAssistantText(text, language).replace(/\s+/g, ' ').trim();
  if (!normalized || normalized.length <= maxLength) {
    return normalized;
  }

  const sentences = normalized.match(/[^.!?…]+[.!?…]+/g);
  if (sentences && sentences.length > 0) {
    const summary = sentences.slice(0, 2).join(' ').trim();
    if (summary.length >= 120) {
      return summary.length > maxLength ? `${summary.slice(0, maxLength - 1).trimEnd()}…` : summary;
    }
  }

  const cutoff = normalized.lastIndexOf('. ', maxLength);
  const fallback = cutoff > 120 ? normalized.slice(0, cutoff + 1) : normalized.slice(0, maxLength);
  return `${fallback.trimEnd()}…`;
}
