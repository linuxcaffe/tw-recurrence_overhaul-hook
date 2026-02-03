#!/usr/bin/env python3
"""
Taskwarrior Enhanced Recurrence - Common Utilities
Version: 0.4.0
Date: 2026-01-31

Shared utilities for recurrence hooks (on-add, on-modify, on-exit)
This module contains date/duration parsing, type normalization, and debug logging.

Installation:
    Place in ~/.task/hooks/ alongside the recurrence hook scripts
"""

import os
import re
from datetime import datetime, timedelta

# Constants for date calculations
DAYS_PER_MONTH = 30
DAYS_PER_YEAR = 365

# Debug configuration
DEBUG = os.environ.get('DEBUG_RECURRENCE', '0') == '1'
LOG_FILE = os.path.expanduser("~/.task/recurrence_debug.log")


def debug_log(msg, prefix="COMMON"):
    """Write debug message to log file if debug enabled
    
    Args:
        msg: Message to log
        prefix: Prefix to identify which hook is logging (ADD/MOD/EXIT/COMMON)
    """
    if DEBUG:
        with open(LOG_FILE, 'a') as f:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"[{timestamp}] {prefix}: {msg}\n")


def normalize_type(type_str):
    """Normalize recurrence type abbreviations to full names
    
    Args:
        type_str: Type string (can be abbreviated)
        
    Returns:
        'chain' or 'period'
        
    Examples:
        'c' -> 'chain'
        'ch' -> 'chain'
        'chain' -> 'chain'
        'p' -> 'period'
        'periodic' -> 'period'
    """
    if not type_str:
        return 'period'
    
    type_lower = str(type_str).lower()
    
    # Handle abbreviations for 'chain'
    if type_lower in ['c', 'ch', 'cha', 'chai', 'chain']:
        return 'chain'
    # Handle abbreviations for 'period'
    elif type_lower in ['p', 'pe', 'per', 'peri', 'perio', 'period']:
        return 'period'
    
    # Default to periodic for unknown types
    return 'period'


def parse_duration(duration_str):
    """Parse duration string (e.g., '7d', '1w', '1mo', '1y') to timedelta
    
    Supports:
        - Simple formats: 1s, 7d, 2w, 1mo, 1y
        - ISO 8601: P1Y2M3DT4H5M6S
        
    Args:
        duration_str: Duration string to parse
        
    Returns:
        timedelta object or None if parsing fails
    """
    if not duration_str:
        return None
    
    # Handle simple formats: 1s, 7d, 2w, 1mo, 1y
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
            return timedelta(days=num * DAYS_PER_MONTH)
        elif unit == 'y':
            return timedelta(days=num * DAYS_PER_YEAR)
    
    # Handle ISO 8601 duration: P1Y2M3DT4H5M6S
    pattern = r'P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?'
    match = re.match(pattern, str(duration_str))
    if match:
        years, months, weeks, days, hours, mins, secs = match.groups()
        delta = timedelta()
        
        # Add components (order doesn't matter for timedelta)
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
            delta += timedelta(days=int(months) * DAYS_PER_MONTH)
        if years:
            delta += timedelta(days=int(years) * DAYS_PER_YEAR)
        
        return delta
    
    return None


def parse_date(date_str):
    """Parse ISO 8601 date string to datetime object
    
    Handles Taskwarrior's ISO 8601 format: 20240131T120000Z
    
    Args:
        date_str: Date string to parse
        
    Returns:
        datetime object or None if parsing fails
    """
    if not date_str:
        return None
    
    try:
        # Remove timezone indicators
        clean = str(date_str).replace('Z', '').replace('+00:00', '')
        # Parse up to seconds (15 characters: YYYYMMDDTHHmmSS)
        return datetime.strptime(clean[:15], '%Y%m%dT%H%M%S')
    except (ValueError, AttributeError):
        return None


def format_date(dt):
    """Format datetime object as ISO 8601 string for Taskwarrior
    
    Args:
        dt: datetime object
        
    Returns:
        ISO 8601 formatted string: 20240131T120000Z
    """
    if not dt:
        return None
    return dt.strftime('%Y%m%dT%H%M%SZ')


