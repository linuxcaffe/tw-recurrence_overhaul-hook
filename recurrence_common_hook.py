#!/usr/bin/env python3
"""
Taskwarrior Enhanced Recurrence - Common Utilities
Version: 2.6.4
Date: 2026-02-08

Shared utilities for recurrence hooks (on-add, on-modify, on-exit)
This module contains date/duration parsing, type normalization, and debug logging.

Installation:
    Place in ~/.task/hooks/ alongside the recurrence hook scripts
"""

import sys
sys.dont_write_bytecode = True

import os
import re
from datetime import datetime, timedelta

# Constants for date calculations
DAYS_PER_MONTH = 30
DAYS_PER_YEAR = 365

# Debug configuration
DEBUG = os.environ.get('DEBUG_RECURRENCE', '0') == '1'
LOG_FILE = os.path.expanduser("~/.task/recurrence_debug.log")

# ============================================================================
# Attribute Categories for Recurrence System
# ============================================================================

# System fields that are unique per task - never copy to instances
NEVER_COPY = {
    'uuid', 'id', 'entry', 'modified', 'status', 'end', 'urgency'
}

# Legacy Taskwarrior recurrence fields - incompatible with our system
LEGACY_RECURRENCE = {
    'recur',   # We use 'r'
    'mask',    # We don't use mask system
    'imask',   # We don't use mask system
    'parent',  # We use 'rtemplate'
    'rtype'    # Legacy field - WARNING: Appears mysteriously, needs investigation
}

# Our template-only recurrence fields
TEMPLATE_ONLY = {
    'r', 'type', 'rlast', 'ranchor', 'rend',
    'rwait', 'rscheduled', 'runtil'
}

# Instance-only fields
INSTANCE_ONLY = {'rtemplate', 'rindex'}

# Fields that are calculated/transformed for instances (not copied directly)
RELATIVE_DATE_FIELDS = {'rwait', 'rscheduled', 'runtil'}

# All fields that should not be copied from template to instance
DO_NOT_COPY = NEVER_COPY | LEGACY_RECURRENCE | TEMPLATE_ONLY | INSTANCE_ONLY


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


# ============================================================================
# Validation Functions
# ============================================================================

def strip_legacy_recurrence(task, original=None):
    """Remove legacy Taskwarrior recurrence fields
    
    Taskwarrior v2.6.2 synthesizes legacy fields (notably 'rtype') into the
    JSON it passes to on-modify hooks for status:recurring tasks, even though
    these fields aren't in the stored data. We silently strip those.
    
    Only warns the user when a legacy field appears to be user-added:
    - on-add (no original): always warn
    - on-modify: warn only if field is NEW in modified (not present in original)
    
    Args:
        task: Task dictionary (modified in place)
        original: Original task state from on-modify (None for on-add)
        
    Returns:
        List of warning messages for user-added legacy fields only
    """
    warnings = []
    for field in LEGACY_RECURRENCE:
        if field in task:
            # Determine source: TW-injected (in both original and modified)
            # vs user-added (new in modified only)
            tw_injected = original is not None and field in original
            
            if DEBUG:
                source = "TW-injected (silent)" if tw_injected else "user/new"
                debug_log(f"Stripping legacy '{field}' ({source}): '{task[field]}' "
                         f"from {task.get('description', 'N/A')[:40]}", "VALIDATION")
            
            del task[field]
            
            # Only warn user about fields they added, not TW-synthesized ones
            if not tw_injected:
                warnings.append(
                    f"WARNING: Removed legacy recurrence field '{field}'\n"
                    f"  Enhanced recurrence uses different fields (r, type, rtemplate, etc.)"
                )
    return warnings


def validate_recurrence_integers(task):
    """Validate rlast/rindex are positive integers
    
    Args:
        task: Task dictionary
        
    Returns:
        List of error messages (empty if valid)
    """
    errors = []
    
    for field in ['rlast', 'rindex']:
        if field in task:
            try:
                value = int(task[field])
                if value < 1:
                    errors.append(f"ERROR: {field} must be >= 1 (got {value})")
            except (ValueError, TypeError):
                errors.append(f"ERROR: {field} must be an integer (got '{task[field]}')")
    
    return errors


