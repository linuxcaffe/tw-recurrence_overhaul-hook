"""recurrence_rules, step 2 of the calendar-periods plan: position rules, "on these calendar
dates", for periodic templates.

    python3 -m pytest -q test/test_rules_positions.py

- Every atom against dateutil's RRULE as an oracle (skipped without dateutil; the module
  itself uses only the standard library): the first 24 dates from several starts.
- Hand-checked tables for what RRULE can't say in one rule: @nbd / @pbd rolls, two times a
  day, intersections with a list.
- Instance n is the nth occurrence on or after the template's anchor date, at the anchor's
  local time of day unless @t= says otherwise; DST keeps the local time.
- Bad rules raise RuleError with the position of the problem.
"""
import os
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

os.environ['TZ'] = 'America/Toronto'
time.tzset()
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from recurrence_rules import RuleError, parse  # noqa: E402


def L(y, mo, d, h=0, mi=0):
    """Local Toronto wall time -> naive UTC, as Taskwarrior stores it."""
    return datetime(y, mo, d, h, mi).astimezone(timezone.utc).replace(tzinfo=None)


def local(dt):
    return dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)


def days(text, anchor, count=6):
    """The first count occurrences' local dates, as ISO strings."""
    return [local(d).date().isoformat() for d in parse(text).dates(anchor, count)]


# ── the oracle: RRULE, for everything it can say ─────────────────────────────

def rrule_cases():
    try:
        from dateutil.rrule import (DAILY, FR, MO, MONTHLY, SA, SU, TH, TU, WE, WEEKLY,
                                    YEARLY)
    except ImportError:
        return []
    bd = (MO, TU, WE, TH, FR)
    return [
        ('w:mon,fri', dict(freq=WEEKLY, byweekday=(MO, FR))),
        ('w:mon..fri', dict(freq=WEEKLY, byweekday=bd)),
        ('weekdays', dict(freq=WEEKLY, byweekday=bd)),
        ('w:sat..mon', dict(freq=WEEKLY, byweekday=(SA, SU, MO))),
        ('w:sun', dict(freq=WEEKLY, byweekday=SU)),
        ('w/2:mon', dict(freq=WEEKLY, interval=2, byweekday=MO, wkst=MO)),
        ('w/3:tue,thu', dict(freq=WEEKLY, interval=3, byweekday=(TU, TH), wkst=MO)),
        ('m:14', dict(freq=MONTHLY, bymonthday=14)),
        ('m:1,15', dict(freq=MONTHLY, bymonthday=(1, 15))),
        ('m:31', dict(freq=MONTHLY, bymonthday=(28, 29, 30, 31), bysetpos=-1)),
        ('m:30', dict(freq=MONTHLY, bymonthday=(28, 29, 30), bysetpos=-1)),
        ('m:-1', dict(freq=MONTHLY, bymonthday=-1)),
        ('m:-3', dict(freq=MONTHLY, bymonthday=-3)),
        ('m:2tue', dict(freq=MONTHLY, byweekday=TU(2))),
        ('m:last-fri', dict(freq=MONTHLY, byweekday=FR(-1))),
        ('m:1wed,3fri', dict(freq=MONTHLY, byweekday=(WE(1), FR(3)))),
        ('m:5tue', dict(freq=MONTHLY, byweekday=TU(5))),      # months without one skip
        ('m:5bd', dict(freq=MONTHLY, byweekday=bd, bysetpos=5)),
        ('m:1bd', dict(freq=MONTHLY, byweekday=bd, bysetpos=1)),
        ('m:lbd', dict(freq=MONTHLY, byweekday=bd, bysetpos=-1)),
        ('m/3:1', dict(freq=MONTHLY, interval=3, bymonthday=1)),
        ('m/2:last-fri', dict(freq=MONTHLY, interval=2, byweekday=FR(-1))),
        ('y:04-12', dict(freq=YEARLY, bymonth=4, bymonthday=12)),
        ('y:01-15,07-15', dict(freq=YEARLY, bymonth=(1, 7), bymonthday=15)),
        ('y:02-29', dict(freq=YEARLY, bymonth=2, bymonthday=(28, 29), bysetpos=-1)),
        ('y:apr', dict(freq=DAILY, bymonth=4)),
        ('y/2:06-01', dict(freq=YEARLY, interval=2, bymonth=6, bymonthday=1)),
        ('w:mon,wed,fri + y:apr', dict(freq=DAILY, bymonth=4, byweekday=(MO, WE, FR))),
        ('m:13 + w:fri', dict(freq=MONTHLY, bymonthday=13, byweekday=FR)),
    ]


ORACLE = rrule_cases()
STARTS = [(2026, 11, 1, 0, 0), (2027, 1, 31, 9, 30), (2028, 2, 29, 23, 59), (2026, 3, 8, 2, 30)]


