# Sprint plan

## Workstreams and ownership

| Stream | Owner | Files |
| --- | --- | --- |
| Contracts, shell, integration | Lead | `pipeline/{http,snapshot,__main__}.py`, `pipeline/models/*`, `src/types/data.ts`, `src/App.tsx`, `src/components/*`, `src/styles/*`, `docs/*` |
| A1 EP people & organizations | Agent | `pipeline/sources/ep_people.py` |
| A2 EP procedures + lifecycle status | Agent | `pipeline/sources/ep_procedures.py`, `pipeline/analysis/status.py` |
| A3 EP plenary votes + margins | Agent | `pipeline/sources/ep_votes.py`, `pipeline/analysis/ep_margin.py` |
| B EUR-Lex legal acts | Agent | `pipeline/sources/eurlex.py` |
| C Council votes + QMV | Agent | `pipeline/sources/council.py`, `pipeline/analysis/council_qmv.py` |
| D National implementation | Agent | `pipeline/sources/implementation.py` |
| R Editorial curation + Legislative Train | Agent | `data/curated/*`, `pipeline/sources/legislative_train.py`, `docs/EDITORIAL.md` |
| E Build, search, activity | Agent | `pipeline/build.py`, `pipeline/validate.py`, `pipeline/analysis/{activity,feeds}.py`, `src/lib/search.ts` |
| F1 Frontend: discovery & legislation | Agent | Home, Legislation, Dossier, Search, Following |
| F2 Frontend: votes, people, countries, guide | Agent | Votes, Vote, People, MEP, Group, Party, Countries, Country, How the EU Works, About, Privacy |
| H QA, CI, deployment | Agent | `.github/workflows/*`, e2e tests, privacy/link checks, README |

Each agent edits only its files; the lead integrates and commits.

## Milestones

1. Contracts + scaffold committed (done first).
2. First real snapshot per source; first end-to-end `build` with partial data.
3. Frontend renders real data for home, explorer, dossier, votes, people, countries.
4. Integration pass: linkage checks (AI Act end-to-end), search quality, empty/unavailable states.
5. Verification: tests, validate, typecheck, build, e2e smoke, accessibility, privacy, mobile/desktop review.

## Acceptance criteria (first release)

Essential: static build; Pages-deployable; verified featured legislation on the homepage; search over real
records; at least one fully verified readable timeline; multiple real detail pages; working official links;
identifiers preserved; proposed vs adopted vs applicable clearly distinguished; responsive design; no tracking;
no fabricated records; CI and tests pass; coverage and limitations documented.

Strongly desirable: Parliament roll-call breakdowns; Council country positions (if a source is accessible);
search by MEP/country/group/topic; a real transposition example; vote-margin analysis; shareable tracking
views; scheduled refresh; visible snapshot timestamps.

## Post-sprint roadmap (prioritized)

See `docs/ROADMAP.md` (written at the end of the sprint from what actually shipped).
