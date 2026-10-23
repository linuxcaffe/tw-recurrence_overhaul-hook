"""Calendar periods in the hooks (step 3 of nb tw:docs/tw-calendar-periods-plan.md), end to
end under a real Taskwarrior in the sandbox (conftest.py), with r a string UDA.

- 1mo on a periodic template lands on the same day each month, clamped to the month's end
  (it was 30 days); chained 1mo is still 30 days from the completion.
- Position rules spawn on their dates. A template dated off its rule is moved to the rule's
  first date on or after it, with a message (open item A); one without a date is refused,
  "anchor date required" (B). Chained templates can't take one.
- r is checked by the hook now (Taskwarrior no longer does): a bad r is refused with the
  reason, on add and on modify.
- Warnings, nothing refused: a month period anchored on a short month's last day; a start in
  the past.
- Templates made while r was a duration UDA (P30D) keep their 30 days.
- The time machine and rwait:due-1mo step calendar months too.
"""
import os
import time
from datetime import datetime, timedelta, timezone

os.environ['TZ'] = 'America/Toronto'           # as the sandbox runs
time.tzset()


def local_date(stamp):
    """Taskwarrior's UTC stamp -> local date (the sandbox runs in America/Toronto)."""
    dt = datetime.strptime(stamp[:15], '%Y%m%dT%H%M%S').replace(tzinfo=timezone.utc)
    return dt.astimezone().date().isoformat()


def anchors(tw, desc):
    """Every instance's due (or scheduled), in rindex order, as local dates."""
    every = tw.instances(desc, active=False)
    return [local_date(t.get('due') or t['scheduled']) for t in every]


def finish(tw, times):
    for _ in range(times):
        tw('rtemplate.any:', '(', 'status:pending', 'or', 'status:waiting', ')', 'done')


# ── periods ──────────────────────────────────────────────────────────────────

def test_r_is_a_string_uda(tw):
    tw('add', 'rent', 'r:1mo', 'due:2030-01-31')
    assert tw.template('rent')['r'] == '1mo'                    # as typed, not P30D


def test_monthly_from_jan_31_clamps_to_month_ends(tw):
    tw('add', 'rent', 'r:1mo', 'due:2030-01-31')
    finish(tw, 12)
    assert anchors(tw, 'rent') == [
        '2030-01-31', '2030-02-28', '2030-03-31', '2030-04-30', '2030-05-31', '2030-06-30',
        '2030-07-31', '2030-08-31', '2030-09-30', '2030-10-31', '2030-11-30', '2030-12-31',
        '2031-01-31']


def test_chained_month_is_30_days_from_completion(tw):
    tw('add', 'haircut', 'r:1mo', 'ty:c', 'due:2030-01-31')
    finish(tw, 1)
    want = (datetime.now() + timedelta(days=30)).date().isoformat()
    assert anchors(tw, 'haircut')[1] == want


def test_old_duration_templates_keep_30_days(tw):
    # made while r was a duration UDA: Taskwarrior stored P30D
    tw('rc.uda.r.type=duration', 'add', 'old bill', 'r:1mo', 'due:2030-01-31')
    assert tw.template('old bill')['r'] == 'P30D'
    finish(tw, 1)
    assert anchors(tw, 'old bill') == ['2030-01-31', '2030-03-02']


def test_rwait_steps_calendar_months(tw):
    tw('add', 'taxes', 'r:1y', 'due:2030-03-31', 'rwait:due-1mo')
    [inst] = tw.instances('taxes')
    assert local_date(inst['wait']) == '2030-02-28'


def test_time_machine_steps_calendar_months(tw):
    tw('add', 'rent', 'r:1mo', 'due:2030-01-31')
    tw('status:recurring', 'mod', 'rlast:2')
    [inst] = tw.instances('rent')
    assert inst['rindex'] == '2' and local_date(inst['due']) == '2030-02-28'


# ── position rules ───────────────────────────────────────────────────────────

def test_second_tuesday_moves_an_off_rule_date_and_says_so(tw):
    out = tw('add', 'team sync', 'r:m:2tue', 'due:2030-01-03')      # a Thursday
    assert 'Moved' in out and '2030-01-08' in out and 'm:2tue' in out
    assert local_date(tw.template('team sync')['due']) == '2030-01-08'
    finish(tw, 2)
    assert anchors(tw, 'team sync') == ['2030-01-08', '2030-02-12', '2030-03-12']


