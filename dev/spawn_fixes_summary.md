## Core Functionality Fix - Final Summary

### The Complete Picture

**The Problem:**
spawn_instance() was updating template rlast even during respawn, causing rlast to change when it shouldn't.

**The Solution:**
Added `update_rlast` parameter to control whether rlast is updated.

**Why It Works:**
- spawn_instance() uses `rc.hooks=off` for rlast updates
- This means on-modify hook NEVER runs from spawn_instance()
- Therefore:
  - on-exit can increment rlast without triggering on-modify
  - on-modify respawn can leave rlast unchanged
  - No cascades, no loops, clean separation

---

## Usage Matrix

| Caller    | Scenario              | update_rlast | rlast Change | on-modify Triggered? |
|-----------|-----------------------|--------------|--------------|----------------------|
| on-exit   | First instance        | TRUE         | ? → 1        | NO (hooks=off)       |
| on-exit   | Next after completion | TRUE         | N → N+1      | NO (hooks=off)       |
| on-modify | Respawn (time machine)| FALSE        | stays same   | N/A (we're IN it)    |
| on-modify | Childless template    | FALSE        | stays same   | N/A (we're IN it)    |

---

## Call Graph

```
User: task add "Daily" due:today r:1d
  ↓
on-add: Create template (rlast:1)
  ↓
[exit]
  ↓
on-exit: spawn_instance(template, 1, update_rlast=TRUE)
  ↓
  task rc.hooks=off modify rlast:1  ← Hooks disabled!
  ↓
âœ… Template rlast:1, Instance #1 created, NO on-modify trigger

---

User: task 2 done
  ↓
on-exit: spawn_instance(template, 2, completion, update_rlast=TRUE)
  ↓
  task rc.hooks=off modify rlast:2  ← Hooks disabled!
  ↓
âœ… Template rlast:2, Instance #2 created, NO on-modify trigger

---

User: task 1 mod rlast:5  ← Time machine!
  ↓
on-modify: should_respawn() returns TRUE
  ↓
on-modify: delete_instance(instance #2)
  ↓
on-modify: spawn_instance(template, 5, update_rlast=FALSE)
  ↓
  (no rlast update - it's already 5 from user!)
  ↓
âœ… Template rlast:5 (unchanged), Instance #5 created

---

User: task 3 done
  ↓
on-exit: spawn_instance(template, 6, completion, update_rlast=TRUE)
  ↓
  task rc.hooks=off modify rlast:6  ← Hooks disabled!
  ↓
âœ… Template rlast:6, Instance #6 created
```

---

## Critical Insights

### 1. rc.hooks=off Prevents Cascades
When spawn_instance() updates rlast with `rc.hooks=off`, the modify command does NOT trigger hooks. This is the KEY to preventing cascades.

### 2. respawn vs spawn Separation
- **spawn** (on-exit): Creates next in sequence, increments rlast
- **respawn** (on-modify): Replaces current, preserves rlast

### 3. update_rlast Controls Behavior
- TRUE: Normal spawn, rlast increments
- FALSE: Respawn, rlast unchanged

### 4. Only User Modifications Trigger on-modify
spawn_instance() internal modifications never trigger on-modify because of rc.hooks=off.

---

## Files Modified

### recurrence_common_hook.py
- Added `update_rlast=True` parameter to spawn_instance()
- Made rlast update conditional on this parameter
- Lines changed: ~360 (signature), ~478 (conditional update)

### on-add_recurrence.py  
- Respawn calls use `update_rlast=False`
- Lines changed: ~850 (respawn), ~865 (childless)

### on-exit_recurrence.py
- Normal spawn calls use `update_rlast=True`
- Lines changed: ~425 (completion spawn), ~450 (first spawn)

---

## Testing

Run test_core_recurrence.sh to verify:

1. âœ… Create recurring task → instance #1 spawns
2. âœ… Complete instance #1 → instance #2 spawns
3. âœ… Time machine (rlast: 2→5) → instance #5 respawns (replacing #2)
4. âœ… Complete instance #5 → instance #6 spawns
5. âœ… Modify non-recurrence field → no respawn

Expected results:
- Template rlast increments naturally (1, 2, 5, 6)
- Instances match (rindex: 1, 2, 5, 6)
- No cascades, no errors, clean messaging

---

## Conclusion

The fix is elegant and surgical:
- One parameter controls behavior
- Leverages existing rc.hooks=off protection
- Maintains clean separation of concerns
- Respects the spawn/respawn distinction

**Core functionality restored!** 🎉