@pytest.mark.skipif(not ORACLE, reason='python-dateutil not installed (only the tests use it)')
@pytest.mark.parametrize('text,kw', ORACLE, ids=[c[0] for c in ORACLE])
@pytest.mark.parametrize('start', STARTS, ids=lambda s: '%04d-%02d-%02d' % s[:3])
def test_atoms_match_rrule(text, kw, start):
    from dateutil.rrule import rrule
    dtstart = datetime(*start)
    want = [d.date().isoformat() for d in rrule(dtstart=dtstart.replace(hour=0, minute=0),
                                                count=24, **kw)]
    assert days(text, L(*start), 24) == want


def test_unions_match_an_rruleset():
    pytest.importorskip('dateutil')
    from dateutil.rrule import FR, MONTHLY, rrule, rruleset
    start = datetime(2026, 11, 1)
    rs = rruleset()
    rs.rrule(rrule(MONTHLY, dtstart=start, bymonthday=1))
    rs.rrule(rrule(MONTHLY, dtstart=start, byweekday=FR(-1)))
    want = [d.date().isoformat() for d in list(rs)[:24]]
    assert days('m:1 | m:last-fri', L(2026, 11, 1), 24) == want


# ── hand-checked: what one RRULE can't say ───────────────────────────────────

def test_second_tuesday_from_november_2026():
    assert days('m:2tue', L(2026, 11, 1), 4) == ['2026-11-10', '2026-12-08', '2027-01-12',
                                                 '2027-02-09']


def test_31st_clamps_to_month_end():
    assert days('m:31', L(2027, 1, 1)) == ['2027-01-31', '2027-02-28', '2027-03-31',
                                           '2027-04-30', '2027-05-31', '2027-06-30']


def test_last_business_day_across_weekend_month_ends():
    # Oct 31 2026 is a Saturday, Jan 31 2027 a Sunday
    assert days('m:lbd', L(2026, 10, 1), 4) == ['2026-10-30', '2026-11-30', '2026-12-31',
                                                '2027-01-29']


def test_nbd_rolls_a_weekend_forward():
    # Aug 1 2026 is a Saturday, Nov 1 a Sunday
    assert days('m:1@nbd', L(2026, 7, 1)) == ['2026-07-01', '2026-08-03', '2026-09-01',
                                              '2026-10-01', '2026-11-02', '2026-12-01']


def test_pbd_rolls_a_weekend_back():
    assert days('m:-1@pbd', L(2026, 1, 1)) == ['2026-01-30', '2026-02-27', '2026-03-31',
                                               '2026-04-30', '2026-05-29', '2026-06-30']


def test_a_roll_into_the_window_counts():
    # anchor Mon Aug 3: the Sat Aug 1 occurrence rolls forward to it
    assert days('m:1@nbd', L(2026, 8, 3), 2) == ['2026-08-03', '2026-09-01']


def test_rolled_duplicates_are_one_occurrence():
    # Sat and Sun both roll to Monday: one instance, not two
    assert days('w:sat,sun@nbd', L(2026, 11, 1), 3) == ['2026-11-02', '2026-11-09',
                                                        '2026-11-16']


def test_two_times_a_day():
    got = [local(d) for d in parse('w:mon@t=09:00,17:30').dates(L(2026, 11, 2), 4)]
    assert got == [datetime(2026, 11, 2, 9, 0), datetime(2026, 11, 2, 17, 30),
                   datetime(2026, 11, 9, 9, 0), datetime(2026, 11, 9, 17, 30)]


def test_time_on_a_group_and_on_an_atom():
    at_nine = [local(d) for d in parse('(m:1 | m:15)@t=09:00').dates(L(2026, 11, 1), 3)]
    assert at_nine == [datetime(2026, 11, 1, 9), datetime(2026, 11, 15, 9),
                       datetime(2026, 12, 1, 9)]
    mixed = [local(d) for d in parse('m:1@t=08:00 | m:15').dates(L(2026, 11, 1, 18), 3)]
    assert mixed == [datetime(2026, 11, 1, 8), datetime(2026, 11, 15, 18),
                     datetime(2026, 12, 1, 8)]


def test_plus_binds_tighter_than_bar():
    # m:1 | (w:fri + y:apr), not (m:1 | w:fri) + y:apr
    assert days('m:1 | w:fri + y:apr', L(2027, 3, 1), 7) == [
        '2027-03-01', '2027-04-01', '2027-04-02', '2027-04-09', '2027-04-16', '2027-04-23',
        '2027-04-30']
    assert days('(m:1 | w:fri) + y:apr', L(2027, 3, 1), 3) == ['2027-04-01', '2027-04-02',
                                                                 '2027-04-09']


