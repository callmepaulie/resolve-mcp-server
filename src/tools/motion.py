"""Camera-motion classification via optical flow.

Samples N frames from a clip's source media file using ffmpeg, computes
Farneback dense optical flow between consecutive samples, and classifies
the dominant camera motion: static, push-in/pull-out, pan/truck-L/R,
tilt/pedestal-U/D, roll-CW/CCW, or combinations.

Camera-agnostic — works on any video file ffmpeg can decode. Telemetry
(when available) would be more accurate; flow is the fallback that always
works.
"""

import json
import os
import shutil
import subprocess
import tempfile

import cv2
import numpy as np
from mcp.server.fastmcp import FastMCP

from ..services.resolve_connection import get_project, get_timeline


def _sample_frames(video_path, out_dir, num_samples, start_sec, end_sec, width=640):
    if end_sec is None:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, check=True,
        )
        end_sec = float(probe.stdout.strip())

    safe_start = start_sec + 0.1
    safe_end = max(end_sec - 0.5, safe_start + 0.001)
    duration = safe_end - safe_start
    interval = duration / max(num_samples - 1, 1)

    paths = []
    for i in range(num_samples):
        t = safe_start + i * interval
        out = os.path.join(out_dir, f"frame_{i:03d}.png")
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-ss", str(t), "-i", video_path,
             "-vframes", "1", "-vf", f"scale={width}:-1", "-y", out],
            check=True,
        )
        paths.append(out)
    return paths


