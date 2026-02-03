## Recurrence Spawning & Respawning Rules - Formal Specification

### Version: 0.4.0
### Date: 2026-02-03

---

## Core Principles

### 1. One-to-One Invariant
Every active template MUST have exactly one pending/waiting instance at all times.

### 2. Perfect Cloning
When an instance is spawned from a template, it MUST faithfully include:
- ✅ All standard attributes (project, priority, tags, description)
- ✅ All UDAs (user-defined attributes)
- ✅ All annotations
- ✅ Plus recurrence metadata (rtemplate, rindex)

### 3. Isolation Principle
Modifying one template/instance NEVER affects other templates/instances.

---

## Terminology

### Spawn (Normal Creation)
- **When**: Instance completes/deletes, template needs next instance
- **Action**: Create NEW instance
- **Increment**: YES - `rlast = rlast + 1`, `rindex = rlast`
- **Where**: on-exit hook

### Respawn (Replace Existing)
- **When**: Template recurrence fields modified
- **Action**: Delete OLD instance, create NEW instance
- **Increment**: NO - `rindex = current rlast` (stays same)
- **Where**: on-modify hook

---

## Template Required Fields

Templates MUST have:
- `status: recurring`
- `r` (recurrence interval, e.g., "7d")
- `type` (period or chain)
- `ranchor` (due or sched)
- `rlast` (last spawned instance number)
- `due` OR `scheduled` (the anchor date)

**Missing any?** → Error, cannot function as template

---

## Instance Required Fields

Instances MUST have:
- `rtemplate` (UUID of parent template)
- `rindex` (instance number in sequence)

**Missing any?** → Error, orphaned instance

---

## Respawn-Triggering Fields

Changes to these template fields trigger RESPAWN:

### 1. `rlast` (Time Machine)
```bash
task 77 mod rlast:5
```
- **Why**: Jump forward/backward in sequence
- **Action**: Delete current instance, spawn instance #5

### 2. `type` (Period ↔ Chain)
```bash
task 77 mod type:chain
```
- **Why**: Changes spawning behavior
- **Action**: Respawn with new type

### 3. `ranchor` (Due ↔ Sched)
```bash
task 77 mod ranchor:sched
```
- **Why**: Changes which field is the anchor
- **Action**: Respawn with new anchor calculations

### 4. `r` (Recurrence Interval)
```bash
task 77 mod r:2w
```
- **Why**: Changes instance spacing/dates
- **Action**: Respawn with new interval

### 5. `rwait` / `wait` (Wait Time)
```bash
task 77 mod wait:due-2d
```
- **Why**: Changes when instance becomes visible
- **Action**: Respawn with new wait

### 6. `rscheduled` / `scheduled` (Scheduled Time)
```bash
task 77 mod scheduled:due-1h
```
- **Why**: Changes scheduled date calculation
- **Action**: Respawn with new scheduled

### 7. `due` / `scheduled` (Anchor Date)
```bash
task 77 mod due:2026-03-15
```
- **Why**: Shifts all instance dates
- **Action**: Respawn with recalculated dates

---

## Non-Respawn Fields

Changes to these fields DO NOT trigger respawn:

### `rend` (Recurrence End)
```bash
task 77 mod rend:10
```
- **Why**: Only affects future spawning, not current instance
- **Action**: Update template only, no respawn

### Standard Attributes
```bash
task 77 mod project:work priority:H +urgent
```
- **Why**: Doesn't affect instance dates/calculation
- **Action**: Update template, provide propagation message

---

## Orphan & Childless Detection

### Childless Template
**Condition**: Template has rlast but no instance with matching rindex exists

**Causes:**
- Instance was manually deleted
- Previous respawn failed
- Data corruption

**Action**: RESPAWN instance with current rlast
```
ERROR: No pending instance exists for template
  Expected: Instance with rindex=5
  Found: None
  Respawning instance #5 now
```

### Orphan Instance
**Condition**: Instance has rtemplate but that template doesn't exist

**Causes:**
- Template was deleted
- Template UUID changed
- Data corruption

**Action**: ERROR - cannot respawn without template
```
ERROR: Orphan instance detected
  Instance rtemplate={uuid} but template not found
  Manual fix required:
    1. Find or recreate the template
    2. Or delete this orphan: task {id} delete
```

---

## Respawn Algorithm

### Pseudocode:
```python
def handle_template_modification(original, modified):
    # 1. Check if any respawn-triggering fields changed
    respawn_needed = should_respawn(original, modified)
    
    # 2. Check for childless template
    status, instance = check_instance_count(template_uuid)
    if status == 'missing':
        respawn_needed = True  # Always respawn if childless
    
    # 3. Perform respawn if needed
    if respawn_needed and status == 'ok':
        delete_instance(instance)
        spawn_instance(modified, modified['rlast'])  # No increment!
    elif respawn_needed and status == 'missing':
        spawn_instance(modified, modified['rlast'])  # Just spawn
    
    # 4. Handle other modifications (messaging, etc.)
```

