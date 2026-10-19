"""recurrence_rules, step 1 of the calendar-periods plan (nb tw:docs/tw-calendar-periods-plan.md):
periods only, standard library only.

    python3 -m pytest -q test/test_rules.py

Dates in and out are naive UTC, as the hooks keep them (parse_date); steps are taken on the
local calendar, as add_local does. These tests run in America/Toronto so that DST is crossed.

- Day and week periods behave exactly as before (add_local over (n-1) x the period).
- Month and year periods step calendar months on periodic templates, clamped to the month's
  end from the template's own day (Jan 31 -> Feb 28 -> Mar 31), and count 30 / 365 days on
  chained ones, as before.
- Bad input raises RuleError with the position of the problem, never a traceback, and so does
  a date too close to the end of datetime's range (someday, later = 9999-12-30).
"""
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ['TZ'] = 'America/Toronto'
time.tzset()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from recurrence_common_hook import add_local, parse_duration  # noqa: E402
from recurrence_rules import RuleError, parse  # noqa: E402


def L(y, mo, d, h=0, mi=0):
    """Local Toronto wall time -> naive UTC, as Taskwarrior stores it."""
    return datetime(y, mo, d, h, mi).astimezone(timezone.utc).replace(tzinfo=None)


def local(dt):
    """Naive UTC -> local wall time (naive)."""
    return dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)


# ── parsing: what each form means ────────────────────────────────────────────

@pytest.mark.parametrize('text,months,days,seconds', [
    ('1d', 0, 1, 0), ('7d', 0, 7, 0), ('3days', 0, 3, 0), ('1day', 0, 1, 0),
    ('1w', 0, 7, 0), ('2wk', 0, 14, 0), ('2weeks', 0, 14, 0),
    ('1h', 0, 0, 3600), ('4hr', 0, 0, 14400), ('2hours', 0, 0, 7200),
    ('30min', 0, 0, 1800), ('1minute', 0, 0, 60),
    ('45s', 0, 0, 45), ('10sec', 0, 0, 10), ('3seconds', 0, 0, 3),
    ('1mo', 1, 0, 0), ('2mos', 2, 0, 0), ('3months', 3, 0, 0),
    ('1q', 3, 0, 0), ('2qtr', 6, 0, 0), ('1quarter', 3, 0, 0),
    ('1y', 12, 0, 0), ('2yr', 24, 0, 0), ('1year', 12, 0, 0),
    ('1D', 0, 1, 0), (' 7d ', 0, 7, 0), ('1Mo', 1, 0, 0),
    # ISO 8601, as Taskwarrior stores durations
    ('P30D', 0, 30, 0), ('P14D', 0, 14, 0), ('P60D', 0, 60, 0), ('P2W', 0, 14, 0),
    ('P1M', 1, 0, 0), ('P1Y', 12, 0, 0), ('P1Y2M', 14, 0, 0), ('P1M15D', 1, 15, 0),
    ('PT1H', 0, 0, 3600), ('PT90M', 0, 0, 5400), ('PT30S', 0, 0, 30),
    ('P1DT12H', 0, 1, 43200), ('p1m', 1, 0, 0),
    # named, with 2.6.2's meanings
    ('daily', 0, 1, 0), ('weekly', 0, 7, 0), ('biweekly', 0, 14, 0), ('fortnight', 0, 14, 0),
    ('monthly', 1, 0, 0), ('bimonthly', 2, 0, 0), ('quarterly', 3, 0, 0),
    ('semiannual', 6, 0, 0), ('annual', 12, 0, 0), ('yearly', 12, 0, 0),
    ('biannual', 24, 0, 0), ('biyearly', 24, 0, 0), ('Monthly', 1, 0, 0),
])
def test_period_forms(text, months, days, seconds):
    rule = parse(text)
    assert rule.kind == 'period'
    assert (rule.months, rule.days, rule.seconds) == (months, days, seconds)


def test_the_rule_keeps_its_text():
    assert parse(' P1M ').text == 'P1M'


# ── periodic: instance n of a template ───────────────────────────────────────

def test_first_instance_is_the_anchor():
    start = L(2026, 1, 31)
    assert parse('1mo').nth(start, 1) == start


def test_monthly_from_jan_31_clamps_to_each_month_end():
    start = L(2028, 1, 31)                              # 2028 is a leap year
    got = [local(parse('1mo').nth(start, n)).date().isoformat() for n in range(1, 14)]
    assert got == ['2028-01-31', '2028-02-29', '2028-03-31', '2028-04-30', '2028-05-31',
                   '2028-06-30', '2028-07-31', '2028-08-31', '2028-09-30', '2028-10-31',
                   '2028-11-30', '2028-12-31', '2029-01-31']


def test_clamping_is_from_the_templates_day_not_the_last_instance():
    # Jan 30: Feb 28 (clamped), then back to the 30th, not stuck on the 28th
    start = L(2027, 1, 30)
    got = [local(parse('monthly').nth(start, n)).day for n in range(1, 5)]
    assert got == [30, 28, 30, 30]


def test_monthly_keeps_the_day_of_month():
    # the live bill: P30D drifts (Oct 29 for #10); 1mo lands on the 17th every month
    start = L(2026, 1, 17)
    assert local(parse('P30D').nth(start, 10)).date().isoformat() == '2026-10-14'
    assert local(parse('1mo').nth(start, 10)).date().isoformat() == '2026-10-17'


