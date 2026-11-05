import type { CountrySummary, DossierSummary, EpVoteSummary, LifecycleStage } from '../../types/data';
import { isClose } from '../votes/labels';

/** Aggregate only the tracked records. These are descriptive counts, not causal estimates. */
export const STAGES: { id: LifecycleStage; label: string }[] = [
  { id: 'in_force', label: 'In force' },
  { id: 'no_longer_in_force', label: 'No longer in force' },
  { id: 'proposed', label: 'Proposal under examination' },
  { id: 'parliament_position', label: 'Parliament position' },
  { id: 'negotiations', label: 'Interinstitutional negotiations' },
  { id: 'provisional_agreement', label: 'Provisional agreement' },
  { id: 'adopted', label: 'Adopted, not yet published' },
  { id: 'published', label: 'Published, not yet in force' },
  { id: 'takes_effect_on_notification', label: 'Effect on notification' },
  { id: 'withdrawn', label: 'Withdrawn' },
  { id: 'rejected', label: 'Rejected by Parliament' },
  { id: 'lapsed', label: 'Lapsed' },
  { id: 'unknown', label: 'Not determinable' },
];

type File = Pick<DossierSummary, 'id' | 'stage' | 'started' | 'adopted'>;
type Vote = Pick<EpVoteSummary, 'kind' | 'outcome' | 'margin' | 'date' | 'has_ballots' | 'id' | 'display_title'>;
type Country = Pick<CountrySummary, 'code' | 'name' | 'council_positions' | 'open_infringements'>;

// A report Parliament adopted on a procedure (2023/0201R, 2023/0201M): a resolution, not a legislative file
// (PARLIAMENT_REPORT_RE in pipeline/build.py).
const REPORT = /^\d{4}-\d{4}[RM]$/;
// A part of a split procedure (2019/0001A and B): its parent stays listed as a file, with its parts' proposal date and
// the status "Split into separate procedures" (stage 'unknown'), but each part has its own procedure and outcome.
const PART = /^(\d{4}-\d{4})[A-Z]$/;

/**
 * Counted once per legislative procedure: the parent of a split procedure is counted through its parts (counting it
 * too would add its proposal again and put it under "Not determinable"), and Parliament's reports on a procedure are
 * not legislative files. `total` is every file listed, as on /legislation; `counted` the files the charts count.
 */
export function legislativePatterns(files: File[]) {
  const ids = new Set(files.map((f) => f.id));
  const parents = new Set(
    files.flatMap((f) => {
      const m = PART.exec(f.id);
      return m && !REPORT.test(f.id) && ids.has(m[1]) ? [m[1]] : [];
    }),
  );
  const reports = files.filter((f) => REPORT.test(f.id)).length;
  const counted = files.filter((f) => !REPORT.test(f.id) && !parents.has(f.id));
  const stageCounts = new Map<LifecycleStage, number>();
  const years = new Map<number, { year: number; introduced: number; adopted: number }>();
  for (const file of counted) {
    stageCounts.set(file.stage, (stageCounts.get(file.stage) ?? 0) + 1);
    for (const [field, target] of [['started', 'introduced'], ['adopted', 'adopted']] as const) {
      const date = file[field];
      if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) continue;
      const year = Number(date.slice(0, 4));
      if (year < 2014 || year > 2100) continue;
      const entry = years.get(year) ?? { year, introduced: 0, adopted: 0 };
      entry[target]++;
      years.set(year, entry);
    }
  }
  const timeline = [...years.values()].sort((a, b) => a.year - b.year).slice(-8);
  const stages = STAGES.map((stage) => ({ ...stage, count: stageCounts.get(stage.id) ?? 0 }))
    .filter((stage) => stage.count > 0)
    .sort((a, b) => b.count - a.count);
  return {
    total: files.length,
    counted: counted.length,
    splitParents: parents.size,
    reports,
    stages,
    timeline,
    maxTimeline: Math.max(1, ...timeline.flatMap((r) => [r.introduced, r.adopted])),
  };
}

/** What the stage bars leave out of the files listed, and why; empty when they count every file. */
export function notCountedText(x: Pick<ReturnType<typeof legislativePatterns>, 'total' | 'counted' | 'splitParents' | 'reports'>): string {
  if (x.counted >= x.total) return '';
  const n = (k: number) => k.toLocaleString('en-GB');
  const why = [
    x.splitParents > 0 &&
      `${n(x.splitParents)} ${x.splitParents === 1 ? 'proposal was' : 'proposals were'} split into separate procedures, which are counted instead`,
    x.reports > 0 &&
      `${n(x.reports)} ${x.reports === 1 ? 'is a report Parliament adopted on a procedure, not a legislative file' : 'are reports Parliament adopted on a procedure, not legislative files'}`,
  ].filter(Boolean);
  return `The bars count ${n(x.counted)} of the ${n(x.total)} files listed: ${why.join('; ')}.`;
}

/** The /votes list of the votes `parliamentPatterns` counts as close: final votes only, as the home page's list. */
export const CLOSE_FINAL_VOTES = '/votes?kind=final&close=1';

export function parliamentPatterns(votes: Vote[]) {
  // 'Final' is a type of Parliament vote; it is not identical to the adoption of EU law.
  const final = votes.filter((v) => v.kind === 'final');
  const withOutcome = final.filter((v) => v.outcome === 'adopted' || v.outcome === 'rejected');
  const withMargin = withOutcome.filter((v) => v.margin != null);
  const close = withMargin.filter((v) => isClose(v));
  const byYear = new Map<string, number>();
  for (const vote of final) {
    if (!/^\d{4}-/.test(vote.date)) continue;
    const year = vote.date.slice(0, 4);
    byYear.set(year, (byYear.get(year) ?? 0) + 1);
  }
  return {
    total: votes.length,
    final: final.length,
    withOutcome: withOutcome.length,
    withMargin: withMargin.length,
    close: close.length,
    withBallots: votes.filter((v) => v.has_ballots).length,
    years: [...byYear].sort(([a], [b]) => a.localeCompare(b)).map(([year, count]) => ({ year, count })),
  };
}

export function councilPatterns(countries: Country[]) {
  const rows = countries.map((country) => {
    const p = country.council_positions;
    const recorded = p.for + p.against + p.abstain;
    return {
      code: country.code,
      name: country.name,
      recorded,
      inFavour: p.for,
      against: p.against,
      abstained: p.abstain,
      notParticipating: p.not_participating,
      dissent: p.against + p.abstain,
      share: recorded > 0 ? (p.against + p.abstain) / recorded : null,
      openInfringements: country.open_infringements,
    };
  });
  // alphabetical, not by count: the site does not rank Member States (About, docs/PRODUCT.md)
  return rows.filter((r) => r.recorded > 0).sort((a, b) => a.name.localeCompare(b.name, 'en'));
}
