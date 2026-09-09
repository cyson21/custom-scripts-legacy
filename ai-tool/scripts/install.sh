#!/usr/bin/env bash
set -e

# ==============================================================================
# ai-tool Installation Script (macOS / Linux)
# ==============================================================================

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}==> Starting ai-tool installation process...${NC}"

# 1. Check Python 3
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is not installed or not in PATH.${NC}"
    echo "Please install Python 3.9+ (e.g., via Homebrew: brew install python3) and try again."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo -e "Found Python $PYTHON_VERSION"

# 2. Check Pip
if ! command -v pip3 &> /dev/null; then
    echo -e "${RED}Error: pip3 is not installed or not in PATH.${NC}"
    echo "Please ensure pip is installed for Python 3."
    exit 1
fi

# 3. Install Python Dependencies
echo -e "${YELLOW}==> Installing required Python packages (textual, rich, pyperclip)...${NC}"
pip3 install -r requirements.txt

# 4. Check External CLI Tools
echo -e "${YELLOW}==> Checking AI CLI providers...${NC}"

CLAUDE_INSTALLED=false
GEMINI_INSTALLED=false

if command -v claude &> /dev/null; then
    echo -e "  [x] Claude Code (claude) is installed."
    CLAUDE_INSTALLED=true
else
    echo -e "  [ ] Claude Code is NOT installed."
fi

if command -v gemini &> /dev/null; then
    echo -e "  [x] Gemini CLI (gemini) is installed."
    GEMINI_INSTALLED=true
else
    echo -e "  [ ] Gemini CLI is NOT installed."
fi

if [ "$CLAUDE_INSTALLED" = false ] && [ "$GEMINI_INSTALLED" = false ]; then
    echo -e "\n${RED}Warning: Neither 'claude' nor 'gemini' CLI tools were found in your PATH.${NC}"
    echo -e "To use ai-tool, you must install at least one provider via npm:"
    echo -e "  ${GREEN}npm install -g @anthropic-ai/claude-code${NC}"
    echo -e "  ${GREEN}npm install -g @google/gemini-cli${NC}"
fi

# 5. Provide Alias Instructions
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
echo -e "\n${GREEN}==> Installation Complete!${NC}"
echo -e "To easily launch ai-tool from anywhere, add the following alias to your ~/.zshrc or ~/.bash_profile:"
echo -e "\n  ${YELLOW}alias aitool='python3 \"$DIR/ai_tool.py\"'${NC}\n"

echo -e "After adding the alias, reload your shell (e.g., 'source ~/.zshrc') and run '${GREEN}aitool${NC}'."
