#!/usr/bin/env python3
"""
Tests for recurrence hook until: auto-expiry reconciliation.

Bug: Taskwarrior silently auto-deletes tasks whose until: date has passed.
     These auto-expired tasks never appear in on-exit hook stdin.
     The reactive spawn logic in process_tasks() therefore never fires.

Fix (v2.7.5): reconcile_orphaned_templates() scans all status:recurring templates
     on every on-exit call and spawns the next instance for any with no
     pending/waiting instance.

Usage:
    python3 test-recurrence-until-expiry.py
"""

import sys
import os
import unittest
import json
import time

sys.path.insert(0, os.path.expanduser('~/.task/awesome-taskwarrior/lib'))
from test_framework import TaskTestCase, TAPTestRunner

HOOK_DIR = os.path.expanduser('~/dev/tw-recurrence_overhaul-hook')

# Recurrence UDAs — mirrors recurrence.rc
RECURRENCE_UDAS = {
    'recurrence': 'no',
    'uda.r.type': 'duration',
    'uda.r.label': 'Recurrence Period',
    'uda.rtemplate.type': 'string',
    'uda.rtemplate.label': 'Recur',
    'uda.rlast.type': 'string',
    'uda.rlast.label': 'Last Instance Index',
    'uda.rindex.type': 'string',
    'uda.rindex.label': 'Instance Index',
    'uda.rwait.type': 'string',
    'uda.rwait.label': 'Template Wait',
    'uda.rscheduled.type': 'string',
    'uda.rscheduled.label': 'Template Scheduled',
    'uda.ranchor.type': 'string',
    'uda.ranchor.label': 'Anchor Field',
    'uda.rend.type': 'date',
    'uda.rend.label': 'Recurrence End',
    'uda.type.type': 'string',
    'uda.type.label': 'Recurrence Type',
}


