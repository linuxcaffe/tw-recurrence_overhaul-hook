- Project: https://github.com/linuxcaffe/tw-recurrence_overhaul-hook
- Issues:  https://github.com/linuxcaffe/tw-recurrence_overhaul-hook/issues

# recurrence-overhaul

An enhanced recurrence system for Taskwarrior, implemented as hooks.

---

## TL;DR

- Chained recurrence — next task due relative to when you *complete* the last one
- Periodic recurrence — fixed schedule, same as built-in but without the mask problem
- Calendar-true periods — `r:1mo` lands on the same day every month (Jan 31 → Feb 28 → Mar 31),
  not every 30 days
- Position rules — `r:m:2tue` (second Tuesday), `r:m:lbd` (last business day),
  `r:w:mon..fri`, `r:y:04-12`, combined with `+` and `|`
- Relative dates — `wait:due-7d`, `sched:due-2h` just work; `rwait:due-1mo` steps a calendar month
- Attribute-agnostic — all template fields (UDAs, annotations, tags, project, priority) copy to instances automatically
- Comprehensive validation — catches errors before they become data problems
- Handy aliases — type `ty:c` instead of `type:chain`
- Three bundled reports — `templates`, `recurring`, `instances`
- Taskwarrior 2.6.2 only — replaces built-in recurrence entirely

---

## Why this exists

Taskwarrior's built-in recurrence has real limitations: it only supports
periodic (time-based) recurrence, the mask system grows unbounded, and there's
no way to say "mow the lawn 7 days after I actually do it." Nor "the second
Tuesday" or "the last business day"; and a duration such as `1mo` is stored as
30 days, so a monthly bill drifts a few days earlier every month.

This hook system replaces built-in recurrence with a template-instance model.
Templates store the recurrence rules. Instances are the actual tasks you see
and complete. When you complete an instance, the next one spawns automatically
with the correct dates.

