"""Country-code normalisation (pure, dependency-free).

Intelligence providers emit ISO-2 country scope keys (``US``, ``CN``), but a
supplier's ``country`` and a product's ``country_of_origin`` are free text and
inconsistent (``USA``, ``United States``, ``China``). ``to_iso2`` folds all of
these to a canonical ISO-2 code so country-scoped signals actually match the
suppliers/products they concern — without it the signals only move the global
risk number, not per-supplier decisions.

Unknown inputs return ``None`` (no match, the prior behaviour), so this only ever
*adds* matches. A curated map of the major trading economies; extend as needed.
"""
from __future__ import annotations

# ISO-3 codes and common names/aliases (lower-cased) -> ISO-2.
_ALIASES: dict[str, str] = {}


def _add(iso2: str, iso3: str, *names: str) -> None:
    _ALIASES[iso3.lower()] = iso2
    for n in names:
        _ALIASES[n.lower()] = iso2


# (iso2, iso3, *aliases) for the major sourcing / trading economies.
_add("CN", "CHN", "china", "prc", "people's republic of china", "mainland china")
_add("US", "USA", "united states", "united states of america", "u.s.", "u.s.a.", "america")
_add("JP", "JPN", "japan")
_add("DE", "DEU", "germany")
_add("IN", "IND", "india")
_add("KR", "KOR", "south korea", "korea", "korea, rep.", "republic of korea")
_add("TW", "TWN", "taiwan", "chinese taipei")
_add("VN", "VNM", "vietnam", "viet nam")
_add("TH", "THA", "thailand")
_add("ID", "IDN", "indonesia")
_add("MY", "MYS", "malaysia")
_add("GB", "GBR", "united kingdom", "uk", "u.k.", "great britain", "britain", "england")
_add("TR", "TUR", "turkey", "türkiye", "turkiye")
_add("MX", "MEX", "mexico")
_add("BR", "BRA", "brazil", "brasil")
_add("ZA", "ZAF", "south africa")
_add("PL", "POL", "poland")
_add("IT", "ITA", "italy")
_add("FR", "FRA", "france")
_add("ES", "ESP", "spain")
_add("NL", "NLD", "netherlands", "holland")
_add("SG", "SGP", "singapore")
_add("HK", "HKG", "hong kong")
_add("BD", "BGD", "bangladesh")
_add("PK", "PAK", "pakistan")
_add("PH", "PHL", "philippines")
_add("CA", "CAN", "canada")
_add("AU", "AUS", "australia")
_add("CH", "CHE", "switzerland")
_add("SE", "SWE", "sweden")
_add("BE", "BEL", "belgium")
_add("AT", "AUT", "austria")
_add("RU", "RUS", "russia", "russian federation")
_add("SA", "SAU", "saudi arabia")
_add("AE", "ARE", "united arab emirates", "uae")
_add("EG", "EGY", "egypt")
_add("NG", "NGA", "nigeria")
_add("AR", "ARG", "argentina")
_add("CL", "CHL", "chile")
_add("CO", "COL", "colombia")
_add("PE", "PER", "peru")
_add("IL", "ISR", "israel")
_add("IE", "IRL", "ireland")
_add("PT", "PRT", "portugal")
_add("GR", "GRC", "greece")
_add("CZ", "CZE", "czech republic", "czechia")
_add("RO", "ROU", "romania")
_add("HU", "HUN", "hungary")
_add("FI", "FIN", "finland")
_add("DK", "DNK", "denmark")
_add("NO", "NOR", "norway")
_add("NZ", "NZL", "new zealand")
_add("KH", "KHM", "cambodia")
_add("LK", "LKA", "sri lanka")
_add("MM", "MMR", "myanmar", "burma")

# Valid ISO-2 codes (so a bare 2-letter input is accepted as-is, not guessed).
_ISO2_CODES = set(_ALIASES.values())


def to_iso2(country: str | None) -> str | None:
    """Canonical ISO-2 for a free-text country / ISO-3 / name, or ``None``."""
    if not country:
        return None
    c = str(country).strip()
    if not c:
        return None
    lowered = c.lower()
    if lowered in _ALIASES:
        return _ALIASES[lowered]
    upper = c.upper()
    if len(upper) == 2 and upper.isalpha() and upper in _ISO2_CODES:
        return upper
    return None
