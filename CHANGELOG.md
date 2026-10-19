# Changelog — tw-recurrence_overhaul-hook

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

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
