# Taskwarrior Enhanced Recurrence - Developer Documentation

**Version:** 2.11.1
**Last Updated:** 2026-10-19

How the hooks work and what will break if you don't know it. User documentation is in
[README.md](README.md), history in [CHANGELOG.md](CHANGELOG.md).

---

## Files

```
~/.task/hooks/
├── on-add_recurrence.py       (executable) templates: create, validate, modify; writes the spool
├── on-modify_recurrence.py    (symlink)    → on-add_recurrence.py (the installer makes it)
├── on-exit_recurrence.py      (executable) applies the spool, spawns instances
├── recurrence_common_hook.py  (library, not executable) dates, validation,
│                                           instance_dates / plan_next / spawn_instance
└── recurrence_rules.py        (library, not executable) what r means: parse(r) -> a period
                                            or a position rule; nth / after / offset / dates
~/.task/scripts/rr                          the recurrence report/repair tool
~/.task/config/recurrence.rc                UDAs and reports
```

on-add and on-modify are one script, told apart by how many lines arrive on stdin (one for an
add, two for a modify).

## Data model

**Template** (`status:recurring`): `r` (the rule, a string UDA: see README, "The r rule";
`recurrence_rules.parse` reads it and the hooks refuse what it can't), `type` (chain | period), `ranchor` (due |
sched), `rlast` (the last index spawned; a new template starts at `0`), the anchor date (`due`
or `scheduled`), and optionally `rwait`, `rscheduled`, `runtil` (relative to the anchor, e.g.
`due-2d`) and `rend`. Absolute wait/scheduled/until given on a template are converted to their
relative forms.

**Instance** (pending or waiting): `rtemplate` (the template's UUID), `rindex` (its number),
and every other template attribute copied, with real dates computed from the relative ones.

Each kind's attributes are forbidden on the other; the hooks strip misplaced ones.

**Instance N's anchor** comes from the rule (`instance_dates`, the one place): for `period`,
`rule.nth(template anchor, N)`, so dates never drift with completion times: N−1 periods on,
months as calendar months clamped from the template's day, or a position rule's Nth date. For
`chain`, #1 is the template's anchor and #N is `rule.after(completion of #N−1)`, months as 30
days. Everything steps on the local calendar, so DST doesn't move the time of day. A position
rule's template is kept on its rule: an off-rule date is moved to the first match, with a
message.

## The rules

- **One-to-one:** every active template has exactly one pending or waiting instance.
- **rlast** equals the highest rindex spawned.
- **Only on-exit spawns** (`spawn_instance`, the one place instances are created), and only
  on-exit modifies other tasks. on-modify may change only the task it was given, so changes
  meant for another task (template → instance sync, instance rindex → template rlast) go in
  the spool for on-exit to apply.
- **Users delete.** The hooks never delete tasks; deleting a template tells you how to delete
  its pending instance.

## on-exit

1. **Spool**: `~/.task/recurrence_propagate.json`, a JSON list of
   `{instance_uuid, updates, instance_rindex, description, changes}`. Each entry is applied
   with `task <uuid> modify` (hooks off), then the file is removed. An old single-dict spool
   still works.
2. **One snapshot**: one export of every template and every active instance
   (`status:recurring or ((status:pending or status:waiting) and rtemplate.any:)`).
3. **One decision per template**: a template with no active instance gets its next one,
   whatever removed the last (done, delete, until: expiry, seen or not). `plan_next` picks the
   index: rlast+1, and for a periodic template it skips indexes whose until has already passed
   (one "Skipped N expired occurrences" message). Past `rend` nothing is spawned, and that is
   said once, only when this command finished the last instance.
4. The tasks on stdin (what this command changed) supply the completion time for chains, and
   tell "this command ended a template" apart from "a template ended long ago".

### Why one snapshot (the double-spawn bug, fixed in 2.10.0)

**Every `task export` runs Taskwarrior's handleUntil**, which deletes tasks whose `until` has
passed; with `rc.hooks=off` that happens silently. So any export the hooks run can change the
data under them: two passes that each exported saw different worlds, and both spawned. Keep it
to one export per run and decide from it. Custom reports, `count` and `_ids` expire tasks too.

## on-modify

- **Template modified**: recurrence fields (`r`, `type`, `ranchor`, `rlast`, `rend`, `rwait`,
  `rscheduled`, `runtil`) are synced to the active instance through the spool; changes to
  project, priority, tags or description get a suggested `task N mod …` for the instance.
  Changing `rlast` is the *time machine*: the instance takes that index and its dates.
- **Instance modified**: an `rindex` change recalculates its dates and spools the template's
  `rlast`; project, priority or tags changes get a suggested command for the template. Only
  these look the template up (an export); start, stop, annotate and other edits run no `task`.
- **Instance completed or deleted**: cleanup only, no `task` at all. Taskwarrior prints
  "Completed task N 'desc'." and on-exit announces the next instance.
- **Template completed or deleted**: its `r` is removed so it can be purged; on-exit reports it.

## Output

on-exit's messages go to stdout as footnotes. on-add/on-modify write theirs to stderr, but
when they refuse a change, to stdout: that's where Taskwarrior looks for a failing hook's
reason ("Hook Error: Expected feedback from failing hook script" otherwise), and no task JSON
goes with it. Taskwarrior shows each distinct footnote once per command, so messages name their task ("Instance #1 of 'x' synced"): three identical lines
would read as one. `rc.verbose=nothing` hides them.

## Debugging

```bash
DEBUG_RECURRENCE=1 task …          # appends to ~/.task/recurrence_debug.log
tw --debug=2 task …                # per-script logs in ~/.task/logs/debug/
TW_TIMING=1 task …                 # each hook's run time on stderr
```

A spool left behind after a command (`~/.task/recurrence_propagate.json`) means on-exit
didn't run or failed.

## Tests

```bash
cd test
python3 -m pytest -q
```

- `conftest.py`: the sandbox fixture: the hooks under real Taskwarrior in a throwaway task dir
  (on-modify symlinked as installed), America/Toronto.
- `test_hooks_sandbox.py`: lifecycle, spool, until-expiry. A `task` wrapper on PATH logs the
  hooks' own calls, so tests can pin how many exports a command costs.
- `test_until_expiry.py`: lifecycle, type normalisation, chains, rend, until-expiry
  reconcile. It needs tw's test framework (`~/.task/awesome-taskwarrior/lib`) and is skipped
  without it.
- `test_dst.py`: date arithmetic across DST changes.
- `test_rules.py`, `test_rules_positions.py`: the rule module alone (positions checked against
  dateutil's RRULE where it's installed; the module itself doesn't need it).
- `test_calendar_hooks.py`: calendar periods and position rules end to end.

**Dry run on real data** before installing: copy `~/.task/*.data` into a temp dir, with an rc
that does `include ~/.taskrc` and then overrides `data.location` and `hooks.location`. A
minimal rc won't do: values such as `priority:3` are valid only with your own config, and
spawns fail on them.

## Releasing

Bump `VERSION`, the meta's `version=`, `__version__` and the file headers together, add a
CHANGELOG entry, then run `make-awesome.py --install` and `--push`. The meta's
`links=on-modify_recurrence.py:on-add_recurrence.py:hook` makes the installer create the
symlink. Never ship on-modify as a file: the download would write through an existing
symlink and overwrite on-add.

## Known limitations

- Templates made while `r` was a duration UDA keep their stored `P30D`: 30 days, not a
  calendar month, until `r` is changed.
- `wait:due-1mo` typed on a template is computed by Taskwarrior (30 days) before the hook
  sees it; `rwait:due-1mo` steps a calendar month.
