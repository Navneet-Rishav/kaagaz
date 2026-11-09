import { useRef, useState, type DragEvent } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError, errorMessage } from '../lib/api';
import { useT } from '../lib/i18n';
import { IN_PROGRESS, type DocSummary } from '../lib/types';
import { Layout } from '../components/Layout';
import { useMeta } from '../lib/meta';
import { cx } from '../lib/cx';
import { Button, Card, EmptyState, ErrorState, PiiChip, Spinner, StatusBadge } from '../components/ui';

export function DocumentsPage() {
  const { t, lang } = useT();
  const qc = useQueryClient();
  const { data: meta } = useMeta();
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['documents'],
    queryFn: () => api<{ items: DocSummary[] }>('/api/documents'),
    // Poll while anything is still being processed.
    refetchInterval: (q) => (q.state.data?.items.some((d) => IN_PROGRESS.includes(d.status)) ? 2000 : false),
  });

  return (
    <Layout>
      <div className="space-y-6">
        <UploadCard maxMb={meta?.limits.max_upload_mb ?? 10} maxPages={meta?.limits.max_pages ?? 30} onUploaded={() => qc.invalidateQueries({ queryKey: ['documents'] })} />

        <section aria-labelledby="docs-title" className="space-y-3">
          <h1 id="docs-title" className="text-lg font-semibold">
            {t.documents}
          </h1>
          {isLoading ? (
            <div className="py-10 text-center">
              <Spinner label={t.loading} />
            </div>
          ) : error ? (
            <ErrorState message={errorMessage(error)} onRetry={() => refetch()} />
          ) : !data?.items.length ? (
            <EmptyState title={t.noDocs}>{t.noDocsHint}</EmptyState>
          ) : (
            <ul className="grid gap-3 sm:grid-cols-2">
              {data.items.map((d) => (
                <li key={d.id}>
                  <Link to={`/documents/${d.id}`} className="block h-full rounded-xl border border-stone-200 bg-white p-4 shadow-sm transition hover:border-amber-300 hover:shadow">
                    <div className="flex items-start justify-between gap-2">
                      <p className="min-w-0 font-medium break-words text-stone-900">{d.doc_type ? t.docType[d.doc_type] : d.filename}</p>
                      <StatusBadge status={d.status} />
                    </div>
                    <p className="mt-0.5 truncate text-xs text-stone-500" title={d.filename}>
                      {d.filename}
                      {d.page_count ? ` · ${d.page_count} ${t.pages}` : ''} · {new Date(d.created_at).toLocaleDateString(lang === 'hi' ? 'hi-IN' : 'en-IN')}
                    </p>
                    {d.status === 'failed' && d.error && <p className="mt-2 text-sm text-rose-700">{d.error}</p>}
                    {Object.keys(d.pii_counts).length > 0 && (
                      <p className="mt-2 flex flex-wrap items-center gap-1 text-xs text-stone-500">
                        {Object.entries(d.pii_counts).map(([k, n]) => (
                          <PiiChip key={k} type={k} count={n} />
                        ))}
                        <span>{t.masked}</span>
                      </p>
                    )}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </Layout>
  );
}

function UploadCard({ maxMb, maxPages, onUploaded }: { maxMb: number; maxPages: number; onUploaded: () => void }) {
  const { t } = useT();
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [language, setLanguage] = useState<'hi-IN' | 'en-IN'>('hi-IN');
  const [clientError, setClientError] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append('file', file);
      form.append('language', language);
      return api<DocSummary>('/api/documents', { form });
    },
    onSuccess: onUploaded,
  });

  const pick = (file: File | undefined) => {
    setClientError(null);
    upload.reset();
    if (!file) return;
    if (file.size > maxMb * 1024 * 1024) return setClientError(`Max ${maxMb} MB`);
    if (!/\.(pdf|png|jpe?g)$/i.test(file.name)) return setClientError('PDF, PNG, JPG');
    upload.mutate(file);
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    pick(e.dataTransfer.files[0]);
  };

  const dupId = upload.error instanceof ApiError && upload.error.code === 'duplicate' ? (upload.error.details as { document_id?: string })?.document_id : undefined;

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-semibold">{t.upload}</h2>
        <label className="flex items-center gap-2 text-sm text-stone-700">
          {t.docLanguage}
          <select value={language} onChange={(e) => setLanguage(e.target.value as 'hi-IN' | 'en-IN')} className="rounded-lg border border-stone-300 px-2 py-1 text-sm">
            <option value="hi-IN">{t.hindi}</option>
            <option value="en-IN">{t.english}</option>
          </select>
        </label>
      </div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        className={cx('mt-3 flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-8 text-center transition', drag ? 'border-amber-500 bg-amber-50' : 'border-stone-300')}
      >
        <p className="text-sm text-stone-600">{t.dropHere}</p>
        <p className="text-xs text-stone-400">
          ≤ {maxMb} MB · ≤ {maxPages} {t.pages}
        </p>
        <Button variant="secondary" onClick={() => input.current?.click()} loading={upload.isPending}>
          {upload.isPending ? t.uploading : t.upload}
        </Button>
        <input
          ref={input}
          type="file"
          accept="application/pdf,image/png,image/jpeg"
          className="sr-only"
          aria-label={t.upload}
          onChange={(e) => {
            pick(e.target.files?.[0]);
            e.target.value = '';
          }}
        />
      </div>
      {(clientError || upload.error) && (
        <p className="mt-2 text-sm text-rose-700" role="alert">
          {clientError ?? errorMessage(upload.error)}{' '}
          {dupId && (
            <Link className="underline" to={`/documents/${dupId}`}>
              →
            </Link>
          )}
        </p>
      )}
    </Card>
  );
}
