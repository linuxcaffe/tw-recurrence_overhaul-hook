"""The recurrence hooks under a real Taskwarrior 2.6.2, in a throwaway task dir.

Each test gets fresh data, a copy of this repo's hooks (on-modify a symlink to on-add, as
installed) and recurrence.rc. Release A of the 2026-10-19 review (nb
tw:recurrence-overhaul_review_—_2026-10-19.md):

- a template past rend: said once, then silence (it was printed after every command)
- one command modifying several templates syncs every instance (the spool kept only the last)
- an until-expired periodic template catches up in one step, with no duplicates and no false
  "ERROR: No pending instances" (it took a command per missed day and spawned doubles)
- deleting a template says how to delete its pending instance (that message never showed)
- runtil is a defined UDA
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


def due_date(t):
    return (t.get('due') or t.get('scheduled'))[:8]


# ── the basics ───────────────────────────────────────────────────────────────

def test_new_template_gets_instance_1(tw):
    out = tw('add', 'water plants', 'r:7d', 'due:2030-01-07')
    assert 'recurrence instance #1' in out
    [inst] = tw.instances('water plants')
    assert inst['rindex'] == '1' and due_date(inst) == '20300107'
    assert tw.template('water plants')['rlast'] == '1'


def test_completing_spawns_the_next(tw):
    tw('add', 'water plants', 'r:7d', 'due:2030-01-07')
    out = tw('rtemplate.any:', 'done')
    assert 'recurrence instance #2' in out
    [inst] = tw.instances('water plants')
    assert inst['rindex'] == '2' and due_date(inst) == '20300114'      # period: anchor + 7d


def test_reports_say_nothing(tw):
    tw('add', 'water plants', 'r:7d', 'due:2030-01-07')
    for _ in range(2):
        assert tw('count').strip() == '1'


def test_description_with_attribute_words_is_kept(tw):
    tw('add', 'r:7d', 'due:2030-01-07', '--', 'water plants due:never +tag pro:x')
    [inst] = tw.instances('water plants due:never +tag pro:x')
    assert 'tags' not in inst and 'project' not in inst


# ── on-modify: no exports where none are needed (Release B) ──────────────────

def test_completing_says_it_once_and_on_modify_exports_nothing(tw):
    tw('add', 'water plants', 'r:7d', 'due:2030-01-07')
    out = tw('rtemplate.any:', 'done')
    assert 'Template:' not in out and 'ERROR' not in out              # task's own line is enough
    assert out.count('\n') == 1 and 'recurrence instance #2' in out   # verbose=footnote here
    exports = [c for c in tw.calls if c.endswith('export')]
    assert len(exports) == 1, tw.calls                                  # on-exit's snapshot only


def test_starting_an_instance_looks_nothing_up(tw):
    tw('add', 'water plants', 'r:7d', 'due:2030-01-07')
    tw('rtemplate.any:', 'start')
    assert [c for c in tw.calls if c.endswith('export')] == [tw.calls[0]]   # the snapshot
    assert 'status:recurring' in tw.calls[0]


def test_instance_priority_change_still_suggests_the_template_command(tw):
    tw('add', 'water plants', 'r:7d', 'due:2030-01-07')
    out = tw('rtemplate.any:', 'mod', 'priority:H')
    assert 'To apply to template (future instances):' in out
    assert f"task {tw.template('water plants')['id']} mod priority:H" in out


def test_template_modification_finds_the_instance(tw):
    tw('add', 'water plants', 'r:7d', 'due:2030-01-07')
    out = tw('status:recurring', 'mod', 'priority:H')
    [inst] = tw.instances('water plants')
    assert f"task {inst['id']} mod priority:H" in out


# ── rend: once ───────────────────────────────────────────────────────────────

def test_rend_is_said_once(tw):
    tw('add', 'ends soon', 'r:1d', 'due:today', 'rend:tomorrow+1h')
    tw('rtemplate.any:', 'done')                                        # #1 -> #2
    out = tw('rtemplate.any:', 'done')                                  # #2 was the last
    assert "Recurrence of 'ends soon' has ended" in out
    assert tw.instances('ends soon') == []
    for _ in range(3):
        assert 'ended' not in tw('count')


# ── the spool: every template a command modifies ─────────────────────────────

def test_one_command_syncs_every_template(tw):
    for d in ('alpha', 'beta', 'gamma'):
        tw('add', d, 'r:7d', 'due:2030-01-07')
    out = tw('status:recurring', 'mod', 'wait:due-1d')
    for d in ('alpha', 'beta', 'gamma'):
        assert f"Instance #1 of '{d}' synced (rwait)." in out
    for d in ('alpha', 'beta', 'gamma'):
        [inst] = tw.instances(d)
        assert inst.get('wait', '')[:8] == '20300106', d
    assert not (tw.dir / 'recurrence_propagate.json').exists()


def test_an_old_single_entry_spool_still_works(tw):
    tw('add', 'alpha', 'r:7d', 'due:2030-01-07')
    [inst] = tw.instances('alpha')
    (tw.dir / 'recurrence_propagate.json').write_text(json.dumps(
        {'instance_uuid': inst['uuid'], 'updates': {'priority': 'H'}, 'instance_rindex': '1'}))
    assert 'Instance #1 synced' in tw('count')
    assert tw.instances('alpha')[0].get('priority') == 'H'


# ── until: expiry catches up in one step, no duplicates ──────────────────────

def test_expired_periodic_catches_up_at_once(tw):
    out = tw('add', 'daily stretch', 'r:1d', 'due:today-5d', 'until:due+1h')
    out += tw('count') + tw('count')
    every = tw.instances('daily stretch', active=False)
    indexes = [int(t['rindex']) for t in every]
    assert len(indexes) == len(set(indexes)), f'duplicates: {indexes}'
    active = tw.instances('daily stretch')
    assert len(active) == 1
    from datetime import datetime, timezone
    assert active[0]['until'] > datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    assert 'ERROR' not in out
    assert 'Skipped' in out and out.count('recurrence instance #') == 1


def test_an_instance_expiring_later_is_replaced_once(tw):
    tw('add', 'hourly', 'r:1d', 'due:now+2s', 'until:due+1s')
    [first] = tw.instances('hourly')
    import time
    time.sleep(4)                                                       # #1 expires
    out = tw('count') + tw('count')
    active = tw.instances('hourly')
    assert len(active) == 1 and active[0]['rindex'] == '2'
    assert out.count('recurrence instance #') == 1


# ── templates ending ─────────────────────────────────────────────────────────

def test_deleting_a_template_says_how_to_delete_its_instance(tw):
    tw('add', 'water plants', 'r:7d', 'due:2030-01-07')
    [inst] = tw.instances('water plants')
    out = tw('status:recurring', 'delete')
    assert "Deleted template 'water plants'" in out
    [left] = tw.instances('water plants')                              # left for the user
    assert left['uuid'] == inst['uuid']
    assert f"To delete the pending instance: task {left['id']} delete" in out   # today's ID


# ── recurrence.rc ────────────────────────────────────────────────────────────

def test_runtil_is_a_defined_uda(tw):
    assert 'runtil' in tw('rc.verbose=nothing', '_udas')
