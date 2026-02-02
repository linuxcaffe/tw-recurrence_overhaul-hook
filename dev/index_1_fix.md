## 1-Indexed Fix - Quick Summary

### Changes Made

All instances now start at **rindex:1** (not 0).

#### 1. recurrence_common_hook.py
```python
# Line ~378
if rindex == 1:  # Was: rindex == 0
    # Instance 1 always uses template's anchor date
    anchor_date = template_anchor
else:
    # Period: template + (rindex - 1) * period  # Was: rindex * period
    anchor_date = template_anchor + (recur_delta * (rindex - 1))
```

#### 2. on-add_recurrence.py
```python
# Line ~395
task['rlast'] = '1'  # Was: '0'
```

#### 3. on-exit_recurrence.py
```python
# Line ~455
msg = spawn_instance(task, 1)  # Was: 0

# Line ~443
str(task.get('rlast', '')).strip() in ['0', '1', '']  # Added '0' for old templates
```

### Index Mapping

**Old (0-indexed):**
- Instance #0: anchor + (0 × r) = anchor
- Instance #1: anchor + (1 × r) = anchor + r
- Instance #2: anchor + (2 × r) = anchor + 2r

**New (1-indexed):**
- Instance #1: anchor + (0 × r) = anchor
- Instance #2: anchor + (1 × r) = anchor + r  
- Instance #3: anchor + (2 × r) = anchor + 2r

### Examples

```bash
# Create template
task add "Daily" due:2026-02-01 r:1d

# Template: rlast=1 (not 0)
# Instance #1: due:2026-02-01 (not #0)

# Time machine
task 1 mod rlast:5

# Deletes instance #1
# Spawns instance #5: due:2026-02-05 (anchor + 4d)

# Complete
task 2 done

# Spawns instance #6: due:2026-02-06 (anchor + 5d)
```

### Backward Compatibility

The on-exit check now looks for `rlast` in `['0', '1', '']` to handle:
- Old templates with rlast=0
- New templates with rlast=1  
- Fresh templates with rlast=''

All should spawn instance #1 correctly.
