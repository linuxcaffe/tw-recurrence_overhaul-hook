# Recurrence System Validation & Attribute-Agnostic Updates

**Date:** 2026-02-08  
**Version:** 2.6.3 (proposed)

## Summary

Comprehensive validation system and attribute-agnostic copying implemented to make the recurrence system more robust and flexible.

---

## 1. Attribute-Agnostic Copying

### Problem
`spawn_instance()` was hardcoded to copy only `project`, `priority`, and `tags`. This meant:
- UDAs (user-defined attributes) were lost
- Annotations were not copied
- Dependencies were not copied
- Any other custom attributes were ignored

### Solution
New attribute categorization system in `recurrence_common_hook.py`:

```python
# System fields - never copy
NEVER_COPY = {'uuid', 'id', 'entry', 'modified', 'status', 'end', 'urgency'}

# Legacy Taskwarrior recurrence - strip with warning
LEGACY_RECURRENCE = {'recur', 'mask', 'imask', 'parent', 'rtype'}

# Our template-only fields
TEMPLATE_ONLY = {'r', 'type', 'rlast', 'ranchor', 'rend', 'rwait', 'rscheduled', 'runtil'}

# Instance-only fields
INSTANCE_ONLY = {'rtemplate', 'rindex'}

# Everything else → COPY to instance
```

### Implementation
`spawn_instance()` now copies ALL attributes except those in `DO_NOT_COPY`:
- **tags**: Added with `+tag` syntax
- **annotations**: Multiple annotations supported
- **depends**: Comma-separated UUIDs
- **UDAs**: All custom fields (string, numeric)
- **Standard fields**: start, etc.

---

## 2. Comprehensive Validation System

### New Validation Functions (in common module)

#### `strip_legacy_recurrence(task)`
Removes incompatible Taskwarrior built-in recurrence fields:
- `recur` → we use `r`
- `mask`, `imask` → we don't use mask system
- `parent` → we use `rtemplate`
- `rtype` → their type, not ours

**Action:** Strip with warning message

#### `validate_recurrence_integers(task)`
Checks `rlast` and `rindex`:
- Must be integers
- Must be >= 1

**Action:** Block with error

#### `validate_template_requirements(task)`
Checks templates have:
- `r` field (period)
- Anchor date (`due` or `scheduled`)
- Valid period format (7d, 1w, 1mo, etc.)
- `rend` not in past (if present)

**Action:** Block with error

#### `validate_date_logic(task, is_template=False)`
Checks logical date relationships:
- **wait before anchor**: `wait` < `due`/`scheduled`
- **until after anchor**: `until` > `due`/`scheduled`
- **scheduled/due coexist**: Allowed (with INFO note if sched > due)

**Action:** Block with error

#### `validate_instance_integrity(task)`
Checks instance has valid template link:
- Template exists
- Template has status:recurring

**Action:** Warning with fix command

#### `validate_no_instance_fields_on_template(task)`
Prevents templates with `rtemplate` or `rindex`

**Action:** Block with error

#### `validate_no_r_on_instance(original, modified)`
Prevents adding `r` to existing instance

**Action:** Block with error

#### `validate_no_rtemplate_change(original, modified)`
Prevents changing `rtemplate` (breaks link)

**Action:** Block with error

---

## 3. Error Handling Strategy

### Blocking Errors (exit with code 1)
When validation fails:
1. Output errors to stderr
2. Return original task unchanged
3. Exit with code 1 (Taskwarrior aborts operation)

This prevents:
- Creating invalid templates
- Breaking template-instance links
- Spawning instances with illogical dates

### Warnings (allow but inform)
- Legacy recurrence fields stripped
- Orphaned instances detected
- Attribute cleanup performed

### Auto-Fix (silent)
- Type abbreviations normalized
- Instance/template attributes separated
- Relative date conversions

---

## 4. Integration Points

### on-add_recurrence.py
- `create_template()`: Full validation before template creation
- `main()`: Strip legacy fields, check for errors before output
- Added `has_errors()` and `add_error()` methods to handler

### recurrence_common_hook.py
- All validation functions
- Attribute category constants
- Attribute-agnostic `spawn_instance()`
- Enhanced `query_task()` function

---

## 5. Examples

### Error: Template without anchor
```bash
$ task add "Test" r:7d
ERROR: Recurring task must have 'due' or 'scheduled' date
       Provided: due=missing, scheduled=missing
```

### Error: wait after due
```bash
$ task add "Test" r:7d due:tomorrow wait:eom
ERROR: wait date must be before due
  wait=eom, due=tomorrow
```

### Warning: Legacy field stripped
```bash
$ task add "Test" recur:weekly due:tomorrow
WARNING: Removed legacy recurrence field 'recur'
  Enhanced recurrence uses different fields (r, type, rtemplate, etc.)
```

### Success: UDA copied to instance
```bash
$ task add "Test" r:7d due:tomorrow myuda:value
Created recurrence template. First instance will be generated on exit.

$ task 2 export | jq .myuda
"value"
```

---

## 6. Removed Features

- **+RECURRING tag**: No longer added to instances (was outdated pattern)

---

## 7. Testing Checklist

- [ ] Template creation with missing anchor
- [ ] Template with wait > due
- [ ] Template with until < due
- [ ] Template with rlast:0
- [ ] Instance with legacy recur field
- [ ] Instance with UDA → check UDA copied
- [ ] Instance with annotations → check annotations copied
- [ ] Instance with depends → check depends copied
- [ ] Modify rtemplate on instance (should fail)
- [ ] Add r to existing instance (should fail)
- [ ] Template with rindex field (should fail)

---

## 8. Version Numbers

Proposed version bump to **v2.6.3** with these changes documented in CHANGES.txt:

**Added:**
- Attribute-agnostic instance spawning (copies ALL non-system attributes)
- Comprehensive validation system with 8+ validation functions
- Support for annotations, depends, and all UDAs
- Legacy recurrence field detection and stripping

**Fixed:**
- Instances now inherit all template attributes, not just project/priority/tags
- Date logic validation prevents wait > anchor and until < anchor
- Template creation validates all requirements before proceeding

**Changed:**
- Removed +RECURRING tag (outdated pattern)
- Error handling now blocks invalid operations with exit code 1

---

## 9. Files Modified

1. **recurrence_common_hook.py** (~670 lines, was 536)
   - Added attribute categories
   - Added 8 validation functions
   - Rewrote spawn_instance() for attribute-agnostic copying
   - Added query_task() function

2. **on-add_recurrence.py** (~1130 lines, was 1042)
   - Integrated validation into create_template()
   - Added error tracking to RecurrenceHandler
   - Updated main() to abort on errors
   - Removed duplicate query_task()

---

## Notes

- Validation is thorough but not exhaustive (project names, priority values not validated - Not Our Problem)
- Focus is on recurrence-specific errors and date logic
- All validation is opt-out (runs automatically, no config needed)
- Debug logging tracks all validation decisions
