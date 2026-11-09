/** Splits masked page text into plain text and PII placeholders such as <AADHAAR>, so the UI can show chips. */
export type Segment = { kind: 'text'; text: string } | { kind: 'pii'; type: string };

const PLACEHOLDER = /<(AADHAAR|PAN|PHONE|IFSC|EMAIL|BANK_ACCOUNT)>/g;

export function splitMasked(text: string): Segment[] {
  const out: Segment[] = [];
  let last = 0;
  for (const m of text.matchAll(PLACEHOLDER)) {
    if (m.index! > last) out.push({ kind: 'text', text: text.slice(last, m.index) });
    out.push({ kind: 'pii', type: m[1] });
    last = m.index! + m[0].length;
  }
  if (last < text.length) out.push({ kind: 'text', text: text.slice(last) });
  return out;
}

/** Splits an answer into text and [p.N] citations, so citations can be rendered as links to the page. */
export type AnswerPart = { kind: 'text'; text: string } | { kind: 'cite'; page: number };

export function splitCitations(answer: string): AnswerPart[] {
  const out: AnswerPart[] = [];
  let last = 0;
  for (const m of answer.matchAll(/\[\s*p\.?\s*(\d+)\s*\]/gi)) {
    if (m.index! > last) out.push({ kind: 'text', text: answer.slice(last, m.index) });
    out.push({ kind: 'cite', page: Number(m[1]) });
    last = m.index! + m[0].length;
  }
  if (last < answer.length) out.push({ kind: 'text', text: answer.slice(last) });
  return out;
}

export const PII_LABEL: Record<string, { en: string; hi: string }> = {
  AADHAAR: { en: 'Aadhaar', hi: 'आधार' },
  PAN: { en: 'PAN', hi: 'पैन' },
  PHONE: { en: 'Phone', hi: 'फ़ोन' },
  IFSC: { en: 'IFSC', hi: 'IFSC' },
  EMAIL: { en: 'Email', hi: 'ईमेल' },
  BANK_ACCOUNT: { en: 'Bank a/c', hi: 'बैंक खाता' },
};

export function formatValue(name: string, value: string | number | null, lang: 'en' | 'hi'): string {
  if (value === null || value === '') return '—';
  if (name.endsWith('_inr')) {
    const n = Number(String(value).replace(/,/g, ''));
    if (!Number.isNaN(n)) return `₹${n.toLocaleString(lang === 'hi' ? 'hi-IN' : 'en-IN')}`;
  }
  return String(value);
}
