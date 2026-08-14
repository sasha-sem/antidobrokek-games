from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class VideoProbe:
    duration_ms: int
    size_bytes: int
    video_codec: str
    pixel_format: str
    width: int
    height: int
    fps: float
    audio_codec: str | None


def _rate(value: str) -> float:
    numerator, _, denominator = value.partition("/")
    denominator_value = float(denominator or 1)
    return float(numerator or 0) / denominator_value if denominator_value else 0.0


def probe_video(path: Path, ffprobe_binary: str = "ffprobe") -> VideoProbe:
    command = [
        ffprobe_binary,
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    payload: dict[str, Any] = json.loads(result.stdout)
    streams = payload.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if not video:
        raise ValueError(f"В файле {path.name} нет видеопотока")
    duration = float(payload.get("format", {}).get("duration") or video.get("duration") or 0)
    return VideoProbe(
        duration_ms=max(1, round(duration * 1000)),
        size_bytes=path.stat().st_size,
        video_codec=str(video.get("codec_name") or ""),
        pixel_format=str(video.get("pix_fmt") or ""),
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        fps=_rate(str(video.get("avg_frame_rate") or "0/1")),
        audio_codec=str(audio.get("codec_name")) if audio else None,
    )


def validate_browser_video(
    probe: VideoProbe,
    *,
    max_duration_seconds: float,
    max_size_bytes: int,
) -> None:
    if probe.video_codec != "h264":
        raise ValueError(f"Ожидался H.264, получен {probe.video_codec}")
    if probe.pixel_format != "yuv420p":
        raise ValueError(f"Ожидался yuv420p, получен {probe.pixel_format}")
    if probe.width > 1280 or probe.height > 720:
        raise ValueError(f"Разрешение {probe.width}x{probe.height} превышает 1280x720")
    if probe.fps > 30.05:
        raise ValueError(f"FPS {probe.fps:.2f} превышает 30")
    if probe.audio_codec not in (None, "aac"):
        raise ValueError(f"Аудиокодек {probe.audio_codec} не поддерживается")
    if probe.duration_ms > max_duration_seconds * 1000 + 250:
        raise ValueError(f"Длительность {probe.duration_ms / 1000:.2f} с превышает лимит")
    if probe.size_bytes > max_size_bytes:
        raise ValueError(f"Файл {probe.size_bytes} байт превышает лимит")


def _nvenc_available(ffmpeg_binary: str) -> bool:
    result = subprocess.run(
        [ffmpeg_binary, "-hide_banner", "-encoders"], capture_output=True, text=True
    )
    return result.returncode == 0 and "h264_nvenc" in result.stdout


def _transcode_command(
    ffmpeg_binary: str,
    source: Path,
    target: Path,
    encoder: str,
) -> list[str]:
    video_options = (
        ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23"]
        if encoder == "h264_nvenc"
        else ["-c:v", "libx264", "-preset", "medium", "-crf", "23"]
    )
    return [
        ffmpeg_binary,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        "scale=1280:720:force_original_aspect_ratio=decrease,"
        "pad=1280:720:(ow-iw)/2:(oh-ih)/2:black,fps=30,format=yuv420p",
        *video_options,
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        "-map_metadata",
        "-1",
        str(target),
    ]


def transcode_video(
    source: Path,
    target: Path,
    *,
    ffmpeg_binary: str = "ffmpeg",
    ffprobe_binary: str = "ffprobe",
    max_duration_seconds: float = 60,
    max_size_bytes: int = 50 * 1024 * 1024,
) -> VideoProbe:
    if not shutil.which(ffmpeg_binary):
        raise FileNotFoundError(f"FFmpeg не найден: {ffmpeg_binary}")
    target.parent.mkdir(parents=True, exist_ok=True)
    encoders = ["h264_nvenc", "libx264"] if _nvenc_available(ffmpeg_binary) else ["libx264"]
    errors: list[str] = []
    for encoder in encoders:
        result = subprocess.run(
            _transcode_command(ffmpeg_binary, source, target, encoder),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            break
        target.unlink(missing_ok=True)
        errors.append(f"{encoder}: {result.stderr.strip()[-500:]}")
    else:
        raise RuntimeError("FFmpeg не смог перекодировать видео: " + " | ".join(errors))
    probe = probe_video(target, ffprobe_binary)
    validate_browser_video(
        probe,
        max_duration_seconds=max_duration_seconds,
        max_size_bytes=max_size_bytes,
    )
    return probe