def test_yearly_from_feb_29():
    start = L(2028, 2, 29)
    got = [local(parse('1y').nth(start, n)).date().isoformat() for n in range(1, 6)]
    assert got == ['2028-02-29', '2029-02-28', '2030-02-28', '2031-02-28', '2032-02-29']


def test_quarterly_and_a_month_plus_days():
    start = L(2026, 1, 31)
    assert local(parse('quarterly').nth(start, 2)).date().isoformat() == '2026-04-30'
    # P1M15D: months first (clamped), then the days: Jan 31 -> Feb 28 -> Mar 15
    assert local(parse('P1M15D').nth(start, 2)).date().isoformat() == '2026-03-15'
    assert local(parse('P1M15D').nth(start, 3)).date().isoformat() == '2026-04-30'  # Jan 31 + 2mo + 30d


def test_monthly_across_dst_keeps_the_local_time_of_day():
    start = L(2026, 1, 15)                              # midnight EST
    july = parse('1mo').nth(start, 7)
    assert local(july) == datetime(2026, 7, 15, 0, 0)  # midnight EDT
    evening = L(2026, 1, 15, 23, 59)
    assert local(parse('1mo').nth(evening, 7)) == datetime(2026, 7, 15, 23, 59)


@pytest.mark.parametrize('text', ['1d', '7d', 'P30D', 'P14D', '2w', 'PT6H', 'P1DT12H', '45s'])
def test_day_periods_are_unchanged(text):
    """Same dates as the hook gave before: add_local(start, (n-1) x period)."""
    start = L(2026, 1, 17)
    for n in (1, 2, 5, 10, 40):
        assert parse(text).nth(start, n) == add_local(start, parse_duration(text) * (n - 1)), (text, n)


# ── chained: after a completion ──────────────────────────────────────────────

def test_chained_month_is_30_days_and_year_365():
    done = L(2026, 1, 31, 14, 30)
    assert parse('1mo').after(done) == add_local(done, timedelta(days=30))
    assert parse('P1Y').after(done) == add_local(done, timedelta(days=365))
    assert parse('P1Y1M').after(done) == add_local(done, timedelta(days=395))
    assert parse('quarterly').after(done) == add_local(done, timedelta(days=90))


@pytest.mark.parametrize('text', ['1d', 'P60D', '1w', 'PT4H', 'P1DT12H'])
def test_chained_days_are_unchanged(text):
    done = L(2026, 3, 1, 9, 0)
    assert parse(text).after(done) == add_local(done, parse_duration(text))


# ── relative fields: due-1mo ─────────────────────────────────────────────────

def test_offset_steps_calendar_months_and_clamps():
    assert local(parse('1mo').offset(L(2027, 3, 31), -1)) == datetime(2027, 2, 28)
    assert local(parse('1mo').offset(L(2027, 1, 31), +1)) == datetime(2027, 2, 28)
    assert local(parse('1y').offset(L(2028, 2, 29), -1)) == datetime(2027, 2, 28)


def test_offset_in_days_is_add_local():
    due = L(2026, 11, 5)
    assert parse('7d').offset(due, -1) == add_local(due, timedelta(days=-7))
    assert parse('PT2H').offset(due, +1) == due + timedelta(hours=2)


# ── errors: a message and a position, never a traceback ──────────────────────

@pytest.mark.parametrize('text,pos,words', [
    ('', 0, 'empty'),
    ('   ', 0, 'empty'),
    ('abc', 0, 'abc'),
    ('3x', 1, "unit 'x'"),
    ('1m', 1, '1mo'),                   # months or minutes? say which
    ('0d', 0, 'longer than zero'),
    ('P0D', 0, 'longer than zero'),
    ('1.5d', 1, '1.5d'),
    ('-1d', 0, '-1d'),
    ('7', 1, 'unit'),
    ('d', 0, 'd'),
    ('P', 1, 'P'),
    ('PT', 2, 'PT'),
    ('P1H', 2, 'H'),                    # hours need the T
    ('P1D2W', 4, 'W'),                  # out of order
    ('1d2h', 2, '2h'),                  # one unit per short form; use P1DT2H
])
def test_bad_input(text, pos, words):
    with pytest.raises(RuleError) as e:
        parse(text)
    assert e.value.pos == pos, str(e.value)
    assert words in str(e.value)


@pytest.mark.parametrize('text', ['weekdays', 'm:2tue', 'w:mon,fri', 'y:04-12', 'm:1 | m:last-fri'])
def test_position_syntax_goes_to_the_position_parser(text):
    assert parse(text).kind == 'position'          # step 2: test_rules_positions.py


def test_nth_needs_a_positive_index():
    with pytest.raises(RuleError):
        parse('1d').nth(L(2026, 1, 1), 0)


# ── the end of time ──────────────────────────────────────────────────────────

# Taskwarrior's someday / later: 9999-12-30 local. Even + 1d still fits in a datetime, but
# nothing in year 9999 is a real date, so any result there is refused.
SOMEDAY = L(9999, 12, 30)


@pytest.mark.parametrize('text', ['1mo', '1y', '1d'])
def test_too_far_ahead_is_a_rule_error(text):
    with pytest.raises(RuleError, match='too far ahead'):
        parse(text).nth(SOMEDAY, 2)
    with pytest.raises(RuleError, match='too far ahead'):
        parse(text).after(SOMEDAY)


def test_a_huge_index_is_a_rule_error():
    with pytest.raises(RuleError, match='too far ahead'):
        parse('1y').nth(L(2026, 1, 1), 10 ** 6)
