"""
Taskwarrior Enhanced Recurrence - Rules
Version: 2.11.1
Date: 2026-10-19

What a template's `r` means, and the dates it gives. Standard library only, no Taskwarrior
I/O. Step 1 of the calendar-periods plan (nb tw:docs/tw-calendar-periods-plan.md): periods.
Position rules (m:2tue, w:mon..fri) come in step 2.

    rule = parse('1mo')            # RuleError, with .pos, for anything else
    rule.nth(anchor, n)            # periodic: instance n (1 = the anchor itself)
    rule.after(completed)          # chained: the next one after a completion
    rule.offset(due, -1)           # relative fields: due-1mo

Dates in and out are naive UTC, as the hooks keep them (parse_date). Steps are taken on the
local calendar, as add_local does, so the local time of day survives DST:

- days and weeks: whole local days; hours, minutes and seconds: elapsed time. Exactly what
  add_local(anchor, (n-1) x period) gave before.
- months, quarters and years on a periodic template: calendar months, clamped to the month's
  end from the template's own day (Jan 31 -> Feb 28 -> Mar 31).
- months and years on a chained template: 30 and 365 days, as before (decision 2).

Accepted forms: Nd Nw Nh Nmin Ns Nmo Nq Ny (and their long spellings: 3days, 2weeks, 1month,
1quarter, 1year...), ISO 8601 durations as Taskwarrior stores them (P30D, P1M, P1Y2M, P1M15D,
PT1H, P1DT12H), and named periods with Taskwarrior 2.6.2's meanings (daily, weekly, biweekly,
fortnight, monthly, bimonthly, quarterly, semiannual = 6 months, annual, yearly, biannual and
biyearly = 2 years).
"""
import calendar
from datetime import datetime, timedelta, timezone

__all__ = ['RuleError', 'Rule', 'parse']

# unit -> (calendar months, days, seconds)
UNITS = {}
for _names, _value in (
        (('d', 'day', 'days'), (0, 1, 0)),
        (('w', 'wk', 'wks', 'week', 'weeks'), (0, 7, 0)),
        (('h', 'hr', 'hrs', 'hour', 'hours'), (0, 0, 3600)),
        (('min', 'mins', 'minute', 'minutes'), (0, 0, 60)),
        (('s', 'sec', 'secs', 'second', 'seconds'), (0, 0, 1)),
        (('mo', 'mos', 'month', 'months'), (1, 0, 0)),
        (('q', 'qtr', 'qtrs', 'quarter', 'quarters'), (3, 0, 0)),
        (('y', 'yr', 'yrs', 'year', 'years'), (12, 0, 0))):
    for _n in _names:
        UNITS[_n] = _value

NAMED = {
    'daily': (0, 1, 0), 'weekly': (0, 7, 0), 'biweekly': (0, 14, 0), 'fortnight': (0, 14, 0),
    'monthly': (1, 0, 0), 'bimonthly': (2, 0, 0), 'quarterly': (3, 0, 0),
    'semiannual': (6, 0, 0), 'annual': (12, 0, 0), 'yearly': (12, 0, 0),
    'biannual': (24, 0, 0), 'biyearly': (24, 0, 0),
}

ISO_DATE = {'Y': (12, 0, 0), 'M': (1, 0, 0), 'W': (0, 7, 0), 'D': (0, 1, 0)}
ISO_TIME = {'H': (0, 0, 3600), 'M': (0, 0, 60), 'S': (0, 0, 1)}

CHAINED_MONTH_DAYS = 30
CHAINED_YEAR_DAYS = 365
SOMEDAY_YEAR = 9999          # Taskwarrior's someday / later: 9999-12-30; nothing there recurs

EXAMPLES = 'like 7d, 2w, 1mo, 1y, P1M or monthly'


class RuleError(ValueError):
    """r isn't a rule we understand, or a date it gives is out of range. pos is the 0-based
    character of r where the problem is (0 when it's the whole thing)."""

    def __init__(self, message, pos=0, text=''):
        super().__init__(message)
        self.pos = pos
        self.text = text


class Rule:
    """A period: calendar months, days and seconds per step."""

    kind = 'period'

    def __init__(self, text, months, days, seconds, chained_days):
        self.text = text
        self.months = months            # calendar months per step (periodic)
        self.days = days                # whole local days per step
        self.seconds = seconds          # elapsed seconds per step
        self.chained_days = chained_days  # what the months count as on a chained template

    def __repr__(self):
        return f'Rule({self.text!r}: {self.months}mo {self.days}d {self.seconds}s)'

    def nth(self, anchor, n):
        """Instance n of a periodic template anchored at anchor (instance 1 is the anchor)."""
        if not isinstance(n, int) or n < 1:
            raise RuleError(f'instance numbers start at 1 (got {n!r})', 0, self.text)
        k = n - 1
        return _shift(anchor, self.months * k, lambda: timedelta(days=self.days * k,
                                                                 seconds=self.seconds * k),
                      self.text)

    def after(self, when):
        """The next date of a chained template completed at when (months as 30 days)."""
        return _shift(when, 0, lambda: timedelta(days=self.chained_days + self.days,
                                                 seconds=self.seconds), self.text)

    def offset(self, when, sign):
        """when moved by one period forward (sign +1) or back (-1): due-1mo, due+2w."""
        if sign not in (1, -1):
            raise ValueError('sign is +1 or -1')
        return _shift(when, sign * self.months,
                      lambda: sign * timedelta(days=self.days, seconds=self.seconds), self.text)


def _too_far(text):
    return RuleError('this date is too far ahead to recur from', 0, text)


