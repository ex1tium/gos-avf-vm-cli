#!/usr/bin/env bash
#
# GVM Bootstrap Script
#
# This script prepares the environment for running the GVM tool.
# Run this once after cloning the repository.
#
# Usage:
#   chmod +x bootstrap.sh && ./bootstrap.sh
#
# Or in one command:
#   bash bootstrap.sh
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Determine the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "GVM Bootstrap - GrapheneOS Debian VM Setup Tool"
echo "================================================"
echo ""

# Track if any issues were found
ISSUES_FOUND=0

# Check 1: Python version
echo -n "Checking Python version... "
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PYTHON_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
    PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')

    if [ "$PYTHON_MAJOR" -gt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -ge 11 ]; }; then
        echo -e "${GREEN}OK${NC} (Python $PYTHON_VERSION)"
    else
        echo -e "${RED}FAILED${NC}"
        echo "  Error: Python 3.11+ required (found $PYTHON_VERSION)"
        echo "  The tool uses tomllib which is only available in Python 3.11+"
        ISSUES_FOUND=1
    fi
else
    echo -e "${RED}FAILED${NC}"
    echo "  Error: python3 not found in PATH"
    echo "  Install Python 3.11+ to continue"
    ISSUES_FOUND=1
fi

# Check 2: tomllib availability
echo -n "Checking tomllib module... "
if python3 -c "import tomllib" 2>/dev/null; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}FAILED${NC}"
    echo "  Error: tomllib module not available"
    echo "  This is built into Python 3.11+. Upgrade Python to continue."
    ISSUES_FOUND=1
fi

# Check 3: curses availability (for TUI)
echo -n "Checking curses module... "
if python3 -c "import curses" 2>/dev/null; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${YELLOW}WARNING${NC}"
    echo "  Warning: curses module not available"
    echo "  TUI mode will not work, but CLI commands will still function"
    echo "  To fix: sudo apt install libncurses-dev python3-curses"
fi

# Check 4: Make gvm executable
echo -n "Setting executable permissions... "
if [ -f "${SCRIPT_DIR}/gvm" ]; then
    chmod +x "${SCRIPT_DIR}/gvm"
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}FAILED${NC}"
    echo "  Error: gvm script not found at ${SCRIPT_DIR}/gvm"
    ISSUES_FOUND=1
fi

# Check 5: Verify the module can be imported
echo -n "Verifying GVM module... "
export PYTHONPATH="${SCRIPT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
if python3 -c "from gvm.cli import main" 2>/dev/null; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}FAILED${NC}"
    echo "  Error: Cannot import GVM module"
    echo "  Check that src/gvm/ directory exists and contains valid Python files"
    ISSUES_FOUND=1
fi

echo ""
echo "================================================"

if [ "$ISSUES_FOUND" -eq 0 ]; then
    echo -e "${GREEN}Bootstrap complete!${NC}"
    echo ""
    echo "You can now run:"
    echo "  ./gvm --help           Show help"
    echo "  ./gvm setup            Interactive TUI setup"
    echo "  ./gvm setup --all      Non-interactive full setup"
    echo ""
    exit 0
else
    echo -e "${RED}Bootstrap failed with errors.${NC}"
    echo "Please fix the issues above and run bootstrap.sh again."
    exit 1
fi
