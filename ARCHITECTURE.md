# Architecture — DaVinci Resolve MCP Server

## How It All Connects

```
                          THE INTERNET
                               |
                               v
                    +-----------------------+
                    |   Cloudflare Tunnel   |
                    |  resolve.cochran.cloud|
                    +-----------+-----------+
                                |
                                | HTTPS -> localhost:3001
                                v
+------------------+   +--------------------------+   +-------------------------+
|                  |   |                          |   |                         |
|  Claude Mobile   |-->|  Resolve MCP Server      |-->|  DaVinci Resolve        |
|  (Phone/Tablet)  |   |  (Python + FastMCP)      |   |  Studio 20.3.1          |
|                  |   |                          |   |                         |
+------------------+   |  Transport: HTTP :3001   |   |  Scripting API          |
                       |                          |   |  (fusionscript.so)      |
+------------------+   |  53 MCP Tools:           |   |                         |
|                  |   |  - Connection (4)        |   |  Project Manager        |
|  Claude Desktop  |-->|  - Project (6)           |-->|  Media Pool             |
|  (This Mac)     |   |  - Timeline (8)          |   |  Timelines              |
|                  |   |  - Media (5)             |   |  Color Page             |
+------------------+   |  - Editing (7)           |   |  Fusion                 |
       |               |  - Color (6)             |   |  Deliver                |
       | stdio         |  - Markers (3)           |   |                         |
       | (JSON-RPC)    |  - Titles (2)            |   +-------------------------+
                       |  - Render (6)            |
                       |  - Fusion (3)            |
                       |  - Vision (3)            |
                       |                          |
                       +------------+-------------+
                                    |
                                    | HTTPS API calls
                                    v
                       +-------------------------+
                       |                         |
                       |  Moondream AI           |
                       |  api.moondream.ai/v1    |
                       |                         |
                       |  - /caption             |
                       |  - /detect              |
                       |  - /query               |
                       |  - /point               |
                       |                         |
                       +-------------------------+
```

## Data Flow

### Local (Claude Desktop -> Resolve)
```
Claude Desktop
    |
    | stdin/stdout (JSON-RPC over stdio)
    v
start.sh
    |
    | Sets RESOLVE_SCRIPT_API, RESOLVE_SCRIPT_LIB, PYTHONPATH
    v
.venv/bin/python3 src/server.py
    |
    | import DaVinciResolveScript (fusionscript.so)
    v
Resolve Scripting API
    |
    | Direct Python method calls
    v
DaVinci Resolve (running on same machine)
```

### Remote (Phone -> Cloudflare -> Resolve)
```
Phone (Claude Mobile)
    |
    | HTTPS POST to resolve.cochran.cloud/mcp
    v
Cloudflare Edge (Seattle)
    |
    | QUIC tunnel (4 connections)
    v
cloudflared (localhost)
    |
    | HTTP proxy -> localhost:3001
    v
Resolve MCP Server (Uvicorn, streamable-http)
    |
    | Python scripting API
    v
DaVinci Resolve
```

### AI Vision Pipeline
```
DaVinci Resolve
    |
    | ExportCurrentFrameAsStill() -> 6MB PNG
    v
Pillow (PIL)
    |
    | Convert to JPEG, cap at 1920px -> ~250KB
    v
Base64 encode -> data:image/jpeg;base64,...
    |
    | HTTPS POST with X-Moondream-Auth header
    v
Moondream API (api.moondream.ai/v1)
    |
    | Returns JSON: caption, detections, answer, or points
    v
Claude formats response for user
```

### Clip Replacement (Three-Point Overwrite Edit)
```
Claude: "Replace the b-roll at 01:00:13:22 with SOUTH_POLE_TAKE_OFF"
    |
    v
resolve_replace_clip(track_index=2, clip_index=2, new_clip_name="A663C012_SOUTH_POLE_TAKE_OFF.mov")
    |
    | 1. Get old clip's record position (start/end frames)
    | 2. Search media pool recursively for replacement clip
    | 3. Calculate source end = source_start + original_duration
    |
    v
timeline.DeleteClips([old_clip], False)   <-- no ripple, keeps gap
    |
    v
pool.AppendToTimeline([{
    "mediaPoolItem": new_mp_item,
    "trackIndex": 2,
    "recordFrame": 86734,          <-- exact same position
    "startFrame": 0,
    "endFrame": 120,               <-- matches original duration
    "mediaType": 1                 <-- video only (preserves audio)
}])
    |
    v
New clip sits at same timeline position with same duration
```

## Network Map

