from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import re
import subprocess
import sys
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = Path(__file__).resolve().parent
TEMP_DIR = ROOT / ".tmp" / "agom-brand-video-20261028-v2"
SITE_PACKAGES = ROOT / ".tmp" / "agom-brand-video-20261028" / "tools" / "site-packages"
sys.path.insert(0, str(SITE_PACKAGES))

import imageio_ffmpeg

import render_storyboards as art
from synthesize_voice import RATE, VOICE, narration_paragraphs, voice_job_id

WIDTH = 1080
HEIGHT = 1920
FPS = 30
DURATION = 150.0
FRAME_COUNT = int(DURATION * FPS)
ICON_PATH = ROOT / "docs" / "images" / "brand" / "agomtradepro-icon-v2-pixel-ashare.png"
VOICE_DIR = TEMP_DIR / "audio" / f"{VOICE}-rate6pct-{voice_job_id(narration_paragraphs())}"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

TEXT = (239, 245, 247)
MUTED = (157, 178, 194)
GOLD = (242, 184, 76)
MINT = (88, 224, 190)
AMBER = (224, 160, 67)
RED = (224, 67, 71)
GREEN = (46, 175, 122)
PANEL = (16, 31, 49)
PANEL_LIGHT = (21, 40, 59)
PAPER = (224, 232, 226)
PAPER_INK = (19, 35, 46)
EDGE = (65, 91, 111)

BOUNDARIES: tuple[float, ...] = (0, 9, 20, 32, 44, 57, 70, 83, 98, 111, 124, 138, 148, 150)
SHOT_TITLES: tuple[str, ...] = (
    "个人研究，也要有完整的流程",
    "一条研究想法，连起四条工作流",
    "工作流一 · 先把研究建立在数据上",
    "数据用途闸门 · 不可用就说明原因",
    "工作流二 · 从宏观环境走到标的",
    "投资信号 · 理由与证伪条件",
    "工作流三 · 决策前逐项检查",
    "阻断、修改、复核，再进入人工确认",
    "工作流四 · 历史验证与模拟跟踪",
    "审计复盘 · 记录回到下一轮研究",
    "AI 协助查数、分析与方案整理",
    "从日常研究开始，逐步搭建自己的方法",
    "AgomTradePro · 持续开发中",
)
SHOT_SUBTITLES: tuple[str, ...] = (
    "个人可用 · 研究与风控流程持续建设中",
    "数据 · 研究 · 风控 · 验证复盘",
    "行情 / 宏观指标 / 财务材料 → 研究材料",
    "来源 · 源观测时间 · 可用范围",
    "增长 / 通胀 / 政策 → 行业 → 股票或基金",
    "研究理由 + 支撑证据 + 证伪条件",
    "总仓位 · 单一标的 · 现金底线 · 风险限制",
    "示例账户 / 示例配置",
    "历史回测 · 模拟交易 · 持仓变化",
    "当时证据 · 判断 · 风险结果 · 处理记录",
    "权限约束 · 人工确认 · 审计记录",
    "研究有证据 · 行动有约束 · 过程可追溯",
    "个人可用 · 研究与风控工作流持续建设中",
)

SUBTITLE_GROUPS: tuple[tuple[str, ...], ...] = (
    ("这是我正在做的 AgomTradePro。", "目标，是让个人也能拥有机构级的", "研究与风控底座。"),
    ("个人可以自行部署。", "接下来，沿着一个研究想法，", "走过数据、研究、风控和复盘四条工作流。"),
    ("第一步，把研究建立在数据上。", "行情、宏观指标和财务材料汇集后，", "核对来源、观测时间和可用范围。"),
    ("数据过期、缺失或者不可靠，", "就保留原因、限制用途。", "每一个判断，先回答依据从哪里来、当时是否可用。"),
    ("第二条，是研究工作流。", "先看增长、通胀和政策环境，", "再深入行业、股票或基金，", "把环境判断与标的研究连起来。"),
    ("形成投资信号时，记录看好的理由，", "也写清什么条件出现，", "就要推翻判断。", "研究结论有依据，也有失效边界。"),
    ("第三条，是决策前的风控工作流。", "根据账户和策略，检查总仓位、", "单一标的集中度、现金底线，", "以及风险限制。"),
    ("拟议操作触碰约束，就拦截并说明原因；", "满足检查要求，再进入相应的审批流程。", "需要人工确认的步骤，", "保留在人的手里。"),
    ("第四条，是验证与复盘工作流。", "先用历史回测检查想法，", "再用模拟交易观察过程，", "把持仓变化和决策记录留下来。"),
    ("复盘时，回看当时用了什么证据、", "做了什么判断、触发了哪些限制。", "让下一次研究，可以沿着记录", "追溯和修正。"),
    ("AI 可以参与这些工作流：", "查数据、整理分析、提出方案。", "它的能力受权限和确认流程约束，", "重要操作留下审计记录。"),
    ("项目开源，持续开发中。", "你可以配置自己的数据源和 AI 服务，", "从日常研究开始，逐步搭建自己的方法。"),
    (),
)

CHAPTERS = (1, 1, 1, 1, 2, 2, 3, 3, 4, 4, 4, 4, 4)
NARRATION = narration_paragraphs()
ICON = Image.open(ICON_PATH).convert("RGBA")
ICON_SMALL = ICON.resize((66, 66), Image.Resampling.NEAREST)
ICON_220 = ICON.resize((220, 220), Image.Resampling.NEAREST)
BACKGROUND = art.make_background(0.37)
FONTS: dict[tuple[int, bool], ImageFont.FreeTypeFont] = {}


@dataclass(frozen=True)
class SubtitleCue:
    start: float
    end: float
    text: str


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (size, bold)
    if key not in FONTS:
        FONTS[key] = art.font(size, bold)
    return FONTS[key]


def center_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    size: int,
    color: tuple[int, int, int] = TEXT,
    bold: bool = False,
    spacing: int = 9,
) -> None:
    draw.multiline_text(
        xy,
        text,
        font=font(size, bold),
        fill=color,
        anchor="mm",
        align="center",
        spacing=spacing,
        stroke_width=0 if max(color) < 100 else 2,
        stroke_fill=(7, 16, 29),
    )


def rect(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: tuple[int, int, int],
    outline: tuple[int, int, int] = EDGE,
    radius: int = 22,
    width: int = 2,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def pill(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    color: tuple[int, int, int],
    fill: tuple[int, int, int] = (13, 27, 42),
    size: int = 18,
) -> None:
    draw.rounded_rectangle(box, radius=(box[3] - box[1]) // 2, fill=fill, outline=color, width=2)
    center_text(draw, ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2), text, size, color, True)


def panel_header(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str, color: tuple[int, int, int]) -> None:
    x1, y1, x2, _ = box
    draw.ellipse((x1 + 20, y1 + 21, x1 + 31, y1 + 32), fill=color)
    draw.text((x1 + 47, y1 + 13), title, font=font(23, True), fill=TEXT)
    draw.line((x1 + 20, y1 + 53, x2 - 20, y1 + 53), fill=(56, 78, 94), width=1)


def bullet(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, color: tuple[int, int, int] = MINT, size: int = 20) -> None:
    draw.ellipse((x, y + 9, x + 10, y + 19), fill=color)
    draw.text((x + 22, y), text, font=font(size), fill=TEXT)


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: tuple[int, int, int], progress: float = 1.0, width: int = 4) -> None:
    x1, y1 = start
    x2, y2 = end
    draw.line((start, end), fill=(56, 78, 94), width=max(2, width - 1))
    p = max(0.0, min(1.0, progress))
    ex = int(x1 + (x2 - x1) * p)
    ey = int(y1 + (y2 - y1) * p)
    draw.line((start, (ex, ey)), fill=color, width=width)
    if p >= 0.97:
        angle = math.atan2(y2 - y1, x2 - x1)
        wing = 12
        left = (x2 - wing * math.cos(angle - 0.55), y2 - wing * math.sin(angle - 0.55))
        right = (x2 - wing * math.cos(angle + 0.55), y2 - wing * math.sin(angle + 0.55))
        draw.polygon((end, left, right), fill=color)
    else:
        draw.ellipse((ex - 6, ey - 6, ex + 6, ey + 6), fill=color)


