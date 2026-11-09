import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { Providers } from '../App';
import { LoginPage } from './LoginPage';
import { DocumentPage } from './DocumentPage';
import type { DocDetail } from '../lib/types';

const META = { provider: 'demo', model: 'rule-based (no AI)', demo_mode: true, ocr_enabled: false, voice_enabled: false, limits: { max_upload_mb: 10, max_pages: 30 } };

const DOC: DocDetail = {
  id: 'd1',
  filename: 'rent.pdf',
  status: 'ready',
  error: null,
  doc_type: 'rent_agreement',
  language: 'hi-IN',
  page_count: 2,
  pii_counts: { AADHAAR: 1, PHONE: 2 },
  text_source: 'demo_prepared',
  original_deleted: true,
  is_demo: true,
  created_at: '2026-11-10T00:00:00Z',
  updated_at: '2026-11-10T00:00:00Z',
  meta: { summary: 'A rent agreement.', language: 'mixed', classification_confidence: 'high', provider: 'demo', model: 'rule-based (no AI)', demo_mode: true },
  fields: [
    { name: 'monthly_rent_inr', label_en: 'Monthly rent (₹)', label_hi: 'मासिक किराया (₹)', value: '18500', page: 1, confidence: 'medium' },
    { name: 'lock_in_period', label_en: 'Lock-in period', label_hi: 'लॉक-इन अवधि', value: null, page: null, confidence: 'missing' },
  ],
};

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }));
}

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  localStorage.clear();
  fetchMock = vi.fn((url: string, init?: RequestInit) => {
    const path = new URL(url).pathname;
    if (path === '/api/meta') return json(META);
    if (path === '/api/auth/demo') return json({ token: 't', user: { id: 'u', name: 'Demo User', email: 'demo-1@kaagaz.demo', is_demo: true } });
    if (path === '/api/documents/d1') return json(DOC);
    if (path === '/api/documents/d1/history') return json({ items: [] });
    if (path === '/api/documents/d1/pages') return json({ pages: [{ page: 1, text: 'Rent ₹18,500. Aadhaar <AADHAAR>' }, { page: 2, text: 'Notice: two months.' }] });
    if (path === '/api/documents/d1/ask') {
      const q = JSON.parse(String(init?.body)).question as string;
      if (q.includes('cricket')) return json({ answer: 'यह जानकारी दस्तावेज़ में नहीं मिली / Not found in this document', language: 'en', citations: [], refused: true, sources: [] });
      return json({ answer: 'According to the document: two months [p.2]', language: 'en', citations: [2], refused: false, sources: [] });
    }
    return json({ error: { code: 'not_found', message: 'nope' } }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

const user = { id: 'u', name: 'Demo User', email: 'demo-1@kaagaz.demo', is_demo: true };

describe('LoginPage', () => {
  it('logs in with the demo button and shows the demo-mode banner', async () => {
    render(
      <Providers>
        <MemoryRouter>
          <LoginPage />
        </MemoryRouter>
      </Providers>,
    );
    expect(await screen.findByText(/Demo mode: results come from simple keyword rules/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Try the demo' }));
    await waitFor(() => expect(localStorage.getItem('kaagaz.token')).toBe('t'));
  });

  it('switches the UI to Hindi', async () => {
    render(
      <Providers>
        <MemoryRouter>
          <LoginPage />
        </MemoryRouter>
      </Providers>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'हिंदी' }));
    expect(screen.getByRole('button', { name: 'डेमो आज़माएँ' })).toBeInTheDocument();
  });
});

function renderDoc() {
  return render(
    <Providers initialUser={user}>
      <MemoryRouter initialEntries={['/documents/d1']}>
        <Routes>
          <Route path="/documents/:id" element={<DocumentPage />} />
        </Routes>
      </MemoryRouter>
    </Providers>,
  );
}

describe('DocumentPage', () => {
  it('shows extracted fields with page links, missing values and masking info', async () => {
    renderDoc();
    expect(await screen.findByText('₹18,500')).toBeInTheDocument();
    expect(screen.getByText('Not found')).toBeInTheDocument();
    expect(screen.getByText(/Original file deleted/)).toBeInTheDocument();
    expect(screen.getByText(/prepared in advance/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Page 1 →' }));
    expect(await screen.findByText('Page 1', { selector: 'h2' })).toBeInTheDocument();
    expect(screen.getByTitle('Aadhaar masked')).toBeInTheDocument();
  });

  it('asks a question and renders a clickable citation; refusals have no citation', async () => {
    renderDoc();
    await userEvent.click(await screen.findByRole('tab', { name: 'Ask' }));
    const box = screen.getByLabelText(/Ask about this document/);
    await userEvent.type(box, 'What is the notice period?{Enter}');
    expect(await screen.findByRole('button', { name: 'Page 2' })).toBeInTheDocument();
    await userEvent.type(box, 'Who won the cricket world cup?{Enter}');
    expect(await screen.findByText(/Not found in this document/)).toBeInTheDocument();
  });

  it('disables voice in demo mode with an explanation', async () => {
    renderDoc();
    await userEvent.click(await screen.findByRole('tab', { name: 'Ask' }));
    const mic = await screen.findByRole('button', { name: /Voice uses the Sarvam speech API/ });
    expect(mic).toBeDisabled();
  });
});
