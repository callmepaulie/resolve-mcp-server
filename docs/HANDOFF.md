# Hand-off — stdio bugfix + motion classifier

This branch (`feature/motion-classifier`) bundles two independent changes against `main`:

1. **`fix/stdio-transport`** — bugfix for a regression that broke MCP stdio transport
2. **`feature/motion-classifier`** — new `resolve_classify_motion` tool: optical-flow camera-motion classifier (static / push / pull / pan / tilt / roll)

The two are packaged together for review convenience but are conceptually independent. Each commit is self-contained and the bugfix can be cherry-picked separately if you want to ship it on its own. A standalone branch `fix/stdio-transport` is also available with just commit 1.

---

## Branch layout

```
origin/main (upstream)
  |
  +-- fix/stdio-transport
  |     97ed93a  Fix stdio transport — remove sys.stdout = sys.stderr redirect
  |
  +-- feature/motion-classifier
        97ed93a  Fix stdio transport — remove sys.stdout = sys.stderr redirect
        14fce71  Add resolve_classify_motion tool — optical-flow camera-motion classifier
        <docs commit>  Update README / ARCHITECTURE / CLAUDE / requirements; add HANDOFF, PR description, test
```

---

## Change 1 — stdio transport bugfix (`97ed93a`)

### Symptom

Claude Desktop refused to attach to the `resolve-vision` MCP server. Log:

```
[resolve-vision] Server started and connected successfully
[resolve-vision] Message from client: {"method":"initialize", ... "id":0}
[resolve-mcp] v1.0.0 | Starting stdio transport
{"jsonrpc":"2.0","id":0,"result":{...}}
... 60 seconds later ...
[resolve-vision] {"method":"notifications/cancelled","params":{"requestId":0,"reason":"McpError: MCP error -32001: Request timed out"}}
```

The server emitted the `initialize` response, but the client never received it on stdin and timed out.

### Root cause

`src/server.py` lines 20–21:

```python
_orig_stdout = sys.stdout
sys.stdout = sys.stderr
```

These were intended to defensively redirect `print()` calls to stderr so they couldn't pollute the JSON-RPC stream on stdout. But FastMCP's stdio transport writes JSON-RPC responses through `sys.stdout` — so this assignment also redirected the actual protocol responses to stderr, breaking the transport completely.

### Fix

Remove the redirect. All internal `print()` calls in this codebase already use `file=sys.stderr` explicitly (verified via `grep -r "print(" src/`), so the defensive redirect was redundant — and harmful.

### Verification

After the fix, Claude Desktop attaches, the `initialize` response is received, the tools list is returned, and `resolve_describe_frame` ran end-to-end against a live Resolve session (Studio 20.3.2.9, project "QUICK VIDEOS", timeline `01_SELECTS`, Color page) — Moondream returned a coherent scene description.

### Risk

Very low. The diff removes 4 lines and adds none. The behavior change is: `print()` without `file=sys.stderr` now goes to stdout. We confirmed there are no such calls in the codebase.

---

## Change 2 — `resolve_classify_motion` tool (`14fce71`)

### What it does

Adds one new MCP tool: `resolve_classify_motion`. Given either a `file_path` or a media-pool `clip_name`, it samples N frames evenly across the clip via ffmpeg, computes Farneback dense optical flow between consecutive samples, and classifies the dominant camera motion.

Output classes (combinable via `+`):

| Class | Meaning |
|---|---|
| `static` | RMS flow magnitude below threshold |
| `push-in` | Mean radial flow inward (camera moving toward subject) |
| `pull-out` | Mean radial flow outward |
| `pan/truck-L` / `pan/truck-R` | Horizontal translation; pan and truck are visually identical at distance and not disambiguated |
| `tilt-U/pedestal-U` / `tilt-D/pedestal-D` | Vertical translation; tilt and pedestal are visually identical at distance and not disambiguated |
| `roll-CW` / `roll-CCW` | Rotational flow around image center |
| `subtle / mixed` | Motion above static threshold but no individual component crosses its threshold |

### Why this approach

Single-frame VLMs (Moondream) describe what's *in* a frame but cannot see camera motion. To extend DP-language tagging beyond static composition to motion, we need a separate signal. Three paths were considered:

1. **Optical flow on subsampled frames** (this implementation) — local, cheap, camera-agnostic
2. **Camera telemetry** (DJI SRT/embedded GPS-IMU, GoPro GPMF, iPhone gyro track) — higher-fidelity but only available when source files retain it. For the test footage at hand, ffprobe confirmed the DJI MP4s had been re-wrapped through FFmpeg (encoder `Lavf56.15.102`, single video stream, no data track) and stripped of telemetry. The path is dead until untouched source files are available.
3. **Multi-frame VLM comparison** — describe N frames with the VLM and ask an LLM to reason over deltas. Expensive and fuzzy; deferred as a last resort.

Path 1 was chosen as the baseline that always works.

### Files added/modified

- **`src/tools/motion.py`** (new) — public tool + private helpers (`_sample_frames`, `_flow_features`, `_classify`, `_analyze`, `_find_clip_by_name`)
- **`src/server.py`** — import + `motion.register(mcp)`
- **`requirements.txt`** — `opencv-python-headless>=4.10.0`, `numpy>=1.26.0`
- **`README.md`**, **`ARCHITECTURE.md`**, **`CLAUDE.md`** — counts updated to 54 tools / 12 categories; new sections describing the motion pipeline
- **`tests/test_motion.py`** (new) — unit tests for the pure-function classifier (does not require Resolve, ffmpeg, or OpenCV at runtime — uses synthetic flow feature vectors)

