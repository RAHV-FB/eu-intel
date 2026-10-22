import { existsSync, readFileSync } from 'node:fs';
import { BASE_PATH } from './env';

/** Fail fast with an actionable message when dist/ is missing or was built for the wrong base path. */
export default function globalSetup(): void {
  if (!existsSync('dist/index.html')) {
    throw new Error('dist/ not found. Run `python -m pipeline build && BASE_PATH=/eu-intel/ npm run build` first.');
  }
  const html = readFileSync('dist/index.html', 'utf8');
  if (!html.includes(`${BASE_PATH}assets/`)) {
    throw new Error(
      `dist/ was not built for the Pages subpath ${BASE_PATH}. Rebuild with \`BASE_PATH=${BASE_PATH} npm run build\`.`,
    );
  }
  if (!existsSync('dist/data/meta.json')) {
    throw new Error('dist/data/ is missing: run `python -m pipeline build` before `npm run build`.');
  }
}
