#!/usr/bin/env python3
"""
Taskwarrior Enhanced Recurrence Hook - On-Exit
Version: 0.5.0
Date: 2026-02-07

Spawns new recurrence instances when needed and enforces one-to-one rule:
Every active template MUST have exactly one pending instance.

Installation:
    Save to ~/.task/hooks/on-exit_recurrence.py
    chmod +x ~/.task/hooks/on-exit_recurrence.py
"""

import sys
sys.dont_write_bytecode = True

import json
import subprocess
from datetime import datetime, timedelta
import re
import os

# Add hooks directory to Python path for importing common module
hooks_dir = os.path.expanduser('~/.task/hooks')
if hooks_dir not in sys.path:
    sys.path.insert(0, hooks_dir)

try:
    from recurrence_common_hook import (
        normalize_type, parse_duration, parse_date, format_date,
        parse_relative_date, is_template, is_instance,
        get_anchor_field_name, debug_log, DEBUG,
        spawn_instance
    )
except ImportError as e:
    # Fallback error handling
    sys.stderr.write(f"ERROR: Cannot import recurrence_common_hook: {e}\n")
    sys.stderr.write("Please ensure recurrence_common_hook.py is in ~/.task/hooks/\n")
    sys.exit(1)

if DEBUG:
    debug_log("="*60, "EXIT")
    debug_log("on-exit hook started", "EXIT")


