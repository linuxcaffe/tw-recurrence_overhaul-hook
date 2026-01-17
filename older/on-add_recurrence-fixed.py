#!/usr/bin/env python3
"""
Taskwarrior Enhanced Recurrence Hook - On-Add/On-Modify
Handles both adding new recurring tasks and modifying existing ones

Installation:
    1. Save to ~/.task/hooks/on-add_recurrence.py
    2. chmod +x ~/.task/hooks/on-add_recurrence.py
    3. cd ~/.task/hooks && ln -s on-add_recurrence.py on-modify_recurrence.py
"""

import sys
import json
import subprocess
from datetime import datetime, timedelta
import re
import os

# Optional debug mode - set environment variable DEBUG_RECURRENCE=1 to enable
DEBUG = os.environ.get('DEBUG_RECURRENCE', '0') == '1'
LOG_FILE = os.path.expanduser("~/.task/recurrence_debug.log")

# Prevent recursive hook calls
if os.environ.get('INSIDE_RECURRENCE_HOOK') == '1':
    # We're being called recursively - just pass through
    lines = sys.stdin.readlines()
    if lines:
        for line in lines:
            print(line.rstrip())
    sys.exit(0)

def debug_log(msg):
    """Write debug message to log file if debug enabled"""
    if DEBUG:
        with open(LOG_FILE, 'a') as f:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"[{timestamp}] ADD/MOD: {msg}\n")

if DEBUG:
    debug_log("="*60)
    debug_log("Hook starting")

# Read all input
lines = sys.stdin.readlines()
IS_ON_ADD = len(lines) == 1

if DEBUG:
    debug_log(f"Mode: {'ADD' if IS_ON_ADD else 'MODIFY'}, lines: {len(lines)}")


