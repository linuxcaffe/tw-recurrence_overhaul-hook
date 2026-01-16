#!/usr/bin/env python3
"""
Taskwarrior Enhanced Recurrence Hook - On-Exit (DEBUG VERSION)
Spawns new recurrence instances when needed

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

# DEBUG: Setup logging
DEBUG = True
LOG_FILE = os.path.expanduser("~/.task/recurrence_debug.log")

def debug_log(msg):
    """Write debug message to log file"""
    if DEBUG:
        with open(LOG_FILE, 'a') as f:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"[{timestamp}] EXIT: {msg}\n")

debug_log("="*60)
debug_log("on-exit hook started")

class RecurrenceSpawner:
    """Spawns new recurrence instances"""
    
    def __init__(self):
        self.now = datetime.utcnow()
        debug_log(f"Initialized spawner, now={self.now}")
    
    def parse_duration(self, duration_str):
        """Parse duration string to timedelta"""
        if not duration_str:
            return None
        
        # Simple formats: 7d, 1w, 1mo, 1y
        match = re.match(r'(\d+)(s|d|w|mo|y)', duration_str.lower())
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
        match = re.match(pattern, duration_str)
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
            clean = date_str.replace('Z', '').replace('+00:00', '')
            return datetime.strptime(clean[:15], '%Y%m%dT%H%M%S')
        except (ValueError, AttributeError):
            return None
    
    def format_date(self, dt):
        """Format datetime as ISO 8601"""
        return dt.strftime('%Y%m%dT%H%M%SZ')
    
    def parse_relative_date(self, rel_str, anchor_date):
        """
        Parse relative date like 'due-2d' or 'scheduled+1w' given anchor date
        Returns calculated datetime or None
        """
        if not rel_str or not anchor_date:
            return None
        
        # Match patterns like "due-2d", "scheduled+1w"
        match = re.match(r'(due|scheduled|wait)\s*([+-])\s*(\d+)(s|d|w|mo|y)', 
                        rel_str.lower())
        if match:
            ref_field, sign, num, unit = match.groups()
            num = int(num)
            
            # Parse unit
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
            
            # Apply sign
            if sign == '-':
                delta = -delta
            
            return anchor_date + delta
        
        return None
    
    def get_template(self, uuid):
        """Fetch template task by UUID"""
        debug_log(f"Fetching template: {uuid}")
        try:
            result = subprocess.run(
                ['task', 'rc.hooks=off', uuid, 'export'],
                capture_output=True,
                text=True,
                check=True
            )
            debug_log(f"Template export stdout: {result.stdout[:200]}")
            lines = [line for line in result.stdout.strip().split('\n') if line]
            if lines:
                template = json.loads(lines[0])
                debug_log(f"Template loaded: {template.get('description')}, status={template.get('status')}, r={template.get('r')}, type={template.get('type')}")
                return template
        except Exception as e:
            debug_log(f"Error fetching template: {e}")
        return None
    
    def check_rend(self, template, new_date):
        """Check if new_date exceeds recurrence end date (rend)"""
        if 'rend' not in template:
            debug_log("No rend date in template")
            return False
        
        rend_str = template['rend']
        debug_log(f"Checking rend: {rend_str}")
        
        # Try parsing as relative first
        anchor_field = template.get('ranchor', 'due')
        anchor_date = self.parse_date(template.get(anchor_field))
        rend_date = self.parse_relative_date(rend_str, anchor_date)
        
        # If not relative, try absolute
        if not rend_date:
            rend_date = self.parse_date(rend_str)
        
        if rend_date and new_date > rend_date:
            debug_log(f"Rend date reached: {new_date} > {rend_date}")
            return True
        
        debug_log(f"Rend not reached: {new_date} <= {rend_date}")
        return False
    
    def create_instance(self, template, index, completion_time=None):
        """Create a new instance task"""
        debug_log(f"Creating instance {index} from template {template.get('uuid')}")
        
        recur_delta = self.parse_duration(template.get('r'))
        if not recur_delta:
            debug_log(f"ERROR: Could not parse recurrence: {template.get('r')}")
            return None
        
        debug_log(f"Recurrence delta: {recur_delta}")
        
        rtype = template.get('type', 'periodic')
        anchor_field = template.get('ranchor', 'due')
        debug_log(f"Type: {rtype}, Anchor: {anchor_field}")
        
        # Build command
        cmd = ['task', 'rc.hooks=off', 'add', template['description']]
        
        # Calculate anchor date
        if rtype == 'chained':
            base = completion_time or self.now
            anchor_date = base + recur_delta
            debug_log(f"Chained: base={base}, anchor={anchor_date}")
        else:  # periodic
            template_anchor = self.parse_date(template.get(anchor_field))
            if not template_anchor:
                debug_log(f"ERROR: Could not parse template anchor date: {template.get(anchor_field)}")
                return None
            
            # Find next occurrence after now
            idx = index
            anchor_date = template_anchor + (recur_delta * idx)
            debug_log(f"Periodic: template_anchor={template_anchor}, initial_calc={anchor_date}")
            
            while anchor_date < self.now:
                idx += 1
                anchor_date = template_anchor + (recur_delta * idx)
                debug_log(f"  Advancing: idx={idx}, anchor={anchor_date}")
            
            index = idx
            debug_log(f"Final periodic: idx={index}, anchor={anchor_date}")
        
        # Check rend date (recurrence end)
        if self.check_rend(template, anchor_date):
            return "Recurrence ended (rend date reached)"
        
        # Add anchor date
        cmd.append(f'{anchor_field}:{self.format_date(anchor_date)}')
        debug_log(f"Added anchor: {anchor_field}:{self.format_date(anchor_date)}")
        
        # If template has until, copy it to instance
        if 'until' in template:
            cmd.append(f'until:{template["until"]}')
            debug_log(f"Added until: {template['until']}")
        
        # Process wait
        if 'rwait' in template:
            wait_str = template['rwait']
            wait_date = self.parse_relative_date(wait_str, anchor_date)
            
            if wait_date:
                cmd.append(f'wait:{self.format_date(wait_date)}')
                debug_log(f"Added wait: {self.format_date(wait_date)}")
        
        # Process scheduled
        if 'rscheduled' in template and anchor_field != 'scheduled':
            sched_str = template['rscheduled']
            sched_date = self.parse_relative_date(sched_str, anchor_date)
            
            if sched_date:
                cmd.append(f'scheduled:{self.format_date(sched_date)}')
                debug_log(f"Added scheduled: {self.format_date(sched_date)}")
        
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
            f'rindex:{index}'
        ])
        
        debug_log(f"Full command: {' '.join(cmd)}")
        
        # Execute
        try:
            result = subprocess.run(cmd, capture_output=True, check=True)
            debug_log(f"Instance created successfully")
            debug_log(f"  stdout: {result.stdout.decode()}")
            
            # Update template's rlast
            update_cmd = ['task', 'rc.hooks=off', template['uuid'], 'modify', f'rlast:{index}']
            debug_log(f"Updating template rlast: {' '.join(update_cmd)}")
            result = subprocess.run(update_cmd, capture_output=True, check=True)
            debug_log(f"Template updated successfully")
            
            return f"Created instance {index}"
        except subprocess.CalledProcessError as e:
            debug_log(f"ERROR creating instance: {e}")
            debug_log(f"  stderr: {e.stderr.decode() if e.stderr else 'none'}")
            debug_log(f"  stdout: {e.stdout.decode() if e.stdout else 'none'}")
            return None
    
    def process_tasks(self, tasks):
        """Process tasks and spawn instances"""
        debug_log(f"Processing {len(tasks)} tasks")
        feedback = []
        
        for i, task in enumerate(tasks):
            debug_log(f"Task {i}: uuid={task.get('uuid')}, status={task.get('status')}, desc={task.get('description')}")
            debug_log(f"  Has rtemplate: {'rtemplate' in task}, Has rindex: {'rindex' in task}")
            debug_log(f"  Has r: {'r' in task}, rlast={task.get('rlast')}")
            
            # Completed/deleted instance?
            if (task.get('status') in ['completed', 'deleted'] and 
                'rtemplate' in task and 'rindex' in task):
                
                debug_log(f"Found completed/deleted instance")
                template = self.get_template(task['rtemplate'])
                if not template:
                    debug_log(f"Could not load template")
                    continue
                
                current_idx = int(task['rindex'])
                last_idx = int(template.get('rlast', '0'))
                debug_log(f"Instance index: {current_idx}, Template last: {last_idx}")
                
                # Only spawn if this is the latest instance
                if current_idx >= last_idx:
                    debug_log(f"This is the latest instance, spawning next")
                    completion = None
                    if task.get('status') == 'completed' and 'end' in task:
                        completion = self.parse_date(task['end'])
                    
                    msg = self.create_instance(template, current_idx + 1, completion)
                    if msg:
                        feedback.append(msg)
                else:
                    debug_log(f"Not the latest instance, skipping")
            
            # New template?
            elif (task.get('status') == 'recurring' and 
                  'r' in task and 
                  task.get('rlast') == '0'):
                
                debug_log(f"Found new template (rlast=0)")
                msg = self.create_instance(task, 1)
                if msg:
                    feedback.append(msg)
            else:
                debug_log(f"Task doesn't match any spawn conditions")
        
        debug_log(f"Processed all tasks, feedback: {feedback}")
        return feedback

def main():
    """Main entry point for on-exit"""
    debug_log("Main function started")
    
    lines = sys.stdin.readlines()
    debug_log(f"Read {len(lines)} lines from stdin")
    
    if not lines:
        debug_log("No input, exiting")
        sys.exit(0)
    
    try:
        tasks = [json.loads(line) for line in lines if line.strip()]
        debug_log(f"Parsed {len(tasks)} tasks from JSON")
    except json.JSONDecodeError as e:
        debug_log(f"JSON decode error: {e}")
        sys.exit(0)
    
    spawner = RecurrenceSpawner()
    feedback = spawner.process_tasks(tasks)
    
    for msg in feedback:
        print(msg)
        debug_log(f"Output: {msg}")
    
    debug_log("on-exit hook completed")
    sys.exit(0)

if __name__ == '__main__':
    main()