def draw_chrome(image: Image.Image, shot: int, local: float) -> None:
    draw = ImageDraw.Draw(image)
    image.alpha_composite(ICON_SMALL, (47, 40))
    draw.text((130, 49), "AgomTradePro", font=font(30, True), fill=TEXT)
    draw.text((132, 91), "个人工作台 · 流程示意", font=font(19), fill=MUTED)
    draw.text((1008, 55), f"{shot + 1:02d} / 13", font=font(20, True), fill=GOLD if shot < 6 else MINT, anchor="ra")
    draw.text((1008, 91), f"工作流 {CHAPTERS[shot]} / 04", font=font(17), fill=MUTED, anchor="ra")

    start_x = 72
    gap = 6
    bar_width = 67
    for index in range(13):
        x1 = start_x + index * (bar_width + gap)
        x2 = x1 + bar_width
        draw.rounded_rectangle((x1, 152, x2, 159), radius=3, fill=(45, 65, 82))
        amount = 1.0 if index < shot else (local if index == shot else 0.0)
        if amount > 0:
            color = GOLD if index <= 5 else MINT
            draw.rounded_rectangle((x1, 152, x1 + max(4, int(bar_width * amount)), 159), radius=3, fill=color)

    title = SHOT_TITLES[shot]
    title_size = 43
    while art.text_width(title, title_size, True) > 968 and title_size > 34:
        title_size -= 1
    center_text(draw, (540, 218), title, title_size, TEXT, True)
    center_text(draw, (540, 279), SHOT_SUBTITLES[shot], 20, MUTED)


def disclaimer(image: Image.Image) -> None:
    draw = ImageDraw.Draw(image)
    for y, line in ((1814, "AI不能替代人工决策"), (1855, "市场有风险 投资需谨慎")):
        width = draw.textbbox((0, 0), line, font=font(26))[2]
        draw.text((WIDTH - 26 - width, y), line, font=font(26), fill=(226, 233, 238))