def validate_template_requirements(task):
    """Validate template has required fields
    
    Args:
        task: Task dictionary
        
    Returns:
        List of error messages (empty if valid)
    """
    errors = []
    
    # Must have 'r' field
    if 'r' not in task:
        errors.append("ERROR: Recurring task must have 'r' field (recurrence period)")
        return errors  # Can't validate further without 'r'
    
    # Must have anchor date (due or scheduled)
    if 'due' not in task and 'scheduled' not in task:
        errors.append(
            "ERROR: Recurring task must have 'due' or 'scheduled' date\n"
            f"  Provided: due={task.get('due', 'missing')}, scheduled={task.get('scheduled', 'missing')}"
        )
    
    # Validate period format
    if not parse_duration(task['r']):
        errors.append(
            f"ERROR: Invalid recurrence period '{task['r']}'\n"
            f"  Valid formats: 1d, 7d, 1w, 1mo, 1y, P1D, P1W, P1M, P1Y"
        )
    
    # Check rend not in past (if present)
    if 'rend' in task:
        rend_date = parse_date(task['rend'])
        if rend_date and rend_date < datetime.utcnow():
            errors.append(
                f"ERROR: rend date is in the past: {task['rend']}\n"
                f"  This would prevent any instances from spawning"
            )
    
    return errors


def validate_date_logic(task, is_template=False):
    """Validate logical date relationships
    
    Checks:
    - wait before anchor (due/scheduled)
    - until after anchor
    - scheduled/due relationship (if both present)
    
    Args:
        task: Task dictionary
        is_template: True if validating template (uses rwait/runtil), False for instance
        
    Returns:
        List of error messages (empty if valid)
    """
    errors = []
    
    # Determine anchor field
    anchor_field = None
    anchor_date = None
    
    if 'due' in task:
        anchor_field = 'due'
        anchor_date = parse_date(task['due'])
    elif 'scheduled' in task:
        anchor_field = 'scheduled'
        anchor_date = parse_date(task['scheduled'])
    
    if not anchor_date:
        return []  # Can't validate without anchor
    
    # Check wait vs anchor
    wait_field = 'rwait' if is_template else 'wait'
    if wait_field in task:
        wait_date = None
        
        if is_template:
            # rwait is relative, need to calculate absolute
            wait_date = parse_relative_date(task[wait_field], anchor_date)
        else:
            # wait is absolute
            wait_date = parse_date(task[wait_field])
        
        if wait_date and wait_date > anchor_date:
            errors.append(
                f"ERROR: {wait_field} date must be before {anchor_field}\n"
                f"  {wait_field}={task[wait_field]}, {anchor_field}={task[anchor_field]}"
            )
    
    # Check until vs anchor
    until_field = 'runtil' if is_template else 'until'
    if until_field in task:
        until_date = None
        
        if is_template:
            # runtil is relative
            until_date = parse_relative_date(task[until_field], anchor_date)
        else:
            # until is absolute
            until_date = parse_date(task[until_field])
        
        if until_date and until_date < anchor_date:
            errors.append(
                f"ERROR: {until_field} date must be after {anchor_field}\n"
                f"  {until_field}={task[until_field]}, {anchor_field}={task[anchor_field]}"
            )
    
    # Check scheduled after due (INFO message, not error)
    if 'scheduled' in task and 'due' in task:
        sched_date = parse_date(task['scheduled'])
        due_date = parse_date(task['due'])
        
        if sched_date and due_date and sched_date > due_date:
            # This is allowed but worth noting
            if DEBUG:
                debug_log(f"INFO: scheduled after due (allowed): sched={task['scheduled']}, due={task['due']}", "VALIDATION")
    
    return errors


