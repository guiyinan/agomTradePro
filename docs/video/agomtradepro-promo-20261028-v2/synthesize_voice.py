from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_SOURCE = ROOT / "docs" / "video" / "agomtradepro-workflows-150s-vertical-v2.md"
V1_SITE_PACKAGES = ROOT / ".tmp" / "agom-brand-video-20261028" / "tools" / "site-packages"
TEMP_AUDIO_ROOT = ROOT / ".tmp" / "agom-brand-video-20261028-v2" / "audio"
VOICE = "zh-CN-YunyangNeural"
RATE = "-6%"

sys.path.insert(0, str(V1_SITE_PACKAGES))
try:
    import edge_tts
except ImportError as error:
    raise RuntimeError(f"edge-tts is unavailable in isolated tools: {V1_SITE_PACKAGES}") from error


def narration_paragraphs() -> tuple[str, ...]:
    """Read the twelve approved spoken paragraphs from the v2 script."""
    source = SCRIPT_SOURCE.read_text(encoding="utf-8")
    spoken_section = source.split("## 配音正文\n", maxsplit=1)[1].split("\n## 镜头与工作流", maxsplit=1)[0]
    paragraphs = tuple(part.strip() for part in spoken_section.split("\n\n") if part.strip())
    if len(paragraphs) != 12:
        raise ValueError(f"Expected 12 approved narration paragraphs; found {len(paragraphs)}")
    return paragraphs


def voice_job_id(paragraphs: tuple[str, ...]) -> str:
    """Return a content-addressed cache key for the selected voice and rate."""
    content = "\n".join((VOICE, RATE, *paragraphs)).encode("utf-8")
    return hashlib.sha256(content).hexdigest()[:20]


async def synthesize(paragraphs: tuple[str, ...], output_dir: Path, overwrite: bool) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for index, paragraph in enumerate(paragraphs, start=1):
        path = output_dir / f"voice-{index:02d}.mp3"
        if path.exists() and path.stat().st_size > 0 and not overwrite:
            files.append(path)
            continue
        communicate = edge_tts.Communicate(text=paragraph, voice=VOICE, rate=RATE)
        await communicate.save(str(path))
        if not path.exists() or path.stat().st_size == 0:
            raise RuntimeError(f"Edge TTS did not create an audio segment: {path}")
        files.append(path)
        print(f"Synthesized segment {index:02d}/12: {path.name} ({path.stat().st_size} bytes)")
    return files


def write_manifest(paragraphs: tuple[str, ...], files: list[Path], output_dir: Path) -> Path:
    manifest: dict[str, Any] = {
        "source": str(SCRIPT_SOURCE.relative_to(ROOT)),
        "source_section": "配音正文",
        "voice": VOICE,
        "rate": RATE,
        "segment_count": len(files),
        "content_sha256": hashlib.sha256("\n".join(paragraphs).encode("utf-8")).hexdigest(),
        "segments": [
            {
                "file": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
            for path in files
        ],
    }
    manifest_path = output_dir / "voice_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthesize the approved v2 narration with Edge TTS.")
    parser.add_argument("--force", action="store_true", help="Regenerate cached segments for this exact script hash.")
    options = parser.parse_args()
    paragraphs = narration_paragraphs()
    job_id = voice_job_id(paragraphs)
    output_dir = TEMP_AUDIO_ROOT / f"{VOICE}-rate6pct-{job_id}"
    files = asyncio.run(synthesize(paragraphs, output_dir, overwrite=options.force))
    manifest = write_manifest(paragraphs, files, output_dir)
    print(f"Narration segments: {len(files)}")
    print(f"Voice cache: {output_dir}")
    print(f"Manifest: {manifest}")


if __name__ == "__main__":
    main()
