import { downloadCsv, type CsvCell } from '../lib/csv';

/**
 * "Download CSV" for a table or a list. The file is made in the browser, when the button is pressed, from what the page
 * shows (labels as shown, plus ids): a Blob and a link with the download attribute (src/lib/csv.ts), no request.
 *
 * - `filename`: from csvFileName, e.g. "ep-vote-166051-groups.csv".
 * - `header` and `rows`: the columns, and a function giving the rows in the order shown (called on each press, so the
 *   file follows the current sort and filters).
 * - `of`: what is downloaded, which completes the button's name for screen readers ("the votes by political group"):
 *   the visible label stays "Download CSV", the start of that name (WCAG 2.5.3).
 */
export function CsvButton({
  filename,
  header,
  rows,
  of,
  className,
}: {
  filename: string;
  header: string[];
  rows: () => CsvCell[][];
  of: string;
  className?: string;
}) {
  return (
    <button
      type="button"
      className={className ? `csv-btn ${className}` : 'csv-btn'}
      onClick={() => downloadCsv(filename, header, rows())}
    >
      Download CSV<span className="visually-hidden"> of {of}</span>
    </button>
  );
}
