# Taskwarrior Enhanced Recurrence

A powerful hook-based recurrence system for Taskwarrior that implements **chained** and **periodic** recurring tasks.

**Version:** 0.3.3  
**Status:** Stable ✅

## Why Enhanced Recurrence?

Built-in Taskwarrior recurrence has limitations:
- Only supports periodic (time-based) recurrence
- Mask system grows unbounded
- Doesn't handle completion-based recurrence

This hook system adds:
- ✅ **Chained recurrence** - "Mow lawn 7 days after completion"
- ✅ **Periodic recurrence** - "Pay rent on 1st of every month"
- ✅ **Better date handling** - Relative dates that actually work
- ✅ **Clean indexing** - No mask growth issues
- ✅ **Type abbreviations** - `type:chain` can be abbreviated to `ty:c` - `ty:p` is the default

Based on the [Taskwarrior Recurrence RFC](https://djmitche.github.io/taskwarrior/rfcs/recurrence.html).

## Quick Start

### Installation

```bash
cd ~/.task/hooks

# Install hooks (get from releases or repository)
chmod +x on-add_recurrence.py on-exit_recurrence.py

# Create symlink
ln -s on-add_recurrence.py on-modify_recurrence.py

# Install configuration
cp recurrence.rc ~/.task/
```

Add to your `~/.taskrc`:
```ini
include ~/.task/hooks/recurrence/recurrence.rc
```

Verify installation:
```bash
task show | grep "uda.type"
```

### Basic Usage

**Chained (completion-based):**
```bash
task add "Mow lawn" ty:c r:7d due:tomorrow
# Next instance due 7 days after you complete current one
```

**Periodic (time-based):**
```bash
task add "Pay rent" ty:p r:1mo due:eom
# Default type, so ty:p is optional
task add "Pay rent" r:1mo due:eom
```

**With relative dates:**
```bash
task add "Bill" r:1mo due:eom wait:due-7d
# Appears 7 days before due date
```

## Common Patterns

### Weekly Tasks
```bash
# Exercise routine (after completion)
task add "Gym workout" ty:c r:3d due:tomorrow +health

# Team meeting (fixed schedule)
task add "Standup" r:1w due:monday scheduled:9am +work
```

### Monthly Tasks
```bash
# Bills (with reminders)
task add "Credit card" r:1mo due:15th wait:due-7d priority:H +finance

# Reviews (completion-based)
task add "Project review" ty:c r:1mo due:eom +admin
```

### Limited Duration
```bash
# Summer project (stops after August)
task add "Beach cleanup" r:1w due:2025-06-01 rend:2025-08-31 +volunteer
```

### Pile-Up Control
```bash
# Keep 3 pending rent reminders
task add "Rent" r:1mo due:eom rlimit:3 +bills
# If you don't complete them, they pile up to rlimit
```

## Key Concepts

### Chained vs Periodic

**Chained (`ty:c`)**
- Next task relative to completion time
- Use for: Exercise, chores, habits
- Due date = completion_time + period

**Periodic (`ty:p` or default)**
- Fixed schedule from template
- Use for: Bills, meetings, appointments  
- Due date = template_due + (index × period)

### Date Fields

**`due:`** - When task is due  
**`wait:`** - When task becomes visible  
**`scheduled:`** - When to start working  
**`until:`** - When instances expire (periodic only)  
**`rend:`** - When to stop creating new instances

### Relative Dates

```bash
wait:due-7d        # 7 days before due
scheduled:due-2d   # 2 days before due
wait:scheduled-1h  # 1 hour before scheduled
```

## Managing Recurrence

### View Templates
```bash
task rtemplates              # All templates
task recurring               # Same thing
```

### View Instances
```bash
task +RECURRING list         # All recurring instances
task rtemplate:UUID list     # Instances of specific template
```

### Modify Recurrence
```bash
task UUID modify r:14d       # Change period
task UUID modify ty:c        # Change type
task UUID modify rend:eom    # Add end date
task UUID modify rlimit:5    # Change pile-up limit
```

### Stop Recurrence
```bash
# Delete template (stops creating new instances)
task UUID delete

# Or use rr.py tool
rr stop UUID
```

## Companion Tool: rr.py

Enhanced management commands:

```bash
rr templates           # Pretty template list
rr template UUID       # Show template + instances
rr stats               # Statistics
rr check               # Validate data
rr stop UUID           # Stop recurrence cleanly
```

Install:
```bash
chmod +x rr.py
sudo cp rr.py /usr/local/bin/rr
```

## Type Abbreviations

All equivalent:
```bash
ty:c, ty:ch, ty:chai, ty:chain, ty:chained, type:chained
ty:p, ty:pe, ty:per, ty:periodic, type:periodic
```

## Debug Mode

```bash
export DEBUG_RECURRENCE=1
task add "Test" r:1d due:tomorrow
tail -f ~/.task/recurrence_debug.log
```

## Troubleshooting

**Hooks not running?**
```bash
task show | grep hooks        # Should show hooks=1
ls -la ~/.task/hooks/on-*     # Should be executable
```

**No instances created?**
```bash
task rtemplates               # Check template exists
export DEBUG_RECURRENCE=1     # Enable logging
task list                     # Trigger hook
cat ~/.task/recurrence_debug.log
```

**Wrong due dates?**
- Chained: Check completion time in debug log
- Periodic: Verify template's due date is correct

## Examples

```bash
# Daily habits (complete whenever, next due 1 day later)
task add "Meditate" ty:c r:1d due:today +habits

# Weekly review (every Friday)
task add "Week review" r:1w due:friday scheduled:due-1h +review

# Monthly bills with 7-day warning
task add "Rent" r:1mo due:1st wait:due-7d priority:H +bills

# Quarterly reports (limited to this year)
task add "Q report" r:3mo due:2025-03-31 rend:2025-12-31 +work

# Groceries (pile up to 3 if you don't do them)
task add "Groceries" ty:c r:3d due:saturday rlimit:3 +shopping
```

## What's Next?

- See [DEVELOPERS.md](DEVELOPERS.md) for technical details
- Check releases for updates
- Share your recurring task patterns!

## License

MIT / Public Domain - use freely!

## Credits

- [Taskwarrior Recurrence RFC](https://djmitche.github.io/taskwarrior/rfcs/recurrence.html)
- Community feedback and testing
- Built with Claude's help! 🤖

---

**Enjoy better recurring tasks!** 🎯
