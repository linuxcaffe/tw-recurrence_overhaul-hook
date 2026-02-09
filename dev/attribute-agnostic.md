# Recurrence System: Validation & Attribute-Agnostic Update

**Date:** 2026-02-08  
**Proposed Version:** 2.6.3

## Executive Summary

Two major improvements implemented:
1. **Attribute-agnostic instance spawning** - ALL template attributes now copy to instances
2. **Comprehensive validation system** - 9 validation functions preventing common errors
3. **Enhanced alias system** - Full conversion of absolute dates to relative offsets

---

## 1. Attribute-Agnostic Copying

### Problem
`spawn_instance()` hardcoded to copy only `project`, `priority`, `tags`

### Solution
New categorization system:
```python
NEVER_COPY = {'uuid', 'id', 'entry', 'modified', 'status', 'end', 'urgency'}
LEGACY_RECURRENCE = {'recur', 'mask', 'imask', 'parent', 'rtype'}
TEMPLATE_ONLY = {'r', 'type', 'rlast', 'ranchor', 'rend', 'rwait', 'rscheduled', 'runtil'}
INSTANCE_ONLY = {'rtemplate', 'rindex'}
# Everything else → COPY
```

### Now Copies
- **All UDAs** (custom user-defined attributes)
- **Annotations** (multiple supported)
- **Dependencies** (depends field)
- **Standard fields** (start, etc.)
- **Numeric UDAs**

---

## 2. Comprehensive Validation System

### New Validation Functions

#### 1. `strip_legacy_recurrence(task)`
Removes incompatible built-in recurrence fields:
- `recur`, `mask`, `imask`, `parent`, `rtype`
- **Action:** Strip with WARNING

#### 2. `validate_recurrence_integers(task)`
- `rlast`, `rindex` must be integers >= 1
- **Action:** ERROR (block)

#### 3. `validate_template_requirements(task)`
- Must have `r` field
- Must have anchor (`due` or `scheduled`)
- Valid period format
- `rend` not in past
- **Action:** ERROR (block)

#### 4. `validate_date_logic(task, is_template=False)`
- `wait` < anchor
- `until` > anchor
- **Action:** ERROR (block)

#### 5. `validate_no_absolute_dates_on_template(task)`
NEW! Templates cannot have absolute `wait`, `scheduled`, `until`
- Must use relative versions (`rwait`, `rscheduled`, `runtil`)
- **Action:** ERROR (block)

#### 6. `validate_instance_integrity(task)`
- Instance has valid template link
- Template exists and has status:recurring
- **Action:** WARNING (with fix command)

#### 7. `validate_no_instance_fields_on_template(task)`
- Template cannot have `rtemplate` or `rindex`
- **Action:** ERROR (block)

#### 8. `validate_no_r_on_instance(original, modified)`
- Cannot add `r` to existing instance
- **Action:** ERROR (block)

#### 9. `validate_no_rtemplate_change(original, modified)`
- Cannot modify `rtemplate` (breaks link)
- **Action:** ERROR (block)

---

## 3. Enhanced Alias System

### New Aliases Added
```bash
last      → rlast       # task 5 mod last:10
index     → rindex      # task 6 mod index:3
anchor    → ranchor     # task 5 mod anchor:sched
```

### Absolute Date Conversion
**NEW BEHAVIOR:** Absolute dates automatically convert to relative offsets

#### Example 1: Template has absolute wait
```bash
$ task 5 mod wait:2026-03-15
# Hook converts to: rwait:due+604800s
```

#### Example 2: Both absolute AND relative present
```bash
$ task 5 mod wait:2026-03-15 rwait:due-2d
ERROR: Template has both 'wait' and 'rwait' - use only rwait
```

#### Example 3: rwait exists, then set absolute wait
```bash
# Template has rwait:due-2d
$ task 5 mod wait:2026-03-15
# Hook removes absolute wait, keeps rwait
```

### Conversion Logic
```
User sets:           Hook converts to:
wait:2026-03-15   →  rwait:due+Xs
sched:2026-03-15  →  rscheduled:due+Xs
until:2026-03-15  →  runtil:due+Xs

Where X = (target_date - anchor_date) in seconds
```

---

## 4. Error Handling

### Blocking Errors (exit code 1)
When validation fails:
1. Output errors to stderr
2. Return ORIGINAL task unchanged
3. Exit with code 1 (Taskwarrior aborts)

### Examples

```bash
# ERROR: Missing anchor
$ task add "Test" r:7d
ERROR: Recurring task must have 'due' or 'scheduled' date

# ERROR: wait after due
$ task add "Test" r:7d due:tomorrow wait:eom
ERROR: wait date must be before due

# ERROR: Absolute date on template
$ task 5 mod wait:2026-03-15
# If rwait doesn't exist, converts automatically
# If rwait EXISTS, ERROR

# WARNING: Legacy field
$ task add "Test" recur:weekly due:tomorrow
WARNING: Removed legacy recurrence field 'recur'
```

---

## 5. Integration Points

### recurrence_common_hook.py
- All 9 validation functions
- Attribute categories
- Attribute-agnostic `spawn_instance()`
- ~720 lines (was 536)

### on-add_recurrence.py  
- Enhanced `expand_template_aliases()` (handles absolute dates)
- Validation in `create_template()`
- Validation in `handle_template_modification()`
- Error tracking with `has_errors()`
- ~1213 lines (was 1042)

---

## 6. Complete Alias List