def draw_intro(draw: ImageDraw.ImageDraw, local: float) -> None:
    size = 196 + int(24 * math.sin(local * math.pi))
    icon = ICON.resize((size, size), Image.Resampling.NEAREST)
    image = draw._image
    image.paste(icon, ((WIDTH - size) // 2, 360), icon)
    pill(draw, (410, 594, 670, 646), "目标", GOLD, size=20)
    center_text(draw, (540, 790), "让个人也能拥有\n机构级的研究与风控底座", 52, TEXT, True, spacing=19)
    center_text(draw, (540, 1012), "数据有依据  ·  决策有边界  ·  复盘可回溯", 24, MUTED)
    rect(draw, (287, 1114, 793, 1193), (14, 30, 47), (77, 111, 128), radius=36)
    center_text(draw, (540, 1154), "个人可用 · 研究与风控工作流", 22, MINT, True)
    pill(draw, (391, 1260, 689, 1322), "持续开发中", GOLD, size=21)


def draw_overview(draw: ImageDraw.ImageDraw, local: float) -> None:
    rect(draw, (110, 357, 970, 463), PANEL_LIGHT, (95, 126, 144), radius=20)
    draw.text((153, 382), "研究想法", font=font(25, True), fill=TEXT)
    draw.text((153, 425), "一条线索进入个人工作台", font=font(20), fill=MUTED)
    pill(draw, (730, 383, 925, 432), "同一条研究想法", GOLD, size=17)

    rows = (
        ("数据", "可核对的研究材料", GOLD),
        ("研究", "有依据、有边界的信号", MINT),
        ("风控", "逐项检查与阻断说明", AMBER),
        ("复盘", "决策记录与研究回流", MINT),
    )
    rail_x = 174
    for index, (name, output, tint) in enumerate(rows):
        y = 546 + index * 246
        row_local = max(0.0, min(1.0, local * 4.4 - index))
        color = tint if row_local > 0 else (76, 96, 110)
        rect(draw, (110, y, 970, y + 174), PANEL if row_local > 0 else (13, 24, 37), color, radius=22)
        draw.ellipse((rail_x - 26, y + 33, rail_x + 26, y + 85), fill=(13, 27, 42), outline=color, width=3)
        center_text(draw, (rail_x, y + 59), f"0{index + 1}", 18, color, True)
        draw.text((225, y + 29), f"工作流 {index + 1} · {name}", font=font(25, True), fill=TEXT if row_local > 0 else MUTED)
        draw.text((225, y + 83), output, font=font(21), fill=MINT if row_local > 0 else (97, 118, 134))
        if row_local > 0.2:
            pill(draw, (748, y + 52, 916, y + 103), "已点亮", tint, size=17)
        if index < 3:
            arrow(draw, (rail_x, y + 174), (rail_x, y + 232), tint, row_local)


def draw_data_sources(draw: ImageDraw.ImageDraw, local: float) -> None:
    sources = (
        ("行情", "来源 · 观测时间"),
        ("宏观指标", "来源 · 单位 · 观测时间"),
        ("财务材料", "报告期 · 来源 · 可用范围"),
    )
    visible = min(3, max(1, int(local * 3.6) + 1))
    for index, (title, detail) in enumerate(sources[:visible]):
        y = 381 + index * 176
        rect(draw, (72, y, 580, y + 137), PANEL_LIGHT, GOLD if index == 0 else MINT, radius=20)
        center_text(draw, (119, y + 68), f"0{index + 1}", 19, GOLD if index == 0 else MINT, True)
        draw.text((163, y + 25), title, font=font(24, True), fill=TEXT)
        draw.text((163, y + 75), detail, font=font(19), fill=MUTED)
        if index == visible - 1:
            scan_y = y + 112 + int(math.sin(local * math.tau) * 7)
            draw.line((157, scan_y, 538, scan_y), fill=GOLD, width=2)

    if local >= 0.28:
        rect(draw, (638, 391, 1008, 904), PAPER, (198, 213, 205), radius=22)
        draw.text((675, 425), "研究材料清单", font=font(25, True), fill=PAPER_INK)
        draw.line((675, 473, 972, 473), fill=(152, 171, 163), width=2)
        fields = ("来源可查", "源观测时间", "范围明确", "单位已标注")
        for index, field in enumerate(fields):
            y = 514 + index * 76
            draw.ellipse((678, y + 5, 695, y + 22), fill=MINT if index < visible + 1 else (145, 161, 154))
            draw.text((716, y), field, font=font(20), fill=PAPER_INK if index < visible + 1 else (98, 116, 110))
            draw.line((675, y + 46, 972, y + 46), fill=(180, 191, 185), width=1)
        pill(draw, (679, 826, 957, 872), "可核对的研究材料", MINT, fill=PAPER, size=17)

    if local >= 0.56:
        rect(draw, (81, 1036, 999, 1530), (14, 29, 45), (88, 120, 139), radius=25)
        draw.text((120, 1068), "放大检查 · 证据字段", font=font(23, True), fill=GOLD)
        field_rows = (("数据来源", "可追到具体来源"), ("源观测时间", "保留源观测时点"), ("可用范围", "明确能否用于研究"))
        for index, (name, detail) in enumerate(field_rows):
            y = 1130 + index * 112
            rect(draw, (120, y, 960, y + 79), (21, 41, 58), (65, 93, 111), radius=14)
            draw.text((149, y + 17), name, font=font(20, True), fill=TEXT)
            draw.text((510, y + 17), detail, font=font(19), fill=MUTED)
            if index == min(2, int(local * 5)):
                draw.rounded_rectangle((133, y + 7, 947, y + 72), radius=12, outline=MINT, width=2)


def draw_data_gate(draw: ImageDraw.ImageDraw, local: float) -> None:
    rect(draw, (78, 379, 1002, 661), PANEL, EDGE, radius=22)
    draw.text((116, 405), "资料可用性核对", font=font(24, True), fill=GOLD)
    rows = (("材料 A", "来源可查", MINT), ("观测时点", "符合要求", MINT), ("用途范围", "进入研究", MINT))
    for index, (left, right, color) in enumerate(rows):
        y = 465 + index * 57
        draw.text((126, y), left, font=font(20), fill=TEXT)
        draw.text((922, y), right, font=font(20), fill=color, anchor="ra")
        draw.line((126, y + 38, 954, y + 38), fill=(52, 75, 91), width=1)

    if local > 0.28:
        center_text(draw, (540, 722), "用途闸门", 21, MINT, True)
        draw.polygon(((540, 754), (581, 795), (540, 836), (499, 795)), fill=PANEL_LIGHT, outline=MINT)
        center_text(draw, (540, 795), "可用?", 17, TEXT, True)

    if local > 0.48:
        arrow(draw, (500, 795), (296, 866), MINT, min(1.0, (local - 0.48) * 4.4))
        rect(draw, (80, 878, 489, 1120), (16, 48, 49), MINT, radius=21)
        draw.text((115, 907), "材料可用", font=font(24, True), fill=TEXT)
        draw.text((115, 961), "来源与时点可核对", font=font(19), fill=(192, 218, 211))
        draw.text((115, 1013), "进入研究工作流", font=font(20, True), fill=MINT)

    if local > 0.68:
        arrow(draw, (580, 795), (784, 866), AMBER, min(1.0, (local - 0.68) * 4.0))
        rect(draw, (573, 878, 1000, 1120), (49, 39, 30), AMBER, radius=21)
        draw.text((609, 907), "不可用于决策", font=font(24, True), fill=TEXT)
        draw.text((609, 961), "原因：观测时间不满足要求", font=font(19), fill=(239, 205, 154))
        draw.text((609, 1013), "来源保留 · 限制用途", font=font(20, True), fill=AMBER)
        pill(draw, (706, 1055, 958, 1099), "不会刷新成新数据", AMBER, size=16)

    if local > 0.8:
        rect(draw, (168, 1226, 912, 1502), (12, 26, 42), (71, 96, 114), radius=24)
        draw.text((210, 1260), "数据用途结论", font=font(22, True), fill=TEXT)
        center_text(draw, (540, 1377), "有效材料进入研究\n受限材料停在闸门前", 28, TEXT, True, spacing=16)


def draw_research_path(draw: ImageDraw.ImageDraw, local: float) -> None:
    rect(draw, (78, 374, 494, 710), PANEL, (129, 104, 64), radius=23)
    draw.text((113, 401), "宏观与政策环境", font=font(24, True), fill=GOLD)
    macro = (("增长", "观察"), ("通胀", "观察"), ("政策", "脉络"))
    for index, (label, detail) in enumerate(macro):
        y = 474 + index * 70
        color = GOLD if local * 3.5 >= index else (95, 112, 126)
        draw.ellipse((115, y + 7, 131, y + 23), fill=color)
        draw.text((154, y), label, font=font(21, True), fill=TEXT if color == GOLD else MUTED)
        draw.text((432, y), detail, font=font(18), fill=color, anchor="ra")
        draw.line((154, y + 38, 448, y + 38), fill=(55, 76, 92), width=1)

    if local > 0.2:
        rect(draw, (612, 407, 1001, 657), PANEL_LIGHT, (71, 116, 114), radius=23)
        draw.text((648, 438), "政策脉络", font=font(23, True), fill=MINT)
        for i, label in enumerate(("政策材料", "影响路径", "待核对观点")):
            y = 500 + i * 49
            draw.ellipse((650, y + 4, 664, y + 18), fill=MINT if local > 0.2 + i * 0.13 else (79, 102, 117))
            draw.text((684, y), label, font=font(18), fill=TEXT if local > 0.2 + i * 0.13 else MUTED)

    if local > 0.38:
        arrow(draw, (494, 535), (612, 535), GOLD, min(1.0, (local - 0.38) * 5))
        arrow(draw, (808, 657), (808, 751), MINT, min(1.0, (local - 0.46) * 4))

    if local > 0.45:
        rect(draw, (120, 764, 958, 1077), PAPER, (198, 213, 205), radius=23)
        draw.text((159, 795), "行业与标的研究", font=font(25, True), fill=PAPER_INK)
        draw.text((159, 846), "行业观察  →  股票 / 基金", font=font(21), fill=(74, 95, 93))
        entry_labels = (("行业观察", GOLD), ("估值研究", MINT), ("因子分析", GOLD))
        for index, (label, color) in enumerate(entry_labels):
            x = 161 + index * 257
            rect(draw, (x, 918, x + 234, 984), (207, 219, 213), color, radius=15, width=1)
            center_text(draw, (x + 117, 951), label, 18, PAPER_INK, True)
        draw.text((159, 1021), "环境判断与标的资料进入同一研究案卷", font=font(18), fill=(71, 93, 90))

    if local > 0.7:
        rect(draw, (184, 1164, 895, 1512), PANEL, (82, 114, 130), radius=23)
        draw.text((222, 1194), "研究案卷 · 过程留痕", font=font(23, True), fill=TEXT)
        rows = (("环境判断", "增长 / 通胀 / 政策"), ("标的研究", "行业 / 股票 / 基金"), ("来源时点", "逐项核对"))
        for index, (left, right) in enumerate(rows):
            y = 1260 + index * 70
            draw.text((224, y), left, font=font(19, True), fill=MINT if index != 1 else GOLD)
            draw.text((492, y), right, font=font(18), fill=MUTED)
            draw.line((224, y + 42, 855, y + 42), fill=(57, 80, 97), width=1)


def draw_signal(draw: ImageDraw.ImageDraw, local: float) -> None:
    rect(draw, (79, 376, 566, 1128), PAPER, (198, 213, 205), radius=24)
    draw.text((117, 405), "研究案卷", font=font(25, True), fill=PAPER_INK)
    pill(draw, (374, 394, 530, 438), "证据清单", MINT, fill=PAPER, size=16)
    evidence = (("来源", "资料出处"), ("源观测时间", "记录时点"), ("研究理由", "观点与依据"))
    for index, (name, detail) in enumerate(evidence):
        y = 490 + index * 120
        rect(draw, (115, y, 528, y + 85), (208, 219, 214), (170, 186, 179), radius=15, width=1)
        draw.text((140, y + 14), name, font=font(20, True), fill=PAPER_INK)
        draw.text((140, y + 49), detail, font=font(17), fill=(79, 97, 91))
        if local > 0.15 + index * 0.14:
            draw.rounded_rectangle((124, y + 6, 518, y + 78), radius=12, outline=MINT, width=2)

    if local > 0.3:
        arrow(draw, (566, 706), (619, 706), GOLD, min(1.0, (local - 0.3) * 6))
        rect(draw, (620, 376, 1001, 1128), PANEL, (127, 100, 60), radius=24)
        draw.text((658, 405), "投资信号", font=font(25, True), fill=GOLD)
        draw.text((658, 482), "研究理由", font=font(21, True), fill=MINT)
        bullet(draw, 660, 532, "环境与标的的关联", MINT, 18)
        bullet(draw, 660, 579, "证据支持当前判断", MINT, 18)
        draw.line((658, 644, 962, 644), fill=(57, 80, 96), width=1)
        draw.text((658, 673), "支撑证据", font=font(20, True), fill=TEXT)
        draw.text((658, 722), "来源 · 时点 · 可用范围", font=font(18), fill=MUTED)

    if local > 0.53:
        rect(draw, (658, 805, 962, 1038), (42, 35, 27), AMBER, radius=18)
        draw.text((688, 834), "证伪条件", font=font(21, True), fill=AMBER)
        draw.text((688, 888), "假设失效 / 新证据出现", font=font(18), fill=TEXT)
        draw.text((688, 934), "触发后重新评估", font=font(18, True), fill=AMBER)
        draw.ellipse((687, 984, 700, 997), fill=AMBER)

    if local > 0.72:
        arrow(draw, (787, 1039), (548, 1190), GOLD, min(1.0, (local - 0.72) * 4.5))
        rect(draw, (250, 1198, 830, 1370), (17, 35, 51), GOLD, radius=20)
        center_text(draw, (540, 1248), "条件触发", 19, GOLD, True)
        center_text(draw, (540, 1310), "返回案卷 · 重新评估", 24, TEXT, True)
        arrow(draw, (250, 1282), (119, 1282), GOLD, min(1.0, (local - 0.8) * 5))


def draw_risk_checks(draw: ImageDraw.ImageDraw, local: float) -> None:
    # The example account/config tag stays visible throughout both risk shots.
    pill(draw, (709, 344, 1000, 393), "示例账户 / 示例配置", GOLD, size=17)
    rect(draw, (78, 420, 1002, 1519), PANEL, EDGE, radius=24)
    draw.text((119, 454), "拟议买入 · 前置风险检查", font=font(24, True), fill=TEXT)
    draw.text((119, 500), "来源于示例策略配置的相对约束", font=font(18), fill=MUTED)
    rows = (
        ("总仓位", "对照组合整体边界", GOLD),
        ("单一标的集中度", "核验拟议操作后的暴露", AMBER),
        ("现金底线", "检查账户现金约束", MINT),
        ("风险限制", "命中硬性排除即停止", AMBER),
    )
    for index, (title, detail, color) in enumerate(rows):
        y = 616 + index * 179
        rect(draw, (118, y, 960, y + 125), (20, 39, 55), (54, 78, 95), radius=18)
        scanned = local * 4.3
        if index < scanned:
            draw.rounded_rectangle((119, y + 1, 959, y + 124), radius=17, outline=color, width=2)
        draw.ellipse((152, y + 32, 173, y + 53), fill=color if index < scanned else (71, 91, 106))
        draw.text((202, y + 24), title, font=font(22, True), fill=TEXT if index < scanned else MUTED)
        draw.text((202, y + 69), detail, font=font(18), fill=MUTED)
        if index < int(scanned):
            center_text(draw, (904, y + 61), "✓", 23, MINT, True)
        elif index == min(3, int(scanned)):
            scan_y = y + 4 + int((local * 4.3 % 1) * 110)
            draw.line((136, scan_y, 942, scan_y), fill=(*color,), width=2)
    center_text(draw, (540, 1451), "逐行检查 · 不展示真实账户数字", 19, MUTED)


def draw_risk_branch(draw: ImageDraw.ImageDraw, local: float) -> None:
    # Keep the example label on every frame in this shot.
    pill(draw, (704, 343, 1000, 393), "示例账户 / 示例配置", GOLD, size=17)
    if local < 0.30:
        rect(draw, (85, 478, 995, 1278), (48, 38, 29), AMBER, radius=25)
        draw.text((126, 523), "首次检查 · 阻断", font=font(28, True), fill=TEXT)
        draw.text((126, 601), "单一标的集中度", font=font(21), fill=(240, 210, 166))
        center_text(draw, (540, 801), "18% 当前  +  4% 拟增加", 34, TEXT, True)
        center_text(draw, (540, 899), "= 22%  >  示例上限 20%", 32, AMBER, True)
        draw.line((173, 964, 907, 964), fill=(134, 97, 53), width=2)
        center_text(draw, (540, 1042), "阻断原因：超过单一标的上限", 23, AMBER, True)
        center_text(draw, (540, 1122), "后续操作停止 · 等待方案调整", 20, MUTED)
        pill(draw, (349, 1172, 731, 1220), "示例数字 · 非实际账户", AMBER, size=17)
    elif local < 0.48:
        rect(draw, (97, 480, 983, 840), (48, 38, 29), AMBER, radius=23)
        draw.text((139, 515), "原方案已阻断", font=font(24, True), fill=AMBER)
        center_text(draw, (540, 636), "18% + 4% = 22%  >  20%", 31, TEXT, True)
        arrow(draw, (540, 862), (540, 1011), MINT, min(1.0, (local - 0.30) / 0.18))
        rect(draw, (177, 1034, 903, 1281), PANEL_LIGHT, MINT, radius=22)
        center_text(draw, (540, 1094), "调整拟议幅度", 22, TEXT, True)
        center_text(draw, (540, 1160), "拟增加 4%  →  改为 1%", 29, MINT, True)
        center_text(draw, (540, 1230), "重新检查", 19, MUTED)
    else:
        rect(draw, (86, 441, 994, 766), (48, 38, 29), AMBER, radius=22)
        draw.text((123, 464), "上次检查 · 已阻断", font=font(21, True), fill=AMBER)
        center_text(draw, (540, 548), "18% + 4% = 22%  >  20%", 25, TEXT, True)
        center_text(draw, (540, 625), "单一标的集中度超限", 18, AMBER, True)
        arrow(draw, (540, 770), (540, 838), MINT, min(1.0, (local - 0.48) * 4.2))
        rect(draw, (86, 858, 994, 1438), (16, 45, 48), MINT, radius=23)
        draw.text((123, 883), "修改后复核", font=font(23, True), fill=TEXT)
        center_text(draw, (540, 1018), "18% 当前  +  1% 拟增加", 30, TEXT, True)
        center_text(draw, (540, 1094), "= 19%  ≤  示例上限 20%", 27, MINT, True)
        draw.line((154, 1156, 926, 1156), fill=(63, 112, 102), width=2)
        center_text(draw, (540, 1220), "其余检查条件满足", 21, (195, 224, 216), True)
        pill(draw, (329, 1277, 751, 1342), "待人工确认", MINT, size=21)
        center_text(draw, (540, 1391), "人工审批后再决定下一步", 19, MUTED)


def draw_candles(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], local: float) -> None:
    x1, y1, x2, y2 = box
    rect(draw, box, (10, 23, 38), (58, 82, 99), radius=15, width=1)
    draw.text((x1 + 16, y1 + 12), "历史序列 · 示意", font=font(16), fill=MUTED)
    baseline = y2 - 24
    heights = (35, 57, 49, 74, 66, 48, 82, 69, 96, 78, 104, 88)
    visible = max(1, min(len(heights), int(local * 19) + 1))
    for index, base_height in enumerate(heights[:visible]):
        x = x1 + 32 + index * 21
        h = base_height
        color = RED if index % 2 == 0 else GREEN
        open_y = baseline - h + (9 if index % 2 == 0 else -8)
        close_y = baseline - h + (-8 if index % 2 == 0 else 9)
        low_y = max(y1 + 41, min(open_y, close_y) - 12)
        high_y = max(open_y, close_y) + 13
        draw.line((x, low_y, x, high_y), fill=color, width=2)
        draw.rectangle((x - 6, min(open_y, close_y), x + 6, max(open_y, close_y)), fill=color)


def draw_validation(draw: ImageDraw.ImageDraw, local: float) -> None:
    rect(draw, (78, 379, 1002, 726), PANEL, (133, 104, 59), radius=22)
    draw.text((116, 407), "01 · 历史回测", font=font(24, True), fill=GOLD)
    pill(draw, (803, 396, 967, 440), "历史数据", GOLD, size=17)
    draw_candles(draw, (116, 467, 483, 695), local)
    draw.text((526, 488), "检验研究想法", font=font(22, True), fill=TEXT)
    bullet(draw, 530, 540, "历史区间 · 策略条件", GOLD, 18)
    bullet(draw, 530, 586, "观察结果 · 使用边界", MINT, 18)
    draw.text((530, 647), "历史验证，帮助发现方法的局限", font=font(17), fill=MUTED)

    if local > 0.32:
        rect(draw, (166, 792, 1002, 1120), (14, 34, 49), (70, 128, 124), radius=22)
        draw.text((206, 820), "02 · 模拟交易", font=font(24, True), fill=TEXT)
        pill(draw, (808, 810, 967, 853), "非实盘", MINT, size=17)
        entries = (("拟议操作", "模拟环境"), ("规则检查", "记录状态"), ("模拟回执", "留存结果"))
        count = min(3, max(1, int((local - 0.32) * 9) + 1))
        for index, (label, status) in enumerate(entries[:count]):
            y = 885 + index * 67
            rect(draw, (205, y, 960, y + 50), (20, 44, 60), (51, 78, 95), radius=10, width=1)
            draw.text((230, y + 13), label, font=font(18), fill=TEXT)
            draw.text((935, y + 13), status, font=font(17), fill=MINT if index == 2 else MUTED, anchor="ra")

    if local > 0.65:
        rect(draw, (78, 1187, 1002, 1547), PANEL_LIGHT, (73, 117, 112), radius=22)
        draw.text((117, 1215), "03 · 持仓跟踪", font=font(24, True), fill=TEXT)
        pill(draw, (786, 1205, 968, 1248), "变化留痕", MINT, size=17)
        rows = (("持仓变化", GOLD), ("风险状态", AMBER), ("研究假设", MINT))
        count = min(3, max(1, int((local - 0.65) * 11) + 1))
        for index, (label, color) in enumerate(rows[:count]):
            y = 1293 + index * 69
            draw.text((120, y), label, font=font(18), fill=MUTED)
            draw.rounded_rectangle((350, y + 2, 929, y + 24), radius=8, fill=(31, 50, 63))
            width = (320, 420, 360)[index]
            draw.rounded_rectangle((350, y + 2, 350 + width, y + 24), radius=8, fill=color)
            draw.text((946, y + 2), "记录", font=font(16), fill=color, anchor="ra")


def draw_audit(draw: ImageDraw.ImageDraw, local: float) -> None:
    # Pale audit paper gives this chapter a different visual register.
    rect(draw, (96, 374, 984, 1500), PAPER, (198, 213, 205), radius=24)
    draw.text((137, 412), "决策审计 · 复盘案卷", font=font(26, True), fill=PAPER_INK)
    pill(draw, (778, 400, 946, 446), "流程示意", MINT, fill=PAPER, size=17)
    draw.text((139, 469), "同一条研究想法 · 过程记录", font=font(18), fill=(78, 97, 91))
    draw.line((138, 512, 944, 512), fill=(157, 176, 168), width=2)
    rows = (
        ("当时证据", "来源 · 源观测时间 · 可用范围"),
        ("研究判断", "理由 · 投资信号 · 证伪条件"),
        ("风险结果", "总仓位 · 集中度 · 阻断原因"),
        ("处理记录", "审批状态 · 模拟过程 · 后续回顾"),
    )
    visible = min(4, max(1, int(local * 4.7) + 1))
    for index, (title, detail) in enumerate(rows[:visible]):
        y = 555 + index * 135
        draw.ellipse((140, y + 9, 184, y + 53), fill=(209, 221, 215), outline=(77, 112, 103), width=2)
        center_text(draw, (162, y + 31), f"0{index + 1}", 16, (62, 91, 84), True)
        draw.text((210, y + 6), title, font=font(21, True), fill=PAPER_INK)
        draw.text((210, y + 52), detail, font=font(18), fill=(77, 96, 91))
        draw.line((210, y + 96, 943, y + 96), fill=(176, 190, 184), width=1)
        if index == min(visible - 1, int(local * 4)):
            draw.rounded_rectangle((198, y - 4, 955, y + 101), radius=13, outline=MINT, width=2)

    if local > 0.56:
        pill(draw, (139, 1136, 943, 1194), "风险日报  ·  持仓日报  ·  历史记录", GOLD, fill=(214, 224, 218), size=20)
        center_text(draw, (540, 1273), "沿记录回看依据、判断与处理", 20, (74, 94, 88), True)
    if local > 0.74:
        arrow(draw, (809, 1368), (356, 1368), GOLD, min(1.0, (local - 0.74) * 4))
        pill(draw, (331, 1397, 749, 1454), "复盘结论 → 下一轮研究", MINT, fill=(214, 224, 218), size=18)


def draw_ai(draw: ImageDraw.ImageDraw, local: float) -> None:
    pill(draw, (757, 351, 998, 399), "辅助轨 · 流程示意", MINT, size=17)
    workflows = (("数据", 471), ("研究", 682), ("风控", 893), ("复盘", 1104))
    for index, (label, y) in enumerate(workflows):
        rect(draw, (78, y, 300, y + 88), PANEL_LIGHT, (62, 94, 112), radius=17)
        draw.text((110, y + 25), f"0{index + 1} · {label}", font=font(19, True), fill=TEXT)
        if local > index * 0.13:
            draw.ellipse((266, y + 35, 281, y + 50), fill=MINT if index < 2 else GOLD)

    rect(draw, (379, 416, 1001, 1202), PANEL, (76, 110, 126), radius=24)
    draw._image.paste(ICON_SMALL, (416, 443), ICON_SMALL)
    draw.text((496, 454), "AI 辅助轨", font=font(25, True), fill=TEXT)
    draw.text((496, 496), "受权限与确认流程约束", font=font(18), fill=MUTED)
    steps = (("查数据", "补齐来源与观测时间"), ("整理分析", "把材料与判断关联"), ("提出方案", "形成待审阅内容"))
    visible = min(3, max(1, int(local * 4.4) + 1))
    for index, (title, detail) in enumerate(steps[:visible]):
        y = 577 + index * 187
        draw.ellipse((423, y, 469, y + 46), fill=(14, 30, 45), outline=MINT if index < 2 else GOLD, width=2)
        center_text(draw, (446, y + 23), f"0{index + 1}", 16, MINT if index < 2 else GOLD, True)
        draw.text((496, y + 2), title, font=font(22, True), fill=TEXT)
        draw.text((496, y + 51), detail, font=font(18), fill=MUTED)
        if index < 2:
            arrow(draw, (446, y + 47), (446, y + 145), MINT, local)

    if local > 0.61:
        arrow(draw, (690, 1203), (690, 1264), GOLD, min(1.0, (local - 0.61) * 4))
        rect(draw, (178, 1279, 1000, 1510), (17, 39, 54), GOLD, radius=23)
        center_text(draw, (589, 1327), "人工确认边界", 24, TEXT, True)
        center_text(draw, (589, 1380), "重要操作经审阅后继续", 19, MUTED)
        pill(draw, (248, 1430, 569, 1481), "人工确认", MINT, size=18)
        pill(draw, (611, 1430, 928, 1481), "退回修改 / 保持阻断", AMBER, size=17)
    if local > 0.82:
        center_text(draw, (540, 1580), "重要操作保留审计记录", 20, GOLD, True)


def draw_closing(draw: ImageDraw.ImageDraw, local: float) -> None:
    icon_size = int(194 + 18 * math.sin(local * math.pi))
    closing_icon = ICON.resize((icon_size, icon_size), Image.Resampling.NEAREST)
    draw._image.paste(closing_icon, ((WIDTH - icon_size) // 2, 364), closing_icon)
    outputs = (("数据", "材料可核对"), ("研究", "信号有边界"), ("风控", "行动有约束"), ("复盘", "过程可追溯"))
    for index, (label, output) in enumerate(outputs):
        x = 83 + index * 242
        y = 682 + (index % 2) * 160
        rect(draw, (x, y, x + 224, y + 118), PANEL_LIGHT, GOLD if index == 0 else MINT, radius=19)
        center_text(draw, (x + 112, y + 37), label, 21, GOLD if index == 0 else MINT, True)
        center_text(draw, (x + 112, y + 81), output, 17, TEXT)

    if local > 0.35:
        rect(draw, (153, 1062, 927, 1178), (13, 28, 44), (81, 109, 125), radius=22)
        center_text(draw, (540, 1096), "自设数据源 · 配置 AI 服务 · 从日常研究开始", 21, TEXT, True)
        center_text(draw, (540, 1144), "持续开发中", 19, GOLD, True)
    if local > 0.58:
        center_text(draw, (540, 1325), "研究有证据  ·  行动有约束  ·  过程可追溯", 25, TEXT, True)
        center_text(draw, (540, 1404), "目标：让个人也能拥有机构级的研究与风控底座", 20, MUTED)


def draw_endcard(draw: ImageDraw.ImageDraw, local: float) -> None:
    size = 154
    end_icon = ICON.resize((size, size), Image.Resampling.NEAREST)
    draw._image.paste(end_icon, ((WIDTH - size) // 2, 520), end_icon)
    center_text(draw, (540, 747), "AgomTradePro", 49, TEXT, True)
    center_text(draw, (540, 844), "目标：让个人也能拥有\n机构级的研究与风控底座", 35, TEXT, True, spacing=12)
    pill(draw, (393, 1017, 687, 1076), "持续开发中", GOLD, size=20)


DRAW_SHOTS = (
    draw_intro,
    draw_overview,
    draw_data_sources,
    draw_data_gate,
    draw_research_path,
    draw_signal,
    draw_risk_checks,
    draw_risk_branch,
    draw_validation,
    draw_audit,
    draw_ai,
    draw_closing,
    draw_endcard,
)


def _subtitle_cues(segment_durations: Sequence[float]) -> tuple[SubtitleCue, ...]:
    cues: list[SubtitleCue] = []
    for segment_index, (phrases, segment_duration) in enumerate(zip(SUBTITLE_GROUPS, segment_durations)):
        if not phrases:
            continue
        scene_start = BOUNDARIES[segment_index]
        speech_start = scene_start + 0.20
        usable = min(segment_duration, BOUNDARIES[segment_index + 1] - scene_start - 0.22)
        usable = max(0.1, usable - 0.10 * max(0, len(phrases) - 1))
        weights = [max(1.0, sum(0.55 if ord(char) < 128 else 1.0 for char in phrase if not char.isspace())) for phrase in phrases]
        total_weight = sum(weights)
        cursor = speech_start
        for phrase, weight in zip(phrases, weights):
            part = usable * weight / total_weight
            cue_end = cursor + part
            cues.append(SubtitleCue(cursor, cue_end, _wrap_subtitle(phrase)))
            cursor = cue_end + 0.10
    return tuple(cues)


def _wrap_subtitle(text: str) -> str:
    """Wrap captions by measured pixel width without splitting Latin words."""
    max_width = 880
    if art.text_width(text, 29, True) <= max_width:
        return text
    parts: list[str] = []
    current = ""
    tokens = re.findall(r"[A-Za-z0-9]+|\s+|.", text)
    for token in tokens:
        candidate = current + token
        if art.text_width(candidate.strip(), 29, True) > max_width and current.strip():
            parts.append(current.strip())
            current = token.lstrip()
        else:
            current = candidate
    if current.strip():
        parts.append(current.strip())
    return "\n".join(parts[:2])


def _srt_time(seconds: float) -> str:
    millis_total = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(millis_total, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds_int, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds_int:02d},{milliseconds:03d}"


def write_srt(cues: Sequence[SubtitleCue], path: Path) -> None:
    lines: list[str] = []
    for index, cue in enumerate(cues, start=1):
        lines.extend((str(index), f"{_srt_time(cue.start)} --> {_srt_time(cue.end)}", cue.text, ""))
    path.write_text("\n".join(lines), encoding="utf-8-sig")


def subtitle_at(cues: Sequence[SubtitleCue], starts: Sequence[float], t: float) -> str | None:
    index = bisect.bisect_right(starts, t) - 1
    if index >= 0 and cues[index].start <= t <= cues[index].end:
        return cues[index].text
    return None


def shot_at(t: float) -> tuple[int, float]:
    shot = min(len(BOUNDARIES) - 2, max(0, bisect.bisect_right(BOUNDARIES, t) - 1))
    duration = BOUNDARIES[shot + 1] - BOUNDARIES[shot]
    return shot, max(0.0, min(1.0, (t - BOUNDARIES[shot]) / duration))


def render_frame(t: float, cues: Sequence[SubtitleCue], cue_starts: Sequence[float], include_subtitles: bool = True) -> Image.Image:
    shot, local = shot_at(t)
    image = BACKGROUND.copy()
    draw_chrome(image, shot, local)
    draw = ImageDraw.Draw(image)
    DRAW_SHOTS[shot](draw, local)

    if include_subtitles:
        caption = subtitle_at(cues, cue_starts, t)
        if caption:
            center_text(draw, (540, 1716), caption, 29, TEXT, True, spacing=5)
    disclaimer(image)
    return image.convert("RGB")


def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", str(path), "-f", "null", "NUL"],
        check=False,
        capture_output=True,
        text=True,
    )
    output = result.stderr + result.stdout
    match = re.search(r"Duration: (\d\d):(\d\d):(\d\d\.\d\d)", output)
    if not match:
        raise RuntimeError(f"Could not read audio duration from {path.name}: {output[-800:]}")
    return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))


def run_checked(command: Sequence[str], log_path: Path, label: str) -> None:
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n## {label}\n$ {' '.join(command)}\n")
        log.write(result.stdout)
        log.write(result.stderr)
        log.flush()
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed ({result.returncode}). See {log_path}")


def generate_music(path: Path) -> None:
    sample_rate = 48_000
    chunk_size = sample_rate
    chord_sets = (
        (130.81, 196.00, 261.63, 329.63),
        (110.00, 164.81, 220.00, 293.66),
        (146.83, 220.00, 293.66, 369.99),
        (98.00, 146.83, 196.00, 261.63),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        total_samples = int(DURATION * sample_rate)
        for offset in range(0, total_samples, chunk_size):
            count = min(chunk_size, total_samples - offset)
            times = (np.arange(count, dtype=np.float64) + offset) / sample_rate
            chord_index = np.minimum((times / 37.5).astype(np.int32), len(chord_sets) - 1)
            signal = np.zeros(count, dtype=np.float64)
            for chord_id, frequencies in enumerate(chord_sets):
                selected = chord_index == chord_id
                if not np.any(selected):
                    continue
                local_times = times[selected]
                chord = np.zeros(local_times.size, dtype=np.float64)
                for index, frequency in enumerate(frequencies):
                    amplitude = (0.011, 0.008, 0.006, 0.004)[index]
                    chord += amplitude * np.sin(2 * np.pi * frequency * local_times + index * 0.35)
                signal[selected] = chord
            envelope = 0.72 + 0.20 * np.sin(2 * np.pi * times / 13.0)
            fade_in = np.clip(times / 2.0, 0.0, 1.0)
            fade_out = np.clip((DURATION - times) / 3.0, 0.0, 1.0)
            signal *= envelope * fade_in * fade_out
            stereo = np.column_stack((signal, signal * 0.94))
            pcm = np.clip(stereo * 32767.0, -32768, 32767).astype(np.int16)
            target.writeframesraw(pcm.tobytes())


def prepare_audio(log_path: Path) -> tuple[Path, Path, tuple[SubtitleCue, ...], tuple[float, ...]]:
    if not VOICE_DIR.exists():
        raise FileNotFoundError(f"V2 Edge TTS cache is missing: {VOICE_DIR}")
    voice_paths = tuple(VOICE_DIR / f"voice-{index:02d}.mp3" for index in range(1, 13))
    missing = [path for path in voice_paths if not path.exists() or path.stat().st_size == 0]
    if missing:
        raise FileNotFoundError(f"Missing Edge TTS segments: {', '.join(path.name for path in missing)}")
    durations = tuple(_probe_duration(path) for path in voice_paths)
    for index, duration in enumerate(durations):
        available = BOUNDARIES[index + 1] - BOUNDARIES[index] - 0.23
        if duration > available:
            raise ValueError(f"Narration segment {index + 1} is {duration:.2f}s but its window is {available:.2f}s")

    cues = _subtitle_cues(durations)
    srt_path = OUTPUT_DIR / "captions.srt"
    write_srt(cues, srt_path)
    music_path = TEMP_DIR / "audio" / "original-ambient-pad-150s.wav"
    if not music_path.exists() or music_path.stat().st_size == 0:
        generate_music(music_path)

    voice_only_path = OUTPUT_DIR / "narration.wav"
    args: list[str] = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y"]
    for path in voice_paths:
        args.extend(("-i", str(path)))
    graph: list[str] = []
    delayed_labels: list[str] = []
    for index in range(12):
        delay_ms = int((BOUNDARIES[index] + 0.20) * 1000)
        graph.append(f"[{index}:a]adelay={delay_ms}|{delay_ms}[v{index}]")
        delayed_labels.append(f"[v{index}]")
    graph.append("".join(delayed_labels) + "amix=inputs=12:normalize=0:duration=longest,apad=pad_dur=2,loudnorm=I=-16.8:TP=-1.5:LRA=11[v]")
    args.extend(("-filter_complex", ";".join(graph), "-map", "[v]", "-t", "150", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(voice_only_path)))
    run_checked(args, log_path, "voice-only-normalize")

    mixed_path = TEMP_DIR / "audio" / "agomtradepro-audio-v2.wav"
    mix_command = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(voice_only_path), "-i", str(music_path),
        "-filter_complex",
        "[0:a]volume=1.0[v];[1:a]volume=1.0[m];[v][m]amix=inputs=2:normalize=0:duration=longest,alimiter=limit=0.84,loudnorm=I=-16.8:TP=-1.5:LRA=11[out]",
        "-map", "[out]", "-t", "150", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(mixed_path),
    ]
    run_checked(mix_command, log_path, "voice-music-mix")
    return voice_only_path, mixed_path, cues, durations


def encode_video_only(output_path: Path, cues: Sequence[SubtitleCue], log_path: Path, threads: int = 4) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", f"{WIDTH}x{HEIGHT}", "-framerate", str(FPS), "-i", "-",
        "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-threads", str(threads), "-movflags", "+faststart", str(output_path),
    ]
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n## video-render ({FRAME_COUNT} frames, {FPS} fps, {threads} threads)\n$ {' '.join(command)}\n")
        log.flush()
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert process.stdin is not None
    starts = tuple(cue.start for cue in cues)
    start_time = time.monotonic()
    progress_log = TEMP_DIR / "qa" / "render-progress.log"
    progress_log.parent.mkdir(parents=True, exist_ok=True)
    try:
        for frame_index in range(FRAME_COUNT):
            timestamp = frame_index / FPS
            frame = render_frame(timestamp, cues, starts)
            process.stdin.write(frame.tobytes())
            if frame_index % 150 == 0 or frame_index == FRAME_COUNT - 1:
                percent = 100.0 * (frame_index + 1) / FRAME_COUNT
                message = f"{frame_index + 1}/{FRAME_COUNT} frames ({percent:.1f}%), elapsed {time.monotonic() - start_time:.0f}s"
                with progress_log.open("a", encoding="utf-8") as progress:
                    progress.write(message + "\n")
                if frame_index % 600 == 0 or frame_index == FRAME_COUNT - 1:
                    print(message, flush=True)
        process.stdin.close()
    except BaseException:
        process.kill()
        raise
    stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
    return_code = process.wait()
    with log_path.open("a", encoding="utf-8") as log:
        log.write(stderr)
        log.write(f"\nvideo render exit code: {return_code}\n")
    if return_code != 0:
        raise RuntimeError(f"H.264 render failed ({return_code}). See {log_path}: {stderr[-1200:]}")


def make_cover(path: Path, cues: Sequence[SubtitleCue]) -> None:
    starts = tuple(cue.start for cue in cues)
    render_frame(4.1, cues, starts, include_subtitles=False).save(path, format="PNG", optimize=True)


def mux_final(video_only: Path, mixed_audio: Path, final_path: Path, log_path: Path) -> None:
    command = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video_only), "-i", str(mixed_audio),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-t", "150", "-threads", "2", "-movflags", "+faststart", str(final_path),
    ]
    run_checked(command, log_path, "mux-final-mp4")


