import { describe, expect, it } from 'vitest';
import { formatValue, splitCitations, splitMasked } from './format';

describe('splitMasked', () => {
  it('turns placeholders into PII segments', () => {
    expect(splitMasked('Aadhaar <AADHAAR>, call <PHONE>.')).toEqual([
      { kind: 'text', text: 'Aadhaar ' },
      { kind: 'pii', type: 'AADHAAR' },
      { kind: 'text', text: ', call ' },
      { kind: 'pii', type: 'PHONE' },
      { kind: 'text', text: '.' },
    ]);
  });

  it('leaves unknown angle-bracket text alone', () => {
    expect(splitMasked('a <b> c')).toEqual([{ kind: 'text', text: 'a <b> c' }]);
  });
});

describe('splitCitations', () => {
  it('finds [p.N] citations in Hindi and English answers', () => {
    expect(splitCitations('किराया ₹18,500 है [p.1] और जमा [p. 2]')).toEqual([
      { kind: 'text', text: 'किराया ₹18,500 है ' },
      { kind: 'cite', page: 1 },
      { kind: 'text', text: ' और जमा ' },
      { kind: 'cite', page: 2 },
    ]);
  });
});

describe('formatValue', () => {
  it('formats rupee amounts in Indian style', () => {
    expect(formatValue('monthly_rent_inr', '1850000', 'en')).toBe('₹18,50,000');
    expect(formatValue('khasra_number', '512/3', 'hi')).toBe('512/3');
    expect(formatValue('x', null, 'en')).toBe('—');
  });
});
