# DaVinci Resolve MCP Server

Control DaVinci Resolve with AI via the Model Context Protocol. Edit video, color grade, render, and analyze frames — all through natural language.

**45 tools** across 11 categories: connection, projects, timelines, media, editing, color grading, markers, titles, rendering, Fusion, and AI vision.

## Features

- **Edit by voice** — "Add the b-roll clip to track 2", "Zoom in to 150%", "Apply the Kodak film look"
- **Color grade** — Apply LUTs, create color versions, export grades
- **Render anywhere** — Quick export for YouTube, TikTok, Vimeo with one command
- **AI vision** — "What's in this shot?", "Is there a person at the podium?", "How many people are visible?"
- **Works with Claude Desktop, claude.ai, and Claude Mobile** via stdio or HTTP transport

## Quick Start

### 1. Install dependencies

```bash
cd ~/resolve-mcp-server
pip install -r requirements.txt
```

### 2. Configure Claude Desktop

Add to `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "resolve": {
      "command": "/Users/guycochranclawdbot/resolve-mcp-server/start.sh",
      "env": {
        "MOONDREAM_API_KEY": "your_key_here"
      }
    }
  }
}
```

### 3. Make sure Resolve is running

The server connects to a running DaVinci Resolve instance on the same machine.

### 4. Talk to your editor

> "What project am I working on?"
> "Show me all the timelines"
> "Apply the Kodak 2383 film look to the current clip"
> "Export this timeline for YouTube"
> "What's visible in this frame?"

## Remote Access (HTTP Mode)

For controlling Resolve from your phone or claude.ai:

```bash
TRANSPORT=http PORT=3001 MOONDREAM_API_KEY=your_key python src/server.py
```

Pair with a Cloudflare tunnel for worldwide access:

```bash
cloudflared tunnel --url http://localhost:3001
```

## Vision / Moondream

The server integrates with [Moondream](https://moondream.ai) for AI-powered frame analysis:

- `resolve_describe_frame` — Natural language scene description
- `resolve_detect_in_frame` — Object detection with bounding boxes
- `resolve_ask_about_frame` — Visual Q&A ("How many people?", "What color is the background?")

Get a free API key at [console.moondream.ai](https://console.moondream.ai).

## Requirements

- DaVinci Resolve (Free or Studio) running on the same machine
- Python 3.10+
- `mcp[cli]`, `httpx`, `Pillow`

## Project Structure

```
src/
├── server.py                    # Main entry point
├── services/
│   ├── resolve_connection.py    # Resolve API connection management
│   └── moondream.py             # Moondream vision API client
└── tools/
    ├── connection.py            # Status, page navigation
    ├── project.py               # Project management
    ├── timeline.py              # Timeline operations
    ├── media.py                 # Media pool management
    ├── editing.py               # Clip properties, transform
    ├── color.py                 # LUTs, color versions
    ├── markers.py               # Timeline markers
    ├── titles.py                # Fusion titles
    ├── render.py                # Rendering & export
    ├── fusion.py                # Fusion compositions
    └── vision.py                # AI frame analysis
```

## License

MIT
