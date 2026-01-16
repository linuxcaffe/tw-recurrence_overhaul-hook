# Phase 2 Implementation Summary
## Template Modification → Instance Updates + Tag Removal

**Implementation Date:** 2026-01-12  
**Status:** ✅ Complete

---

## Changes Made

### 1. **on-add_recurrence.py** - Template Modification Handler

#### Added Functions:
- `get_pending_instances(template_uuid)` - Fetch all pending instances for a template
- `update_instance_from_template(instance, template, changes)` - Apply template changes to single instance

#### Enhanced Functions:
- `handle_template_modification()` - Now detects changes and propagates to instances:
  - **Description**: Replaced on instances
  - **Priority**: Replaced on instances  
  - **Project**: Replaced on instances
  - **Tags**: Merged (additive - keeps user-added tags + adds template tags)

- `handle_instance_completion()` - Now warns user when modifying an instance:
  ```
  ⚠️  You're modifying a recurring instance.
     Consider modifying the template instead: task <ID> modify ...
     This will update all pending instances.
  ```

#### Behavior:
```bash
# User modifies template:
task 1 modify project:work priority:H +urgent

# Hook automatically updates all pending instances:
# - Sets project:work (replace)
# - Sets priority:H (replace)
# - Adds +urgent tag (merge - keeps existing tags)
# → "Updated 3 pending instance(s) with template changes."
```

---

### 2. **on-exit_recurrence.py** - Tag Removal

#### Removed:
- `+RECURRING` tag no longer added to instances
- Instances now identified via `rtemplate` UDA only

**Before:**
```bash
task add "Test" r:1w due:tomorrow ty:p
# Instance created with: +RECURRING tag (ugly in reports)
```

**After:**
```bash
task add "Test" r:1w due:tomorrow ty:p
# Instance created with: rtemplate:uuid (clean, searchable)
```

---

### 3. **recurrence.rc** - Report Enhancements (Option D)

#### Changed UDA Label:
```diff
- uda.rtemplate.label=Template UUID
+ uda.rtemplate.label=Recur
```
**Impact:** Cleaner column display in reports

#### Enhanced `rinstances` Report:
**Before:**
```bash
task rinstances rtemplate:UUID  # Required UUID argument
# Only showed pending/waiting
```

**After:**
```bash
task rinstances                 # Show ALL instances
task rinstances rtemplate:UUID  # Show specific template's instances
task rinstances project:work    # Filter by project
# Shows all statuses (pending/waiting/completed)
```

**New columns:**
- `ID` - Task ID
- `Status` - Current status
- `Description` - Task description
- `#` - Instance index (rindex)
- `Due` - Due date
- `Template` - Template UUID (shortened for display)
- `Urg` - Urgency score

**Sort order:** `due+,rindex+` (by due date, then instance number)

---

## Usage Examples

### Modifying Templates

**Scenario 1: Update all instances**
```bash
# Create template with 3 pending instances
task add "Weekly review" r:1w due:tomorrow ty:p rlimit:3

# Modify template - all instances update automatically
task 1 modify project:reviews priority:H
# → Updated 3 pending instance(s) with template changes.
```

**Scenario 2: Add tags**
```bash
# Template has no tags
task 1 modify +important +work
# → All instances get +important +work tags (merged)
```

**Scenario 3: User customized instance**
```bash
# User previously added +urgent to instance 5
task 5 modify +urgent

# Later, template is modified
task 1 modify +important
# → Instance 5 now has: +urgent +important (merge, not replace)
```

### Finding Instances

**Old way (ugly):**
```bash
task +RECURRING list        # Tag clutters display
task +RECURRING -COMPLETED  # Filter syntax awkward
```

**New way (clean):**
```bash
task rinstances             # All instances, all statuses
task rinstances project:work  # Filter by project
task rtemplate:abc123      # Instances of specific template
```

### Instance Modification Warning

**Before:**
```bash
task 5 modify project:personal
# No warning, user might not realize it's a recurring instance
```

**After:**
```bash
task 5 modify project:personal

⚠️  You're modifying a recurring instance.
   Consider modifying the template instead: task 1 modify ...
   This will update all pending instances.

# Instance still modified (user choice), but informed
```

---

## Configuration Impact

### For Existing Users

**No action required** - changes are backward compatible:
- Old instances with `+RECURRING` tag still work
- New instances won't have the tag
- Reports work for both

**Optional cleanup:**
```bash
# Remove old +RECURRING tags from existing instances
task rtemplate.any: modify -RECURRING
```

### For New Users

Just include `recurrence.rc` as before:
```bash
# In ~/.taskrc
include ~/.task/recurrence.rc
```

---

## Testing Recommendations

### Test Cases for Template Modification:

1. **Description change**
   ```bash
   task 1 modify "New description"
   # Verify all instances have new description
   ```

2. **Priority change**
   ```bash
   task 1 modify priority:H
   # Verify all instances have priority:H
   ```

3. **Project change**
   ```bash
   task 1 modify project:work
   # Verify all instances have project:work
   ```

4. **Tag merge**
   ```bash
   # Instance 5 has +custom
   task 1 modify +urgent
   # Verify instance 5 has both +custom +urgent
   ```

5. **Mixed changes**
   ```bash
   task 1 modify priority:H project:work +urgent "Updated desc"
   # Verify all instances get all changes
   ```

### Test Cases for Reports:

1. **rinstances report**
   ```bash
   task rinstances
   # Should show all instances, no +RECURRING in tags column
   ```

2. **Searchability**
   ```bash
   task rtemplate.any:        # Find all instances
   task rtemplate:uuid123     # Find specific template's instances
   ```

---

## Debug Output

With `DEBUG_RECURRENCE=1`:

```
[2026-01-12 10:30:45] ADD/MOD: Template modified, updating instances: ['description', 'priority', 'tags']
[2026-01-12 10:30:45] ADD/MOD:   Updated instance 5
[2026-01-12 10:30:45] ADD/MOD:   Updated instance 6
[2026-01-12 10:30:45] ADD/MOD:   Updated instance 7
```

---

## Known Limitations

1. **Performance**: Modifying template with 100+ instances requires 100+ subprocess calls
   - With default `rlimit:3`, typically only 3 instances updated
   - Acceptable for most use cases

2. **Annotations**: Not yet propagated (future enhancement)

3. **User customizations**: Merge strategy is additive for tags, replace for other fields
   - No way to detect which fields user intentionally customized
   - Conservative approach: trust user's explicit modifications

---

## Next Steps

- [ ] **Phase 1**: Rewrite test suite with robust architecture
- [ ] **Phase 4**: Enhance rr.py for template/instance management (on hold)
- [ ] **Phase 3**: Design discussion for +RECURRING removal strategy

---

## Files Modified

1. `/mnt/project/on-add_recurrence.py` - Added instance update logic
2. `/mnt/project/on-exit_recurrence.py` - Removed +RECURRING tag
3. `/mnt/project/recurrence.rc` - Enhanced reports (Option D)