def final_media_qa(final_path: Path) -> tuple[float, float]:
    qa_dir = TEMP_DIR / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    decode_log = qa_dir / "full-decode.log"
    decode = subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "info", "-i", str(final_path), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "NUL"],
        check=False,
        capture_output=True,
        text=True,
    )
    decode_text = decode.stderr + decode.stdout
    decode_log.write_text(decode_text, encoding="utf-8")
    if decode.returncode != 0:
        raise RuntimeError(f"Full MP4 decode failed. See {decode_log}")
    duration_match = re.search(r"Duration: (\d\d):(\d\d):(\d\d\.\d\d)", decode_text)
    if duration_match:
        duration = int(duration_match.group(1)) * 3600 + int(duration_match.group(2)) * 60 + float(duration_match.group(3))
        if abs(duration - DURATION) > 0.05:
            raise RuntimeError(f"Final duration is {duration:.2f}s, expected {DURATION:.2f}s")
    if "1080x1920" not in decode_text or "30 fps" not in decode_text:
        raise RuntimeError(f"Unexpected final video stream geometry or frame rate. See {decode_log}")

    loudness = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", str(final_path), "-map", "0:a:0", "-af", "ebur128=peak=true", "-f", "null", "NUL"],
        check=False,
        capture_output=True,
        text=True,
    )
    loudness_text = loudness.stderr + loudness.stdout
    (qa_dir / "audio-loudness.log").write_text(loudness_text, encoding="utf-8")
    if loudness.returncode != 0:
        raise RuntimeError(f"Final audio loudness check failed. See {qa_dir / 'audio-loudness.log'}")
    integrated_matches = re.findall(r"\bI:\s*(-?\d+(?:\.\d+)?)\s*LUFS", loudness_text)
    peak_matches = re.findall(r"\bPeak:\s*(-?\d+(?:\.\d+)?)\s*dBFS", loudness_text)
    if not integrated_matches or not peak_matches:
        raise RuntimeError(f"Could not parse integrated loudness and true peak. See {qa_dir / 'audio-loudness.log'}")
    integrated_lufs = float(integrated_matches[-1])
    true_peak = float(peak_matches[-1])
    duration_text = duration_match.group(0).split(": ", 1)[1] if duration_match else "not reported"
    (qa_dir / "media-qa-summary.txt").write_text(
        f"Full MP4 decode: pass\nDuration: {duration_text}\nFrame target: {FRAME_COUNT}\n"
        f"Video: H.264, 1080x1920, 30 fps, yuv420p\nAudio: AAC 48 kHz stereo\n"
        f"Integrated loudness: {integrated_lufs:.1f} LUFS\nTrue peak: {true_peak:.1f} dBTP\n",
        encoding="utf-8",
    )
    return integrated_lufs, true_peak


