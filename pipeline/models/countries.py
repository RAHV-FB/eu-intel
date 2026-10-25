"""EU Member States reference table (static, verified facts only).

Population figures for Council qualified-majority calculations are NOT stored here;
they change annually and are owned by pipeline/analysis/council_qmv.py with their
official source (Council decision on population figures).
"""

from __future__ import annotations

# ISO 3166-1 alpha-2 -> English short name. EU institutions use "EL" for Greece; we normalize to "GR".
MEMBER_STATES: dict[str, str] = {
    "AT": "Austria",
    "BE": "Belgium",
    "BG": "Bulgaria",
    "HR": "Croatia",
    "CY": "Cyprus",
    "CZ": "Czechia",
    "DK": "Denmark",
    "EE": "Estonia",
    "FI": "Finland",
    "FR": "France",
    "DE": "Germany",
    "GR": "Greece",
    "HU": "Hungary",
    "IE": "Ireland",
    "IT": "Italy",
    "LV": "Latvia",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "MT": "Malta",
    "NL": "Netherlands",
    "PL": "Poland",
    "PT": "Portugal",
    "RO": "Romania",
    "SK": "Slovakia",
    "SI": "Slovenia",
    "ES": "Spain",
    "SE": "Sweden",
}

# Former member state, needed for historical MEP and Council records (until 31 Jan 2020).
FORMER_MEMBER_STATES: dict[str, str] = {"GB": "United Kingdom"}

# ISO alpha-3 (used by Cellar / EU authority tables) -> alpha-2
ALPHA3_TO_ALPHA2: dict[str, str] = {
    "AUT": "AT", "BEL": "BE", "BGR": "BG", "HRV": "HR", "CYP": "CY", "CZE": "CZ", "DNK": "DK",
    "EST": "EE", "FIN": "FI", "FRA": "FR", "DEU": "DE", "GRC": "GR", "HUN": "HU", "IRL": "IE",
    "ITA": "IT", "LVA": "LV", "LTU": "LT", "LUX": "LU", "MLT": "MT", "NLD": "NL", "POL": "PL",
    "PRT": "PT", "ROU": "RO", "SVK": "SK", "SVN": "SI", "ESP": "ES", "SWE": "SE", "GBR": "GB",
}  # fmt: skip


def normalize_country(code: str | None) -> str | None:
    """Normalize EU/ISO country codes (alpha-2, alpha-3, 'EL', 'UK', authority URIs) to ISO alpha-2."""
    if not code:
        return None
    c = code.strip().rstrip("/").split("/")[-1].upper()
    if c in ("EL",):
        return "GR"
    if c == "UK":
        return "GB"
    if len(c) == 3:
        return ALPHA3_TO_ALPHA2.get(c)
    if c in MEMBER_STATES or c in FORMER_MEMBER_STATES:
        return c
    return None
