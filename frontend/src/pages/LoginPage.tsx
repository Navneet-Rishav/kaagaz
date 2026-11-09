import { useState, type FormEvent } from 'react';
import { useMutation } from '@tanstack/react-query';
import { api, ApiError, errorMessage } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useT } from '../lib/i18n';
import type { Session } from '../lib/types';
import { Button, Card } from '../components/ui';
import { DemoBanner, LangToggle, Logo } from '../components/Layout';

export function LoginPage() {
  const { signIn } = useAuth();
  const { t } = useT();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [form, setForm] = useState({ name: '', email: '', password: '' });

  const demo = useMutation({ mutationFn: () => api<Session>('/api/auth/demo', { method: 'POST', auth: false }), onSuccess: signIn });
  const submit = useMutation({
    mutationFn: () =>
      api<Session>(`/api/auth/${mode}`, {
        auth: false,
        body: mode === 'login' ? { email: form.email, password: form.password } : form,
      }),
    onSuccess: signIn,
  });

  const fieldErrors: Record<string, string> = {};
  if (submit.error instanceof ApiError && Array.isArray(submit.error.details)) {
    for (const d of submit.error.details as { field: string; message: string }[]) fieldErrors[d.field] = d.message;
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    submit.mutate();
  };
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  return (
    <div className="min-h-screen">
      <DemoBanner />
      <div className="mx-auto flex max-w-md flex-col gap-6 px-4 py-10">
        <div className="flex items-center justify-between">
          <Logo />
          <LangToggle />
        </div>
        <p className="text-stone-600">{t.tagline}</p>

        <Card>
          <Button className="w-full" onClick={() => demo.mutate()} loading={demo.isPending}>
            {t.tryDemo}
          </Button>
          <p className="mt-2 text-center text-xs text-stone-500">{t.tryDemoHint}</p>
          {demo.isPending && <p className="mt-2 text-center text-xs text-stone-500">{t.wakeUp}</p>}
          {demo.error && <p className="mt-2 text-sm text-rose-700" role="alert">{errorMessage(demo.error)}</p>}
        </Card>

        <div className="flex items-center gap-3 text-xs text-stone-400" aria-hidden="true">
          <span className="h-px flex-1 bg-stone-200" /> {t.or} <span className="h-px flex-1 bg-stone-200" />
        </div>

        <Card>
          <form onSubmit={onSubmit} className="space-y-3" noValidate>
            <h1 className="text-lg font-semibold">{mode === 'login' ? t.login : t.register}</h1>
            {mode === 'register' && (
              <Input id="name" label={t.name} value={form.name} onChange={set('name')} error={fieldErrors.name} autoComplete="name" />
            )}
            <Input id="email" label={t.email} type="email" value={form.email} onChange={set('email')} error={fieldErrors.email} autoComplete="email" />
            <Input
              id="password"
              label={t.password}
              type="password"
              value={form.password}
              onChange={set('password')}
              error={fieldErrors.password}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            />
            {submit.error && !Object.keys(fieldErrors).length && (
              <p className="text-sm text-rose-700" role="alert">
                {errorMessage(submit.error)}
              </p>
            )}
            <Button type="submit" variant="secondary" className="w-full" loading={submit.isPending}>
              {mode === 'login' ? t.login : t.register}
            </Button>
            <button
              type="button"
              className="w-full text-center text-sm text-amber-800 hover:underline"
              onClick={() => {
                setMode(mode === 'login' ? 'register' : 'login');
                submit.reset();
              }}
            >
              {mode === 'login' ? t.noAccount : t.haveAccount}
            </button>
          </form>
        </Card>
      </div>
    </div>
  );
}

function Input({ id, label, error, ...rest }: React.InputHTMLAttributes<HTMLInputElement> & { id: string; label: string; error?: string }) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-stone-700">
        {label}
      </label>
      <input
        id={id}
        name={id}
        aria-invalid={!!error}
        aria-describedby={error ? `${id}-error` : undefined}
        className="mt-1 block w-full rounded-lg border border-stone-300 px-3 py-2 text-sm focus:border-amber-600 focus:ring-0"
        {...rest}
      />
      {error && (
        <p id={`${id}-error`} className="mt-1 text-xs text-rose-700">
          {error}
        </p>
      )}
    </div>
  );
}
