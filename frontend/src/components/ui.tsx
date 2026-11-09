import type { ButtonHTMLAttributes, ReactNode } from 'react';
import type { DocStatus } from '../lib/types';
import { IN_PROGRESS } from '../lib/types';
import { useT } from '../lib/i18n';
import { PII_LABEL } from '../lib/format';
import { cx } from '../lib/cx';

export function Button({
  variant = 'primary',
  loading,
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'ghost' | 'danger'; loading?: boolean }) {
  const styles = {
    primary: 'bg-amber-700 text-white hover:bg-amber-800 disabled:bg-amber-700/50',
    secondary: 'border border-stone-300 bg-white text-stone-800 hover:bg-stone-50 disabled:opacity-50',
    ghost: 'text-stone-700 hover:bg-stone-100 disabled:opacity-50',
    danger: 'border border-rose-200 bg-white text-rose-700 hover:bg-rose-50 disabled:opacity-50',
  }[variant];
  return (
    <button
      className={cx('inline-flex min-h-10 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed', styles, className)}
      disabled={rest.disabled || loading}
      {...rest}
    >
      {loading && <Spinner small />}
      {children}
    </button>
  );
}

export function Spinner({ small, label }: { small?: boolean; label?: string }) {
  return (
    <span role="status" className="inline-flex items-center gap-2 text-sm text-stone-500">
      <span className={cx('animate-spin rounded-full border-2 border-current border-t-transparent', small ? 'h-3.5 w-3.5' : 'h-5 w-5')} aria-hidden="true" />
      {label ? <span>{label}</span> : <span className="sr-only">Loading</span>}
    </span>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx('rounded-xl border border-stone-200 bg-white p-4 shadow-sm sm:p-5', className)}>{children}</div>;
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const { t } = useT();
  return (
    <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
      <p>{message}</p>
      {onRetry && (
        <Button variant="secondary" className="mt-3" onClick={onRetry}>
          {t.retry}
        </Button>
      )}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-stone-300 bg-white px-6 py-10 text-center">
      <p className="font-medium text-stone-800">{title}</p>
      {children && <div className="mt-1 text-sm text-stone-500">{children}</div>}
    </div>
  );
}

export function StatusBadge({ status }: { status: DocStatus }) {
  const { t } = useT();
  const style = status === 'ready' ? 'bg-emerald-100 text-emerald-800' : status === 'failed' ? 'bg-rose-100 text-rose-800' : 'bg-sky-100 text-sky-800';
  return (
    <span className={cx('inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap', style)}>
      {IN_PROGRESS.includes(status) && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" aria-hidden="true" />}
      {t.status[status]}
    </span>
  );
}

const PII_STYLE: Record<string, string> = {
  AADHAAR: 'bg-violet-100 text-violet-800 ring-violet-200',
  PAN: 'bg-fuchsia-100 text-fuchsia-800 ring-fuchsia-200',
  PHONE: 'bg-sky-100 text-sky-800 ring-sky-200',
  EMAIL: 'bg-teal-100 text-teal-800 ring-teal-200',
  BANK_ACCOUNT: 'bg-orange-100 text-orange-800 ring-orange-200',
  IFSC: 'bg-lime-100 text-lime-800 ring-lime-200',
};

export function PiiChip({ type, count }: { type: string; count?: number }) {
  const { lang, t } = useT();
  const label = PII_LABEL[type]?.[lang] ?? type;
  return (
    <span
      className={cx('mx-0.5 inline-flex items-center gap-1 rounded-md px-1.5 py-px align-baseline text-xs font-medium ring-1', PII_STYLE[type] ?? 'bg-stone-100 text-stone-700 ring-stone-200')}
      title={`${label} ${t.maskedValue}`}
    >
      <svg viewBox="0 0 16 16" className="h-3 w-3" aria-hidden="true">
        <path fill="currentColor" d="M4 7V5a4 4 0 1 1 8 0v2h.5A1.5 1.5 0 0 1 14 8.5v5a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 2 13.5v-5A1.5 1.5 0 0 1 3.5 7H4Zm1.5 0h5V5a2.5 2.5 0 0 0-5 0v2Z" />
      </svg>
      {label}
      {count !== undefined && <span className="opacity-70">× {count}</span>}
    </span>
  );
}
