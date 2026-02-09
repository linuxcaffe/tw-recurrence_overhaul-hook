# The Spool File Pattern - Technical Deep Dive

**Version:** 2.6.2  
**Date:** 2026-02-08  
**Status:** Implemented and Working ✓

---

## The Problem

When a user modifies a recurrence template attribute, the corresponding instance must be updated **in the same transaction**. This creates a fundamental challenge:

```bash
user: task 72 mod rlast:5

# Required behavior:
# 1. Template 72: rlast changes from 1 → 5
# 2. Instance 73: rindex changes from 1 → 5
# 3. Instance 73: due date recalculates
# 4. All in ONE user command
```

**The challenge:** How does `on-modify` hook modify TWO tasks when it's only processing ONE?

---

## Failed Approaches

### Attempt 1: Direct Subprocess from on-modify

```python
# In on-add_recurrence.py (on-modify hook)
def handle_template_modification(original, modified):
    # Detect rlast change
    if modified['rlast'] != original['rlast']:
        # Try to update instance directly
        subprocess.run(['task', modified['uuid'], 'modify', 'rindex:5'])
```

**Result:** 
- Subprocess returns exit code 0 (success!)
- No error messages
- Changes silently lost
- Instance never updated

**Why:** Taskwarrior 2.6.2 holds a **file lock on `pending.data`** during hook execution. The subprocess `task modify` waits for the lock, gets it after parent releases it, but by then the parent has already written its version of `pending.data`, overwriting the subprocess's changes.

### Attempt 2: Using rc.hooks=off

```python
subprocess.run(['task', 'rc.hooks=off', 'rc.confirmation=off', 
                uuid, 'modify', 'rindex:5'])
```

**Result:** Same as Attempt 1

**Why:** `rc.hooks=off` prevents hook re-entrancy but doesn't affect the file lock. The parent process still holds the lock during hook execution.

### Attempt 3: Re-entrancy Guard

```python
# Set environment variable to prevent cascading
os.environ['RECURRENCE_PROPAGATING'] = '1'
subprocess.run(['task', uuid, 'modify', 'rindex:5'])
```

**Result:** Same as Attempt 1

**Why:** The re-entrancy guard worked perfectly (prevented infinite loops), but the underlying file lock problem remained. The subprocess's changes were still lost.

---

## The Solution: Spool File Pattern

**Key Insight:** `on-exit` hook runs AFTER Taskwarrior releases the file lock!

```
Taskwarrior execution timeline:

1. User: task 72 mod rlast:5
2. Lock pending.data
3. Read task 72
4. Call on-modify hook
   ├─ Hook calculates updates
   ├─ Hook writes instructions to spool file
   └─ Hook returns
5. Write task 72 changes
6. Unlock pending.data
7. Call on-exit hook
   ├─ Read spool file
   ├─ Execute: task 73 modify rindex:5 due:...
   ├─ Delete spool file
   └─ Return
8. Done
```

### Implementation

**File Location:**
```
~/.task/recurrence_propagate.json
```

**Spool File Format:**
```json
{
  "instance_uuid": "52c8c750-f101-40da-96c0-cb7fad8b2749",
  "instance_rindex": "1",
  "updates": {
    "rindex": "5",
    "due": "20260213T050000Z"
  },
  "template_id": "72",
  "changes": ["rlast"]
}
```

**on-modify writes spool (on-add_recurrence.py):**
```python
# After calculating what instance needs
spool = {
    'instance_uuid': instance_uuid,
    'instance_rindex': instance.get('rindex', '?'),
    'updates': instance_updates,  # {rindex: "5", due: "..."}
    'template_id': task_id,
    'changes': list(recurrence_changes.keys())
}

spool_path = os.path.expanduser('~/.task/recurrence_propagate.json')
with open(spool_path, 'w') as f:
    json.dump(spool, f)

# User sees: "Instance #1 will be synced."
```