class RecurrenceSpawner:
    """Spawns new recurrence instances"""
    
    def __init__(self):
        self.now = datetime.utcnow()
    
    def get_anchor_field_name(self, anchor_field):
        """Map our short anchor name to taskwarrior's actual field name"""
        field_map = {'sched': 'scheduled', 'due': 'due'}
        return field_map.get(anchor_field, anchor_field)
    
    def parse_duration(self, duration_str):
        """Parse duration string to timedelta"""
        if not duration_str:
            return None
        
        # Simple formats
        match = re.match(r'(\d+)(s|d|w|mo|y)', str(duration_str).lower())
        if match:
            num, unit = match.groups()
            num = int(num)
            if unit == 's':
                return timedelta(seconds=num)
            elif unit == 'd':
                return timedelta(days=num)
            elif unit == 'w':
                return timedelta(weeks=num)
            elif unit == 'mo':
                return timedelta(days=num * 30)
            elif unit == 'y':
                return timedelta(days=num * 365)
        
        # ISO 8601
        pattern = r'P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?'
        match = re.match(pattern, str(duration_str))
        if match:
            years, months, weeks, days, hours, mins, secs = match.groups()
            delta = timedelta()
            if secs:
                delta += timedelta(seconds=int(secs))
            if mins:
                delta += timedelta(minutes=int(mins))
            if hours:
                delta += timedelta(hours=int(hours))
            if days:
                delta += timedelta(days=int(days))
            if weeks:
                delta += timedelta(weeks=int(weeks))
            if months:
                delta += timedelta(days=int(months) * 30)
            if years:
                delta += timedelta(days=int(years) * 365)
            return delta
        
        return None
    
    def parse_date(self, date_str):
        """Parse ISO 8601 date"""
        if not date_str:
            return None
        try:
            clean = str(date_str).replace('Z', '').replace('+00:00', '')
            return datetime.strptime(clean[:15], '%Y%m%dT%H%M%S')
        except (ValueError, AttributeError):
            return None
    
    def format_date(self, dt):
        """Format datetime as ISO 8601"""
        return dt.strftime('%Y%m%dT%H%M%SZ')
    
    def parse_relative_date(self, rel_str, anchor_date):
        """Parse relative date like 'due-2d' or 'due-30m' given anchor date"""
        if not rel_str or not anchor_date:
            return None
        
        match = re.match(r'(due|sched|wait)\s*([+-])\s*(\d+)(s|seconds?|min|minutes?|m|h|hours?|d|days?|w|weeks?|mo|months?|y|years?)', 
                        str(rel_str).lower())
        if match:
            ref_field, sign, num, unit = match.groups()
            num = int(num)
            
            # Normalize unit to category
            # Order matters: 'min'/'minutes' before 'mo'/'months', 'm' is minutes
            if unit.startswith('min') or unit == 'm':
                delta = timedelta(minutes=num)
            elif unit.startswith('s'):
                delta = timedelta(seconds=num)
            elif unit.startswith('h'):
                delta = timedelta(hours=num)
            elif unit.startswith('d'):
                delta = timedelta(days=num)
            elif unit.startswith('w'):
                delta = timedelta(weeks=num)
            elif unit.startswith('mo'):
                delta = timedelta(days=num * 30)
            elif unit.startswith('y'):
                delta = timedelta(days=num * 365)
            else:
                return None
            
            if sign == '-':
                delta = -delta
            
            return anchor_date + delta
        
        return None
    
    def get_template(self, uuid):
        """Fetch template task by UUID"""
        if DEBUG:
            debug_log(f"Attempting to fetch template: {uuid}")
        
        # Try method 1: Direct UUID export
        try:
            result = subprocess.run(
                ['task', 'rc.hooks=off', uuid, 'export'],
                capture_output=True,
                text=True,
                check=True
            )
            if DEBUG:
                debug_log(f"Method 1 returncode: {result.returncode}")
                debug_log(f"Method 1 stderr: {result.stderr}")
            
            lines = [line for line in result.stdout.strip().split('\n') if line]
            if lines:
                # Parse the JSON array
                tasks = json.loads(result.stdout.strip())
                if tasks and len(tasks) > 0:
                    template = tasks[0]
                    if DEBUG:
                        debug_log(f"Template fetched via method 1: {template.get('description')}, status={template.get('status')}")
                    return template
                else:
                    if DEBUG:
                        debug_log("Method 1: Empty task array")
        except subprocess.CalledProcessError as e:
            if DEBUG:
                debug_log(f"Method 1 CalledProcessError: returncode={e.returncode}")
                debug_log(f"  stderr: {e.stderr}")
        except json.JSONDecodeError as e:
            if DEBUG:
                debug_log(f"Method 1 JSONDecodeError: {e}")
        except Exception as e:
            if DEBUG:
                debug_log(f"Method 1 exception: {type(e).__name__}: {e}")
        
        # Try method 2: Filter by UUID with status:recurring
        try:
            result = subprocess.run(
                ['task', 'rc.hooks=off', f'uuid:{uuid}', 'status:recurring', 'export'],
                capture_output=True,
                text=True,
                check=True
            )
            if DEBUG:
                debug_log(f"Method 2 returncode: {result.returncode}")
            
            tasks = json.loads(result.stdout.strip())
            if tasks and len(tasks) > 0:
                template = tasks[0]
                if DEBUG:
                    debug_log(f"Template fetched via method 2: {template.get('description')}")
                return template
        except Exception as e:
            if DEBUG:
                debug_log(f"Method 2 exception: {type(e).__name__}: {e}")
        
        if DEBUG:
            debug_log("All template fetch methods failed")
        return None
    
    def check_rend(self, template, new_date):
        """Check if new_date exceeds recurrence end date (rend)"""
        if 'rend' not in template:
            return False
        
        rend_str = template['rend']
        anchor_field = template.get('ranchor', 'due')
        actual_field = self.get_anchor_field_name(anchor_field)
        anchor_date = self.parse_date(template.get(actual_field))
        rend_date = self.parse_relative_date(rend_str, anchor_date)
        
        if not rend_date:
            rend_date = self.parse_date(rend_str)
        
        if rend_date and new_date > rend_date:
            return True
        
        return False
    
    def process_tasks(self, tasks):
        """Process tasks and spawn instances"""
        feedback = []
        
        # Process propagation spool from on-modify (template -> instance sync).
        # on-modify can't subprocess 'task modify' because Taskwarrior holds a
        # file lock during hook execution. on-exit runs after the lock is released.
        spool_path = os.path.expanduser('~/.task/recurrence_propagate.json')
        if os.path.exists(spool_path):
            try:
                with open(spool_path, 'r') as f:
                    spool = json.load(f)
                os.remove(spool_path)
                
                instance_uuid = spool['instance_uuid']
                updates = spool['updates']
                template_id = spool.get('template_id', '?')
                instance_rindex = spool.get('instance_rindex', '?')
                changes = spool.get('changes', [])
                
                mod_args = [f'{field}:{value}' for field, value in updates.items()]
                
                if DEBUG:
                    debug_log(f"Processing propagation spool: instance {instance_uuid}, updates: {updates}", "EXIT")
                
                result = subprocess.run(
                    ['task', 'rc.hooks=off', 'rc.confirmation=off', 'rc.verbose=nothing',
                     instance_uuid, 'modify'] + mod_args,
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if result.returncode == 0:
                    if DEBUG:
                        debug_log(f"Propagation successful", "EXIT")
                    field_list = ', '.join(changes) if changes else 'recurrence fields'
                    feedback.append(f"Instance #{instance_rindex} synced ({field_list}).")
                else:
                    if DEBUG:
                        debug_log(f"Propagation failed: {result.stderr}", "EXIT")
                    feedback.append(f"WARNING: Failed to sync instance #{instance_rindex}. Manual sync may be needed.")
                    
            except (json.JSONDecodeError, KeyError, OSError) as e:
                if DEBUG:
                    debug_log(f"Error processing propagation spool: {e}", "EXIT")
                # Clean up bad spool file
                try:
                    os.remove(spool_path)
                except OSError:
                    pass
        
        for task in tasks:
            if DEBUG:
                debug_log(f"Processing task: uuid={task.get('uuid')}, status={task.get('status')}, "
                         f"rtemplate={task.get('rtemplate')}, rindex={task.get('rindex')}")
            
            # Template being deleted or completed?
            if ((task.get('status') in ['deleted', 'completed']) and 
                'r' in task and 
                'rtemplate' not in task):
                
                if DEBUG:
                    debug_log(f"Template {task.get('status')}: {task.get('uuid')}")
                
                # Find pending instances
                try:
                    result = subprocess.run(
                        ['task', 'rc.hooks=off', f'rtemplate:{task.get("uuid")}', 'status:pending', 'export'],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    instances = json.loads(result.stdout.strip()) if result.stdout.strip() else []
                    instance_ids = [str(inst.get('id', '')) for inst in instances if inst.get('id')]
                except Exception as e:
                    if DEBUG:
                        debug_log(f"Could not fetch instances: {e}")
                    instance_ids = []
                
                if task.get('status') == 'deleted':
                    feedback.append(f"Deleted template '{task.get('description')}' - all future instances stopped.")
                    if instance_ids:
                        if len(instance_ids) == 1:
                            feedback.append(f"To delete the pending instance: task {instance_ids[0]} delete")
                        else:
                            feedback.append(f"To delete pending instances: task {' '.join(instance_ids)} delete")
                else:  # completed
                    feedback.append(f"Completed template '{task.get('description')}' - all future instances stopped.")
                    if instance_ids:
                        if len(instance_ids) == 1:
                            feedback.append(f"To complete the pending instance: task {instance_ids[0]} done")
                        else:
                            feedback.append(f"To complete pending instances: task {' '.join(instance_ids)} done")
                continue
            
            # Completed or deleted instance?
            if (task.get('status') in ['completed', 'deleted'] and 
                'rtemplate' in task and 'rindex' in task):
                
                if DEBUG:
                    debug_log(f"Found {task.get('status')} instance: rindex={task['rindex']}")
                
                template = self.get_template(task['rtemplate'])
                if not template:
                    if DEBUG:
                        debug_log(f"Could not fetch template: {task['rtemplate']}")
                    continue
                
                # Check if template has been deleted or completed
                if template.get('status') in ['deleted', 'completed']:
                    if DEBUG:
                        debug_log(f"Template is {template.get('status')}, not spawning")
                    continue
                
                if DEBUG:
                    debug_log(f"Template found: {template.get('description')}, rlast={template.get('rlast')}, type={template.get('type')}")
                
                current_idx = int(task['rindex'])
                last_idx = int(template.get('rlast', '0'))
                
                if DEBUG:
                    debug_log(f"Checking: current_idx={current_idx}, last_idx={last_idx}")
                
                # Only spawn if this is the latest instance
                # Both periodic and chained spawn on completion/deletion
                if current_idx >= last_idx:
                    if DEBUG:
                        debug_log(f"Will spawn next instance", "EXIT")
                    
                    # Get completion/deletion time for chained type
                    completion = None
                    if task.get('status') == 'completed' and 'end' in task:
                        completion = parse_date(task['end'])
                        if DEBUG:
                            debug_log(f"Completion time: {completion}", "EXIT")
                    elif task.get('status') == 'deleted':
                        # For deleted tasks, use deletion time (now)
                        completion = self.now
                        if DEBUG:
                            debug_log(f"Deletion time: {completion}", "EXIT")
                    
                    # Always use spawn_instance from common module
                    msg = spawn_instance(template, current_idx + 1, completion)
                    
                    if msg:
                        feedback.append(msg)
                        if DEBUG:
                            debug_log(f"Result: {msg}", "EXIT")
                else:
                    if DEBUG:
                        debug_log(f"Skipping spawn: not the latest instance")
            
            # Deleted instance? (just acknowledge, don't spawn)
            elif (task.get('status') == 'deleted' and 
                  'rtemplate' in task and 'rindex' in task):
                
                if DEBUG:
                    debug_log(f"Instance deleted (not spawning): rindex={task['rindex']}")
            
            # New template? (handle both string and int rlast)
            elif (task.get('status') == 'recurring' and 
                  'r' in task and 
                  str(task.get('rlast', '')).strip() in ['0', '1', '']):
                
                if DEBUG:
                    debug_log(f"Found template with rlast in [0,1,'']: {task.get('description')}", "EXIT")
                
                # Check if instance already exists (prevent duplicate spawning on template mods)
                from recurrence_common_hook import query_instances
                template_uuid = task.get('uuid')
                existing_instances = query_instances(template_uuid) if template_uuid else []
                
                if existing_instances:
                    if DEBUG:
                        debug_log(f"Instance already exists (count={len(existing_instances)}), not spawning", "EXIT")
                else:
                    if DEBUG:
                        debug_log(f"No instance exists, spawning first instance", "EXIT")
                    
                    # Always use spawn_instance from common module
                    msg = spawn_instance(task, 1)  # First instance is always index 1
                    
                    if msg:
                        feedback.append(msg)
        
        return feedback


def main():
    """Main entry point for on-exit"""
    lines = sys.stdin.readlines()
    
    if DEBUG:
        debug_log(f"Received {len(lines)} lines of input", "EXIT")
    
    if not lines:
        sys.exit(0)
    
    try:
        tasks = [json.loads(line) for line in lines if line.strip()]
        if DEBUG:
            debug_log(f"Parsed {len(tasks)} tasks", "EXIT")
            for i, task in enumerate(tasks):
                debug_log(f"Task {i}: uuid={task.get('uuid')}, status={task.get('status')}, "
                         f"desc={task.get('description', '')[:50]}", "EXIT")
    except json.JSONDecodeError as e:
        if DEBUG:
            debug_log(f"JSON decode error: {e}", "EXIT")
        sys.exit(0)
    
    spawner = RecurrenceSpawner()
    
    # Process tasks (reactive spawning - only for tasks that were modified)
    feedback = spawner.process_tasks(tasks)
    
    for msg in feedback:
        print(msg)
    
    if DEBUG:
        debug_log(f"on-exit completed with {len(feedback)} feedback messages", "EXIT")
    
    sys.exit(0)


if __name__ == '__main__':
    main()
