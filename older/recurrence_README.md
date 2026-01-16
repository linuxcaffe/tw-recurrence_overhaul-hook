# Taskwarrior Enhanced Recurrence Hook

Implementation of the [Taskwarrior Recurrence Overhaul RFC](https://djmitche.github.io/taskwarrior/rfcs/recurrence.html) using hooks.

## Features

- **Chained Recurrence** - Next task created relative to completion ("mow lawn every 7 days")
- **Periodic Recurrence** - Fixed schedule ("pay rent on 1st of month")
- **Proper Wait/Scheduled** - Relative offsets that propagate correctly
- **Clean Indexing** - Uses `rlast` instead of unbounded `mask`
- **RFC Compliant** - Template/instance model from official design

## Installation

### 1. Download Hooks

```bash
cd ~/.task/hooks

# Download the two hook files
curl -O [url-to-on-modify_recurrence.py]
curl -O [url-to-on-exit_recurrence.py]

# Make executable
chmod +x on-*_recurrence.py
```

### 2. Configure Taskwarrior

Add to `~/.taskrc`:

```ini
# Disable built-in recurrence
recurrence=no

# Enhanced recurrence UDAs
uda.rtype.type=string
uda.rtype.label=Recurrence Type
uda.rtype.values=chained,periodic

uda.r.type=duration
uda.r.label=Recurrence Period

uda.rtemplate.type=string
uda.rtemplate.label=Template UUID

uda.rlast.type=numeric
uda.rlast.label=Last Instance Index

uda.rindex.type=numeric
uda.rindex.label=Instance Index

uda.rwait.type=duration
uda.rwait.label=Template Wait

uda.rscheduled.type=duration
uda.rscheduled.label=Template Scheduled

uda.ranchor.type=string
uda.ranchor.label=Anchor Field

uda.rend.type=date
uda.rend.label=Recurrence End

# Note: rwait, rscheduled are internal storage
# Users just use wait:, scheduled:, until: normally
# rend: is for stopping recurrence creation

# Recurring templates report
report.rtemplates.description=Recurring task templates
report.rtemplates.filter=status:recurring
report.rtemplates.columns=id,description,rtype,r,ranchor,rlast,rend,tags,project
report.rtemplates.labels=ID,Description,Type,Recur,Anchor,Last,End,Tags,Project
report.rtemplates.sort=project+,description+

# Optional: enhanced recurring report
report.recurring.filter=status:recurring
report.recurring.columns=id,description,rtype,r,ranchor,rlast,rend,entry,modified
report.recurring.labels=ID,Description,Type,Recur,Anchor,Last,End,Entry,Modified
```

### 3. Verify

```bash
task diagnostics | grep -A5 Hooks
```

Should show both hooks as executable.

## Usage

### Important Changes

**User-Friendly Date Attributes:**
- Just use normal `wait:`, `scheduled:`, and `until:` attributes
- Hook automatically translates `wait:` and `scheduled:` to internal storage
- `until:` applies to **instances** (when individual tasks expire)
- Use `rend:` on templates to **stop creating new instances**
- Examples:
  - `wait:2025-01-25` (absolute)
  - `wait:due-7d` (relative to due)
  - `scheduled:due+1w` (relative to due)
  - `until:2025-12-31` (instance expires)
  - `rend:2025-12-31` (stop creating new instances)

**Default Recurrence Type:**
- If no `rtype` specified, defaults to `periodic`
- Specify `rtype:chained` only when needed

**Anchor Date:**
- By default, recurrence revolves around `due:` date
- If no `due:` specified, uses `scheduled:` date
- Must have at least one of these dates

### Chained Recurrence

Tasks recur relative to when you complete them:

```bash
# Basic chained task
task add "Mow the lawn" rtype:chained r:7d due:tomorrow

# With wait period (appears 1 day before due)
task add "Exercise" rtype:chained r:2d due:3d wait:due-1d

# With scheduled (calendar entry 2 days before)
task add "Grocery shop" rtype:chained r:1w due:saturday scheduled:due-2d
```

### Periodic Recurrence

Tasks recur on fixed schedule:

```bash
# Monthly bill (periodic is default)
task add "Pay rent" r:1mo due:2025-01-01

# Weekly meeting (explicit periodic)
task add "Team standup" rtype:periodic r:1w due:monday wait:due-1d

# Quarterly report with until date
task add "Q1 report" r:3mo due:2025-04-01 until:2025-12-31

# Using scheduled instead of due
task add "Weekly review" r:1w scheduled:friday

# Relative wait date
task add "Bill reminder" r:1mo due:2025-01-01 wait:due-7d

# Absolute wait date (converted to relative internally)
task add "Event prep" r:1mo due:2025-02-01 wait:2025-01-25
```

### Until Dates

**Instance until** - expires individual task:
```bash
# Each instance gets same until date
task add "Task" r:1w due:tomorrow until:2025-12-31
```

**Recurrence end (rend)** - stops creating new instances:
```bash
# Stop creating instances after date
task add "Summer task" r:1w due:2025-06-01 rend:2025-08-31

# Relative recurrence end
task add "Limited project" r:1w due:tomorrow rend:due+8w
```

**Difference:**
- `until:` - copied to each instance, task expires on that date
- `rend:` - stops spawning new instances after that date

### Using Scheduled Instead of Due

```bash
# Recurrence based on scheduled date
task add "Weekly planning" r:1w scheduled:monday wait:scheduled-2d

# No due date needed
task add "Daily standup" r:1d scheduled:9am
```

### Duration Syntax

| Duration | Example |
|----------|---------|
| Days | `r:7d` |
| Weeks | `r:2w` or `r:14d` |
| Months | `r:1mo` |
| Years | `r:1y` |

## How It Works

### Creating a Template

```bash
task add "Task" rtype:chained r:7d due:tomorrow
```

1. on-modify hook converts to template (status=recurring)
2. on-exit hook creates first instance

### Completing an Instance

```bash
task 123 done
```

1. on-modify marks instance complete
2. on-exit detects completion
3. Loads template
4. Creates next instance with new due date
5. Updates template's `rlast` counter

### Template vs Instance

**Template** (hidden, status=recurring):
- Stores recurrence rules
- Never completed/deleted directly
- Has `rtype`, `r`, `rlast`

**Instance** (normal task):
- Has `rtemplate` (UUID of template)
- Has `rindex` (which instance number)
- Completed/deleted normally

## Managing Recurring Tasks

### View Templates

```bash
task recurring
# or
task rtemplates
```

Shows all recurrence templates with their metadata.

### View Instances

```bash
task rtemplate:UUID list
```

### Modify Recurrence

```bash
# Change period
task UUID modify r:14d

# Change type
task UUID modify rtype:chained
```

Changes apply to future instances only.

### Delete Recurring Task

```bash
# Delete all instances
task rtemplate:UUID delete

# Delete template
task UUID delete
```

## Examples

### Weekly Exercise Chain

```bash
task add "Go to gym" \
  rtype:chained \
  r:2d \
  due:tomorrow \
  wait:due-1d \
  +health
```

### Monthly Bills with Reminder

```bash
task add "Credit card payment" \
  r:1mo \
  due:2025-01-15 \
  wait:due-7d \
  project:finance \
  priority:H
```

### Daily Medication (Scheduled-based)

```bash
task add "Take vitamins" \
  r:1d \
  scheduled:8am \
  +health
```

### Limited Time Recurring Task

```bash
# Stop creating after date (rend)
task add "Summer reading" \
  r:1w \
  due:2025-06-01 \
  rend:2025-08-31 \
  project:goals

# Instances expire (until)
task add "Temporary reminders" \
  r:1d \
  due:tomorrow \
  until:2025-12-31
```

## Troubleshooting

### Hooks Not Running

```bash
# Check status
task diagnostics | grep Hooks

# Enable debug
task rc.debug.hooks=2 add "Test" rtype:chained r:1d due:tomorrow

# Check permissions
ls -l ~/.task/hooks/on-*.py
```

### No Instance Created

- Verify template has status=recurring
- Check that `rtype` and `r` are set
- Ensure hooks have execute permission

### Wrong Due Date

- **Chained**: Due is completion_time + recurrence
- **Periodic**: Due is template.due + (index × recurrence)

## Differences from Built-in

| Feature | Built-in | Enhanced |
|---------|----------|----------|
| Types | Periodic only | Chained + Periodic |
| Mask | Grows unbounded | Clean index |
| Wait/Scheduled | Broken | Works correctly |
| Naming | parent/child | template/instance |

## Limitations

- Hooks run only where tasks are modified
- First sync after creation may be delayed
- No "until" date support (yet)
- Dependencies don't propagate (yet)

## Credits

Based on:
- [Taskwarrior Recurrence RFC](https://djmitche.github.io/taskwarrior/rfcs/recurrence.html)
- [lyz-code/taskwarrior_recurrence](https://github.com/lyz-code/taskwarrior_recurrence)
- [task.shift-recurrence](https://github.com/tbabej/task.shift-recurrence)

## License

Public domain / MIT - use freely!
