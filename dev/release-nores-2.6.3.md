# Taskwarrior Enhanced Recurrence - v2.6.3 Release Notes
**Date:** 2026-02-10  
**Status:** Critical Bug Fixes

---

## Critical Fixes

### Bug Fix #1: Date Calculations Completely Broken (CRITICAL)
**Impact:** ALL instances were getting template's exact date instead of calculated dates

**Root Cause:**  
Two instances of using wrong field name in `spawn_instance()`:

1. **Line 819** - Command building:
   ```python
   # WRONG:
   cmd.append(f'{anchor_field}:{format_date(anchor_date)}')  # 'sched:...' - invalid!
   
   # FIXED:
   cmd.append(f'{actual_field}:{format_date(anchor_date)}')  # 'scheduled:...' - valid!
   ```
   
   When anchor was 'sched', Taskwarrior received `sched:YYYYMMDD...` which it ignored as invalid field.
   Instance got no scheduled date from calculation.

2. **Line 848** - Attribute-agnostic copying:
   ```python
   # WRONG:
   already_handled = {anchor_field, 'description', 'uuid', 'status'}  # 'sched'
   
   # FIXED:
   already_handled = {actual_field, 'description', 'uuid', 'status'}  # 'scheduled'
   ```
   
   The attribute-agnostic copying loop saw template's 'scheduled' field was NOT in `already_handled` 
   (which contained 'sched'), so it copied the raw template scheduled date as a string field.

**Combined Effect:**
- Calculated date command ignored (line 819 bug)
- Template's raw date copied instead (line 848 bug)
- Instance got template's exact date, not calculated

**Symptom:**
```bash
task add r:7d due:tomorrow "Test"
# Template due: Feb 11
# Instance #1 due: Feb 11 ✓ (correct, should match template)

task <instance> done
# Instance #2 due: Feb 11 ✗ (WRONG! Should be Feb 18 = template + 7d)
```

**Files Changed:**
- `recurrence_common_hook.py` lines 819, 848

---

### Bug Fix #2: Chain Recurrence Validation Too Strict
**Impact:** Chain recurrence refused to spawn instances if completed early

**Root Cause:**  
Validation added to catch calculation errors was too broad:

```python
# WRONG (applied to both types):
if rindex > 1 and anchor_date <= template_anchor:
    return None  # Refuse to spawn
```

**The Problem:**
- **Periodic:** Instance #2 = template + period → MUST be after template ✓
- **Chain:** Instance #2 = completion_time + period → CAN be before template ✓

Example where chain SHOULD work:
```
Template created at 17:00 with sched:19:00 (now+2hrs)
Instance #1 sched: 19:00
User completes #1 at 17:05 (early!)
Instance #2 should be: 17:05 + 1h = 18:05
Validation saw: 18:05 < 19:00 → BLOCKED ✗
```

**Fixed:**
```python
# Only validate for periodic (where it's mathematically required)
if rtype == 'period' and anchor_date <= template_anchor:
    return None
```

**Files Changed:**
- `recurrence_common_hook.py` lines 796-800

---

## What We Learned

### 1. The Danger of Short Field Names
Taskwarrior has both:
- Short names: `sched`, `ty`, `pri` (used in UDA definitions)
- Full names: `scheduled`, `type`, `priority` (actual field names in JSON)

**The Trap:**
```python
anchor_field = task.get('ranchor', 'due')  # Returns 'sched' or 'due'
actual_field = get_anchor_field_name(anchor_field)  # Maps to 'scheduled' or 'due'

# Must use actual_field for:
# - Task commands: 'scheduled:...' not 'sched:...'
# - Field lookups: template['scheduled'] not template['sched']
# - Exclusion sets: {'scheduled', ...} not {'sched', ...}
```

### 2. Attribute-Agnostic Copying is Powerful but Dangerous
Before v2.6.3, we explicitly listed fields to copy:
```python
if 'project' in template:
    cmd.append(f'project:{template["project"]}')
if 'priority' in template:
    cmd.append(f'priority:{template["priority"]}')
# Safe but limited
```

After v2.6.3, we copy everything:
```python
for field, value in template.items():
    if field not in already_handled and field not in DO_NOT_COPY:
        cmd.append(f'{field}:{value}')
# Powerful but requires perfect already_handled set
```

**Lesson:** When copying "everything except X", the "except X" list must be 100% accurate.

### 3. Validation Must Match Logic
We added validation to catch calculation errors, but didn't account for chain recurrence:
- Periodic: Deterministic formula (template + index × period)
- Chain: Dynamic (depends on completion time)

**Lesson:** Validation rules must match the flexibility of the underlying algorithm.

### 4. The Testing Gap
These bugs existed in our comprehensive validation update (v2.6.2 → v2.6.3) because:
- Tests focused on template creation (on-add validation)
- Tests didn't cover instance spawning (on-exit execution)
- Tests didn't verify actual dates in spawned instances

**Gap:** We validated INPUT but not OUTPUT.

---

## Testing Insights

### What Caught These Bugs
**User testing with DEBUG enabled:**
```bash
export DEBUG_RECURRENCE=1
task add r:1h ty:c sched:now+2hrs ...
task <id> done
tail -50 ~/.task/recurrence_debug.log
```

**Key Debug Lines:**
```
[2026-02-10 15:05:15] COMMON: Copied scheduled: 20260210T215858Z  ← RED FLAG!
```

If you see "Copied <anchor_field>:" in debug log, it means the anchor wasn't properly excluded.

