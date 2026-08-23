#!/usr/bin/env python3
"""试听 edge-tts 中文音色，方便挑陪伴向声音。

用法：
  python3 list_tts_voices.py              # 列出推荐男声（陪伴向）
  python3 list_tts_voices.py --female     # 列出推荐女声
  python3 list_tts_voices.py --all        # 列出全部中文音色
  python3 list_tts_voices.py --try zh-CN-YunxiNeural
  python3 list_tts_voices.py --try zh-CN-YunxiNeural --style narrative-relaxed
"""

from __future__ import annotations

import argparse
import asyncio
import tempfile
from pathlib import Path

from voice_io import TtsConfig, play_mp3, text_to_speech_file

SAMPLE = "嗯……我在。你不用急着说什么，我听着。"

MALE_RECOMMENDED = (
    ("zh-CN-YunxiNeural", "narrative-relaxed", "云希·叙事放松"),
    ("zh-CN-YunxiNeural", "assistant", "云希·助手"),
    ("zh-CN-YunjianNeural", "", "云健·沉稳"),
)

FEMALE_RECOMMENDED = (
    ("zh-CN-XiaoxiaoNeural", "", "晓晓·甜柔"),
    ("zh-CN-XiaoyiNeural", "", "晓伊·清亮"),
    ("zh-CN-liaoning-XiaobeiNeural", "", "晓北·东北"),
)


async def list_voices(show_all: bool, female: bool) -> None:
    from edge_tts import list_voices as edge_list

    voices = await edge_list()
    recommended = FEMALE_RECOMMENDED if female else MALE_RECOMMENDED
    rec_names = {x[0] for x in recommended}
    gender = "Female" if female else "Male"

    for v in sorted(voices, key=lambda x: x["ShortName"]):
        locale = v.get("Locale", "")
        if not show_all and not locale.startswith("zh"):
            continue
        if not show_all and v.get("Gender") != gender:
            continue
        mark = " *" if v["ShortName"] in rec_names else ""
        print(f"{v['ShortName']:35} {v.get('FriendlyName', '')}{mark}")

    print("\n推荐试听：")
    for voice, style, label in recommended:
        style_arg = f" --style {style}" if style else ""
        print(f"  {label}: python3 list_tts_voices.py --try {voice}{style_arg}")


async def try_voice(
    name: str,
    rate: str,
    volume: str,
    pitch: str,
    style: str,
    styledegree: str,
) -> None:
    tts = TtsConfig(
        backend="edge",
        voice=name,
        rate=rate,
        volume=volume,
        pitch=pitch,
        style=style,
        styledegree=styledegree,
    )
    style_note = f" style={style} degree={styledegree}" if style else ""
    print(f"试听: {name} rate={rate} volume={volume} pitch={pitch}{style_note}")
    print(f"文本: {SAMPLE}")
    with tempfile.TemporaryDirectory() as td:
        mp3 = Path(td) / "try.mp3"
        await text_to_speech_file(SAMPLE, mp3, tts)
        play_mp3(mp3)


def main() -> None:
    parser = argparse.ArgumentParser(description="edge-tts 中文音色试听")
    parser.add_argument("--all", action="store_true", help="显示全部中文音色")
    parser.add_argument("--female", action="store_true", help="列出女声（默认列出男声）")
    parser.add_argument("--try", dest="voice", metavar="VOICE", help="试听指定音色")
    parser.add_argument("--rate", default="-10%", help="语速，如 -10%")
    parser.add_argument("--volume", default="-8%", help="音量，如 -8%")
    parser.add_argument("--pitch", default="-4Hz", help="音高，如 -4Hz")
    parser.add_argument("--style", default="", help="情感风格，如 narrative-relaxed")
    parser.add_argument("--styledegree", default="1.2", help="风格强度，如 1.2")
    args = parser.parse_args()

    if args.voice:
        asyncio.run(
            try_voice(
                args.voice,
                args.rate,
                args.volume,
                args.pitch,
                args.style,
                args.styledegree,
            )
        )
    else:
        asyncio.run(list_voices(args.all, args.female))


if __name__ == "__main__":
    main()
