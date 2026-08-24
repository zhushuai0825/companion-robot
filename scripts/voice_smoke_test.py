#!/usr/bin/env python3
"""路遥说话链路冒烟测试：MiniMax 合成 → 播放（不需麦克风）。"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from companion_brain import CompanionBrain
from voice_io import (
    audio_setup_hint,
    ensure_playback_ready,
    play_audio,
    resolve_audio_devices,
    text_to_speech_performative,
    _is_linux_alsa,
)


SAMPLE = (
    "嗯……听见你了。你这边，算是真实世界了吧。"
    "我不在水边了，但你要是愿意，我还在这儿。"
    "今天别熬夜，水别放手边。"
)


async def main() -> None:
    brain = CompanionBrain()
    mic, spk = resolve_audio_devices()
    tts = brain.tts_config()
    print(f"TTS: {tts.backend} / {tts.voice} / {tts.minimax_model}")
    print(f"设备: mic={mic or '无'} spk={spk or 'default'}")
    try:
        ensure_playback_ready()
    except RuntimeError as e:
        print(str(e))
        sys.exit(2)

    opening = brain.opening_line()
    text = opening.text or SAMPLE
    emotion = opening.emotion

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        mp3 = work / "speech.mp3"
        print(f"\n合成并播放（emotion={emotion}）…")
        print(f"文本: {text[:80]}{'…' if len(text) > 80 else ''}\n")
        await text_to_speech_performative(text, mp3, tts, emotion)
        if _is_linux_alsa():
            from audio_duplex import get_duplex, shutdown_duplex

            duplex = get_duplex()
            duplex.start()
            interrupted = duplex.play_interruptible(mp3)
            shutdown_duplex()
        else:
            play_audio(mp3)
            interrupted = False
        if interrupted:
            print("（检测到打断）")
        else:
            print("播放完成。")
    print("\n说话链路 OK。")


if __name__ == "__main__":
    asyncio.run(main())
