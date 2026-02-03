## Transparent Wait/Scheduled Conversion on Templates

### Feature: Natural Modification Syntax

Users can now modify `wait:` and `scheduled:` on templates using natural syntax, and the hook automatically converts them to `rwait:` and `rscheduled:` behind the scenes.

---

## User Experience

### Before (Technical):
```bash
# User had to know about rwait/rscheduled
task 72 mod rwait:due-1d      # Technical, not intuitive
task 72 mod rscheduled:due-2d # What's the 'r' prefix?
```

### After (Natural):
```bash
# User just uses normal wait/scheduled
task 72 mod wait:due-1d       # Natural! ✅
task 72 mod sched:due-2d      # Natural! ✅
```

**The hook silently converts:**
- `wait:` → `rwait:`
- `scheduled:` → `rscheduled:`

---

## How It Works

### Relative Expressions (Preferred)
```bash
task 72 mod wait:due-2d
  ↓
Hook detects: "due-2d" is relative
Hook stores: rwait:due-2d
Hook messages: "Modified wait time. This will apply to all future instances."
```

### Absolute Dates (Converted)
```bash
task 72 mod wait:2026-03-15
  ↓
Hook detects: Absolute date
Hook calculates: Offset from anchor (e.g., due-7d = -604800s)
Hook stores: rwait:due-604800s
Hook messages: "Modified wait time. This will apply to all future instances."
```

---

## Examples

### Example 1: Change Wait Time
```bash
# Template with wait
task add "Review PR" due:friday r:1w rwait:due-2d

# Later, user wants to change wait
task 72 mod wait:due-1d
```

**Output:**
```
Modified task 72 -- Review PR (recurrence template)
Modified wait time.
  This will apply to all future instances.
```

**Behind the scenes:**
- `wait:due-1d` deleted
- `rwait:due-1d` added
- User never sees "rwait"

### Example 2: Change Scheduled Time
```bash
# Template with scheduled
task add "Standup" due:9am r:1d rscheduled:due-1h

# Change scheduled time
task 72 mod scheduled:due-30min
```

**Output:**
```
Modified task 72 -- Standup (recurrence template)
Modified scheduled time.
  This will apply to all future instances.
```

### Example 3: Absolute Date Conversion
```bash
# Template
task add "Bill" due:2026-03-01 r:1mo

# Add wait with absolute date
task 72 mod wait:2026-02-22
```

**Output:**
```
Modified task 72 -- Bill (recurrence template)
Modified wait time.
  This will apply to all future instances.
```

**Behind the scenes:**
- Hook calculates: 2026-02-22 is 7 days before 2026-03-01
- Stores: `rwait:due-604800s` (7 days in seconds)

---

## Technical Details

### What Gets Converted

**wait: → rwait:**
- Relative expressions: `wait:due-2d` → `rwait:due-2d`
- Absolute dates: `wait:2026-03-15` → `rwait:due±Xs` (calculated offset)
- Keywords: `wait:tomorrow` → parsed and converted

**scheduled: → rscheduled:**
- Same logic as wait
- Only converted if anchor is NOT scheduled (if anchor is sched, scheduled IS the anchor)

### When Conversion Happens

1. **Template creation** (`create_template`)
   - `wait:` and `scheduled:` converted on initial add

2. **Template modification** (`handle_template_modification`)
   - `wait:` and `scheduled:` converted when modified

### Functions Updated

```python
convert_wait_to_relative(task, anchor_field, anchor_date):
    # Now messages: "Modified wait time. This will apply to all future instances."
    # (No mention of rwait)
    
convert_scheduled_to_relative(task, anchor_field, anchor_date):
    # Now messages: "Modified scheduled time. This will apply to all future instances."
    # (No mention of rscheduled)
```

### Both Functions Now:
1. Detect if value is relative expression or absolute
2. Convert appropriately
3. Delete original field (wait/scheduled)
4. Add relative field (rwait/rscheduled)
5. Message user in natural language (no "rwait"/"rscheduled" mentioned)

---

## Edge Cases Handled

### Case 1: Anchor is Scheduled
```bash
task add "Task" scheduled:friday r:1w
task 72 mod scheduled:saturday
```
- `scheduled` is the anchor itself, not relative
- NOT converted to rscheduled
- Acts as anchor date modification

### Case 2: Already Relative
```bash
task 72 mod wait:due-2d
```
- Already relative format
- Stored as `rwait:due-2d` directly
- No calculation needed

### Case 3: Complex Relative Expressions
```bash
task 72 mod wait:due-2days
task 72 mod wait:due+1w
```
- All parsed correctly by `parse_relative_date()`
- Stored as-is in rwait/rscheduled

---

## User Benefits

✅ **Intuitive** - Use natural `wait:` and `scheduled:`
✅ **Transparent** - No need to know about rwait/rscheduled
✅ **Consistent** - Same syntax for templates and instances
✅ **Forgiving** - Handles both relative and absolute
✅ **Educational** - Message explains "applies to future instances"

---

## Implementation

### Files Changed

**on-add_recurrence.py:**
- Updated `convert_wait_to_relative()` messaging
- Updated `convert_scheduled_to_relative()` messaging
- Added scheduled conversion to `handle_template_modification()`

### Lines Added/Modified
- ~60 lines enhanced
- No new functions
- Improved UX messaging

---

## Testing

```bash
# Test 1: Relative wait
task add "Test" due:friday r:1w
task 1 mod wait:due-2d
task 1 export | jq '.[] | {rwait}'
# Should show: rwait:"due-2d"

# Test 2: Absolute wait
task add "Test2" due:2026-03-01 r:1mo
task 2 mod wait:2026-02-25
task 2 export | jq '.[] | {rwait}'
# Should show: rwait:"due-518400s" (6 days)

# Test 3: Scheduled
task add "Test3" due:friday r:1w
task 3 mod scheduled:due-1d
task 3 export | jq '.[] | {rscheduled}'
# Should show: rscheduled:"due-1d"

# Test 4: Verify user doesn't see rwait
task 1 mod wait:due-3d
# Output should NOT mention "rwait"
```

---

## Summary

Users can now modify templates using natural `wait:` and `scheduled:` syntax. The hook silently handles the conversion to `rwait:`/`rscheduled:`, making the recurrence system more intuitive and user-friendly.

**The hood stays closed!** 🎉
