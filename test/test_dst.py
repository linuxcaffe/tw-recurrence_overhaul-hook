"""Recurrence across a daylight-saving change, in a non-UTC zone.

    python3 -m pytest -q test/test_dst.py

Dates are stored in UTC. Adding whole days in UTC moves the local time of day by an hour when
the period crosses a DST change: a template due at local midnight in January (T050000Z, EST)
gave an October instance at 01:00 EDT, and a summer template gives winter instances at 23:00
the day before. Whole days now step on the local calendar; shorter parts stay absolute.
"""
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

os.environ['TZ'] = 'America/Toronto'
time.tzset()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from recurrence_common_hook import add_local, parse_date, parse_relative_date  # noqa: E402

JAN17_MIDNIGHT = parse_date('20260117T050000Z')     # 00:00 EST
JUL01_MIDNIGHT = parse_date('20260701T040000Z')     # 00:00 EDT


def test_winter_to_summer_keeps_midnight():
    assert add_local(JAN17_MIDNIGHT, timedelta(days=270)) == parse_date('20261014T040000Z')


def test_summer_to_winter_keeps_the_date():
    # 23:00 on Dec 26 before the fix: the wrong day
    assert add_local(JUL01_MIDNIGHT, timedelta(days=180)) == parse_date('20261228T050000Z')


def test_within_one_offset_is_plain_addition():
    assert add_local(JAN17_MIDNIGHT, timedelta(days=7)) == JAN17_MIDNIGHT + timedelta(days=7)


def test_sub_day_part_is_absolute():
    # Mar 8 2026, 01:30 EST + 1 h = 03:30 EDT (02:xx doesn't exist)
    start = parse_date('20260308T063000Z')
    assert add_local(start, timedelta(hours=1)) == parse_date('20260308T073000Z')


def test_negative_days():
    # wait = due - 7 days, across the November change: still local midnight
    due = parse_date('20261105T050000Z')             # Nov 5 00:00 EST
    assert add_local(due, timedelta(days=-7)) == parse_date('20261029T040000Z')


def test_relative_date_uses_local_days():
    due = parse_date('20261105T050000Z')
    assert parse_relative_date('due-604800s', due) == parse_date('20261029T040000Z')
    assert parse_relative_date('due-7d', due) == parse_date('20261029T040000Z')