```
+------------------------------------------------------------------+
|  Your Mac (Edit Station)                                         |
|                                                                  |
|  +---------------------------+  +-----------------------------+  |
|  | DaVinci Resolve Studio    |  | Resolve MCP Server          |  |
|  | (GUI + Scripting API)     |<-| Python 3.14 / FastMCP       |  |
|  |                           |  | Port 3001 (HTTP)            |  |
|  +---------------------------+  | or stdio (Claude Desktop)   |  |
|                                 +-------------+---------------+  |
|                                               |                  |
|  +---------------------------+                |                  |
|  | ATEM MCP Server           |  +-------------+---------------+  |
|  | Node.js                   |  | cloudflared                 |  |
|  | Port 3000 (HTTP)          |  | Tunnel: 0226f8c4-...       |  |
|  +-------------+-------------+  +-------------+---------------+  |
|                |                              |                  |
+------------------------------------------------------------------+
                 |                              |
                 |   Cloudflare Tunnel (QUIC)   |
                 |                              |
         +-------+------------------------------+-------+
         |              Cloudflare Edge                  |
         |                                               |
         |  atem.cochran.cloud    -> localhost:3000       |
         |  bmatem.cochran.cloud  -> localhost:3000       |
         |  resolve.cochran.cloud -> localhost:3001       |
         |                                               |
         +-----------------------------------------------+
                             |
                          HTTPS
                             |
                    +--------+--------+
                    |  Claude Mobile  |
                    |  (Anywhere)     |
                    +-----------------+
```

## File Structure

```
~/resolve-mcp-server/
|
+-- src/
|   +-- server.py                  # Entry point, creates FastMCP, registers tools
|   |                              # Supports stdio + streamable-http transport
|   |
|   +-- services/
|   |   +-- resolve_connection.py  # Loads fusionscript.so, manages Resolve connection
|   |   |                          # Exports: get_resolve(), get_project(), get_timeline()
|   |   |
|   |   +-- moondream.py           # Moondream API client, image prep (PNG->JPEG)
|   |                              # Exports: caption(), detect(), query(), point()
|   |
|   +-- tools/                     # Each file exports register(mcp: FastMCP)
|       +-- connection.py          # resolve_get_status, resolve_open_page, ...
|       +-- project.py             # resolve_list_projects, resolve_load_project, ...
|       +-- timeline.py            # resolve_list_timelines, resolve_get_playhead, ...
|       +-- media.py               # resolve_import_media, resolve_append_to_timeline, ...
|       +-- editing.py             # resolve_set_clip_transform, resolve_replace_clip, resolve_delete_clip, ...
|       +-- color.py               # resolve_apply_lut, resolve_create_color_version, ...
|       +-- markers.py             # resolve_add_marker, resolve_get_markers, ...
|       +-- titles.py              # resolve_insert_title, resolve_modify_title_text
|       +-- render.py              # resolve_quick_export, resolve_start_render, ...
|       +-- fusion.py              # resolve_get_fusion_comps, ...
|       +-- vision.py              # resolve_describe_frame, resolve_detect_in_frame, ...
|
+-- .venv/                         # Python 3.14 virtualenv (Homebrew)
+-- .env                           # MOONDREAM_API_KEY (not committed)
+-- .env.example                   # Template for .env
+-- start.sh                       # Launcher for Claude Desktop (sets env vars)
+-- requirements.txt               # mcp[cli], httpx, Pillow
+-- CLAUDE.md                      # Instructions for Claude when using this server
+-- README.md                      # Human documentation
+-- ARCHITECTURE.md                # This file
```

## Ports & Services

| Service              | Port | Protocol         | URL                           |
|----------------------|------|------------------|-------------------------------|
| Resolve MCP (HTTP)   | 3001 | streamable-http  | http://localhost:3001/mcp     |
| Resolve MCP (stdio)  | —    | JSON-RPC stdio   | via start.sh                  |
| ATEM MCP             | 3000 | streamable-http  | http://localhost:3000         |
| Cloudflare Metrics   | 20241| HTTP             | http://localhost:20241/metrics|
| Moondream API        | 443  | HTTPS            | api.moondream.ai/v1          |

## Tunnel Hostnames

| Hostname                  | Routes To        | Service          |
|---------------------------|------------------|------------------|
| atem.cochran.cloud        | localhost:3000   | ATEM MCP Server  |
| bmatem.cochran.cloud      | localhost:3000   | ATEM MCP Server  |
| resolve.cochran.cloud     | localhost:3001   | Resolve MCP Server|
