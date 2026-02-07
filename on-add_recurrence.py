#!/usr/bin/env python3
"""
Taskwarrior Enhanced Recurrence Hook - On-Add/On-Modify
Version: 0.5.0
Date: 2026-02-07

Handles both adding new recurring tasks and modifying existing ones with
sophisticated modification tracking and user feedback.

Features:
- Template creation with type normalization
- Smart modification detection and handling
- Bidirectional rindex Ã¢â€ â€� rlast synchronization
- Anchor change detection with automatic rwait/rscheduled updates
- Time machine functionality (rlast modifications)
- Comprehensive user messaging following awesome-taskwarrior standard
- Attribute change propagation suggestions

Installation:
    1. Save to ~/.task/hooks/on-add_recurrence.py
    2. chmod +x ~/.task/hooks/on-add_recurrence.py
    3. cd ~/.task/hooks && ln -s on-add_recurrence.py on-modify_recurrence.py
    4. Ensure recurrence_common_hook.py is in ~/.task/hooks/
"""

import sys
sys.dont_write_bytecode = True

import json
import os
import re
import subprocess

# Re-entrancy guard: when propagating template changes to instance,
# the subprocess 'task modify' triggers on-modify again. This env var
# tells the second invocation to pass through without cascading.
PROPAGATING = os.environ.get('RECURRENCE_PROPAGATING', '') == '1'

# Add hooks directory to Python path for importing common module
hooks_dir = os.path.expanduser('~/.task/hooks')
if hooks_dir not in sys.path:
    sys.path.insert(0, hooks_dir)

try:
    from recurrence_common_hook import (
        normalize_type, parse_duration, parse_date, format_date,
        parse_relative_date, is_template, is_instance,
        get_anchor_field_name, debug_log, DEBUG,
        query_instances, check_instance_count
    )
except ImportError as e:
    # Fallback error handling
    sys.stderr.write(f"ERROR: Cannot import recurrence_common_hook: {e}\n")
    sys.stderr.write("Please ensure recurrence_common_hook.py is in ~/.task/hooks/\n")
    sys.exit(1)


