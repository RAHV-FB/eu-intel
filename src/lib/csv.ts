/**
 * CSV files made in the browser from the data a page already holds: no request is made (src/components/CsvButton.tsx).
 *
 * RFC 4180: comma-separated, a field with a comma, a double quote or a line break enclosed in double quotes, a double
 * quote inside it doubled, CRLF line ends, one header row. UTF-8 with a byte-order mark: Excel (on Windows and macOS)
 * reads a CSV file without one in the system's legacy code page, so that "Pérez" becomes "PÃ©rez" and "Šefčovič" is
 * garbled; with it Excel, Numbers, LibreOffice and Google Sheets read UTF-8, and so do pandas, R's readr and Python
 * with encoding="utf-8-sig". (The open dataset's files, data/open/*.csv, have no byte-order mark: Frictionless
 * readers expect plain UTF-8.)
 *
 * A text cell that a spreadsheet would take for a formula (it starts with =, +, -, @, a tab or a carriage return) gets a
 * leading apostrophe, which spreadsheets hide ("CSV injection", OWASP). Numbers are written as numbers.
 */
export type CsvCell = string | number | null | undefined;

export const BOM = '﻿';

const QUOTE = /[",\r\n]/;
const FORMULA = /^[=+\-@\t\r]/;

/** One field as RFC 4180 writes it; null, undefined and a number that is not finite are empty. */
export function csvField(value: CsvCell): string {
  if (value == null) return '';
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : '';
  const text = FORMULA.test(value) ? `'${value}` : value;
  return QUOTE.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** The header row and the rows, each the header's length, as CSV text with CRLF line ends. */
export function toCsv(header: string[], rows: CsvCell[][]): string {
  const bad = rows.findIndex((r) => r.length !== header.length);
  if (bad >= 0) throw new Error(`CSV row ${bad + 1} has ${rows[bad].length} fields, the header ${header.length}`);
  return [header, ...rows].map((r) => r.map(csvField).join(',')).join('\r\n') + '\r\n';
}

/** The file: the byte-order mark and the CSV text, as UTF-8 of type text/csv. */
export function csvBlob(header: string[], rows: CsvCell[][]): Blob {
  return new Blob([BOM, toCsv(header, rows)], { type: 'text/csv;charset=utf-8' });
}

/** A file name of lower-case letters, digits, dots and dashes, ending in .csv: csvFileName('ep-vote', '166051',
 * 'groups') is "ep-vote-166051-groups.csv". */
export function csvFileName(...parts: (string | number)[]): string {
  const base = parts
    .map((p) =>
      String(p)
        .normalize('NFKD')
        .replace(/[̀-ͯ]/g, '')
        .toLowerCase()
        .replace(/[^a-z0-9.]+/g, '-')
        .replace(/^-+|-+$/g, ''),
    )
    .filter(Boolean)
    .join('-');
  return `${base || 'data'}.csv`;
}

/** Offer the CSV as a download: a link to a Blob URL with the download attribute, clicked. Nothing is sent: the file
 * is made from `rows` in the browser. The URL is revoked a minute later (a browser may read it after the click). */
export function downloadCsv(filename: string, header: string[], rows: CsvCell[][]): void {
  const url = URL.createObjectURL(csvBlob(header, rows));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.hidden = true;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
