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

type File = Pick<DossierSummary, 'stage' | 'started' | 'adopted'>;
type Vote = Pick<EpVoteSummary, 'kind' | 'outcome' | 'margin' | 'date' | 'has_ballots' | 'id' | 'display_title'>;
type Country = Pick<CountrySummary, 'code' | 'name' | 'council_positions' | 'open_infringements'>;

export function legislativePatterns(files: File[]) {
  const stageCounts = new Map<LifecycleStage, number>();
  const years = new Map<number, { year: number; introduced: number; adopted: number }>();
  for (const file of files) {
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
  return { total: files.length, stages, timeline, maxTimeline: Math.max(1, ...timeline.flatMap((r) => [r.introduced, r.adopted])) };
}

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