def test_spaces_and_case_dont_matter():
    assert days('M:2TUE', L(2026, 11, 1), 2) == days('m:2tue', L(2026, 11, 1), 2)
    assert days(' w:mon|w:fri ', L(2026, 11, 1), 4) == days('w:mon,fri', L(2026, 11, 1), 4)


def test_full_day_and_month_names():
    assert days('w:monday', L(2026, 11, 1), 2) == days('w:mon', L(2026, 11, 1), 2)
    assert days('y:april', L(2027, 1, 1), 2) == ['2027-04-01', '2027-04-02']


# ── instances: nth from the template's anchor ────────────────────────────────

def test_instance_1_is_the_first_occurrence_from_the_anchor_date():
    rule = parse('m:2tue')
    assert local(rule.nth(L(2026, 11, 10), 1)) == datetime(2026, 11, 10)
    assert local(rule.nth(L(2026, 11, 10), 3)) == datetime(2027, 1, 12)
    # an anchor off the rule starts at the next occurrence (open item A decides what to say)
    assert local(rule.nth(L(2026, 11, 12), 1)) == datetime(2026, 12, 8)


def test_the_anchors_time_of_day_carries_across_dst():
    rule = parse('m:1')
    anchor = L(2026, 1, 1, 9, 0)                        # 09:00 EST
    assert local(rule.nth(anchor, 7)) == datetime(2026, 7, 1, 9, 0)   # 09:00 EDT


def test_intervals_count_from_the_anchor():
    # every second week from the anchor's week, not from some epoch
    a = days('w/2:mon', L(2026, 11, 2), 3)
    b = days('w/2:mon', L(2026, 11, 9), 3)
    assert a == ['2026-11-02', '2026-11-16', '2026-11-30']
    assert b == ['2026-11-09', '2026-11-23', '2026-12-07']


def test_kind_and_text():
    rule = parse(' m:2tue ')
    assert rule.kind == 'position' and rule.text == 'm:2tue'


def test_chained_and_offsets_are_periods_only():
    with pytest.raises(RuleError, match='periodic'):
        parse('m:2tue').after(L(2026, 11, 1))
    with pytest.raises(RuleError, match='period'):
        parse('w:mon').offset(L(2026, 11, 1), -1)


def test_nth_needs_a_positive_index():
    with pytest.raises(RuleError):
        parse('m:1').nth(L(2026, 1, 1), 0)


def test_a_rule_that_never_happens():
    with pytest.raises(RuleError, match='never'):
        parse('w:sat + m:lbd').nth(L(2026, 1, 1), 1)


def test_the_end_of_time():
    with pytest.raises(RuleError, match='too far ahead'):
        parse('m:1').nth(L(9999, 12, 1), 2)
    with pytest.raises(RuleError, match='too far ahead'):
        parse('y:01-01').nth(L(9998, 1, 1), 3)


def test_no_dateutil_needed():
    code = ('import sys; sys.path.insert(0, %r); import recurrence_rules as r; '
            'from datetime import datetime; '
            'r.parse("m:2tue | w:mon..fri@nbd + y:apr").nth(datetime(2026, 1, 1), 5); '
            'print("dateutil" in sys.modules)' % str(REPO))
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert out.stdout.strip() == 'False', out.stderr


# ── errors: a message and a position ─────────────────────────────────────────

@pytest.mark.parametrize('text,pos,words', [
    ('m:', 2, 'empty'),
    ('m:32', 2, '32'),
    ('m:0', 2, '0'),
    ('m:-32', 2, '-32'),
    ('m:1,,15', 4, 'empty'),
    ('m:6tue', 2, '6tue'),
    ('m:2xyz', 2, '2xyz'),
    ('m:0bd', 2, '0bd'),
    ('w:funday', 2, 'funday'),
    ('w:mon..', 2, 'mon..'),
    ('w/0:mon', 2, 'interval'),
    ('y:02-30', 2, '02-30'),
    ('y:13-01', 2, '13-01'),
    ('y:04-31', 2, '04-31'),
    ('y:smarch', 2, 'smarch'),
    ('x:1', 0, 'x:1'),
    ('m:1 |', 5, 'end'),
    ('| m:1', 0, '|'),
    ('(m:1', 4, ')'),
    ('m:1)', 3, ')'),
    ('m:1 w:mon', 4, 'w:mon'),
    ('m:1@t=25:00', 6, '25:00'),
    ('m:1@t=9', 6, '9'),
    ('m:1@t=', 6, 'time'),
    ('m:1@xyz', 3, '@xyz'),
    ('1mo@nbd', 3, 'position'),
    ('1mo + m:1', 0, '1mo'),
])
def test_bad_rules(text, pos, words):
    with pytest.raises(RuleError) as e:
        parse(text)
    assert e.value.pos == pos, str(e.value)
    assert words in str(e.value)
