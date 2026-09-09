from __future__ import annotations

import mimetypes
import shutil
import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def has_audio(path: Path) -> bool:
    proc = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return bool(proc.stdout.strip())


def detect_type(path: Path | None, text_content: str) -> str:
    if path is None:
        return "TEXT" if text_content.strip() else "NEEDS_REVIEW"
    mime, _ = mimetypes.guess_type(path.name)
    if mime and mime.startswith("video/"):
        return "VIDEO"
    if mime and mime.startswith("image/"):
        return "IMAGE"
    return "NEEDS_REVIEW"


def render_text_story(text: str, out: Path, size=(1080, 1920)) -> Path:
    img = Image.new("RGB", size, (18, 68, 110))
    draw = ImageDraw.Draw(img)
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font = ImageFont.truetype(font_path, 64)
    wrapped = textwrap.fill(text.strip(), width=24)
    box = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=20, align="center")
    w, h = box[2] - box[0], box[3] - box[1]
    draw.multiline_text(((size[0] - w) / 2, (size[1] - h) / 2), wrapped, font=font, fill="white", spacing=20, align="center")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, quality=95)
    return out


def image_with_music(image: Path, music: Path, out: Path, duration: int = 15, volume: int = 18, fade_in: float = 0.5, fade_out: float = 1.0) -> Path:
    fade_out_start = max(0, duration - fade_out)
    run(["ffmpeg", "-y", "-loop", "1", "-i", str(image), "-i", str(music), "-filter_complex", f"[1:a]volume={volume/100},afade=t=in:st=0:d={fade_in},afade=t=out:st={fade_out_start}:d={fade_out}[a]", "-map", "0:v", "-map", "[a]", "-t", str(duration), "-r", "30", "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)])
    return out


def video_with_music(video: Path, music: Path, out: Path, volume: int = 18, fade_in: float = 0.5) -> Path:
    run(["ffmpeg", "-y", "-i", str(video), "-i", str(music), "-filter_complex", f"[1:a]volume={volume/100},afade=t=in:st=0:d={fade_in}[a]", "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-shortest", str(out)])
    return out


def prepare_media(source: Path | None, content_type: str, text_content: str, music: Path | None, out_dir: Path, config: dict[str, str]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = int(float(config.get("STORY_DEFAULT_DURATION_SEC", "15")))
    volume = int(float(config.get("DEFAULT_MUSIC_VOLUME_PERCENT", "18")))
    fade_in = float(config.get("MUSIC_FADE_IN_SEC", "0.5"))
    fade_out = float(config.get("MUSIC_FADE_OUT_SEC", "1"))
    if content_type == "TEXT":
        image = render_text_story(text_content, out_dir / "text_story.png")
        if music:
            return image_with_music(image, music, out_dir / "ready.mp4", duration, volume, fade_in, fade_out)
        return image
    if source is None:
        raise RuntimeError("Missing source media")
    if content_type == "VIDEO":
        if music and not has_audio(source):
            return video_with_music(source, music, out_dir / "ready.mp4", volume, fade_in)
        target = out_dir / source.name
        shutil.copy2(source, target)
        return target
    if content_type == "IMAGE":
        if music:
            return image_with_music(source, music, out_dir / "ready.mp4", duration, volume, fade_in, fade_out)
        target = out_dir / source.name
        shutil.copy2(source, target)
        return target
    raise RuntimeError(f"Unsupported content type: {content_type}")
