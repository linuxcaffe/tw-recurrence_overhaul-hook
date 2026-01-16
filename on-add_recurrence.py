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
from datetime import datetime, timedelta
import re
import os

# Optional debug mode - set environment variable DEBUG_RECURRENCE=1 to enable
DEBUG = os.environ.get('DEBUG_RECURRENCE', '0') == '1'
LOG_FILE = os.path.expanduser("~/.task/recurrence_debug.log")

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
        
        # Handle simple formats
        match = re.match(r'(\d+)(d|w|mo|y)', str(duration_str).lower())
        if match:
            num, unit = match.groups()
            num = int(num)
            if unit == 'd':
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
            result = datetime.strptime(clean[:15], '%Y%m%dT%H%M%S')
            if DEBUG:
                debug_log(f"  parse_date: '{date_str}' -> {result}")
            return result
        except (ValueError, AttributeError) as e:
            if DEBUG:
                debug_log(f"  parse_date FAILED: '{date_str}' -> {e}")
            return None
    
    def format_date(self, dt):
        """Format datetime as ISO 8601"""
        return dt.strftime('%Y%m%dT%H%M%SZ')
    
    def parse_relative_date(self, date_str):
        """Parse relative date expression like 'due-2d' or 'due-2days'"""
        if not date_str:
            return None, None
        
        match = re.match(r'(due|scheduled|wait)\s*([+-])\s*(\d+)(s|d|days?|w|weeks?|mo|months?|y|years?)', 
                        str(date_str).lower())
        if match:
            ref_field, sign, num, unit = match.groups()
            num = int(num)
            
            # Normalize unit to single letter
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
                return None, None
            
            if sign == '-':
                delta = -delta
            
            return ref_field, delta
        
        return None, None
    
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
            if DEBUG:
                debug_log(f"  ERROR: No valid anchor date found")
                debug_log(f"  Task due: {task.get('due')}")
                debug_log(f"  Task scheduled: {task.get('scheduled')}")
            sys.stderr.write("ERROR: Recurring task must have either 'due' or 'scheduled' date\n")
            sys.stderr.write(f"       Provided: due={task.get('due')}, scheduled={task.get('scheduled')}\n")
            # Return the task unchanged rather than crashing
            if DEBUG:
                debug_log("  Returning task unchanged")
            return task
        
        task['ranchor'] = anchor_field
        
        # Process wait
        if 'wait' in task:
            wait_str = task['wait']
            ref_field, offset = self.parse_relative_date(wait_str)
            
            if ref_field and offset:
                # Already in relative format - preserve it as-is
                task['rwait'] = wait_str
                del task['wait']
            else:
                # Absolute date - convert to relative offset in seconds
                wait_dt = self.parse_date(wait_str)
                if wait_dt and anchor_date:
                    delta_sec = int((wait_dt - anchor_date).total_seconds())
                    # Use negative offset since wait is typically before due
                    if delta_sec != 0:
                        task['rwait'] = f'{anchor_field}{delta_sec:+d}s'
                    del task['wait']
        
        # Process scheduled
        if 'scheduled' in task and anchor_field != 'scheduled':
            sched_str = task['scheduled']
            ref_field, offset = self.parse_relative_date(sched_str)
            
            if ref_field and offset:
                # Already in relative format - preserve it as-is
                task['rscheduled'] = sched_str
                del task['scheduled']
            else:
                # Absolute date - convert to relative offset in seconds
                sched_dt = self.parse_date(sched_str)
                if sched_dt and anchor_date:
                    delta_sec = int((sched_dt - anchor_date).total_seconds())
                    if delta_sec != 0:
                        task['rscheduled'] = f'{anchor_field}{delta_sec:+d}s'
                    del task['scheduled']
        
        if DEBUG:
            debug_log(f"  Template created: status={task['status']}, rlast={task['rlast']}")
        
        return task
    
    def handle_template_modification(self, original, modified):
        """Handle modifications to a template"""
        # If template is being deleted/completed, remove r field so it can be purged
        if modified.get('status') in ['deleted', 'completed']:
            if 'r' in modified:
                del modified['r']
        
        # Normalize type if it was changed
        if 'type' in modified:
            modified['type'] = self.normalize_type(modified['type'])
        
        return modified
    
    def handle_instance_completion(self, original, modified):
        """Handle completion/deletion of an instance"""
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
