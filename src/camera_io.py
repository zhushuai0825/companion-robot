"""摄像头探测与抓拍（树莓派 USB 摄像头 / Mac 内置相机）。"""

from __future__ import annotations

import platform
import shutil
import subprocess
import tempfile
from pathlib import Path


def list_video_devices_linux() -> list[str]:
    devs = sorted(Path("/dev").glob("video*"))
    return [str(p) for p in devs if p.is_char_device()]


def list_video_devices_mac() -> list[str]:
    if not shutil.which("ffmpeg"):
        return []
    try:
        out = subprocess.run(
            ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True,
            text=True,
            timeout=10,
        )
        text = out.stderr
    except OSError:
        return []
    devices: list[str] = []
    in_video = False
    for line in text.splitlines():
        if "AVFoundation video devices" in line:
            in_video = True
            continue
        if "AVFoundation audio devices" in line:
            in_video = False
        if in_video and "[" in line and "]" in line:
            # [0] FaceTime HD Camera
            name = line.split("]", 1)[-1].strip()
            if name and "Capture screen" not in name:
                devices.append(name)
    return devices


def list_cameras() -> list[str]:
    if platform.system() == "Linux":
        return list_video_devices_linux()
    if platform.system() == "Darwin":
        return list_video_devices_mac()
    return []


def capture_photo(out: Path, device: str | int | None = None) -> Path:
    """抓拍一张 JPG。Linux 默认 /dev/video0；Mac 用 avfoundation 索引 0。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    if platform.system() == "Linux":
        dev = str(device) if device is not None else "/dev/video0"
        if shutil.which("ffmpeg"):
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "v4l2",
                    "-i",
                    dev,
                    "-frames:v",
                    "1",
                    "-update",
                    "1",
                    str(out),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return out
        try:
            import cv2

            cap = cv2.VideoCapture(dev if isinstance(dev, int) else 0)
            ok, frame = cap.read()
            cap.release()
            if not ok:
                raise RuntimeError("OpenCV 无法读取帧")
            cv2.imwrite(str(out), frame)
            return out
        except ImportError as e:
            raise RuntimeError("需要 ffmpeg 或 opencv-python") from e

    if platform.system() == "Darwin":
        idx = int(device) if device is not None else 0
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "avfoundation",
                "-framerate",
                "30",
                "-i",
                f"{idx}:none",
                "-frames:v",
                "1",
                str(out),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return out

    raise RuntimeError(f"不支持的平台: {platform.system()}")


def probe_camera() -> tuple[bool, str]:
    """尝试抓拍，返回 (成功与否, 说明)。"""
    cams = list_cameras()
    if not cams and platform.system() == "Linux":
        return False, "未发现 /dev/video* 设备"
    with tempfile.TemporaryDirectory() as td:
        jpg = Path(td) / "probe.jpg"
        try:
            capture_photo(jpg)
        except Exception as e:
            return False, f"抓拍失败: {e}"
        if not jpg.exists() or jpg.stat().st_size < 500:
            return False, "抓拍文件过小"
        return True, f"OK ({jpg.stat().st_size} bytes, 设备: {cams[:3] or ['default']})"