### What Would Have Caught Them Earlier
**Integration test:**
```bash
# Create template
task add r:7d due:tomorrow "Test"
TEMPLATE_DUE=$(task export status:recurring | jq -r '.[0].due')

# Complete instance
task <id> done

# Check instance #2
INSTANCE_DUE=$(task export status:pending | jq -r '.[0].due')

# Verify dates differ
if [ "$TEMPLATE_DUE" == "$INSTANCE_DUE" ]; then
    echo "BUG: Instance has same date as template!"
fi
```

---

## Architecture Notes

### The spawn_instance() Flow
```
1. Parse recurrence interval (7d → timedelta)
2. Get template anchor date
3. Calculate instance anchor date:
   - rindex=1: Use template date
   - rindex>1 periodic: template + (index-1) × period
   - rindex>1 chain: completion_time + period
4. Calculate relative dates (rwait, rscheduled, runtil)
5. Build task add command:
   - Add calculated anchor date         ← Line 819 (was using wrong name)
   - Add calculated relative dates
   - Copy all other attributes          ← Line 848 (was missing anchor in skip list)
6. Execute command
7. Update template rlast
```

### The Field Name Map
```
User Input    → UDA Short Name → Actual Field Name → Task Command
============    ===============   =================   ============
sched:...       ranchor:sched     scheduled           scheduled:...
due:...         ranchor:due       due                 due:...
ty:c           type:chain        type                 type:chain
last:5         rlast:5           rlast                rlast:5
```

**Key:** `ranchor` stores short names, but spawn_instance must use actual names.

---

## Prevention Strategies

### 1. Naming Convention
```python
# Always use this pattern:
anchor_field = template.get('ranchor', 'due')     # Short name from UDA
actual_field = get_anchor_field_name(anchor_field)  # Full name for use

# Then:
# - Commands: Use actual_field
# - Lookups: Use actual_field  
# - Comments: Clarify which one you're using
```

### 2. Debug Assertions
Add to spawn_instance:
```python
if DEBUG:
    debug_log(f"anchor_field={anchor_field}, actual_field={actual_field}", "COMMON")
    assert actual_field in ['due', 'scheduled'], f"Invalid actual_field: {actual_field}"
    assert anchor_field in ['due', 'sched'], f"Invalid anchor_field: {anchor_field}"
```

### 3. Test Coverage
Add integration tests:
- Verify instance dates differ from template
- Check both periodic and chain
- Test both 'due' and 'sched' anchors
- Verify relative date calculations

---

## Migration Notes

### Upgrading from v2.6.2
1. **Backup your data:**
   ```bash
   cp ~/.task/pending.data ~/.task/pending.data.backup
   cp ~/.task/completed.data ~/.task/completed.data.backup
   ```

2. **Install v2.6.3:**
   ```bash
   cp recurrence_common_hook.py ~/.task/hooks/
   chmod 644 ~/.task/hooks/recurrence_common_hook.py
   rm -rf ~/.task/hooks/__pycache__
   ```

3. **Existing templates are fine** - they don't need modification

4. **Existing instances with wrong dates:**
   - Option A: Delete and let them re-spawn correctly
   - Option B: Manually fix: `task <id> mod due:correct-date`

### Compatibility
- ✓ Works with existing v2.6.2 templates
- ✓ No config file changes needed
- ✓ No .taskrc changes needed
- ✓ Templates with old bugs will spawn correct instances going forward

---

## Version History Summary

**v2.6.1 → v2.6.2:** Added comprehensive validation system, attribute-agnostic copying  
**v2.6.2 → v2.6.3:** Fixed critical bugs in v2.6.2's attribute-agnostic implementation

---

## Files Changed in v2.6.3

### recurrence_common_hook.py
- Line 819: `anchor_field` → `actual_field` (command building)
- Line 848: `anchor_field` → `actual_field` (already_handled set)
- Lines 796-800: Moved validation inside periodic branch only
- Line 5: Version updated to 2.6.3

**Total changes:** 4 lines modified

---

## Acknowledgments

These bugs were discovered and fixed through:
- Real-world testing with DEBUG mode
- Careful log analysis
- Understanding the subtle difference between short and full field names
- Recognizing that chain recurrence is fundamentally different from periodic

**Lesson:** Sometimes the most powerful features (attribute-agnostic copying) introduce the most subtle bugs. Testing and debugging infrastructure saved us.

---

## What's Working Now (Verified)

### Chain Recurrence ✓
```bash
task add r:1h ty:c sched:now+2hrs wait:sched-90min "Chain test"
task <id> delete
# Instance #2 spawned with calculated dates ✓
```

### Periodic Recurrence ✓
```bash
task add r:1d ty:p due:tomorrow "Periodic test"  
task <id> done
# Instance #2 due = tomorrow + 1d ✓
```

### Both Anchors ✓
- `ranchor:due` (default) ✓
- `ranchor:sched` ✓

### Relative Dates ✓
- `rwait:due-7d` ✓
- `rscheduled:due-2d` ✓
- `runtil:due+30d` ✓

---

## Next Steps

1. **More user testing** - especially edge cases
2. **Integration test suite** - verify dates, not just structure
3. **Documentation updates** - add troubleshooting section
4. **Consider:** Add self-check command that verifies dates match formulas

---

**v2.6.3 Status:** Production Ready  
**Confidence Level:** High (bugs found and fixed through actual usage)  
**Recommendation:** Update immediately if using v2.6.2

---

*"The best debugger is real users with DEBUG=1 turned on."*
