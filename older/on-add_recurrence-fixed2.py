#!/usr/bin/env python3
"""
Taskwarrior Enhanced Recurrence Hook - On-Exit
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

# Optional debug mode
DEBUG = os.environ.get('DEBUG_RECURRENCE', '0') == '1'
LOG_FILE = os.path.expanduser("~/.task/recurrence_debug.log")

def debug_log(msg):
    """Write debug message to log file if debug enabled"""
    if DEBUG:
        with open(LOG_FILE, 'a') as f:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"[{timestamp}] EXIT: {msg}\n")

if DEBUG:
    debug_log("="*60)
    debug_log("on-exit hook started")


class RecurrenceSpawner:
    """Spawns new recurrence instances"""
    
    def __init__(self):
        self.now = datetime.utcnow()
    
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
        """Parse relative date like 'due-2d' given anchor date"""
        if not rel_str or not anchor_date:
            return None
        
        match = re.match(r'(due|scheduled|wait)\s*([+-])\s*(\d+)(s|d|w|mo|y)', 
                        str(rel_str).lower())
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
            
            return anchor_date + delta
        
        return None
    
    def get_template(self, uuid):
        """Fetch template task by UUID"""
        try:
            result = subprocess.run(
                ['task', 'rc.hooks=off', uuid, 'export'],
                capture_output=True,
                text=True,
                check=True
            )
            lines = [line for line in result.stdout.strip().split('\n') if line]
            if lines:
                return json.loads(lines[0])
        except:
            pass
        return None
    
    def check_rend(self, template, new_date):
        """Check if new_date exceeds recurrence end date (rend)"""
        if 'rend' not in template:
            return False
        
        rend_str = template['rend']
        anchor_field = template.get('ranchor', 'due')
        anchor_date = self.parse_date(template.get(anchor_field))
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
        
        rtype = template.get('type', 'periodic')
        anchor_field = template.get('ranchor', 'due')
        
        # Build command
        cmd = ['task', 'rc.hooks=off', 'add', template['description']]
        
        # Calculate anchor date
        if rtype == 'chained':
            base = completion_time or self.now
            anchor_date = base + recur_delta
        else:  # periodic
            template_anchor = self.parse_date(template.get(anchor_field))
            if not template_anchor:
                return None
            
            # Find next occurrence after now
            idx = index
            anchor_date = template_anchor + (recur_delta * idx)
            while anchor_date < self.now:
                idx += 1
                anchor_date = template_anchor + (recur_delta * idx)
            index = idx
        
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
        
        # Process scheduled
        if 'rscheduled' in template and anchor_field != 'scheduled':
            sched_date = self.parse_relative_date(template['rscheduled'], anchor_date)
            if sched_date:
                cmd.append(f'scheduled:{self.format_date(sched_date)}')
        
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
        
        # Execute
        try:
            subprocess.run(cmd, capture_output=True, check=True)
            
            # Update template's rlast
            subprocess.run(
                ['task', 'rc.hooks=off', template['uuid'], 'modify', f'rlast:{index}'],
                capture_output=True,
                check=True
            )
            
            if DEBUG:
                debug_log(f"Instance {index} created successfully")
            
            return f"Created instance {index}"
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
            
            # Completed/deleted instance?
            if (task.get('status') in ['completed', 'deleted'] and 
                'rtemplate' in task and 'rindex' in task):
                
                if DEBUG:
                    debug_log(f"Found completed/deleted instance: rindex={task['rindex']}")
                
                template = self.get_template(task['rtemplate'])
                if not template:
                    if DEBUG:
                        debug_log(f"Could not fetch template: {task['rtemplate']}")
                    continue
                
                if DEBUG:
                    debug_log(f"Template found: {template.get('description')}, rlast={template.get('rlast')}")
                
                current_idx = int(task['rindex'])
                last_idx = int(template.get('rlast', '0'))
                
                if DEBUG:
                    debug_log(f"Checking: current_idx={current_idx}, last_idx={last_idx}")
                
                # Only spawn if this is the latest instance
                if current_idx >= last_idx:
                    if DEBUG:
                        debug_log(f"Will spawn next instance (current >= last)")
                    
                    completion = None
                    if task.get('status') == 'completed' and 'end' in task:
                        completion = self.parse_date(task['end'])
                        if DEBUG:
                            debug_log(f"Completion time: {completion}")
                    
                    msg = self.create_instance(template, current_idx + 1, completion)
                    if msg:
                        feedback.append(msg)
                        if DEBUG:
                            debug_log(f"Result: {msg}")
                else:
                    if DEBUG:
                        debug_log(f"Skipping spawn: not the latest instance")
            
            # New template? (handle both string and int rlast)
            elif (task.get('status') == 'recurring' and 
                  'r' in task and 
                  str(task.get('rlast', '')).strip() in ['0', '']):
                
                if DEBUG:
                    debug_log(f"Found new template: {task.get('description')}")
                
                msg = self.create_instance(task, 1)
                if msg:
                    feedback.append(msg)
        
        return feedback


def main():
    """Main entry point for on-exit"""
    lines = sys.stdin.readlines()
    
    if DEBUG:
        debug_log(f"Received {len(lines)} lines of input")
    
    if not lines:
        sys.exit(0)
    
    try:
        tasks = [json.loads(line) for line in lines if line.strip()]
        if DEBUG:
            debug_log(f"Parsed {len(tasks)} tasks")
            for i, task in enumerate(tasks):
                debug_log(f"Task {i}: uuid={task.get('uuid')}, status={task.get('status')}, "
                         f"desc={task.get('description', '')[:50]}")
    except json.JSONDecodeError as e:
        if DEBUG:
            debug_log(f"JSON decode error: {e}")
        sys.exit(0)
    
    spawner = RecurrenceSpawner()
    feedback = spawner.process_tasks(tasks)
    
    for msg in feedback:
        print(msg)
    
    if DEBUG:
        debug_log(f"on-exit completed with {len(feedback)} feedback messages")
    
    sys.exit(0)


if __name__ == '__main__':
    main()
