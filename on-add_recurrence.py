#!/usr/bin/env python3
"""
Taskwarrior Enhanced Recurrence Hook - On-Add/On-Modify
Version: 0.4.1
Date: 2026-02-01
Handles both adding new recurring tasks and modifying existing ones

Features:
- Template creation from tasks with 'r' field
- Smart modification handling (type, anchor, rlast, rwait changes)
- Instance rindex/template rlast synchronization
- Comprehensive user feedback with actionable suggestions

Installation:
    1. Save to ~/.task/hooks/on-add_recurrence.py
    2. chmod +x ~/.task/hooks/on-add_recurrence.py
    3. cd ~/.task/hooks && ln -s on-add_recurrence.py on-modify_recurrence.py
    4. Ensure recurrence_common_hook-x.py is in ~/.task/hooks/ (not executable)
"""

import sys
import json
import subprocess
from datetime import datetime, timedelta
import os

# Add hooks directory to Python path for imports
HOOKS_DIR = os.path.expanduser("~/.task/hooks")
if HOOKS_DIR not in sys.path:
    sys.path.insert(0, HOOKS_DIR)

# Import common utilities
try:
    from recurrence_common_hook import (
        normalize_type, parse_duration, parse_date, format_date,
        parse_relative_date, is_template, is_instance, 
        get_anchor_field_name, debug_log, DEBUG
    )
except ImportError as e:
    sys.stderr.write(f"ERROR: recurrence_common_hook.py not found in hooks directory\n")
    sys.stderr.write(f"Import error: {e}\n")
    sys.stderr.write(f"Python path: {sys.path}\n")
    sys.exit(1)

if DEBUG:
    debug_log("="*60, "ADD/MOD")
    debug_log("Hook starting", "ADD/MOD")

# Read all input
lines = sys.stdin.readlines()
IS_ON_ADD = len(lines) == 1

if DEBUG:
    debug_log(f"Mode: {'ADD' if IS_ON_ADD else 'MODIFY'}, lines: {len(lines)}", "ADD/MOD")