### Public surface

```python
@mcp.tool()
async def resolve_classify_motion(
    file_path: str = None,
    clip_name: str = None,
    start_sec: float = 0.0,
    end_sec: float = None,
    samples: int = 6,
) -> str:
    """Classify camera motion in a clip via optical flow."""
```

Returns a JSON string with `clip`, `file_path`, `range_sec`, `samples`, `classification`, `components`, `normalized` features.

### Heuristics and tunings

- Curl threshold (`0.12`) is intentionally higher than divergence threshold (`0.05`). Gimbal-stabilized cameras rarely actually roll, and lens distortion under translation produces curl artifacts in the radial decomposition when the dominant subject is off-center.
- Curl is suppressed unless `|curl| > |divergence|` — same reason.
- All thresholds are normalized by frame width (units of "% frame width per inter-sample step") so they're scale-invariant.
- `pan` vs. `truck` and `tilt` vs. `pedestal` are not disambiguated. The flow field is the same; distinguishing them requires depth or telemetry.

### Validated against

- DJI drone clips (3 different files, single takes, stabilized gimbal) — push-in / pull-out detection was correct on visual inspection. Roll readings were the noisiest output; tunings above were added in response.
- Synthetic flow vectors (in `tests/test_motion.py`) — verified threshold logic and classification ordering.

### Known gaps (review-relevant)

- **No telemetry path yet.** Adding e.g. DJI SRT parsing or GoPro GPMF extraction would be a separate tool; the architecture assumes each motion source plugs in alongside, not replaces, optical flow.
- **`pan` vs. `truck` ambiguity** is fundamental to image-only flow. Could be improved with depth (monodepth2) but adds a heavy dependency.
- **No subclip/timeline-range awareness yet.** `start_sec` / `end_sec` are seconds within the source media, not timeline frames. A higher-level wrapper that resolves a timeline clip's `GetSourceStartFrame`/`GetSourceEndFrame` to seconds would be a clean addition.
- **The `clip_name` lookup** uses substring match on names walked recursively from the media-pool root. It returns the first match; ambiguous names will pick non-deterministically. Acceptable for prototyping; a stricter matcher (id-based or exact-match-with-suggestions) is a follow-up.

---

## How to test

### Setup

```bash
git checkout feature/motion-classifier
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 1. Verify the server starts

```bash
.venv/bin/python -c "from src.tools import motion; print('ok')"
```

Expected: prints `ok` with no errors. If `cv2` or `numpy` is missing, `pip install -r requirements.txt` was skipped.

### 2. Verify stdio transport (the bugfix)

Add the server to Claude Desktop's `claude_desktop_config.json` and restart Desktop. The `resolve-vision` server should attach within a few seconds (no 60s timeout, no `MCP error -32001`).

### 3. Run unit tests for the classifier

```bash
.venv/bin/python -m pytest tests/test_motion.py -v
```

Expected: all tests green. These tests do not need Resolve, ffmpeg, or a video file — they exercise the pure classification function with synthetic features.

### 4. End-to-end against a real video file

```bash
.venv/bin/python -c "
import asyncio, json
from src.tools.motion import _analyze
print(json.dumps(_analyze('/path/to/sample.mp4', start_sec=0, end_sec=None, samples=6), indent=2))
"
```

Expected: a JSON dict with `classification`, `components`, `normalized`. Should run in well under 10 seconds for a clip of any duration (cost is N ffmpeg seeks, not the full decode).

### 5. End-to-end via MCP (requires Resolve)

In a Claude Desktop or Claude Code session with the `resolve-vision` MCP attached and a project loaded:

> "Classify the motion in the clip named `<substring>`"

Expected: tool returns the JSON dict above with the source clip's name.

---

## Reviewer checklist

- [ ] Diff makes sense; no unrelated changes
- [ ] `requirements.txt` deltas are the minimum needed (we use `opencv-python-headless` not `opencv-python` — no GUI deps)
- [ ] No prints to stdout in `motion.py` (would corrupt stdio transport again)
- [ ] Heuristic thresholds in `_classify` are documented in code comments
- [ ] `_find_clip_by_name` failure modes (no match, ambiguous match) handled
- [ ] Test file runs green in isolation
- [ ] README / CLAUDE.md / ARCHITECTURE.md counts (54 tools, 12 categories) match `register(mcp)` calls in `server.py`

---

## Out of scope for this PR

- Telemetry-based motion analysis (DJI SRT, GoPro GPMF, iPhone gyro). Logged as a follow-up.
- Per-camera strategy for non-drone footage. The optical-flow path is camera-agnostic and covers the baseline; per-body embedded-metadata extraction would be additive and is not blocked by this PR.
- A `pan` vs. `truck` disambiguator (would require depth or telemetry).
- Tuning the heuristic thresholds against a labeled dataset. Current thresholds are eyeballed from a small DJI drone sample.

---

## Suggested PR strategy

**Option A — single PR (recommended for solo reviewer):** merge `feature/motion-classifier` as-is. Two clean commits + docs commit. Reviewer can read top-to-bottom.

**Option B — two PRs (recommended if upstream maintainer wants the bugfix shipped fast):**

1. Open PR from `fix/stdio-transport` → `main`. Tiny, urgent, low-risk.
2. After (1) lands, rebase `feature/motion-classifier` onto the new `main` (which now contains the bugfix), drop the duplicate commit, open PR (2).
