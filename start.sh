#!/bin/bash
# Launcher for Claude Desktop — sets up Resolve scripting environment
export RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
export RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
export PYTHONPATH="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/:$PYTHONPATH"

exec /Users/guycochranclawdbot/resolve-mcp-server/.venv/bin/python3 /Users/guycochranclawdbot/resolve-mcp-server/src/server.py 2>/dev/null