class RecurrenceHandler:
    """Handles enhanced recurrence for Taskwarrior"""
    
    def __init__(self):
        self.now = datetime.utcnow()
    
    def get_anchor_date(self, task):
        """Get the anchor date (due or sched) for recurrence"""
        if 'due' in task:
            return 'due', parse_date(task['due'])
        elif 'scheduled' in task:
            return 'sched', parse_date(task['scheduled'])
        return None, None
    
    def get_task_id(self, uuid):
        """Get task ID from UUID for user messaging"""
        try:
            result = subprocess.run(
                ['task', 'rc.hooks=off', f'uuid:{uuid}', 'export'],
                capture_output=True,
                text=True,
                check=True
            )
            tasks = json.loads(result.stdout.strip())
            if tasks and len(tasks) > 0:
                return tasks[0].get('id', '?')
        except Exception:
            pass
        return '?'
    
    def create_template(self, task):
        """Convert a new task with r (recurrence) into a template"""
        if DEBUG:
            debug_log(f"Creating template: {task.get('description')}", "ADD/MOD")
        
        if 'r' not in task:
            return task, []
        
        feedback = []
        
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
            return task, []
        
        task['ranchor'] = anchor_field
        
        # Process wait
        if 'wait' in task:
            wait_str = task['wait']
            ref_field, offset = parse_relative_date(wait_str)
            
            if ref_field and offset:
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
        
        # Process sched
        if 'scheduled' in task and anchor_field != 'sched':
            sched_str = task['scheduled']
            ref_field, offset = parse_relative_date(sched_str)
            
            if ref_field and offset:
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
        
        return task, feedback
    
    def handle_anchor_change(self, original, modified):
        """Handle change in anchor field (due ↔ sched)"""
        old_anchor = original.get('ranchor')
        feedback = []
        
        # Detect new anchor based on what fields exist
        new_anchor = None
        if 'due' in modified and 'scheduled' not in modified:
            new_anchor = 'due'
        elif 'scheduled' in modified and 'due' not in modified:
            new_anchor = 'sched'
        
        if new_anchor and new_anchor != old_anchor:
            if DEBUG:
                debug_log(f"Anchor change detected: {old_anchor} → {new_anchor}", "ADD/MOD")
            
            modified['ranchor'] = new_anchor
            
            # Update relative dates to use new anchor
            if 'rwait' in modified and old_anchor in modified['rwait']:
                modified['rwait'] = modified['rwait'].replace(old_anchor, new_anchor)
            
            if 'rscheduled' in modified and old_anchor in modified.get('rscheduled', ''):
                modified['rscheduled'] = modified['rscheduled'].replace(old_anchor, new_anchor)
            
            feedback.append(
                f"Modified template anchor: {old_anchor} → {new_anchor}\n"
                f"Relative dates (rwait, rscheduled) updated to use new anchor."
            )
        
        return modified, feedback
    
    def handle_wait_modification(self, original, modified):
        """Handle changes to wait field on templates"""
        feedback = []
        
        # If absolute wait added/changed on template
        if 'wait' in modified and is_template(modified):
            wait_str = modified['wait']
            ref_field, offset = parse_relative_date(wait_str)
            
            if ref_field and offset:
                # Already relative - convert to rwait
                modified['rwait'] = wait_str
                del modified['wait']
                if DEBUG:
                    debug_log(f"Converted wait to rwait: {wait_str}", "ADD/MOD")
            else:
                # Absolute date - convert to relative
                anchor_field, anchor_date = self.get_anchor_date(modified)
                wait_dt = parse_date(wait_str)
                
                if wait_dt and anchor_date:
                    delta_sec = int((wait_dt - anchor_date).total_seconds())
                    modified['rwait'] = f'{anchor_field}{delta_sec:+d}s'
                    del modified['wait']
                    
                    if DEBUG:
                        debug_log(f"Converted absolute wait to rwait: {modified['rwait']}", "ADD/MOD")
                    
                    feedback.append(
                        f"Converted absolute wait to relative: rwait={modified['rwait']}\n"
                        f"This will apply to all future instances."
                    )
        
        return modified, feedback
    
    def handle_rlast_modification(self, original, modified):
        """Handle time-machine functionality via rlast modification"""
        feedback = []
        
        old_rlast = int(original.get('rlast', '0'))
        new_rlast = int(modified.get('rlast', '0'))
        
        if new_rlast != old_rlast:
            if DEBUG:
                debug_log(f"rlast modified: {old_rlast} → {new_rlast}", "ADD/MOD")
            
            # Sync current pending instance rindex to match template rlast
            try:
                result = subprocess.run(
                    ['task', 'rc.hooks=off', f'rtemplate:{modified["uuid"]}', 
                     'status:pending', 'export'],
                    capture_output=True, text=True, check=True
                )
                instances = json.loads(result.stdout.strip()) if result.stdout.strip() else []
                
                if instances:
                    inst = instances[0]
                    old_rindex = int(inst.get('rindex', '0'))
                    
                    if old_rindex != new_rlast:
                        # Update instance rindex to match template rlast
                        if DEBUG:
                            debug_log(f"Attempting to sync instance {inst['uuid']} rindex: {old_rindex} → {new_rlast}", "ADD/MOD")
                        
                        result = subprocess.run(
                            ['task', 'rc.hooks=off', inst['uuid'], 'modify', f'rindex:{new_rlast}'],
                            capture_output=True,
                            text=True,
                            check=False
                        )
                        
                        if DEBUG:
                            debug_log(f"Subprocess returncode: {result.returncode}", "ADD/MOD")
                            debug_log(f"Subprocess stdout: {result.stdout}", "ADD/MOD")
                            debug_log(f"Subprocess stderr: {result.stderr}", "ADD/MOD")
                        
                        if result.returncode == 0:
                            feedback.append(f"Synced current instance rindex to {new_rlast}.")
                        else:
                            feedback.append(f"Warning: Could not sync instance rindex (may sync on next interaction).")
                        
                        if DEBUG:
                            debug_log(f"Synced instance rindex to {new_rlast}", "ADD/MOD")
            except Exception as e:
                if DEBUG:
                    debug_log(f"Could not sync instance rindex: {e}", "ADD/MOD")
            
            # Calculate next instance details for period types
            if modified.get('type') == 'period':
                r_delta = parse_duration(modified.get('r'))
                anchor_field, anchor_date = self.get_anchor_date(modified)
                
                if r_delta and anchor_date:
                    # Next instance will be (new_rlast + 1)
                    next_idx = new_rlast + 1
                    next_due = anchor_date + (r_delta * next_idx)
                    
                    skip_count = new_rlast - old_rlast
                    direction = "forward" if skip_count > 0 else "backward"
                    
                    feedback.append(
                        f"Template rlast modified: {old_rlast} → {new_rlast} "
                        f"({abs(skip_count)} instance{'s' if abs(skip_count) != 1 else ''} {direction})\n"
                        f"Next instance will be #{next_idx} due {format_date(next_due)}"
                    )
            else:
                # Chain type - simpler message
                feedback.append(
                    f"Template rlast modified: {old_rlast} → {new_rlast}\n"
                    f"Next instance will be #{new_rlast + 1} (spawns on completion)."
                )
        
        return modified, feedback
    
    def handle_template_modification(self, original, modified):
        """Handle modifications to a template"""
        feedback = []
        
        # If template is being deleted/completed, remove r field so it can be purged
        if modified.get('status') in ['deleted', 'completed']:
            if 'r' in modified:
                del modified['r']
            return modified, feedback
        
        # Check for type change
        if 'type' in modified and modified.get('type') != original.get('type'):
            old_type = original.get('type', 'period')
            new_type = normalize_type(modified.get('type'))
            modified['type'] = new_type
            
            if old_type != new_type:
                if DEBUG:
                    debug_log(f"Type change: {old_type} → {new_type}", "ADD/MOD")
                
                spawn_msg = "on completion" if new_type == "chain" else "on schedule"
                feedback.append(
                    f"Modified template type: {old_type} → {new_type}\n"
                    f"This changes how future instances spawn ({spawn_msg}).\n"
                    f"Current rlast={modified.get('rlast', '0')} preserved."
                )
        elif 'type' in modified:
            # Normalize even if not changed
            modified['type'] = normalize_type(modified['type'])
        
        # Check for anchor change
        modified, anchor_feedback = self.handle_anchor_change(original, modified)
        feedback.extend(anchor_feedback)
        
        # Check for wait modification
        modified, wait_feedback = self.handle_wait_modification(original, modified)
        feedback.extend(wait_feedback)
        
        # Check for rlast modification (time machine)
        if 'rlast' in modified and modified.get('rlast') != original.get('rlast'):
            modified, rlast_feedback = self.handle_rlast_modification(original, modified)
            feedback.extend(rlast_feedback)
        
        # Check for attribute changes that might propagate to current instance
        changed_attrs = {}
        for attr in ['project', 'priority', 'tags', 'due', 'scheduled']:
            if attr in modified and modified.get(attr) != original.get(attr):
                changed_attrs[attr] = modified.get(attr)
        
        if changed_attrs:
            # Find current pending instance
            try:
                result = subprocess.run(
                    ['task', 'rc.hooks=off', f'rtemplate:{modified["uuid"]}', 
                     'status:pending', 'export'],
                    capture_output=True, text=True, check=True
                )
                instances = json.loads(result.stdout.strip()) if result.stdout.strip() else []
                
                if instances:
                    inst = instances[0]
                    inst_id = inst.get('id')
                    
                    # Build modify command
                    mod_parts = []
                    if 'project' in changed_attrs:
                        mod_parts.append(f"project:{changed_attrs['project']}")
                    if 'priority' in changed_attrs:
                        mod_parts.append(f"priority:{changed_attrs['priority']}")
                    if 'tags' in changed_attrs:
                        # This is simplified - full tag handling is complex
                        for tag in changed_attrs['tags']:
                            mod_parts.append(f"+{tag}")
                    if 'due' in changed_attrs:
                        mod_parts.append(f"due:{changed_attrs['due']}")
                    if 'scheduled' in changed_attrs:
                        mod_parts.append(f"scheduled:{changed_attrs['scheduled']}")
                    
                    if mod_parts:
                        task_id = self.get_task_id(modified['uuid'])
                        feedback.append(
                            f"Modified task {task_id} -- {modified.get('description', '')} (recurrence template)\n"
                            f"This will affect future instances. To apply to current instance #{inst.get('rindex')}:\n"
                            f"task {inst_id} mod {' '.join(mod_parts)}"
                        )
            except Exception as e:
                if DEBUG:
                    debug_log(f"Could not fetch instances: {e}", "ADD/MOD")
        
        return modified, feedback
    
    def handle_instance_modification(self, original, modified):
        """Handle modifications to an instance"""
        feedback = []
        
        # Sync rindex to template rlast
        if 'rindex' in modified and modified.get('rindex') != original.get('rindex'):
            new_idx = int(modified['rindex'])
            old_idx = int(original.get('rindex', '0'))
            
            if DEBUG:
                debug_log(f"Instance rindex modified: {old_idx} → {new_idx}", "ADD/MOD")
            
            try:
                subprocess.run(
                    ['task', 'rc.hooks=off', modified['rtemplate'], 'modify', f'rlast:{new_idx}'],
                    capture_output=True,
                    check=True
                )
                feedback.append(
                    f"Modified instance rindex: {old_idx} → {new_idx}\n"
                    f"Template rlast synced to {new_idx}."
                )
                if DEBUG:
                    debug_log(f"Synced template rlast to {new_idx}", "ADD/MOD")
            except Exception as e:
                if DEBUG:
                    debug_log(f"Failed to sync template rlast: {e}", "ADD/MOD")
        
        # Check for attribute changes that might want to propagate to template
        changed_attrs = {}
        for attr in ['project', 'priority', 'tags']:
            if attr in modified and modified.get(attr) != original.get(attr):
                changed_attrs[attr] = modified.get(attr)
        
        if changed_attrs and 'rtemplate' in modified:
            try:
                # Get template info
                result = subprocess.run(
                    ['task', 'rc.hooks=off', f'uuid:{modified["rtemplate"]}', 'export'],
                    capture_output=True, text=True, check=True
                )
                templates = json.loads(result.stdout.strip())
                
                if templates:
                    tmpl = templates[0]
                    tmpl_id = tmpl.get('id')
                    
                    # Build modify command for template
                    mod_parts = []
                    if 'project' in changed_attrs:
                        mod_parts.append(f"project:{changed_attrs['project']}")
                    if 'priority' in changed_attrs:
                        mod_parts.append(f"priority:{changed_attrs['priority']}")
                    if 'tags' in changed_attrs:
                        for tag in changed_attrs['tags']:
                            mod_parts.append(f"+{tag}")
                    
                    if mod_parts:
                        inst_id = self.get_task_id(modified['uuid'])
                        feedback.append(
                            f"Modified task {inst_id} -- {modified.get('description', '')} (instance #{modified.get('rindex')})\n"
                            f"To apply this change to all future instances:\n"
                            f"task {tmpl_id} mod {' '.join(mod_parts)}"
                        )
            except Exception as e:
                if DEBUG:
                    debug_log(f"Could not fetch template: {e}", "ADD/MOD")
        
        return modified, feedback


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
            task, feedback = handler.create_template(task)
            sys.stderr.write("Created recurrence template. First instance will be generated on exit.\n")
            for msg in feedback:
                sys.stderr.write(f"{msg}\n")
        
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
        
        feedback = []
        
        # Adding recurrence to existing task? (but not if being deleted)
        if 'r' in modified and modified.get('status') not in ['recurring', 'deleted']:
            modified, fb = handler.create_template(modified)
            feedback.extend(fb)
            sys.stderr.write("Created recurrence template. First instance will be generated on exit.\n")
        
        # Modifying a template?
        elif is_template(original):
            modified, fb = handler.handle_template_modification(original, modified)
            feedback.extend(fb)
        
        # Modifying an instance?
        elif is_instance(original):
            modified, fb = handler.handle_instance_modification(original, modified)
            feedback.extend(fb)
        
        # Output feedback
        for msg in feedback:
            sys.stderr.write(f"{msg}\n")
        
        print(json.dumps(modified))
    
    if DEBUG:
        debug_log("Hook completed", "ADD/MOD")
    
    sys.exit(0)


if __name__ == '__main__':
    main()
