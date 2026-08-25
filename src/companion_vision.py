"""摄像头陪伴：抓拍、画面变化、「看见你在」上下文。"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VisionSnapshot:
    ok: bool
    image_path: Path | None
    motion_score: float
    detail: str


def _linux_capture(out: Path, device: str = "/dev/video0") -> bool:
    if not Path(device).exists():
        return False
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "v4l2",
                "-i",
                device,
                "-frames:v",
                "1",
                "-update",
                "1",
                str(out),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
        )
        return out.exists() and out.stat().st_size > 500
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False


def _frame_motion_score(path_a: Path, path_b: Path) -> float:
    try:
        import cv2

        a = cv2.imread(str(path_a))
        b = cv2.imread(str(path_b))
        if a is None or b is None:
            return 0.0
        a = cv2.resize(a, (160, 120))
        b = cv2.resize(b, (160, 120))
        diff = cv2.absdiff(a, b)
        return float(diff.mean())
    except ImportError:
        # 无 opencv：用文件大小差粗估
        if not path_a.exists() or not path_b.exists():
            return 0.0
        return abs(path_a.stat().st_size - path_b.stat().st_size) / 1000.0


def capture_snapshot(
    out_dir: Path,
    device: str = "",
) -> VisionSnapshot:
    out_dir.mkdir(parents=True, exist_ok=True)
    jpg = out_dir / "vision_latest.jpg"
    dev = device or os.getenv("CAMERA_DEVICE", "/dev/video0")
    ok = _linux_capture(jpg, dev)
    if not ok:
        return VisionSnapshot(False, None, 0.0, f"抓拍失败 ({dev})")
    return VisionSnapshot(True, jpg, 0.0, f"已抓拍 {jpg.stat().st_size} bytes")


def detect_presence(
    out_dir: Path,
    device: str = "",
    motion_threshold: float = 8.0,
) -> VisionSnapshot:
    """连续两帧差分，粗判「有人在动」。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    dev = device or os.getenv("CAMERA_DEVICE", "/dev/video0")
    with tempfile.TemporaryDirectory() as td:
        a = Path(td) / "a.jpg"
        b = Path(td) / "b.jpg"
        if not _linux_capture(a, dev):
            return VisionSnapshot(False, None, 0.0, "摄像头不可用")
        import time

        time.sleep(0.35)
        if not _linux_capture(b, dev):
            return VisionSnapshot(False, None, 0.0, "第二帧失败")
        score = _frame_motion_score(a, b)
        latest = out_dir / "vision_latest.jpg"
        try:
            import shutil

            shutil.copy(b, latest)
        except OSError:
            latest = b
        present = score >= motion_threshold
        detail = (
            f"画面有变化(score={score:.1f})，可能有人在"
            if present
            else f"画面较静(score={score:.1f})"
        )
        return VisionSnapshot(present, latest, score, detail)


def vision_context_for_brain(snapshot: VisionSnapshot) -> str:
    if not snapshot.ok:
        return ""
    if snapshot.motion_score >= 8.0:
        return (
            "【视觉】摄像头看到画面有动静，用户可能在面前。"
            "可自然说「看见你了」或「你到了」，不要描述具体穿着外貌（你看不清）。"
        )
    return (
        "【视觉】摄像头画面较静，用户可能不在镜头前或没动。"
        "不要假装看清用户表情。"
    )