### Function: should_respawn()
```python
def should_respawn(original, modified):
    """Check if any respawn-triggering fields changed"""
    
    respawn_fields = [
        'rlast', 'type', 'ranchor', 'r',
        'rwait', 'wait', 'rscheduled', 'scheduled',
        'due', 'scheduled'  # anchor dates
    ]
    
    for field in respawn_fields:
        if field in modified and modified.get(field) != original.get(field):
            return True
    
    return False
```

---

## Spawn Requirements (Perfect Cloning)

When spawning an instance from a template, copy:

### Standard Attributes
- `description`
- `project`
- `priority`
- `tags` (all of them)
- `depends` (task dependencies)

### Calculated Dates
- `due` or `scheduled` (based on rindex and type)
- `wait` (calculated from rwait if present)
- `scheduled` (calculated from rscheduled if present)

### UDAs (User-Defined Attributes)
- ALL UDAs from template (except recurrence-specific ones)
- Examples: `estimate`, `category`, custom fields

### Annotations
- ALL annotations from template
- Preserve timestamps

### Recurrence Metadata (Added)
- `rtemplate` = template UUID
- `rindex` = instance number

### NOT Copied
- `status` (instance is pending, not recurring)
- `rlast` (template-only)
- `type` (template-only)
- `ranchor` (template-only)
- `r` (template-only)
- `rend` (template-only)
- `rwait` (template-only, becomes absolute wait)
- `rscheduled` (template-only, becomes absolute scheduled)

---

## Examples

### Example 1: Respawn Due to rlast Change
```bash
# Template with instance #1
task 77 mod rlast:5
```

**Process:**
1. Detect: rlast changed (1 → 5)
2. Check: Instance #1 exists
3. Delete: Instance #1
4. Spawn: Instance #5 with dates = anchor + (r × 4)
5. Result: Template rlast=5, Instance rindex=5

### Example 2: Respawn Due to Interval Change
```bash
# Template r:1d
task 77 mod r:2d
```

**Process:**
1. Detect: r changed (1d → 2d)
2. Check: Instance exists
3. Delete: Old instance
4. Spawn: New instance with new interval
5. Result: Instance dates recalculated with r:2d

### Example 3: Non-Respawn Modification
```bash
# Change priority
task 77 mod priority:H
```

**Process:**
1. Detect: priority changed
2. Check: Not a respawn field
3. Update: Template priority only
4. Message: "To apply to current instance: task 78 mod priority:H"

### Example 4: Childless Template
```bash
# Instance manually deleted
task 78 delete
# Then modify template
task 77 mod priority:H
```

**Process:**
1. Detect: priority changed (not respawn field)
2. Check: NO instance exists (childless!)
3. Respawn: Spawn instance #1 anyway (one-to-one invariant)
4. Message: "Respawned missing instance #1"

---

## Error Conditions

### Missing Required Field on Template
```
ERROR: Template missing required field: r
  Templates must have: status, r, type, ranchor, rlast, due/scheduled
  Manual fix required
```

### Missing Required Field on Instance
```
ERROR: Instance missing required field: rtemplate
  Instances must have: rtemplate, rindex
  This is an orphaned instance - manual cleanup needed
```

### Orphan Instance
```
ERROR: Orphan instance detected
  Instance rtemplate={uuid} but template not found
  Cannot respawn without template
  Manual fix: delete this instance or restore template
```

### Multiple Instances (Data Corruption)
```
ERROR: Multiple instances exist (violates one-to-one rule)
  Expected: 1 instance
  Found: 3 instances
  Manual fix required - decide which to keep
```

---

## Implementation Checklist

- [ ] Add `should_respawn()` function
- [ ] Update `handle_template_modification()` to use respawn logic
- [ ] Always check for childless template on ANY modification
- [ ] Enhance `spawn_instance()` to copy ALL UDAs and annotations
- [ ] Add required field validation
- [ ] Add orphan detection
- [ ] Update messaging to distinguish respawn vs spawn
- [ ] Test all respawn-triggering fields
- [ ] Test perfect cloning (UDAs, annotations)
- [ ] Test childless template recovery

---

## Summary

**Respawn** = Replace existing instance when template recurrence fields change
**Spawn** = Create next instance when current completes
**Perfect Clone** = Instance must have ALL template attributes/UDAs/annotations
**One-to-One** = Always maintain exactly one instance per template