def query_task(uuid):
    """Query Taskwarrior for a task by UUID
    
    Args:
        uuid: Task UUID to query
        
    Returns:
        Task dictionary or None if not found/error
    """
    try:
        result = subprocess.run(
            ['task', 'rc.hooks=off', uuid, 'export'],
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.returncode == 0 and result.stdout.strip():
            tasks = json.loads(result.stdout)
            if tasks:
                if DEBUG:
                    debug_log(f"Queried task {uuid}: found", "ADD/MOD")
                return tasks[0]
        
        if DEBUG:
            debug_log(f"Queried task {uuid}: not found", "ADD/MOD")
        return None
        
    except (subprocess.SubprocessError, json.JSONDecodeError) as e:
        if DEBUG:
            debug_log(f"Query task {uuid} failed: {e}", "ADD/MOD")
        return None


def query_instances(template_uuid):
    """Query all pending instances for a template
    
    Args:
        template_uuid: Template UUID
        
    Returns:
        List of instance task dictionaries
    """
    try:
        result = subprocess.run(
            ['task', 'rc.hooks=off', f'rtemplate:{template_uuid}', 'status:pending', 'export'],
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.returncode == 0 and result.stdout.strip():
            instances = json.loads(result.stdout)
            if DEBUG:
                debug_log(f"Queried instances for {template_uuid}: {len(instances)} found", "ADD/MOD")
            return instances
        
        if DEBUG:
            debug_log(f"Queried instances for {template_uuid}: none found", "ADD/MOD")
        return []
        
    except (subprocess.SubprocessError, json.JSONDecodeError) as e:
        if DEBUG:
            debug_log(f"Query instances for {template_uuid} failed: {e}", "ADD/MOD")
        return []


def update_task(uuid, modifications):
    """Update a task via Taskwarrior command
    
    Args:
        uuid: Task UUID to update
        modifications: Dictionary of field:value to modify
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Build modification command
        mod_args = []
        for field, value in modifications.items():
            mod_args.append(f'{field}:{value}')
        
        result = subprocess.run(
            ['task', 'rc.hooks=off', 'rc.confirmation=off', 'rc.verbose=nothing', uuid, 'mod'] + mod_args,
            capture_output=True,
            text=True,
            check=False
        )
        
        success = result.returncode == 0
        
        if DEBUG:
            if success:
                debug_log(f"Updated task {uuid} with {modifications}", "ADD/MOD")
            else:
                debug_log(f"Failed to update task {uuid}: {result.stderr}", "ADD/MOD")
        
        return success
        
    except subprocess.SubprocessError as e:
        if DEBUG:
            debug_log(f"Update task {uuid} failed: {e}", "ADD/MOD")
        return False

def update_instance_for_rlast_change(template, instance, old_rlast, new_rlast):
    """Update an existing instance when template rlast changes (time machine)
    
    This modifies the instance in place rather than deleting and respawning it.
    Updates both the rindex and the due date to match the new sequence position.
    
    Args:
        template: Template task dict (with new rlast)
        instance: Instance task dict (with old rindex)
        old_rlast: Previous rlast value
        new_rlast: New rlast value
        
    Returns:
        True if successful, False otherwise
    """
    inst_uuid = instance['uuid']
    inst_id = instance.get('id', '?')
    
    if DEBUG:
        debug_log(f"Updating instance {inst_id} for rlast change: {old_rlast} -> {new_rlast}", "ADD/MOD")
    
    # Calculate new due date based on template type
    type_str = template.get('type', 'period')
    anchor_field = template.get('ranchor', 'due')
    actual_field = get_anchor_field_name(anchor_field)
    template_anchor = parse_date(template.get(actual_field))
    
    if not template_anchor:
        if DEBUG:
            debug_log(f"Cannot update instance - no template anchor date", "ADD/MOD")
        return False
    
    r_delta = parse_duration(template.get('r'))
    if not r_delta:
        if DEBUG:
            debug_log(f"Cannot update instance - cannot parse recurrence period", "ADD/MOD")
        return False
    
    # Calculate new anchor date for this instance
    if type_str == 'period':
        # Periodic: template_anchor + (new_rlast Ã— period)
        new_anchor = template_anchor + (r_delta * new_rlast)
    else:
        # Chained: approximate using template_anchor + offset
        # Note: Changing rlast on chained tasks is unusual since they're based on completion
        new_anchor = template_anchor + (r_delta * new_rlast)
    
    # Build modification dictionary
    modifications = {
        'rindex': str(new_rlast),
        actual_field: format_date(new_anchor)
    }
    
    # Update relative dates if they exist in template
    if 'rwait' in template:
        wait_date = parse_relative_date(template['rwait'], new_anchor)
        if wait_date:
            modifications['wait'] = format_date(wait_date)
    
    if 'rscheduled' in template and anchor_field != 'sched':
        sched_date = parse_relative_date(template['rscheduled'], new_anchor)
        if sched_date:
            modifications['scheduled'] = format_date(sched_date)
    
    # Execute modification with rc.hooks=off
    return update_task(inst_uuid, modifications)

# Read all input
lines = sys.stdin.readlines()
IS_ON_ADD = len(lines) == 1

if DEBUG:
    debug_log("="*60, "ADD/MOD")
    debug_log(f"Hook starting - Mode: {'ADD' if IS_ON_ADD else 'MODIFY'}, lines: {len(lines)}", "ADD/MOD")


class RecurrenceHandler:
    """Handles enhanced recurrence for Taskwarrior"""
    
    # Define which attributes belong to templates vs instances
    TEMPLATE_ONLY_ATTRS = {'r', 'type', 'ranchor', 'rlast', 'rend', 'rwait', 'rscheduled', 'runtil'}
    INSTANCE_ONLY_ATTRS = {'rtemplate', 'rindex'}
    
    def __init__(self):
        self.messages = []  # Collect messages to output at end
    
    def add_message(self, message):
        """Add a message to be output to user"""
        self.messages.append(message)
    
    def output_messages(self):
        """Output all collected messages to stderr"""
        if self.messages:
            for msg in self.messages:
                sys.stderr.write(f"{msg}\n")
    
    def cleanup_template_attributes(self, task):
        """Remove instance-only attributes from a template
        
        Args:
            task: Task dictionary (modified in place)
            
        Returns:
            List of removed attributes (for reporting)
        """
        removed = []
        for attr in self.INSTANCE_ONLY_ATTRS:
            if attr in task:
                del task[attr]
                removed.append(attr)
                if DEBUG:
                    debug_log(f"Removed instance-only attribute '{attr}' from template", "ADD/MOD")
        return removed
    
    def cleanup_instance_attributes(self, task):
        """Remove template-only attributes from an instance
        
        Args:
            task: Task dictionary (modified in place)
            
        Returns:
            List of removed attributes (for reporting)
        """
        removed = []
        for attr in self.TEMPLATE_ONLY_ATTRS:
            if attr in task:
                del task[attr]
                removed.append(attr)
                if DEBUG:
                    debug_log(f"Removed template-only attribute '{attr}' from instance", "ADD/MOD")
        return removed
    
    def validate_and_cleanup(self, task, is_template_task):
        """Validate and cleanup a task based on its type
        
        Args:
            task: Task dictionary (modified in place)
            is_template_task: True if template, False if instance
            
        Returns:
            Warning message if attributes were removed, None otherwise
        """
        if is_template_task:
            removed = self.cleanup_template_attributes(task)
            if removed:
                return (
                    f"WARNING: Removed instance-only attributes from template: {', '.join(removed)}\n"
                    f"  Templates should not have: rindex, rtemplate"
                )
        else:
            removed = self.cleanup_instance_attributes(task)
            if removed:
                return (
                    f"WARNING: Removed template-only attributes from instance: {', '.join(removed)}\n"
                    f"  Instances should not have: r, type, ranchor, rlast, rend, rwait, rscheduled, runtil"
                )
        return None
    
    def get_anchor_date(self, task):
        """Get the anchor date (due or sched) for recurrence"""
        if 'due' in task:
            return 'due', parse_date(task['due'])
        elif 'scheduled' in task:
            return 'sched', parse_date(task['scheduled'])
        return None, None
    
    def convert_wait_to_relative(self, task, anchor_field, anchor_date):
        """Convert absolute wait to relative rwait
        
        Args:
            task: Task dictionary (modified in place)
            anchor_field: 'due' or 'sched'
            anchor_date: Datetime object for anchor
            
        Returns:
            True if conversion was performed
        """
        if 'wait' not in task:
            return False
        
        wait_str = task['wait']
        ref_field, offset = parse_relative_date(wait_str)
        
        if ref_field and offset:
            # Already in relative format - preserve it
            task['rwait'] = wait_str
            del task['wait']
            return False  # No conversion needed
        else:
            # Absolute date - convert to relative offset in seconds
            wait_dt = parse_date(wait_str)
            if wait_dt and anchor_date:
                delta_sec = int((wait_dt - anchor_date).total_seconds())
                if delta_sec != 0:
                    task['rwait'] = f'{anchor_field}{delta_sec:+d}s'
                else:
                    task['rwait'] = f'{anchor_field}+0s'
                del task['wait']
                
                if DEBUG:
                    debug_log(f"Converted absolute wait to relative: {task['rwait']}", "ADD/MOD")
                
                # No user message needed - this is expected behavior
                return True
        
        return False
    
    def convert_scheduled_to_relative(self, task, anchor_field, anchor_date):
        """Convert absolute scheduled to relative rscheduled (if anchor is not sched)
        
        Args:
            task: Task dictionary (modified in place)
            anchor_field: 'due' or 'sched'
            anchor_date: Datetime object for anchor
            
        Returns:
            True if conversion was performed
        """
        if 'scheduled' not in task or anchor_field == 'sched':
            return False
        
        sched_str = task['scheduled']
        ref_field, offset = parse_relative_date(sched_str)
        
        if ref_field and offset:
            # Already in relative format - preserve it
            task['rscheduled'] = sched_str
            del task['scheduled']
            return False
        else:
            # Absolute date - convert to relative offset
            sched_dt = parse_date(sched_str)
            if sched_dt and anchor_date:
                delta_sec = int((sched_dt - anchor_date).total_seconds())
                if delta_sec != 0:
                    task['rscheduled'] = f'{anchor_field}{delta_sec:+d}s'
                else:
                    task['rscheduled'] = f'{anchor_field}+0s'
                del task['scheduled']
                
                if DEBUG:
                    debug_log(f"Converted absolute scheduled to relative: {task['rscheduled']}", "ADD/MOD")
                
                return True
        
        return False
    
    def convert_until_to_relative(self, task, anchor_field, anchor_date):
        """Convert absolute until to relative runtil
        
        Args:
            task: Task dictionary (modified in place)
            anchor_field: 'due' or 'sched'
            anchor_date: Datetime object for anchor
            
        Returns:
            True if conversion was performed
        """
        if 'until' not in task:
            return False
        
        until_str = task['until']
        ref_field, offset = parse_relative_date(until_str)
        
        if ref_field and offset:
            # Already in relative format - preserve it
            task['runtil'] = until_str
            del task['until']
            if DEBUG:
                debug_log(f"Converted relative until expression: {task['runtil']}", "ADD/MOD")
            return True
        else:
            # Absolute date - convert to relative offset
            until_dt = parse_date(until_str)
            if until_dt and anchor_date:
                delta_sec = int((until_dt - anchor_date).total_seconds())
                if delta_sec != 0:
                    task['runtil'] = f'{anchor_field}{delta_sec:+d}s'
                else:
                    task['runtil'] = f'{anchor_field}+0s'
                del task['until']
                
                if DEBUG:
                    debug_log(f"Converted absolute until to relative: {task['runtil']}", "ADD/MOD")
                
                return True
        
        return False
    
    def update_relative_dates_for_anchor_change(self, task, old_anchor, new_anchor):
        """Update rwait and rscheduled when anchor changes
        
        Args:
            task: Task dictionary (modified in place)
            old_anchor: Previous anchor field ('due' or 'sched')
            new_anchor: New anchor field ('due' or 'sched')
        """
        updated_fields = []
        
        # Update rwait if it exists
        if 'rwait' in task:
            old_rwait = task['rwait']
            # Replace old anchor reference with new anchor
            new_rwait = re.sub(r'^(due|sched)', new_anchor, old_rwait)
            if new_rwait != old_rwait:
                task['rwait'] = new_rwait
                updated_fields.append('rwait')
                if DEBUG:
                    debug_log(f"Updated rwait: {old_rwait} -> {new_rwait}", "ADD/MOD")
        
        # Update rscheduled if it exists
        if 'rscheduled' in task:
            old_rsched = task['rscheduled']
            new_rsched = re.sub(r'^(due|sched)', new_anchor, old_rsched)
            if new_rsched != old_rsched:
                task['rscheduled'] = new_rsched
                updated_fields.append('rscheduled')
                if DEBUG:
                    debug_log(f"Updated rscheduled: {old_rsched} -> {new_rsched}", "ADD/MOD")
        
        return updated_fields
    
    def create_template(self, task):
        """Convert a new task with r (recurrence) into a template
        
        Args:
            task: Task dictionary
            
        Returns:
            Modified task dictionary as template
        """
        if DEBUG:
            debug_log(f"Creating template: {task.get('description')}", "ADD/MOD")
        
        if 'r' not in task:
            return task
        
        # Normalize and set type (with abbreviation support)
        task['type'] = normalize_type(task.get('type'))
        
        if DEBUG:
            debug_log(f"  Type: {task['type']}, r={task.get('r')}", "ADD/MOD")
        
        # Mark as template
        task['status'] = 'recurring'
        task['rlast'] = '1'
        
        # Get anchor date
        anchor_field, anchor_date = self.get_anchor_date(task)
        
        if not anchor_field or not anchor_date:
            if DEBUG:
                debug_log(f"  ERROR: No valid anchor date found", "ADD/MOD")
                debug_log(f"  Task due: {task.get('due')}", "ADD/MOD")
                debug_log(f"  Task scheduled: {task.get('scheduled')}", "ADD/MOD")
            
            self.add_message(
                "ERROR: Recurring task must have either 'due' or 'scheduled' date\n"
                f"       Provided: due={task.get('due')}, scheduled={task.get('scheduled')}"
            )
            return task
        
        task['ranchor'] = anchor_field
        
        # Convert wait, scheduled, and until to relative
        self.convert_wait_to_relative(task, anchor_field, anchor_date)
        self.convert_scheduled_to_relative(task, anchor_field, anchor_date)
        self.convert_until_to_relative(task, anchor_field, anchor_date)
        
        if DEBUG:
            debug_log(f"  Template created: status={task['status']}, rlast={task['rlast']}", "ADD/MOD")
        
        # Validate and cleanup - ensure no instance-only attributes
        warning = self.validate_and_cleanup(task, is_template_task=True)
        if warning:
            self.add_message(warning)
        
        # Note: Taskwarrior will output "Created task N (recurrence template)."
        # We don't need to add our own message here
        
        return task
    
    def handle_template_modification(self, original, modified):
        """Handle modifications to a template with auto-sync to instance
        
        Template modifications fall into two categories:
        1. Recurrence fields → Auto-sync parallel changes to current instance
        2. Non-recurrence fields → Inform user with suggested command
        
        Args:
            original: Original task state
            modified: Modified task state
            
        Returns:
            Updated modified task
        """
        if DEBUG:
            debug_log(f"Handling template modification: {modified.get('description')}", "ADD/MOD")
        
        task_id = modified.get('id', '?')
        description = modified.get('description', 'untitled')
        template_uuid = modified.get('uuid')
        
        # If template is being deleted/completed, remove r field so it can be purged
        if modified.get('status') in ['deleted', 'completed']:
            if 'r' in modified:
                del modified['r']
            self.add_message(
                f"Template {task_id} marked for deletion. Recurrence will stop."
            )
            return modified
        
        # Get current instance
        instance = None
        if template_uuid:
            instances = query_instances(template_uuid)
            if instances:
                instance = instances[0]  # Should only be one per one-to-one rule
        
        # Track recurrence field changes that need instance sync
        recurrence_changes = {}
        
        # Check for recurrence field changes
        recur_fields = ['r', 'type', 'ranchor', 'rlast', 'rend', 'rwait', 'rscheduled', 'runtil']
        for field in recur_fields:
            if field in modified and modified.get(field) != original.get(field):
                recurrence_changes[field] = {
                    'old': original.get(field),
                    'new': modified.get(field)
                }
        
        # Normalize type if it changed
        if 'type' in recurrence_changes:
            modified['type'] = normalize_type(modified['type'])
            recurrence_changes['type']['new'] = modified['type']
        
        # Auto-sync recurrence changes to instance
        if recurrence_changes and instance:
            if DEBUG:
                debug_log(f"Recurrence fields changed: {list(recurrence_changes.keys())}", "ADD/MOD")
            
            # Calculate what needs to be updated on the instance
            instance_updates = self.calculate_instance_updates(modified, instance, recurrence_changes)
            
            if instance_updates:
                # Check if instance already has these values
                needs_update = False
                for field, value in instance_updates.items():
                    if str(instance.get(field)) != str(value):
                        needs_update = True
                        break
                
                if needs_update:
                    # Write propagation instructions for on-exit to execute.
                    # We can't subprocess 'task modify' here because Taskwarrior
                    # holds a lock on pending.data during on-modify hook execution.
                    # on-exit runs AFTER the lock is released.
                    instance_uuid = instance['uuid']
                    
                    spool = {
                        'instance_uuid': instance_uuid,
                        'instance_rindex': instance.get('rindex', '?'),
                        'updates': instance_updates,
                        'template_id': task_id,
                        'changes': list(recurrence_changes.keys())
                    }
                    
                    spool_path = os.path.expanduser('~/.task/recurrence_propagate.json')
                    try:
                        with open(spool_path, 'w') as f:
                            json.dump(spool, f)
                        if DEBUG:
                            debug_log(f"Wrote propagation spool: {spool}", "ADD/MOD")
                        
                        field_list = ', '.join(recurrence_changes.keys())
                        self.add_message(
                            f"Template {task_id} modified: {field_list}\n"
                            f"Instance #{instance.get('rindex', '?')} will be synced."
                        )
                    except OSError as e:
                        if DEBUG:
                            debug_log(f"Failed to write propagation spool: {e}", "ADD/MOD")
                        self.add_message(
                            f"Template {task_id} modified: {', '.join(recurrence_changes.keys())}\n"
                            f"WARNING: Failed to queue instance sync. Manual sync may be needed."
                        )
                else:
                    if DEBUG:
                        debug_log(f"Instance already has target values, skipping update", "ADD/MOD")
                    field_list = ', '.join(recurrence_changes.keys())
                    self.add_message(
                        f"Template {task_id} modified: {field_list}\n"
                        f"Instance #{instance.get('rindex', '?')} already in sync."
                    )
            else:
                if DEBUG:
                    debug_log("No instance updates calculated", "ADD/MOD")
        
        elif recurrence_changes and not instance:
            # No instance exists - changes will apply to next spawn
            field_list = ', '.join(recurrence_changes.keys())
            if DEBUG:
                debug_log(f"Recurrence fields changed but no instance exists: {field_list}", "ADD/MOD")
            self.add_message(
                f"Template {task_id} modified: {field_list}\n"
                f"Changes will apply when next instance spawns."
            )
        
        # Check for non-recurrence field changes (inform only)
        non_recur_changes = []
        non_recur_fields = ['project', 'priority', 'tags', 'description']
        for field in non_recur_fields:
            if field in modified and modified.get(field) != original.get(field):
                non_recur_changes.append(field)
        
        if non_recur_changes and instance:
            # Suggest applying to current instance
            instance_id = instance.get('id', '?')
            mod_parts = []
            for field in non_recur_changes:
                if field == 'tags':
                    mod_parts.append(f"{field}:{','.join(modified[field])}")
                else:
                    mod_parts.append(f"{field}:{modified[field]}")
            
            self.add_message(
                f"Non-recurrence fields changed: {', '.join(non_recur_changes)}\n"
                f"To apply to current instance: task {instance_id} mod {' '.join(mod_parts)}"
            )
        
        # Validate and cleanup
        warning = self.validate_and_cleanup(modified, is_template_task=True)
        if warning:
            self.add_message(warning)
        
        return modified
    
    def calculate_instance_updates(self, template, instance, changes):
        """Calculate what needs to be updated on instance to match template changes
        
        Returns a dict of field:value updates to apply to the instance.
        The actual modification will be done via 'task modify' which triggers on-modify.
        
        Args:
            template: Modified template task dict
            instance: Current instance task dict
            changes: Dict of {field: {'old': old_val, 'new': new_val}}
            
        Returns:
            Dict of {field: value} to apply to instance
        """
        instance_updates = {}
        
        if DEBUG:
            debug_log(f"Calculating instance updates for changes: {list(changes.keys())}", "ADD/MOD")
        
        # Get current instance rindex (needed for date calculations)
        rindex = int(instance.get('rindex', 1))
        
        # If rlast changed, update instance rindex to match (TIME MACHINE)
        if 'rlast' in changes:
            new_rlast = int(changes['rlast']['new'])
            instance_updates['rindex'] = str(new_rlast)
            rindex = new_rlast  # Use new index for date calculations
            if DEBUG:
                debug_log(f"TIME MACHINE: rlast changed, will update rindex to {new_rlast}", "ADD/MOD")
        
        # Recalculate anchor date if r, ranchor, or rlast changed
        needs_date_recalc = any(f in changes for f in ['r', 'ranchor', 'rlast'])
        
        if needs_date_recalc:
            # Get recurrence parameters
            r_delta = parse_duration(template.get('r'))
            rtype = template.get('type', 'period')
            anchor_field = template.get('ranchor', 'due')
            actual_field = get_anchor_field_name(anchor_field)
            template_anchor = parse_date(template.get(actual_field))
            
            if r_delta and template_anchor:
                # Calculate new anchor date for this instance
                if rtype == 'period':
                    # Periodic: template_anchor + (rindex - 1) * period
                    new_anchor = template_anchor + (r_delta * (rindex - 1))
                else:
                    # Chained: Can't recalculate without completion time
                    # Just update the anchor field name if it changed
                    if 'ranchor' in changes:
                        new_anchor = template_anchor
                    else:
                        new_anchor = None
                
                if new_anchor:
                    instance_updates[actual_field] = format_date(new_anchor)
                    
                    # Recalculate relative dates if they exist
                    if 'rwait' in template:
                        wait_date = parse_relative_date(template['rwait'], new_anchor)
                        if wait_date:
                            instance_updates['wait'] = format_date(wait_date)
                    
                    if 'rscheduled' in template and anchor_field != 'sched':
                        sched_date = parse_relative_date(template['rscheduled'], new_anchor)
                        if sched_date:
                            instance_updates['scheduled'] = format_date(sched_date)
                    
                    if 'runtil' in template:
                        until_date = parse_relative_date(template['runtil'], new_anchor)
                        if until_date:
                            instance_updates['until'] = format_date(until_date)
                    
                    if DEBUG:
                        debug_log(f"Calculated new dates: {actual_field}={format_date(new_anchor)}", "ADD/MOD")
        
        # If only rwait/rscheduled/runtil changed (without anchor change), recalculate them
        relative_date_changes = any(f in changes for f in ['rwait', 'rscheduled', 'runtil'])
        if relative_date_changes and not needs_date_recalc:
            # Get current anchor date from instance
            anchor_field = template.get('ranchor', 'due')
            actual_field = get_anchor_field_name(anchor_field)
            instance_anchor = parse_date(instance.get(actual_field))
            
            if instance_anchor:
                if 'rwait' in changes and 'rwait' in template:
                    wait_date = parse_relative_date(template['rwait'], instance_anchor)
                    if wait_date:
                        instance_updates['wait'] = format_date(wait_date)
                
                if 'rscheduled' in changes and 'rscheduled' in template:
                    sched_date = parse_relative_date(template['rscheduled'], instance_anchor)
                    if sched_date:
                        instance_updates['scheduled'] = format_date(sched_date)
                
                if 'runtil' in changes and 'runtil' in template:
                    until_date = parse_relative_date(template['runtil'], instance_anchor)
                    if until_date:
                        instance_updates['until'] = format_date(until_date)
        
        if DEBUG and instance_updates:
            debug_log(f"Calculated instance updates: {instance_updates}", "ADD/MOD")
        
        return instance_updates
    
    def handle_instance_modification(self, original, modified):
        """Handle modifications to an instance with auto-sync to template
        
        Instance modifications:
        - rindex change → Auto-sync template rlast + recalculate dates (TIME MACHINE)
        - rtemplate change → REJECT (not allowed)
        - Non-recurrence fields → Inform with suggested command to apply to template
        
        Args:
            original: Original task state
            modified: Modified task state
            
        Returns:
            Updated modified task
        """
        if DEBUG:
            debug_log(f"Handling instance modification: {modified.get('description')}", "ADD/MOD")
        
        task_id = modified.get('id', '?')
        description = modified.get('description', 'untitled')
        rtemplate_uuid = modified.get('rtemplate', '')
        
        # REJECT rtemplate changes
        if 'rtemplate' in modified and modified.get('rtemplate') != original.get('rtemplate'):
            self.add_message(
                f"ERROR: Cannot modify rtemplate field.\n"
                f"  This would break the template-instance relationship."
            )
            # Restore original value
            modified['rtemplate'] = original.get('rtemplate')
        
        # Get template
        template = None
        if rtemplate_uuid:
            template = query_task(rtemplate_uuid)
        
        # Check for rindex change (TIME MACHINE from instance side)
        if 'rindex' in modified and modified['rindex'] != original.get('rindex'):
            old_rindex = int(original.get('rindex', 0))
            new_rindex = int(modified['rindex'])
            
            if template:
                template_id = template.get('id', '?')
                template_uuid = template.get('uuid')
                current_rlast = int(template.get('rlast', 0))
                
                if DEBUG:
                    debug_log(f"TIME MACHINE (instance): rindex {old_rindex} -> {new_rindex}, template rlast={current_rlast}", "ADD/MOD")
                
                # Only sync if template rlast doesn't already match
                if current_rlast != new_rindex:
                    # Spool the template sync for on-exit (same file-lock issue as template->instance)
                    spool = {
                        'instance_uuid': template_uuid,  # target is the template
                        'instance_rindex': f'template-{template_id}',
                        'updates': {'rlast': str(new_rindex)},
                        'template_id': template_id,
                        'changes': ['rlast (from instance rindex sync)']
                    }
                    
                    spool_path = os.path.expanduser('~/.task/recurrence_propagate.json')
                    try:
                        with open(spool_path, 'w') as f:
                            json.dump(spool, f)
                        if DEBUG:
                            debug_log(f"Wrote template sync spool: rlast -> {new_rindex}", "ADD/MOD")
                        
                        self.add_message(
                            f"Instance {task_id} rindex changed: {old_rindex} → {new_rindex}\n"
                            f"Template {template_id} rlast will be synced."
                        )
                    except OSError as e:
                        if DEBUG:
                            debug_log(f"Failed to write template sync spool: {e}", "ADD/MOD")
                        self.add_message(
                            f"Instance {task_id} rindex changed: {old_rindex} → {new_rindex}\n"
                            f"WARNING: Failed to queue template sync. Manual fix: task {template_id} mod rlast:{new_rindex}"
                        )
                else:
                    if DEBUG:
                        debug_log(f"Template rlast already matches {new_rindex}, skipping sync", "ADD/MOD")
                    self.add_message(
                        f"Instance {task_id} rindex changed: {old_rindex} → {new_rindex}\n"
                        f"Template {template_id} already in sync."
                    )
            else:
                self.add_message(
                    f"Instance {task_id} rindex changed but template not found.\n"
                    f"Manual sync required: task {rtemplate_uuid} mod rlast:{new_rindex}"
                )
        
        # Check for non-recurrence field changes (inform only)
        non_recur_changes = []
        non_recur_fields = ['project', 'priority', 'tags']
        for field in non_recur_fields:
            if field in modified and modified.get(field) != original.get(field):
                non_recur_changes.append(field)
        
        if non_recur_changes and template:
            template_id = template.get('id', '?')
            mod_parts = []
            for field in non_recur_changes:
                if field == 'tags':
                    mod_parts.append(f"{field}:{','.join(modified[field])}")
                else:
                    mod_parts.append(f"{field}:{modified[field]}")
            
            self.add_message(
                f"Non-recurrence fields changed: {', '.join(non_recur_changes)}\n"
                f"To apply to template (future instances): task {template_id} mod {' '.join(mod_parts)}"
            )
        
        # Validate and cleanup
        warning = self.validate_and_cleanup(modified, is_template_task=False)
        if warning:
            self.add_message(warning)
        
        return modified
    
    def handle_instance_completion(self, original, modified):
        """Handle completion/deletion of an instance with validation
        
        Args:
            original: Original task state
            modified: Modified task state
            
        Returns:
            Updated modified task
        """
        if DEBUG:
            debug_log(f"Handling instance completion: {modified.get('description')}", "ADD/MOD")
        
        # Check if being completed or deleted
        if modified.get('status') not in ['completed', 'deleted']:
            return modified
        
        task_id = modified.get('id', '?')
        description = modified.get('description', 'untitled')
        rindex = int(modified.get('rindex', 0))
        rtemplate_uuid = modified.get('rtemplate', '')
        
        status_word = 'Completed' if modified['status'] == 'completed' else 'Deleted'
        messages = []
        
        # Query template to check rlast and detect issues
        template = None
        template_id = None
        template_rlast = None
        
        if rtemplate_uuid:
            template = query_task(rtemplate_uuid)
            if template:
                template_id = template.get('id', '?')
                template_rlast = int(template.get('rlast', 0))
        
        if template:
            # Check for rlast/rindex desync
            if template_rlast != rindex:
                messages.append(
                    f"WARNING: Instance rindex={rindex} doesn't match template rlast={template_rlast}\n"
                    f"  This may indicate out-of-order completion or missed instances."
                )
                if DEBUG:
                    debug_log(f"Completion desync: rindex={rindex}, rlast={template_rlast}", "ADD/MOD")
            
            # Check if any pending instances exist
            instances = query_instances(rtemplate_uuid)
            
            if not instances:
                # No pending instances exist!
                messages.append(
                    f"ERROR: No pending instances exist for this template.\n"
                    f"  On-exit hook should spawn next instance, but may need manual intervention."
                )
                if DEBUG:
                    debug_log(f"No pending instances found for template {template_id}", "ADD/MOD")
            else:
                if DEBUG:
                    debug_log(f"Found {len(instances)} pending instance(s) for template {template_id}", "ADD/MOD")
        
        # Build final message
        msg = f"{status_word} task {task_id} -- {description} (instance #{rindex})\n"
        if template_id:
            msg += f"  Template: task {template_id}"
        else:
            msg += f"  Template: {rtemplate_uuid}"
        
        if messages:
            msg += "\n" + "\n".join(messages)
        
        self.add_message(msg)
        
        if DEBUG:
            debug_log(f"Instance {rindex} {status_word.lower()}", "ADD/MOD")
        
        # Validate and cleanup - ensure no template-only attributes
        warning = self.validate_and_cleanup(modified, is_template_task=False)
        if warning:
            self.add_message(warning)
        
        return modified


def main():
    """Main hook entry point"""
    if not lines:
        sys.exit(0)
    
    # Re-entrancy guard: if we're being called from a template->instance propagation,
    # just pass the modified task through without any recurrence logic.
    # This prevents infinite recursion when handle_template_modification() subprocess
    # calls 'task modify' on the instance, which triggers this hook again.
    if PROPAGATING:
        if DEBUG:
            debug_log("PROPAGATION pass-through (re-entrant call, skipping recurrence logic)", "ADD/MOD")
        if IS_ON_ADD:
            print(json.dumps(json.loads(lines[0])))
        else:
            if len(lines) >= 2:
                print(json.dumps(json.loads(lines[1])))
            elif lines:
                print(json.dumps(json.loads(lines[0])))
        sys.exit(0)
    
    handler = RecurrenceHandler()
    
    if IS_ON_ADD:
        # On-add: single task input
        try:
            task = json.loads(lines[0])
        except json.JSONDecodeError as e:
            sys.stderr.write(f"Error parsing JSON: {e}\n")
            sys.exit(1)
        
        # Check if this should be a template (but not if being deleted)
        if 'r' in task and task.get('status') != 'deleted':
            task = handler.create_template(task)
        
        print(json.dumps(task))
        handler.output_messages()
    
    else:
        # On-modify: two task inputs
        if len(lines) < 2:
            if lines:
                print(json.dumps(json.loads(lines[0])))
            sys.exit(0)
        
        try:
            original = json.loads(lines[0])
            modified = json.loads(lines[1])
        except json.JSONDecodeError as e:
            sys.stderr.write(f"Error parsing JSON: {e}\n")
            sys.exit(1)
        
        # Adding recurrence to existing task? (but not if being deleted)
        if 'r' in modified and 'r' not in original and modified.get('status') != 'deleted':
            modified = handler.create_template(modified)
        
        # Modifying a template?
        elif is_template(original):
            modified = handler.handle_template_modification(original, modified)
        
        # Modifying an instance?
        elif is_instance(original):
            # Check if being completed/deleted
            if modified.get('status') in ['completed', 'deleted']:
                modified = handler.handle_instance_completion(original, modified)
            else:
                modified = handler.handle_instance_modification(original, modified)
        
        print(json.dumps(modified))
        handler.output_messages()
    
    if DEBUG:
        debug_log("Hook completed", "ADD/MOD")
    
    sys.exit(0)


if __name__ == '__main__':
    main()
