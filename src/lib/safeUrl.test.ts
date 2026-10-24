import { describe, expect, it } from 'vitest';
import { safeUrl } from './format';

// The official data gives http:// addresses for Parliament's RegData files (2,229 in the 23 October 2026 build) and for ELI
// identifiers (1,290). Both hosts answer them with a 301 to the same path on https (checked with curl on a sample of each).
describe('safeUrl', () => {
  it('opens the http:// addresses of the official hosts that serve them over https as https://', () => {
    expect(safeUrl('http://data.europa.eu/eli/reg/2018/848/oj')).toBe('https://data.europa.eu/eli/reg/2018/848/oj');
    expect(safeUrl('http://www.europarl.europa.eu/RegData/docs_autres_institutions/commission_europeenne/com/2016/0683/COM_COM(2016)0683(ANN)_EN.pdf')).toBe(
      'https://www.europarl.europa.eu/RegData/docs_autres_institutions/commission_europeenne/com/2016/0683/COM_COM(2016)0683(ANN)_EN.pdf',
    );
  });

  it('changes nothing else', () => {
    const same = [
      'https://data.europa.eu/eli/reg/2018/848/oj',
      'http://example.org/page',
      'http://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689', // not checked: left as given
      'http://data.europa.eu.example.org/eli/reg/2018/848/oj', // a look-alike host
      'http://evildata.europa.eu/eli/reg/2018/848/oj',
      'http://data.europa.eu:8080/eli/reg/2018/848/oj', // another service on the host
    ];
    for (const u of same) expect(safeUrl(u)).toBe(new URL(u).href);
  });

  it('still refuses what is not http(s)', () => {
    expect(safeUrl('javascript:alert(1)')).toBeUndefined();
    expect(safeUrl('ftp://data.europa.eu/x')).toBeUndefined();
    expect(safeUrl('not a url')).toBeUndefined();
    expect(safeUrl(null)).toBeUndefined();
  });
});
