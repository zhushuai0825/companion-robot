#!/usr/bin/env python3
"""听 → DeepSeek → 音箱说出来（树莓派轻量版：Vosk 识别 + edge-tts 播报）。"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
import wave
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from vosk import KaldiRecognizer, Model, SetLogLevel

load_dotenv(Path(__file__).resolve().parent / ".env")
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()
MIC = os.getenv("MIC_DEVICE", "plughw:2,0")
SPK = os.getenv("SPK_DEVICE", "plughw:3,0")
RECORD_SECONDS = int(os.getenv("RECORD_SECONDS", "4"))
VOSK_MODEL_DIR = Path(
    os.getenv("VOSK_MODEL_DIR", str(Path.home() / "companion-robot" / "models" / "vosk-cn"))
)

if not API_KEY:
    raise SystemExit("缺少 DEEPSEEK_API_KEY：请在 companion-robot/.env 里配置")

SetLogLevel(-1)
client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
_vosk_model: Model | None = None


def get_vosk() -> Model:
    global _vosk_model
    if _vosk_model is None:
        if not VOSK_MODEL_DIR.exists():
            raise SystemExit(
                f"找不到 Vosk 模型目录: {VOSK_MODEL_DIR}\n请先下载中文小模型到该路径。"
            )
        print("加载语音识别模型…")
        _vosk_model = Model(str(VOSK_MODEL_DIR))
    return _vosk_model


def record_wav(path: Path) -> None:
    # Vosk 需要 16k 单声道
    cmd = [
        "arecord",
        "-D",
        MIC,
        "-d",
        str(RECORD_SECONDS),
        "-f",
        "S16_LE",
        "-r",
        "16000",
        "-c",
        "1",
        "-t",
        "wav",
        str(path),
    ]
    print(f"录音 {RECORD_SECONDS} 秒，请说话…")
    subprocess.run(cmd, check=True)


def speech_to_text(wav_path: Path) -> str:
    model = get_vosk()
    rec = KaldiRecognizer(model, 16000)
    rec.SetWords(False)
    parts: list[str] = []
    with wave.open(str(wav_path), "rb") as wf:
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() != 16000:
            raise RuntimeError("录音格式必须是 16kHz / 16bit / mono")
        while True:
            data = wf.readframes(4000)
            if not data:
                break
            if rec.AcceptWaveform(data):
                obj = json.loads(rec.Result())
                if obj.get("text"):
                    parts.append(obj["text"])
        final = json.loads(rec.FinalResult())
        if final.get("text"):
            parts.append(final["text"])
    return "".join(parts).strip()


def ask_deepseek(messages: list[dict]) -> str:
    resp = client.chat.completions.create(model=MODEL, messages=messages)
    return (resp.choices[0].message.content or "").strip()


async def text_to_speech_file(text: str, mp3: Path) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice="zh-CN-XiaoxiaoNeural")
    await communicate.save(str(mp3))


def play_mp3(mp3: Path) -> None:
    wav = mp3.with_suffix(".play.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp3), str(wav)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(["aplay", "-D", SPK, str(wav)], check=True)
    wav.unlink(missing_ok=True)


def main() -> None:
    print("语音对话已启动（Vosk + DeepSeek + edge-tts）。")
    print("回车开始说话；输入 q 回车退出。\n")
    messages = [
        {
            "role": "system",
            "content": "你是树莓派上的语音助手。用简短中文回答，一两句即可，方便朗读。",
        }
    ]

    while True:
        cmd = input("准备好了按回车开始录音（q 退出）: ").strip().lower()
        if cmd in {"q", "quit", "exit"}:
            print("再见。")
            break

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            wav = td_path / "in.wav"
            mp3 = td_path / "out.mp3"

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
                print("没听清，请再试一次。")
                continue

            print(f"你说: {user_text}")
            messages.append({"role": "user", "content": user_text})

            print("思考中…")
            try:
                reply = ask_deepseek(messages)
            except Exception as e:
                print(f"DeepSeek 失败: {e}")
                messages.pop()
                continue

            messages.append({"role": "assistant", "content": reply})
            print(f"助手: {reply}")

            print("播报中…")
            try:
                asyncio.run(text_to_speech_file(reply, mp3))
                play_mp3(mp3)
            except Exception as e:
                print(f"播报失败（文字已出）: {e}")


if __name__ == "__main__":
    main()
