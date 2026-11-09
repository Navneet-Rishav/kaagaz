import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, apiBlob, ApiError, errorMessage } from '../lib/api';
import { useT } from '../lib/i18n';
import { formatValue, splitCitations, splitMasked } from '../lib/format';
import { IN_PROGRESS, type DocDetail, type DocType, type QaItem } from '../lib/types';
import { Layout } from '../components/Layout';
import { useMeta } from '../lib/meta';
import { cx } from '../lib/cx';
import { Button, Card, EmptyState, ErrorState, PiiChip, Spinner, StatusBadge } from '../components/ui';

type Tab = 'summary' | 'pages' | 'ask';

export function DocumentPage() {
  const { id } = useParams<{ id: string }>();
  const { t, lang } = useT();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>('summary');
  const [focusPage, setFocusPage] = useState<number | null>(null);

  const { data: doc, isLoading, error, refetch } = useQuery({
    queryKey: ['document', id],
    queryFn: () => api<DocDetail>(`/api/documents/${id}`),
    refetchInterval: (q) => (q.state.data && IN_PROGRESS.includes(q.state.data.status) ? 2000 : false),
  });
  const del = useMutation({
    mutationFn: () => api<void>(`/api/documents/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['documents'] });
      nav('/');
    },
  });

  const goToPage = (p: number) => {
    setFocusPage(p);
    setTab('pages');
  };

  if (isLoading)
    return (
      <Layout>
        <Spinner label={t.loading} />
      </Layout>
    );
  if (error || !doc)
    return (
      <Layout>
        <BackLink />
        <ErrorState message={error instanceof ApiError && error.status === 404 ? t.notFound : errorMessage(error)} onRetry={() => refetch()} />
      </Layout>
    );

  const tabs: { key: Tab; label: string }[] = [
    { key: 'summary', label: t.summary },
    { key: 'pages', label: t.pagesTab },
    { key: 'ask', label: t.ask },
  ];

  return (
    <Layout>
      <div className="space-y-4">
        <BackLink />
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold">{doc.doc_type ? t.docType[doc.doc_type] : doc.filename}</h1>
              <StatusBadge status={doc.status} />
            </div>
            <p className="mt-0.5 truncate text-sm text-stone-500">
              {doc.filename}
              {doc.page_count ? ` · ${doc.page_count} ${t.pages}` : ''}
            </p>
          </div>
          <Button variant="danger" onClick={() => window.confirm(t.confirmDelete) && del.mutate()} loading={del.isPending}>
            {t.deleteDoc}
          </Button>
        </header>

        {doc.status === 'failed' ? (
          <ErrorState message={doc.error ?? t.status.failed} />
        ) : doc.status !== 'ready' ? (
          <Card>
            <Spinner label={`${t.status[doc.status]}…`} />
            {doc.error && <p className="mt-2 text-sm text-stone-600">{doc.error}</p>}
          </Card>
        ) : (
          <>
            <div role="tablist" aria-label={doc.filename} className="flex gap-1 border-b border-stone-200">
              {tabs.map((x) => (
                <button
                  key={x.key}
                  role="tab"
                  id={`tab-${x.key}`}
                  aria-selected={tab === x.key}
                  aria-controls={`panel-${x.key}`}
                  onClick={() => setTab(x.key)}
                  className={cx('-mb-px border-b-2 px-4 py-2 text-sm font-medium', tab === x.key ? 'border-amber-700 text-amber-800' : 'border-transparent text-stone-600 hover:text-stone-900')}
                >
                  {x.label}
                </button>
              ))}
            </div>
            <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
              {tab === 'summary' && <SummaryPanel doc={doc} onPage={goToPage} lang={lang} />}
              {tab === 'pages' && <PagesPanel docId={doc.id} focusPage={focusPage} />}
              {tab === 'ask' && <AskPanel doc={doc} onPage={goToPage} />}
            </div>
          </>
        )}
      </div>
    </Layout>
  );
}

function BackLink() {
  const { t } = useT();
  return (
    <Link to="/" className="inline-block text-sm text-amber-800 hover:underline">
      ← {t.back}
    </Link>
  );
}

function SourceNote({ doc }: { doc: DocDetail }) {
  const { t } = useT();
  const source = doc.text_source === 'demo_prepared' ? t.preparedText : doc.text_source === 'ocr' ? t.ocrUsed : t.pdfText;
  return (
    <ul className="space-y-1 text-xs text-stone-500">
      <li>✓ {t.originalDeleted}</li>
      <li>✓ {source}</li>
      {doc.meta && (
        <li>
          ✓ {doc.meta.provider}/{doc.meta.model}
          {doc.meta.demo_mode && <span className="ml-1 rounded bg-amber-100 px-1.5 py-px font-medium text-amber-900">demo mode (rule-based)</span>}
        </li>
      )}
    </ul>
  );
}

const CONF_STYLE = {
  high: 'bg-emerald-50 text-emerald-800',
  medium: 'bg-sky-50 text-sky-800',
  low: 'bg-amber-50 text-amber-900',
  missing: 'bg-stone-100 text-stone-500',
};

function SummaryPanel({ doc, onPage, lang }: { doc: DocDetail; onPage: (p: number) => void; lang: 'en' | 'hi' }) {
  const { t } = useT();
  return (
    <div className="space-y-4 pt-4">
      {doc.meta?.summary && <p className="text-stone-700">{doc.meta.summary}</p>}
      {Object.keys(doc.pii_counts).length > 0 && (
        <div className="flex flex-wrap items-center gap-1 text-sm text-stone-600">
          {Object.entries(doc.pii_counts).map(([k, n]) => (
            <PiiChip key={k} type={k} count={n} />
          ))}
          <span className="text-xs">{t.piiLegend}</span>
        </div>
      )}
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {doc.fields.map((f) => (
          <li key={f.name}>
            <Card className="h-full">
              <p className="text-xs font-medium tracking-wide text-stone-500 uppercase">{lang === 'hi' ? f.label_hi : f.label_en}</p>
              <p className={cx('mt-1 break-words', f.value === null ? 'text-stone-400' : 'font-medium text-stone-900')}>
                {f.value === null ? t.missing : <MaskedText text={formatValue(f.name, f.value, lang)} />}
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                <span className={cx('rounded px-1.5 py-px', CONF_STYLE[f.confidence])}>{t.confidence[f.confidence]}</span>
                {f.page && (
                  <button type="button" onClick={() => onPage(f.page!)} className="text-amber-800 hover:underline">
                    {t.page} {f.page} →
                  </button>
                )}
              </div>
            </Card>
          </li>
        ))}
      </ul>
      <SourceNote doc={doc} />
    </div>
  );
}

function MaskedText({ text }: { text: string }) {
  return (
    <>
      {splitMasked(text).map((s, i) => (s.kind === 'text' ? <span key={i}>{s.text}</span> : <PiiChip key={i} type={s.type} />))}
    </>
  );
}

function PagesPanel({ docId, focusPage }: { docId: string; focusPage: number | null }) {
  const { t } = useT();
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['pages', docId],
    queryFn: () => api<{ pages: { page: number; text: string }[] }>(`/api/documents/${docId}/pages`),
  });
  useEffect(() => {
    if (focusPage && data) document.getElementById(`page-${focusPage}`)?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  }, [focusPage, data]);

  if (isLoading) return <Spinner label={t.loading} />;
  if (error) return <ErrorState message={errorMessage(error)} onRetry={() => refetch()} />;
  return (
    <div className="space-y-4 pt-4">
      {data!.pages.map((p) => (
        <section key={p.page} id={`page-${p.page}`} className={cx('scroll-mt-4 rounded-xl', focusPage === p.page && 'ring-2 ring-amber-400')}>
          <Card>
            <h2 className="mb-2 text-sm font-semibold text-stone-500">
              {t.page} {p.page}
            </h2>
            <p className="text-sm leading-relaxed break-words whitespace-pre-wrap text-stone-800">
              <MaskedText text={p.text} />
            </p>
          </Card>
        </section>
      ))}
    </div>
  );
}

const SUGGESTIONS: Record<DocType, { en: string[]; hi: string[] }> = {
  rent_agreement: { en: ['What is the notice period?', 'How much is the security deposit?'], hi: ['मासिक किराया कितना है?', 'लॉक-इन अवधि क्या है?'] },
  electricity_bill: { en: ['What is the amount due?', 'When is the due date?'], hi: ['कितने यूनिट खर्च हुए?', 'देय राशि कितनी है?'] },
  bank_statement: { en: ['What is the closing balance?'], hi: ['अंतिम शेष कितना है?'] },
  property_record: { en: ['What is the khasra number?', 'What is the area of the land?'], hi: ['खातेदार का नाम क्या है?', 'क्षेत्रफल कितना है?'] },
  other: { en: ['What is this document about?'], hi: ['यह दस्तावेज़ किस बारे में है?'] },
};

function AskPanel({ doc, onPage }: { doc: DocDetail; onPage: (p: number) => void }) {
  const { t, lang } = useT();
  const { data: meta } = useMeta();
  const [question, setQuestion] = useState('');
  const [items, setItems] = useState<QaItem[]>([]);
  const history = useQuery({
    queryKey: ['history', doc.id],
    queryFn: () => api<{ items: QaItem[] }>(`/api/documents/${doc.id}/history`),
  });
  const ask = useMutation({
    mutationFn: (q: string) => api<QaItem>(`/api/documents/${doc.id}/ask`, { body: { question: q } }),
    onSuccess: (r, q) => setItems((xs) => [...xs, { ...r, question: q }]),
  });

  const all = [...(history.data?.items ?? []), ...items];
  const send = (q: string) => {
    const trimmed = q.trim();
    if (trimmed.length < 2 || ask.isPending) return;
    setQuestion('');
    ask.mutate(trimmed);
  };
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    send(question);
  };
  const suggestions = doc.doc_type ? [...SUGGESTIONS[doc.doc_type][lang], ...SUGGESTIONS[doc.doc_type][lang === 'hi' ? 'en' : 'hi']].slice(0, 3) : [];

  return (
    <div className="space-y-4 pt-4">
      {history.isLoading ? (
        <Spinner label={t.loading} />
      ) : all.length === 0 ? (
        <EmptyState title={t.suggestions}>
          <div className="mt-3 flex flex-wrap justify-center gap-2">
            {suggestions.map((s) => (
              <button key={s} type="button" onClick={() => send(s)} className="rounded-full border border-stone-300 bg-white px-3 py-1 text-sm text-stone-700 hover:bg-stone-50">
                {s}
              </button>
            ))}
          </div>
        </EmptyState>
      ) : (
        <ol className="space-y-4" aria-label={t.questionsHistory}>
          {all.map((qa, i) => (
            <li key={qa.id ?? `new-${i}`} className="space-y-2">
              <p className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-sm bg-amber-700 px-3 py-2 text-sm text-white" lang={qa.language}>
                {qa.question}
              </p>
              <AnswerBubble qa={qa} onPage={onPage} voiceEnabled={!!meta?.voice_enabled} />
            </li>
          ))}
        </ol>
      )}
      {ask.isPending && <Spinner label={t.thinking} />}
      {ask.error && <ErrorState message={errorMessage(ask.error)} />}

      <form onSubmit={onSubmit} className="flex items-end gap-2">
        <label htmlFor="question" className="sr-only">
          {t.askPlaceholder}
        </label>
        <textarea
          id="question"
          rows={2}
          maxLength={500}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              send(question);
            }
          }}
          placeholder={t.askPlaceholder}
          className="min-w-0 flex-1 resize-none rounded-lg border border-stone-300 px-3 py-2 text-sm focus:border-amber-600 focus:ring-0"
        />
        <MicButton enabled={!!meta?.voice_enabled} onText={(text) => setQuestion(text)} />
        <Button type="submit" loading={ask.isPending} disabled={question.trim().length < 2}>
          {t.askButton}
        </Button>
      </form>
    </div>
  );
}

function AnswerBubble({ qa, onPage, voiceEnabled }: { qa: QaItem; onPage: (p: number) => void; voiceEnabled: boolean }) {
  const { t } = useT();
  return (
    <div className={cx('max-w-[90%] rounded-2xl rounded-bl-sm border px-3 py-2 text-sm', qa.refused ? 'border-stone-200 bg-stone-100 text-stone-600' : 'border-stone-200 bg-white text-stone-900')}>
      <p lang={qa.language}>
        {splitCitations(qa.answer).map((part, i) =>
          part.kind === 'text' ? (
            <span key={i}>{part.text}</span>
          ) : (
            <button key={i} type="button" onClick={() => onPage(part.page)} className="mx-0.5 rounded bg-amber-100 px-1 text-xs font-medium text-amber-900 hover:bg-amber-200" aria-label={`${t.page} ${part.page}`}>
              p.{part.page}
            </button>
          ),
        )}
      </p>
      {!qa.refused && <SpeakButton text={qa.answer.replace(/\[\s*p\.?\s*\d+\s*\]/gi, '')} language={qa.language === 'hi' ? 'hi-IN' : 'en-IN'} enabled={voiceEnabled} />}
    </div>
  );
}

function SpeakButton({ text, language, enabled }: { text: string; language: string; enabled: boolean }) {
  const { t } = useT();
  const speak = useMutation({
    mutationFn: () => apiBlob('/api/voice/speak', { body: { text, language } }),
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.onended = () => URL.revokeObjectURL(url);
      void audio.play();
    },
  });
  return (
    <div className="mt-1">
      <button
        type="button"
        disabled={!enabled || speak.isPending}
        title={enabled ? t.speak : t.voiceOff}
        onClick={() => speak.mutate()}
        className="inline-flex items-center gap-1 text-xs text-stone-500 hover:text-stone-800 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <span aria-hidden="true">🔊</span> {t.speak}
      </button>
      {speak.error && <span className="ml-2 text-xs text-rose-700">{errorMessage(speak.error)}</span>}
    </div>
  );
}

function MicButton({ enabled, onText }: { enabled: boolean; onText: (text: string) => void }) {
  const { t } = useT();
  const [recording, setRecording] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null);
  const transcribe = useMutation({
    mutationFn: (blob: Blob) => {
      const form = new FormData();
      form.append('audio', blob, 'question.webm');
      return api<{ text: string }>('/api/voice/transcribe', { form });
    },
    onSuccess: (r) => onText(r.text),
  });

  const toggle = async () => {
    if (recording) {
      recorder.current?.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      rec.ondataavailable = (e) => chunks.push(e.data);
      rec.onstop = () => {
        stream.getTracks().forEach((tr) => tr.stop());
        setRecording(false);
        transcribe.mutate(new Blob(chunks, { type: rec.mimeType || 'audio/webm' }));
      };
      recorder.current = rec;
      rec.start();
      setRecording(true);
      setTimeout(() => rec.state === 'recording' && rec.stop(), 30_000);
    } catch {
      setRecording(false);
    }
  };

  const label = !enabled ? t.voiceOff : recording ? t.stopRecording : t.record;
  return (
    <div className="flex flex-col items-center">
      <button
        type="button"
        onClick={toggle}
        disabled={!enabled || transcribe.isPending}
        title={label}
        aria-label={label}
        aria-pressed={recording}
        className={cx(
          'flex h-10 w-10 items-center justify-center rounded-full border text-lg disabled:cursor-not-allowed disabled:opacity-40',
          recording ? 'animate-pulse border-rose-400 bg-rose-50' : 'border-stone-300 bg-white hover:bg-stone-50',
        )}
      >
        {transcribe.isPending ? <Spinner small /> : <span aria-hidden="true">🎙️</span>}
      </button>
    </div>
  );
}
