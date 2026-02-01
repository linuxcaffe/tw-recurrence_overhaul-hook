#!/usr/bin/env python3
"""
Taskwarrior Enhanced Recurrence Hook - On-Add/On-Modify
Version: 0.4.1
Date: 2026-01-31
Handles both adding new recurring tasks and modifying existing ones

Installation:
    1. Save to ~/.task/hooks/on-add_recurrence.py
    2. chmod +x ~/.task/hooks/on-add_recurrence.py
    3. cd ~/.task/hooks && ln -s on-add_recurrence.py on-modify_recurrence.py
    4. Ensure recurrence_common.py is in the same directory
"""

import sys
import os
import json
from datetime import datetime

# Add hooks directory to Python path so we can import recurrence_common
hooks_dir = os.path.dirname(os.path.abspath(__file__))
if hooks_dir not in sys.path:
    sys.path.insert(0, hooks_dir)

# Import shared utilities
from recurrence_common import (
    debug_log, parse_date, format_date, parse_relative_date,
    normalize_type, is_template, is_instance, DEBUG
)

# Read all input
lines = sys.stdin.readlines()
IS_ON_ADD = len(lines) == 1

if DEBUG:
    debug_log("="*60, "ADD/MOD")
    debug_log(f"Mode: {'ADD' if IS_ON_ADD else 'MODIFY'}, lines: {len(lines)}", "ADD/MOD")


class RecurrenceHandler:
    """Handles enhanced recurrence for Taskwarrior"""
    
    def __init__(self):
        self.now = datetime.utcnow()
    
    def get_anchor_date(self, task):
        """Get the anchor date (due or sched) for recurrence
        
        Returns:
            tuple: (anchor_field, anchor_datetime) or (None, None)
        """
        if 'due' in task:
            return 'due', parse_date(task['due'])
        elif 'scheduled' in task:
            return 'sched', parse_date(task['scheduled'])
        return None, None
    
    def create_template(self, task):
        """Convert a new task with r (recurrence) into a template
        
        Args:
            task: Task dictionary with 'r' field
            
        Returns:
            Modified task as template, or unchanged task if error
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
        task['rlast'] = '0'
        
        # Get anchor date
        anchor_field, anchor_date = self.get_anchor_date(task)
        
        if not anchor_field or not anchor_date:
            if DEBUG:
                debug_log(f"  ERROR: No valid anchor date found", "ADD/MOD")
                debug_log(f"  Task due: {task.get('due')}", "ADD/MOD")
                debug_log(f"  Task scheduled: {task.get('scheduled')}", "ADD/MOD")
            sys.stderr.write("ERROR: Recurring task must have either 'due' or 'scheduled' date\n")
            sys.stderr.write(f"       Provided: due={task.get('due')}, scheduled={task.get('scheduled')}\n")
            # Return the task unchanged rather than crashing
            if DEBUG:
                debug_log("  Returning task unchanged", "ADD/MOD")
            return task
        
        task['ranchor'] = anchor_field
        
        # Process wait date
        if 'wait' in task:
            wait_str = task['wait']
            result = parse_relative_date(wait_str)
            
            if result != (None, None):
                # Already in relative format - preserve it as-is
                task['rwait'] = wait_str
                del task['wait']
            else:
                # Absolute date - convert to relative offset in seconds
                wait_dt = parse_date(wait_str)
                if wait_dt and anchor_date:
                    delta_sec = int((wait_dt - anchor_date).total_seconds())
                    # Use negative offset since wait is typically before due
                    if delta_sec != 0:
                        task['rwait'] = f'{anchor_field}{delta_sec:+d}s'
                    del task['wait']
        
        # Process scheduled date (if anchor is not scheduled)
        if 'scheduled' in task and anchor_field != 'sched':
            sched_str = task['scheduled']
            result = parse_relative_date(sched_str)
            
            if result != (None, None):
                # Already in relative format - preserve it as-is
                task['rscheduled'] = sched_str
                del task['scheduled']
            else:
                # Absolute date - convert to relative offset in seconds
                sched_dt = parse_date(sched_str)
                if sched_dt and anchor_date:
                    delta_sec = int((sched_dt - anchor_date).total_seconds())
                    if delta_sec != 0:
                        task['rscheduled'] = f'{anchor_field}{delta_sec:+d}s'
                    del task['scheduled']
        
        if DEBUG:
            debug_log(f"  Template created: status={task['status']}, rlast={task['rlast']}", "ADD/MOD")
        
        return task
    
    def handle_template_modification(self, original, modified):
        """Handle modifications to a template
        
        Args:
            original: Original task dictionary
            modified: Modified task dictionary
            
        Returns:
            Modified task with any adjustments
        """
        # If template is being deleted/completed, remove r field so it can be purged
        if modified.get('status') in ['deleted', 'completed']:
            if 'r' in modified:
                del modified['r']
        
        # Normalize type if it was changed
        if 'type' in modified:
            modified['type'] = normalize_type(modified['type'])
        
        return modified
    
    def handle_instance_completion(self, original, modified):
        """Handle completion/deletion of an instance
        
        Args:
            original: Original task dictionary
            modified: Modified task dictionary
            
        Returns:
            Modified task (currently just passes through)
        """
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
            sys.stderr.write("Created recurrence template. First instance will be generated on exit.\n")
        
        print(json.dumps(task))
    
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
        if 'r' in modified and modified.get('status') not in ['recurring', 'deleted']:
            modified = handler.create_template(modified)
            sys.stderr.write("Created recurrence template. First instance will be generated on exit.\n")
        
        # Modifying a template?
        elif is_template(original):
            modified = handler.handle_template_modification(original, modified)
        
        # Completing an instance?
        elif is_instance(original):
            modified = handler.handle_instance_completion(original, modified)
        
        print(json.dumps(modified))
    
    if DEBUG:
        debug_log("Hook completed", "ADD/MOD")
    
    sys.exit(0)


if __name__ == '__main__':
    main()