def test_a_date_on_the_rule_says_nothing_about_moving(tw):
    out = tw('add', 'team sync', 'r:m:2tue', 'due:2030-01-08')
    assert 'Moved' not in out


def test_last_business_day(tw):
    tw('add', 'invoice', 'r:m:lbd', 'due:2030-08-01')
    finish(tw, 1)
    # Aug 31 2030 is a Saturday
    assert anchors(tw, 'invoice') == ['2030-08-30', '2030-09-30']


def test_position_rule_needs_an_anchor_date(tw):
    out = tw('add', 'team sync', 'r:m:2tue')
    assert 'anchor date required' in out
    assert tw.export('status:recurring') == []


def test_chained_position_rule_is_refused(tw):
    out = tw('add', 'payday', 'r:m:last-fri', 'ty:c', 'due:2030-01-25')
    assert 'periodic' in out
    assert tw.export('status:recurring') == []


# ── a chain takes no until: its instance would expire, spawn the next, expire… ──

def test_chained_until_is_refused(tw):
    out = tw('add', 'gym', 'r:2d', 'ty:c', 'due:2030-01-25', 'until:2030-01-27')
    assert 'until' in out and 'chain' in out
    assert tw.export() == []


def test_chained_relative_until_is_refused(tw):
    out = tw('add', 'gym', 'r:2d', 'ty:c', 'due:2030-01-25', 'until:due+2d')
    assert 'until' in out
    assert tw.export() == []


def test_until_added_to_a_chain_is_refused(tw):
    tw('add', 'gym', 'r:2d', 'ty:c', 'due:2030-01-25')
    out = tw('status:recurring', 'mod', 'until:due+2d')
    assert 'until' in out and 'chain' in out
    t = tw.template('gym')
    assert 'runtil' not in t and 'until' not in t


def test_a_periodic_with_until_cannot_become_a_chain(tw):
    tw('add', 'rent', 'r:1mo', 'due:2030-01-31', 'until:due+3d')
    out = tw('status:recurring', 'mod', 'ty:c')
    assert 'until' in out and 'chain' in out
    assert tw.template('rent')['type'] == 'period'


def test_a_chain_takes_wait_the_other_date_and_rend(tw):
    out = tw('add', 'gym', 'r:2d', 'ty:c', 'due:2030-01-25', 'wait:due-1d',
             'scheduled:due-2h', 'rend:2030-06-01')
    assert 'ERROR' not in out
    t = tw.template('gym')
    assert t['type'] == 'chain' and t['ranchor'] == 'due'
    assert 'rwait' in t and 'rscheduled' in t and 'rend' in t


# ── r is the hook's to check now ─────────────────────────────────────────────

def test_a_bad_r_is_refused_with_the_reason(tw):
    out = tw('add', 'oops', 'r:1m', 'due:2030-01-31')
    assert '1mo for months' in out
    assert 'Hook Error' not in out          # the reason goes where Taskwarrior looks for it
    assert tw.export() == []


def test_a_bad_r_on_modify_is_refused(tw):
    tw('add', 'rent', 'r:1mo', 'due:2030-01-31')
    out = tw('status:recurring', 'mod', 'r:m:6tue')
    assert '6tue' in out and 'Hook Error' not in out
    assert tw.template('rent')['r'] == '1mo'


def test_changing_r_to_a_position_rule_moves_the_anchor(tw):
    tw('add', 'team sync', 'r:1w', 'due:2030-01-03')
    out = tw('status:recurring', 'mod', 'r:m:2tue')
    assert 'Moved' in out
    assert local_date(tw.template('team sync')['due']) == '2030-01-08'


# ── warnings ─────────────────────────────────────────────────────────────────

def test_month_end_of_a_short_month_warns(tw):
    out = tw('add', 'rent', 'r:1mo', 'due:2030-11-30')
    assert 'month end' in out and 'r:m:-1' in out
    assert tw.template('rent')                                    # warned, not refused


def test_a_31st_or_a_mid_month_date_doesnt_warn(tw):
    assert 'month end' not in tw('add', 'a', 'r:1mo', 'due:2030-01-31')
    assert 'month end' not in tw('add', 'b', 'r:1mo', 'due:2030-11-29')


def test_a_quarterly_month_end_suggests_every_third_month(tw):
    out = tw('add', 'vat', 'r:quarterly', 'due:2030-06-30')
    assert 'r:m/3:-1' in out


def test_a_start_in_the_past_warns(tw):
    out = tw('add', 'gym', 'r:1w', 'due:2020-01-06')
    assert 'in the past' in out
    assert tw.template('gym')
