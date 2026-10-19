# Changelog — tw-recurrence_overhaul-hook

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased] — calendar periods (branch `calendar-periods`)

Plan: nb `tw:docs/tw-calendar-periods-plan.md`.

### Added
- `recurrence_rules.py` (step 1): what `r` means and the dates it gives, standard library
  only, not yet used by the hooks. `1mo`, `1q`, `1y`, `P1M`, `monthly`… step calendar months
  on periodic templates, clamped to the month's end from the template's own day (Jan 31 →
  Feb 28 → Mar 31); chained templates still count 30 / 365 days. Day and week periods give
  exactly the dates the hook gives today (checked against every active instance). Bad input
  raises `RuleError` with the position of the problem; dates in year 9999 (Taskwarrior's
  someday) are refused. `test/test_rules.py`: 103 tests.
- Position rules (step 2): `w:mon,fri`, `w:mon..fri`, `weekdays`, `w/2:mon`; `m:14`, `m:1,15`,
  `m:31` (clamped to month end), `m:-1`, `m:2tue`, `m:last-fri`, `m:5bd`, `m:lbd`, `m/3:1`;
  `y:04-12`, `y:02-29` (Feb 28 in other years), `y:apr`, `y/2:06-01`; `+` (both), `|` (either),
  parentheses; `@t=09:00,17:30`, `@nbd`, `@pbd`. Instance n is the nth occurrence from the
  anchor's date, at the anchor's local time of day unless `@t=` says otherwise. Standard
  library only (the plan said dateutil: an intersection or a roll isn't one RRULE, and a hook
  that fails to import blocks every command); the tests use dateutil's RRULE as an oracle.
  `test/test_rules_positions.py`: 165 tests.

### Changed (step 3: the hooks use the rules)
- `r` is a string UDA (`recurrence.rc`), kept as typed; the hook checks it, on add and on
  modify, and refuses a bad one with the reason (`'1m' is ambiguous: 1mo for months, 1min for
  minutes`). Templates stored as `P30D` keep their 30 days.
- Every instance date comes from `instance_dates`, which asks the rule: periodic `1mo` lands
  on the same day each month, clamped to month end; chained stays 30 days. Both time machines
  (template `rlast`, instance `rindex`) use it too; they had their own copies of the
  arithmetic.