class RecurrenceHandler:
    """Handles enhanced recurrence for Taskwarrior"""
    
    def __init__(self):
        self.now = datetime.utcnow()
    
    def normalize_type(self, type_str):
        """Normalize type abbreviations to full names"""
        if not type_str:
            return 'periodic'
        
        type_lower = str(type_str).lower()
        
        # Handle abbreviations
        if type_lower in ['c', 'ch', 'cha', 'chai', 'chain', 'chained']:
            return 'chained'
        elif type_lower in ['p', 'pe', 'per', 'peri', 'perio', 'period', 'periodic']:
            return 'periodic'
        
        # Default to periodic for unknown
        return 'periodic'
    
    def parse_duration(self, duration_str):
        """Parse duration string (7d, 1w, 1mo, etc.) to timedelta"""
        if not duration_str:
            return None
        
        # Handle simple formats: 1min, 7d, 1w, 1mo, 1y
        match = re.match(r'(\d+)(s|min|h|d|w|mo|y)', str(duration_str).lower())
        if match:
            num, unit = match.groups()
            num = int(num)
            if unit == 's':
                return timedelta(seconds=num)
            elif unit == 'min':
                return timedelta(minutes=num)
            elif unit == 'h':
                return timedelta(hours=num)
            elif unit == 'd':
                return timedelta(days=num)
            elif unit == 'w':
                return timedelta(weeks=num)
            elif unit == 'mo':
                return timedelta(days=num * 30)
            elif unit == 'y':
                return timedelta(days=num * 365)
        
        # Handle ISO 8601 duration
        pattern = r'P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?'
        match = re.match(pattern, str(duration_str))
        if match:
            years, months, weeks, days, hours, mins, secs = match.groups()
            delta = timedelta()
            if days:
                delta += timedelta(days=int(days))
            if weeks:
                delta += timedelta(weeks=int(weeks))
            if hours:
                delta += timedelta(hours=int(hours))
            if mins:
                delta += timedelta(minutes=int(mins))
            if secs:
                delta += timedelta(seconds=int(secs))
            if months:
                delta += timedelta(days=int(months) * 30)
            if years:
                delta += timedelta(days=int(years) * 365)
            return delta
        
        return None
    
    def parse_date(self, date_str):
        """Parse ISO 8601 date string"""
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
    
    def parse_relative_date(self, date_str, anchor_date=None):
        """Parse relative date expression like 'due-2d'"""
        if not date_str:
            return None
        
        match = re.match(r'(due|scheduled|wait)\s*([+-])\s*(\d+)(s|d|w|mo|y)', 
                        str(date_str).lower())
        if match:
            ref_field, sign, num, unit = match.groups()
            num = int(num)
            
            if unit == 's':
                delta = timedelta(seconds=num)
            elif unit == 'd':
                delta = timedelta(days=num)
            elif unit == 'w':
                delta = timedelta(weeks=num)
            elif unit == 'mo':
                delta = timedelta(days=num * 30)
            elif unit == 'y':
                delta = timedelta(days=num * 365)
            else:
                return None
            
            if sign == '-':
                delta = -delta
            
            if anchor_date:
                return anchor_date + delta
            return None
        
        return None
    
    def is_template(self, task):
        """Check if task is a recurrence template"""
        return task.get('status') == 'recurring' and 'r' in task
    
    def is_instance(self, task):
        """Check if task is a recurrence instance"""
        return 'rtemplate' in task and 'rindex' in task
    
    def get_anchor_date(self, task):
        """Get the anchor date (due or scheduled) for recurrence"""
        if 'due' in task:
            return 'due', self.parse_date(task['due'])
        elif 'scheduled' in task:
            return 'scheduled', self.parse_date(task['scheduled'])
        return None, None
    
    def get_template(self, uuid):
        """Load a template by UUID"""
        try:
            env = os.environ.copy()
            env['INSIDE_RECURRENCE_HOOK'] = '1'
            result = subprocess.run(
                ['task', 'rc.hooks=off', uuid, 'export'],
                capture_output=True,
                check=True,
                env=env
            )
            tasks = json.loads(result.stdout.decode())
            return tasks[0] if tasks else None
        except (subprocess.CalledProcessError, json.JSONDecodeError, IndexError):
            return None
    
    def check_rend(self, template, new_date):
        """Check if recurrence end date has been reached"""
        if 'rend' not in template:
            return False
        
        rend_str = template['rend']
        rend_date = self.parse_date(rend_str)
        
        if rend_date and new_date > rend_date:
            if DEBUG:
                debug_log(f"Rend date reached: {new_date} > {rend_date}")
            return True
        
        return False
    
    def spawn_next_instance(self, template, current_idx, completion_time=None):
        """Spawn the next instance of a recurrence"""
        next_idx = current_idx + 1
        
        if DEBUG:
            debug_log(f"Spawning instance {next_idx} from template {template.get('uuid')}")
        
        recur_delta = self.parse_duration(template.get('r'))
        if not recur_delta:
            if DEBUG:
                debug_log(f"ERROR: Could not parse recurrence: {template.get('r')}")
            return False
        
        rtype = template.get('type', 'periodic')
        anchor_field = template.get('ranchor', 'due')
        
        if DEBUG:
            debug_log(f"  Type: {rtype}, Anchor: {anchor_field}, Delta: {recur_delta}")
        
        # Calculate anchor date for new instance
        if rtype == 'chained':
            base = completion_time or self.now
            anchor_date = base + recur_delta
            if DEBUG:
                debug_log(f"  Chained: base={base}, anchor={anchor_date}")
        else:  # periodic
            template_anchor = self.parse_date(template.get(anchor_field))
            if not template_anchor:
                if DEBUG:
                    debug_log(f"ERROR: Could not parse template anchor: {template.get(anchor_field)}")
                return False
            
            # Calculate next occurrence
            idx = next_idx
            anchor_date = template_anchor + (recur_delta * idx)
            
            # For periodic, advance to next future occurrence
            while anchor_date < self.now:
                idx += 1
                anchor_date = template_anchor + (recur_delta * idx)
            
            next_idx = idx
            if DEBUG:
                debug_log(f"  Periodic: template_anchor={template_anchor}, final_idx={next_idx}, anchor={anchor_date}")
        
        # Check rend date
        if self.check_rend(template, anchor_date):
            if DEBUG:
                debug_log("  Rend date reached, not spawning")
            return False
        
        # Build command
        cmd = ['task', 'rc.hooks=off', 'add', template['description']]
        cmd.append(f'{anchor_field}:{self.format_date(anchor_date)}')
        
        # Copy other attributes
        if 'until' in template:
            cmd.append(f'until:{template["until"]}')
        
        if 'rwait' in template:
            wait_date = self.parse_relative_date(template['rwait'], anchor_date)
            if wait_date:
                cmd.append(f'wait:{self.format_date(wait_date)}')
        
        if 'rscheduled' in template and anchor_field != 'scheduled':
            sched_date = self.parse_relative_date(template['rscheduled'], anchor_date)
            if sched_date:
                cmd.append(f'scheduled:{self.format_date(sched_date)}')
        
        if 'project' in template:
            cmd.append(f'project:{template["project"]}')
        if 'priority' in template:
            cmd.append(f'priority:{template["priority"]}')
        if 'tags' in template and template['tags']:
            cmd.extend([f'+{tag}' for tag in template['tags']])
        
        # Add metadata
        cmd.extend([
            f'rtemplate:{template["uuid"]}',
            f'rindex:{next_idx}'
        ])
        
        if DEBUG:
            debug_log(f"  Command: {' '.join(cmd)}")
        
        # Execute
        try:
            env = os.environ.copy()
            env['INSIDE_RECURRENCE_HOOK'] = '1'
            result = subprocess.run(cmd, capture_output=True, check=True, env=env)
            if DEBUG:
                debug_log(f"  Instance created: {result.stdout.decode().strip()}")
            
            # Update template's rlast
            update_cmd = ['task', 'rc.hooks=off', template['uuid'], 'modify', f'rlast:{next_idx}']
            env = os.environ.copy()
            env['INSIDE_RECURRENCE_HOOK'] = '1'
            subprocess.run(update_cmd, capture_output=True, check=True, env=env)
            if DEBUG:
                debug_log(f"  Template rlast updated to {next_idx}")
            
            sys.stderr.write(f"Spawned next instance {next_idx}\n")
            return True
            
        except subprocess.CalledProcessError as e:
            if DEBUG:
                debug_log(f"ERROR spawning instance: {e}")
                if e.stderr:
                    debug_log(f"  stderr: {e.stderr.decode()}")
            return False
    
    def create_template(self, task):
        """Convert a new task with r (recurrence) into a template"""
        if DEBUG:
            debug_log(f"Creating template: {task.get('description')}")
        
        if 'r' not in task:
            return task
        
        # Normalize and set type (with abbreviation support)
        task['type'] = self.normalize_type(task.get('type'))
        
        if DEBUG:
            debug_log(f"  Type: {task['type']}, r={task.get('r')}")
        
        # Mark as template
        task['status'] = 'recurring'
        task['rlast'] = '0'
        
        # Get anchor date
        anchor_field, anchor_date = self.get_anchor_date(task)
        
        if not anchor_field or not anchor_date:
            sys.stderr.write("ERROR: Recurring task must have either 'due' or 'scheduled' date\n")
            sys.exit(1)
        
        task['ranchor'] = anchor_field
        
        # Process wait
        if 'wait' in task:
            wait_str = task['wait']
            ref_field_match = re.match(r'(due|scheduled|wait)\s*([+-])\s*(\d+)(s|d|w|mo|y)', 
                                      str(wait_str).lower())
            
            if ref_field_match:
                task['rwait'] = wait_str
                del task['wait']
            else:
                wait_dt = self.parse_date(wait_str)
                if wait_dt and anchor_date:
                    delta_sec = int((anchor_date - wait_dt).total_seconds())
                    task['rwait'] = f'{anchor_field}-{delta_sec}s'
                    del task['wait']
        
        # Process scheduled
        if 'scheduled' in task and anchor_field != 'scheduled':
            sched_str = task['scheduled']
            ref_field_match = re.match(r'(due|scheduled|wait)\s*([+-])\s*(\d+)(s|d|w|mo|y)', 
                                      str(sched_str).lower())
            
            if ref_field_match:
                task['rscheduled'] = sched_str
                del task['scheduled']
            else:
                sched_dt = self.parse_date(sched_str)
                if sched_dt and anchor_date:
                    delta_sec = int((anchor_date - sched_dt).total_seconds())
                    task['rscheduled'] = f'{anchor_field}-{delta_sec}s'
                    del task['scheduled']
        
        if DEBUG:
            debug_log(f"  Template created: status={task['status']}, rlast={task['rlast']}")
        
        return task
    
    def handle_template_modification(self, original, modified):
        """Handle modifications to a template"""
        if modified.get('status') in ['completed', 'deleted']:
            sys.stderr.write("ERROR: Cannot complete or delete a recurrence template.\n")
            sys.stderr.write("Delete the instances first, or modify the template instead.\n")
            sys.exit(1)
        
        # Normalize type if it was changed
        if 'type' in modified:
            modified['type'] = self.normalize_type(modified['type'])
        
        return modified
    
    def handle_instance_completion(self, original, modified):
        """Handle completion/deletion of an instance - spawn next instance"""
        if DEBUG:
            debug_log(f"Instance completion detected: {original.get('description')}")
            debug_log(f"  Status changed: {original.get('status')} -> {modified.get('status')}")
        
        # Only spawn if actually completing or deleting
        if modified.get('status') not in ['completed', 'deleted']:
            return modified
        
        # Get template
        template_uuid = original.get('rtemplate')
        current_idx = int(original.get('rindex', 0))
        
        if DEBUG:
            debug_log(f"  Template: {template_uuid}, Index: {current_idx}")
        
        template = self.get_template(template_uuid)
        if not template:
            if DEBUG:
                debug_log("  ERROR: Could not load template")
            return modified
        
        # Only spawn if this is the latest instance
        last_idx = int(template.get('rlast', '0'))
        if DEBUG:
            debug_log(f"  Template rlast: {last_idx}")
        
        if current_idx >= last_idx:
            if DEBUG:
                debug_log("  This is the latest instance, spawning next")
            
            # Get completion time for chained recurrence
            completion_time = None
            if modified.get('status') == 'completed' and 'end' in modified:
                completion_time = self.parse_date(modified['end'])
            
            self.spawn_next_instance(template, current_idx, completion_time)
        else:
            if DEBUG:
                debug_log("  Not the latest instance, skipping spawn")
        
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
        
        # Check if this should be a template
        if 'r' in task:
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
        
        # Adding recurrence to existing task?
        if 'r' in modified and modified.get('status') != 'recurring':
            modified = handler.create_template(modified)
            sys.stderr.write("Created recurrence template. First instance will be generated on exit.\n")
        
        # Modifying a template?
        elif handler.is_template(original):
            modified = handler.handle_template_modification(original, modified)
        
        # Completing an instance?
        elif handler.is_instance(original):
            modified = handler.handle_instance_completion(original, modified)
        
        print(json.dumps(modified))
    
    if DEBUG:
        debug_log("Hook completed")
    
    sys.exit(0)


if __name__ == '__main__':
    main()
