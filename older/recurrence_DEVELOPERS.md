# Taskwarrior Enhanced Recurrence - Developer Guide

Technical documentation for developers, contributors, and those debugging the system.

## Architecture

### Components

1. **on-add_recurrence.py** - Template creation and validation
2. **on-exit_recurrence.py** - Instance spawning and management  
3. **recurrence.rc** - UDA definitions and configuration
4. **rr.py** - Management utility (optional)

### Hook Flow

```
User: task add "Task" r:1w due:tomorrow ty:c
  ↓
on-add hook:
  - Validates r, type, until compatibility
  - Converts task to template (status:recurring)
  - Sets rlast:0, normalizes type
  - Stores relative dates (rwait, rscheduled)
  ↓
on-exit hook:
  - Detects new template (rlast:0)
  - Creates first instance
  - Updates rlast:1
  ↓
User completes instance
  ↓
on-exit hook:
  - Detects completed instance
  - Fetches template (with caching)
  - Calculates next due date
  - Creates new instance(s) to maintain rlimit
  - Updates rlast
```

## Data Model

### Template (status:recurring)

```json
{
  "status": "recurring",
  "description": "Mow lawn",
  "type": "chained",
  "r": "P7D",
  "ranchor": "due",
  "rlast": 3,
  "rlimit": 1,
  "rend": "20251231T000000Z",
  "due": "20250601T000000Z",
  "rwait": "due-2d",
  "rscheduled": "due-1d"
}
```

### Instance (status:pending/waiting)

```json
{
  "status": "pending",
  "description": "Mow lawn",
  "rtemplate": "uuid-of-template",
  "rindex": 3,
  "due": "20250615T000000Z",
  "wait": "20250613T000000Z",
  "scheduled": "20250614T000000Z",
  "until": "20360101T000000Z",
  "tags": ["RECURRING", "chores"]
}
```

## UDA Definitions

### Core UDAs

| UDA | Type | Purpose | Example |
|-----|------|---------|---------|
| `type` | string | Recurrence type | chained, periodic |
| `r` | duration | Recurrence period | P7D, P1M, PT2H |
| `rtemplate` | string | Template UUID | abc123... |
| `rindex` | numeric | Instance number | 1, 2, 3... |
| `rlast` | numeric | Last spawned index | 5 |
| `rlimit` | numeric | Max pending instances | 3 (default: 1) |
| `ranchor` | string | Anchor field | due, scheduled |
| `rend` | date | Stop spawning after | 2025-12-31 |
| `rwait` | string | Relative wait | due-7d |
| `rscheduled` | string | Relative scheduled | due-2d |

### Special Fields

**`recur`** - Intentionally NOT used in instances (causes status:recurring)  
**`+RECURRING`** - Virtual tag for filtering instances  
**`until`** - Periodic: from template; Chained: 10yr default

## Key Algorithms

### Date Calculation (Periodic)

```python
def calculate_periodic_due(template, index):
    """
    Due date for periodic tasks is:
    template.due + (index × recurrence_period)
    """
    template_due = parse_date(template['due'])
    period = parse_duration(template['r'])
    return template_due + (period * index)
```

### Date Calculation (Chained)

```python
def calculate_chained_due(completion_time, template):
    """
    Due date for chained tasks is:
    completion_time + recurrence_period
    """
    period = parse_duration(template['r'])
    return completion_time + period
```

### rlimit Pile-Up (Periodic)

```python
def spawn_to_rlimit(template, start_index):
    """
    Maintain rlimit pending instances
    """
    existing = count_pending_instances(template['uuid'])
    rlimit = int(template.get('rlimit', 1))
    to_create = rlimit - existing
    
    for i in range(to_create):
        create_instance(template, start_index + i)
```

## Hook Implementation Details

### on-add_recurrence.py

**Purpose:** Template creation and validation

**Key Functions:**
- `normalize_type()` - Handle abbreviations (c→chained, p→periodic)
- `create_template()` - Convert task to template
- `parse_relative_date()` - Convert absolute to relative dates
- `handle_template_modification()` - Allow template edits

**Validations:**
- Block `until` on chained tasks
- Require `r` field for templates
- Normalize type before Taskwarrior validates

### on-exit_recurrence.py

**Purpose:** Instance spawning and management

**Key Functions:**
- `get_template()` - Fetch with caching
- `create_instance()` - Build task command
- `create_instances_for_template()` - Handle rlimit
- `count_pending_instances()` - Query existing instances
- `process_tasks()` - Main loop