def write_readme(
    video_path: Path,
    voice_path: Path,
    mixed_audio: Path,
    srt_path: Path,
    cover_path: Path,
    measured_lufs: float,
    measured_true_peak: float,
) -> None:
    readme = OUTPUT_DIR / "制作说明.md"
    body = f"""# AgomTradePro V2 竖屏宣传视频

## 交付文件

- 成片：`{video_path.name}`（1080×1920、30 fps、150.00秒、H.264 High / yuv420p、AAC 48 kHz 双声道）
- 封面：`{cover_path.name}`
- 字幕：`{srt_path.name}`
- 配音：`{voice_path.name}`
- 原创背景音乐混音临时文件：`.tmp/agom-brand-video-20261028-v2/audio/{mixed_audio.name}`
- 可重现渲染器：`render_v2_video.py`
- 分镜图形：`render_storyboards.py`
- Edge TTS 脚本：`synthesize_voice.py`

## Re-render

从仓库根目录使用现有 `agomtradepro` Python 环境与隔离的视频依赖：

```powershell
.\\agomtradepro\\Scripts\\python.exe docs\\video\\agomtradepro-promo-20261028-v2\\synthesize_voice.py
.\\agomtradepro\\Scripts\\python.exe docs\\video\\agomtradepro-promo-20261028-v2\\render_v2_video.py --render
```

配音使用 `{VOICE}`、语速 `{RATE}`。分段语音按正文 SHA-256 缓存在 `.tmp/agom-brand-video-20261028-v2/audio/`；没有 SAPI 替代。原创轻背景音乐由正弦波合成，没有下载外部音乐。

## Content boundaries

所有功能画面均为原创流程示意，没有冒充当前生产实录。18% + 4% → 22% / 示例上限20%的过程持续标注为“示例账户 / 示例配置”，不是实际账户或项目默认阈值。调整拟议幅度后才显示19%复核结果，并标注“待人工确认”。回测和模拟场景明确标为“历史数据”和“非实盘”；没有展示收益承诺或真实成交。“机构级”只作为产品目标表述。

右下角两行风险文字全片固定，包含转场和片尾，无底板或边框：

```text
AI不能替代人工决策
市场有风险 投资需谨慎
```

## 音频与 QA

- 旁白来源：`docs/video/agomtradepro-workflows-150s-vertical-v2.md` 的12段定稿正文。
- 口播实测约124.66秒；镜头停留和转场留白补足150秒，不拉伸或裁断语音。
- 混音目标：−16.8 LUFS 综合响度、−1.5 dBTP 真峰值；成片 AAC 实测为 {measured_lufs:.1f} LUFS、{measured_true_peak:.1f} dBTP。
- 配音与原创音乐混音临时文件：`.tmp/agom-brand-video-20261028-v2/audio/{mixed_audio.name}`。
- 编码参数：`{FPS}` fps、`{FRAME_COUNT}` 帧；H.264 最多4线程，AAC混流2线程。
- 全片解码和音频测量日志保存在 `.tmp/agom-brand-video-20261028-v2/qa/`。
"""
    readme.write_text(body, encoding="utf-8")


