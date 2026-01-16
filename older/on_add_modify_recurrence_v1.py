#!/usr/bin/env python3
"""
Taskwarrior Enhanced Recurrence Hook - On-Add/On-Modify
Handles both adding new recurring tasks and modifying existing ones

Installation:
    Save to ~/.task/hooks/on-add-modify_recurrence.py
    chmod +x ~/.task/hooks/on-add-modify_recurrence.py
    cd ~/.task/hooks
    ln -s on-add-modify_recurrence.py on-add_recurrence.py
    ln -s on-add-modify_recurrence.py on-modify_recurrence.py
"""

import sys
import json
from datetime import datetime, timedelta
import re
import os

# DEBUG: Setup logging
DEBUG = True
LOG_FILE = os.path.expanduser("~/.task/recurrence_debug.log")

def debug_log(msg):
    """Write debug message to log file"""
    if DEBUG:
        with open(LOG_FILE, 'a') as f:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            hook_name = "ADD" if len(sys.stdin.readlines()) == 1 else "MODIFY"
            sys.stdin.seek(0)  # Reset after peek
            f.write(f"[{timestamp}] {hook_name}: {msg}\n")

# Detect which hook we are
IS_ON_ADD = False
lines = sys.stdin.readlines()
if len(lines) == 1:
    IS_ON_ADD = True
    HOOK_TYPE = "ADD"
else:
    HOOK_TYPE = "MODIFY"

debug_log("="*60)
debug_log(f"on-{HOOK_TYPE.lower()} hook started")

class RecurrenceHandler:
    """Handles enhanced recurrence for Taskwarrior"""
    
    def __init__(self):
        self.now = datetime.utcnow()
        debug_log(f"Initialized handler, now={self.now}")
    
    def parse_duration(self, duration_str):
        """Parse duration string (7d, 1w, 1mo, etc.) to timedelta"""
        if not duration_str:
            return None
        
        # Handle simple formats like 7d, 1w, 1mo, 1y
        match = re.match(r'(\d+)(d|w|mo|y)', duration_str.lower())
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
        match = re.match(pattern, duration_str)
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
            clean = date_str.replace('Z', '').replace('+00:00', '')
            return datetime.strptime(clean[:15], '%Y%m%dT%H%M%S')
        except (ValueError, AttributeError):
            return None
    
    def format_date(self, dt):
        """Format datetime as ISO 8601"""
        return dt.strftime('%Y%m%dT%H%M%SZ')
    
    def parse_relative_date(self, date_str):
        """
        Parse relative date expression like 'due-2d' or 'scheduled+1w'
        Returns (reference_field, offset_timedelta) or (None, None)
        """
        if not date_str:
            return None, None
        
        match = re.match(r'(due|scheduled|wait)\s*([+-])\s*(\d+)(d|w|mo|y)', 
                        date_str.lower())
        if match:
            ref_field, sign, num, unit = match.groups()
            num = int(num)
            
            if unit == 'd':
                delta = timedelta(days=num)
            elif unit == 'w':
                delta = timedelta(weeks=num)
            elif unit == 'mo':
                delta = timedelta(days=num * 30)
            elif unit == 'y':
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
        debug_log(f"create_template called for: {task.get('description')}")
        debug_log(f"  Has r: {'r' in task}, r={task.get('r')}")
        debug_log(f"  Has type: {'type' in task}, type={task.get('type')}")
        
        if 'r' not in task:
            debug_log("  No recurrence, returning unchanged")
            return task
        
        # Default to periodic if no type specified
        if 'type' not in task:
            task['type'] = 'periodic'
            debug_log(f"  Set default type: periodic")
        
        # Mark as template
        task['status'] = 'recurring'
        task['rlast'] = '0'
        debug_log(f"  Set status=recurring, rlast=0")
        
        # Get anchor date (due or scheduled)
        anchor_field, anchor_date = self.get_anchor_date(task)
        debug_log(f"  Anchor: {anchor_field}={anchor_date}")
        
        if not anchor_field or not anchor_date:
            debug_log("  ERROR: No anchor date found!")
            sys.stderr.write("ERROR: Recurring task must have either 'due' or 'scheduled' date\n")
            sys.exit(1)
        
        # Store which field is the anchor
        task['ranchor'] = anchor_field
        debug_log(f"  Set ranchor={anchor_field}")
        
        # Process wait
        if 'wait' in task:
            wait_str = task['wait']
            debug_log(f"  Processing wait: {wait_str}")
            
            ref_field, offset = self.parse_relative_date(wait_str)
            if ref_field and offset:
                task['rwait'] = wait_str
                del task['wait']
                debug_log(f"    Stored as relative: rwait={wait_str}")
            else:
                wait_dt = self.parse_date(wait_str)
                if wait_dt and anchor_date:
                    delta_sec = int((anchor_date - wait_dt).total_seconds())
                    task['rwait'] = f'{anchor_field}-{delta_sec}s'
                    del task['wait']
                    debug_log(f"    Converted to relative: rwait={task['rwait']}")
        
        # Process scheduled
        if 'scheduled' in task and anchor_field != 'scheduled':
            sched_str = task['scheduled']
            debug_log(f"  Processing scheduled: {sched_str}")
            
            ref_field, offset = self.parse_relative_date(sched_str)
            if ref_field and offset:
                task['rscheduled'] = sched_str
                del task['scheduled']
                debug_log(f"    Stored as relative: rscheduled={sched_str}")
            else:
                sched_dt = self.parse_date(sched_str)
                if sched_dt and anchor_date:
                    delta_sec = int((anchor_date - sched_dt).total_seconds())
                    task['rscheduled'] = f'{anchor_field}-{delta_sec}s'
                    del task['scheduled']
                    debug_log(f"    Converted to relative: rscheduled={task['rscheduled']}")
        
        # Process rend
        if 'rend' in task:
            debug_log(f"  Has rend: {task['rend']}")
        
        debug_log(f"  Template created successfully")
        debug_log(f"  Final task: status={task.get('status')}, rlast={task.get('rlast')}, type={task.get('type')}")
        return task
    
    def handle_template_modification(self, original, modified):
        """Handle modifications to a template"""
        debug_log(f"Template modification: {modified.get('description')}")
        
        if modified.get('status') in ['completed', 'deleted']:
            debug_log("  ERROR: Attempting to complete/delete template")
            sys.stderr.write("ERROR: Cannot complete or delete a recurrence template.\n")
            sys.stderr.write("Delete the instances first, or modify the template instead.\n")
            sys.exit(1)
        
        return modified
    
    def handle_instance_completion(self, original, modified):
        """Handle completion/deletion of an instance"""
        debug_log(f"Instance completion: {modified.get('description')}, status={modified.get('status')}")
        return modified

