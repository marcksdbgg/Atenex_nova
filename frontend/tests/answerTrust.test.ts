import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  assessAnswerTrust,
  formatVerificationIssues,
  getAnswerVerificationPresentation,
} from '../src/components/answerTrust.ts';

describe('answer trust presentation', () => {
  it('keeps unverified and conflicting answers in an error state even with strong metrics', () => {
    assert.equal(assessAnswerTrust('unverified', 0.99, 12)?.tone, 'error');
    assert.equal(assessAnswerTrust('conflicting', 0.99, 12)?.tone, 'error');
  });

  it('provides semantic labels for every supported verdict and for missing detail', () => {
    assert.equal(getAnswerVerificationPresentation('verified').label, 'Verificada');
    assert.equal(getAnswerVerificationPresentation('partially_verified').tone, 'warning');
    assert.equal(getAnswerVerificationPresentation(undefined).key, 'unavailable');
    assert.equal(assessAnswerTrust(undefined, undefined, undefined), null);
  });

  it('turns verifier codes into deduplicated, understandable Spanish messages', () => {
    assert.deepEqual(
      formatVerificationIssues(['missing_citations', 'missing_citations', 'unresolved_contradiction', 'none']),
      [
        'No se generaron citas explícitas para respaldar la respuesta.',
        'La evidencia contiene una contradicción que la respuesta no resolvió.',
      ],
    );
  });
});
