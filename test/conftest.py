"""The sandbox: the recurrence hooks under a real Taskwarrior 2.6.2 in a throwaway task dir.

Each test gets fresh data, a copy of this repo's hooks (on-modify a symlink to on-add, as
installed) and recurrence.rc, in America/Toronto. tw(*args) runs task with hooks and returns
stdout + stderr; tw.calls are the hooks' own task calls (through a logging wrapper on PATH);
tw.export / template / instances read the data with hooks off.

RECURRENCE_INSTALLED=<task dir> tests an installed copy instead of this repo: the hooks from
<dir>/hooks (its on-modify link included) and <dir>/config/recurrence.rc.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
HOOKS = ['on-add_recurrence.py', 'on-exit_recurrence.py', 'recurrence_common_hook.py',
         'recurrence_rules.py']
INSTALLED = os.environ.get('RECURRENCE_INSTALLED')
SOURCE = Path(INSTALLED) / 'hooks' if INSTALLED else REPO
RC = Path(INSTALLED) / 'config' / 'recurrence.rc' if INSTALLED else REPO / 'recurrence.rc'


@pytest.fixture
def tw(tmp_path):
    hooks = tmp_path / 'hooks'
    hooks.mkdir()
    for h in HOOKS:
        shutil.copy2(SOURCE / h, hooks / h)
    link = SOURCE / 'on-modify_recurrence.py'
    if INSTALLED:
        assert link.is_symlink() and str(link.readlink()) == 'on-add_recurrence.py', link
    (hooks / 'on-modify_recurrence.py').symlink_to('on-add_recurrence.py')
    rc = tmp_path / 'rc'
    rc.write_text(f'data.location={tmp_path}\nhooks.location={hooks}\nconfirmation=off\n'
                  f'verbose=footnote\nbulk=0\ninclude {RC}\n')
    # the hooks' own task calls go through a wrapper that logs them
    bin_ = tmp_path / 'bin'
    bin_.mkdir()
    calls = tmp_path / 'hook-calls'
    real = shutil.which('task')
    (bin_ / 'task').write_text(f'#!/bin/sh\necho "$*" >> {calls}\nexec {real} "$@"\n')
    (bin_ / 'task').chmod(0o755)
    env = dict(os.environ, TASKRC=str(rc), TW_TASK_DIR=str(tmp_path), HOME=str(tmp_path),
               TZ='America/Toronto',
               PYTHONPYCACHEPREFIX=str(tmp_path / 'pycache'),
               PATH=f"{bin_}:{os.environ['PATH']}")
    for k in ('DEBUG_RECURRENCE', 'TW_DEBUG', 'TW_TIMING'):
        env.pop(k, None)

    class T:
        dir = tmp_path

        def __call__(self, *args):
            """Run task with hooks; stdout + stderr. self.calls: the hooks' own task calls."""
            calls.write_text('')
            r = subprocess.run([real] + list(args), capture_output=True, text=True, env=env,
                               timeout=60)
            return r.stdout + r.stderr

        @property
        def calls(self):
            return calls.read_text().splitlines() if calls.exists() else []

        def export(self, *filt):
            r = subprocess.run([real, 'rc.hooks=off', 'rc.verbose=nothing'] + list(filt) + ['export'],
                               capture_output=True, text=True, env=env, timeout=60)
            return json.loads(r.stdout) if r.stdout.strip() else []

        def template(self, desc):
            return next(t for t in self.export('status:recurring') if t['description'] == desc)

        def instances(self, desc, active=True):
            filt = ['(', 'status:pending', 'or', 'status:waiting', ')'] if active else []
            return sorted((t for t in self.export('rtemplate.any:', *filt) if t['description'] == desc),
                          key=lambda t: int(t['rindex']))

    return T()