- A position rule's template dated off the rule is moved to the rule's first date on or after
  it, with a message ("Moved due from Thu 2026-11-12 to Tue 2026-12-08, the first 'm:2tue' on
  or after it."), on add and when `r` or the date changes. A template without a date: "anchor
  date required". A position rule on a chained template is refused.
- Notes (nothing refused): a month period anchored on a short month's last day ("For every
  month end use r:m:-1"); a new template starting in the past.
- When the hook refuses a change, its reason goes to stdout, where Taskwarrior looks for it:
  every refusal used to add "Hook Error: Expected feedback from failing hook script", and a
  refused modify printed the task's JSON.

### Fixed
- `rwait:due-1mo` (and `rscheduled`, `runtil`) meant one *minute*: the unit pattern tried `m`
  before `mo`. Months and years in relative fields now step calendar months (Mar 31 − 1mo =
  Feb 28), and the pattern must match the whole value.

## [2.11.1] — 2026-10-19

Release C of the 2026-10-19 review: tidying, no change in behaviour.

### Removed
- Dead code: `delete_instance`, `check_instance_count` and `validate_instance_integrity`
  (never called; ~100 lines), and on-modify's `RECURRENCE_PROPAGATING` pass-through (nothing
  ever set it: on-exit's own modifies run with hooks off).

### Changed
- One version everywhere: VERSION, meta, README, recurrence.rc and the hook headers all say
  2.11.1 (they said 2.6.2 to 2.11.0). `rr` keeps its own version.
- Mojibake in on-add's comments (`ÃƒÂ¢Ã¢â‚¬Â…`) is back to `→` and `↔`.
- DEVELOPERS.md rewritten for how the hooks work now: one snapshot per on-exit and why
  (handleUntil), the spool as a list, what on-modify exports and when, footnote dedup, tests,
  dry runs on real data, releasing with `links=`. It linked a SPOOL_PATTERN.md that never
  existed and recommended `PYTHONPYCACHEPREFIX=/dev/null`, which recompiles the standard
  library on every hook start.
- test/: the until-expiry suite is `test_until_expiry.py` (pytest collects it; it finds the
  hooks beside itself and skips if tw's test framework isn't installed). Old notes moved to
  dev/notes/ (not published); test/logs/ is no longer tracked (.gitignore already said so).

## [2.11.0] — 2026-10-19

Release B of the 2026-10-19 review: no exports where none are needed.

### Changed
- **Completing or deleting an instance** no longer prints its own "Completed task ? -- desc
  (instance #N) / Template: task M" on top of Taskwarrior's "Completed task N 'desc'.", and no
  longer exports the template and the template's full instance history to check them (two
  exports mid-command, where an export also expires until: tasks behind Taskwarrior's back;
  its "ERROR: No pending instances" was misleading, on-exit spawns right after). on-modify now
  runs no `task` at all on a completion.
- **Modifying an instance** looks its template up only when the change needs it (rindex, or
  project/priority/tags for the "to apply to template" hint); start, stop, annotate, date and
  description edits run no export.
- **Deleting or completing a template**: on-modify's "Template N marked for deletion" is gone;
  on-exit's message says the same and how to finish the pending instance.
- `query_instances` asks Taskwarrior for active instances only, not the full history (up to
  159 deleted instances per template here).
- `pathlib` is imported only when debugging (it was ~15 ms of every hook's start, for the
  debug header alone).

on-exit after a report: one `task export` (~25 ms) on top of Python's start; ~70 ms in all.

## [2.10.0] — 2026-10-19

Release A of the 2026-10-19 review (nb `tw:recurrence-overhaul_review_—_2026-10-19.md`).

### Fixed
- **Double spawns.** The reactive pass and the reconcile pass each decided on their own, and
  every `task export` the hooks ran (hooks off) also expired `until:` tasks silently
  (Taskwarrior's handleUntil runs in export), so the two passes saw different worlds: a new
  template whose first instance had already expired got #1 and #2 at once. on-exit now takes
  one snapshot and makes one decision per template: no active instance, spawn the next.
- **until-expired periodic catch-up** took one command per missed occurrence, printing a false
  "ERROR: No pending instances exist" every other time. It now skips the occurrences whose
  until has passed and spawns one instance ("Skipped N expired occurrences of 'X'. Created…").
- **A template past rend printed "Recurrence ended" after every command, forever.** It's now
  said once, when its last instance is completed or deleted, then never again.
- **Bulk template edits synced only the last instance**: the spool held one entry. It's a
  list now (an old single-entry spool still works), and each sync message names its task
  (task shows identical footnotes once).
- **Deleting or completing a template** now says how to delete or complete its pending
  instance (that message checked for `r`, which on-modify had just removed).
- **The installer never created the on-modify symlink**, so a fresh `tw -I recurrence-overhaul`
  had no template↔instance sync and no modify-time validation (the README said it did). The meta
  now has `links=on-modify_recurrence.py:on-add_recurrence.py:hook` (make-awesome 4.13.0):
  the installer runs `ln -sfn`, records the link, and its remove deletes it.
- `recurrence.rc`: `uda.runtil` is defined (it was an orphan UDA); `report.templates.context=0`
  (was spelled `tamplates`).

### Changed
- A new template starts at `rlast:0` (none spawned yet); spawning #1 sets it to 1, as `rr`
  already assumed.
- on-exit: 497 → ~260 lines; one export per run instead of 1 + one per template (each with
  that template's whole history): ~450 ms → ~130 ms here.
- `instance_dates()` and `plan_next()` in the common module; spawn_instance uses them.

### Tests
- `test/test_hooks_sandbox.py` (11): the hooks under real Taskwarrior in a throwaway task dir.

## [2.9.1] — 2026-10-15

### Fixed
- **Daylight-saving drift.** Dates are stored in UTC and periods were added in UTC, so the
  local time of day moved by an hour whenever a period crossed a DST change: a template due
  at midnight in January gave 01:00 instances from March to November, and a summer template
  gives winter instances at 23:00 on the previous day (the wrong date). New `add_local()`
  counts whole days on the local calendar (the part shorter than a day stays elapsed time);
  periodic and chained anchors and relative wait/scheduled/until/rend all use it.
  Tests: `test/test_dst.py` (America/Toronto). Existing instances keep their dates.

## [2.7.5] — 2026-04-02

*Distributed via `tw -I recurrence-overhaul`. Internally developed as 2.7.5.*

### Fixed
- **until: auto-expiry no longer silently kills recurrence** — Taskwarrior
  auto-deletes tasks whose `until:` date has passed, but does NOT send those
  tasks to the on-exit hook via stdin. The previous reactive-only approach in
  `process_tasks()` therefore never saw these deletions and never spawned
  replacement instances. Discovered via sandbox debugging in the B+C isolated
  dev environment.

### Added
- `reconcile_orphaned_templates()` in `on-exit_recurrence.py` — runs after
  the reactive pass on every on-exit call. Queries all `status:recurring`
  templates; for any that have no pending/waiting instance, spawns the next
  one via `spawn_instance(template, rlast + 1)`. A `processed_uuids` set
  prevents double-spawning when the deletion *did* arrive on stdin (manual
  deletes, completions).
- `test/test-recurrence-until-expiry.py` — 17-test suite (2 classes)
  covering the fixed bug, chained recurrence behaviour, and type
  normalisation. Requires the awesome-taskwarrior test framework (`tw-test`).
  - `TestRecurrenceUntilExpiry` (8 tests): regression suite for the
    `until:` auto-expiry bug fixed in v2.7.5.
  - `TestRecurrenceChainedAndTypes` (9 tests): type normalisation
    (`ty:c`/`ty:ch`/`ty:chain` → `"chain"`; `ty:p` → `"period"`; default
    `"period"`), chained first-instance creation, completion-anchored due
    date, multi-step rindex increment, and `rend:` stop-spawning.

### Changed
- `on-exit_recurrence.py`: version bumped 2.7.4 → 2.7.5 / 2.8.0.
- `on-exit_recurrence.py`: `main()` no longer exits early on empty stdin —
  the reconciliation pass is useful even when no tasks were modified.

---

## [2.7.4] — 2026-02-08

### Changed
- Debug infrastructure injected by `make-awesome.py` (TW_DEBUG level support).
- Timing infrastructure injected by `make-awesome.py` (TW_TIMING support).

---

## [2.7.3] and earlier

See git log for history prior to structured changelog adoption.

---

## Dev environment note

The `include=` vs `include ` bug (taskrc syntax) was discovered during debugging
this release. Taskwarrior requires a **space** separator for `include` directives —
`include=path` is silently ignored. Affected `~/.taskrc-dev`; fixed there separately.