**on-exit reads and processes spool (on-exit_recurrence.py):**
```python
def process_tasks(self, tasks):
    feedback = []
    
    # FIRST: Process spool (before anything else)
    spool_path = os.path.expanduser('~/.task/recurrence_propagate.json')
    if os.path.exists(spool_path):
        try:
            with open(spool_path, 'r') as f:
                spool = json.load(f)
            os.remove(spool_path)
            
            instance_uuid = spool['instance_uuid']
            updates = spool['updates']
            
            # Build modification arguments
            mod_args = [f'{field}:{value}' for field, value in updates.items()]
            
            # Execute with hooks off (no file lock now!)
            result = subprocess.run(
                ['task', 'rc.hooks=off', 'rc.confirmation=off', 'rc.verbose=nothing',
                 instance_uuid, 'modify'] + mod_args,
                capture_output=True, text=True, check=False
            )
            
            if result.returncode == 0:
                feedback.append(f"Instance #{spool['instance_rindex']} synced.")
            
        except Exception as e:
            # Log error, clean up bad spool
            os.remove(spool_path)
    
    # THEN: Process normal spawning, etc.
    # ...
    
    return feedback
```

---

## What Makes This Work

### 1. File Lock Timing

**Critical:** on-exit runs AFTER Taskwarrior releases the lock.

```
on-modify:  Lock HELD    → Can't modify other tasks
on-exit:    Lock RELEASED → Can modify other tasks
```

### 2. Atomic Spool File

Writing the JSON file is atomic enough for our purposes. Even if the process crashes:
- Best case: Spool processed on next command
- Worst case: Stale spool file (user can delete manually)

### 3. Single Responsibility

Each hook has ONE job:
- **on-modify:** Calculate what needs to change, write instructions
- **on-exit:** Execute instructions, clean up spool

### 4. Immediate Feedback

User sees two messages:
```
Modifying task 72 'Test'.
Template modified: rlast
Instance #1 will be synced.     ← from on-modify
Modified 1 task.
Instance #1 synced (rlast).     ← from on-exit
```

---

## Bidirectional Sync

The pattern works in BOTH directions:

### Template → Instance
```bash
task 72 mod rlast:5

# on-modify: Template rlast changed
# Spool: {updates: {rindex: "5", due: "..."}, target: instance_uuid}
# on-exit: Instance 73 updated
```

### Instance → Template
```bash
task 73 mod rindex:10

# on-modify: Instance rindex changed
# Spool: {updates: {rlast: "10"}, target: template_uuid}
# on-exit: Template 72 updated
```

---

## Edge Cases Handled

### 1. No Instance Exists
```python
if template_uuid:
    instances = query_instances(template_uuid)
    if not instances:
        # Don't write spool
        message = "No instance exists. Changes will apply when next spawns."
```

### 2. Multiple Instances (Data Corruption)
```python
if len(instances) > 1:
    # Don't write spool
    message = "ERROR: Multiple instances exist. Manual fix required."
```

### 3. Spool Read Failure
```python
try:
    spool = json.load(f)
except json.JSONDecodeError:
    # Clean up bad spool, log error
    os.remove(spool_path)
```

### 4. Modification Failure
```python
if result.returncode != 0:
    feedback.append(f"WARNING: Failed to sync instance. Manual sync needed.")
```

### 5. Stale Spool File
If on-exit doesn't run (process killed), stale spool remains:
- Next task command will process it
- Worst case: User deletes `~/.task/recurrence_propagate.json`

---

## Re-entrancy Protection

**Problem:** What if the spool modification triggers on-modify again?

**Solution:** Environment variable guard
```python
# In on-add_recurrence.py
PROPAGATING = os.environ.get('RECURRENCE_PROPAGATING', '') == '1'

def main():
    if PROPAGATING:
        # Pass through without recurrence logic
        print(json.dumps(modified))
        sys.exit(0)
    
    # Normal processing
    handler = RecurrenceHandler()
    # ...
```

Currently not used (we call with `rc.hooks=off`), but provides safety net.

---

## Performance Characteristics

### File I/O
- **Write:** Single JSON dump (~500 bytes)
- **Read:** Single JSON load
- **Lifecycle:** ~100ms typically

### Subprocess Overhead
- One extra `task modify` call per propagation
- With `rc.hooks=off` and `rc.verbose=nothing`
- Minimal overhead

### User Experience
- Two feedback messages (clear, informative)
- Feels instant (milliseconds delay)
- No noticeable performance impact

---

## Debug Logging

**Spool Write (on-modify):**
```
[2026-02-08 19:35:23] ADD/MOD: TIME MACHINE: rlast changed, will update rindex to 5
[2026-02-08 19:35:23] ADD/MOD: Calculated instance updates: {'rindex': '5', 'due': '...'}
[2026-02-08 19:35:23] ADD/MOD: Wrote propagation spool: {...}
```

