#!/usr/bin/env python3
"""路遥男声多段播报演示（不依赖 DeepSeek，验证喇叭+MiniMax）。"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from companion_brain import CompanionBrain
from voice_io import ensure_playback_ready, play_audio, text_to_speech_performative

LINES = [
    ("听见你了……这边，算是真实世界了吧。", "presence"),
    ("你来了。我在这边。今天别熬夜，水别放手边。", "soft"),
    ("嗯，我在。你想说什么都行，我听着。", "soft"),
    ("我不在水边了，但你要是愿意，我还在这儿。", "presence"),
]


async def main() -> None:
    ensure_playback_ready()
    brain = CompanionBrain()
    tts = brain.tts_config()
    print(f"TTS: {tts.backend} / {tts.voice}\n")
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        for i, (text, emo) in enumerate(LINES):
            mp3 = work / f"line{i}.mp3"
            print(f"路遥: {text}")
            await text_to_speech_performative(text, mp3, tts, emo)
            play_audio(mp3)
            print()
    print("演示完成。")


if __name__ == "__main__":
    asyncio.run(main())