def parse_relative_date(date_str, anchor_date=None):
    """Parse relative date expression like 'due-2d' or 'sched+1w'
    
    Supports expressions relative to due, sched(uled), or wait dates.
    
    Args:
        date_str: Relative date string (e.g., 'due-2d', 'sched+1w')
        anchor_date: Anchor datetime to calculate from (optional)
        
    Returns:
        For on-add (no anchor): (reference_field, timedelta) tuple or (None, None)
        For on-exit (with anchor): datetime object or None
        
    Examples:
        'due-2d' with anchor=2024-01-31 -> 2024-01-29
        'sched+1w' with anchor=2024-01-31 -> 2024-02-07
    """
    if not date_str:
        return (None, None) if anchor_date is None else None
    
    # Match patterns like: due-2d, sched+1w, wait-3days
    match = re.match(
        r'(due|sched|wait)\s*([+-])\s*(\d+)(s|seconds?|d|days?|w|weeks?|mo|months?|y|years?)',
        str(date_str).lower()
    )
    
    if not match:
        return (None, None) if anchor_date is None else None
    
    ref_field, sign, num, unit = match.groups()
    num = int(num)
    
    # Normalize unit to timedelta
    if unit.startswith('s'):
        delta = timedelta(seconds=num)
    elif unit.startswith('d'):
        delta = timedelta(days=num)
    elif unit.startswith('w'):
        delta = timedelta(weeks=num)
    elif unit.startswith('mo'):
        delta = timedelta(days=num * DAYS_PER_MONTH)
    elif unit.startswith('y'):
        delta = timedelta(days=num * DAYS_PER_YEAR)
    else:
        return (None, None) if anchor_date is None else None
    
    # Apply sign
    if sign == '-':
        delta = -delta
    
    # If no anchor provided (on-add case), return the components
    if anchor_date is None:
        return (ref_field, delta)
    
    # If anchor provided (on-exit case), calculate absolute date
    return anchor_date + delta


def is_template(task):
    """Check if a task is a recurrence template
    
    Args:
        task: Task dictionary
        
    Returns:
        True if task is a template (status:recurring)
    """
    return task.get('status') == 'recurring'


def is_instance(task):
    """Check if a task is a recurrence instance
    
    Args:
        task: Task dictionary
        
    Returns:
        True if task has an rtemplate field
    """
    return 'rtemplate' in task and task['rtemplate']


def get_anchor_field_name(anchor_field):
    """Map short anchor field name to Taskwarrior's actual field name
    
    Args:
        anchor_field: Short name ('sched' or 'due')
        
    Returns:
        Full field name ('scheduled' or 'due')
    """
    field_map = {
        'sched': 'scheduled',
        'due': 'due'
    }
    return field_map.get(anchor_field, anchor_field)


