#!/bin/bash
# ============================================================================
# Python Bytecode Cache Nuclear Obliteration Script
# ============================================================================
# 
# This script permanently disables Python's bytecode caching system to ensure
# that code changes are ALWAYS reflected immediately when testing hooks.
#
# Run once: ./obliterate-pycache.sh
# Then never worry about stale bytecode again.
#
# ============================================================================

set -e  # Exit on any error

echo "============================================================================"
echo "Python Bytecode Cache Nuclear Obliteration"
echo "============================================================================"
echo ""

# ============================================================================
# 1. Clean existing caches NOW
# ============================================================================

echo "[1/5] Destroying existing bytecode caches..."

# Find and destroy all pycache directories
destroyed_dirs=$(find ~/.task -type d -name "__pycache__" 2>/dev/null | wc -l)
find ~/.task -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# Find and destroy all .pyc files
destroyed_pyc=$(find ~/.task -type f -name "*.pyc" 2>/dev/null | wc -l)
find ~/.task -type f -name "*.pyc" -delete 2>/dev/null || true

# Find and destroy all .pyo files (optimized bytecode)
destroyed_pyo=$(find ~/.task -type f -name "*.pyo" 2>/dev/null | wc -l)
find ~/.task -type f -name "*.pyo" -delete 2>/dev/null || true

echo "   Destroyed: $destroyed_dirs __pycache__ directories"
echo "   Destroyed: $destroyed_pyc .pyc files"
echo "   Destroyed: $destroyed_pyo .pyo files"
echo "   ✓ Existing caches obliterated"
echo ""

# ============================================================================
# 2. Create Python startup config
# ============================================================================

echo "[2/5] Creating Python startup configuration..."

# Create config directory
mkdir -p ~/.config/python

# Create pythonrc that disables bytecode
cat > ~/.config/python/pythonrc.py << 'PYTHONRC_EOF'
# Python startup configuration
# Disables bytecode caching system-wide
import sys
sys.dont_write_bytecode = True
PYTHONRC_EOF

echo "   ✓ Created ~/.config/python/pythonrc.py"
echo ""

# ============================================================================
# 3. Update bashrc with permanent settings
# ============================================================================

echo "[3/5] Updating ~/.bashrc with permanent settings..."

# Check if settings already exist
if grep -q "PYTHONDONTWRITEBYTECODE" ~/.bashrc 2>/dev/null; then
    echo "   ! Settings already exist in ~/.bashrc"
    echo "   Would you like to update them? (yes/no)"
    read -r response
    if [ "$response" = "yes" ]; then
        # Remove old settings
        sed -i '/# Python: NO BYTECODE CACHE EVER/,/^$/d' ~/.bashrc
        echo "   ✓ Removed old settings"
    else
        echo "   ✓ Keeping existing settings"
        SKIP_BASHRC=1
    fi
fi

if [ "$SKIP_BASHRC" != "1" ]; then
    # Append new settings to bashrc
    cat >> ~/.bashrc << 'BASHRC_EOF'

# ============================================================================
# Python: NO BYTECODE CACHE EVER
# ============================================================================
# Prevents Python from creating __pycache__ directories and .pyc files
# This ensures code changes are ALWAYS reflected immediately during testing
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX=/dev/null
export PYTHONSTARTUP=~/.config/python/pythonrc.py

# Quick cleanup alias
alias kill-pycache='find ~/.task -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; find ~/.task -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete 2>/dev/null; echo "Pycache obliterated."'

BASHRC_EOF
    echo "   ✓ Updated ~/.bashrc"
fi

echo ""

# ============================================================================
# 4. Create standalone cleanup script
# ============================================================================

echo "[4/5] Creating standalone cleanup script..."

cat > ~/kill-pycache.sh << 'CLEANUP_EOF'
#!/bin/bash
# ============================================================================
# Python Bytecode Cache Cleanup Script
# ============================================================================
# Run this before testing to ensure no stale bytecode exists
# Usage: ~/kill-pycache.sh

echo "Obliterating Python bytecode caches..."

# Destroy all pycache directories
dirs=$(find ~/.task -type d -name "__pycache__" 2>/dev/null | wc -l)
find ~/.task -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

# Destroy all .pyc files
pyc=$(find ~/.task -type f -name "*.pyc" 2>/dev/null | wc -l)
find ~/.task -type f -name "*.pyc" -delete 2>/dev/null

# Destroy all .pyo files
pyo=$(find ~/.task -type f -name "*.pyo" 2>/dev/null | wc -l)
find ~/.task -type f -name "*.pyo" -delete 2>/dev/null

echo "✓ Obliterated: $dirs __pycache__ directories, $pyc .pyc files, $pyo .pyo files"

# Verify
remaining=$(find ~/.task -type d -name "__pycache__" -o -name "*.pyc" -o -name "*.pyo" 2>/dev/null | wc -l)
if [ "$remaining" -eq 0 ]; then
    echo "✓ All clear - no bytecode caches remain"
else
    echo "⚠ Warning: $remaining cache items still exist"
fi
CLEANUP_EOF

chmod +x ~/kill-pycache.sh
echo "   ✓ Created ~/kill-pycache.sh"
echo ""

# ============================================================================
# 5. Apply settings to current shell
# ============================================================================

echo "[5/5] Applying settings to current shell..."

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX=/dev/null
export PYTHONSTARTUP=~/.config/python/pythonrc.py

echo "   ✓ Environment variables set for this session"
echo ""

# ============================================================================
# Summary and verification
# ============================================================================

echo "============================================================================"
echo "Setup Complete!"
echo "============================================================================"
echo ""
echo "What was done:"
echo "  1. Destroyed all existing bytecode caches"
echo "  2. Created ~/.config/python/pythonrc.py (disables bytecode at Python level)"
echo "  3. Updated ~/.bashrc with permanent environment variables"
echo "  4. Created ~/kill-pycache.sh cleanup script"
echo "  5. Applied settings to current shell"
echo ""
echo "Verification:"
echo "  PYTHONDONTWRITEBYTECODE = $PYTHONDONTWRITEBYTECODE"
echo "  PYTHONPYCACHEPREFIX     = $PYTHONPYCACHEPREFIX"
echo "  PYTHONSTARTUP           = $PYTHONSTARTUP"
echo ""
echo "Commands available:"
echo "  kill-pycache        - Quick cleanup (after you reload bashrc)"
echo "  ~/kill-pycache.sh   - Standalone cleanup script"
echo ""
echo "Next steps:"
echo "  1. Reload your shell: source ~/.bashrc"
echo "  2. Copy your hook files to ~/.task/hooks/"
echo "  3. Test: task add \"Test\" r:1d due:tomorrow"
echo "  4. Verify no __pycache__ appears: ls ~/.task/hooks/__pycache__"
echo ""
echo "If you ever see __pycache__ again, run: kill-pycache"
echo ""
echo "============================================================================"
echo "Python bytecode caching is now PERMANENTLY DISABLED."
echo "Your hooks will ALWAYS use the latest code."
echo "============================================================================"
