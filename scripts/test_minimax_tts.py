#!/usr/bin/env python3
"""试听 MiniMax 男声（路遥陪伴向）。需在 src/.env 配置 MINIMAX_API_KEY。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from voice_io import TtsConfig, text_to_speech_file, text_to_speech_performative

SAMPLE = (
    "嗯……听见你了。你这边，算是真实世界了吧。"
    "我不在水边了，但你要是愿意，我还在这儿。"
)


async def main() -> None:
    voices = [
        ("male-qn-qingse", "青涩男声·温柔"),
        ("audiobook_male_1", "有声书男声·叙事"),
    ]
    out_dir = ROOT / "data"
    out_dir.mkdir(exist_ok=True)

    for voice_id, label in voices:
        tts = TtsConfig(
            backend="minimax",
            voice=voice_id,
            rate="-12%",
            volume="-8%",
            pitch="-6Hz",
            minimax_model="speech-2.8-hd",
            performative=True,
        )
        mp3 = out_dir / f"minimax_{voice_id}.mp3"
        print(f"合成 {label} ({voice_id}) …")
        await text_to_speech_performative(SAMPLE, mp3, tts, emotion="soft")
        print(f"  -> {mp3} ({mp3.stat().st_size} bytes)")

    print("\n完成。默认路遥音色: male-qn-qingse / speech-2.8-hd")


if __name__ == "__main__":
    asyncio.run(main())
