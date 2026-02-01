# Enhanced Recurrence Hook - Modification Features
Version: 0.4.0
Date: 2026-02-01

## Overview

The enhanced on-add/on-modify recurrence hook now provides sophisticated handling of template and instance modifications with comprehensive user feedback following the awesome-taskwarrior messaging standard.

## Key Features

### 1. Template Modifications

#### Type Changes (period ↔ chain)
- **Allowed**: Yes, with clear explanation
- **Behavior**: Type is normalized and changed, rlast preserved
- **Message Format**:
  ```
  Modified template type: period → chain
  This changes how future instances spawn (on completion).
  Current rlast=6 preserved.
  ```

#### Anchor Changes (due ↔ sched)
- **Allowed**: Yes, with automatic recalculation
- **Behavior**: 
  - `ranchor` updated to new anchor field
  - All relative dates (`rwait`, `rscheduled`) automatically updated
  - Example: `rwait:due-2d` → `rwait:sched-2d`
- **Message Format**:
  ```
  Modified template anchor: due → sched
  Relative dates (rwait, rscheduled) updated to use new anchor.
  ```

#### Time Machine (rlast modifications)
- **Allowed**: Yes, enables skipping forward/backward in sequence
- **Behavior**:
  - Modify template `rlast` to jump to different point in sequence
  - For **period types**: Next instance calculated as `anchor + (r × (rlast + 1))`
  - For **chain types**: Next instance spawns on completion of current
- **Use Case**: Catch up when you've missed several instances
- **Message Format** (period):
  ```
  Template rlast modified: 6 → 9 (3 instances forward)
  Next instance will be #10 due 20260315T120000Z
  ```
- **Message Format** (chain):
  ```
  Template rlast modified: 6 → 9
  Next instance will be #10 (spawns on completion).
  ```

#### Wait Field Modifications
- **Allowed**: Yes, with automatic conversion
- **Behavior**:
  - Absolute `wait` dates automatically converted to relative `rwait`
  - Relative expressions preserved as-is
  - Calculation: `rwait = anchor_field ± offset_in_seconds`
- **Message Format**:
  ```
  Converted absolute wait to relative: rwait=due-172800s
  This will apply to all future instances.
  ```

#### Attribute Propagation to Current Instance
- **Tracked Attributes**: project, priority, tags, due, scheduled
- **Behavior**: When template attributes change, suggests command to apply to current pending instance
- **Message Format**:
  ```
  Modified task 42 -- gym routine (recurrence template)
  This will affect future instances. To apply to current instance #7:
  task 43 mod project:fitness priority:H
  ```

### 2. Instance Modifications

#### Index Synchronization (rindex ↔ rlast)
- **Allowed**: Yes, with automatic template sync
- **Behavior**: 
  - Modifying instance `rindex` automatically updates template `rlast`
  - Prevents template/instance desynchronization
  - Critical for system integrity
- **Message Format**:
  ```
  Modified instance rindex: 6 → 9
  Template rlast synced to 9.
  ```

#### Attribute Propagation to Future Instances
- **Tracked Attributes**: project, priority, tags
- **Behavior**: When instance attributes change, suggests command to apply to template (affecting future instances)
- **Message Format**:
  ```
  Modified task 43 -- gym routine (instance #7)
  To apply this change to all future instances:
  task 42 mod project:fitness priority:H
  ```

## Messaging Standard

All feedback follows this consistent format:

```
<action> task <ID> -- <description> [<context>]
<impact_explanation>
<suggestion_with_exact_command>
```

### Benefits
1. **Clarity**: User knows exactly what happened
2. **Education**: Explains template vs instance distinction
3. **Actionability**: Provides copy-paste commands
4. **Flexibility**: Doesn't prevent actions, just informs

## Architecture

### Module Structure
```
recurrence_common_hook.py     # Shared utilities (v0.4.0)
├── normalize_type()
├── parse_duration()
├── parse_date()
├── format_date()
├── parse_relative_date()
├── is_template()
├── is_instance()
├── get_anchor_field_name()
└── debug_log()

on-add_recurrence.py           # Hook implementation (v0.4.0)
├── RecurrenceHandler
│   ├── create_template()
│   ├── handle_anchor_change()
│   ├── handle_wait_modification()
│   ├── handle_rlast_modification()
│   ├── handle_template_modification()
│   └── handle_instance_modification()
└── main()
```

