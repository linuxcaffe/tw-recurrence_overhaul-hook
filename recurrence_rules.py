"""
Taskwarrior Enhanced Recurrence - Rules
Version: 2.11.1
Date: 2026-10-19

What a template's `r` means, and the dates it gives. Standard library only, no Taskwarrior
I/O. Steps 1 and 2 of the calendar-periods plan (nb tw:docs/tw-calendar-periods-plan.md):
periods ("this long") and position rules ("on these calendar dates", below).

    rule = parse('1mo')            # RuleError, with .pos, for anything else
    rule.nth(anchor, n)            # periodic: instance n (1 = the anchor itself)
    rule.after(completed)          # chained: the next one after a completion
    rule.offset(due, -1)           # relative fields: due-1mo (periods only)
    rule.dates(anchor, count)      # position rules: the first count dates from the anchor's date

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

__all__ = ['RuleError', 'Rule', 'PositionRule', 'parse']

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
    if any(c in s for c in ':|+()@') or s.lower() == 'weekdays':
        return _parse_position(s, lead)

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


# ── position rules: "on these calendar dates" ────────────────────────────────
#
#   atom      w:mon,fri  w:mon..fri  weekdays  w/2:mon
#             m:14  m:1,15  m:31 (clamped to month end)  m:-1  m:2tue  m:last-fri  m:5bd
#             m:lbd  m/3:1
#             y:04-12  y:01-15,07-15  y:apr  y/2:06-01
#   a + b     dates in both (+ binds tighter)        a | b   dates in either
#   ( ... )   grouping
#   @t=09:00,17:30   times of day (else the anchor's)   @nbd / @pbd   roll a weekend date to the
#                    next / previous business day (Mon-Fri)
#
# Each node lists its occurrences in a window of local dates as (date, time) pairs; the rule
# walks windows forward from the anchor's date. Standard library only: an intersection or a
# roll isn't one RRULE, and a hook that can't import something blocks every task command.

DAY_NAMES = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
DAY_FULL = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
MONTH_NAMES = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
MONTH_FULL = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
              'september', 'october', 'november', 'december']
WINDOW_DAYS = 366
NEVER_YEARS = 200            # no occurrence in this long: the rule never happens
ROLL_PAD = 3                 # a weekend date rolls at most 2 days


def _day(name):
    name = name.lower()
    if name in DAY_NAMES:
        return DAY_NAMES.index(name)
    if name in DAY_FULL:
        return DAY_FULL.index(name)
    return None


def _month(name):
    name = name.lower()
    if name in MONTH_NAMES:
        return MONTH_NAMES.index(name) + 1
    if name in MONTH_FULL:
        return MONTH_FULL.index(name) + 1
    return None


def _month_len(d):
    return calendar.monthrange(d.year, d.month)[1]


def _is_bd(d):
    return d.weekday() < 5


class _Ctx:
    """What every node needs: the anchor's local date (intervals count from it) and time of
    day (occurrences without @t= take it)."""

    def __init__(self, ref, time_of_day):
        self.ref = ref
        self.time = time_of_day


class _Atom:
    """w:, m: or y: with a list of items, an optional /N interval."""

    def __init__(self, unit, interval, tests):
        self.unit = unit
        self.interval = interval
        self.tests = tests          # predicates on a local date

    def _in_interval(self, d, ref):
        if self.interval == 1:
            return True
        if self.unit == 'w':
            weeks = ((d - timedelta(days=d.weekday())) - (ref - timedelta(days=ref.weekday()))).days // 7
            return weeks % self.interval == 0
        if self.unit == 'm':
            return ((d.year - ref.year) * 12 + d.month - ref.month) % self.interval == 0
        return (d.year - ref.year) % self.interval == 0

    def occurrences(self, ctx, start, stop):
        out, d = [], start
        while d < stop:
            if any(t(d) for t in self.tests) and self._in_interval(d, ctx.ref):
                out.append((d, ctx.time))
            d += timedelta(days=1)
        return out


class _Union:
    def __init__(self, parts):
        self.parts = parts

    def occurrences(self, ctx, start, stop):
        return sorted({o for p in self.parts for o in p.occurrences(ctx, start, stop)})


class _Both:
    """a + b: the occurrences of a on the dates b has too (times come from a)."""

    def __init__(self, parts):
        self.parts = parts

    def occurrences(self, ctx, start, stop):
        out = self.parts[0].occurrences(ctx, start, stop)
        for p in self.parts[1:]:
            dates = {d for d, _ in p.occurrences(ctx, start, stop)}
            out = [o for o in out if o[0] in dates]
        return out


class _Times:
    def __init__(self, inner, times):
        self.inner = inner
        self.times = times

    def occurrences(self, ctx, start, stop):
        dates = sorted({d for d, _ in self.inner.occurrences(ctx, start, stop)})
        return [(d, t) for d in dates for t in self.times]


class _Roll:
    """@nbd / @pbd: a weekend date moves to the next / previous business day."""

    def __init__(self, inner, step):
        self.inner = inner
        self.step = step            # +1 or -1

    def occurrences(self, ctx, start, stop):
        pad = timedelta(days=ROLL_PAD)
        out = set()
        for d, t in self.inner.occurrences(ctx, start - pad, stop + pad):
            while not _is_bd(d):
                d += timedelta(days=self.step)
            if start <= d < stop:
                out.add((d, t))
        return sorted(out)


class PositionRule:
    """On these calendar dates. Periodic templates only."""

    kind = 'position'

    def __init__(self, text, node):
        self.text = text
        self.node = node

    def __repr__(self):
        return f'PositionRule({self.text!r})'

    def _walk(self, anchor):
        """Occurrences on or after the anchor's local date, as naive UTC, in order."""
        try:
            if anchor.year >= SOMEDAY_YEAR:
                raise OverflowError(anchor)
            wall = anchor.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        except (OverflowError, ValueError):
            raise _too_far(self.text) from None
        ctx = _Ctx(wall.date(), wall.time())
        start, empty_since = wall.date(), wall.date()
        while True:
            try:
                stop = start + timedelta(days=WINDOW_DAYS)
                if stop.year >= SOMEDAY_YEAR:
                    raise OverflowError(stop)
            except OverflowError:
                raise _too_far(self.text) from None
            found = self.node.occurrences(ctx, start, stop)
            if found:
                empty_since = stop
            elif (stop - empty_since).days > NEVER_YEARS * 366:
                raise RuleError(f"'{self.text}' never happens (nothing in {NEVER_YEARS} years)",
                                0, self.text)
            for d, t in found:
                out = datetime.combine(d, t).astimezone(timezone.utc).replace(tzinfo=None)
                if out.year >= SOMEDAY_YEAR:
                    raise _too_far(self.text)
                yield out
            start = stop

    def dates(self, anchor, count):
        """The first count occurrences on or after the anchor's local date (naive UTC)."""
        out = []
        for when in self._walk(anchor):
            if len(out) == count:
                break
            out.append(when)
        return out

    def nth(self, anchor, n):
        """Instance n of a periodic template: the nth occurrence from the anchor's date."""
        if not isinstance(n, int) or n < 1:
            raise RuleError(f'instance numbers start at 1 (got {n!r})', 0, self.text)
        return self.dates(anchor, n)[-1]

    def after(self, when):
        raise RuleError(f"'{self.text}' is a position rule: those work on periodic templates "
                        f"only (ty:p); a chained template needs a period, like 1mo", 0, self.text)

    def offset(self, when, sign):
        raise RuleError(f"'{self.text}' is a position rule: relative dates take a period, "
                        f"like due-1mo", 0, self.text)