def _flow_features(frame_a, frame_b):
    gray_a = cv2.cvtColor(frame_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(frame_b, cv2.COLOR_BGR2GRAY)
    flow = cv2.calcOpticalFlowFarneback(
        gray_a, gray_b, None,
        pyr_scale=0.5, levels=3, winsize=15,
        iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
    )
    fx, fy = flow[..., 0], flow[..., 1]
    mean_dx, mean_dy = float(fx.mean()), float(fy.mean())

    fx_c = fx - mean_dx
    fy_c = fy - mean_dy
    h, w = fx.shape
    cx, cy = w / 2.0, h / 2.0
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    rx, ry = xx - cx, yy - cy
    r_norm = np.sqrt(rx * rx + ry * ry) + 1e-6
    rx /= r_norm
    ry /= r_norm
    divergence = float((fx_c * rx + fy_c * ry).mean())
    curl = float((fx_c * (-ry) + fy_c * rx).mean())
    rms = float(np.sqrt((fx ** 2 + fy ** 2).mean()))
    return {"mean_dx": mean_dx, "mean_dy": mean_dy,
            "divergence": divergence, "curl": curl, "rms": rms}


def _classify(features, width):
    avg = {k: float(np.mean([f[k] for f in features])) for k in features[0]}
    norm = width / 100.0
    dx, dy = avg["mean_dx"] / norm, avg["mean_dy"] / norm
    div, curl, rms = avg["divergence"] / norm, avg["curl"] / norm, avg["rms"] / norm

    STATIC_RMS = 0.3
    TRANS_MIN = 0.15
    DIV_MIN = 0.05
    # Curl threshold is intentionally higher than div: stabilized cameras
    # rarely true-roll, and lens distortion under translation can create
    # spurious curl when the dominant subject is off-center.
    CURL_MIN = 0.12

    if rms < STATIC_RMS:
        return {"classification": "static", "components": [],
                "normalized": {"dx": round(dx, 3), "dy": round(dy, 3),
                               "divergence": round(div, 3),
                               "curl": round(curl, 3), "rms": round(rms, 3)}}

    components = []
    if abs(div) > DIV_MIN:
        components.append(("push-in" if div < 0 else "pull-out", abs(div)))
    if abs(curl) > CURL_MIN and abs(curl) > abs(div):
        # Only trust curl when it dominates divergence — otherwise it's likely
        # a distortion artifact of the radial motion.
        components.append(("roll-CCW" if curl > 0 else "roll-CW", abs(curl)))
    if max(abs(dx), abs(dy)) > TRANS_MIN:
        if abs(dx) > abs(dy):
            components.append(("pan/truck-R" if dx < 0 else "pan/truck-L", abs(dx)))
        else:
            components.append(("tilt-D/pedestal-D" if dy < 0 else "tilt-U/pedestal-U", abs(dy)))

    components.sort(key=lambda x: x[1], reverse=True)
    classification = " + ".join(c[0] for c in components[:2]) if components else "subtle / mixed"
    return {"classification": classification,
            "components": [{"label": c[0], "weight": round(c[1], 3)} for c in components],
            "normalized": {"dx": round(dx, 3), "dy": round(dy, 3),
                           "divergence": round(div, 3),
                           "curl": round(curl, 3), "rms": round(rms, 3)}}


def _analyze(file_path, start_sec, end_sec, samples):
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Video file not found: {file_path}")
    tmp = tempfile.mkdtemp(prefix="resolve_motion_")
    try:
        frame_paths = _sample_frames(file_path, tmp, samples, start_sec, end_sec)
        imgs = [cv2.imread(p) for p in frame_paths]
        if any(img is None for img in imgs):
            raise RuntimeError("Failed to read one or more sampled frames")
        feats = [_flow_features(imgs[i], imgs[i + 1]) for i in range(len(imgs) - 1)]
        return _classify(feats, width=imgs[0].shape[1])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _find_clip_by_name(name_substring):
    """Search the media pool recursively for a clip whose name contains the substring."""
    project = get_project()
    pool = project.GetMediaPool()
    root = pool.GetRootFolder()

    def walk(folder):
        for clip in folder.GetClipList() or []:
            n = clip.GetName() or ""
            if name_substring.lower() in n.lower():
                yield clip
        for sub in folder.GetSubFolderList() or []:
            yield from walk(sub)

    return next(walk(root), None)


def register(mcp: FastMCP):

    @mcp.tool()
    async def resolve_classify_motion(
        file_path: str = None,
        clip_name: str = None,
        start_sec: float = 0.0,
        end_sec: float = None,
        samples: int = 6,
    ) -> str:
        """Classify camera motion in a clip via optical flow.

        Samples N frames evenly across the source media using ffmpeg, computes
        Farneback dense optical flow between consecutive samples, and classifies
        the dominant motion. Camera-agnostic; runs locally with no API cost.

        Output classes (combinable):
            static, push-in, pull-out, pan/truck-L, pan/truck-R,
            tilt-U/pedestal-U, tilt-D/pedestal-D, roll-CW, roll-CCW.

        Provide either `file_path` (absolute path to the source media) OR
        `clip_name` (substring of a media pool clip name — looked up via Resolve).

        Args:
            file_path: Absolute path to the video file.
            clip_name: Substring of a media pool clip name (alternative to file_path).
            start_sec: Start of analysis window in seconds (default 0).
            end_sec: End of analysis window in seconds (default: full duration).
            samples: Number of frames to sample (default 6, more = slower but smoother).
        """
        if not file_path and not clip_name:
            return json.dumps({"error": "Provide file_path or clip_name."})

        resolved_path = file_path
        clip_label = None
        if not resolved_path:
            clip = _find_clip_by_name(clip_name)
            if clip is None:
                return json.dumps({"error": f"No media pool clip matched '{clip_name}'."})
            clip_label = clip.GetName()
            resolved_path = clip.GetClipProperty("File Path")
            if not resolved_path:
                return json.dumps({"error": f"Clip '{clip_label}' has no File Path."})

        try:
            result = _analyze(resolved_path, start_sec, end_sec, samples)
        except Exception as e:
            return json.dumps({"error": str(e), "file_path": resolved_path})

        return json.dumps({
            "clip": clip_label or os.path.basename(resolved_path),
            "file_path": resolved_path,
            "range_sec": [start_sec, end_sec],
            "samples": samples,
            **result,
        }, indent=2)
