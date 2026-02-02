## Attribute Validation & Cleanup - Test Scenarios

### Overview
The recurrence hook now enforces strict attribute ownership between templates and instances. This prevents data contamination and ensures clean separation of concerns.

---

## Attribute Ownership Rules

### Templates MUST have:
- `status: recurring`
- `r` - recurrence interval (e.g., "7d", "1w")
- `type` - recurrence type ("period" or "chain")
- `ranchor` - anchor field ("due" or "sched")
- `rlast` - last spawned instance index
- `rend` - (optional) when to stop recurring
- `rwait` - (optional) relative wait expression
- `rscheduled` - (optional) relative scheduled expression

### Templates MUST NOT have:
- `rindex` ❌ (instance-only)
- `rtemplate` ❌ (instance-only)

### Instances MUST have:
- `rtemplate` - UUID of parent template
- `rindex` - instance number in sequence
- `status: pending` (or completed/deleted)

### Instances MUST NOT have:
- `r` ❌ (template-only)
- `type` ❌ (template-only)
- `ranchor` ❌ (template-only)
- `rlast` ❌ (template-only)
- `rend` ❌ (template-only)
- `rwait` ❌ (template-only)
- `rscheduled` ❌ (template-only)

---

## Test Scenarios

### Scenario 1: Template with Instance Attributes (INVALID)

**User attempts:**
```bash
task add "Test" due:friday r:1w rindex:5
```

**What happens:**
1. Hook creates template (status:recurring)
2. Hook detects `rindex` attribute
3. Hook removes `rindex` from template
4. Hook warns user

**Expected output:**
```
WARNING: Removed instance-only attributes from template: rindex
  Templates should not have: rindex, rtemplate
Created recurrence template. First instance will be generated on exit.
```

---

### Scenario 2: Instance with Template Attributes (INVALID)

**Setup:**
```bash
task add "Test" due:friday r:1w
# Wait for instance to spawn (task 42)
```

**User attempts:**
```bash
task 42 mod rlast:10
```

**What happens:**
1. Hook detects task 42 is an instance (has rtemplate, rindex)
2. Hook detects `rlast` attribute being added
3. Hook removes `rlast` from instance
4. Hook warns user

**Expected output:**
```
WARNING: Removed template-only attributes from instance: rlast
  Instances should not have: r, type, ranchor, rlast, rend, rwait, rscheduled
Modified task 42 -- Test (instance #0)
```

---

### Scenario 3: Multiple Invalid Attributes

**User attempts on template:**
```bash
task add "Test" due:friday r:1w rindex:5 rtemplate:abc-123-def
```

**Expected output:**
```
WARNING: Removed instance-only attributes from template: rindex, rtemplate
  Templates should not have: rindex, rtemplate
Created recurrence template. First instance will be generated on exit.
```

**User attempts on instance:**
```bash
task 42 mod r:14d type:chain rlast:10
```

**Expected output:**
```
WARNING: Removed template-only attributes from instance: r, type, rlast
  Instances should not have: r, type, ranchor, rlast, rend, rwait, rscheduled
Modified task 42 -- Test (instance #0)
```

---

### Scenario 4: Valid Modifications (NO WARNINGS)

**Template modification (valid):**
```bash
task 1 mod rlast:5
```

**Expected output:**
```
Template rlast modified: 0 → 5 (5 instances forward)
  Next instance will be #6 due 20260314T000000Z
  Instance #0 (task 42) rindex auto-synced to 5.
```
*(No warning - rlast is valid on templates)*

**Instance modification (valid):**
```bash
task 42 mod rindex:10
```

**Expected output:**
```
Modified instance rindex: 0 → 10
  Template rlast auto-synced to 10.
```
*(No warning - rindex is valid on instances)*

---

## Implementation Details

### Validation Functions

```python
TEMPLATE_ONLY_ATTRS = {'r', 'type', 'ranchor', 'rlast', 'rend', 'rwait', 'rscheduled'}
INSTANCE_ONLY_ATTRS = {'rtemplate', 'rindex'}

def cleanup_template_attributes(task):
    """Remove instance-only attributes from template"""
    removed = []
    for attr in INSTANCE_ONLY_ATTRS:
        if attr in task:
            del task[attr]
            removed.append(attr)
    return removed

def cleanup_instance_attributes(task):
    """Remove template-only attributes from instance"""
    removed = []
    for attr in TEMPLATE_ONLY_ATTRS:
        if attr in task:
            del task[attr]
            removed.append(attr)
    return removed
```

### When Validation Occurs

Validation runs at the END of each handler function, just before returning:

1. **create_template()** - validates as template
2. **handle_template_modification()** - validates as template
3. **handle_instance_modification()** - validates as instance
4. **handle_instance_completion()** - validates as instance

This ensures that even if user tries to add invalid attributes during modification, they are stripped before the task is saved back to Taskwarrior.

---

## Why This Matters

### Without Validation:
```
Template (task 1):
  r: 7d
  rlast: 5
  rindex: 5     ← CONTAMINATION! Shouldn't be here!
  
Instance (task 42):
  rtemplate: {uuid}
  rindex: 5
  rlast: 5      ← CONTAMINATION! Shouldn't be here!
  r: 7d         ← CONTAMINATION! Shouldn't be here!
```

This leads to:
- Confusion about which values are authoritative
- Sync issues and desyncs
- Incorrect instance spawning
- Data bloat

### With Validation:
```
Template (task 1):
  r: 7d
  rlast: 5
  type: period
  ranchor: due
  
Instance (task 42):
  rtemplate: {uuid}
  rindex: 5
```

Clean, clear, and correct!

---

## Edge Cases Handled

### External Modifications
If user directly edits task JSON or uses `task {id} edit` to add invalid attributes:
- Next time hook runs (any modification)
- Hook detects invalid attributes
- Hook removes them with warning

### Import/Sync
If tasks are synced from another system with contaminated attributes:
- Hook will clean them on first modification
- User is warned about cleanup

### Migration from Old System
If migrating from an old recurrence system:
- Invalid attributes will be cleaned automatically
- Warnings inform user about the cleanup
- No manual intervention needed

---

## Testing Checklist

- [ ] Template creation with rindex (should be removed)
- [ ] Template creation with rtemplate (should be removed)
- [ ] Template modification adding rindex (should be removed)
- [ ] Instance modification adding rlast (should be removed)
- [ ] Instance modification adding r (should be removed)
- [ ] Instance modification adding type (should be removed)
- [ ] Instance modification adding rwait (should be removed)
- [ ] Multiple invalid attributes at once (all removed)
- [ ] Valid template modifications (no warnings)
- [ ] Valid instance modifications (no warnings)
- [ ] Completion with invalid attributes (cleaned)

---

## Debug Output

When DEBUG_RECURRENCE=1:
```
[2026-02-02 10:30:15] ADD/MOD: Removed instance-only attribute 'rindex' from template
[2026-02-02 10:30:15] ADD/MOD: Removed instance-only attribute 'rtemplate' from template
```

This helps track when and why attributes are being removed.
