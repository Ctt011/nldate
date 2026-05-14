"""Test suite for nldate.parse.

These tests are the spec. Each test pins down one behavior with a fixed
``today=...`` reference so the assertions are deterministic.
"""

from __future__ import annotations

from datetime import date

import pytest

from nldate import parse

# A fixed reference date used across most tests. Wed May 13, 2026 — the day
# the assignment is being completed. Weekday: Wednesday (weekday() == 2).
REF = date(2026, 5, 13)


# ---------------------------------------------------------------------------
# 1. Simple anchors
# ---------------------------------------------------------------------------


def test_today() -> None:
    assert parse("today", today=REF) == REF


def test_tomorrow() -> None:
    assert parse("tomorrow", today=REF) == date(2026, 5, 14)


def test_yesterday() -> None:
    assert parse("yesterday", today=REF) == date(2026, 5, 12)


def test_anchor_case_and_whitespace_insensitive() -> None:
    assert parse("  TODAY  ", today=REF) == REF
    assert parse("ToMoRrOw", today=REF) == date(2026, 5, 14)


def test_day_after_tomorrow() -> None:
    assert parse("the day after tomorrow", today=REF) == date(2026, 5, 15)


def test_day_before_yesterday() -> None:
    assert parse("day before yesterday", today=REF) == date(2026, 5, 11)


# ---------------------------------------------------------------------------
# 2. Weekday phrases
# ---------------------------------------------------------------------------


def test_next_tuesday_when_today_is_wednesday() -> None:
    # REF is Wednesday May 13, 2026 -> next Tuesday is May 19.
    assert parse("next Tuesday", today=REF) == date(2026, 5, 19)


def test_next_weekday_same_as_today_skips_a_week() -> None:
    # REF is Wednesday; "next Wednesday" should mean a week from today.
    assert parse("next Wednesday", today=REF) == date(2026, 5, 20)


def test_this_friday() -> None:
    # REF is Wednesday; "this Friday" is the upcoming Friday this week.
    assert parse("this Friday", today=REF) == date(2026, 5, 15)


def test_bare_weekday_means_upcoming() -> None:
    # Bare "Friday" treated as the next occurrence (REF Wed -> Fri May 15).
    assert parse("Friday", today=REF) == date(2026, 5, 15)


def test_last_friday() -> None:
    # Most recent past Friday before REF (Wed May 13) is May 8.
    assert parse("last Friday", today=REF) == date(2026, 5, 8)


def test_last_weekday_when_today_is_that_weekday() -> None:
    # REF is Wednesday; "last Wednesday" should mean a week ago, not today.
    assert parse("last Wednesday", today=REF) == date(2026, 5, 6)


def test_weekday_abbreviation() -> None:
    assert parse("next tue", today=REF) == date(2026, 5, 19)
    assert parse("last fri", today=REF) == date(2026, 5, 8)


# ---------------------------------------------------------------------------
# 3. "in N units" / "N units ago" / "N units from now"
# ---------------------------------------------------------------------------


def test_in_three_days() -> None:
    assert parse("in 3 days", today=REF) == date(2026, 5, 16)


def test_in_two_weeks() -> None:
    assert parse("in 2 weeks", today=REF) == date(2026, 5, 27)


def test_in_one_month() -> None:
    assert parse("in 1 month", today=REF) == date(2026, 6, 13)


def test_in_one_year() -> None:
    assert parse("in 1 year", today=REF) == date(2027, 5, 13)


def test_n_days_ago() -> None:
    assert parse("5 days ago", today=REF) == date(2026, 5, 8)


def test_n_weeks_from_now() -> None:
    assert parse("3 weeks from now", today=REF) == date(2026, 6, 3)


def test_word_number_in_offset() -> None:
    assert parse("two weeks from tomorrow", today=REF) == date(2026, 5, 28)


def test_compound_duration_year_and_months() -> None:
    # REF + 1 year + 2 months = July 13, 2027.
    assert parse("1 year and 2 months from now", today=REF) == date(2027, 7, 13)


def test_compound_duration_weeks_and_days() -> None:
    # REF + 2 weeks + 3 days = May 30, 2026.
    assert parse("2 weeks and 3 days from now", today=REF) == date(2026, 5, 30)


# ---------------------------------------------------------------------------
# 4. Offsets relative to a specific date
# ---------------------------------------------------------------------------


def test_n_days_before_absolute_date() -> None:
    # 5 days before December 1, 2025 = November 26, 2025.
    assert parse("5 days before December 1st, 2025", today=REF) == date(2025, 11, 26)


def test_n_days_after_absolute_date() -> None:
    assert parse("10 days after December 1, 2025", today=REF) == date(2025, 12, 11)


def test_year_months_after_yesterday() -> None:
    # REF - 1 day = May 12, 2026; + 1 year + 2 months = July 12, 2027.
    assert parse("1 year and 2 months after yesterday", today=REF) == date(2027, 7, 12)


def test_three_weeks_before_next_friday() -> None:
    # REF Wed May 13 -> next Friday = May 15 -> 3 weeks before = Apr 24.
    assert parse("3 weeks before next Friday", today=REF) == date(2026, 4, 24)


# ---------------------------------------------------------------------------
# 5. Absolute dates in many formats
# ---------------------------------------------------------------------------


def test_iso_date() -> None:
    assert parse("2025-12-01", today=REF) == date(2025, 12, 1)


def test_us_slash_date() -> None:
    assert parse("12/01/2025", today=REF) == date(2025, 12, 1)


def test_two_digit_year() -> None:
    assert parse("12/01/25", today=REF) == date(2025, 12, 1)


def test_long_month_name() -> None:
    assert parse("December 1, 2025", today=REF) == date(2025, 12, 1)


def test_short_month_name() -> None:
    assert parse("Dec 1 2025", today=REF) == date(2025, 12, 1)


def test_day_month_year_order() -> None:
    assert parse("1 December 2025", today=REF) == date(2025, 12, 1)


def test_ordinal_in_absolute_date() -> None:
    assert parse("December 1st, 2025", today=REF) == date(2025, 12, 1)
    assert parse("1st of December 2025", today=REF) == date(2025, 12, 1)


# ---------------------------------------------------------------------------
# 6. End-of-month rollover edge cases
# ---------------------------------------------------------------------------


def test_add_month_clamps_to_last_day() -> None:
    # Jan 31 + 1 month -> Feb 28 (2027 is not a leap year).
    assert parse("1 month after January 31 2027", today=REF) == date(2027, 2, 28)


def test_add_month_leap_year() -> None:
    # Jan 31 + 1 month in a leap year (2028) -> Feb 29.
    assert parse("1 month after January 31 2028", today=REF) == date(2028, 2, 29)


# ---------------------------------------------------------------------------
# 7. Defaults: today=None uses real today
# ---------------------------------------------------------------------------


def test_default_today_runs_without_error() -> None:
    result = parse("today")
    assert isinstance(result, date)
    assert result == date.today()


# ---------------------------------------------------------------------------
# 8. Error handling
# ---------------------------------------------------------------------------


def test_unparseable_raises_value_error() -> None:
    with pytest.raises(ValueError):
        parse("this is not a date", today=REF)


def test_non_string_raises_type_error() -> None:
    with pytest.raises(TypeError):
        parse(12345, today=REF)  # type: ignore[arg-type]


def test_empty_string_raises_value_error() -> None:
    with pytest.raises(ValueError):
        parse("", today=REF)
