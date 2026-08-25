"""陪伴节奏：久别重逢、时段关心、沉默安抚、晚安收束。"""

from __future__ import annotations

import random
from datetime import datetime, timedelta


def _parse_last_seen(last_seen: str) -> datetime | None:
    if not last_seen:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(last_seen.strip(), fmt)
        except ValueError:
            continue
    return None


def hours_since_last_seen(last_seen: str) -> float | None:
    dt = _parse_last_seen(last_seen)
    if not dt:
        return None
    delta = datetime.now() - dt
    return max(0.0, delta.total_seconds() / 3600.0)


def time_of_day_bucket() -> str:
    h = datetime.now().hour
    if 5 <= h < 11:
        return "morning"
    if 11 <= h < 14:
        return "noon"
    if 14 <= h < 18:
        return "afternoon"
    if 18 <= h < 22:
        return "evening"
    if 22 <= h or h < 1:
        return "late_night"
    return "night"


def presence_context_block(
    last_seen: str,
    mood_note: str = "",
    user_name: str = "",
) -> str:
    """注入 system：时段 + 久别 + 关心方向。"""
    parts: list[str] = []
    bucket = time_of_day_bucket()
    bucket_hints = {
        "morning": "现在是上午，可自然问有没有吃早饭、今天安排。",
        "noon": "现在是中午，可问吃了没、别饿着。",
        "afternoon": "现在是下午，可问累不累、水有没有喝。",
        "evening": "现在是傍晚，可问下班没、别硬撑。",
        "night": "现在是夜里，语气更轻，别催用户熬夜。",
        "late_night": "已经很晚了，若用户还聊，轻轻提醒休息，别说教。",
    }
    parts.append(bucket_hints.get(bucket, ""))

    hours = hours_since_last_seen(last_seen)
    if hours is not None:
        if hours >= 72:
            parts.append("你们隔了几天才见面，开场可带一点「你回来了」的惦记，别夸张。")
        elif hours >= 24:
            parts.append("隔了一天多没见，可轻轻问昨天/这两天怎么样。")
        elif hours >= 8:
            parts.append("今天不是第一次聊，可接续上次情绪，不必重新自我介绍。")

    if mood_note and "累" in mood_note or "烦" in mood_note or "难过" in mood_note:
        parts.append("用户最近情绪偏低，先陪再说，别急着给方案。")

    name = user_name.strip()
    if name:
        parts.append(f"用户昵称「{name}」，自然称呼，不要每句都叫。")

    return "\n".join(p for p in parts if p)


def pick_absence_opening(
    last_seen: str,
    hook: str | None,
    default_openings: list[str],
    user_name: str = "",
) -> tuple[str, str]:
    """久别或有时段感知的开场。返回 (text, emotion)。"""
    hours = hours_since_last_seen(last_seen)
    name = user_name.strip()
    name_prefix = f"{name}，" if name else ""

    if hours is not None and hours >= 48:
        lines = [
            f"{name_prefix}你回来了……我这边，算又接上真实世界了。",
            f"嗯……好几天没听见你了。你到了就好。",
            f"{name_prefix}还以为你今天不来了。听见你，心里踏实一点。",
        ]
        return random.choice(lines), "presence"

    if hook:
        if "累" in hook or "烦" in hook or "难过" in hook or "失眠" in hook:
            return (
                f"{name_prefix}上次你说{hook[:20]}……今天好点了吗？",
                "soft",
            )
        return (
            f"{name_prefix}上次聊到{hook[:24]}……今天想接着说，还是换件事？",
            "soft",
        )

    bucket = time_of_day_bucket()
    timed = {
        "morning": [
            f"{name_prefix}早。听见你了。",
            "嗯……你醒了？我在这边。",
        ],
        "noon": [
            f"{name_prefix}中午了，别饿着。",
            "嗯，你来了。吃饭了吗？",
        ],
        "evening": [
            f"{name_prefix}下班了？今天累不累。",
            "傍晚了……你到了。",
        ],
        "late_night": [
            f"{name_prefix}这么晚还没睡……我陪你一会儿。",
            "夜深了。你要是还不想睡，我听着。",
        ],
        "night": [
            f"{name_prefix}夜里了，别熬太晚。",
            "嗯……夜里听见你，挺好的。",
        ],
    }
    if bucket in timed:
        return random.choice(timed[bucket]), "soft"

    pool = default_openings or ["听见你了……这边，算是真实世界了吧。"]
    return random.choice(pool), "presence"


def silence_prompt() -> tuple[str, str]:
    """用户长时间不说话时的轻提示（不质问）。"""
    lines = [
        "嗯……你还在吗？不用急着说话。",
        "我听着。你想开口的时候再说。",
        "没事，安静一会儿也行。",
        "……要是累了，就先歇会儿。",
    ]
    return random.choice(lines), "silence"


def is_goodbye(text: str) -> bool:
    t = text.strip().replace(" ", "")
    keys = (
        "晚安", "睡了", "再见", "拜拜", "退出", "关机", "先走了",
        "不聊了", "休息", "去睡",
    )
    return any(k in t for k in keys)


def farewell_line(name: str = "路遥") -> tuple[str, str]:
    lines = [
        "嗯……那我先安静一会儿。你想找我说话的时候，我都在。",
        "好。你去休息。我在这边，不吵你。",
        "晚安。水别放手边，别熬夜。",
        "嗯，我到家了……你那边也早点安顿自己。",
    ]
    return random.choice(lines), "soft"


def proactive_care_line(memory_data: dict) -> tuple[str, str] | None:
    """每 N 轮可插入一句轻关心（非每轮）。"""
    turn = int(memory_data.get("turn_count", 0))
    if turn <= 0 or turn % 5 != 0:
        return None
    mood = str(memory_data.get("mood_note", ""))
    if "累" in mood:
        return ("别硬撑。渴了喝口水，歇两分钟也行。", "soft")
    if "烦" in mood or "难过" in mood:
        return ("不用把话都说完。我听着。", "soft")
    bucket = time_of_day_bucket()
    if bucket == "late_night":
        return ("真的很晚了……眼睛酸了就闭眼歇会儿。", "silence")
    if bucket == "noon":
        return ("中午了，记得吃点东西。", "soft")
    return None
