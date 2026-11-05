import { describe, expect, it } from 'vitest';
import { isDossierFile } from './labels';

describe("a file read as a legislative file's record", () => {
  const ai = { id: '2021-0106', title: 'Artificial Intelligence Act', timeline: [] };

  it('is the record of the id asked for', () => {
    expect(isDossierFile(ai, '2021-0106')).toBe(true);
  });

  it('is not the list of every file, which dossiers/index.json is (a shared Following link can name the id "index")', () => {
    // /following?ids=index read that list as a file and failed on its missing title: "This page could not be displayed"
    expect(isDossierFile([{ id: '2021-0106', title: 'Artificial Intelligence Act' }], 'index')).toBe(false);
  });

  it("is not another file's record, nor a value without a timeline", () => {
    expect(isDossierFile(ai, '2022-0155')).toBe(false);
    expect(isDossierFile({ id: '2021-0106' }, '2021-0106')).toBe(false);
    expect(isDossierFile(null, '2021-0106')).toBe(false);
    expect(isDossierFile('2021-0106', '2021-0106')).toBe(false);
  });
});