def render_all(threads: int = 4) -> None:
    if len(NARRATION) != 12 or len(BOUNDARIES) != 14:
        raise ValueError("The approved v2 narration or timing table changed; review the renderer mapping first.")
    TEMP_DIR.joinpath("qa").mkdir(parents=True, exist_ok=True)
    log_path = TEMP_DIR / "qa" / "render-v2.log"
    log_path.write_text(
        f"AgomTradePro v2 render\nframes={FRAME_COUNT}\nfps={FPS}\nsize={WIDTH}x{HEIGHT}\nduration={DURATION:.2f}\nvoice={VOICE}\nrate={RATE}\nthreads={threads}\n",
        encoding="utf-8",
    )
    voice_only, mixed_audio, cues, durations = prepare_audio(log_path)
    srt_path = OUTPUT_DIR / "captions.srt"
    cover_path = OUTPUT_DIR / "cover.png"
    video_only = TEMP_DIR / "qa" / "video-only-v2.mp4"
    final_path = OUTPUT_DIR / "agomtradepro-150s-workflows-v2.mp4"
    make_cover(cover_path, cues)
    encode_video_only(video_only, cues, log_path, threads=threads)
    mux_final(video_only, mixed_audio, final_path, log_path)
    measured_lufs, measured_true_peak = final_media_qa(final_path)
    write_readme(final_path, voice_only, mixed_audio, srt_path, cover_path, measured_lufs, measured_true_peak)
    with log_path.open("a", encoding="utf-8") as log:
        log.write("\n## narration segment durations\n")
        log.write("\n".join(f"{index + 1:02d}: {duration:.2f}s" for index, duration in enumerate(durations)))
        log.write(f"\nvoice total: {sum(durations):.2f}s\nfinal: {final_path}\n")
    print(f"Final video: {final_path}")
    print(f"Voice WAV: {voice_only}")
    print(f"Mixed audio WAV: {mixed_audio}")
    print(f"SRT: {srt_path}")
    print(f"Cover PNG: {cover_path}")
    print(f"制作说明: {OUTPUT_DIR / '制作说明.md'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the complete 150-second AgomTradePro v2 vertical video.")
    parser.add_argument("--render", action="store_true", help="Encode the full 150-second H.264/AAC video.")
    parser.add_argument("--threads", type=int, choices=(2, 3, 4), default=4)
    parser.add_argument("--cover-only", action="store_true", help="Write only the cover PNG.")
    parser.add_argument("--sample-frames", action="store_true", help="Render three subtitle-bearing frames for final layout preflight.")
    options = parser.parse_args()
    if options.cover_only:
        cues = _subtitle_cues(tuple(_probe_duration(VOICE_DIR / f"voice-{index:02d}.mp3") for index in range(1, 13)))
        cover = OUTPUT_DIR / "cover.png"
        make_cover(cover, cues)
        print(f"Cover: {cover}")
    elif options.sample_frames:
        durations = tuple(_probe_duration(VOICE_DIR / f"voice-{index:02d}.mp3") for index in range(1, 13))
        cues = _subtitle_cues(durations)
        cue_starts = tuple(cue.start for cue in cues)
        sample_dir = TEMP_DIR / "qa" / "final-renderer-frames"
        sample_dir.mkdir(parents=True, exist_ok=True)
        samples = ((47.5, "research"), (92.0, "risk-recheck"), (118.5, "audit"))
        for timestamp, name in samples:
            path = sample_dir / f"{name}-{timestamp:.1f}s.png"
            render_frame(timestamp, cues, cue_starts).save(path, format="PNG", optimize=True)
            print(f"Final renderer frame: {path}")
        cover = OUTPUT_DIR / "cover.png"
        make_cover(cover, cues)
        print(f"Cover: {cover}")
    elif options.render:
        render_all(threads=options.threads)
    else:
        parser.error("Pass --render to encode the complete video or --cover-only to render just the cover.")


if __name__ == "__main__":
    main()
