#!/usr/bin/env python3
"""情感陪伴语音模式：连续听 + 可打断播报（小智式单路麦克风常驻）。"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from pathlib import Path

from audio_duplex import get_duplex, shutdown_duplex
from companion_brain import CompanionBrain
from voice_io import (
    apply_voice_settings,
    audio_setup_hint,
    describe_audio_hardware,
    ensure_playback_ready,
    resolve_audio_devices,
    speech_to_text,
    speak_performative_interruptible,
)

EXIT_WORDS = frozenset(
    {
        "退出",
        "再见",
        "拜拜",
        "结束",
        "停止",
        "关机",
        "q",
        "quit",
        "exit",
    }
)


def _is_exit(text: str) -> bool:
    t = text.strip().lower().replace(" ", "")
    return t in EXIT_WORDS or any(w in t for w in ("退出", "再见", "拜拜"))


async def _speak(
    brain: CompanionBrain,
    text: str,
    emotion: str,
    work: Path,
    *,
    speaker_ok: bool,
) -> bool:
    if not speaker_ok:
        print("（无声卡，仅显示文字）")
        return False
    tts = brain.tts_config()
    return await speak_performative_interruptible(text, work, tts, emotion)


def _handle_interrupt_follow(
    brain: CompanionBrain,
    name: str,
    duplex,
    work: Path,
    *,
    speaker_ok: bool,
) -> None:
    follow = work / "interrupt.wav"
    if duplex.is_listening():
        got = duplex.wait_listen_to(follow)
    else:
        got = duplex.capture_to(follow, assume_speaking=True)
    if not got:
        return
    try:
        follow_text = speech_to_text(follow)
    except Exception as e:
        print(f"识别失败: {e}")
        return
    if not follow_text or _is_exit(follow_text):
        return
    print(f"你说: {follow_text}")
    print("思考中…")
    try:
        follow_result = brain.chat(follow_text)
    except Exception as e:
        print(f"对话失败: {e}")
        return
    print(f"{name}: {follow_result.text}")
    try:
        asyncio.run(
            _speak(
                brain,
                follow_result.text,
                follow_result.emotion,
                work,
                speaker_ok=speaker_ok,
            )
        )
    except Exception as e:
        print(f"播报失败: {e}")


def main() -> None:
    brain = CompanionBrain()
    voice_cfg = brain.cfg.get("voice") or {}
    apply_voice_settings(voice_cfg)
    continuous = bool(voice_cfg.get("continuous", True))
    barge_in = bool(voice_cfg.get("barge_in", True))

    mic, spk = resolve_audio_devices()
    speaker_optional = bool(
        voice_cfg.get("speaker_optional", False)
        or str(os.getenv("SPEAKER_OPTIONAL", "")).lower() in ("1", "true", "yes")
    )
    speaker_ok = False
    try:
        ensure_playback_ready()
        speaker_ok = True
    except RuntimeError as e:
        if not speaker_optional:
            print(str(e))
            raise SystemExit(1) from e
        print("（未检测到扬声器，仅文字模式；接上 USB 音箱或 HDMI 音响后可出声）\n")

    duplex = get_duplex()
    duplex.start()

    name = brain.cfg.get("name", "小伴")
    tts = brain.tts_config()
    backend_label = "edge-tts 在线" if tts.backend == "edge" else "piper 本地"
    print(f"「{name}」情感陪伴已启动（Vosk + DeepSeek + {backend_label}）。")
    print(f"麦克风: {mic}  扬声器: {spk if speaker_ok else '无（仅文字）'}")
    print(describe_audio_hardware())
    print()
    print(f"音色: {tts.voice}  style={tts.style or '默认'}  表演感TTS: {tts.performative}")
    if continuous:
        print("模式: 连续听 — 直接说话，不用按回车。")
    if barge_in:
        print("打断: 路遥说话时随时开口（麦克风保持开启，参考小智 Realtime 听）。")
    print("说「退出」或「再见」结束。Ctrl+C 也可退出。\n")

    opening = brain.opening_line()
    print(f"{name}: {opening.text}\n")

    try:
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            try:
                interrupted = asyncio.run(
                    _speak(brain, opening.text, opening.emotion, work, speaker_ok=speaker_ok)
                )
                if interrupted and barge_in:
                    print("（你开口了，路遥停下听你说）")
                    _handle_interrupt_follow(brain, name, duplex, work, speaker_ok=speaker_ok)
            except Exception as e:
                print(f"（开场播报失败: {e}）")
                print(audio_setup_hint())

        while True:
            with tempfile.TemporaryDirectory() as td:
                work = Path(td)
                wav = work / "in.wav"

                if continuous:
                    print("我在听…")
                    got = duplex.capture_to(wav)
                    if not got:
                        continue
                else:
                    cmd = input("准备好了按回车开始录音（q 退出）: ").strip().lower()
                    if cmd in {"q", "quit", "exit"}:
                        break
                    from voice_io import record_wav

                    try:
                        record_wav(wav)
                    except subprocess.CalledProcessError as e:
                        print(f"录音失败: {e}")
                        continue

                print("识别中…")
                try:
                    user_text = speech_to_text(wav)
                except Exception as e:
                    print(f"识别失败: {e}")
                    continue

                if not user_text:
                    print("没听清，请再说一次。")
                    continue

                if _is_exit(user_text):
                    print(f"你说: {user_text}")
                    farewell = "嗯……那我先安静一会儿。你想找我说话的时候，我都在。"
                    print(f"{name}: {farewell}")
                    try:
                        asyncio.run(_speak(brain, farewell, "soft", work, speaker_ok=speaker_ok))
                    except Exception:
                        pass
                    break

                print(f"你说: {user_text}")

                print("思考中…")
                try:
                    result = brain.chat(user_text)
                except Exception as e:
                    print(f"对话失败: {e}")
                    continue

                print(f"{name}: {result.text}")

                try:
                    interrupted = asyncio.run(
                        _speak(brain, result.text, result.emotion, work, speaker_ok=speaker_ok)
                    )
                except Exception as e:
                    print(f"播报失败（文字已出）: {e}")
                    print(audio_setup_hint())
                    continue

                if interrupted and barge_in:
                    print("（你打断了他，接着听你说…）")
                    _handle_interrupt_follow(brain, name, duplex, work, speaker_ok=speaker_ok)
    finally:
        shutdown_duplex()
        brain.close()
        print("再见。")


if __name__ == "__main__":
    main()