def _add_months(wall, months):
    """wall + months, clamped to the month's last day."""
    year, month0 = divmod(wall.month - 1 + months, 12)
    year += wall.year
    if not 1 <= year < SOMEDAY_YEAR:
        raise OverflowError(year)
    month = month0 + 1
    return wall.replace(year=year, month=month,
                        day=min(wall.day, calendar.monthrange(year, month)[1]))


def _shift(dt, months, delta, text):
    """dt (naive UTC) + months on the local calendar, then delta() as add_local adds it: whole
    days on the local calendar, the rest as elapsed time. Naive UTC out."""
    try:
        if dt.year >= SOMEDAY_YEAR:
            raise OverflowError(dt)
        delta = delta()
        days = int(delta / timedelta(days=1))           # whole days, toward zero
        rest = delta - timedelta(days=days)
        wall = dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        if months:
            wall = _add_months(wall, months)
        wall += timedelta(days=days)
        out = wall.astimezone(timezone.utc).replace(tzinfo=None) + rest
    except (OverflowError, ValueError):
        raise _too_far(text) from None
    if out.year >= SOMEDAY_YEAR:
        raise _too_far(text)
    return out


def _rule(text, parts, pos=0):
    """parts: (months, days, seconds, is_years) for each piece of r."""
    months = sum(p[0] for p in parts)
    days = sum(p[1] for p in parts)
    seconds = sum(p[2] for p in parts)
    if not (months or days or seconds):
        raise RuleError(f"'{text}': a period must be longer than zero", pos, text)
    chained = sum(p[0] // 12 * CHAINED_YEAR_DAYS if p[3] else p[0] * CHAINED_MONTH_DAYS
                  for p in parts)
    return Rule(text, months, days, seconds, chained)


def parse(text):
    """The rule r says, or RuleError saying what's wrong and where."""
    raw = '' if text is None else str(text)
    lead = len(raw) - len(raw.lstrip())
    s = raw.strip()
    if not s:
        raise RuleError("r is empty: give a period, " + EXAMPLES, 0, raw)
    if any(c in s for c in ':|+') or s.lower() == 'weekdays':
        raise RuleError(f"'{s}': position rules (like m:2tue or w:mon..fri) aren't supported "
                        f"yet; use a period, {EXAMPLES}", lead, raw)

    low = s.lower()
    if low in NAMED:
        m, d, sec = NAMED[low]
        return _rule(s, [(m, d, sec, m % 12 == 0)])
    if s[0] in 'Pp':
        return _parse_iso(s, lead)
    return _parse_short(s, lead)


def _parse_short(s, lead):
    j = 0
    while j < len(s) and s[j].isdigit():
        j += 1
    if j == 0:
        if s[0] == '-':
            raise RuleError(f"'{s}': a period can't be negative", lead, s)
        raise RuleError(f"'{s}' isn't a period: use one {EXAMPLES}", lead, s)
    if j == len(s):
        raise RuleError(f"'{s}' needs a unit: {s}d, {s}w, {s}mo, {s}y...", lead + j, s)
    if s[j] in '.,':
        raise RuleError(f"'{s}': whole numbers only", lead + j, s)
    k = j
    while k < len(s) and s[k].isalpha():
        k += 1
    unit = s[j:k].lower()
    if unit == 'm':
        n = s[:j]
        raise RuleError(f"'{s}' is ambiguous: {n}mo for months, {n}min for minutes",
                        lead + j, s)
    if unit not in UNITS:
        raise RuleError(f"unknown unit '{s[j:k]}' in '{s}': use d, w, h, min, s, mo, q or y",
                        lead + j, s)
    if k < len(s):
        raise RuleError(f"unexpected '{s[k:]}' after '{s[:k]}': one unit per period here; "
                        f"for a mix use ISO 8601, like P1DT2H", lead + k, s)
    n = int(s[:j])
    m, d, sec = UNITS[unit]
    return _rule(s, [(m * n, d * n, sec * n, unit.startswith('y'))], lead)


def _parse_iso(s, lead):
    u = s.upper()
    i, parts, in_time, order = 1, [], False, 'YMWD'
    if len(u) == 1:
        raise RuleError(f"'{s}' needs at least one part, like P1M or P30D", lead + 1, s)
    while i < len(u):
        if u[i] == 'T':
            if in_time:
                raise RuleError(f"'{s}' has two T's", lead + i, s)
            in_time, order = True, 'HMS'
            i += 1
            if i == len(u):
                raise RuleError(f"'{s}' needs a time part after the T, like PT1H", lead + i, s)
            continue
        j = i
        while j < len(u) and u[j].isdigit():
            j += 1
        if j == i:
            raise RuleError(f"unexpected '{s[i]}' in '{s}': expected a number", lead + i, s)
        if j == len(u):
            raise RuleError(f"'{s}' needs a unit after {s[i:j]}", lead + j, s)
        if u[j] in '.,':
            raise RuleError(f"'{s}': whole numbers only", lead + j, s)
        unit = u[j]
        if unit not in order:
            if not in_time and unit in 'HS':
                raise RuleError(f"'{unit}' needs a T before it in '{s}', like PT1{unit}",
                                lead + j, s)
            if unit in ISO_DATE or unit in ISO_TIME:
                raise RuleError(f"'{unit}' is out of order in '{s}' (ISO 8601 order: "
                                f"P Y M W D T H M S)", lead + j, s)
            raise RuleError(f"unknown unit '{s[j]}' in '{s}'", lead + j, s)
        order = order[order.index(unit) + 1:]
        n = int(u[i:j])
        m, d, sec = (ISO_TIME if in_time else ISO_DATE)[unit]
        parts.append((m * n, d * n, sec * n, unit == 'Y' and not in_time))
        i = j + 1
    return _rule(s, parts, lead)
