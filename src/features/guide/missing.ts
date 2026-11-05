import { NotFoundError } from '../../lib/data';

/**
 * True when a data file does not exist: a 404 (GitHub Pages), or the SPA's HTML page that a dev or preview server
 * answers for a missing path (loadData turns both into a NotFoundError). A file that exists but cannot be read (not
 * JSON, or cut short) is not missing: its page says it could not be loaded, with a way to try again, rather than that
 * the record is not in the dataset.
 */
export function isMissing(error: unknown): boolean {
  return error instanceof NotFoundError;
}