### Symlink Setup
```bash
cd ~/.task/hooks
ln -s on-add_recurrence.py on-modify_recurrence.py
```

## Test Scenarios

### Scenario 1: Template Type Change
```bash
# Create period recurrence
task add "Weekly meeting" due:friday r:1w type:period

# Change to chain
task 1 mod type:chain

# Expected output:
# Modified template type: period → chain
# This changes how future instances spawn (on completion).
# Current rlast=0 preserved.
```

### Scenario 2: Time Machine (Period Type)
```bash
# Create template
task add "Gym" due:2026-02-03 r:7d type:period

# User missed 3 weeks, wants to catch up
task 1 mod rlast:3

# Expected output:
# Template rlast modified: 0 → 3 (3 instances forward)
# Next instance will be #4 due 20260224T000000Z
```

### Scenario 3: Anchor Change
```bash
# Create with due date
task add "Review code" due:friday r:1w

# Change to scheduled
task 1 mod due: scheduled:friday

# Expected output:
# Modified template anchor: due → sched
# Relative dates (rwait, rscheduled) updated to use new anchor.
```

### Scenario 4: Instance Index Change
```bash
# Complete instance #2
task 3 done

# Manually adjust instance index
task 4 mod rindex:5

# Expected output:
# Modified instance rindex: 3 → 5
# Template rlast synced to 5.
```

### Scenario 5: Wait Field Conversion
```bash
# Create template with absolute wait
task add "Backup" due:2026-02-10 r:7d wait:2026-02-08

# Expected output during template creation:
# (wait automatically converted to rwait:due-172800s)

# Later modify wait
task 1 mod wait:2026-02-09

# Expected output:
# Converted absolute wait to relative: rwait=due-86400s
# This will apply to all future instances.
```

### Scenario 6: Template Attribute Change
```bash
# Create template
task add "Weekly review" due:friday r:1w project:work

# Change project
task 1 mod project:planning

# Expected output:
# Modified task 1 -- Weekly review (recurrence template)
# This will affect future instances. To apply to current instance #2:
# task 2 mod project:planning
```

### Scenario 7: Instance Attribute Change
```bash
# Modify current instance
task 2 mod priority:H

# Expected output:
# Modified task 2 -- Weekly review (instance #2)
# To apply this change to all future instances:
# task 1 mod priority:H
```

## Edge Cases Handled

1. **Out-of-sync rindex/rlast**: Automatically synced on modification
2. **Template deletion/completion**: `r` field removed to allow purging
3. **Anchor change with relative dates**: All relative expressions updated
4. **Type normalization**: Abbreviations (c, ch, p, per) handled consistently
5. **Missing instances**: Graceful handling when no pending instance exists
6. **JSON decode errors**: Clear error messages to stderr

## Debug Mode

Enable comprehensive logging:
```bash
export DEBUG_RECURRENCE=1
task <command>
tail -f ~/.task/recurrence_debug.log
```

Debug output includes:
- Hook entry/exit
- Mode detection (ADD vs MODIFY)
- Template/instance detection
- Attribute changes
- Sync operations
- Feedback generation

## Integration with awesome-taskwarrior

This messaging standard should be adopted across all awesome-taskwarrior hooks and extensions:

1. **Consistent format** across all tools
2. **Actionable suggestions** with exact commands
3. **Educational feedback** explaining implications
4. **Copy-paste friendly** for user efficiency

## Future Enhancements

Potential areas for expansion:
1. Batch modifications (multiple instances at once)
2. Conditional propagation (ask before syncing)
3. Undo/rollback for time machine operations
4. Smart tag handling (add/remove vs replace)
5. Validation rules (configurable limits on rlast jumps)

## Version History

- **0.4.0** (2026-02-01): Complete rewrite with common module, smart modifications
- **0.3.7** (2026-01-17): Basic template/instance handling
- **0.3.6** (2026-01-17): Initial on-modify support
