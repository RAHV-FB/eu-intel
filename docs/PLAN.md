# Plan

## Components

| Area | Files |
| --- | --- |
| Core contracts and app shell | `pipeline/{http,snapshot,__main__}.py`, `pipeline/models/*`, `src/types/data.ts`, `src/App.tsx`, `src/components/*`, `src/styles/*` |
| EP people and organizations | `pipeline/sources/ep_people.py` |
| EP procedures and lifecycle status | `pipeline/sources/ep_procedures.py`, `pipeline/analysis/status.py` |
| EP plenary votes and margins | `pipeline/sources/ep_votes.py`, `pipeline/analysis/ep_margin.py` |
| EUR-Lex legal acts | `pipeline/sources/eurlex.py` |
| Council votes and QMV | `pipeline/sources/council.py`, `pipeline/analysis/council_qmv.py` |
| National implementation | `pipeline/sources/implementation.py` |
| Editorial layer and Legislative Train | `data/curated/*`, `pipeline/sources/legislative_train.py`, `docs/EDITORIAL.md` |
| Build, search, activity | `pipeline/build.py`, `pipeline/validate.py`, `pipeline/analysis/{activity,feeds}.py`, `src/lib/search.ts` |
| Discovery and legislation pages | Home, Legislation, Dossier, Search, Following |
| Votes, people, countries, guide pages | Votes, Vote, People, MEP, Group, Party, Countries, Country, How the EU Works, About, Privacy |
| QA, CI, deployment | `.github/workflows/*`, `tests/e2e/*`, privacy/link checks, README |

## Milestones

1. Contracts and scaffold.
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

## Roadmap

See `docs/ROADMAP.md`.
