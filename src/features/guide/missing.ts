import { NotFoundError } from '../../lib/data';

/**
 * True when a data file does not exist. Static hosts and dev servers with an SPA fallback may answer a
 * missing JSON path with the HTML app shell (HTTP 200), which then fails to parse as JSON.
 */
export function isMissing(error: Error | undefined): boolean {
  return error instanceof NotFoundError || error instanceof SyntaxError;
}
