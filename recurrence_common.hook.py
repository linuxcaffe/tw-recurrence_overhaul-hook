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


# Version info
__version__ = '0.4.0'
__date__ = '2026-01-31'

if DEBUG:
    debug_log(f"recurrence_common v{__version__} loaded")
