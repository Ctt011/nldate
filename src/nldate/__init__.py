"""nldate — parse natural-language date strings into datetime.date objects.

Public API:
    parse(s: str, today: date | None = None) -> date

The parser handles a wide variety of natural-language date expressions, including:

    * Anchors: "today", "tomorrow", "yesterday"
    * Weekday phrases: "next Tuesday", "this Monday", "last Friday"
    * Offsets relative to now: "in 3 days", "2 weeks ago", "5 days from now"
    * Offsets relative to a date: "5 days before December 1st, 2025",
      "1 year and 2 months after yesterday"
    * Absolute dates in many forms: "December 1, 2025", "Dec 1 2025",
      "1 December 2025", "2025-12-01", "12/01/2025"
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

__all__ = ["main", "parse"]


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

WEEKDAYS: dict[str, int] = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "weds": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}

MONTHS: dict[str, int] = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

NUMBER_WORDS: dict[str, int] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "hundred": 100,
    "a": 1,
    "an": 1,
}

UNIT_ALIASES: dict[str, str] = {
    "day": "day",
    "days": "day",
    "week": "week",
    "weeks": "week",
    "wk": "week",
    "wks": "week",
    "fortnight": "fortnight",
    "fortnights": "fortnight",
    "month": "month",
    "months": "month",
    "mo": "month",
    "mos": "month",
    "year": "year",
    "years": "year",
    "yr": "year",
    "yrs": "year",
    "decade": "decade",
    "decades": "decade",
    "century": "century",
    "centuries": "century",
}

# How many days each unit represents (for the ones expressible as fixed days).
UNIT_TO_DAYS: dict[str, int] = {
    "day": 1,
    "week": 7,
    "fortnight": 14,
}

# Months / years are handled via calendar arithmetic so end-of-month edge cases work.
UNIT_TO_MONTHS: dict[str, int] = {
    "month": 1,
    "year": 12,
    "decade": 120,
    "century": 1200,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_ordinals(s: str) -> str:
    """Remove ordinal suffixes from numbers: 1st -> 1, 22nd -> 22."""
    return re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", s)


def _normalize(s: str) -> str:
    """Lowercase, strip filler, normalize whitespace, drop ordinal suffixes.

    Handles:
      * trailing periods on words (``Dec.`` -> ``dec``) without touching
        digit-separated dates like ``12.01.2025``;
      * possessives (``today's date`` -> ``today date``);
      * commas, hyphens-as-spaces in date phrases (``december-1-2025`` ->
        ``december 1 2025``), and the filler words ``of`` and ``the``.
    """
    if not isinstance(s, str):
        raise TypeError(f"parse() expects a str, got {type(s).__name__}")
    text = s.strip().lower()
    text = _strip_ordinals(text)
    # Strip period after a letter (e.g. "dec." -> "dec"). Leaves digit-dotted
    # dates like "12.01.2025" alone because the period there follows a digit.
    text = re.sub(r"([a-z])\.", r"\1", text)
    # Strip apostrophe-s possessives ("today's" -> "today"). Handles both
    # straight (U+0027) and curly (U+2019) apostrophes.
    text = re.sub(r"([a-z])['\u2019]s\b", r"\1", text)
    # Replace stray punctuation with space (commas, semicolons).
    text = re.sub(r"[,;]", " ", text)
    # Hyphens between letters/numbers in verbose dates -> spaces, but leave
    # ISO-style numeric dates ("2025-12-01") intact.
    before_alpha = text
    text = re.sub(r"(?<=[a-z])-(?=[a-z\d])", " ", text)
    text = re.sub(r"(?<=\d)-(?=[a-z])", " ", text)
    # Only collapse remaining digit-hyphen-digit if the prior alpha rules
    # actually fired — that signals we're parsing a verbose date like
    # "december-1-2025" where hyphens are word separators throughout. If they
    # didn't fire, an embedded ISO date like "2 weeks after 2025-12-04" stays
    # intact for the absolute-date matcher.
    if text != before_alpha:
        text = re.sub(r"(?<=\d)-(?=\d)", " ", text)
    text = re.sub(r"\bof\b", " ", text)
    text = re.sub(r"\bthe\b", " ", text)
    # "today's date" -> "today date" -> drop "date" as filler.
    text = re.sub(r"\bdate\b", " ", text)
    # Collapse whitespace.
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _words_to_int(words: str) -> int | None:
    """Turn a small English number phrase into an int.

    Examples: "two" -> 2, "twenty one" -> 21, "one hundred and five" -> 105.
    Returns None if the phrase isn't a recognizable number.
    """
    parts = [p for p in re.split(r"[\s-]+", words.strip()) if p and p != "and"]
    if not parts:
        return None
    total = 0
    current = 0
    for part in parts:
        if part not in NUMBER_WORDS:
            return None
        value = NUMBER_WORDS[part]
        if value == 100:
            current = max(current, 1) * 100
        else:
            current += value
    total += current
    return total


def _parse_amount(token: str) -> int | None:
    """Parse a numeric amount written as digits or English words."""
    token = token.strip()
    if not token:
        return None
    if re.fullmatch(r"-?\d+", token):
        return int(token)
    return _words_to_int(token)


def _add_months(d: date, months: int) -> date:
    """Add ``months`` (possibly negative) to ``d``, clamping the day if needed.

    Adding 1 month to Jan 31 gives Feb 28 (or 29 on a leap year), not an error.
    """
    total = d.month - 1 + months
    new_year = d.year + total // 12
    new_month = total % 12 + 1
    last_day = calendar.monthrange(new_year, new_month)[1]
    new_day = min(d.day, last_day)
    return date(new_year, new_month, new_day)


# ---------------------------------------------------------------------------
# Duration parsing
# ---------------------------------------------------------------------------

# Regex token sets built once.
_WORD_NUMBERS_PATTERN = (
    r"(?:\d+|" + "|".join(sorted(NUMBER_WORDS.keys(), key=len, reverse=True)) + r")"
)
_UNIT_PATTERN = "|".join(sorted(UNIT_ALIASES.keys(), key=len, reverse=True))
# A single "<amount> <unit>" clause. Amount may itself be multi-word
# (e.g. "twenty one"), so use a non-greedy capture and then validate.
_SINGLE_DURATION_RE = re.compile(
    rf"\b([\w\s-]+?)\s+({_UNIT_PATTERN})\b",
)


def _parse_duration(text: str) -> tuple[int, int] | None:
    """Parse a duration phrase into (days, months).

    The duration can be a sum of several units joined by "and" or commas, e.g.
    "1 year and 2 months", "2 weeks 3 days". Returns ``None`` if no recognizable
    duration is present. Negative durations are produced by callers via sign-flip.
    """
    text = text.strip()
    if not text:
        return None
    # Split on "and" / "," to allow compound durations.
    chunks = re.split(r"\s+and\s+|\s*,\s*", text)
    total_days = 0
    total_months = 0
    found_any = False
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        match = re.fullmatch(rf"(.+?)\s+({_UNIT_PATTERN})", chunk)
        if not match:
            return None
        amount = _parse_amount(match.group(1))
        if amount is None:
            return None
        unit = UNIT_ALIASES[match.group(2)]
        if unit in UNIT_TO_DAYS:
            total_days += amount * UNIT_TO_DAYS[unit]
        elif unit in UNIT_TO_MONTHS:
            total_months += amount * UNIT_TO_MONTHS[unit]
        else:  # pragma: no cover - defensive
            return None
        found_any = True
    if not found_any:
        return None
    return total_days, total_months


def _apply_offset(anchor: date, days: int, months: int) -> date:
    """Apply a (days, months) offset to ``anchor``."""
    result = _add_months(anchor, months) if months else anchor
    if days:
        result = result + timedelta(days=days)
    return result


# ---------------------------------------------------------------------------
# Weekday-relative parsing
# ---------------------------------------------------------------------------

WEEKDAY_QUALIFIERS = {"next", "this", "last", "coming", "past", "upcoming", "previous"}


def _resolve_weekday(text: str, today: date) -> date | None:
    """Resolve phrases like "next Tuesday", "this Monday", "last Friday"."""
    parts = text.split()
    qualifier: str | None = None
    if parts and parts[0] in WEEKDAY_QUALIFIERS:
        qualifier = parts[0]
        parts = parts[1:]
    if len(parts) != 1:
        return None
    weekday_name = parts[0]
    if weekday_name not in WEEKDAYS:
        return None
    target = WEEKDAYS[weekday_name]
    delta = (target - today.weekday()) % 7
    if qualifier in (None, "this", "coming", "upcoming"):
        # "this Tuesday" / bare "Tuesday" / "coming Tuesday": the next time that
        # weekday occurs, treating today as that weekday if it matches.
        if delta == 0 and qualifier in ("coming", "upcoming"):
            delta = 7
        return today + timedelta(days=delta)
    if qualifier == "next":
        # "next Tuesday" means strictly future; if today is Tuesday, skip a week.
        if delta == 0:
            delta = 7
        return today + timedelta(days=delta)
    if qualifier in ("last", "past", "previous"):
        back = (today.weekday() - target) % 7
        if back == 0:
            back = 7
        return today - timedelta(days=back)
    return None


# ---------------------------------------------------------------------------
# Absolute date parsing
# ---------------------------------------------------------------------------

_MONTH_PATTERN = "|".join(sorted(MONTHS.keys(), key=len, reverse=True))


def _parse_absolute(text: str) -> date | None:
    """Try to parse ``text`` as an absolute date in any of several formats."""
    text = text.strip()
    if not text:
        return None

    # 1. ISO-ish: 2025-12-01, 2025/12/01, 2025.12.01
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if m:
        year, month, day = (int(x) for x in m.groups())
        return _safe_date(year, month, day)

    # 2. US: 12/01/2025, 12-01-2025, 12.1.25
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2}|\d{4})", text)
    if m:
        month, day, year = (int(x) for x in m.groups())
        if year < 100:
            year += 2000 if year < 70 else 1900
        return _safe_date(year, month, day)

    # 3. "December 1 2025" or "1 December 2025" (with optional commas already stripped)
    m = re.fullmatch(rf"({_MONTH_PATTERN})\s+(\d{{1,2}})\s+(\d{{2,4}})", text)
    if m:
        month = MONTHS[m.group(1)]
        day = int(m.group(2))
        year = _expand_year(int(m.group(3)))
        return _safe_date(year, month, day)
    m = re.fullmatch(rf"(\d{{1,2}})\s+({_MONTH_PATTERN})\s+(\d{{2,4}})", text)
    if m:
        day = int(m.group(1))
        month = MONTHS[m.group(2)]
        year = _expand_year(int(m.group(3)))
        return _safe_date(year, month, day)

    # 4. "December 1" or "1 December" (no year — default to today's year)
    m = re.fullmatch(rf"({_MONTH_PATTERN})\s+(\d{{1,2}})", text)
    if m:
        month = MONTHS[m.group(1)]
        day = int(m.group(2))
        return _safe_date(date.today().year, month, day)
    m = re.fullmatch(rf"(\d{{1,2}})\s+({_MONTH_PATTERN})", text)
    if m:
        day = int(m.group(1))
        month = MONTHS[m.group(2)]
        return _safe_date(date.today().year, month, day)

    return None


def _expand_year(year: int) -> int:
    """Expand a 2-digit year to a 4-digit year using a 70/30 pivot."""
    if year < 100:
        return year + (2000 if year < 70 else 1900)
    return year


def _safe_date(year: int, month: int, day: int) -> date | None:
    """Build a date, returning None on invalid components."""
    try:
        return date(year, month, day)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Top-level parser
# ---------------------------------------------------------------------------

_RELATIVE_ANCHORS = {"today", "now", "tomorrow", "yesterday"}


def _parse_anchor(text: str, today: date) -> date | None:
    """Resolve a 'simple anchor' phrase to a concrete date."""
    text = text.strip()
    if text in ("today", "now"):
        return today
    if text == "tomorrow":
        return today + timedelta(days=1)
    if text == "yesterday":
        return today - timedelta(days=1)
    if text in ("day after tomorrow", "the day after tomorrow"):
        return today + timedelta(days=2)
    if text in ("day before yesterday", "the day before yesterday"):
        return today - timedelta(days=2)
    return None


_PERIOD_OFFSETS: dict[str, tuple[int, int]] = {
    # period_word -> (days, months) offset for "next <period>"
    "week": (7, 0),
    "month": (0, 1),
    "year": (0, 12),
}


def _resolve_period_phrase(text: str, today: date) -> date | None:
    """Resolve "next/this/last <week|month|year>" into a date offset from today."""
    m = re.fullmatch(r"(next|this|last|past|previous|coming|upcoming)\s+(week|month|year)", text)
    if not m:
        return None
    qualifier, period = m.group(1), m.group(2)
    days, months = _PERIOD_OFFSETS[period]
    if qualifier in ("next", "coming", "upcoming"):
        return _apply_offset(today, days, months)
    if qualifier in ("last", "past", "previous"):
        return _apply_offset(today, -days, -months)
    # "this <period>" -> today (the closest date in the current period).
    return today


def _parse_inner(text: str, today: date) -> date | None:
    """Parse a normalized phrase into a concrete date, or return None.

    Order matters: more specific patterns are tried first.
    """
    text = text.strip()
    if not text:
        return None

    # 1. Simple anchors.
    anchor = _parse_anchor(text, today)
    if anchor is not None:
        return anchor

    # 2. Weekday phrases (bare weekday, or "next/this/last <weekday>").
    weekday_result = _resolve_weekday(text, today)
    if weekday_result is not None:
        return weekday_result

    # 2b. Period phrases ("next week", "last month", "next year").
    period_result = _resolve_period_phrase(text, today)
    if period_result is not None:
        return period_result

    # 3. "in <duration>" -> today + duration.
    m = re.fullmatch(r"in\s+(.+)", text)
    if m:
        duration = _parse_duration(m.group(1))
        if duration is not None:
            days, months = duration
            return _apply_offset(today, days, months)

    # 4. "<duration> from now" -> today + duration.
    m = re.fullmatch(r"(.+?)\s+from\s+now", text)
    if m:
        duration = _parse_duration(m.group(1))
        if duration is not None:
            days, months = duration
            return _apply_offset(today, days, months)

    # 5. "<duration> ago" -> today - duration.
    m = re.fullmatch(r"(.+?)\s+ago", text)
    if m:
        duration = _parse_duration(m.group(1))
        if duration is not None:
            days, months = duration
            return _apply_offset(today, -days, -months)

    # 6. "<duration> (before|after|from|prior to|past) <date>".
    m = re.fullmatch(
        r"(.+?)\s+(before|after|following|from|past|prior to|after that of)\s+(.+)",
        text,
    )
    if m:
        duration = _parse_duration(m.group(1))
        if duration is not None:
            anchor_date = _parse_inner(m.group(3), today)
            if anchor_date is not None:
                days, months = duration
                if m.group(2) in ("before", "prior to"):
                    days, months = -days, -months
                return _apply_offset(anchor_date, days, months)

    # 7. Absolute date.
    absolute = _parse_absolute(text)
    if absolute is not None:
        return absolute

    return None


def parse(s: str, today: date | None = None) -> date:
    """Parse a natural-language date string into a ``datetime.date``.

    Parameters
    ----------
    s:
        The natural-language date string, e.g. ``"next Tuesday"`` or
        ``"5 days before December 1st, 2025"``.
    today:
        The reference date for relative expressions. Defaults to
        :func:`datetime.date.today`.

    Returns
    -------
    datetime.date
        The concrete date the string refers to.

    Raises
    ------
    ValueError
        If the string cannot be parsed as a date.
    TypeError
        If ``s`` is not a ``str``.
    """
    if today is None:
        today = date.today()
    normalized = _normalize(s)
    result = _parse_inner(normalized, today)
    if result is None:
        raise ValueError(f"Could not parse date string: {s!r}")
    return result


def main() -> None:  # pragma: no cover - small CLI wrapper
    """Tiny CLI: ``uv run nldate "next Tuesday"`` prints the resolved date."""
    import sys

    if len(sys.argv) < 2:
        print("usage: nldate <natural-language date>", file=sys.stderr)
        raise SystemExit(2)
    text = " ".join(sys.argv[1:])
    print(parse(text).isoformat())