| User Types | Hook Stores | Context |
|------------|-------------|---------|
| `ty:c` | `type:chain` | Any |
| `ty:p` | `type:period` | Any |
| `last:5` | `rlast:5` | Template mod |
| `index:3` | `rindex:3` | Template mod (TIME MACHINE) |
| `anchor:sched` | `ranchor:sched` | Template mod |
| `wait:due-2d` | `rwait:due-2d` | Template mod |
| `wait:2026-03-15` | `rwait:due+Xs` | Template mod (converted) |
| `sched:due-1h` | `rscheduled:due-1h` | Template mod |
| `sched:2026-03-15` | `rscheduled:due+Xs` | Template mod (converted) |
| `until:due+7d` | `runtil:due+7d` | Template mod |
| `until:2026-03-15` | `runtil:due+Xs` | Template mod (converted) |

---

## 7. Testing Checklist

### Validation Tests
- [ ] Template without anchor date (should ERROR)
- [ ] Template with `wait > due` (should ERROR)
- [ ] Template with `until < due` (should ERROR)
- [ ] Template with `rlast:0` (should ERROR)
- [ ] Template with `rlast:abc` (should ERROR)
- [ ] Template with legacy `recur` field (should WARN + strip)
- [ ] Modify `rtemplate` on instance (should ERROR)
- [ ] Add `r` to existing instance (should ERROR)

### Attribute Copying Tests
- [ ] Template with UDA → instance has UDA
- [ ] Template with annotations → instance has annotations
- [ ] Template with depends → instance has depends
- [ ] Template with numeric UDA → instance has numeric UDA

### Alias Tests
- [ ] `task X mod last:5` → stores as `rlast:5`
- [ ] `task X mod index:3` → stores as `rindex:3`
- [ ] `task X mod anchor:sched` → stores as `ranchor:sched`

### Absolute Date Conversion Tests
- [ ] `task X mod wait:2026-03-15` (no rwait) → converts to rwait
- [ ] `task X mod wait:2026-03-15` (rwait exists) → removes absolute wait
- [ ] `task X mod wait:2026-03-15 rwait:due-2d` → ERROR (both present)
- [ ] Same for scheduled and until

---

## 8. Files Modified

### recurrence_common_hook.py
**Changes:**
- Added attribute category constants (lines 23-47)
- Added 9 validation functions (lines 61-346)
- Rewrote `spawn_instance()` for attribute-agnostic copying (lines 440-550)
- Added `query_task()` function (lines 362-390)

**Line count:** 536 → 720 (+184 lines)

### on-add_recurrence.py
**Changes:**
- Enhanced `expand_template_aliases()` with absolute date conversion (lines 437-593)
- Added validation to `create_template()` (lines 275-432)
- Added validation to `handle_template_modification()` (lines 610-620)
- Updated `main()` to check errors and abort (lines 1122-1213)
- Added `has_errors()`, `add_error()` methods to RecurrenceHandler

**Line count:** 1042 → 1213 (+171 lines)

---

## 9. Removed Features

- **+RECURRING tag:** No longer added to instances (outdated pattern)

---

## 10. Version Documentation

Proposed CHANGES.txt entry:

```
## v2.6.3 - 2026-02-08

### Added
- Attribute-agnostic instance spawning - ALL template attributes now copy
- Support for annotations, dependencies, and all UDAs in instances
- 9 comprehensive validation functions with blocking errors
- Alias support for last→rlast, index→rindex, anchor→ranchor
- Automatic absolute-to-relative date conversion on templates
- Legacy recurrence field detection (recur, mask, imask, parent, rtype)

### Fixed
- Instances now inherit all template attributes, not just project/priority/tags
- Date logic validation prevents wait>anchor and until<anchor
- Template validation blocks absolute wait/scheduled/until fields
- Template creation validates all requirements before proceeding

### Changed
- Removed +RECURRING tag (outdated pattern)
- Error handling blocks invalid operations with exit code 1
- Alias expansion now converts absolute dates to relative offsets
```

---

## 11. Key Behavioral Changes

### Before
- Only project, priority, tags copied to instances
- Aliases only worked for relative dates
- No validation of date logic
- Templates could have absolute dates

### After
- ALL attributes (except DO_NOT_COPY) copied to instances
- Aliases convert absolute dates to relative automatically
- Comprehensive validation with blocking errors
- Templates MUST use relative dates (rwait, rscheduled, runtil)

---

## 12. Debug Examples

```bash
export DEBUG_RECURRENCE=1

# Test absolute date conversion
$ task 5 mod wait:2026-03-15
[2026-02-08 14:30:00] ADD/MOD: Alias expanded: wait -> rwait: {wait_val} -> due+604800s

# Test validation
$ task add "Test" r:7d
[2026-02-08 14:30:01] VALIDATION: Template requirements check failed
ERROR: Recurring task must have 'due' or 'scheduled' date

# Test attribute copying
$ task 72 export | grep myuda
[2026-02-08 14:30:02] COMMON: Copied myuda: test_value
```

---

## Questions & Answers

**Q: What if user sets both wait:2026-03-15 AND rwait:due-2d?**  
A: ERROR - "Template has both 'wait' and 'rwait' - use only rwait"

**Q: What if template already has rwait, then user sets wait:2026-03-15?**  
A: Absolute wait is removed silently, rwait preserved

**Q: Does this work on template creation (on-add)?**  
A: No - alias expansion only works on modification (on-modify)

**Q: Can instances have absolute dates?**  
A: Yes! Instances have actual absolute dates (wait, scheduled, until) calculated from template's relative dates

**Q: What about scheduled as anchor?**  
A: If anchor is 'sched', template CAN have absolute 'scheduled' field (it's the anchor!)

---

**Files Ready:**
- `/home/claude/on-add_recurrence.py` (updated)
- `/mnt/project/recurrence_common_hook.py` (updated)

**Next Steps:**
1. Copy to ~/.task/hooks/
2. Test validation scenarios
3. Test attribute copying
4. Test alias conversion
5. Update CHANGES.txt with v2.6.3 entry