Based on the
[Taskwarrior Recurrence RFC](https://djmitche.github.io/taskwarrior/rfcs/recurrence.html).

---

## Core concepts

- **Template**
  A task with `status:recurring` that stores the recurrence rules. Templates
  don't appear in your normal task list — they're the blueprint.

- **Instance**
  A regular pending task linked to a template via `rtemplate`. This is what
  you see, work on, and complete. Completing or deleting it spawns the next.

- **Chained recurrence** (`ty:c`)
  Next instance due relative to completion time. Good for habits, chores,
  exercise — anything where "every N days" means "after I actually do it."

- **Periodic recurrence** (`ty:p`, default)
  Fixed schedule from the template. Instance #N is the template's date plus
  N−1 periods (calendar months for `1mo`), or the rule's Nth date for a
  position rule, regardless of when you complete the others. Good for bills,
  meetings, appointments.

- **Rule**
  The template's `r`: a period ("every 2 weeks", `r:2w`) or a position rule
  ("on the second Tuesday", `r:m:2tue`). See [The r rule](#the-r-rule).

- **Anchor**
  The date field that recurrence calculations are based on — either `due`
   or `scheduled`.

- **Relative dates**
  Wait, scheduled, and until dates expressed as offsets from the anchor:
  `wait:due-7d`, `sched:due-2h`, `until:due+30d`. These are stored on
  the template and recalculated for each instance.

---

## Installation

### Option 1) Download and run the install file
```bash
chmod +x recurrence-overhaul.install  # then run it
recurrence-overhaul.install
```
copies the hooks, the two library files, `rr`, the rc config and the README
to directories under ~/.task, sets permissions and makes the on-modify symlink

### Option 2) Via [awesome-taskwarrior](https://github.com/linuxcaffe/awesome-taskwarrior)

```bash
tw -I recurrence-overhaul
```

### Option 3) Manual

```bash
cd ~/.task/hooks

# Copy the two hooks and the two libraries
cp on-add_recurrence.py on-exit_recurrence.py recurrence_common_hook.py recurrence_rules.py .

# Make the hooks executable (the libraries needn't be)
chmod +x on-add_recurrence.py on-exit_recurrence.py

# Create the on-modify symlink
ln -s on-add_recurrence.py on-modify_recurrence.py

# Install configuration, and the rr tool
cp recurrence.rc ~/.task/config/
cp rr ~/.task/scripts/ && chmod +x ~/.task/scripts/rr
```

Add to `~/.taskrc`:

```ini
include ~/.task/config/recurrence.rc
```

Verify:

```bash
task _get rc.uda.r.type   # string
task diag                 # see the hooks section
```

---

## Usage

### Creating recurring tasks

**Chained** — next due relative to completion:

```bash
task add "Mow lawn" ty:c r:7d due:tomorrow
task add "Gym workout" ty:c r:3d due:tomorrow +health
task add "Meditate" ty:c r:1d due:today +habits
```

**Periodic** — fixed schedule (default type, `ty:p` optional):

```bash
task add "Pay rent" r:1mo due:1st
task add "Standup" r:1w due:monday +work
task add "Quarterly report" r:m/3:-1 due:eoq +work
task add "Team sync" r:m:2tue due:2030-01-08 +work
```

**With relative dates:**

```bash
task add "Credit card" r:1mo due:15th wait:due-7d priority:H +finance
task add "Week review" r:1w due:friday sched:due-1h +review
```

**With an end date:**

```bash
task add "Beach cleanup" r:1w due:2025-06-01 rend:2025-08-31 +volunteer
```

**Using scheduled as anchor:**

```bash
task add "Daily standup" ty:c r:1d sched:tomorrow+9hrs wait:sched-90min
```

### The `r` rule

`r` is kept as you type it (a string UDA), and the hook reads it. It is either a **period**
("this long") or a **position rule** ("on these calendar dates").

**Periods:** `1d`, `2w`, `12h`, `30min`, `1mo`, `1q`, `1y` (and the spelled-out `3days`,
`2weeks`, `1month`…), ISO 8601 (`P30D`, `P1M`, `P1M15D`, `PT1H`), or a name: `daily`,
`weekly`, `biweekly`/`fortnight`, `monthly`, `bimonthly`, `quarterly`, `semiannual` (6 months),
`annual`/`yearly`, `biannual`/`biyearly` (2 years). `1m` is refused as ambiguous: write `1mo`
or `1min`.

On a **periodic** template, months and years are calendar months: `r:1mo due:2030-01-31` gives
Jan 31, Feb 28, Mar 31, Apr 30… (clamped to the month's end, from the template's own day, so it
never gets stuck on the 28th). On a **chained** template a month is 30 days and a year 365.
Days and weeks keep the local time of day across daylight-saving changes.

**Position rules** (periodic templates only):

| Rule | Means |
|---|---|
| `w:mon,fri`, `w:mon..fri`, `weekdays` | those weekdays |
| `w/2:mon` | every second week, counted from the template's week |
| `m:14`, `m:1,15` | those days of the month; `m:29`–`m:31` become the month's end in shorter months |
| `m:-1` | the last day of the month (`m:-2` the day before) |
| `m:2tue`, `m:last-fri`, `m:1wed,3fri` | the nth / last weekday of the month |
| `m:5bd`, `m:lbd` | the 5th / last business day (Mon–Fri) |
| `m/3:1` | every third month, on the 1st |
| `y:04-12`, `y:01-15,07-15` | those dates each year (`y:02-29` is Feb 28 in other years) |
| `y:apr` | every day in April (for combining) |
| `y/2:06-01` | every second year |

Combine with `+` (both: `w:mon,wed,fri + y:apr`) and `|` (either: `m:1 | m:last-fri`); `+`
binds tighter, and parentheses group. Modifiers: `@t=09:00` or `@t=09:00,17:30` sets the time
of day (otherwise the template's), `@nbd` / `@pbd` moves a weekend date to the next / previous
business day: `m:1@nbd`.

A template whose date isn't on its rule is moved to the rule's first date after it, and the
hook says so. A position rule needs a date to start from: `due:` or `sched:`.

**Relative dates use the template fields.** Taskwarrior computes `wait:due-1mo` itself, as 30
days, before the hook sees it. To step calendar months, give the template field directly:
`rwait:due-1mo`, `rscheduled:due-2w`, `runtil:due+1mo`.

**Taskwarrior's named dates as a start:** use the forward-looking ones, such as `1st`, `15th`,
`monday`, `january`, `eom`, `eoq`. `som`, `sow` and `soy` are already past, so the first
instance would be overdue at once (the hook notes it). `eom` pairs with `r:m:-1` and `eoq` with
`r:m/3:-1`: with `r:1mo`, a template started on the 30th repeats on the 30th, and the hook says
so. `easter` resolves to a date, but `r:1y` repeats that date, not the feast.

Templates made before `r` was a string keep their stored period (`P30D` stays 30 days); change
`r` to `1mo` to move one to calendar months.

### Completing and deleting

```bash
task 42 done       # Completes instance, spawns next automatically
task 42 delete     # Deletes instance, spawns next automatically
```

Both completion and deletion trigger the next instance. The system never
leaves you without a pending instance for an active template.

### Viewing recurrence

Three bundled reports:

```bash
task templates     # All recurrence templates
task recurring     # Templates AND their instances together
task instances     # All instances (or filter by template)
```

The `R` column in reports shows an indicator for recurring instances.

### Modifying templates

Changes to recurrence fields auto-sync to the current instance:

```bash
task 5 modify r:14d           # Change period
task 5 modify ty:c            # Switch to chained
task 5 modify ranchor:sched   # Change anchor to scheduled
task 5 modify rlast:10        # Time machine — jump to instance #10
```

Changes to non-recurrence fields show a suggested command:

```bash
task 5 modify priority:H      # Template updated
# "To apply to current instance: task 42 mod priority:H"
```

### Modifying instances

```bash
task 42 modify rindex:5       # Time machine — recalculates dates
```

Changing `rindex` on an instance auto-syncs `rlast` on the template and
recalculates all dates. This has basically no effect on chain type.

---

## Aliases

The hook accepts short, friendly names and translates them internally.
You never need to type the `r`-prefixed field names directly.

| You type | Hook stores | Notes |
|----------|-------------|-------|
| `ty:c` | `type:chain` | Also: `ty:ch`, `ty:chai`, `ty:chain` |
| `ty:p` | `type:period` | Also: `ty:pe`, `ty:per`. Default if omitted |
| `wait:due-2d` | `rwait:due-172800s` | Kept as an offset from the anchor |
| `wait:2026-03-15` | `rwait:due-Xs` | Absolute dates convert to offsets too |
| `sched:due-1h` | `rscheduled:due-3600s` | Same conversion |
| `until:due+7d` | `runtil:due+604800s` | Same conversion |

Taskwarrior turns `wait:`, `sched:` and `until:` into dates before the hook sees
them, and the hook stores each as an offset from the anchor, in seconds, so every
instance gets the same offset from its own date. For calendar months, type the
template field yourself: `rwait:due-1mo` is kept as typed and steps back a
calendar month from each instance's date (`wait:due-1mo` would be 30 days).

---

## Recurrence fields

| Field | Where | Purpose |
|-------|-------|---------|
| `r` | Template | The rule: a period (`1d`, `1w`, `1mo`, `quarterly`) or a position rule (`m:2tue`); see [The r rule](#the-r-rule) |
| `type` | Template | `chain` or `period` (default: period) |
| `ranchor` | Template | Anchor field: `due` or `sched` (default: due) |
| `rlast` | Template | Index of last spawned instance |
| `rend` | Template | Stop creating instances after this date |
| `rwait` | Template | Relative wait offset: `due-7d`, `due-1mo` |
| `rscheduled` | Template | Relative scheduled offset: `due-2h` |
| `runtil` | Template | Relative until offset: `due+30d` |
| `rtemplate` | Instance | UUID of parent template |
| `rindex` | Instance | This instance's sequence number |

---

## Validation

The hook validates input and blocks errors before they corrupt data.

**Blocked with error:**
- Template without anchor date: "anchor date required" (`due:` or `sched:`)
- Template with wait date after anchor
- Template with until date before anchor
- An `r` the hook can't read (with the reason: `'1m' is ambiguous: 1mo for months, 1min for
  minutes`)
- A position rule on a chained template
- `rend` date in the past
- Adding `r` to an existing instance
- Changing `rtemplate` on an instance

**Corrected, with a message:**
- A position rule's template dated off its rule moves to the rule's first date
  after it: "Moved due from Thu 2026-11-12 to Tue 2026-12-08, the first 'm:2tue'
  on or after it."

**Noted (nothing changed):**
- A month period started on a short month's last day (`r:1mo due:2026-11-30`
  repeats on the 30th): "For every month end use r:m:-1"
- A new template starting in the past: its first instance is overdue at once

**Warned and cleaned up:**
- Legacy fields (`recur`, `mask`, `imask`, `parent`) — stripped automatically
- Instance-only fields on templates — removed
- Template-only fields on instances — removed

---

## How it works

### Architecture

Four files, one symlink:

| File | Hook type | Purpose |
|------|-----------|---------|
| `on-add_recurrence.py` | on-add | Template creation, validation |
| `on-modify_recurrence.py` | on-modify | Symlink → on-add. Template/instance modification |
| `on-exit_recurrence.py` | on-exit | Instance spawning, spool processing |
| `recurrence_common_hook.py` | library | Shared utilities, validation, spawn logic |
| `recurrence_rules.py` | library | What `r` means: periods and position rules, and the dates they give |

### Template-instance lifecycle

```
1. User: task add "Mow lawn" ty:c r:7d due:tomorrow
2. on-add: Creates template (status:recurring, rlast:0 — none spawned yet)
3. on-exit: Sees new template, spawns instance #1
4. User: task 42 done
5. on-exit: Sees completed instance, spawns instance #2
   - Chain: due = completion_time + 7d (a month counts as 30 days)
   - Period: due = template_due + (N−1) × period (calendar months for 1mo),
     or the rule's Nth date (r:m:2tue)
6. Repeat from step 4
```

### Spool file pattern

Template modifications can't directly update instances during on-modify
(Taskwarrior holds a file lock). Instead, on-modify writes a JSON spool
file (`~/.task/recurrence_propagate.json`) and on-exit processes it after
the lock is released.

### Attribute-agnostic copying

When spawning instances, everything copies from the template except:
system fields (`uuid`, `id`, `entry`, `modified`, `status`), legacy fields
(`recur`, `mask`), template-only fields (`r`, `type`, `rlast`), and
instance-only fields (`rtemplate`, `rindex`). All UDAs, annotations,
dependencies, tags, project, and priority carry over automatically.

---

## Debug mode

```bash
export DEBUG_RECURRENCE=1
task add "Test" ty:c r:1d due:tomorrow
tail -f ~/.task/recurrence_debug.log
```

Debug output shows template creation, alias expansion, validation,
instance spawning, date calculations, and field copying. Useful for
understanding exactly what happened and why.

---

## Troubleshooting

**Hooks not running?**

```bash
task show | grep hooks     # Should show hooks=1
ls -la ~/.task/hooks/on-*  # on-add and on-exit executable; on-modify a symlink to on-add
```

**No instances created?**

```bash
task templates              # Verify template exists
export DEBUG_RECURRENCE=1
task list                   # Trigger on-exit hook
cat ~/.task/recurrence_debug.log
```

**Wrong due dates?**

For chained: check completion time in debug log — next due = completion + period.
For periodic: verify template's anchor date — instance N due = template + (N-1) × period,
or the rule's Nth date for a position rule.

**A monthly task still drifts a few days a month?**

Its template was made before 3.0.1, when Taskwarrior stored `r:1mo` as `P30D`
(30 days). Change it: `task <template> mod r:1mo`. The current instance moves
to its calendar date at once, and later ones follow.

**"Invalid recurrence r:…"?**

The hook reads `r` itself and says what it couldn't read, for example
`'1m' is ambiguous: 1mo for months, 1min for minutes`. See [The r rule](#the-r-rule).

**Legacy field warnings?**

Taskwarrior 2.6.2 synthesizes legacy fields (`rtype`) into JSON passed to
hooks for `status:recurring` tasks. These are silently stripped. You'll only
see a warning if you explicitly add a legacy field like `recur:weekly`.

---

## Project status

Active development. Core functionality — template creation, instance spawning,
chained and periodic recurrence, calendar periods and position rules (3.0.1),
validation, attribute-agnostic copying, and bidirectional sync — is working
and in daily use.

---

## Further reading

- [DEVELOPERS.md](DEVELOPERS.md) — architecture, internals, hook API details
- [Taskwarrior Recurrence RFC](https://djmitche.github.io/taskwarrior/rfcs/recurrence.html) — the design this implements

---

## Metadata

- License: MIT
- Language: Python
- Requires: Taskwarrior 2.6.2, Python 3
- Files: 2 hooks + 2 libraries + 1 symlink + 1 config + `rr`
- Version: 3.0.1
