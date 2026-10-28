from __future__ import annotations

import argparse
import math
import os
import re
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = Path(__file__).resolve().parent
TEMP_DIR = REPO_ROOT / ".tmp" / "agom-brand-video-20261028"
SITE_PACKAGES = TEMP_DIR / "tools" / "site-packages"
sys.path.insert(0, str(SITE_PACKAGES))

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

WIDTH = 1080
HEIGHT = 1920
FPS = 30
VIDEO_SECONDS = 60
VOICE = "zh-CN-YunyangNeural"
VOICE_RATE = "-6%"
ICON_PATH = REPO_ROOT / "docs" / "images" / "brand" / "agomtradepro-icon-v2-pixel-ashare.png"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

BG_TOP = (9, 17, 31)
BG_BOTTOM = (12, 27, 43)
PANEL = (17, 30, 48)
PANEL_ALT = (20, 38, 56)
TEXT = (240, 245, 249)
MUTED = (159, 180, 198)
GOLD = (242, 184, 76)
MINT = (88, 224, 190)
RED = (232, 69, 69)
GREEN = (38, 162, 105)

NARRATION: tuple[str, ...] = (
    "每天刷行情、翻研报，真要做决定，依据却散在各个窗口里。",
    "我在做的 AgomTradePro，是一个可以自己部署的个人投研系统。",
    "先看宏观和政策环境，再研究股票、基金，把数据和判断放在一起。",
    "形成投资信号时，写清理由，也设好推翻判断的条件。",
    "用历史回测检验想法，用模拟交易跟踪，再结合持仓和决策记录复盘。",
    "AI 可以接入系统，帮你查数据、整理分析。需要审批的操作，确认后再执行。",
    "我希望，每一次判断都有依据，每一次复盘都能积累经验。",
    "项目开源，持续开发中。关注我，一起搭建自己的投研工作台。",
)

CAPTIONS: tuple[str, ...] = (
    "每天刷行情、翻研报，\n真要做决定，依据却散在各个窗口里。",
    "我在做的 AgomTradePro，\n是一个可以自己部署的个人投研系统。",
    "先看宏观和政策环境，再研究股票、基金，\n把数据和判断放在一起。",
    "形成投资信号时，写清理由，\n也设好推翻判断的条件。",
    "用历史回测检验想法，用模拟交易跟踪，\n再结合持仓和决策记录复盘。",
    "AI 可以接入系统，帮你查数据、整理分析。\n需要审批的操作，确认后再执行。",
    "我希望，每一次判断都有依据，\n每一次复盘都能积累经验。",
    "项目开源，持续开发中。关注我，\n一起搭建自己的投研工作台。",
)

HEADLINES: tuple[str, ...] = (
    "信息很多，依据很散",
    "给自己搭一套投研工作台",
    "先看环境，再研究标的",
    "理由清楚，边界也清楚",
    "回测 · 模拟 · 复盘",
    "AI 协作，操作有确认",
    "判断有依据，经验能积累",
    "关注 agom，一起搭建",
)

BASE_SCENE_SECONDS: tuple[float, ...] = (6, 7, 7, 6, 8, 9, 7, 8)


@dataclass(frozen=True)
class SceneTiming:
    start: float
    end: float
    speech_start: float
    speech_end: float


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def ease_out(value: float) -> float:
    x = clamp(value)
    return 1.0 - (1.0 - x) ** 3


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = (
        ["msyhbd.ttc", "simhei.ttf", "Dengb.ttf"]
        if bold
        else ["msyh.ttc", "simsun.ttc", "Deng.ttf"]
    )
    for name in names:
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    raise FileNotFoundError("No supported Chinese font was found in C:/Windows/Fonts")


def text_center(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, ...],
    stroke_width: int = 0,
) -> None:
    draw.text(
        xy,
        text,
        font=font,
        fill=fill,
        anchor="mm",
        align="center",
        spacing=8,
        stroke_width=stroke_width,
        stroke_fill=(4, 10, 18, 230),
    )


def text_right(
    draw: ImageDraw.ImageDraw,
    right: int,
    top: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, ...],
) -> None:
    width = draw.textbbox((0, 0), text, font=font)[2]
    draw.text((right - width, top), text, font=font, fill=fill)


