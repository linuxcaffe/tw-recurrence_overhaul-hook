# Changelog — tw-recurrence_overhaul-hook

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [2.8.0] — 2026-04-02

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