def main():
    """Main hook entry point"""
    debug_log("Main function started")
    debug_log(f"Read {len(lines)} lines from stdin")
    
    if not lines:
        debug_log("No input, exiting")
        sys.exit(0)
    
    handler = RecurrenceHandler()
    
    if IS_ON_ADD:
        # On-add: single task input
        try:
            task = json.loads(lines[0])
            debug_log(f"Parsed task: {task.get('description')}")
            debug_log(f"  status={task.get('status')}, has r={'r' in task}")
        except json.JSONDecodeError as e:
            debug_log(f"JSON decode error: {e}")
            sys.stderr.write(f"Error parsing JSON: {e}\n")
            sys.exit(1)
        
        # Check if this should be a template
        if 'r' in task:
            debug_log("Task has recurrence, creating template")
            task = handler.create_template(task)
            sys.stderr.write("Created recurrence template. First instance will be generated on exit.\n")
        else:
            debug_log("Regular task, no changes")
        
        print(json.dumps(task))
        debug_log(f"Output task: status={task.get('status')}, rlast={task.get('rlast')}")
    
    else:
        # On-modify: two task inputs (original and modified)
        if len(lines) < 2:
            debug_log("Less than 2 lines for modify, returning first line if exists")
            if lines:
                print(json.dumps(json.loads(lines[0])))
            sys.exit(0)
        
        try:
            original = json.loads(lines[0])
            modified = json.loads(lines[1])
            debug_log(f"Parsed original: {original.get('description')}")
            debug_log(f"Parsed modified: {modified.get('description')}")
        except json.JSONDecodeError as e:
            debug_log(f"JSON decode error: {e}")
            sys.stderr.write(f"Error parsing JSON: {e}\n")
            sys.exit(1)
        
        # Creating a new template via modify?
        if 'r' in modified and modified.get('status') != 'recurring':
            debug_log("Adding recurrence to existing task, creating template")
            modified = handler.create_template(modified)
            sys.stderr.write("Created recurrence template. First instance will be generated on exit.\n")
        
        # Modifying a template?
        elif handler.is_template(original):
            debug_log("Modifying existing template")
            modified = handler.handle_template_modification(original, modified)
        
        # Completing an instance?
        elif handler.is_instance(original):
            debug_log("Completing instance")
            modified = handler.handle_instance_completion(original, modified)
        
        print(json.dumps(modified))
    
    debug_log("Hook completed")
    sys.exit(0)

if __name__ == '__main__':
    main()
