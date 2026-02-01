#!/usr/bin/env python3
"""
Taskwarrior Enhanced Recurrence Hook - On-Exit
Version: 0.4.1
Date: 2026-01-31
Spawns new recurrence instances when needed

Installation:
    1. Save to ~/.task/hooks/on-exit_recurrence.py
    2. chmod +x ~/.task/hooks/on-exit_recurrence.py
    3. Ensure recurrence_common.py is in the same directory
"""

import sys
import os
import json
import subprocess
from datetime import datetime

# Add hooks directory to Python path so we can import recurrence_common
hooks_dir = os.path.dirname(os.path.abspath(__file__))
if hooks_dir not in sys.path:
    sys.path.insert(0, hooks_dir)

# Import shared utilities
from recurrence_common import (
    debug_log, parse_date, format_date, parse_duration, parse_relative_date,
    get_anchor_field_name, DEBUG
)

if DEBUG:
    debug_log("="*60, "EXIT")
    debug_log("on-exit hook started", "EXIT")


class RecurrenceSpawner:
    """Spawns new recurrence instances"""
    
    def __init__(self):
        self.now = datetime.utcnow()
    
    def get_template(self, uuid):
        """Fetch template task by UUID
        
        Args:
            uuid: UUID of the template task
            
        Returns:
            Task dictionary or None if not found
        """
        if DEBUG:
            debug_log(f"Attempting to fetch template: {uuid}", "EXIT")
        
        # Try method 1: Direct UUID export
        try:
            result = subprocess.run(
                ['task', 'rc.hooks=off', uuid, 'export'],
                capture_output=True,
                text=True,
                check=True
            )
            if result.stdout.strip():
                tasks = json.loads(result.stdout)
                if tasks and len(tasks) > 0:
                    if DEBUG:
                        debug_log("Template fetched successfully (method 1)", "EXIT")
                    return tasks[0]
        except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
            if DEBUG:
                debug_log(f"Method 1 failed: {e}", "EXIT")
        
        # Try method 2: Filter by UUID
        try:
            result = subprocess.run(
                ['task', 'rc.hooks=off', f'uuid:{uuid}', 'export'],
                capture_output=True,
                text=True,
                check=True
            )
            if result.stdout.strip():
                tasks = json.loads(result.stdout)
                if tasks and len(tasks) > 0:
                    if DEBUG:
                        debug_log("Template fetched successfully (method 2)", "EXIT")
                    return tasks[0]
        except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
            if DEBUG:
                debug_log(f"Method 2 failed: {e}", "EXIT")
        
        if DEBUG:
            debug_log("All template fetch methods failed", "EXIT")
        return None
    
    def check_rend(self, template, new_date):
        """Check if new_date exceeds recurrence end date (rend)
        
        Args:
            template: Template task dictionary
            new_date: New instance date to check
            
        Returns:
            True if rend date has been reached
        """
        if 'rend' not in template:
            return False
        
        rend_str = template['rend']
        anchor_field = template.get('ranchor', 'due')
        actual_field = get_anchor_field_name(anchor_field)
        anchor_date = parse_date(template.get(actual_field))
        rend_date = parse_relative_date(rend_str, anchor_date)
        
        if not rend_date:
            rend_date = parse_date(rend_str)
        
        if rend_date and new_date > rend_date:
            return True
        
        return False
    
    def create_instance(self, template, index, completion_time=None):
        """Create a new instance task
        
        Args:
            template: Template task dictionary
            index: Instance number to create
            completion_time: Completion time for chained recurrence
            
        Returns:
            Success/error message or None
        """
        if DEBUG:
            debug_log(f"Creating instance {index} from {template.get('uuid')}", "EXIT")
        
        recur_delta = parse_duration(template.get('r'))
        if not recur_delta:
            return None
        
        rtype = template.get('type', 'period')
        anchor_field = template.get('ranchor', 'due')
        
        # Build command
        cmd = ['task', 'rc.hooks=off', 'add', template['description']]
        
        # Get template anchor date
        actual_field = get_anchor_field_name(anchor_field)
        template_anchor = parse_date(template.get(actual_field))
        if not template_anchor:
            return None
        
        # Calculate anchor date based on type and index
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
        cmd.append(f'{anchor_field}:{format_date(anchor_date)}')
        
        # Copy until from template if present
        if 'until' in template:
            cmd.append(f'until:{template["until"]}')
        
        # Process wait date
        if 'rwait' in template:
            wait_date = parse_relative_date(template['rwait'], anchor_date)
            if wait_date:
                cmd.append(f'wait:{format_date(wait_date)}')
        
        # Process scheduled date
        if 'rscheduled' in template and anchor_field != 'sched':
            sched_date = parse_relative_date(template['rscheduled'], anchor_date)
            if sched_date:
                cmd.append(f'sched:{format_date(sched_date)}')
        
        # Copy attributes from template
        if 'project' in template:
            cmd.append(f'project:{template["project"]}')
        if 'priority' in template:
            cmd.append(f'priority:{template["priority"]}')
        if 'tags' in template and template['tags']:
            cmd.extend([f'+{tag}' for tag in template['tags']])
        
        # Add recurrence metadata
        cmd.extend([
            f'rtemplate:{template["uuid"]}',
            f'rindex:{int(index)}'
        ])
        
        # Execute task add command
        try:
            subprocess.run(cmd, capture_output=True, check=True)
            
            # Update template's rlast
            subprocess.run(
                ['task', 'rc.hooks=off', template['uuid'], 'modify', f'rlast:{int(index)}'],
                capture_output=True,
                check=True
            )
            
            return f"Created recurrence instance {int(index)}"
        except subprocess.CalledProcessError as e:
            if DEBUG:
                debug_log(f"Error creating instance: {e}", "EXIT")
            return f"Error creating instance {int(index)}"
    
    def process_tasks(self, tasks):
        """Process tasks from on-exit hook
        
        Args:
            tasks: List of task dictionaries
            
        Returns:
            List of feedback messages
        """
        feedback = []
        
        for task in tasks:
            # Completed/deleted instance?
            if (task.get('status') in ['completed', 'deleted'] and 
                'rtemplate' in task and 'rindex' in task):
                
                if DEBUG:
                    debug_log(f"Instance {task['status']}: rindex={task['rindex']}, "
                             f"rtemplate={task.get('rtemplate')[:8]}...", "EXIT")
                
                # Fetch the template
                template = self.get_template(task['rtemplate'])
                if not template:
                    if DEBUG:
                        debug_log(f"Template not found: {task['rtemplate']}", "EXIT")
                    continue
                
                if DEBUG:
                    debug_log(f"Template found: {template.get('description')}, "
                             f"rlast={template.get('rlast')}, type={template.get('type')}", "EXIT")
                
                current_idx = int(task['rindex'])
                last_idx = int(template.get('rlast', '0'))
                
                if DEBUG:
                    debug_log(f"Checking: current_idx={current_idx}, last_idx={last_idx}", "EXIT")
                
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
                    
                    msg = self.create_instance(template, current_idx + 1, completion)
                    if msg:
                        feedback.append(msg)
                        if DEBUG:
                            debug_log(f"Result: {msg}", "EXIT")
                else:
                    if DEBUG:
                        debug_log(f"Skipping spawn: not the latest instance", "EXIT")
            
            # Deleted instance? (just acknowledge, don't spawn)
            elif (task.get('status') == 'deleted' and 
                  'rtemplate' in task and 'rindex' in task):
                
                if DEBUG:
                    debug_log(f"Instance deleted (not spawning): rindex={task['rindex']}", "EXIT")
            
            # New template? (handle both string and int rlast)
            elif (task.get('status') == 'recurring' and 
                  'r' in task and 
                  str(task.get('rlast', '')).strip() in ['0', '']):
                
                if DEBUG:
                    debug_log(f"Found new template: {task.get('description')}", "EXIT")
                
                msg = self.create_instance(task, 1)
                if msg:
                    feedback.append(msg)
        
        return feedback


def main():
    """Main entry point for on-exit hook"""
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
    feedback = spawner.process_tasks(tasks)
    
    for msg in feedback:
        print(msg)
    
    if DEBUG:
        debug_log(f"on-exit completed with {len(feedback)} feedback messages", "EXIT")
    
    sys.exit(0)


if __name__ == '__main__':
    main()
