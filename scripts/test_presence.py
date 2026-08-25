#!/usr/bin/env python3
"""陪伴节奏模块自检。"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from companion_presence import (
    farewell_line,
    hours_since_last_seen,
    is_goodbye,
    pick_absence_opening,
    presence_context_block,
    silence_prompt,
    time_of_day_bucket,
)


def main() -> None:
    errors = 0
    print("=== presence 自检 ===\n")

    h = hours_since_last_seen("2020-01-01 08:00")
    print(f"hours_since (old): {h}")
    if h is None or h < 1000:
        print("!! hours_since_last_seen")
        errors += 1
    else:
        print("OK hours_since")

    bucket = time_of_day_bucket()
    print(f"time bucket: {bucket}")

    ctx = presence_context_block("2020-01-01", "很累", "小明")
    if not ctx:
        print("!! presence_context empty")
        errors += 1
    else:
        print("OK presence_context")

    text, emo = pick_absence_opening(
        "2020-01-01",
        "失眠",
        ["听见你了……"],
        "阿雾",
    )
    print(f"absence opening: {text[:60]}… [{emo}]")

    st, _ = silence_prompt()
    print(f"silence: {st}")

    fw, _ = farewell_line()
    print(f"farewell: {fw}")

    for s in ("晚安", "拜拜", "今天好累"):
        print(f"  goodbye '{s}': {is_goodbye(s)}")

    print(f"\n完成。错误: {errors}")
    sys.exit(errors)


if __name__ == "__main__":
    main()