def make_background() -> Image.Image:
    background = Image.new("RGB", (WIDTH, HEIGHT), BG_TOP)
    draw = ImageDraw.Draw(background)
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        color = tuple(round(a * (1 - t) + b * t) for a, b in zip(BG_TOP, BG_BOTTOM))
        draw.line((0, y, WIDTH, y), fill=color)

    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse((380, 170, 1250, 970), fill=(43, 145, 137, 50))
    glow_draw.ellipse((-280, 870, 620, 1820), fill=(189, 129, 53, 29))
    glow = glow.filter(ImageFilter.GaussianBlur(130))
    background = Image.alpha_composite(background.convert("RGBA"), glow)

    grid = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    grid_draw = ImageDraw.Draw(grid)
    for x in range(42, WIDTH, 84):
        grid_draw.line((x, 0, x, HEIGHT), fill=(150, 185, 210, 9), width=1)
    for y in range(36, HEIGHT, 84):
        grid_draw.line((0, y, WIDTH, y), fill=(150, 185, 210, 8), width=1)
    return Image.alpha_composite(background, grid)


class VideoRenderer:
    def __init__(self) -> None:
        self.background = make_background()
        self.icon = Image.open(ICON_PATH).convert("RGBA")
        self.icon_small = self.icon.resize((78, 78), Image.Resampling.LANCZOS)
        self.icon_medium = self.icon.resize((292, 292), Image.Resampling.LANCZOS)
        self.icon_large = self.icon.resize((360, 360), Image.Resampling.LANCZOS)
        self.fonts = {
            "small": load_font(25),
            "small_bold": load_font(25, True),
            "body": load_font(31),
            "body_bold": load_font(34, True),
            "heading": load_font(61, True),
            "hero": load_font(72, True),
            "caption": load_font(39, True),
            "brand": load_font(53, True),
            "footer": load_font(28),
        }

    def _draw_background_motion(self, draw: ImageDraw.ImageDraw, t: float) -> None:
        for i in range(16):
            x0 = 48 + (i * 163) % (WIDTH - 96)
            y0 = 330 + (i * 271) % 1160
            x = x0 + math.sin(t * 0.28 + i * 0.71) * 17
            y = y0 + math.cos(t * 0.19 + i * 0.37) * 14
            alpha = 35 + int((math.sin(t * 0.8 + i) + 1) * 20)
            color = (102, 223, 196, alpha) if i % 3 == 0 else (242, 184, 76, alpha // 2)
            draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=color)

    def _draw_header(self, draw: ImageDraw.ImageDraw, t: float, index: int, local: float) -> None:
        draw.rounded_rectangle((58, 55, 151, 148), radius=27, fill=(11, 22, 37, 235))
        draw.rounded_rectangle((58, 55, 151, 148), radius=27, outline=(117, 172, 174, 110), width=2)
        draw._image.paste(self.icon_small, (66, 62), self.icon_small)
        draw.text((170, 76), "AgomTradePro", font=self.fonts["body_bold"], fill=TEXT)
        draw.text((171, 116), "个人投研工作台", font=self.fonts["small"], fill=MUTED)

        pill = (670, 72, 1014, 132)
        draw.rounded_rectangle(pill, radius=29, fill=(12, 24, 39, 225), outline=(93, 161, 151, 155), width=2)
        text_center(draw, (842, 102), "流程示意 · 持续开发中", self.fonts["small_bold"], MINT)

        draw.rounded_rectangle((82, 196, 998, 204), radius=4, fill=(53, 70, 84, 170))
        progress = clamp((index + local) / 8.0)
        draw.rounded_rectangle(
            (82, 196, 82 + int(916 * progress), 204),
            radius=4,
            fill=GOLD if index < 2 else MINT,
        )
        draw.text(
            (82, 226),
            f"{index + 1:02d} / 08",
            font=self.fonts["small_bold"],
            fill=(147, 170, 190, 225),
        )

    def _draw_heading(self, draw: ImageDraw.ImageDraw, index: int) -> None:
        accent = GOLD if index in (0, 1, 7) else MINT
        text_center(draw, (540, 332), HEADLINES[index], self.fonts["heading"], TEXT, stroke_width=1)
        draw.rounded_rectangle((461, 390, 619, 396), radius=3, fill=accent)

    def _card(
        self,
        draw: ImageDraw.ImageDraw,
        box: tuple[int, int, int, int],
        title: str,
        subtitle: str,
        accent: tuple[int, int, int],
        progress: float,
        symbol: str,
        t: float,
    ) -> None:
        x1, y1, x2, y2 = box
        lift = int((1 - ease_out(progress)) * 34)
        box = (x1, y1 + lift, x2, y2 + lift)
        x1, y1, x2, y2 = box
        draw.rounded_rectangle(box, radius=30, fill=(14, 27, 44, 238), outline=(*accent, 175), width=2)
        draw.rounded_rectangle((x1 + 24, y1 + 24, x2 - 24, y1 + 31), radius=3, fill=(*accent, 220))
        cx = (x1 + x2) // 2
        cy = y1 + 102
        self._draw_symbol(draw, symbol, cx, cy, accent, progress, t)
        text_center(draw, (cx, y1 + 178), title, self.fonts["body_bold"], TEXT)
        text_center(draw, (cx, y1 + 224), subtitle, self.fonts["small"], MUTED)

    def _draw_symbol(
        self,
        draw: ImageDraw.ImageDraw,
        symbol: str,
        cx: int,
        cy: int,
        accent: tuple[int, int, int],
        progress: float,
        t: float,
    ) -> None:
        width = 5
        if symbol in ("pulse", "research", "backtest"):
            points = [(cx - 50, cy + 20), (cx - 24, cy + 2), (cx, cy + 13), (cx + 24, cy - 25), (cx + 50, cy - 8)]
            draw.line(points[: max(2, int(2 + ease_out(progress) * 3))], fill=(*accent, 255), width=width, joint="curve")
            for px, py in points:
                draw.ellipse((px - 6, py - 6, px + 6, py + 6), fill=accent)
            if symbol == "backtest":
                for j, height in enumerate((24, 42, 33, 60)):
                    bx = cx - 45 + j * 30
                    color = RED if j in (0, 3) else GREEN
                    draw.rectangle((bx, cy + 34 - height, bx + 12, cy + 34), fill=color)
        elif symbol in ("policy", "signal", "review"):
            draw.ellipse((cx - 41, cy - 41, cx + 41, cy + 41), outline=(*accent, 230), width=width)
            if symbol == "signal":
                draw.line((cx - 19, cy + 1, cx - 4, cy + 17, cx + 25, cy - 19), fill=accent, width=width + 1, joint="curve")
            elif symbol == "review":
                draw.arc((cx - 21, cy - 24, cx + 23, cy + 23), start=35, end=315, fill=accent, width=width)
                draw.polygon(((cx + 17, cy - 25), (cx + 34, cy - 24), (cx + 23, cy - 9)), fill=accent)
            else:
                draw.line((cx, cy - 22, cx, cy + 24), fill=accent, width=width)
                draw.line((cx - 22, cy, cx + 22, cy), fill=accent, width=width)
        elif symbol in ("ai", "human", "control"):
            draw.rounded_rectangle((cx - 42, cy - 32, cx + 42, cy + 32), radius=18, outline=(*accent, 240), width=width)
            if symbol == "ai":
                for dx in (-16, 0, 16):
                    draw.ellipse((cx + dx - 4, cy - 5, cx + dx + 4, cy + 3), fill=accent)
                draw.line((cx - 19, cy + 13, cx + 19, cy + 13), fill=accent, width=4)
            elif symbol == "human":
                draw.ellipse((cx - 10, cy - 20, cx + 10, cy), fill=accent)
                draw.arc((cx - 22, cy - 5, cx + 22, cy + 29), start=190, end=350, fill=accent, width=width)
            else:
                draw.line((cx - 20, cy + 1, cx - 4, cy + 16, cx + 24, cy - 18), fill=accent, width=width, joint="curve")
        else:
            draw.rounded_rectangle((cx - 43, cy - 38, cx + 43, cy + 38), radius=16, outline=(*accent, 235), width=width)
            for row in range(3):
                yy = cy - 18 + row * 18
                draw.line((cx - 24, yy, cx + 24 - (row % 2) * 9, yy), fill=accent, width=4)

    def _draw_scene(self, draw: ImageDraw.ImageDraw, index: int, local: float, t: float) -> None:
        reveal = ease_out(local * 1.65)
        if index == 0:
            text_center(draw, (540, 506), "行情 · 研报 · 笔记", self.fonts["body"], MUTED)
            cards = [
                ((86, 676, 348, 985), "行情窗口", "价格与环境", GOLD, "pulse"),
                ((409, 676, 671, 985), "研究材料", "数据与观点", MINT, "research"),
                ((732, 676, 994, 985), "决策笔记", "依据待整理", GOLD, "notes"),
            ]
            for n, (box, title, subtitle, accent, symbol) in enumerate(cards):
                self._card(draw, box, title, subtitle, accent, clamp((local - n * 0.11) * 2.0), symbol, t)
            center_y = 1080
            draw.line((222, center_y, 858, center_y), fill=(87, 155, 152, 165), width=3)
            dot_x = int(222 + 636 * clamp(local * 1.2))
            draw.ellipse((dot_x - 11, center_y - 11, dot_x + 11, center_y + 11), fill=GOLD)
            text_center(draw, (540, 1184), "把分散线索，连成自己的研究流程", self.fonts["body_bold"], TEXT)
        elif index == 1:
            halo = int(410 + math.sin(t * 2.2) * 9)
            draw.ellipse((540 - halo // 2, 500 - halo // 2, 540 + halo // 2, 500 + halo // 2), outline=(88, 224, 190, 52), width=3)
            size = int(310 + 24 * reveal)
            icon = self.icon.resize((size, size), Image.Resampling.LANCZOS)
            draw._image.paste(icon, (540 - size // 2, 520), icon)
            text_center(draw, (540, 930), "AgomTradePro", self.fonts["brand"], TEXT)
            text_center(draw, (540, 1010), "可以自己部署的个人投研系统", self.fonts["body"], MUTED)
            self._pill(draw, (265, 1100, 815, 1172), "开源 · AI 协作 · 持续开发中", GOLD)
        elif index == 2:
            cards = [
                ((84, 678, 354, 986), "宏观环境", "观察大势", GOLD, "policy"),
                ((405, 678, 675, 986), "政策脉搏", "整理变化", MINT, "notes"),
                ((726, 678, 996, 986), "股票 / 基金", "研究标的", GOLD, "research"),
            ]
            for n, (box, title, subtitle, accent, symbol) in enumerate(cards):
                self._card(draw, box, title, subtitle, accent, clamp((local - n * 0.12) * 2.0), symbol, t)
            for x in (354, 675):
                draw.line((x + 8, 832, x + 45, 832), fill=(96, 177, 158, 215), width=4)
                draw.polygon(((x + 45, 832), (x + 31, 823), (x + 31, 841)), fill=MINT)
            text_center(draw, (540, 1106), "环境与观点，同屏整理", self.fonts["body_bold"], TEXT)
            self._pill(draw, (370, 1176, 710, 1240), "研究流程示意", MINT)
        elif index == 3:
            self._card(draw, (95, 675, 505, 1090), "研究理由", "数据 · 逻辑 · 观察", MINT, reveal, "signal", t)
            self._card(draw, (575, 675, 985, 1090), "证伪条件", "何时重新检查判断", GOLD, clamp((local - 0.16) * 1.4), "review", t)
            text_center(draw, (540, 1192), "信号不只写结论，也写清边界", self.fonts["body_bold"], TEXT)
        elif index == 4:
            cards = [
                ((78, 670, 344, 1024), "历史回测", "检验想法", GOLD, "backtest"),
                ((407, 670, 673, 1024), "模拟交易", "跟踪过程", MINT, "pulse"),
                ((736, 670, 1002, 1024), "决策复盘", "积累经验", GOLD, "review"),
            ]
            for n, (box, title, subtitle, accent, symbol) in enumerate(cards):
                self._card(draw, box, title, subtitle, accent, clamp((local - n * 0.12) * 1.7), symbol, t)
            draw.line((209, 1100, 871, 1100), fill=(72, 125, 134, 210), width=4)
            moving_x = 209 + int(662 * clamp(local * 1.25))
            draw.ellipse((moving_x - 12, 1088, moving_x + 12, 1112), fill=MINT)
            text_center(draw, (540, 1195), "检验 → 跟踪 → 回看", self.fonts["body_bold"], TEXT)
            self._pill(draw, (385, 1250, 695, 1314), "流程示意", MINT)
        elif index == 5:
            cards = [
                ((67, 700, 285, 1010), "查询", "获取所需信息", GOLD, "notes"),
                ((316, 700, 534, 1010), "整理", "形成分析脉络", MINT, "ai"),
                ((565, 700, 783, 1010), "人工确认", "先审阅再决定", GOLD, "human"),
                ((814, 700, 1032, 1010), "受控执行", "授权后继续", MINT, "control"),
            ]
            for n, (box, title, subtitle, accent, symbol) in enumerate(cards):
                self._card(draw, box, title, subtitle, accent, clamp((local - n * 0.09) * 2.2), symbol, t)
                if n < 3:
                    x = box[2] + 11
                    draw.line((x, 855, x + 27, 855), fill=(119, 192, 174, 200), width=3)
                    draw.polygon(((x + 27, 855), (x + 16, 848), (x + 16, 862)), fill=MINT)
            text_center(draw, (540, 1147), "AI 协作流程示意 · 查询之外，关键操作保留人工确认", self.fonts["small"], MUTED)
        elif index == 6:
            labels = [
                ((104, 730, 398, 1010), "有依据", "每次判断"),
                ((393, 730, 687, 1010), "可追溯", "过程记录"),
                ((682, 730, 976, 1010), "能积累", "复盘经验"),
            ]
            for n, (box, title, sub) in enumerate(labels):
                accent = GOLD if n == 1 else MINT
                self._card(draw, box, title, sub, accent, clamp((local - 0.1 * n) * 1.8), "signal" if n == 0 else "review", t)
            text_center(draw, (540, 1163), "把一次判断，变成下一次研究的起点", self.fonts["body_bold"], TEXT)
        else:
            size = int(330 + 24 * math.sin(t * 1.5) ** 2)
            icon = self.icon.resize((size, size), Image.Resampling.LANCZOS)
            draw._image.paste(icon, (540 - size // 2, 465), icon)
            text_center(draw, (540, 860), "AgomTradePro", self.fonts["brand"], TEXT)
            text_center(draw, (540, 952), "把投研流程，留在自己的工作台", self.fonts["body"], MUTED)
            self._pill(draw, (280, 1060, 800, 1136), "开源 · 持续开发中", GOLD)
            text_center(draw, (540, 1210), "关注 agom，一起搭建", self.fonts["body_bold"], TEXT)

    def _pill(
        self,
        draw: ImageDraw.ImageDraw,
        box: tuple[int, int, int, int],
        label: str,
        color: tuple[int, int, int],
    ) -> None:
        draw.rounded_rectangle(box, radius=(box[3] - box[1]) // 2, fill=(15, 28, 44, 230), outline=(*color, 190), width=2)
        text_center(draw, ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2), label, self.fonts["small_bold"], color)

    def _draw_subtitle(self, draw: ImageDraw.ImageDraw, caption: str, progress: float) -> None:
        alpha = int(245 * min(ease_out(progress * 8), ease_out((1 - progress) * 8)))
        box = (74, 1400, 1006, 1552)
        draw.rounded_rectangle(box, radius=26, fill=(4, 11, 20, min(alpha, 230)), outline=(92, 125, 143, min(alpha, 120)), width=2)
        text_center(draw, (540, 1474), caption, self.fonts["caption"], (*TEXT, alpha), stroke_width=1)

    def _draw_disclaimer(self, draw: ImageDraw.ImageDraw) -> None:
        right = WIDTH - 26
        text_right(draw, right, HEIGHT - 102, "AI不能替代人工决策", self.fonts["footer"], (226, 233, 238, 245))
        text_right(draw, right, HEIGHT - 62, "市场有风险 投资需谨慎", self.fonts["footer"], (226, 233, 238, 245))

    def draw_frame(
        self,
        t: float,
        timings: Sequence[SceneTiming],
        preview: bool = False,
    ) -> Image.Image:
        index = len(timings) - 1
        for i, timing in enumerate(timings):
            if t < timing.end or i == len(timings) - 1:
                index = i
                break
        timing = timings[index]
        duration = max(0.01, timing.end - timing.start)
        local = clamp((t - timing.start) / duration)

        frame = self.background.copy()
        draw = ImageDraw.Draw(frame, "RGBA")
        self._draw_background_motion(draw, t)
        self._draw_header(draw, t, index, local)
        self._draw_heading(draw, index)
        self._draw_scene(draw, index, local, t)
        speech_duration = timing.speech_end - timing.speech_start
        if preview and index == 4:
            self._draw_subtitle(draw, CAPTIONS[index], 0.48)
        elif timing.speech_start <= t <= timing.speech_end and speech_duration > 0:
            self._draw_subtitle(draw, CAPTIONS[index], (t - timing.speech_start) / speech_duration)
        self._draw_disclaimer(draw)
        return frame.convert("RGB")


def default_timings() -> list[SceneTiming]:
    boundaries = (0, 6, 13, 20, 26, 34, 43, 50, 60)
    values: list[SceneTiming] = []
    for i in range(8):
        start = float(boundaries[i])
        end = float(boundaries[i + 1])
        speech_start = start + 0.4
        speech_end = min(end - 0.4, speech_start + (end - start) * 0.78)
        values.append(SceneTiming(start, end, speech_start, speech_end))
    return values


def write_preview(renderer: VideoRenderer, output_path: Path, at: float) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame = renderer.draw_frame(at, default_timings(), preview=True)
    frame.save(output_path, format="PNG", optimize=True)
    print(f"Preview image: {output_path}")


def run_checked(command: Sequence[str], env: dict[str, str] | None = None) -> None:
    result = subprocess.run(command, check=False, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "command failed").strip()
        raise RuntimeError(f"Command failed ({result.returncode}): {message}")


def generate_voice_segments() -> list[Path]:
    tts_dir = TEMP_DIR / "tts"
    tts_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SITE_PACKAGES)
    paths: list[Path] = []
    for index, line in enumerate(NARRATION, start=1):
        path = tts_dir / f"voice-{index:02d}.mp3"
        if path.exists() and path.stat().st_size > 0:
            paths.append(path)
            continue
        command = [
            sys.executable,
            "-m",
            "edge_tts",
            "--voice",
            VOICE,
            f"--rate={VOICE_RATE}",
            "--text",
            line,
            "--write-media",
            str(path),
        ]
        run_checked(command, env)
        paths.append(path)
    return paths


def mp3_to_wav(mp3_path: Path, wav_path: Path) -> None:
    run_checked(
        [
            FFMPEG,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(mp3_path),
            "-ac",
            "2",
            "-ar",
            "48000",
            "-c:a",
            "pcm_s16le",
            str(wav_path),
        ]
    )


def combine_voice(paths: Sequence[Path], full_wav: Path) -> list[SceneTiming]:
    tts_dir = TEMP_DIR / "tts"
    wav_paths = [tts_dir / f"voice-{index:02d}.wav" for index in range(1, len(paths) + 1)]
    for mp3, wav_path in zip(paths, wav_paths):
        mp3_to_wav(mp3, wav_path)

    speech_bytes: list[bytes] = []
    speech_seconds: list[float] = []
    for path in wav_paths:
        with wave.open(str(path), "rb") as source:
            if source.getframerate() != 48000 or source.getnchannels() != 2 or source.getsampwidth() != 2:
                raise ValueError(f"Unexpected WAV format in {path}")
            raw = source.readframes(source.getnframes())
            speech_bytes.append(raw)
            speech_seconds.append(len(raw) / (48000 * 2 * 2))

    minimum_padding = 0.48
    if sum(speech_seconds) + minimum_padding * len(speech_seconds) > 58.0:
        raise RuntimeError(
            "The selected Yunyang narration is too long for the 58-second spoken section at -6% rate. "
            "The clip files are retained in .tmp; increase the Edge TTS rate slightly and rerun."
        )
    slack = 58.0 - sum(speech_seconds) - minimum_padding * len(speech_seconds)
    base_sum = sum(BASE_SCENE_SECONDS)
    scene_lengths = [
        duration + minimum_padding + slack * base / base_sum
        for duration, base in zip(speech_seconds, BASE_SCENE_SECONDS)
    ]

    timings: list[SceneTiming] = []
    scene_start = 0.0
    sample_rate = 48000
    frame_width = 4
    total_frames = VIDEO_SECONDS * sample_rate
    combined = bytearray(total_frames * frame_width)
    for index, (raw, duration, scene_length) in enumerate(zip(speech_bytes, speech_seconds, scene_lengths)):
        speech_start = scene_start + max(0.18, (scene_length - duration) * 0.34)
        speech_end = speech_start + duration
        timings.append(SceneTiming(scene_start, scene_start + scene_length, speech_start, speech_end))
        offset = round(speech_start * sample_rate) * frame_width
        end = min(len(combined), offset + len(raw))
        combined[offset:end] = raw[: end - offset]
        scene_start += scene_length

    full_wav.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(full_wav), "wb") as destination:
        destination.setnchannels(2)
        destination.setsampwidth(2)
        destination.setframerate(sample_rate)
        destination.writeframes(combined)
    return timings


def normalize_voice(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    run_checked(
        [
            FFMPEG,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-af",
            "loudnorm=I=-16:TP=-2:LRA=11",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-c:a",
            "pcm_s16le",
            str(destination),
        ]
    )


def write_srt(path: Path, timings: Sequence[SceneTiming]) -> None:
    def timestamp(seconds: float) -> str:
        milliseconds = round(seconds * 1000)
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        whole_seconds, milliseconds = divmod(remainder, 1000)
        return f"{hours:02}:{minutes:02}:{whole_seconds:02},{milliseconds:03}"

    rows: list[str] = []
    for index, timing in enumerate(timings, start=1):
        rows.extend(
            [
                str(index),
                f"{timestamp(timing.speech_start)} --> {timestamp(timing.speech_end)}",
                CAPTIONS[index - 1],
                "",
            ]
        )
    path.write_text("\n".join(rows), encoding="utf-8-sig")


def write_original_music(path: Path) -> None:
    sample_rate = 48000
    total = VIDEO_SECONDS * sample_rate
    samples = np.zeros((total, 2), dtype=np.float32)
    chords = (
        (130.81, 164.81, 196.00),
        (110.00, 130.81, 164.81),
        (87.31, 110.00, 130.81),
        (98.00, 130.81, 146.83),
    )
    chord_seconds = 7.5
    time_axis = np.arange(total, dtype=np.float64) / sample_rate
    for index, frequencies in enumerate(chords * 2):
        start = int(index * chord_seconds * sample_rate)
        end = min(total, int((index + 1) * chord_seconds * sample_rate))
        if start >= total:
            break
        local = time_axis[start:end] - index * chord_seconds
        fade_in = np.clip(local / 1.2, 0, 1)
        fade_out = np.clip((chord_seconds - local) / 1.6, 0, 1)
        envelope = np.minimum(fade_in, fade_out)
        pad = sum(np.sin(2 * math.pi * frequency * local) for frequency in frequencies) / 3.0
        harmonic = np.sin(2 * math.pi * frequencies[0] * 2 * local) * 0.18
        signal = (pad + harmonic) * envelope * 0.012
        samples[start:end, 0] += signal.astype(np.float32)
        samples[start:end, 1] += (signal * 0.92).astype(np.float32)

    for beat in np.arange(0.6, VIDEO_SECONDS, 2.0):
        start = int(beat * sample_rate)
        length = min(int(1.35 * sample_rate), total - start)
        local = np.arange(length, dtype=np.float64) / sample_rate
        pluck = np.sin(2 * math.pi * 523.25 * local) * np.exp(-local * 3.2) * 0.006
        samples[start : start + length, 0] += pluck.astype(np.float32)
        samples[start : start + length, 1] += (pluck * 0.78).astype(np.float32)

    fade_count = int(2.0 * sample_rate)
    samples[-fade_count:] *= np.linspace(1.0, 0.0, fade_count, dtype=np.float32)[:, None]
    pcm = (np.clip(samples, -0.95, 0.95) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as destination:
        destination.setnchannels(2)
        destination.setsampwidth(2)
        destination.setframerate(sample_rate)
        destination.writeframes(pcm.tobytes())


def render_mp4(
    renderer: VideoRenderer,
    timings: Sequence[SceneTiming],
    voice_path: Path,
    music_path: Path,
    output_path: Path,
) -> None:
    command = [
        FFMPEG,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-video_size",
        f"{WIDTH}x{HEIGHT}",
        "-framerate",
        str(FPS),
        "-i",
        "-",
        "-i",
        str(voice_path),
        "-i",
        str(music_path),
        "-filter_complex",
        "[1:a]loudnorm=I=-16:TP=-2:LRA=11[voice];"
        "[2:a]loudnorm=I=-28:TP=-9:LRA=10[bed];"
        "[voice][bed]amix=inputs=2:duration=first:normalize=0:dropout_transition=0,"
        "alimiter=limit=0.84:attack=5:release=80:level=0,"
        "loudnorm=I=-16:TP=-1.5:LRA=11[aout]",
        "-map",
        "0:v:0",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "19",
        "-profile:v",
        "high",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(FPS),
        "-threads",
        "4",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-t",
        str(VIDEO_SECONDS),
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert process.stdin is not None
    try:
        for frame_index in range(FPS * VIDEO_SECONDS):
            timestamp = frame_index / FPS
            frame = renderer.draw_frame(timestamp, timings)
            process.stdin.write(frame.tobytes())
            if frame_index % 150 == 0:
                print(f"Rendering {timestamp:05.1f}s / {VIDEO_SECONDS}s", flush=True)
        process.stdin.close()
        stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        return_code = process.wait()
    except Exception:
        process.kill()
        process.wait()
        raise
    if return_code != 0:
        raise RuntimeError(f"FFmpeg failed ({return_code}): {stderr.strip()}")


def save_cover(renderer: VideoRenderer, timings: Sequence[SceneTiming], path: Path) -> None:
    frame = renderer.draw_frame(timings[-1].start + 1.3, timings)
    frame.save(path, format="PNG", optimize=True)


def prepare_audio_assets() -> tuple[Path, Path, list[SceneTiming]]:
    mp3_paths = generate_voice_segments()
    raw_voice_path = TEMP_DIR / "voice-timed-raw.wav"
    timings = combine_voice(mp3_paths, raw_voice_path)
    voice_path = OUTPUT_DIR / "narration.wav"
    normalize_voice(raw_voice_path, voice_path)
    srt_path = OUTPUT_DIR / "captions.srt"
    write_srt(srt_path, timings)
    print(f"Narration: {voice_path}")
    print(f"Captions: {srt_path}")
    print(f"Speech segment durations: {[round(item.speech_end - item.speech_start, 2) for item in timings]}")
    print(f"Scene durations: {[round(item.end - item.start, 2) for item in timings]}")
    return voice_path, srt_path, timings


def render_full_video() -> None:
    renderer = VideoRenderer()
    voice_path, srt_path, timings = prepare_audio_assets()
    music_path = TEMP_DIR / "original-ambient-music.wav"
    write_original_music(music_path)
    cover_path = OUTPUT_DIR / "cover.png"
    save_cover(renderer, timings, cover_path)
    output_path = OUTPUT_DIR / "agomtradepro-60s-promo.mp4"
    render_mp4(renderer, timings, voice_path, music_path, output_path)
    print(f"Video: {output_path}")
    print(f"Narration: {voice_path}")
    print(f"Captions: {srt_path}")
    print(f"Cover: {cover_path}")
    print(f"Scene timings: {[round(item.end - item.start, 2) for item in timings]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the AgomTradePro vertical promo video.")
    parser.add_argument("--preview", action="store_true", help="Render one representative still preview only.")
    parser.add_argument("--time", type=float, default=31.0, help="Preview timestamp in seconds.")
    parser.add_argument("--render", action="store_true", help="Render the complete MP4 and deliverables.")
    parser.add_argument("--prepare-audio", action="store_true", help="Generate narration and subtitles without rendering video.")
    args = parser.parse_args()
    if sum((args.preview, args.render, args.prepare_audio)) != 1:
        parser.error("Choose exactly one of --preview, --prepare-audio, or --render.")
    if args.preview:
        renderer = VideoRenderer()
        preview_path = TEMP_DIR / "preview" / "workflow-preview.png"
        write_preview(renderer, preview_path, args.time)
        return
    if args.prepare_audio:
        prepare_audio_assets()
        return
    render_full_video()


if __name__ == "__main__":
    main()
