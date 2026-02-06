#!/usr/bin/env python3
"""
Taskwarrior Enhanced Recurrence Hook - On-Add/On-Modify
Version: 0.4.1
Date: 2026-02-06

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
import json
import os
import re
import subprocess

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
        """Handle modifications to a template with comprehensive feedback
        
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
        
        # Track what changed
        changes = []
        
        # If template is being deleted/completed, remove r field so it can be purged
        if modified.get('status') in ['deleted', 'completed']:
            if 'r' in modified:
                del modified['r']
            self.add_message(
                f"Modified task {task_id} -- {description} (recurrence template)\n"
                f"Template marked for deletion. Recurrence will stop."
            )
            return modified
        
        # Check for type change
        if 'type' in modified and modified['type'] != original.get('type'):
            old_type = original.get('type', 'period')
            new_type = normalize_type(modified['type'])
            modified['type'] = new_type
            
            spawn_behavior = {
                'period': 'on anchor date arrival',
                'chain': 'on completion of current instance'
            }
            
            changes.append(
                f"Modified template type: {old_type} Ã¢â€ â€™ {new_type}\n"
                f"  This changes how future instances spawn ({spawn_behavior[new_type]}).\n"
                f"  Current rlast={modified.get('rlast', '0')} preserved."
            )
            
            if DEBUG:
                debug_log(f"Type changed: {old_type} -> {new_type}", "ADD/MOD")
        
        # Check for recurrence interval change
        if 'r' in modified and modified['r'] != original.get('r'):
            old_r = original.get('r', '')
            new_r = modified['r']
            
            changes.append(
                f"Modified recurrence interval: {old_r} Ã¢â€ â€™ {new_r}\n"
                f"  This changes the spacing between future instances."
            )
            
            if DEBUG:
                debug_log(f"Recurrence interval changed: {old_r} -> {new_r}", "ADD/MOD")
        
        # Check for anchor change (due Ã¢â€ â€� sched)
        old_anchor = original.get('ranchor')
        new_anchor_field, new_anchor_date = self.get_anchor_date(modified)
        
        if new_anchor_field and old_anchor and new_anchor_field != old_anchor:
            # Update ranchor
            modified['ranchor'] = new_anchor_field
            
            # Update all relative date references
            updated_fields = self.update_relative_dates_for_anchor_change(
                modified, old_anchor, new_anchor_field
            )
            
            updated_str = ', '.join(updated_fields) if updated_fields else 'none'
            
            changes.append(
                f"Modified template anchor: {old_anchor} Ã¢â€ â€™ {new_anchor_field}\n"
                f"  Relative dates ({updated_str}) updated to use new anchor."
            )
            
            if DEBUG:
                debug_log(f"Anchor changed: {old_anchor} -> {new_anchor_field}", "ADD/MOD")
        
        # Check for rlast change (time machine)
        if 'rlast' in modified and modified['rlast'] != original.get('rlast'):
            old_rlast = int(original.get('rlast', 0))
            new_rlast = int(modified['rlast'])
            delta = new_rlast - old_rlast
            direction = "forward" if delta > 0 else "backward"
            
            type_str = modified.get('type', 'period')
            
            # Use targeted checking - only check THIS template's instances
            template_uuid = modified.get('uuid')
            sync_msg = None
            
            if template_uuid:
                status, data = check_instance_count(template_uuid)
                
                if status == 'missing':
                    # No instance exists - will spawn on next task command via on-exit
                    if DEBUG:
                        debug_log(f"No instance found for template {template_uuid}", "ADD/MOD")
                    
                    sync_msg = (
                        f"  No pending instance exists.\n"
                        f"  On-exit hook will spawn instance #{new_rlast} when this template's instance completes."
                    )
                
                elif status == 'ok':
                    # CORRECT: Exactly one instance exists
                    # MODIFY the instance (don't delete/respawn)
                    instance = data
                    
                    inst_uuid = instance['uuid']
                    inst_id = instance.get('id', '?')
                    old_inst_rindex = int(instance.get('rindex', 0))
                    
                    if DEBUG:
                        debug_log(f"Updating instance #{old_inst_rindex} to #{new_rlast} (time machine)", "ADD/MOD")
                    
                    # Update the instance in place
                    if update_instance_for_rlast_change(modified, instance, old_rlast, new_rlast):
                        sync_msg = (
                            f"  Instance #{old_inst_rindex} (task {inst_id}) updated to #{new_rlast}\n"
                            f"  Due date recalculated for new sequence position."
                        )
                    else:
                        sync_msg = (
                            f"  WARNING: Failed to update instance #{old_inst_rindex} (task {inst_id})\n"
                            f"  Template rlast changed but instance may be out of sync.\n"
                            f"  Manual fix: task {inst_id} modify rindex:{new_rlast}"
                        )
                
                elif status == 'multiple':
                    # ERROR: Multiple instances exist (violates one-to-one rule - data corruption)
                    instances = data
                    
                    if DEBUG:
                        debug_log(f"Multiple instances found for template {template_uuid}: {len(instances)}", "ADD/MOD")
                    
                    inst_list = ', '.join([f"task {inst.get('id', '?')} (rindex={inst.get('rindex', '?')})" 
                                          for inst in instances])
                    
                    sync_msg = (
                        f"  ERROR: Multiple instances exist (violates one-to-one rule - DATA CORRUPTION)\n"
                        f"  Expected: Exactly 1 instance\n"
                        f"  Found: {len(instances)} instances: {inst_list}\n"
                        f"  This indicates a serious bug or external data corruption.\n"
                        f"  Manual fix required:\n"
                        f"    1. Decide which instance to keep (usually the one with rindex={new_rlast})\n"
                        f"    2. Delete the others: task <id> delete\n"
                        f"    3. Ensure remaining instance has rindex={new_rlast}\n"
                        f"  Or delete all and let on-exit spawn fresh: task {' '.join([str(i.get('id')) for i in instances])} delete"
                    )
            
            if type_str == 'period':
                # Calculate next instance date for period types
                anchor_field, anchor_date = self.get_anchor_date(modified)
                if anchor_date and 'r' in modified:
                    r_delta = parse_duration(modified['r'])
                    if r_delta:
                        from datetime import timedelta
                        next_date = anchor_date + (r_delta * (new_rlast + 1))
                        next_date_str = format_date(next_date)
                        
                        msg = f"Template rlast modified: {old_rlast} Ã¢â€ â€™ {new_rlast} ({abs(delta)} instances {direction})\n"
                        msg += f"  Next instance will be #{new_rlast + 1} due {next_date_str}"
                        if sync_msg:
                            msg += f"\n{sync_msg}"
                        changes.append(msg)
                    else:
                        msg = f"Template rlast modified: {old_rlast} Ã¢â€ â€™ {new_rlast} ({abs(delta)} instances {direction})\n"
                        msg += f"  Next instance will be #{new_rlast + 1}"
                        if sync_msg:
                            msg += f"\n{sync_msg}"
                        changes.append(msg)
                else:
                    msg = f"Template rlast modified: {old_rlast} Ã¢â€ â€™ {new_rlast} ({abs(delta)} instances {direction})"
                    if sync_msg:
                        msg += f"\n{sync_msg}"
                    changes.append(msg)
            else:
                # Chain type
                msg = f"Template rlast modified: {old_rlast} Ã¢â€ â€™ {new_rlast}\n"
                msg += f"  Next instance will be #{new_rlast + 1} (spawns on completion)."
                if sync_msg:
                    msg += f"\n{sync_msg}"
                changes.append(msg)
            
            if DEBUG:
                debug_log(f"rlast changed: {old_rlast} -> {new_rlast}", "ADD/MOD")
        
        # Check for rend change
        if 'rend' in modified and modified.get('rend') != original.get('rend'):
            old_rend = original.get('rend', 'none')
            new_rend = modified['rend']
            
            changes.append(
                f"Modified recurrence end: {old_rend} Ã¢â€ â€™ {new_rend}\n"
                f"  Template will stop repeating after this limit."
            )
            
            if DEBUG:
                debug_log(f"rend changed: {old_rend} -> {new_rend}", "ADD/MOD")
        
        # Check for wait modifications (absolute Ã¢â€ â€™ relative conversion)
        anchor_field, anchor_date = self.get_anchor_date(modified)
        if anchor_field and anchor_date:
            self.convert_wait_to_relative(modified, anchor_field, anchor_date)
        
        # Check for anchor date changes (the actual due/scheduled date value)
        if anchor_field:
            old_anchor_date = None
            if anchor_field == 'due' and 'due' in original:
                old_anchor_date = parse_date(original['due'])
            elif anchor_field == 'sched' and 'scheduled' in original:
                old_anchor_date = parse_date(original['scheduled'])
            
            if old_anchor_date and anchor_date and old_anchor_date != anchor_date:
                type_str = modified.get('type', 'period')
                
                if type_str == 'period':
                    changes.append(
                        f"Modified template {anchor_field} date: {format_date(old_anchor_date)} Ã¢â€ â€™ {format_date(anchor_date)}\n"
                        f"  This shifts all future instances by the same offset."
                    )
                else:
                    changes.append(
                        f"Modified template {anchor_field} date: {format_date(old_anchor_date)} Ã¢â€ â€™ {format_date(anchor_date)}\n"
                        f"  This affects next instance only (chain type)."
                    )
                
                if DEBUG:
                    debug_log(f"Anchor date changed: {old_anchor_date} -> {anchor_date}", "ADD/MOD")
        
        # Check for non-recurrence attribute changes (suggest propagation to current instance)
        non_recurrence_attrs = ['project', 'priority', 'tags', 'description']
        attr_changes = []
        
        for attr in non_recurrence_attrs:
            if attr in modified and modified.get(attr) != original.get(attr):
                attr_changes.append(attr)
        
        if attr_changes:
            attr_list = ', '.join(attr_changes)
            
            # Try to find current instance to provide specific command
            template_uuid = modified.get('uuid')
            current_instance_id = None
            
            if template_uuid:
                instances = query_instances(template_uuid)
                rlast = int(modified.get('rlast', 0))
                
                # Find instance with rindex matching rlast
                for inst in instances:
                    if int(inst.get('rindex', 0)) == rlast:
                        current_instance_id = inst.get('id')
                        break
            
            if current_instance_id:
                # Build modification command for specific instance
                mod_cmd_parts = []
                for attr in attr_changes:
                    if attr == 'tags':
                        # Tags need special handling
                        mod_cmd_parts.append(f"{attr}:{','.join(modified[attr])}")
                    else:
                        mod_cmd_parts.append(f"{attr}:{modified[attr]}")
                
                changes.append(
                    f"Modified template attributes: {attr_list}\n"
                    f"  This will affect future instances. To apply to current instance #{rlast}:\n"
                    f"  task {current_instance_id} mod {' '.join(mod_cmd_parts)}"
                )
            else:
                changes.append(
                    f"Modified template attributes: {attr_list}\n"
                    f"  This will affect future instances. To apply to current instance:\n"
                    f"  Find current instance and apply the same modifications."
                )
        
        # Output comprehensive message
        if changes:
            msg = f"Modified task {task_id} -- {description} (recurrence template)\n"
            msg += "\n".join(changes)
            self.add_message(msg)
        
        # Validate and cleanup - ensure no instance-only attributes
        warning = self.validate_and_cleanup(modified, is_template_task=True)
        if warning:
            self.add_message(warning)
        
        return modified
    
    def handle_instance_modification(self, original, modified):
        """Handle modifications to an instance with rindex Ã¢â€ â€� rlast sync
        
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
        
        # Track changes
        changes = []
        
        # Query template to check current rlast and detect desync
        template = None
        template_id = None
        template_rlast = None
        
        if rtemplate_uuid:
            template = query_task(rtemplate_uuid)
            if template:
                template_id = template.get('id', '?')
                template_rlast = int(template.get('rlast', 0))
                
                # Check one-to-one rule: use targeted checking for THIS template only
                status, data = check_instance_count(rtemplate_uuid)
                
                if status == 'multiple':
                    # ERROR: Multiple instances exist (violates one-to-one rule)
                    instances = data
                    inst_list = ', '.join([f"task {inst.get('id', '?')} (rindex={inst.get('rindex', '?')})" 
                                          for inst in instances])
                    
                    changes.append(
                        f"ERROR: Multiple instances exist (violates one-to-one rule - DATA CORRUPTION)\n"
                        f"  Expected: Exactly 1 instance\n"
                        f"  Found: {len(instances)} instances: {inst_list}\n"
                        f"  This indicates a serious bug or external data corruption.\n"
                        f"  Manual fix required:\n"
                        f"    1. Decide which instance to keep\n"
                        f"    2. Delete the others: task <id> delete\n"
                        f"    3. Ensure remaining instance has rindex matching template rlast={template_rlast}"
                    )
                    
                    if DEBUG:
                        debug_log(f"ERROR: Multiple instances detected for template {rtemplate_uuid}: {len(instances)}", "ADD/MOD")
        
        # Check for rindex change (must sync with template rlast)
        if 'rindex' in modified and modified['rindex'] != original.get('rindex'):
            old_rindex = int(original.get('rindex', 0))
            new_rindex = int(modified['rindex'])
            
            # Auto-sync template rlast to match new rindex
            if template:
                # Check for desync first
                if template_rlast != old_rindex:
                    changes.append(
                        f"WARNING: Detected desync - instance rindex={old_rindex} but template rlast={template_rlast}\n"
                        f"  Auto-fixing: Template rlast will be updated to {new_rindex}"
                    )
                    if DEBUG:
                        debug_log(f"Desync detected: rindex={old_rindex}, rlast={template_rlast}", "ADD/MOD")
                
                # Update template rlast
                if update_task(rtemplate_uuid, {'rlast': new_rindex}):
                    if DEBUG:
                        debug_log(f"Auto-synced template {template_id} rlast: {template_rlast} -> {new_rindex}", "ADD/MOD")
                    
                    changes.append(
                        f"Modified instance rindex: {old_rindex} Ã¢â€ â€™ {new_rindex}\n"
                        f"  Template rlast auto-synced to {new_rindex}."
                    )
                else:
                    changes.append(
                        f"Modified instance rindex: {old_rindex} Ã¢â€ â€™ {new_rindex}\n"
                        f"  WARNING: Failed to auto-sync template rlast. Manual sync needed:\n"
                        f"  task {template_id} mod rlast:{new_rindex}"
                    )
            else:
                # Could not query template
                changes.append(
                    f"Modified instance rindex: {old_rindex} Ã¢â€ â€™ {new_rindex}\n"
                    f"  Template rlast should be synced to {new_rindex}.\n"
                    f"  Update template with: task {rtemplate_uuid} mod rlast:{new_rindex}"
                )
            
            if DEBUG:
                debug_log(f"rindex changed: {old_rindex} -> {new_rindex}", "ADD/MOD")
        else:
            # No rindex change, but check for desync
            if template and template_rlast is not None:
                current_rindex = int(modified.get('rindex', 0))
                if template_rlast != current_rindex:
                    # Detected desync - auto-fix it
                    if update_task(rtemplate_uuid, {'rlast': current_rindex}):
                        changes.append(
                            f"WARNING: Detected desync - instance rindex={current_rindex} but template rlast={template_rlast}\n"
                            f"  Auto-fixed: Template rlast updated to {current_rindex}"
                        )
                        if DEBUG:
                            debug_log(f"Auto-fixed desync: updated rlast {template_rlast} -> {current_rindex}", "ADD/MOD")
        
        # Check for non-recurrence attribute changes (suggest propagation to template)
        non_recurrence_attrs = ['project', 'priority', 'tags']
        attr_changes = []
        attr_mod_parts = []
        
        for attr in non_recurrence_attrs:
            if attr in modified and modified.get(attr) != original.get(attr):
                attr_changes.append(attr)
                if attr == 'tags':
                    attr_mod_parts.append(f"{attr}:{','.join(modified[attr])}")
                else:
                    attr_mod_parts.append(f"{attr}:{modified[attr]}")
        
        if attr_changes:
            rindex = modified.get('rindex', '?')
            attr_list = ', '.join(attr_changes)
            
            if template_id:
                changes.append(
                    f"Modified instance attributes: {attr_list}\n"
                    f"  To apply this change to all future instances:\n"
                    f"  task {template_id} mod {' '.join(attr_mod_parts)}"
                )
            else:
                changes.append(
                    f"Modified instance attributes: {attr_list}\n"
                    f"  To apply this change to all future instances:\n"
                    f"  task {rtemplate_uuid} mod {' '.join(attr_mod_parts)}"
                )
        
        # Output message
        if changes:
            rindex = modified.get('rindex', '?')
            msg = f"Modified task {task_id} -- {description} (instance #{rindex})\n"
            msg += "\n".join(changes)
            self.add_message(msg)
        
        # Validate and cleanup - ensure no template-only attributes
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