**Event Handling:**
1. **New template** (rlast:0) → Create first instance
2. **Completed instance** → Spawn to maintain rlimit
3. **Deleted chained instance** → Spawn next (user skipping)
4. **Deleted periodic instance** → Do nothing (time-based)
5. **Deleted template** → Ignore (don't spawn)

### Template Caching

Avoids repeated fetches during bulk operations:

```python
class RecurrenceSpawner:
    def __init__(self):
        self._template_cache = {}
    
    def get_template(self, uuid):
        if uuid in self._template_cache:
            return self._template_cache[uuid]
        
        template = fetch_from_taskwarrior(uuid)
        self._template_cache[uuid] = template
        return template
```

Cache is per-hook execution, discarded after.

## Debugging

### Enable Debug Mode

```bash
export DEBUG_RECURRENCE=1
# or in recurrence.rc:
export.DEBUG_RECURRENCE=1
```

### Debug Log Location

`~/.task/recurrence_debug.log`

### Debug Output Format

```
[2026-01-10 12:00:00] ADD/MOD: Creating template: Mow lawn
[2026-01-10 12:00:00] ADD/MOD:   Type: chained, r=P7D, rlimit=1
[2026-01-10 12:00:00] EXIT: Found new template: Mow lawn
[2026-01-10 12:00:00] EXIT: Creating instance 1 from abc123
[2026-01-10 12:00:00] EXIT: Instance 1 created successfully with ID 42
```

### Common Debug Patterns

**No instance created:**
```
EXIT: Found new template: X
EXIT: Skipping old template (age=120s): X
```
→ Template is too old (>60s), safety check triggered

**Wrong due date:**
```
EXIT: Periodic spawn: existing=0, rlimit=3, to_create=3
EXIT: Creating instance 1...
```
→ Check calculated anchor_date in create_instance

**Infinite spawn:**
```
EXIT: Template 123 has 0 pending instances
EXIT: Creating instance 2...
EXIT: Template 123 has 0 pending instances
```
→ Instances not being counted (check status)

## Testing

### Unit Test Pattern

```bash
# Clean slate
task rc.data.location=/tmp/test-tw init
cd /tmp/test-tw

# Install hooks
cp hooks to .task/hooks/
cp recurrence.rc .task/

# Test case
export DEBUG_RECURRENCE=1
task add "Test" r:1d due:tomorrow ty:c

# Verify
task rtemplates  # Should show 1 template
task list        # Should show 1 instance
tail recurrence_debug.log
```

### Integration Tests

See `tests/` directory for automated tests:
- `test_chained.sh` - Chained recurrence scenarios
- `test_periodic.sh` - Periodic recurrence scenarios
- `test_edge_cases.sh` - Corner cases and error conditions

### Manual Test Checklist

- [ ] Create chained task, complete, verify next instance
- [ ] Create periodic task, complete, verify due date
- [ ] Test rlimit pile-up (complete 1, should spawn multiple)
- [ ] Test `until` on chained (should error)
- [ ] Test `rend` stops spawning
- [ ] Test type abbreviations (c, ch, p, pe)
- [ ] Test relative dates (wait:due-7d)
- [ ] Test template deletion stops spawning
- [ ] Test bulk operations (task 1-10 delete)
- [ ] Test GC disabled (no automatic deletions)

## Known Limitations

### No Native R Indicator

Instances don't show R in reports because we can't use `recur:` field (causes status:recurring).

**Workaround:** Use `+RECURRING` tag:
```bash
task +RECURRING list
```

### No Retroactive Instance Creation

If you complete instance #3 before #2, instance #4 is spawned (not #2).

**Design decision:** Keep it simple, no backfill.

### rlimit Only on Completion

Pile-up only happens when you complete instances, not automatically by time.

**Future:** Could add time-based spawning with cron/on-launch hook.

### Bulk Deletion Edge Cases

If you delete instances out of order in bulk, highest index wins.

**Mitigation:** Sort by index before processing (implemented).

## Performance Considerations

### Template Caching

Bulk operations fetch each template once per hook execution.

**Impact:** ~10ms per template fetch → saved on repeated access

### Subprocess Overhead

Each instance creation spawns taskwarrior subprocess.

**Impact:** ~50-100ms per instance → acceptable for typical use

**Potential optimization:** Batch creates with import/export

### GC Disabled

`gc=off` prevents automatic cleanup of completed tasks.

**Impact:** Database grows over time

**Mitigation:** Manual `task gc` when needed, or use higher threshold

## Contributing

### Code Style

- Python 3.6+
- 4-space indentation
- Docstrings for all functions
- Type hints encouraged
- Keep lines < 100 chars

### Testing Requirements

- Test on both chained and periodic
- Test with debug mode enabled
- Verify no output corruption
- Check debug log for errors

### Submitting Changes

1. Test manually with debug enabled
2. Run integration tests (if available)
3. Update changelog in file headers
4. Update version numbers consistently
5. Document breaking changes

## File Structure

```
.
├── on-add_recurrence.py       # Template creation (symlink to on-modify)
├── on-exit_recurrence.py      # Instance spawning
├── recurrence.rc              # Configuration
├── rr.py                      # Management tool
├── README.md                  # User documentation
├── DEVELOPERS.md             # This file
└── tests/                    # Integration tests
    ├── test_chained.sh
    ├── test_periodic.sh
    └── test_edge_cases.sh
```

## Version History

### 0.3.3 (2026-01-10)
- CRITICAL: Removed recur field from instances
- Fixed status:recurring issue

### 0.3.2 (2026-01-10)
- Fixed new template spawning (only 1 instance)
- Fixed rlimit pile-up logic

### 0.3.1 (2026-01-10)
- Fixed rlimit counting
- Fixed until handling per type
- Added +RECURRING tag

### 0.3.0 (2026-01-09)
- Added rlimit UDA
- Removed type values restriction
- Added template caching
- Performance improvements

### 0.2.0 (2026-01-08)
- Fixed GC infinite loop
- Fixed JSON parsing
- Added task IDs in feedback

### 0.1.0 (2026-01-06)
- Initial implementation

## Resources

- [Taskwarrior Recurrence RFC](https://djmitche.github.io/taskwarrior/rfcs/recurrence.html)
- [Taskwarrior Hooks Documentation](https://taskwarrior.org/docs/hooks.html)
- [Original Recurrence Code](https://github.com/GothenburgBitFactory/taskwarrior/blob/develop/src/recur.cpp)

## Support

- File issues on GitHub
- Join Taskwarrior community discussions
- Share your debugging experiences

---

**Happy coding!** 🚀
