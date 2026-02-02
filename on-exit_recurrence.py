#!/usr/bin/env python3
"""
Taskwarrior Enhanced Recurrence Hook - On-Exit
Version: 0.4.0
Date: 2026-02-02

Spawns new recurrence instances when needed and enforces one-to-one rule:
Every active template MUST have exactly one pending instance.

Installation:
    Save to ~/.task/hooks/on-exit_recurrence.py
    chmod +x ~/.task/hooks/on-exit_recurrence.py
"""

import sys
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
    COMMON_MODULE_AVAILABLE = True
except ImportError as e:
    # Fallback - use local functions if common module not available
    DEBUG = os.environ.get('DEBUG_RECURRENCE', '0') == '1'
    LOG_FILE = os.path.expanduser("~/.task/recurrence_debug.log")
    COMMON_MODULE_AVAILABLE = False
    
    def debug_log(msg, prefix="EXIT"):
        """Write debug message to log file if debug enabled"""
        if DEBUG:
            with open(LOG_FILE, 'a') as f:
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                f.write(f"[{timestamp}] {prefix}: {msg}\n")

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
        """Parse relative date like 'due-2d' or 'due-2days' given anchor date"""
        if not rel_str or not anchor_date:
            return None
        
        match = re.match(r'(due|sched|wait)\s*([+-])\s*(\d+)(s|seconds?|d|days?|w|weeks?|mo|months?|y|years?)', 
                        str(rel_str).lower())
        if match:
            ref_field, sign, num, unit = match.groups()
            num = int(num)
            
            # Normalize unit to category
            if unit.startswith('s'):
                delta = timedelta(seconds=num)
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
    
    def create_instance(self, template, index, completion_time=None):
        """Create a new instance task"""
        if DEBUG:
            debug_log(f"Creating instance {index} from {template.get('uuid')}")
        
        recur_delta = self.parse_duration(template.get('r'))
        if not recur_delta:
            return None
        
        rtype = template.get('type', 'period')
        anchor_field = template.get('ranchor', 'due')
        
        # Build command
        cmd = ['task', 'rc.hooks=off', 'add', template['description']]
        
        # Get template anchor date
        actual_field = self.get_anchor_field_name(anchor_field)
        template_anchor = self.parse_date(template.get(actual_field))
        if not template_anchor:
            return None
        
        # Calculate anchor date
        if index == 1:
            # Instance 1 always uses template's anchor date
            anchor_date = template_anchor
        else:
            if rtype == 'chain':
                # Instance 2+: completion_time + period
                base = completion_time or self.now
                anchor_date = base + recur_delta
            else:  # period
                # Instance 2+: template + (index-1) * period
                anchor_date = template_anchor + (recur_delta * (index - 1))
        
        # Check rend date
        if self.check_rend(template, anchor_date):
            return "Recurrence ended (rend date reached)"
        
        # Add anchor date
        cmd.append(f'{anchor_field}:{self.format_date(anchor_date)}')
        
        # Copy until from template if present
        if 'until' in template:
            cmd.append(f'until:{template["until"]}')
        
        # Process wait
        if 'rwait' in template:
            wait_date = self.parse_relative_date(template['rwait'], anchor_date)
            if wait_date:
                cmd.append(f'wait:{self.format_date(wait_date)}')
        
        # Process sched
        if 'rscheduled' in template and anchor_field != 'sched':
            sched_date = self.parse_relative_date(template['rscheduled'], anchor_date)
            if sched_date:
                cmd.append(f'sched:{self.format_date(sched_date)}')
        
        # Copy attributes
        if 'project' in template:
            cmd.append(f'project:{template["project"]}')
        if 'priority' in template:
            cmd.append(f'priority:{template["priority"]}')
        if 'tags' in template and template['tags']:
            cmd.extend([f'+{tag}' for tag in template['tags']])
        
        # Metadata
        cmd.extend([
            f'rtemplate:{template["uuid"]}',
            f'rindex:{int(index)}'
        ])
        
        # Execute
        try:
            subprocess.run(cmd, capture_output=True, check=True)
            
            # Update template's rlast
            subprocess.run(
                ['task', 'rc.hooks=off', template['uuid'], 'modify', f'rlast:{int(index)}'],
                capture_output=True,
                check=True
            )
            
            if DEBUG:
                debug_log(f"Instance {index} created successfully")
            
            return f"Created instance {index} of '{template['description']}'"
        except subprocess.CalledProcessError as e:
            if DEBUG:
                debug_log(f"Error creating instance: {e}")
            return None
    
    def process_tasks(self, tasks):
        """Process tasks and spawn instances"""
        feedback = []
        
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
                        completion = parse_date(task['end']) if COMMON_MODULE_AVAILABLE else self.parse_date(task['end'])
                        if DEBUG:
                            debug_log(f"Completion time: {completion}", "EXIT")
                    elif task.get('status') == 'deleted':
                        # For deleted tasks, use deletion time (now)
                        completion = self.now
                        if DEBUG:
                            debug_log(f"Deletion time: {completion}", "EXIT")
                    
                    # Use common spawn_instance if available, otherwise fallback to local
                    if COMMON_MODULE_AVAILABLE:
                        msg = spawn_instance(template, current_idx + 1, completion)
                    else:
                        msg = self.create_instance(template, current_idx + 1, completion)
                    
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
                    debug_log(f"Found new template: {task.get('description')}", "EXIT")
                
                # Use common spawn_instance if available, otherwise fallback to local
                if COMMON_MODULE_AVAILABLE:
                    msg = spawn_instance(task, 1)  # First instance is always index 1
                else:
                    msg = self.create_instance(task, 1)
                
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