def validate_instance_integrity(task):
    """Validate instance has proper template link
    
    Args:
        task: Task dictionary (instance)
        
    Returns:
        List of warning messages (empty if valid)
    """
    warnings = []
    
    if 'rtemplate' not in task:
        return []  # Not an instance
    
    # Check if template exists
    template_uuid = task['rtemplate']
    template = query_task(template_uuid)
    
    if not template:
        warnings.append(
            f"WARNING: Instance references non-existent template {template_uuid}\n"
            f"  Template may have been deleted. To fix:\n"
            f"  - Delete orphaned instance: task {task.get('uuid', 'UUID')} delete\n"
            f"  - Or remove link: task {task.get('uuid', 'UUID')} modify rtemplate:"
        )
    elif template.get('status') not in ['recurring']:
        warnings.append(
            f"WARNING: Instance references template with status={template.get('status')}\n"
            f"  Template should have status:recurring"
        )
    
    return warnings


def validate_no_instance_fields_on_template(task):
    """Check template doesn't have instance-only fields
    
    Args:
        task: Task dictionary
        
    Returns:
        List of error messages (empty if valid)
    """
    errors = []
    
    for field in INSTANCE_ONLY:
        if field in task:
            errors.append(
                f"ERROR: Cannot create template with '{field}' field\n"
                f"  Templates should not have instance-only attributes"
            )
    
    return errors


def validate_no_r_on_instance(original, modified):
    """Check if trying to add 'r' to existing instance
    
    Args:
        original: Original task state
        modified: Modified task state
        
    Returns:
        Error message if invalid, None if valid
    """
    if 'rtemplate' in original and 'r' in modified and 'r' not in original:
        return (
            "ERROR: Cannot add 'r' field to instance\n"
            "  This instance is already linked to a template\n"
            f"  Template: {original.get('rtemplate')}"
        )
    return None


def validate_no_rtemplate_change(original, modified):
    """Check if trying to change rtemplate
    
    Args:
        original: Original task state
        modified: Modified task state
        
    Returns:
        Error message if invalid, None if valid
    """
    if 'rtemplate' in modified and 'rtemplate' in original:
        if modified['rtemplate'] != original['rtemplate']:
            return (
                "ERROR: Cannot modify rtemplate field\n"
                "  This would break the template-instance relationship\n"
                f"  Original: {original['rtemplate']}\n"
                f"  Attempted: {modified['rtemplate']}"
            )
    return None


