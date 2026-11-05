import { describe, expect, it } from 'vitest';
import { BOM, csvBlob, csvField, csvFileName, toCsv } from './csv';

/** RFC 4180 read back: fields in double quotes may hold commas, doubled quotes and line breaks. */
function parse(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = '';
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') {
        field += '"';
        i++;
      } else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ',') {
      row.push(field);
      field = '';
    } else if (c === '\r' && text[i + 1] === '\n') {
      row.push(field);
      rows.push(row);
      row = [];
      field = '';
      i++;
    } else field += c;
  }
  if (field || row.length) rows.push([...row, field]);
  return rows;
}

describe('csvField', () => {
  it('leaves a plain field as it is', () => {
    expect(csvField('Renew Europe')).toBe('Renew Europe');
    expect(csvField('2026-11-05')).toBe('2026-11-05');
    expect(csvField('Šefčovič')).toBe('Šefčovič');
  });

  it('quotes a field with a comma, a double quote or a line break, and doubles its quotes', () => {
    expect(csvField('Regulation on payment services, and amending Regulations')).toBe(
      '"Regulation on payment services, and amending Regulations"',
    );
    expect(csvField('the “AI Act”, "as agreed"')).toBe('"the “AI Act”, ""as agreed"""');
    expect(csvField('a "quoted" word')).toBe('"a ""quoted"" word"');
    expect(csvField('two\nlines')).toBe('"two\nlines"');
    expect(csvField('carriage\rreturn')).toBe('"carriage\rreturn"');
  });

  it('writes numbers as numbers, and nothing for a missing value', () => {
    expect(csvField(0)).toBe('0');
    expect(csvField(-12)).toBe('-12');
    expect(csvField(705)).toBe('705');
    expect(csvField(0.985)).toBe('0.985');
    expect(csvField(null)).toBe('');
    expect(csvField(undefined)).toBe('');
    expect(csvField(Number.NaN)).toBe('');
    expect(csvField('')).toBe('');
  });

  it('keeps a spreadsheet from reading a text cell as a formula', () => {
    expect(csvField('=HYPERLINK("https://example.org")')).toBe(`"'=HYPERLINK(""https://example.org"")"`);
    expect(csvField('+32')).toBe("'+32");
    expect(csvField('-5')).toBe("'-5"); // text: a number is passed as a number
    expect(csvField('@SUM(A1)')).toBe("'@SUM(A1)");
    expect(csvField('\tTab')).toBe("'\tTab");
    expect(csvField('a = b')).toBe('a = b'); // only at the start
  });
});

describe('toCsv', () => {
  it('writes one header row and the rows with CRLF line ends, read back as written', () => {
    const header = ['MEP', 'MEP ID', 'Group', 'Recorded vote'];
    const rows = [
      ['Marie-Agnes Strack-Zimmermann', '197443', 'Renew', 'For'],
      ['O’Sullivan, Grace', 7, null, 'Against'],
      ['A "nickname"\nand a second line', '1', 'EPP', 'Abstained'],
    ];
    const text = toCsv(header, rows);
    expect(text.startsWith('MEP,MEP ID,Group,Recorded vote\r\n')).toBe(true);
    expect(text.endsWith('\r\n')).toBe(true);
    expect(text.split('\r\n')).toHaveLength(rows.length + 2); // the header, the rows and the final line end (a value's line break stays \n)
    expect(parse(text)).toEqual([header, ...rows.map((r) => r.map((x) => (x == null ? '' : String(x))))]);
  });

  it('writes a header alone for no rows', () => {
    expect(toCsv(['a', 'b'], [])).toBe('a,b\r\n');
  });

  it('refuses a row of another length than the header', () => {
    expect(() => toCsv(['a', 'b'], [['1', '2'], ['3']])).toThrow('CSV row 2 has 1 fields, the header 2');
  });
});

describe('csvBlob', () => {
  it('is UTF-8 text/csv that starts with a byte-order mark, for spreadsheet applications', async () => {
    const blob = csvBlob(['Country', 'Share for'], [['Česko', '54%']]);
    expect(blob.type).toBe('text/csv;charset=utf-8');
    const bytes = new Uint8Array(await blob.arrayBuffer());
    expect([...bytes.slice(0, 3)]).toEqual([0xef, 0xbb, 0xbf]);
    expect(new TextDecoder('utf-8', { ignoreBOM: true }).decode(bytes)).toBe(`${BOM}Country,Share for\r\nČesko,54%\r\n`);
  });
});

describe('csvFileName', () => {
  it('makes a plain file name ending in .csv', () => {
    expect(csvFileName('ep-vote', '166051', 'groups')).toBe('ep-vote-166051-groups.csv');
    expect(csvFileName('legislation', 'Technology & AI')).toBe('legislation-technology-ai.csv');
    expect(csvFileName('Ćwiczenie', 'Größe/Δ')).toBe('cwiczenie-gro-e.csv'); // accents dropped, other letters replaced
    expect(csvFileName('', '  ')).toBe('data.csv');
  });
});