class TestRecurrenceUntilExpiry(TaskTestCase):

    def get_taskrc_extras(self):
        return RECURRENCE_UDAS

    def setUp(self):
        super().setUp()
        # B+C isolation: hooks read TW_TASK_DIR for paths
        os.environ['TW_TASK_DIR'] = self.t.taskdata
        # Install all three hooks + common module
        for fname in ('on-add_recurrence.py', 'on-modify_recurrence.py',
                      'on-exit_recurrence.py', 'recurrence_common_hook.py'):
            src = os.path.join(HOOK_DIR, fname)
            if os.path.exists(src):
                self.t.link_hook(fname, src)

    def tearDown(self):
        os.environ.pop('TW_TASK_DIR', None)
        super().tearDown()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _add_daily_recur(self, desc='daily test task', until_offset='+7d'):
        """Add a daily recurring task with until: on each instance."""
        self.t.task('add', desc, '+test', 'r:1d', 'due:today', f'until:{until_offset}')
        # Find the template (status:recurring) — filter must come before verb
        _, out, _ = self.t.task('status:recurring', 'export')
        all_tasks = json.loads(out) if out.strip() else []
        self.assertGreater(len(all_tasks), 0, "No recurring template created")
        return all_tasks[0]

    def _pending_instances(self):
        """Return all pending tasks that are recurrence instances."""
        # rtemplate.any: filters tasks that have the rtemplate UDA set
        _, out, _ = self.t.task('rtemplate.any:', 'status:pending', 'export')
        return json.loads(out) if out.strip() else []

    def _expire_instance(self, task_id):
        """Simulate until: auto-expiry by setting until: to past, then triggering on-exit."""
        self.t.task(str(task_id), 'modify', 'until:2020-01-01')
        # Any task command triggers on-exit, which is when TW auto-deletes
        # the expired task and our reconcile pass runs.
        self.t.task('next')

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_template_creates_first_instance_on_add(self):
        """on-add hook creates template + first instance"""
        self._add_daily_recur()
        instances = self._pending_instances()
        self.assertEqual(len(instances), 1, "Expected exactly 1 pending instance after add")
        self.assertEqual(instances[0]['rindex'], '1')

    def test_manual_deletion_spawns_next_instance(self):
        """Manually deleting an instance triggers reactive spawn of the next one"""
        self._add_daily_recur()
        inst = self._pending_instances()[0]
        self.t.task(str(inst['id']), 'delete')
        instances = self._pending_instances()
        self.assertEqual(len(instances), 1, "Expected 1 new instance after manual delete")
        self.assertEqual(instances[0]['rindex'], '2', "New instance should be index 2")

    def test_completion_spawns_next_instance(self):
        """Completing an instance triggers reactive spawn of the next one"""
        self._add_daily_recur()
        inst = self._pending_instances()[0]
        self.t.task(str(inst['id']), 'done')
        instances = self._pending_instances()
        self.assertEqual(len(instances), 1, "Expected 1 new instance after completion")
        self.assertEqual(instances[0]['rindex'], '2')

    def test_until_expiry_reconcile_spawns_next_instance(self):
        """
        BUG REGRESSION: until: auto-expiry silently kills instances without
        triggering reactive spawn. reconcile_orphaned_templates() must catch this.

        Confirmed broken in v2.7.4: instance deleted, nothing spawned.
        Fixed in v2.7.5.
        """
        self._add_daily_recur(until_offset='+7d')
        inst = self._pending_instances()[0]
        self.assertEqual(inst['rindex'], '1')

        # Simulate until: expiry — TW silently deletes, on-exit stdin gets 0 lines
        self._expire_instance(inst['id'])

        instances = self._pending_instances()
        self.assertEqual(
            len(instances), 1,
            f"Expected reconcile to spawn instance after until: expiry, got {len(instances)}"
        )
        self.assertEqual(instances[0]['rindex'], '2',
                         "Reconciled instance should be index 2")

    def test_no_double_spawn_on_manual_delete(self):
        """Reactive pass + reconcile together must NOT double-spawn"""
        self._add_daily_recur()
        inst = self._pending_instances()[0]
        self.t.task(str(inst['id']), 'delete')
        instances = self._pending_instances()
        self.assertEqual(len(instances), 1,
                         f"Expected exactly 1 instance, got {len(instances)} (double-spawn?)")

    def test_until_expiry_twice_spawns_sequentially(self):
        """Two successive until: expiries each advance the instance index"""
        self._add_daily_recur()

        # Expire instance 1
        inst1 = self._pending_instances()[0]
        self._expire_instance(inst1['id'])
        instances = self._pending_instances()
        self.assertEqual(instances[0]['rindex'], '2')

        # Expire instance 2
        inst2 = instances[0]
        self._expire_instance(inst2['id'])
        instances = self._pending_instances()
        self.assertEqual(instances[0]['rindex'], '3')

    def test_instance_until_date_is_relative_to_instance_due(self):
        """Each instance's until: = instance_due + runtil_offset (not template_due)"""
        self._add_daily_recur(until_offset='+7d')
        inst1 = self._pending_instances()[0]
        until1 = inst1.get('until', '')
        due1 = inst1.get('due', '')
        self.assertTrue(until1, "Instance should have until: field")

        # Delete instance 1, get instance 2
        self.t.task(str(inst1['id']), 'delete')
        inst2 = self._pending_instances()[0]
        until2 = inst2.get('until', '')
        due2 = inst2.get('due', '')

        # until2 should be offset from due2, same delta as until1 from due1
        from datetime import datetime
        fmt = '%Y%m%dT%H%M%SZ'
        delta1 = datetime.strptime(until1, fmt) - datetime.strptime(due1, fmt)
        delta2 = datetime.strptime(until2, fmt) - datetime.strptime(due2, fmt)
        # Allow 60s tolerance for test execution time
        self.assertAlmostEqual(
            delta1.total_seconds(), delta2.total_seconds(), delta=60,
            msg="until: offset should be the same for each instance"
        )

    def test_template_deletion_stops_recurrence(self):
        """Deleting the template stops future instance spawning"""
        template = self._add_daily_recur()
        # Delete the template
        self.t.task(template['uuid'], 'delete')
        # Delete the pending instance
        instances = self._pending_instances()
        for inst in instances:
            self.t.task(str(inst['id']), 'delete')
        # Run a command — reconcile should NOT spawn anything (template gone)
        # expect_error=True because 'task next' exits 1 when there are no tasks
        self.t.task('next', expect_error=True)
        self.assertEqual(len(self._pending_instances()), 0,
                         "No instances should spawn after template is deleted")


