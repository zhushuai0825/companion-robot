"""录音、Vosk 识别、TTS 播报（voice_chat / companion 共用）。

TTS 后端：
  edge  — Microsoft Edge 在线神经语音（edge-tts，需联网）
  piper — 本地 Piper 模型（离线，需自行下载 .onnx）
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import shutil
import ssl
import struct
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

import certifi
from dotenv import load_dotenv
from vosk import KaldiRecognizer, Model, SetLogLevel

load_dotenv(Path(__file__).resolve().parent / ".env")
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MIC = os.getenv("MIC_DEVICE", "").strip()
SPK = os.getenv("SPK_DEVICE", "").strip()
PLAYBACK_BACKEND = os.getenv("PLAYBACK_BACKEND", "aplay").strip()
RECORD_SECONDS = int(os.getenv("RECORD_SECONDS", "5"))
VAD_ENERGY = int(os.getenv("VAD_ENERGY", "450"))
BARGE_IN_ENERGY = int(os.getenv("BARGE_IN_ENERGY", "900"))
VAD_CHUNK_MS = int(os.getenv("VAD_CHUNK_MS", "50"))
VAD_SILENCE_END_MS = int(os.getenv("VAD_SILENCE_END_MS", "1400"))
VAD_MIN_SPEECH_MS = int(os.getenv("VAD_MIN_SPEECH_MS", "250"))
RECORD_MAX_SEC = int(os.getenv("RECORD_MAX_SEC", "30"))
LISTEN_TIMEOUT_SEC = int(os.getenv("LISTEN_TIMEOUT_SEC", "0"))
CHUNK_SAMPLES = max(1, 16000 * VAD_CHUNK_MS // 1000)
CHUNK_BYTES = CHUNK_SAMPLES * 2
VOSK_MODEL_DIR = Path(
    os.getenv("VOSK_MODEL_DIR", str(Path.home() / "companion-robot" / "models" / "vosk-cn"))
)

SetLogLevel(-1)
_vosk_model: Model | None = None


@dataclass(frozen=True)
class TtsConfig:
    backend: str = "edge"
    voice: str = "zh-CN-YunxiNeural"
    rate: str = "-12%"
    volume: str = "-8%"
    pitch: str = "-6Hz"
    style: str = ""
    styledegree: str = "1.2"
    piper_model: str = ""
    performative: bool = True


EMOTION_PROFILES: dict[str, tuple[str, str, str]] = {
    "neutral": ("-12%", "-8%", "-6Hz"),
    "soft": ("-14%", "-10%", "-8Hz"),
    "happy": ("-8%", "-5%", "-2Hz"),
    "silence": ("-18%", "-14%", "-10Hz"),
    "sad": ("-16%", "-12%", "-8Hz"),
    "presence": ("-10%", "-6%", "-4Hz"),
}


def apply_emotion(base: TtsConfig, emotion: str) -> TtsConfig:
    rate, volume, pitch = EMOTION_PROFILES.get(
        emotion.lower(), EMOTION_PROFILES["neutral"]
    )
    return TtsConfig(
        backend=base.backend,
        voice=base.voice,
        rate=rate,
        volume=volume,
        pitch=pitch,
        style=base.style,
        styledegree=base.styledegree,
        piper_model=base.piper_model,
        performative=base.performative,
    )


def _split_clauses(text: str) -> list[str]:
    import re

    parts = [p.strip() for p in re.split(r"(?<=[。！？!?])", text) if p.strip()]
    return parts or [text.strip()]


def _tts_key(cfg: TtsConfig) -> tuple:
    return (
        cfg.backend,
        cfg.voice,
        cfg.rate,
        cfg.volume,
        cfg.pitch,
        cfg.style,
        cfg.styledegree,
        cfg.piper_model,
        cfg.performative,
    )


# 树莓派上实测可用的备用链（男声优先）
TTS_FALLBACK_CHAIN: tuple[TtsConfig, ...] = (
    TtsConfig("edge", "zh-CN-YunxiNeural", "-12%", "-8%", "-6Hz", "", "", "", True),
    TtsConfig("edge", "zh-CN-YunxiNeural", "-8%", "-6%", "-4Hz", "", "", "", True),
    TtsConfig("edge", "zh-CN-YunjianNeural", "-8%", "-6%", "-4Hz", "", "", "", True),
    TtsConfig("edge", "zh-CN-YunxiNeural", "+0%", "+0%", "+0Hz", "", "", "", True),
)


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


def _parse_alsa_list(text: str) -> list[tuple[int, int, str]]:
    devices: list[tuple[int, int, str]] = []
    card: int | None = None
    for line in text.splitlines():
        inline = re.match(r"^card (\d+):.*device (\d+):", line)
        if inline:
            devices.append((int(inline.group(1)), int(inline.group(2)), line.strip()))
            card = int(inline.group(1))
            continue
        m_card = re.match(r"^card (\d+):", line)
        if m_card:
            card = int(m_card.group(1))
            continue
        m_dev = re.match(r"^\s+device (\d+):", line)
        if m_dev and card is not None:
            devices.append((card, int(m_dev.group(1)), line.strip()))
    return devices


def _probe_playback(device: str, test_wav: Path) -> bool:
    return _probe_aplay(device, test_wav)


def _make_probe_wav(path: Path) -> None:
    pcm = struct.pack("<1600h", *([200] * 800 + [0] * 800))
    _write_pcm_wav(path, pcm)


def discover_capture_device() -> str | None:
    try:
        out = subprocess.run(
            ["arecord", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except OSError:
        return None
    if out.returncode != 0:
        return None
    devices = _parse_alsa_list(out.stdout)
    usb = [d for d in devices if "USB" in d[2].upper()]
    pick = usb[0] if usb else (devices[0] if devices else None)
    if not pick:
        return None
    return f"plughw:{pick[0]},{pick[1]}"


def _load_voice_yaml() -> dict:
    try:
        from companion_persona import load_companion_config

        return load_companion_config().get("voice") or {}
    except ImportError:
        return {}


def _aplay_list_output() -> str:
    try:
        out = subprocess.run(
            ["aplay", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout if out.returncode == 0 else ""
    except OSError:
        return ""


def _list_aplay_L_devices() -> list[str]:
    try:
        out = subprocess.run(
            ["aplay", "-L"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except OSError:
        return []
    if out.returncode != 0:
        return []
    names: list[str] = []
    for line in out.stdout.splitlines():
        if line and not line[0].isspace():
            name = line.strip()
            if name and name != "null":
                names.append(name)
    return names


def _pipewire_has_hardware_sink() -> bool:
    if not shutil.which("pw-cli"):
        return False
    try:
        out = subprocess.run(
            ["pw-cli", "ls", "Node"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except OSError:
        return False
    if out.returncode != 0:
        return False
    blocks = out.stdout.split("id ")
    for block in blocks:
        if "media.class = \"Audio/Sink\"" not in block:
            continue
        if "auto_null" in block or "Dummy Output" in block:
            continue
        return True
    return False


def _playback_probe_order(preferred: str = "") -> list[str]:
    names: list[str] = []
    if preferred:
        names.append(preferred)
    for name in _list_aplay_L_devices():
        if name in names or name == "null":
            continue
        if any(
            k in name
            for k in (
                "usb",
                "USB",
                "Device",
                "hdmi",
                "sysdefault",
                "plughw",
                "default:CARD",
            )
        ):
            names.append(name)
    for card, dev, line in _parse_alsa_list(_aplay_list_output()):
        plug = f"plughw:{card},{dev}"
        if plug not in names:
            names.append(plug)
        card_name = line.split(":", 1)[0].replace("card ", "").split()[0]
        if "[" in line:
            bracket = line.split("[", 1)[1].split("]", 1)[0]
            named = f"plughw:CARD={bracket},DEV={dev}"
            if named not in names:
                names.append(named)
    if "default" not in names:
        names.append("default")
    return names


def _probe_aplay(device: str, test_wav: Path) -> bool:
    try:
        result = subprocess.run(
            ["aplay", "-q", "-D", device, str(test_wav)],
            capture_output=True,
            timeout=4,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def find_working_playback(
    test_wav: Path,
    preferred: str = "",
) -> tuple[str, str]:
    """返回 (设备名或 default, backend: aplay|pw-play)。都失败则 ('', '')。"""
    for device in _playback_probe_order(preferred):
        if _probe_aplay(device, test_wav):
            return device, "aplay"
    if _pipewire_has_hardware_sink() and shutil.which("pw-play"):
        try:
            result = subprocess.run(
                ["pw-play", str(test_wav)],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                return preferred or "default", "pw-play"
        except OSError:
            pass
    return "", ""


def is_speaker_available() -> bool:
    with tempfile.TemporaryDirectory() as td:
        test_wav = Path(td) / "probe.wav"
        _make_probe_wav(test_wav)
        device, _ = find_working_playback(test_wav, SPK)
        return bool(device)


def discover_playback_device() -> str | None:
    with tempfile.TemporaryDirectory() as td:
        test_wav = Path(td) / "probe.wav"
        _make_probe_wav(test_wav)
        device, backend = find_working_playback(test_wav)
        if device:
            global PLAYBACK_BACKEND
            PLAYBACK_BACKEND = backend
            return device if backend == "aplay" else SPK or "default"
    return None


def resolve_audio_devices() -> tuple[str, str]:
    global MIC, SPK, PLAYBACK_BACKEND
    yaml_voice = _load_voice_yaml()
    apply_voice_settings(yaml_voice)

    mic = os.getenv("MIC_DEVICE", "").strip() or str(yaml_voice.get("mic_device", "")).strip()
    spk = os.getenv("SPK_DEVICE", "").strip() or str(yaml_voice.get("spk_device", "")).strip()
    if not mic:
        mic = discover_capture_device() or "plughw:3,0"

    with tempfile.TemporaryDirectory() as td:
        test_wav = Path(td) / "probe.wav"
        _make_probe_wav(test_wav)
        working, backend = find_working_playback(test_wav, preferred=spk)
        if working:
            if backend == "aplay":
                spk = working
            PLAYBACK_BACKEND = backend
        elif not spk:
            spk = "default"

    MIC = mic
    SPK = spk
    os.environ.setdefault("PLAYBACK_BACKEND", PLAYBACK_BACKEND)
    return MIC, SPK


def ensure_playback_ready() -> None:
    resolve_audio_devices()
    if not is_speaker_available():
        raise RuntimeError(audio_setup_hint())


def usb_capture_only_cards() -> list[str]:
    """列出仅有录音、无播放的 USB 声卡说明。"""
    root = Path("/proc/asound")
    notes: list[str] = []
    if not root.is_dir():
        return notes
    for card_dir in sorted(root.glob("card*")):
        if not card_dir.is_dir():
            continue
        stream = card_dir / "stream0"
        usbid = card_dir / "usbid"
        if not stream.exists():
            continue
        text = stream.read_text(encoding="utf-8", errors="replace")
        if "Capture:" in text and "Playback:" not in text:
            card_id = (card_dir / "id").read_text(encoding="utf-8").strip()
            chip = usbid.read_text(encoding="utf-8").strip() if usbid.exists() else ""
            notes.append(f"card {card_dir.name[4:]} ({card_id}, {chip})：仅麦克风，无 USB 播放")
    return notes


def describe_audio_hardware() -> str:
    lines = [
        "当前树莓派能用的声音设备：",
        f"  麦克风 → {MIC or '未配置'}",
        f"  扬声器 → {SPK or '未配置'}（后端 {PLAYBACK_BACKEND}）",
    ]
    caps = usb_capture_only_cards()
    if caps:
        lines.append("")
        lines.append("USB 声卡详情（Linux 视角）：")
        for c in caps:
            lines.append(f"  · {c}")
        lines.append(
            "  说明：设备外壳上可能有喇叭孔，但 USB 只接了麦克风线路，"
            "树莓派无法通过它播放 TTS。"
        )
    if _aplay_list_output() and not is_speaker_available():
        lines.append(
            "  HDMI 音响需接显示器并点亮屏幕；未接 HDMI 时 error 524 是正常的。"
        )
    return "\n".join(lines)


def audio_setup_hint() -> str:
    hdmi_note = ""
    if _aplay_list_output() and not is_speaker_available():
        hdmi_note = (
            "\n（Pi5 HDMI 音频需要接显示器/电视并点亮屏幕；没接 HDMI 会报 error 524，属正常。）\n"
        )
    usb_note = ""
    caps = usb_capture_only_cards()
    if caps:
        usb_note = (
            "\n你的 USB PnP Sound Device（芯片 PCM2902）在系统里只有麦克风通道，"
            "没有播放通道，树莓派无法通过它出声。\n"
        )
    return (
        "找不到可用的扬声器（aplay 全部失败）。\n"
        f"{usb_note}"
        "请任选其一：\n"
        "  1. 另插带播放的 USB 音箱/耳机（推荐，与小麦克风可同时使用）\n"
        "  2. HDMI 接电视/显示器音响，并确保屏幕点亮\n"
        f"{hdmi_note}"
        "然后运行: python3 scripts/test_audio.py\n"
        "或在 src/.env 设置 MIC_DEVICE / SPK_DEVICE（见 test 输出）。\n"
        "暂时只想看文字：config/companion.yaml 设 voice.speaker_optional: true"
    )


def start_playback(wav_path: Path) -> subprocess.Popen:
    backend = os.getenv("PLAYBACK_BACKEND", PLAYBACK_BACKEND)
    if backend == "pw-play" and shutil.which("pw-play"):
        return subprocess.Popen(
            ["pw-play", str(wav_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    return subprocess.Popen(
        ["aplay", "-q", "-D", SPK, str(wav_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _rms(pcm: bytes) -> float:
    if len(pcm) < 2:
        return 0.0
    count = len(pcm) // 2
    samples = struct.unpack(f"<{count}h", pcm[: count * 2])
    return math.sqrt(sum(s * s for s in samples) / count)


def _write_pcm_wav(path: Path, pcm: bytes, sample_rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)


def _start_arecord_raw() -> subprocess.Popen:
    return subprocess.Popen(
        [
            "arecord",
            "-D",
            MIC,
            "-f",
            "S16_LE",
            "-r",
            "16000",
            "-c",
            "1",
            "-t",
            "raw",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )


def apply_voice_settings(cfg: dict | None) -> None:
    """从 companion.yaml 的 voice 段写入环境变量（可被 .env 覆盖）。"""
    if not cfg:
        return
    mapping = {
        "listen_timeout_sec": "LISTEN_TIMEOUT_SEC",
        "record_max_sec": "RECORD_MAX_SEC",
        "silence_end_ms": "VAD_SILENCE_END_MS",
        "vad_energy": "VAD_ENERGY",
        "barge_in_energy": "BARGE_IN_ENERGY",
        "mic_device": "MIC_DEVICE",
        "spk_device": "SPK_DEVICE",
        "speaker_optional": "SPEAKER_OPTIONAL",
    }
    for key, env in mapping.items():
        if key in cfg:
            if env not in os.environ or not str(os.environ.get(env, "")).strip():
                os.environ[env] = str(cfg[key])


def capture_utterance(
    path: Path,
    *,
    wait_for_start: bool = True,
    assume_speaking: bool = False,
    listen_timeout_sec: int | None = None,
    silence_end_ms: int | None = None,
    max_seconds: int | None = None,
) -> bool:
    """VAD 录音：可选等待开口；录到静音结束。返回是否录到有效语音。"""
    timeout = listen_timeout_sec if listen_timeout_sec is not None else int(
        os.getenv("LISTEN_TIMEOUT_SEC", str(LISTEN_TIMEOUT_SEC))
    )
    silence_ms = silence_end_ms if silence_end_ms is not None else int(
        os.getenv("VAD_SILENCE_END_MS", str(VAD_SILENCE_END_MS))
    )
    max_sec = max_seconds if max_seconds is not None else int(
        os.getenv("RECORD_MAX_SEC", str(RECORD_MAX_SEC))
    )
    vad_energy = int(os.getenv("VAD_ENERGY", str(VAD_ENERGY)))

    silence_chunks = max(1, silence_ms // VAD_CHUNK_MS)
    min_speech_chunks = max(1, VAD_MIN_SPEECH_MS // VAD_CHUNK_MS)
    max_chunks = max(1, max_sec * 1000 // VAD_CHUNK_MS)
    wait_chunks = max(1, timeout * 1000 // VAD_CHUNK_MS) if timeout > 0 else None

    proc = _start_arecord_raw()
    frames: list[bytes] = []
    speech_started = assume_speaking
    speech_run = min_speech_chunks if assume_speaking else 0
    silence_run = 0
    waited = 0

    try:
        while proc.stdout:
            chunk = proc.stdout.read(CHUNK_BYTES)
            if not chunk:
                break
            level = _rms(chunk)

            if not speech_started:
                if level >= vad_energy:
                    speech_run += 1
                    if speech_run >= min_speech_chunks:
                        speech_started = True
                        frames.append(chunk)
                else:
                    speech_run = 0
                    if wait_chunks is not None:
                        waited += 1
                        if waited >= wait_chunks:
                            return False
            else:
                frames.append(chunk)
                if level < vad_energy:
                    silence_run += 1
                    if silence_run >= silence_chunks:
                        break
                else:
                    silence_run = 0
                if len(frames) >= max_chunks:
                    break
    finally:
        proc.kill()
        proc.wait(timeout=1)

    if not speech_started or not frames:
        return False

    _write_pcm_wav(path, b"".join(frames))
    return True


def record_wav(path: Path, seconds: int | None = None) -> None:
    dur = seconds or RECORD_SECONDS
    cmd = [
        "arecord",
        "-D",
        MIC,
        "-d",
        str(dur),
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
    print(f"录音 {dur} 秒，请说话…")
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


def _clean_tts_text(text: str) -> str:
    from edge_tts.communicate import remove_incompatible_characters

    return remove_incompatible_characters(text.strip())


def _build_expressive_ssml(tts: TtsConfig, text: str) -> str:
    inner = escape(_clean_tts_text(text))
    prosody = (
        f"<prosody pitch='{tts.pitch}' rate='{tts.rate}' volume='{tts.volume}'>"
        f"{inner}</prosody>"
    )
    if tts.style:
        prosody = (
            f"<mstts:express-as style='{tts.style}' "
            f"styledegree='{tts.styledegree or '1.0'}'>"
            f"{prosody}</mstts:express-as>"
        )
    return (
        "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' "
        "xmlns:mstts='http://www.w3.org/2001/mstts' xml:lang='zh-CN'>"
        f"<voice name='{tts.voice}'>{prosody}</voice></speak>"
    )


async def _edge_save_mp3(ssml: str, mp3: Path) -> None:
    import aiohttp
    from edge_tts.communicate import (
        connect_id,
        date_to_string,
        get_headers_and_data,
        ssml_headers_plus_data,
    )
    from edge_tts.constants import SEC_MS_GEC_VERSION, WSS_HEADERS, WSS_URL
    from edge_tts.drm import DRM
    from edge_tts.exceptions import NoAudioReceived

    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    audio_parts: list[bytes] = []
    audio_received = False

    async with aiohttp.ClientSession(trust_env=True) as session:
        async with session.ws_connect(
            f"{WSS_URL}&ConnectionId={connect_id()}"
            f"&Sec-MS-GEC={DRM.generate_sec_ms_gec()}"
            f"&Sec-MS-GEC-Version={SEC_MS_GEC_VERSION}",
            compress=15,
            headers=DRM.headers_with_muid(WSS_HEADERS),
            ssl=ssl_ctx,
        ) as websocket:
            await websocket.send_str(
                f"X-Timestamp:{date_to_string()}\r\n"
                "Content-Type:application/json; charset=utf-8\r\n"
                "Path:speech.config\r\n\r\n"
                '{"context":{"synthesis":{"audio":{"metadataoptions":{'
                '"sentenceBoundaryEnabled":"true","wordBoundaryEnabled":"false"'
                "},"
                '"outputFormat":"audio-24khz-48kbitrate-mono-mp3"'
                "}}}}\r\n"
            )
            await websocket.send_str(
                ssml_headers_plus_data(connect_id(), date_to_string(), ssml)
            )

            async for received in websocket:
                if received.type == aiohttp.WSMsgType.BINARY:
                    if len(received.data) < 2:
                        continue
                    header_length = int.from_bytes(received.data[:2], "big")
                    if header_length > len(received.data):
                        continue
                    parameters, data = get_headers_and_data(
                        received.data, header_length
                    )
                    if parameters.get(b"Path") != b"audio":
                        continue
                    content_type = parameters.get(b"Content-Type", None)
                    if content_type not in (b"audio/mpeg", None):
                        continue
                    if content_type is None and len(data) == 0:
                        continue
                    if len(data) == 0:
                        continue
                    audio_received = True
                    audio_parts.append(data)
                elif received.type == aiohttp.WSMsgType.TEXT:
                    encoded_data = received.data.encode("utf-8")
                    parameters, _ = get_headers_and_data(
                        encoded_data, encoded_data.find(b"\r\n\r\n")
                    )
                    if parameters.get(b"Path") == b"turn.end":
                        break
                elif received.type == aiohttp.WSMsgType.ERROR:
                    raise RuntimeError(received.data or "edge-tts websocket error")

    if not audio_received:
        raise NoAudioReceived(
            "No audio was received. Please verify that your parameters are correct."
        )
    mp3.write_bytes(b"".join(audio_parts))


async def _edge_synthesize(text: str, mp3: Path, tts: TtsConfig) -> None:
    import edge_tts

    if tts.style:
        try:
            ssml = _build_expressive_ssml(tts, text)
            await _edge_save_mp3(ssml, mp3)
            return
        except Exception:
            pass

    communicate = edge_tts.Communicate(
        text,
        voice=tts.voice,
        rate=tts.rate,
        volume=tts.volume,
        pitch=tts.pitch,
    )
    await communicate.save(str(mp3))


def _piper_synthesize(text: str, wav: Path, model_path: Path) -> None:
    try:
        from piper import PiperVoice
    except ImportError as e:
        raise RuntimeError(
            "未安装 piper-tts。在 venv 内执行: pip install piper-tts"
        ) from e

    if not model_path.exists():
        raise RuntimeError(f"找不到 Piper 模型: {model_path}")

    voice = PiperVoice.load(str(model_path))
    with wave.open(str(wav), "wb") as wf:
        voice.synthesize(_clean_tts_text(text), wf)


async def text_to_speech_file(text: str, out: Path, tts: TtsConfig) -> None:
    candidates: list[TtsConfig] = [tts]
    for fb in TTS_FALLBACK_CHAIN:
        if _tts_key(fb) not in {_tts_key(c) for c in candidates}:
            candidates.append(fb)

    last_err: Exception | None = None
    for cfg in candidates:
        try:
            if cfg.backend == "piper":
                wav = out.with_suffix(".piper.wav")
                model = Path(cfg.piper_model or os.getenv("PIPER_MODEL", "")).expanduser()
                _piper_synthesize(text, wav, model)
                if wav.exists() and wav.stat().st_size > 500:
                    if out.suffix.lower() == ".mp3":
                        subprocess.run(
                            [
                                "ffmpeg",
                                "-y",
                                "-i",
                                str(wav),
                                str(out),
                            ],
                            check=True,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        wav.unlink(missing_ok=True)
                    else:
                        wav.rename(out)
                    if cfg != tts:
                        print(f"（Piper 模型 {model.name} 已用于播报）")
                    return
                last_err = RuntimeError("Piper 生成的音频过小")
                continue

            mp3 = out if out.suffix.lower() == ".mp3" else out.with_suffix(".mp3")
            await _edge_synthesize(text, mp3, cfg)
            if mp3.exists() and mp3.stat().st_size > 500:
                if mp3 != out:
                    mp3.rename(out)
                if cfg != tts:
                    style_note = f" style={cfg.style}" if cfg.style else ""
                    print(
                        f"（音色 {tts.voice} 不可用，已改用 {cfg.voice}"
                        f" rate={cfg.rate}{style_note}）"
                    )
                return
            last_err = RuntimeError("生成的音频文件过小")
        except Exception as e:
            last_err = e

    msg = "语音合成失败。"
    if tts.backend == "piper":
        msg += " Piper 本地模型未就绪，可在 config/companion.yaml 改 tts_backend: edge"
    else:
        msg += " 微软 edge-tts 未返回音频（需联网）。"
    if last_err:
        msg += f" 原因: {last_err}"
    msg += " 试听: python3 list_tts_voices.py --try zh-CN-YunxiNeural"
    raise RuntimeError(msg)


async def text_to_speech_performative(
    text: str,
    out: Path,
    base_tts: TtsConfig,
    emotion: str = "neutral",
) -> None:
    """按情绪调节 TTS；多句时后半段更慢更轻，增加表演感。"""
    tts = apply_emotion(base_tts, emotion)
    if not base_tts.performative:
        await text_to_speech_file(text, out, tts)
        return

    parts = _split_clauses(text)
    if len(parts) <= 1:
        await text_to_speech_file(text, out, tts)
        return

    temp_mp3s: list[Path] = []
    tail_emotion = emotion if emotion in ("soft", "sad", "silence") else "soft"
    for i, part in enumerate(parts):
        part_tts = tts if i == 0 else apply_emotion(base_tts, tail_emotion)
        part_path = out.with_suffix(f".part{i}.mp3")
        await text_to_speech_file(part, part_path, part_tts)
        temp_mp3s.append(part_path)

    list_file = out.with_suffix(".concat.txt")
    list_file.write_text(
        "\n".join(f"file '{p.resolve()}'" for p in temp_mp3s),
        encoding="utf-8",
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(out),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for p in temp_mp3s:
        p.unlink(missing_ok=True)
    list_file.unlink(missing_ok=True)


def play_audio(path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix == ".wav":
        subprocess.run(["aplay", "-q", "-D", SPK, str(path)], check=True)
        return

    wav = path.with_suffix(".play.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(path), str(wav)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    proc = start_playback(wav)
    proc.wait()
    if proc.returncode != 0:
        err = (proc.stderr.read() or b"").decode(errors="replace").strip()
        raise RuntimeError(f"播放失败 ({SPK}): {err}")
    wav.unlink(missing_ok=True)


def play_audio_interruptible(path: Path) -> bool:
    """播放音频；用户开口则打断播放。返回 True 表示被打断。"""
    suffix = path.suffix.lower()
    wav = path
    temp_wav: Path | None = None
    if suffix != ".wav":
        temp_wav = path.with_suffix(".play.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(path), str(temp_wav)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        wav = temp_wav

    barge_energy = int(os.getenv("BARGE_IN_ENERGY", str(BARGE_IN_ENERGY)))
    player = start_playback(wav)
    mic = _start_arecord_raw()
    interrupted = False
    speech_run = 0
    trigger_chunks = max(3, 200 // VAD_CHUNK_MS)

    try:
        while player.poll() is None and mic.stdout:
            chunk = mic.stdout.read(CHUNK_BYTES)
            if not chunk:
                break
            if _rms(chunk) >= barge_energy:
                speech_run += 1
                if speech_run >= trigger_chunks:
                    interrupted = True
                    player.kill()
                    break
            else:
                speech_run = max(0, speech_run - 1)
    finally:
        mic.kill()
        mic.wait(timeout=1)
        if player.poll() is None:
            player.kill()
        player.wait(timeout=2)
        if temp_wav and temp_wav.exists():
            temp_wav.unlink(missing_ok=True)

    return interrupted


async def speak_performative_interruptible(
    text: str,
    work_dir: Path,
    base_tts: TtsConfig,
    emotion: str = "neutral",
) -> bool:
    """按句播报，支持打断。返回 True 表示用户中途开口。"""
    try:
        from audio_duplex import get_duplex

        duplex = get_duplex()
        use_duplex = duplex._alive
    except ImportError:
        use_duplex = False
        duplex = None

    tts = apply_emotion(base_tts, emotion)
    parts = _split_clauses(text)
    if not base_tts.performative or len(parts) <= 1:
        mp3 = work_dir / "speech.mp3"
        await text_to_speech_file(text, mp3, tts)
        if use_duplex and duplex is not None:
            return duplex.play_interruptible(mp3)
        return play_audio_interruptible(mp3)

    tail_emotion = emotion if emotion in ("soft", "sad", "silence") else "soft"
    for i, part in enumerate(parts):
        part_tts = tts if i == 0 else apply_emotion(base_tts, tail_emotion)
        part_mp3 = work_dir / f"speech.part{i}.mp3"
        await text_to_speech_file(part, part_mp3, part_tts)
        if use_duplex and duplex is not None:
            interrupted = duplex.play_interruptible(part_mp3)
        else:
            interrupted = play_audio_interruptible(part_mp3)
        part_mp3.unlink(missing_ok=True)
        if interrupted:
            return True
    return False


def play_mp3(mp3: Path) -> None:
    play_audio(mp3)
