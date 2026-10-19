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

REPO = Path(__file__).resolve().parent.parent
HOOKS = ['on-add_recurrence.py', 'on-exit_recurrence.py', 'recurrence_common_hook.py']


@pytest.fixture
def tw(tmp_path):
    hooks = tmp_path / 'hooks'
    hooks.mkdir()
    for h in HOOKS:
        shutil.copy2(REPO / h, hooks / h)
    (hooks / 'on-modify_recurrence.py').symlink_to('on-add_recurrence.py')
    rc = tmp_path / 'rc'
    rc.write_text(f'data.location={tmp_path}\nhooks.location={hooks}\nconfirmation=off\n'
                  f'verbose=footnote\nbulk=0\ninclude {REPO / "recurrence.rc"}\n')
    env = dict(os.environ, TASKRC=str(rc), TW_TASK_DIR=str(tmp_path), HOME=str(tmp_path),
               PYTHONPYCACHEPREFIX=str(tmp_path / 'pycache'))
    for k in ('DEBUG_RECURRENCE', 'TW_DEBUG', 'TW_TIMING'):
        env.pop(k, None)

    class T:
        dir = tmp_path

        def __call__(self, *args):
            """Run task with hooks; stdout + stderr."""
            r = subprocess.run(['task'] + list(args), capture_output=True, text=True, env=env,
                               timeout=60)
            return r.stdout + r.stderr

        def export(self, *filt):
            r = subprocess.run(['task', 'rc.hooks=off', 'rc.verbose=nothing'] + list(filt) + ['export'],
                               capture_output=True, text=True, env=env, timeout=60)
            return json.loads(r.stdout) if r.stdout.strip() else []

        def template(self, desc):
            return next(t for t in self.export('status:recurring') if t['description'] == desc)

        def instances(self, desc, active=True):
            filt = ['(', 'status:pending', 'or', 'status:waiting', ')'] if active else []
            return sorted((t for t in self.export('rtemplate.any:', *filt) if t['description'] == desc),
                          key=lambda t: int(t['rindex']))

    return T()


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
