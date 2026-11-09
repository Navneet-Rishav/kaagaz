import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../lib/auth';
import { useT } from '../lib/i18n';
import { useMeta } from '../lib/meta';
import { cx } from '../lib/cx';

export function LangToggle() {
  const { lang, setLang } = useT();
  return (
    <div role="group" aria-label="Language / भाषा" className="inline-flex rounded-lg border border-stone-300 bg-white p-0.5 text-sm">
      {(['en', 'hi'] as const).map((l) => (
        <button
          key={l}
          type="button"
          aria-pressed={lang === l}
          onClick={() => setLang(l)}
          className={cx('rounded-md px-2.5 py-1', lang === l ? 'bg-amber-700 text-white' : 'text-stone-700 hover:bg-stone-100')}
        >
          {l === 'en' ? 'English' : 'हिंदी'}
        </button>
      ))}
    </div>
  );
}

export function Logo() {
  return (
    <span className="inline-flex items-center gap-2 font-semibold text-stone-900">
      <img src="/favicon.svg" alt="" className="h-7 w-7" />
      Kaagaz <span className="font-normal text-stone-500">कागज़</span>
    </span>
  );
}

export function DemoBanner() {
  const { t } = useT();
  const { data } = useMeta();
  if (!data?.demo_mode) return null;
  return (
    <div className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-center text-xs text-amber-900 sm:text-sm" role="note">
      {t.demoBanner}
    </div>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const { user, signOut } = useAuth();
  const { t } = useT();
  return (
    <div className="min-h-screen">
      <DemoBanner />
      <header className="border-b border-stone-200 bg-white">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <Link to="/" aria-label="Kaagaz home">
            <Logo />
          </Link>
          <div className="flex items-center gap-2">
            <LangToggle />
            {user && (
              <button type="button" onClick={signOut} className="rounded-lg px-3 py-1.5 text-sm text-stone-700 hover:bg-stone-100">
                {t.logout}
              </button>
            )}
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
    </div>
  );
}