**Spool Read (on-exit):**
```
[2026-02-08 19:35:23] EXIT: Processing propagation spool: instance 52c8c750-..., updates: {...}
[2026-02-08 19:35:23] EXIT: Propagation successful
```

---

## Lessons Learned

### 1. File Locks Are Real
Taskwarrior's file locking is strict and not documented. Can't be bypassed with `rc.hooks=off` or any other config option.

### 2. Hook Execution Timing Matters
Understanding WHEN each hook runs relative to the file lock is critical:
- on-add: Lock held
- on-modify: Lock held
- on-exit: Lock released ← THIS IS KEY

### 3. Indirect Communication Works
When direct modification is blocked, indirect communication (spool file) is elegant:
- Decouples calculation from execution
- Clear responsibility boundaries
- Easy to debug (can inspect spool file)

### 4. User Feedback Is Critical
Split feedback between hooks:
- on-modify: "will be synced" (future tense)
- on-exit: "synced" (past tense, confirmation)

Users understand the two-phase process intuitively.

### 5. Re-entrancy Guards Are Cheap Insurance
Even if not strictly needed (rc.hooks=off), the `PROPAGATING` guard costs nothing and prevents catastrophic cascading if something goes wrong.

---

## Testing the Spool Pattern

### Basic Test
```bash
# 1. Create template and instance
task add "Test" r:1d due:tomorrow ty:p

# 2. Enable debug
export DEBUG_RECURRENCE=1

# 3. Modify template
task 72 mod rlast:5

# 4. Check results
task 73 export | jq '.[0] | {rindex, due}'

# 5. Check debug log
grep "spool\|propagat" ~/.task/recurrence_debug.log | tail -10
```

### Verify No Stale Spool
```bash
# Should not exist (cleaned up immediately)
ls -la ~/.task/recurrence_propagate.json
# Should show: No such file or directory
```

### Force Error Handling
```bash
# Create bad spool
echo "INVALID JSON" > ~/.task/recurrence_propagate.json

# Run any task command
task list > /dev/null

# Check it was cleaned up
ls ~/.task/recurrence_propagate.json
# Should show: No such file or directory
```

---

## Comparison to Alternatives

### Alternative 1: Batch Queue System
Could use a full queue system (Redis, database, etc.)

**Pros:** 
- More robust
- Handle backlog
- Transaction support

**Cons:**
- Massive overkill
- External dependencies
- Complexity explosion

**Verdict:** Spool file is simpler and sufficient

### Alternative 2: Wait for Lock Release
Could have on-modify wait/poll for lock release

**Pros:**
- Direct execution in same hook

**Cons:**
- How to detect lock release?
- Race conditions
- Timeout handling
- Complexity

**Verdict:** on-exit hook already solves this elegantly

### Alternative 3: Post-processing Script
Could have user run separate sync script

**Pros:**
- Simple implementation

**Cons:**
- User must remember to run it
- Not transparent
- Poor UX

**Verdict:** Automatic is better

---

## Future Enhancements

### 1. Spool Queue (Multiple Operations)
Currently: Single spool file (last write wins)

Future: Queue multiple operations
```json
[
  {"target": "uuid1", "updates": {...}},
  {"target": "uuid2", "updates": {...}}
]
```

### 2. Spool Validation
Add checksums or timestamps to detect corruption:
```json
{
  "version": "2.6.2",
  "timestamp": "20260208T193523Z",
  "checksum": "sha256:...",
  "operations": [...]
}
```

### 3. Rollback Support
Keep spool file until confirmed successful:
```json
{
  "status": "pending|success|failed",
  "original_values": {...},
  "new_values": {...}
}
```

### 4. Spool Monitoring
Add command to inspect spool:
```bash
rr spool status   # Check if operations pending
rr spool clear    # Manual cleanup
rr spool history  # Show recent operations
```

---

## Conclusion

The spool file pattern solves an architectural constraint (file locking) with a simple, elegant solution (deferred execution). It demonstrates that:

1. **Understanding constraints** is more important than fighting them
2. **Hook execution timing** is a critical design consideration
3. **Indirect communication** can be cleaner than direct
4. **Simple solutions** often work better than complex ones

This pattern enabled the "time machine" feature and bidirectional sync, making the recurrence system feel seamless to users despite complex underlying mechanics.

---

**References:**
- Main documentation: `/mnt/project/DEVELOPERS.md`
- Spool implementation: `on-add_recurrence.py` lines 545-580, 815-845
- Spool processing: `on-exit_recurrence.py` lines 140-195
