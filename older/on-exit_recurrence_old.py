#!/usr/bin/env python3
"""
Taskwarrior Enhanced Recurrence Hook - On-Exit
Spawns new recurrence instances when needed

Version: 0.3.5
Last Updated: 2026-01-11

Changelog:
  0.3.5 (2026-01-11):
    - CRITICAL FIX: rlast update now uses task ID instead of UUID (works in test environments)
    - Fixed: Better error handling for rlast updates
    - Fixed: Won't crash if rlast update fails
    
  0.3.4 (2026-01-10):
    - CRITICAL FIX: Periodic instance #1 now has correct due date (template date)
    - Fixed: Periodic calculation now uses (index-1) so first instance matches template
    - Added: rlist alias as backup for rtemplates report
    
  0.3.3 (2026-01-10):
    - CRITICAL FIX: Removed recur field from instances (was causing status:recurring)
    - FIXED: Instances now have proper status:pending/waiting (not recurring)
    - FIXED: Instances now completable with 'task X done'
    - FIXED: Instances now appear in normal task lists
    
  0.3.2 (2026-01-10):
    - FIXED: New templates now create only 1 instance initially (not all rlimit)
    - FIXED: rlimit pile-up works correctly on completion (maintains limit)
    
  0.3.1 (2026-01-10):
    - FIXED: rlimit now works correctly - counts existing pending instances
    - FIXED: rlimit spawns to maintain limit, not all at once upfront
    - FIXED: Periodic tasks keep template's until date (valid time-based limit)
    - FIXED: Chained tasks never copy until (prevents instant expiration)
    - FIXED: Don't spawn from deleted templates
    - Added: +RECURRING tag to all instances for native R indicator
    
  0.3.0 (2026-01-09):
    - Added: Template caching (avoid repeated fetches in bulk operations)
    - Added: Bulk deletion protection (sort by index, process highest first)
    - Added: rlimit support for controlled instance pile-up (periodic only)
    - Added: 'recur' field copied to instances for native R indicator display
    - Improved: Better feedback with task IDs
    - Improved: Smarter deletion handling for chained vs periodic
    - Performance: Parse task ID from stdout (no extra subprocess)
    
  0.2.1 (2026-01-09):
    - Fixed: Chained tasks now spawn on deletion (user skipping instance)
    - Fixed: Periodic tasks ignore deletion (time-based, not user-driven)
    - Improved: Better distinction between completion and deletion logic
    - Improved: Feedback shows task IDs for immediate use ("task 46: description")
    - Improved: Deleted chained instances show how to stop all future instances
    - Performance: Parse task ID from stdout instead of extra subprocess call
    
  0.2.0 (2026-01-08):
    - Fixed: Only spawn on completion, not deletion (prevents GC infinite loop)
    - Fixed: JSON parsing bug when fetching templates
    - Added: Better feedback messages with task descriptions
    - Added: Safety check for old templates (60s entry time filter)
    - Added: Default far-future 'until' date to prevent GC issues
    
  0.1.0 (2026-01-06):
    - Initial implementation

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
        self._template_cache = {}  # Cache templates during this hook execution
    
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
        """Fetch template task by UUID with caching"""
        # Check cache first
        if uuid in self._template_cache:
            if DEBUG:
                debug_log(f"Template {uuid[:8]} retrieved from cache")
            return self._template_cache[uuid]
        
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
                    
                    # Don't use deleted templates
                    if template.get('status') == 'deleted':
                        if DEBUG:
                            debug_log(f"Template is deleted, ignoring")
                        return None
                    
                    if DEBUG:
                        debug_log(f"Template fetched via method 1: {template.get('description')}, status={template.get('status')}")
                    # Cache it
                    self._template_cache[uuid] = template
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
                # Cache it
                self._template_cache[uuid] = template
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
            
            # Calculate next occurrence from template anchor
            # For periodic: Instance #N due = template_anchor + ((N-1) * recurrence)
            # This way instance #1 has same due as template
            anchor_date = template_anchor + (recur_delta * (index - 1))
        
        # Check rend date
        if self.check_rend(template, anchor_date):
            return "Recurrence ended (rend date reached)"
        
        # Add anchor date
        cmd.append(f'{anchor_field}:{self.format_date(anchor_date)}')
        
        # Handle until dates
        # Periodic: copy template's until (valid time-based limit)
        # Chained: never copy until (would cause instant expiration)
        if rtype == 'periodic' and 'until' in template:
            cmd.append(f'until:{template["until"]}')
        else:
            # Default: instances expire 10 years from now (prevents GC auto-deletion)
            far_future = self.now + timedelta(days=3650)
            cmd.append(f'until:{self.format_date(far_future)}')
        
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
        
        # Add RECURRING virtual tag for filtering and potential native recurrence indicator
        cmd.append('+RECURRING')
        
        # Metadata
        cmd.extend([
            f'rtemplate:{template["uuid"]}',
            f'rindex:{index}'
            # NOTE: Do NOT add recur:X here! It causes taskwarrior to set status:recurring
        ])
        
        # Execute
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            
            # Parse the new task ID from output
            new_id = None
            match = re.search(r'Created task (\d+)', result.stdout)
            if match:
                new_id = match.group(1)
            
            # Update template's rlast using ID (more reliable than UUID in different data locations)
            template_id = template.get('id')
            if template_id:
                try:
                    subprocess.run(
                        ['task', 'rc.hooks=off', str(template_id), 'modify', f'rlast:{index}'],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                except subprocess.CalledProcessError as e:
                    if DEBUG:
                        debug_log(f"Warning: Could not update rlast on template {template_id}: {e.stderr}")
            else:
                # Fallback to UUID if no ID (shouldn't happen)
                try:
                    subprocess.run(
                        ['task', 'rc.hooks=off', template['uuid'], 'modify', f'rlast:{index}'],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                except subprocess.CalledProcessError as e:
                    if DEBUG:
                        debug_log(f"Warning: Could not update rlast on template {template['uuid']}: {e.stderr}")
            
            if DEBUG:
                debug_log(f"Instance {index} created successfully with ID {new_id}")
            
            # Return feedback with task ID for easy reference
            if new_id:
                return f"Created instance #{index} of 'task {new_id}: {template['description']}'"
            else:
                return f"Created instance #{index} of '{template['description']}'"
        except subprocess.CalledProcessError as e:
            if DEBUG:
                debug_log(f"Error creating instance: {e}")
            return None
    
    def count_pending_instances(self, template_uuid):
        """Count how many pending/waiting instances exist for this template"""
        try:
            result = subprocess.run(
                ['task', 'rc.hooks=off', f'rtemplate:{template_uuid}', 
                 'status:pending or status:waiting', 'count'],
                capture_output=True,
                text=True,
                check=True
            )
            count = int(result.stdout.strip())
            if DEBUG:
                debug_log(f"Template {template_uuid[:8]} has {count} pending instances")
            return count
        except Exception as e:
            if DEBUG:
                debug_log(f"Error counting instances: {e}")
            return 0
    
    def create_instances_for_template(self, template, start_index, completion_time=None):
        """
        Create instances until we have rlimit pending instances.
        For chained: always create just one
        For periodic: keep spawning until rlimit pending instances exist
        For NEW templates (rlast=0): always create just one initially
        """
        rtype = template.get('type', 'periodic')
        rlast = str(template.get('rlast', '0')).strip()
        
        # Chained always creates one instance
        if rtype == 'chained':
            msg = self.create_instance(template, start_index, completion_time)
            return [msg] if msg else []
        
        # New template (rlast=0): create just the first instance
        if rlast in ['0', '']:
            if DEBUG:
                debug_log(f"New template: creating first instance only")
            msg = self.create_instance(template, start_index, completion_time)
            return [msg] if msg else []
        
        # Existing periodic template: count existing pending instances
        existing_pending = self.count_pending_instances(template['uuid'])
        rlimit = int(template.get('rlimit', 1))
        
        # How many more do we need to reach rlimit?
        to_create = rlimit - existing_pending
        
        if DEBUG:
            debug_log(f"Periodic spawn: existing={existing_pending}, rlimit={rlimit}, to_create={to_create}")
        
        if to_create <= 0:
            if DEBUG:
                debug_log(f"Already have {existing_pending} instances, rlimit is {rlimit}, not spawning")
            return []
        
        feedback = []
        for i in range(to_create):
            index = start_index + i
            msg = self.create_instance(template, index, completion_time)
            if msg:
                feedback.append(msg)
        
        return feedback
    
    def process_tasks(self, tasks):
        """Process tasks and spawn instances"""
        feedback = []
        
        for task in tasks:
            if DEBUG:
                debug_log(f"Processing task: uuid={task.get('uuid')}, status={task.get('status')}, "
                         f"rtemplate={task.get('rtemplate')}, rindex={task.get('rindex')}")
            
            # Completed instance? Spawns next for both types
            # Deleted instance? Only spawns for chained (user chose to skip)
            if task.get('status') == 'completed' and 'rtemplate' in task and 'rindex' in task:
                
                if DEBUG:
                    debug_log(f"Found completed instance: rindex={task['rindex']}")
                
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
                        debug_log(f"Will spawn next instance (completed)")
                    
                    completion = None
                    if 'end' in task:
                        completion = self.parse_date(task['end'])
                        if DEBUG:
                            debug_log(f"Completion time: {completion}")
                    
                    # Create instances (respects rlimit for periodic)
                    messages = self.create_instances_for_template(template, current_idx + 1, completion)
                    feedback.extend(messages)
                    if DEBUG:
                        for msg in messages:
                            debug_log(f"Result: {msg}")
                else:
                    if DEBUG:
                        debug_log(f"Skipping spawn: not the latest instance")
            
            # Deleted instance for chained recurrence? (user chose to skip this one)
            elif (task.get('status') == 'deleted' and 
                  'rtemplate' in task and 'rindex' in task):
                
                template = self.get_template(task['rtemplate'])
                if not template:
                    continue
                
                # Only spawn for chained type (periodic instances are time-based)
                if template.get('type') == 'chained':
                    if DEBUG:
                        debug_log(f"Found deleted chained instance: rindex={task['rindex']}")
                    
                    current_idx = int(task['rindex'])
                    last_idx = int(template.get('rlast', '0'))
                    
                    # Only spawn if this is the latest instance
                    if current_idx >= last_idx:
                        if DEBUG:
                            debug_log(f"Will spawn next instance (deleted/chained)")
                        
                        # Show what was deleted
                        deleted_uuid = task.get('uuid', '')[:8]
                        feedback.append(f"Deleted instance #{current_idx} of '{template.get('description')}' (uuid: {deleted_uuid})")
                        
                        # Use deletion time as completion time
                        deletion_time = None
                        if 'end' in task:
                            deletion_time = self.parse_date(task['end'])
                        
                        # Create next instance (chained only creates one)
                        messages = self.create_instances_for_template(template, current_idx + 1, deletion_time)
                        feedback.extend(messages)
                        if DEBUG:
                            for msg in messages:
                                debug_log(f"Result: {msg}")
                        
                        # Show how to stop all future instances
                        if 'id' in template:
                            feedback.append(f"To stop all future instances, delete template with: task {template['id']} delete")
                    else:
                        if DEBUG:
                            debug_log(f"Skipping spawn: not the latest instance")
                else:
                    if DEBUG:
                        debug_log(f"Skipping deleted periodic instance (time-based, not user-driven)")
            
            # New template? (handle both string and int rlast)
            elif (task.get('status') == 'recurring' and 
                  'r' in task and 
                  str(task.get('rlast', '')).strip() in ['0', '']):
                
                # Safety: only spawn if this is a recently created template
                # Check if entry time is within last 60 seconds
                entry_time = self.parse_date(task.get('entry'))
                if entry_time:
                    age_seconds = (self.now - entry_time).total_seconds()
                    if age_seconds > 60:
                        if DEBUG:
                            debug_log(f"Skipping old template (age={age_seconds}s): {task.get('description')}")
                        continue
                
                if DEBUG:
                    debug_log(f"Found new template: {task.get('description')}")
                
                # Create initial instances (respects rlimit for periodic)
                messages = self.create_instances_for_template(task, 1)
                feedback.extend(messages)
        
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
