/**
 * Shared UI primitives. Keep these small and generic; feature-specific components live in src/features/<area>/.
 */
import { useId, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { Basis, LifecycleStage, SourceRef } from '../types/data';
import { GLOSSARY } from '../content/glossary';
import { formatNumber, safeUrl } from '../lib/format';

// ------------------------------------------------------------------ page scaffolding

export function PageHeader(props: { eyebrow?: ReactNode; title: ReactNode; lead?: ReactNode; children?: ReactNode }) {
  return (
    <header className="page-header">
      {props.eyebrow && <div className="eyebrow">{props.eyebrow}</div>}
      <h1>{props.title}</h1>
      {props.lead && <p className="lead">{props.lead}</p>}
      {props.children}
    </header>
  );
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="state state--loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      {label}
    </div>
  );
}

export function ErrorState({ error, title = 'Something went wrong' }: { error?: Error; title?: string }) {
  return (
    <div className="state state--error" role="alert">
      <strong>{title}</strong>
      {error && <p className="meta">{error.message}</p>}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state state--empty">
      <strong>{title}</strong>
      {children && <div className="meta">{children}</div>}
    </div>
  );
}

export function NotFound({ what = 'page' }: { what?: string }) {
  return (
    <div className="container page">
      <PageHeader title={`We couldn't find this ${what}`} lead="It may not be in our dataset yet, or the link may be wrong." />
      <p>
        <Link to="/legislation">Browse legislation</Link> · <Link to="/">Go to the homepage</Link>
      </p>
    </div>
  );
}

// ------------------------------------------------------------------ status

const STAGE_TONE: Record<LifecycleStage, string> = {
  proposed: 'progress',
  parliament_position: 'progress',
  negotiations: 'progress',
  provisional_agreement: 'agreement',
  adopted: 'done',
  published: 'done',
  in_force: 'done',
  withdrawn: 'inactive',
  lapsed: 'inactive',
  rejected: 'critical',
  unknown: 'inactive',
};

const STAGE_ICON: Record<string, string> = {
  progress: '◔',
  agreement: '◑',
  done: '●',
  inactive: '○',
  critical: '✕',
  alert: '!',
};

/** Lifecycle status pill: text label + icon; color is never the only signal. */
export function StatusBadge({ stage, label, blocked }: { stage: LifecycleStage; label: string; blocked?: boolean }) {
  const tone = blocked ? 'alert' : STAGE_TONE[stage];
  return (
    <span className={`badge badge--${tone}`}>
      <span aria-hidden="true" className="badge__icon">
        {STAGE_ICON[tone]}
      </span>
      {label}
    </span>
  );
}

export function Tag({ children }: { children: ReactNode }) {
  return <span className="tag">{children}</span>;
}

/** Marks statements that we derived (vs. recorded by an official source). */
export function BasisNote({ basis }: { basis: Basis }) {
  if (basis === 'source') return null;
  return (
    <span className="basis" title={basis === 'derived' ? 'Calculated by us from recorded events' : 'Not determinable from available records'}>
      {basis === 'derived' ? 'Derived from recorded events' : 'Not determinable'}
    </span>
  );
}

// ------------------------------------------------------------------ sources

const INSTITUTION_LABEL: Record<string, string> = {
  EP: 'European Parliament',
  Council: 'Council of the EU',
  'European Council': 'European Council',
  Commission: 'European Commission',
  'EUR-Lex': 'EUR-Lex',
  OEIL: 'Legislative Observatory',
  LegislativeTrain: 'Legislative Train Schedule',
  CJEU: 'Court of Justice',
};

export function institutionLabel(i: string): string {
  return INSTITUTION_LABEL[i] ?? i;
}

/** External official link. Opens in a new tab, never sends a referrer. */
export function ExtLink({ href, children, className }: { href: string | null | undefined; children: ReactNode; className?: string }) {
  const url = safeUrl(href);
  if (!url) return <>{children}</>;
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" className={className}>
      {children}
      <span className="ext" aria-hidden="true">
        ↗
      </span>
      <span className="visually-hidden"> (opens official website in a new tab)</span>
    </a>
  );
}

export function SourceLink({ source, prefix = 'Source:' }: { source: SourceRef | null | undefined; prefix?: string }) {
  if (!source) return null;
  return (
    <span className="source">
      {prefix} <ExtLink href={source.url}>{source.label || institutionLabel(source.institution)}</ExtLink>
    </span>
  );
}

// ------------------------------------------------------------------ glossary term

/** Inline explanation of an EU term. Click/tap to reveal; works with keyboard and screen readers. */
export function Term({ id, children }: { id: keyof typeof GLOSSARY | string; children?: ReactNode }) {
  const entry = GLOSSARY[id];
  const [open, setOpen] = useState(false);
  const tipId = useId();
  if (!entry) return <>{children}</>;
  return (
    <span className="term">
      <button
        type="button"
        className="term__btn"
        aria-expanded={open}
        aria-controls={tipId}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}
      >
        {children ?? entry.term}
      </button>
      {open && (
        <span id={tipId} role="note" className="term__tip">
          <strong>{entry.term}.</strong> {entry.short}{' '}
          {entry.href && <Link to={entry.href}>Learn more</Link>}
        </span>
      )}
    </span>
  );
}

// ------------------------------------------------------------------ disclosure

export function Disclosure({ summary, children, defaultOpen }: { summary: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  return (
    <details className="disclosure" open={defaultOpen}>
      <summary>{summary}</summary>
      <div className="disclosure__body">{children}</div>
    </details>
  );
}

// ------------------------------------------------------------------ vote bar

/**
 * Proportional for/abstain/against bar with readable numbers. Order: for | abstain | against.
 * Always shows the numbers as text (color is not the only encoding).
 */
export function VoteBar({
  forCount,
  against,
  abstain,
  compact,
  label,
}: {
  forCount: number | null;
  against: number | null;
  abstain: number | null;
  compact?: boolean;
  label?: string;
}) {
  const f = forCount ?? 0;
  const a = against ?? 0;
  const x = abstain ?? 0;
  const total = f + a + x;
  if (forCount == null && against == null) return <span className="meta">Vote counts not recorded</span>;
  const w = (n: number) => (total ? `${(n / total) * 100}%` : '0');
  const desc = `${label ? label + ': ' : ''}${formatNumber(f)} for, ${formatNumber(x)} abstentions, ${formatNumber(a)} against`;
  return (
    <div className={`votebar${compact ? ' votebar--compact' : ''}`}>
      <div className="votebar__track" role="img" aria-label={desc}>
        {f > 0 && <span className="votebar__seg votebar__seg--for" style={{ width: w(f) }} />}
        {x > 0 && <span className="votebar__seg votebar__seg--abstain" style={{ width: w(x) }} />}
        {a > 0 && <span className="votebar__seg votebar__seg--against" style={{ width: w(a) }} />}
      </div>
      <div className="votebar__legend" aria-hidden="true">
        <span>
          <i className="dot dot--for" />
          <b>{formatNumber(f)}</b> for
        </span>
        <span>
          <i className="dot dot--abstain" />
          <b>{formatNumber(x)}</b> abstained
        </span>
        <span>
          <i className="dot dot--against" />
          <b>{formatNumber(a)}</b> against
        </span>
      </div>
    </div>
  );
}