def validate_no_absolute_dates_on_template(task):
    """Check template doesn't have absolute wait/scheduled/until (should be rwait/rscheduled/runtil)
    
    Args:
        task: Task dictionary (template)
        
    Returns:
        List of error messages (empty if valid)
    """
    errors = []
    
    # Check if this is actually a template
    if task.get('status') != 'recurring' and 'r' not in task:
        return []
    
    # Check for absolute wait
    if 'wait' in task:
        # Check if it's relative (due-2d) or absolute (20260315T120000Z)
        ref_field, offset = parse_relative_date(task['wait'])
        if not (ref_field and offset):
            # It's absolute
            errors.append(
                f"ERROR: Template has absolute 'wait' field (should be 'rwait')\n"
                f"  Use: rwait:due-2d (relative) instead of wait:2026-03-15 (absolute)"
            )
    
    # Check for absolute scheduled (but only if it's not the anchor)
    if 'scheduled' in task:
        anchor = task.get('ranchor', 'due')
        if anchor != 'sched':
            ref_field, offset = parse_relative_date(task['scheduled'])
            if not (ref_field and offset):
                errors.append(
                    f"ERROR: Template has absolute 'scheduled' field (should be 'rscheduled')\n"
                    f"  Use: rscheduled:due-2d (relative) instead of scheduled:2026-03-15 (absolute)"
                )
    
    # Check for absolute until
    if 'until' in task:
        ref_field, offset = parse_relative_date(task['until'])
        if not (ref_field and offset):
            errors.append(
                f"ERROR: Template has absolute 'until' field (should be 'runtil')\n"
                f"  Use: runtil:due+7d (relative) instead of until:2026-03-15 (absolute)"
            )
    
    return errors


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
    
    # Match patterns like: due-2d, sched+1w, wait-30m, wait-3days, sched+4hr
    match = re.match(
        r'(due|sched|wait)\s*([+-])\s*(\d+)(s|seconds?|min|minutes?|m|h|hours?|d|days?|w|weeks?|mo|months?|y|years?)',
        str(date_str).lower()
    )
    
    if not match:
        return (None, None) if anchor_date is None else None
    
    ref_field, sign, num, unit = match.groups()
    num = int(num)
    
    # Normalize unit to timedelta
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
        # Query without status filter first, then filter manually
        # This avoids potential parentheses parsing issues
        result = subprocess.run(
            ['task', 'rc.hooks=off', f'rtemplate:{template_uuid}', 'export'],
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.returncode == 0 and result.stdout.strip():
            all_instances = json.loads(result.stdout)
            # Filter to pending/waiting only
            instances = [i for i in all_instances if i.get('status') in ['pending', 'waiting']]
            if DEBUG:
                debug_log(f"Queried instances for {template_uuid}: {len(instances)} found (from {len(all_instances)} total)", "COMMON")
            return instances
        
        if DEBUG:
            debug_log(f"Queried instances for {template_uuid}: none found", "COMMON")
        return []
        
    except (subprocess.SubprocessError, json.JSONDecodeError) as e:
        if DEBUG:
            debug_log(f"Query instances for {template_uuid} failed: {e}", "COMMON")
        return []


def query_task(uuid):
    """Query Taskwarrior for a task by UUID
    
    Args:
        uuid: Task UUID to query
        
    Returns:
        Task dictionary or None if not found/error
    """
    import subprocess
    import json
    
    try:
        result = subprocess.run(
            ['task', 'rc.hooks=off', uuid, 'export'],
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.returncode == 0 and result.stdout.strip():
            tasks = json.loads(result.stdout)
            if tasks:
                if DEBUG:
                    debug_log(f"Queried task {uuid}: found", "COMMON")
                return tasks[0]
        
        if DEBUG:
            debug_log(f"Queried task {uuid}: not found", "COMMON")
        return None
        
    except (subprocess.SubprocessError, json.JSONDecodeError) as e:
        if DEBUG:
            debug_log(f"Query task {uuid} failed: {e}", "COMMON")
        return None


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
    
    # Validate rindex
    try:
        rindex = int(rindex)
        if rindex < 1:
            if DEBUG:
                debug_log(f"Invalid rindex: {rindex} (must be >= 1)", "COMMON")
            return None
    except (ValueError, TypeError):
        if DEBUG:
            debug_log(f"Invalid rindex type: {rindex}", "COMMON")
        return None
    
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
            
            # Validate: For PERIODIC only, rindex > 1 means instance anchor MUST be after template anchor
            # (Chain can be earlier if completed early)
            if anchor_date <= template_anchor:
                if DEBUG:
                    debug_log(f"ERROR: Periodic rindex={rindex} but calculated anchor ({anchor_date}) not after template anchor ({template_anchor})", "COMMON")
                return None
    
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
    # rc.verbose=new-id: Only output task ID line, suppress warnings and context messages
    cmd = ['task', 'rc.hooks=off', 'rc.confirmation=off', 'rc.verbose=new-id', 'add', template['description']]
    
    # Add anchor date
    cmd.append(f'{actual_field}:{format_date(anchor_date)}')
    
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
    
    # Process relative until
    if 'runtil' in template:
        if DEBUG:
            debug_log(f"Template has runtil: {template['runtil']}", "COMMON")
        until_date = parse_relative_date(template['runtil'], anchor_date)
        if until_date:
            cmd.append(f'until:{format_date(until_date)}')
            if DEBUG:
                debug_log(f"Added until: {format_date(until_date)}", "COMMON")
        else:
            if DEBUG:
                debug_log(f"Failed to parse runtil: {template['runtil']}", "COMMON")
    
    # Copy ALL other attributes from template (attribute-agnostic)
    # Skip fields in DO_NOT_COPY and fields already handled above
    already_handled = {actual_field, 'description', 'uuid', 'status'}
    
    for field, value in template.items():
        # Skip if already handled or in do-not-copy list
        if field in already_handled or field in DO_NOT_COPY:
            continue
        
        # Handle different field types
        if field == 'tags' and isinstance(value, list):
            # Tags are added with + prefix
            cmd.extend([f'+{tag}' for tag in value])
            if DEBUG:
                debug_log(f"Copied tags: {value}", "COMMON")
        
        elif field == 'annotations' and isinstance(value, list):
            # Annotations cannot be added via 'task add' - they need separate 'task annotate' commands
            # Store them for post-creation handling
            if DEBUG:
                debug_log(f"Skipping {len(value)} annotation(s) - will add after task creation", "COMMON")
            # Note: We'll need to handle this separately after task is created
        
        elif field == 'depends' and value:
            # Dependencies: comma-separated UUIDs
            if isinstance(value, list):
                cmd.append(f'depends:{",".join(value)}')
            else:
                cmd.append(f'depends:{value}')
            if DEBUG:
                debug_log(f"Copied depends: {value}", "COMMON")
        
        elif isinstance(value, str):
            # Simple string fields (project, priority, UDAs, etc.)
            cmd.append(f'{field}:{value}')
            if DEBUG:
                debug_log(f"Copied {field}: {value}", "COMMON")
        
        elif isinstance(value, (int, float)):
            # Numeric UDAs
            cmd.append(f'{field}:{value}')
            if DEBUG:
                debug_log(f"Copied {field}: {value}", "COMMON")
        
        else:
            # Skip complex types we don't know how to handle
            if DEBUG:
                debug_log(f"Skipped field {field} (type: {type(value).__name__})", "COMMON")
    
    # Add recurrence metadata
    cmd.extend([
        f'rtemplate:{template["uuid"]}',
        f'rindex:{int(rindex)}'
    ])
    
    # Execute task creation
    try:
        result = subprocess.run(cmd, capture_output=True, check=True, text=True)
        
        # Extract task ID from output (Taskwarrior prints "Created task N.")
        task_id = None
        for line in result.stdout.split('\n'):
            if 'Created task' in line:
                import re
                match = re.search(r'Created task (\d+)', line)
                if match:
                    task_id = match.group(1)
                    break
        
        # Add annotations if template has them (must be done after task creation)
        if task_id and 'annotations' in template and isinstance(template['annotations'], list):
            for annotation in template['annotations']:
                if isinstance(annotation, dict) and 'description' in annotation:
                    try:
                        subprocess.run(
                            ['task', 'rc.hooks=off', 'rc.confirmation=off', 'rc.verbose=nothing',
                             task_id, 'annotate', annotation['description']],
                            capture_output=True,
                            check=True
                        )
                        if DEBUG:
                            debug_log(f"Added annotation to instance: {annotation['description']}", "COMMON")
                    except subprocess.CalledProcessError as e:
                        if DEBUG:
                            debug_log(f"Failed to add annotation: {e}", "COMMON")
        
        # Update template's rlast to match
        subprocess.run(
            ['task', 'rc.hooks=off', 'rc.confirmation=off', 'rc.verbose=nothing', template['uuid'], 'modify', f'rlast:{int(rindex)}'],
            capture_output=True,
            check=True
        )
        
        if DEBUG:
            debug_log(f"Instance {rindex} spawned successfully (task {task_id})", "COMMON")
        
        # Build message with task ID if available
        task_desc = template.get('description', 'untitled')
        if task_id:
            return f"Created task {task_id} - '{task_desc}' (recurrence instance #{rindex})"
        else:
            return f"Created instance #{rindex} - '{task_desc}'"
    
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


# Version info
__version__ = '0.5.2'
__date__ = '2026-02-11'

if DEBUG:
    debug_log(f"recurrence_common v{__version__} loaded")
