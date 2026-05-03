# PR description (paste into GitHub)

> **Title:** `Add resolve_classify_motion tool + fix stdio transport`
>
> **Base:** `main`  **Compare:** `feature/motion-classifier`

---

## Summary

- **Bugfix** — `src/server.py` was reassigning `sys.stdout = sys.stderr` at module load, which silently routed FastMCP's JSON-RPC writes to stderr and caused Claude Desktop to time out on `initialize` (`MCP error -32001` after 60s). Removed the redirect; all internal `print()` calls already use `file=sys.stderr` explicitly.
- **Feature** — new MCP tool `resolve_classify_motion` (in new module `src/tools/motion.py`) that classifies camera motion in a clip via optical flow. Output classes: `static`, `push-in`, `pull-out`, `pan/truck-L/R`, `tilt-U/D` (or `pedestal-U/D`), `roll-CW/CCW`, or combinations. Camera-agnostic, runs locally, no API calls.

The two changes are conceptually independent. They're packaged together for review convenience; reviewer can split into two PRs by cherry-picking the bugfix commit (`97ed93a`) onto its own branch (one already exists locally as `fix/stdio-transport`).

## Why

Single-frame VLMs (e.g. Moondream, already integrated via `vision.py`) describe what's *in* a frame but cannot see camera movement — a static shot and a 5-second push-in are indistinguishable to a still-image VLM. To extend DP-language metadata tagging beyond static composition, we need a separate signal for motion.

Three candidate signals were evaluated:

1. **Optical flow on subsampled frames** — local, cheap, camera-agnostic. **Implemented.**
2. **Camera telemetry** (DJI SRT / embedded GPS-IMU, GoPro GPMF, iPhone gyro track) — higher fidelity but only present when source files retain it. Verified dead on the test footage: re-wrapped through FFmpeg, single video stream, no data track.
3. **Multi-frame VLM comparison** — expensive and fuzzy; deferred.

## How

```
ffprobe (duration) -> ffmpeg seeks N evenly-spaced frames @640px ->
cv2.calcOpticalFlowFarneback per consecutive pair ->
flow field decomposed into translation (dx, dy), divergence (radial),
curl (rotational) -> width-normalized -> threshold/classify
```

Heuristic notes baked into `_classify`:

- Curl threshold (`0.12`) > divergence threshold (`0.05`); curl is suppressed when `|curl| <= |divergence|`. Reason: gimbal-stabilized cameras rarely actually roll, and lens distortion under translation produces spurious curl in the radial decomposition when the dominant subject is off-center.
- Thresholds normalized by frame width so behavior is scale-invariant.
- `pan` vs. `truck` and `tilt` vs. `pedestal` are not disambiguated — flow is identical at distance.

## Test plan

- [ ] `pip install -r requirements.txt` (adds `opencv-python-headless`, `numpy`)
- [ ] `python -c "from src.tools import motion; print('ok')"` — module imports cleanly
- [ ] Restart Claude Desktop with `resolve-vision` configured — server attaches in <5s, no `MCP error -32001` (proves bugfix)
- [ ] `pytest tests/test_motion.py -v` — unit tests for classification logic green (no Resolve / ffmpeg required)
- [ ] In a Claude session: `resolve_classify_motion(clip_name="<some clip>")` returns a coherent classification JSON
- [ ] Verify stdio doesn't get noise: `python src/server.py < /dev/null 2>/tmp/err 1>/tmp/out`, then check `/tmp/out` is empty until first JSON-RPC message arrives on stdin

## Files changed

| File | Change |
|---|---|
| `src/server.py` | (-) `sys.stdout` redirect; (+) import + register `motion` |
| `src/tools/motion.py` | NEW — public tool + private helpers |
| `requirements.txt` | (+) `opencv-python-headless`, `numpy` |
| `tests/test_motion.py` | NEW — unit tests for `_classify` heuristics |
| `README.md` | tool count 53→54, 11→12 categories; new "How Motion Classification Works" section; ffmpeg prereq |
| `ARCHITECTURE.md` | tool count + new "Camera Motion Classification Pipeline" section + file structure update |
| `CLAUDE.md` | tool count + new "Tag a clip with DP language (composition + motion)" workflow |
| `docs/HANDOFF.md` | NEW — reviewer hand-off doc |
| `docs/PR_DESCRIPTION.md` | NEW — this file |

## Out of scope

- Telemetry parsers (DJI SRT, GoPro GPMF, iPhone gyro track) — logged as follow-up
- Depth-based `pan` vs. `truck` disambiguation
- Per-camera-body strategies for non-drone footage (covered by optical flow as baseline; embedded-metadata paths are additive)
- Threshold tuning against a labeled dataset

## Risk

- Bugfix: very low (4-line removal; no calls in codebase rely on the removed redirect)
- Feature: medium-low (new module, doesn't touch existing tool paths; new system deps are widely available; thresholds are conservative and easily tuned without changing the public surface)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