def query_instances(template_uuid):
    """Query all instances (pending OR waiting) for a specific template
    
    Args:
        template_uuid: Template UUID to query instances for
        
    Returns:
        List of instance task dictionaries
    """
    import subprocess
    import json
    
    try:
        # Query for both pending AND waiting status
        # Waiting tasks are still "active" instances, just not ready yet
        result = subprocess.run(
            ['task', 'rc.hooks=off', f'rtemplate:{template_uuid}', 
             '(status:pending or status:waiting)', 'export'],
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.returncode == 0 and result.stdout.strip():
            instances = json.loads(result.stdout)
            if DEBUG:
                debug_log(f"Queried instances for {template_uuid}: {len(instances)} found", "COMMON")
            return instances
        
        if DEBUG:
            debug_log(f"Queried instances for {template_uuid}: none found", "COMMON")
        return []
        
    except (subprocess.SubprocessError, json.JSONDecodeError) as e:
        if DEBUG:
            debug_log(f"Query instances for {template_uuid} failed: {e}", "COMMON")
        return []


def check_instance_count(template_uuid):
    """Check instance count for a specific template (targeted checking)
    
    This is the ONLY way to check instances - never check all templates globally!
    
    Args:
        template_uuid: Template UUID to check
        
    Returns:
        Tuple: (status, data)
            - ('missing', None): No instances exist
            - ('ok', instance): Exactly one instance exists
            - ('multiple', instances): Multiple instances exist (corruption)
    """
    instances = query_instances(template_uuid)
    
    if len(instances) == 0:
        if DEBUG:
            debug_log(f"Instance check for {template_uuid}: MISSING (0 found)", "COMMON")
        return ('missing', None)
    
    elif len(instances) == 1:
        if DEBUG:
            debug_log(f"Instance check for {template_uuid}: OK (1 found)", "COMMON")
        return ('ok', instances[0])
    
    else:
        if DEBUG:
            debug_log(f"Instance check for {template_uuid}: MULTIPLE ({len(instances)} found - CORRUPTION)", "COMMON")
        return ('multiple', instances)


def spawn_instance(template, rindex, completion_time=None):
    """Spawn a new instance for a template
    
    This is the ONLY way to spawn instances - can be called from on-exit (normal)
    or on-modify (re-spawn when rlast changes).
    
    Args:
        template: Template task dictionary
        rindex: Instance index to create
        completion_time: For chain types, when previous instance completed
        
    Returns:
        Success message string or None on failure
    """
    import subprocess
    from datetime import datetime
    
    if DEBUG:
        debug_log(f"Spawning instance {rindex} from template {template.get('uuid')}", "COMMON")
    
    # Parse recurrence interval
    recur_delta = parse_duration(template.get('r'))
    if not recur_delta:
        if DEBUG:
            debug_log(f"Failed to parse recurrence interval: {template.get('r')}", "COMMON")
        return None
    
    rtype = template.get('type', 'period')
    anchor_field = template.get('ranchor', 'due')
    actual_field = get_anchor_field_name(anchor_field)
    
    # Get template anchor date
    template_anchor = parse_date(template.get(actual_field))
    if not template_anchor:
        if DEBUG:
            debug_log(f"Failed to parse template anchor date: {template.get(actual_field)}", "COMMON")
        return None
    
    # Calculate anchor date for this instance
    if rindex == 1:
        # Instance 1 always uses template's anchor date
        anchor_date = template_anchor
    else:
        if rtype == 'chain':
            # Chain: completion_time + period
            base = completion_time or datetime.utcnow()
            anchor_date = base + recur_delta
        else:
            # Period: template + (rindex - 1) * period
            anchor_date = template_anchor + (recur_delta * (rindex - 1))
    
    # Check if recurrence has ended (rend)
    if 'rend' in template:
        rend_str = template['rend']
        rend_date = parse_relative_date(rend_str, template_anchor)
        if not rend_date:
            rend_date = parse_date(rend_str)
        
        if rend_date and anchor_date > rend_date:
            if DEBUG:
                debug_log(f"Recurrence ended: anchor_date {anchor_date} > rend {rend_date}", "COMMON")
            return "Recurrence ended (rend date reached)"
    
    # Build task add command
    cmd = ['task', 'rc.hooks=off', 'rc.confirmation=off', 'add', template['description']]
    
    # Add anchor date
    cmd.append(f'{anchor_field}:{format_date(anchor_date)}')
    
    # Copy until from template if present
    if 'until' in template:
        cmd.append(f'until:{template["until"]}')
    
    # Process relative wait
    if 'rwait' in template:
        wait_date = parse_relative_date(template['rwait'], anchor_date)
        if wait_date:
            cmd.append(f'wait:{format_date(wait_date)}')
    
    # Process relative scheduled
    if 'rscheduled' in template and anchor_field != 'sched':
        sched_date = parse_relative_date(template['rscheduled'], anchor_date)
        if sched_date:
            cmd.append(f'scheduled:{format_date(sched_date)}')
    
    # Copy attributes from template
    if 'project' in template:
        cmd.append(f'project:{template["project"]}')
    if 'priority' in template:
        cmd.append(f'priority:{template["priority"]}')
    if 'tags' in template and template['tags']:
        cmd.extend([f'+{tag}' for tag in template['tags']])
    if 'depends' in template:
        cmd.append(f'depends:{template["depends"]}')
    
    # Copy ALL UDAs (user-defined attributes) from template
    # Skip recurrence-specific fields and standard taskwarrior fields
    skip_fields = {
        # Standard taskwarrior fields
        'id', 'uuid', 'status', 'entry', 'modified', 'start', 'end',
        'description', 'project', 'priority', 'tags', 'depends', 'annotations',
        'due', 'scheduled', 'wait', 'until', 'recur', 'mask', 'imask', 'parent',
        # Recurrence template-only fields
        'r', 'type', 'ranchor', 'rlast', 'rend', 'rwait', 'rscheduled',
        # Recurrence instance fields (will be added separately)
        'rtemplate', 'rindex'
    }
    
    for key, value in template.items():
        if key not in skip_fields and value:
            # This is a UDA - copy it
            if isinstance(value, list):
                # Handle list UDAs (unlikely but possible)
                cmd.append(f'{key}:{",".join(str(v) for v in value)}')
            else:
                cmd.append(f'{key}:{value}')
    
    # Add recurrence metadata
    cmd.extend([
        f'rtemplate:{template["uuid"]}',
        f'rindex:{int(rindex)}'
    ])
    
    # Execute task creation
    try:
        result = subprocess.run(cmd, capture_output=True, check=True, text=True)
        
        # Copy annotations (must be done after task is created)
        if 'annotations' in template and template['annotations']:
            # Get the newly created instance UUID from output
            # We need to query for it since we don't get UUID back
            query_result = subprocess.run(
                ['task', 'rc.hooks=off', f'rtemplate:{template["uuid"]}', f'rindex:{int(rindex)}', 'export'],
                capture_output=True,
                check=True,
                text=True
            )
            
            if query_result.stdout.strip():
                import json
                instances = json.loads(query_result.stdout)
                if instances:
                    new_instance_uuid = instances[0]['uuid']
                    
                    # Copy each annotation
                    for ann in template['annotations']:
                        ann_text = ann.get('description', '')
                        if ann_text:
                            subprocess.run(
                                ['task', 'rc.hooks=off', 'rc.confirmation=off', new_instance_uuid, 'annotate', ann_text],
                                capture_output=True,
                                check=False  # Don't fail if annotation fails
                            )
                    
                    if DEBUG:
                        debug_log(f"Copied {len(template['annotations'])} annotations to instance", "COMMON")
        
        # Update template's rlast to match
        subprocess.run(
            ['task', 'rc.hooks=off', 'rc.confirmation=off', template['uuid'], 'modify', f'rlast:{int(rindex)}'],
            capture_output=True,
            check=True
        )
        
        if DEBUG:
            debug_log(f"Instance {rindex} spawned successfully", "COMMON")
        
        return f"Created instance {rindex} of '{template['description']}'"
    
    except subprocess.CalledProcessError as e:
        if DEBUG:
            debug_log(f"Failed to spawn instance {rindex}: {e}", "COMMON")
            if e.stderr:
                debug_log(f"Error output: {e.stderr}", "COMMON")
        return None


def delete_instance(instance_uuid, instance_id=None):
    """Delete an instance task
    
    Args:
        instance_uuid: Instance UUID to delete
        instance_id: Optional task ID for logging
        
    Returns:
        True if successful, False otherwise
    """
    import subprocess
    
    if DEBUG:
        debug_log(f"Deleting instance {instance_id or instance_uuid}", "COMMON")
    
    try:
        subprocess.run(
            ['task', 'rc.hooks=off', 'rc.confirmation=off', instance_uuid, 'delete'],
            capture_output=True,
            check=True
        )
        
        if DEBUG:
            debug_log(f"Instance {instance_id or instance_uuid} deleted successfully", "COMMON")
        
        return True
    
    except subprocess.CalledProcessError as e:
        if DEBUG:
            debug_log(f"Failed to delete instance {instance_id or instance_uuid}: {e}", "COMMON")
        
        return False


def should_respawn(original, modified):
    """Check if template modification requires respawn
    
    Respawn = delete old instance + create new instance (no rlast increment)
    
    Respawn-triggering fields:
    - rlast (time machine)
    - type (period ↔ chain)
    - ranchor (due ↔ sched)
    - r (recurrence interval)
    - rwait or wait (wait time)
    - rscheduled or scheduled (scheduled time)
    - due or scheduled (anchor date value)
    
    Args:
        original: Original template state
        modified: Modified template state
        
    Returns:
        Boolean: True if respawn needed
    """
    # List of fields that trigger respawn when changed
    respawn_fields = [
        'rlast',        # Time machine
        'type',         # Period ↔ chain
        'ranchor',      # Due ↔ sched
        'r',            # Recurrence interval
        'rwait',        # Relative wait
        'wait',         # Absolute wait (converted to rwait)
        'rscheduled',   # Relative scheduled
        'scheduled',    # Absolute scheduled (converted to rscheduled) OR anchor date if ranchor=sched
        'due',          # Anchor date if ranchor=due
    ]
    
    # Check each field
    for field in respawn_fields:
        if field in modified:
            old_value = original.get(field)
            new_value = modified.get(field)
            
            if old_value != new_value:
                if DEBUG:
                    debug_log(f"Respawn triggered by {field} change: {old_value} -> {new_value}", "COMMON")
                return True
    
    return False


# Version info
__version__ = '0.4.0'
__date__ = '2026-01-31'

if DEBUG:
    debug_log(f"recurrence_common v{__version__} loaded")