def _tokens(s, lead):
    """(kind, text, pos): '(' ')' '|' '+', ('mod', '@name=value'), ('atom', text)."""
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c.isspace():
            i += 1
        elif c in '()|+':
            out.append((c, c, lead + i))
            i += 1
        elif c == '@':
            j = i + 1
            while j < len(s) and not s[j].isspace() and s[j] not in '()|+@':
                j += 1
            out.append(('mod', s[i:j], lead + i))
            i = j
        else:
            j = i
            while j < len(s) and not s[j].isspace() and s[j] not in '()|+@':
                j += 1
            out.append(('atom', s[i:j], lead + i))
            i = j
    return out


class _Parser:
    def __init__(self, text, lead):
        self.text = text
        self.toks = _tokens(text, lead)
        self.i = 0
        self.end = lead + len(text)

    def error(self, message, pos):
        return RuleError(message, pos, self.text)

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None, self.end)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse(self):
        node = self.union()
        kind, text, pos = self.peek()
        if kind is not None:
            raise self.error(f"unexpected '{text}' in '{self.text}': join rules with + or |",
                             pos)
        return node

    def union(self):
        parts = [self.both()]
        while self.peek()[0] == '|':
            self.take()
            parts.append(self.both())
        return parts[0] if len(parts) == 1 else _Union(parts)

    def both(self):
        parts = [self.factor()]
        while self.peek()[0] == '+':
            self.take()
            parts.append(self.factor())
        return parts[0] if len(parts) == 1 else _Both(parts)

    def factor(self):
        kind, text, pos = self.take()
        if kind == '(':
            node = self.union()
            k, t, p = self.take()
            if k != ')':
                raise self.error(f"expected ')' in '{self.text}'", p)
        elif kind == 'atom':
            node = self.atom(text, pos)
        elif kind is None:
            raise self.error(f"'{self.text}' ends where a rule should be, like m:1 or w:mon",
                             pos)
        else:
            raise self.error(f"unexpected '{text}' in '{self.text}': expected a rule, like "
                             f"m:1 or w:mon", pos)
        while self.peek()[0] == 'mod':
            node = self.modifier(node, *self.take()[1:])
        return node

    def modifier(self, node, text, pos):
        low = text.lower()
        if low == '@nbd':
            return _Roll(node, 1)
        if low == '@pbd':
            return _Roll(node, -1)
        if low.startswith('@t='):
            value, vpos = text[3:], pos + 3
            if not value:
                raise self.error(f"@t= needs a time, like @t=09:00", vpos)
            times, at = [], vpos
            for part in value.split(','):
                hm = part.split(':')
                ok = (len(hm) == 2 and all(x.isdigit() for x in hm) and len(hm[1]) == 2
                      and int(hm[0]) < 24 and int(hm[1]) < 60)
                if not ok:
                    raise self.error(f"'{part}' isn't a time of day: use HH:MM, like 09:00",
                                     at)
                times.append(datetime.strptime(part, '%H:%M').time())
                at += len(part) + 1
            return _Times(node, sorted(set(times)))
        raise self.error(f"unknown modifier '{text}': use @t=HH:MM, @nbd or @pbd", pos)

    def atom(self, text, pos):
        low = text.lower()
        if low == 'weekdays':
            return _Atom('w', 1, [lambda d: d.weekday() < 5])
        unit, colon, items = low.partition(':')
        interval = 1
        if '/' in unit:
            unit, _, n = unit.partition('/')
            if not n.isdigit() or int(n) < 1:
                raise self.error(f"'{text}': the interval after / is a whole number from 1",
                                 pos + len(unit) + 1)
            interval = int(n)
        if unit not in ('w', 'm', 'y') or not colon:
            if ':' not in low:
                try:
                    parse(text)
                except RuleError:
                    pass
                else:
                    if self.peek()[0] == 'mod':
                        raise self.error("modifiers (@t=, @nbd, @pbd) work on position rules "
                                         "only, like m:1@nbd", self.peek()[2])
                    raise self.error(f"'{text}' is a period: periods can't be combined with "
                                     f"position rules", pos)
            raise self.error(f"'{text}' isn't a rule: use w:, m: or y:, like w:mon, m:14 or "
                             f"y:04-12", pos)
        start = pos + len(text) - len(items)
        if not items:
            raise self.error(f"'{text}' is empty after the colon", start)
        tests, at = [], start
        for item in items.split(','):
            if not item:
                raise self.error(f"'{text}' has an empty item", at)
            tests.append(getattr(self, '_' + unit)(item, at))
            at += len(item) + 1
        return _Atom(unit, interval, tests)

    def _w(self, item, pos):
        if '..' in item:
            a, _, b = item.partition('..')
            first, last = _day(a), _day(b)
            if first is None or last is None:
                raise self.error(f"'{item}' isn't a range of days, like mon..fri", pos)
            days = {(first + k) % 7 for k in range((last - first) % 7 + 1)}
            return lambda d: d.weekday() in days
        wd = _day(item)
        if wd is None:
            raise self.error(f"'{item}' isn't a day: use mon, tue, wed, thu, fri, sat, sun", pos)
        return lambda d: d.weekday() == wd

    def _m(self, item, pos):
        if item.lstrip('-').isdigit():
            n = int(item)
            if 1 <= n <= 31:
                return lambda d: d.day == min(n, _month_len(d))
            if -31 <= n <= -1:
                return lambda d: d.day == _month_len(d) + n + 1
            raise self.error(f"'{item}' isn't a day of the month: 1 to 31, or -1 for the last",
                             pos)
        if item == 'lbd':
            return lambda d: _is_bd(d) and not any(
                _is_bd(d + timedelta(days=k)) for k in range(1, _month_len(d) - d.day + 1))
        if item.endswith('bd') and item[:-2].isdigit():
            n = int(item[:-2])
            if n < 1:
                raise self.error(f"'{item}': business days count from 1 (1bd, 2bd...)", pos)
            return lambda d: _is_bd(d) and sum(
                _is_bd(d.replace(day=k)) for k in range(1, d.day + 1)) == n
        if item.startswith('last-') or item.startswith('last'):
            wd = _day(item[5:] if item.startswith('last-') else item[4:])
            if wd is not None:
                return lambda d: d.weekday() == wd and d.day + 7 > _month_len(d)
        if item[:1].isdigit():
            wd = _day(item[1:])
            n = int(item[0])
            if wd is not None and 1 <= n <= 5:
                return lambda d: d.weekday() == wd and (d.day - 1) // 7 == n - 1
        raise self.error(f"'{item}' isn't a day of the month: use 14, -1, 2tue, last-fri, "
                         f"5bd or lbd", pos)

    def _y(self, item, pos):
        month = _month(item)
        if month is not None:
            return lambda d: d.month == month
        mm, sep, dd = item.partition('-')
        if sep and mm.isdigit() and dd.isdigit() and 1 <= int(mm) <= 12:
            m, n = int(mm), int(dd)
            longest = calendar.monthrange(2028, m)[1]          # a leap year: Feb 29 is real
            if 1 <= n <= longest:
                return lambda d: d.month == m and d.day == min(n, _month_len(d))
        raise self.error(f"'{item}' isn't a date in the year: use MM-DD, like 04-12, or a "
                         f"month, like apr", pos)


def _parse_position(s, lead):
    return PositionRule(s, _Parser(s, lead).parse())
