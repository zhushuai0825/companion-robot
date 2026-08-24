#!/usr/bin/env python3
"""麦克风 + 扬声器 + 摄像头 + MiniMax 男声 + 路遥多轮对话 全链路测试。"""

from __future__ import annotations

import asyncio
import json
import math
import os
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from dotenv import load_dotenv

load_dotenv(SRC / ".env")
load_dotenv(ROOT / ".env")

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def _wav_rms(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        raw = wf.readframes(wf.getnframes())
    if len(raw) < 2:
        return 0.0
    samples = struct.unpack(f"<{len(raw)//2}h", raw[: len(raw) // 2 * 2])
    return math.sqrt(sum(s * s for s in samples) / len(samples))


def shutil_which(cmd: str) -> str | None:
    return shutil.which(cmd)


def test_list_devices() -> None:
    print("\n=== 1. 设备枚举 ===")
    if shutil_which("arecord"):
        subprocess.run(["arecord", "-l"], check=False)
    if shutil.which("aplay"):
        subprocess.run(["aplay", "-l"], check=False)
    if shutil.which("lsusb"):
        subprocess.run(["lsusb"], check=False)
    from camera_io import list_cameras

    cams = list_cameras()
    record("摄像头枚举", bool(cams) or platform.system() == "Darwin", ", ".join(cams) or "无")


def test_microphone() -> None:
    print("\n=== 2. 麦克风录音 ===")
    from voice_io import MIC, resolve_audio_devices

    resolve_audio_devices()
    mic = MIC or "default"
    wav = Path(tempfile.mkdtemp()) / "mic.wav"
    try:
        if shutil_which("arecord"):
            subprocess.run(
                [
                    "arecord",
                    "-q",
                    "-D",
                    mic,
                    "-d",
                    "3",
                    "-f",
                    "S16_LE",
                    "-r",
                    "16000",
                    "-c",
                    "1",
                    str(wav),
                ],
                check=True,
                timeout=15,
            )
        elif platform.system() == "Darwin" and shutil_which("ffmpeg"):
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "avfoundation",
                    "-i",
                    ":0",
                    "-t",
                    "3",
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    str(wav),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
        else:
            record("麦克风录音", False, "无 arecord/ffmpeg")
            return
        rms = _wav_rms(wav)
        ok = wav.exists() and wav.stat().st_size > 1000 and rms > 30
        record("麦克风录音", ok, f"{mic} RMS={rms:.0f} size={wav.stat().st_size if wav.exists() else 0}")
    except Exception as e:
        record("麦克风录音", False, str(e))
    finally:
        wav.unlink(missing_ok=True)


def test_speaker_tts() -> None:
    print("\n=== 3. MiniMax 男声 + 扬声器 ===")
    from companion_brain import CompanionBrain
    from voice_io import ensure_playback_ready, play_audio, resolve_audio_devices, text_to_speech_file

    resolve_audio_devices()
    try:
        ensure_playback_ready()
    except RuntimeError as e:
        record("扬声器可用", False, str(e)[:120])
        return
    record("扬声器可用", True, os.getenv("PLAYBACK_BACKEND", "aplay"))

    brain = CompanionBrain()
    tts = brain.tts_config()
    with tempfile.TemporaryDirectory() as td:
        mp3 = Path(td) / "tts.mp3"
        try:
            asyncio.run(
                text_to_speech_file(
                    "嗯，我在。这是路遥的男声测试，你能听见吗？", mp3, tts
                )
            )
            play_audio(mp3)
            record("MiniMax TTS 播放", mp3.exists() and mp3.stat().st_size > 500, tts.voice)
        except Exception as e:
            record("MiniMax TTS 播放", False, str(e))


def test_camera() -> None:
    print("\n=== 4. 摄像头 ===")
    from camera_io import list_cameras, probe_camera

    cams = list_cameras()
    ok, msg = probe_camera()
    out = ROOT / "data" / "test_capture.jpg"
    if ok:
        try:
            from camera_io import capture_photo

            capture_photo(out)
            record("摄像头抓拍", out.exists() and out.stat().st_size > 500, f"{msg} → {out}")
        except Exception as e:
            record("摄像头抓拍", False, str(e))
    else:
        record("摄像头抓拍", False, msg or f"设备: {cams}")


def test_stt() -> None:
    print("\n=== 5. 语音识别 (Vosk) ===")
    from voice_io import MIC, speech_to_text

    wav = Path(tempfile.mkdtemp()) / "stt.wav"
    try:
        if shutil_which("arecord"):
            subprocess.run(
                [
                    "arecord",
                    "-q",
                    "-D",
                    MIC,
                    "-d",
                    "2",
                    "-f",
                    "S16_LE",
                    "-r",
                    "16000",
                    "-c",
                    "1",
                    str(wav),
                ],
                check=True,
                timeout=10,
            )
        else:
            record("Vosk 识别", False, "跳过（无录音设备）")
            return
        text = speech_to_text(wav)
        record("Vosk 识别", True, repr(text) or "(空)")
    except Exception as e:
        record("Vosk 识别", False, str(e))
    finally:
        wav.unlink(missing_ok=True)


def test_dialogue_with_voice() -> None:
    print("\n=== 6. 路遥多轮对话 + 播报 ===")
    api = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api or "粘贴" in api:
        record("路遥对话+播报", False, "缺少 DEEPSEEK_API_KEY")
        return

    from companion_brain import CompanionBrain
    from voice_io import ensure_playback_ready, play_audio, text_to_speech_performative

    try:
        ensure_playback_ready()
    except RuntimeError:
        record("路遥对话+播报", False, "无扬声器")
        return

    brain = CompanionBrain()
    tts = brain.tts_config()
    prompts = [
        "你好，在吗？",
        "你会一直陪着我吗？",
        "今天上班好累",
    ]
    all_ok = True
    details: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        for i, q in enumerate(prompts):
            try:
                r = brain.chat(q)
                mp3 = work / f"reply{i}.mp3"
                asyncio.run(text_to_speech_performative(r.text, mp3, tts, r.emotion))
                play_audio(mp3)
                details.append(f"Q{i+1} len={len(r.text)} emo={r.emotion}")
                print(f"  你说: {q}")
                print(f"  路遥: {r.text[:100]}{'…' if len(r.text)>100 else ''}\n")
            except Exception as e:
                all_ok = False
                details.append(f"Q{i+1} err={e}")
    brain.close()
    record("路遥对话+播报", all_ok, "; ".join(details))


def test_barge_in() -> None:
    print("\n=== 7. 打断播报 (可选) ===")
    if not shutil_which("arecord"):
        record("打断播报", True, "跳过（Mac 无 duplex）")
        return
    from audio_duplex import get_duplex, shutdown_duplex
    from companion_brain import CompanionBrain
    from voice_io import ensure_playback_ready, text_to_speech_file

    try:
        ensure_playback_ready()
    except RuntimeError as e:
        record("打断播报", False, str(e)[:80])
        return

    brain = CompanionBrain()
    tts = brain.tts_config()
    with tempfile.TemporaryDirectory() as td:
        mp3 = Path(td) / "long.mp3"
        long_text = "嗯。" + "我在听。" * 8
        asyncio.run(text_to_speech_file(long_text, mp3, tts))
        duplex = get_duplex()
        duplex.start()
        print("  （播放中，请对着麦克风说话以测试打断…3 秒后开始）")
        time.sleep(1)
        interrupted = duplex.play_interruptible(mp3)
        shutdown_duplex()
        record("打断播报", True, "检测到打断" if interrupted else "未检测到打断(可人工再试)")


def main() -> None:
    print("=" * 50)
    print(" companion-robot 全硬件测试")
    print(f" 平台: {platform.system()} {platform.machine()}")
    print(f" 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    test_list_devices()
    test_microphone()
    test_speaker_tts()
    test_camera()
    test_stt()
    test_dialogue_with_voice()
    test_barge_in()

    print("\n" + "=" * 50)
    print(" 测试汇总")
    print("=" * 50)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    for name, ok, detail in RESULTS:
        print(f"  {'✓' if ok else '✗'} {name}: {detail}")
    print(f"\n合计: {passed}/{len(RESULTS)} 通过")
    report = ROOT / "data" / "hardware_test_report.json"
    report.parent.mkdir(exist_ok=True)
    report.write_text(
        json.dumps(
            [{"name": n, "ok": o, "detail": d} for n, o, d in RESULTS],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"报告已写: {report}")
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
