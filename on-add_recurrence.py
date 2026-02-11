#!/usr/bin/env python3
"""
Taskwarrior Enhanced Recurrence Hook - On-Add/On-Modify
Version: 2.6.3
Date: 2026-02-08

Handles both adding new recurring tasks and modifying existing ones with
sophisticated modification tracking and user feedback.

Features:
- Template creation with type normalization
- Smart modification detection and handling
- Bidirectional rindex ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÂ¢Ã¢â€šÂ¬Ã¯Â¿Â½ rlast synchronization
- Anchor change detection with automatic rwait/rscheduled updates
- Time machine functionality (rlast/rindex modifications)
- User-friendly aliases (wait->rwait, scheduled->rscheduled, until->runtil)
- Comprehensive user messaging
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
        query_instances, check_instance_count, query_task,
        # Validation functions
        strip_legacy_recurrence, validate_recurrence_integers,
        validate_template_requirements, validate_date_logic,
        validate_instance_integrity, validate_no_instance_fields_on_template,
        validate_no_r_on_instance, validate_no_rtemplate_change,
        validate_no_absolute_dates_on_template,
        # Attribute categories
        TEMPLATE_ONLY, INSTANCE_ONLY, LEGACY_RECURRENCE
    )
except ImportError as e:
    # Fallback error handling
    sys.stderr.write(f"ERROR: Cannot import recurrence_common_hook: {e}\n")
    sys.stderr.write("Please ensure recurrence_common_hook.py is in ~/.task/hooks/\n")
    sys.exit(1)


# Read all input
lines = sys.stdin.readlines()
IS_ON_ADD = len(lines) == 1

if DEBUG:
    debug_log("="*60, "ADD/MOD")
    debug_log(f"Hook starting - Mode: {'ADD' if IS_ON_ADD else 'MODIFY'}, lines: {len(lines)}", "ADD/MOD")


class RecurrenceHandler:
    """Handles enhanced recurrence for Taskwarrior"""
    
    # Use imported constants from common module
    TEMPLATE_ONLY_ATTRS = TEMPLATE_ONLY
    INSTANCE_ONLY_ATTRS = INSTANCE_ONLY
    
    def __init__(self):
        self.messages = []  # Collect messages to output at end
        self.errors = []    # Collect blocking errors
    
    def add_message(self, message):
        """Add a message to be output to user"""
        self.messages.append(message)
    
    def add_error(self, error):
        """Add a blocking error"""
        self.errors.append(error)
    
    def has_errors(self):
        """Check if any blocking errors exist"""
        return len(self.errors) > 0
    
    def output_messages(self):
        """Output all collected messages to stderr"""
        # Output errors first
        if self.errors:
            for msg in self.errors:
                sys.stderr.write(f"{msg}\n")
        
        # Then warnings/info
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
        
        # VALIDATION PHASE
        # ================
        
        # Strip legacy recurrence fields
        legacy_warnings = strip_legacy_recurrence(task)
        for warning in legacy_warnings:
            self.add_message(warning)
        
        # Validate no instance-only fields
        instance_field_errors = validate_no_instance_fields_on_template(task)
        for error in instance_field_errors:
            self.add_error(error)
        
        # Validate template requirements (r, anchor, period format)
        template_errors = validate_template_requirements(task)
        for error in template_errors:
            self.add_error(error)
        
        # If critical errors, stop here
        if self.has_errors():
            return task
        
        # Validate integer fields (rlast if present)
        int_errors = validate_recurrence_integers(task)
        for error in int_errors:
            self.add_error(error)
        
        if self.has_errors():
            return task
        
        # TEMPLATE CREATION
        # =================
        
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
            
            self.add_error(
                "ERROR: Recurring task must have either 'due' or 'scheduled' date\n"
                f"       Provided: due={task.get('due')}, scheduled={task.get('scheduled')}"
            )
            return task
        
        task['ranchor'] = anchor_field
        
        # Convert wait, scheduled, and until to relative
        self.convert_wait_to_relative(task, anchor_field, anchor_date)
        self.convert_scheduled_to_relative(task, anchor_field, anchor_date)
        self.convert_until_to_relative(task, anchor_field, anchor_date)
        
        # Validate date logic (wait before anchor, until after anchor)
        date_errors = validate_date_logic(task, is_template=True)
        for error in date_errors:
            self.add_error(error)
        
        if self.has_errors():
            return task
        
        if DEBUG:
            debug_log(f"  Template created: status={task['status']}, rlast={task['rlast']}", "ADD/MOD")
        
        # Validate and cleanup - ensure no instance-only attributes
        warning = self.validate_and_cleanup(task, is_template_task=True)
        if warning:
            self.add_message(warning)
        
        # Note: Taskwarrior will output "Created task N (recurrence template)."
        # We don't need to add our own message here
        
        return task
    
    def expand_template_aliases(self, original, modified):
        """Expand user-friendly aliases to internal field names on templates.
        
        Users can type: wait:due-30m, sched:due-2d, until:due+7d, last:3, index:5, anchor:due
        Hook translates to: rwait:due-30m, rscheduled:due-2d, runtil:due+7d, rlast:3, rindex:5, ranchor:due
        
        Also converts absolute dates to relative offsets from anchor.
        
        Args:
            original: Original task state (to detect changes)
            modified: Modified task state (modified in place)
            
        Returns:
            List of alias expansions performed (for logging)
        """
        expanded = []
        
        # PROACTIVE CLEANUP: If template has BOTH absolute and relative (legacy edge case),
        # prioritize relative and remove absolute regardless of whether it changed
        if 'rwait' in modified and 'wait' in modified:
            del modified['wait']
            expanded.append(f'wait (absolute) removed - rwait exists (cleanup)')
            if DEBUG:
                debug_log(f"Proactive cleanup: removed wait (rwait exists)", "ADD/MOD")
        
        if 'rscheduled' in modified and 'scheduled' in modified:
            anchor = modified.get('ranchor', 'due')
            if anchor != 'sched':  # Only cleanup if scheduled is not the anchor
                del modified['scheduled']
                expanded.append(f'scheduled (absolute) removed - rscheduled exists (cleanup)')
                if DEBUG:
                    debug_log(f"Proactive cleanup: removed scheduled (rscheduled exists)", "ADD/MOD")
        
        if 'runtil' in modified and 'until' in modified:
            del modified['until']
            expanded.append(f'until (absolute) removed - runtil exists (cleanup)')
            if DEBUG:
                debug_log(f"Proactive cleanup: removed until (runtil exists)", "ADD/MOD")
        
        # Get anchor info for date conversions
        anchor_field = modified.get('ranchor', 'due')
        anchor_date = None
        if anchor_field == 'sched':
            anchor_date = parse_date(modified.get('scheduled'))
        else:
            anchor_date = parse_date(modified.get('due'))
        
        # last -> rlast
        if 'last' in modified and modified.get('last') != original.get('last'):
            modified['rlast'] = modified['last']
            del modified['last']
            expanded.append(f'last->rlast ({modified["rlast"]})')
            if DEBUG:
                debug_log(f"Alias expanded: last -> rlast: {modified['rlast']}", "ADD/MOD")
        
        # index -> rindex (for TIME MACHINE operations)
        if 'index' in modified and modified.get('index') != original.get('index'):
            modified['rindex'] = modified['index']
            del modified['index']
            expanded.append(f'index->rindex ({modified["rindex"]})')
            if DEBUG:
                debug_log(f"Alias expanded: index -> rindex: {modified['rindex']}", "ADD/MOD")
        
        # anchor -> ranchor
        if 'anchor' in modified and modified.get('anchor') != original.get('anchor'):
            modified['ranchor'] = modified['anchor']
            del modified['anchor']
            expanded.append(f'anchor->ranchor ({modified["ranchor"]})')
            if DEBUG:
                debug_log(f"Alias expanded: anchor -> ranchor: {modified['ranchor']}", "ADD/MOD")
        
        # wait -> rwait (handle both relative and absolute)
        if 'wait' in modified and modified.get('wait') != original.get('wait'):
            wait_val = str(modified['wait'])
            ref_field, offset = parse_relative_date(wait_val)
            
            if ref_field and offset:
                # Already relative - just rename
                if 'rwait' in modified:
                    self.add_error(f"ERROR: Template has both 'wait' and 'rwait' - use only rwait")
                    return expanded
                modified['rwait'] = wait_val
                del modified['wait']
                expanded.append(f'wait->rwait ({wait_val})')
                if DEBUG:
                    debug_log(f"Alias expanded: wait -> rwait: {wait_val}", "ADD/MOD")
            else:
                # Absolute date - convert to relative
                if 'rwait' in modified:
                    # rwait exists, just cleanup absolute wait
                    del modified['wait']
                    expanded.append(f'wait (absolute) removed - rwait exists')
                    if DEBUG:
                        debug_log(f"Removed absolute wait (rwait exists): {wait_val}", "ADD/MOD")
                elif anchor_date:
                    # Convert to relative offset
                    wait_date = parse_date(wait_val)
                    if wait_date:
                        delta_sec = int((wait_date - anchor_date).total_seconds())
                        modified['rwait'] = f'{anchor_field}{delta_sec:+d}s'
                        del modified['wait']
                        expanded.append(f'wait (absolute) -> rwait ({modified["rwait"]})')
                        if DEBUG:
                            debug_log(f"Converted absolute wait to rwait: {wait_val} -> {modified['rwait']}", "ADD/MOD")
        
        # scheduled/sched -> rscheduled (handle both relative and absolute)
        for alias in ['scheduled', 'sched']:
            if alias in modified and modified.get(alias) != original.get(alias):
                sched_val = str(modified[alias])
                ref_field, offset = parse_relative_date(sched_val)
                
                if ref_field and offset:
                    # Already relative - just rename
                    if 'rscheduled' in modified:
                        self.add_error(f"ERROR: Template has both '{alias}' and 'rscheduled' - use only rscheduled")
                        return expanded
                    modified['rscheduled'] = sched_val
                    del modified[alias]
                    expanded.append(f'{alias}->rscheduled ({sched_val})')
                    if DEBUG:
                        debug_log(f"Alias expanded: {alias} -> rscheduled: {sched_val}", "ADD/MOD")
                else:
                    # Absolute date - convert to relative
                    if 'rscheduled' in modified:
                        # rscheduled exists, just cleanup absolute
                        del modified[alias]
                        expanded.append(f'{alias} (absolute) removed - rscheduled exists')
                        if DEBUG:
                            debug_log(f"Removed absolute {alias} (rscheduled exists): {sched_val}", "ADD/MOD")
                    elif anchor_date and anchor_field != 'sched':
                        # Convert to relative offset (only if anchor is not sched itself)
                        sched_date = parse_date(sched_val)
                        if sched_date:
                            delta_sec = int((sched_date - anchor_date).total_seconds())
                            modified['rscheduled'] = f'{anchor_field}{delta_sec:+d}s'
                            del modified[alias]
                            expanded.append(f'{alias} (absolute) -> rscheduled ({modified["rscheduled"]})')
                            if DEBUG:
                                debug_log(f"Converted absolute {alias} to rscheduled: {sched_val} -> {modified['rscheduled']}", "ADD/MOD")
                break  # Only process one alias
        
        # until -> runtil (handle both relative and absolute)
        if 'until' in modified and modified.get('until') != original.get('until'):
            until_val = str(modified['until'])
            ref_field, offset = parse_relative_date(until_val)
            
            if ref_field and offset:
                # Already relative - just rename
                if 'runtil' in modified:
                    self.add_error(f"ERROR: Template has both 'until' and 'runtil' - use only runtil")
                    return expanded
                modified['runtil'] = until_val
                del modified['until']
                expanded.append(f'until->runtil ({until_val})')
                if DEBUG:
                    debug_log(f"Alias expanded: until -> runtil: {until_val}", "ADD/MOD")
            else:
                # Absolute date - convert to relative
                if 'runtil' in modified:
                    # runtil exists, just cleanup absolute until
                    del modified['until']
                    expanded.append(f'until (absolute) removed - runtil exists')
                    if DEBUG:
                        debug_log(f"Removed absolute until (runtil exists): {until_val}", "ADD/MOD")
                elif anchor_date:
                    # Convert to relative offset
                    until_date = parse_date(until_val)
                    if until_date:
                        delta_sec = int((until_date - anchor_date).total_seconds())
                        modified['runtil'] = f'{anchor_field}{delta_sec:+d}s'
                        del modified['until']
                        expanded.append(f'until (absolute) -> runtil ({modified["runtil"]})')
                        if DEBUG:
                            debug_log(f"Converted absolute until to runtil: {until_val} -> {modified['runtil']}", "ADD/MOD")
        
        return expanded
    
    def handle_template_modification(self, original, modified):
        """Handle modifications to a template with auto-sync to instance
        
        Template modifications fall into two categories:
        1. Recurrence fields Ã¢â€ â€™ Auto-sync parallel changes to current instance
        2. Non-recurrence fields Ã¢â€ â€™ Inform user with suggested command
        
        Args:
            original: Original task state
            modified: Modified task state
            
        Returns:
            Updated modified task
        """
        if DEBUG:
            debug_log(f"Handling template modification: {modified.get('description')}", "ADD/MOD")
        
        # Expand user-friendly aliases (waitÃ¢â€ â€™rwait, lastÃ¢â€ â€™rlast, tyÃ¢â€ â€™type, etc.)
        expansions = self.expand_template_aliases(original, modified)
        
        
        # Validate no absolute dates remain on template after alias expansion
        absolute_errors = validate_no_absolute_dates_on_template(modified)
        for error in absolute_errors:
            self.add_error(error)
        
        if self.has_errors():
            return modified
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
        - rindex change Ã¢â€ â€™ Auto-sync template rlast + recalculate dates (TIME MACHINE)
        - rtemplate change Ã¢â€ â€™ REJECT (not allowed)
        - Non-recurrence fields Ã¢â€ â€™ Inform with suggested command to apply to template
        
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
                
                # Recalculate instance dates in-place (we CAN modify 'modified' directly)
                r_delta = parse_duration(template.get('r'))
                rtype = template.get('type', 'period')
                anchor_field = template.get('ranchor', 'due')
                actual_field = get_anchor_field_name(anchor_field)
                template_anchor = parse_date(template.get(actual_field))
                
                if r_delta and template_anchor:
                    if rtype == 'period':
                        new_anchor = template_anchor + (r_delta * (new_rindex - 1))
                    else:
                        # Chained: best approximation without completion time
                        new_anchor = template_anchor + (r_delta * (new_rindex - 1))
                    
                    modified[actual_field] = format_date(new_anchor)
                    
                    # Recalculate relative dates
                    if 'rwait' in template:
                        wait_date = parse_relative_date(template['rwait'], new_anchor)
                        if wait_date:
                            modified['wait'] = format_date(wait_date)
                    
                    if 'rscheduled' in template and anchor_field != 'sched':
                        sched_date = parse_relative_date(template['rscheduled'], new_anchor)
                        if sched_date:
                            modified['scheduled'] = format_date(sched_date)
                    
                    if 'runtil' in template:
                        until_date = parse_relative_date(template['runtil'], new_anchor)
                        if until_date:
                            modified['until'] = format_date(until_date)
                    
                    if DEBUG:
                        debug_log(f"Recalculated instance dates: {actual_field}={format_date(new_anchor)}", "ADD/MOD")
                
                # Spool template rlast sync (can't subprocess from on-modify)
                if current_rlast != new_rindex:
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
                            f"Instance {task_id} rindex changed: {old_rindex} Ã¢â€ â€™ {new_rindex}\n"
                            f"Dates recalculated. Template {template_id} rlast will be synced."
                        )
                    except OSError as e:
                        if DEBUG:
                            debug_log(f"Failed to write template sync spool: {e}", "ADD/MOD")
                        self.add_message(
                            f"Instance {task_id} rindex changed: {old_rindex} Ã¢â€ â€™ {new_rindex}\n"
                            f"Dates recalculated. WARNING: Template sync failed. Manual fix: task {template_id} mod rlast:{new_rindex}"
                        )
                else:
                    if DEBUG:
                        debug_log(f"Template rlast already matches {new_rindex}, skipping sync", "ADD/MOD")
                    self.add_message(
                        f"Instance {task_id} rindex changed: {old_rindex} Ã¢â€ â€™ {new_rindex}\n"
                        f"Dates recalculated. Template {template_id} already in sync."
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
        
        # Strip legacy fields first (before any other processing)
        legacy_warnings = strip_legacy_recurrence(task)
        for warning in legacy_warnings:
            handler.add_message(warning)
        
        # Check if this should be a template (but not if being deleted)
        if 'r' in task and task.get('status') != 'deleted':
            task = handler.create_template(task)
            
            # If errors occurred, output original task unchanged
            if handler.has_errors():
                handler.output_messages()
                sys.exit(1)
        
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
        
        # Strip legacy fields first (before any other processing)
        # Pass original so TW-synthesized fields (like rtype) are silently stripped
        # Only warns user about fields they explicitly added
        legacy_warnings = strip_legacy_recurrence(modified, original=original)
        for warning in legacy_warnings:
            handler.add_message(warning)
        
        # Check for prohibited modifications
        error = validate_no_rtemplate_change(original, modified)
        if error:
            handler.add_error(error)
            modified['rtemplate'] = original.get('rtemplate')  # Restore original
        
        error = validate_no_r_on_instance(original, modified)
        if error:
            handler.add_error(error)
            if 'r' in modified:
                del modified['r']  # Remove invalid r field
        
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
        
        # If errors occurred, output original task unchanged
        if handler.has_errors():
            print(json.dumps(original))
            handler.output_messages()
            sys.exit(1)
        
        print(json.dumps(modified))
        handler.output_messages()
    
    if DEBUG:
        debug_log("Hook completed", "ADD/MOD")
    
    sys.exit(0)


if __name__ == '__main__':
    main()