class TestRecurrenceChainedAndTypes(TaskTestCase):
    """Tests for chained recurrence type and type normalisation."""

    def get_taskrc_extras(self):
        return RECURRENCE_UDAS

    def setUp(self):
        super().setUp()
        os.environ['TW_TASK_DIR'] = self.t.taskdata
        for fname in ('on-add_recurrence.py', 'on-modify_recurrence.py',
                      'on-exit_recurrence.py', 'recurrence_common_hook.py'):
            src = os.path.join(HOOK_DIR, fname)
            if os.path.exists(src):
                self.t.link_hook(fname, src)

    def tearDown(self):
        os.environ.pop('TW_TASK_DIR', None)
        super().tearDown()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _add_recur(self, desc='recur task', period='1d', type_str=None, **extras):
        """Add a recurring task. Pass type_str for ty: field; extras as key:val."""
        args = ['add', desc, '+test', f'r:{period}', 'due:today']
        if type_str:
            args.append(f'ty:{type_str}')
        for k, v in extras.items():
            args.append(f'{k}:{v}')
        self.t.task(*args)
        _, out, _ = self.t.task('status:recurring', 'export')
        templates = json.loads(out) if out.strip() else []
        self.assertGreater(len(templates), 0, "No recurring template created")
        return templates[0]

    def _pending_instances(self):
        _, out, _ = self.t.task('rtemplate.any:', 'status:pending', 'export')
        return json.loads(out) if out.strip() else []

    # ------------------------------------------------------------------
    # Type normalisation
    # ------------------------------------------------------------------

    def test_type_c_normalised_to_chain(self):
        """ty:c shorthand is stored as 'chain'"""
        tmpl = self._add_recur(type_str='c')
        self.assertEqual(tmpl.get('type'), 'chain')

    def test_type_ch_normalised_to_chain(self):
        """ty:ch abbreviation is stored as 'chain'"""
        tmpl = self._add_recur(type_str='ch')
        self.assertEqual(tmpl.get('type'), 'chain')

    def test_type_chain_stored_as_chain(self):
        """ty:chain is stored as 'chain'"""
        tmpl = self._add_recur(type_str='chain')
        self.assertEqual(tmpl.get('type'), 'chain')

    def test_type_p_normalised_to_period(self):
        """ty:p shorthand is stored as 'period'"""
        tmpl = self._add_recur(type_str='p')
        self.assertEqual(tmpl.get('type'), 'period')

    def test_default_type_is_period(self):
        """Omitting ty: defaults to 'period'"""
        tmpl = self._add_recur()
        self.assertEqual(tmpl.get('type'), 'period')

    # ------------------------------------------------------------------
    # Chained recurrence behaviour
    # ------------------------------------------------------------------

    def test_chained_first_instance_has_rindex_1(self):
        """Chained recurrence creates first instance with rindex=1"""
        self._add_recur(type_str='c', period='1d')
        instances = self._pending_instances()
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]['rindex'], '1')

    def test_chained_completion_anchors_due_to_completion_time(self):
        """Completing a chained instance sets next due = completion_time + period"""
        period_sec = 5
        self._add_recur(type_str='c', period=f'{period_sec}s')
        inst1 = self._pending_instances()[0]

        before_complete = time.time()
        self.t.task(str(inst1['id']), 'done')
        after_complete = time.time()

        instances = self._pending_instances()
        self.assertEqual(len(instances), 1, "Expected 1 instance after chained completion")

        from datetime import datetime, timezone
        due2_str = instances[0].get('due', '')
        self.assertTrue(due2_str, "Instance 2 should have a due date")
        due2_epoch = datetime.strptime(due2_str, '%Y%m%dT%H%M%SZ') \
                             .replace(tzinfo=timezone.utc).timestamp()

        # due2 should be ≈ completion_time + period_sec (10s tolerance for slow CI)
        self.assertGreater(due2_epoch, before_complete + period_sec - 10,
                           f"due2 too early: {due2_epoch}")
        self.assertLess(due2_epoch, after_complete + period_sec + 10,
                        f"due2 too late: {due2_epoch}")

    def test_chained_multiple_completions_increment_rindex(self):
        """Three successive chained completions produce rindex 1, 2, 3 in order"""
        self._add_recur(type_str='c', period='5s')
        for expected_rindex in ('1', '2', '3'):
            instances = self._pending_instances()
            self.assertEqual(len(instances), 1)
            self.assertEqual(instances[0]['rindex'], expected_rindex,
                             f"Expected rindex={expected_rindex}, got {instances[0].get('rindex')}")
            self.t.task(str(instances[0]['id']), 'done')

    def test_rend_stops_spawning(self):
        """rend: stops spawning when next due would exceed it (r:7d, rend:+3d)"""
        # period=7d, rend=+3d — next due after completion = today+7d >> rend
        self._add_recur(type_str='c', period='7d', rend='+3d')
        instances = self._pending_instances()
        self.assertEqual(len(instances), 1, "Expected first instance to be created")
        self.t.task(str(instances[0]['id']), 'done')
        new_instances = self._pending_instances()
        self.assertEqual(len(new_instances), 0,
                         "No new instance should spawn when next due exceeds rend")


if __name__ == '__main__':
    unittest.main(testRunner=TAPTestRunner())
