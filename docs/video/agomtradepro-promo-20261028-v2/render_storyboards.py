from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Literal, Sequence

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = Path(__file__).resolve().parent
TEMP_DIR = ROOT / ".tmp" / "agom-brand-video-20261028-v2"
PREVIEW_DIR = TEMP_DIR / "preview"
ICON_PATH = ROOT / "docs" / "images" / "brand" / "agomtradepro-icon-v2-pixel-ashare.png"

WIDTH = 1080
HEIGHT = 1920
BG_TOP = (7, 16, 29)
BG_BOTTOM = (11, 27, 42)
PANEL = (16, 31, 49)
PANEL_LIFT = (21, 40, 59)
PAPER = (224, 232, 226)
PAPER_SHADE = (207, 219, 213)
PAPER_INK = (19, 35, 46)
TEXT = (239, 245, 247)
MUTED = (157, 178, 194)
FAINT = (109, 133, 151)
GOLD = (242, 184, 76)
MINT = (88, 224, 190)
AMBER = (224, 160, 67)
A_SHARE_UP = (224, 67, 71)
A_SHARE_DOWN = (46, 175, 122)
EDGE = (65, 91, 111)

Scene = Literal["data", "research", "risk", "review", "ai"]
FONT_CACHE: dict[tuple[int, bool], ImageFont.FreeTypeFont] = {}


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def ease_out(value: float) -> float:
    x = clamp(value)
    return 1.0 - (1.0 - x) ** 3


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (size, bold)
    if key not in FONT_CACHE:
        names = ("msyhbd.ttc", "simhei.ttf", "Dengb.ttf") if bold else ("msyh.ttc", "simsun.ttc", "Deng.ttf")
        for name in names:
            path = Path("C:/Windows/Fonts") / name
            if path.exists():
                FONT_CACHE[key] = ImageFont.truetype(str(path), size=size)
                break
        else:
            raise FileNotFoundError("Chinese font msyh.ttc was not found in C:/Windows/Fonts")
    return FONT_CACHE[key]


def draw_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    size: int,
    color: tuple[int, int, int] = TEXT,
    bold: bool = False,
    anchor: str = "la",
    spacing: int = 8,
    align: str = "left",
) -> None:
    draw.multiline_text(
        xy,
        text,
        font=font(size, bold),
        fill=color,
        anchor=anchor,
        spacing=spacing,
        align=align,
    )


def text_width(text: str, size: int, bold: bool = False) -> int:
    return int(font(size, bold).getlength(text))


def panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: tuple[int, int, int] = PANEL,
    outline: tuple[int, int, int] = EDGE,
    radius: int = 24,
    width: int = 2,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def pill(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    label: str,
    color: tuple[int, int, int],
    dark: bool = True,
    size: int = 20,
) -> None:
    fill = (14, 29, 45) if dark else PAPER_SHADE
    text_color = color if dark else PAPER_INK
    draw.rounded_rectangle(box, radius=(box[3] - box[1]) // 2, fill=fill, outline=color, width=2)
    draw_text(
        draw,
        ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2),
        label,
        size,
        text_color,
        bold=True,
        anchor="mm",
    )


def bullet(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    color: tuple[int, int, int] = TEXT,
    dot_color: tuple[int, int, int] = MINT,
    size: int = 22,
) -> None:
    draw.ellipse((x, y + 12, x + 10, y + 22), fill=dot_color)
    draw_text(draw, (x + 24, y), text, size, color)


def glow_dot(
    image: Image.Image,
    xy: tuple[float, float],
    color: tuple[int, int, int],
    radius: int = 9,
    strength: int = 105,
) -> None:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    x, y = xy
    draw.ellipse((x - radius * 4, y - radius * 4, x + radius * 4, y + radius * 4), fill=(*color, strength))
    layer = layer.filter(ImageFilter.GaussianBlur(radius * 1.6))
    image.alpha_composite(layer)
    ImageDraw.Draw(image).ellipse((x - radius, y - radius, x + radius, y + radius), fill=(*color, 255))


def _point_on_path(points: Sequence[tuple[float, float]], progress: float) -> tuple[float, float]:
    lengths = [math.dist(points[i], points[i + 1]) for i in range(len(points) - 1)]
    total = max(1.0, sum(lengths))
    remaining = clamp(progress) * total
    for index, segment_length in enumerate(lengths):
        if remaining <= segment_length:
            fraction = remaining / max(1.0, segment_length)
            x1, y1 = points[index]
            x2, y2 = points[index + 1]
            return (x1 + (x2 - x1) * fraction, y1 + (y2 - y1) * fraction)
        remaining -= segment_length
    return points[-1]


def _path_prefix(points: Sequence[tuple[float, float]], progress: float) -> list[tuple[float, float]]:
    if len(points) < 2:
        return list(points)
    current = _point_on_path(points, progress)
    total = sum(math.dist(points[i], points[i + 1]) for i in range(len(points) - 1))
    cutoff = clamp(progress) * total
    result = [points[0]]
    walked = 0.0
    for index in range(len(points) - 1):
        segment_length = math.dist(points[index], points[index + 1])
        if walked + segment_length >= cutoff:
            if math.dist(result[-1], current) > 0.5:
                result.append(current)
            break
        result.append(points[index + 1])
        walked += segment_length
    return result


def connector(
    image: Image.Image,
    points: Sequence[tuple[float, float]],
    progress: float,
    color: tuple[int, int, int] = MINT,
    width: int = 4,
    arrow: bool = True,
    dashed: bool = False,
) -> None:
    if len(points) < 2:
        return
    draw = ImageDraw.Draw(image, "RGBA")
    if dashed:
        for start, end in zip(points, points[1:]):
            distance = math.dist(start, end)
            pieces = max(1, int(distance / 18))
            for part in range(0, pieces, 2):
                a = part / pieces
                b = min(1.0, (part + 1) / pieces)
                p1 = (start[0] + (end[0] - start[0]) * a, start[1] + (end[1] - start[1]) * a)
                p2 = (start[0] + (end[0] - start[0]) * b, start[1] + (end[1] - start[1]) * b)
                draw.line((p1, p2), fill=(71, 102, 122, 85), width=max(2, width - 1))
    else:
        draw.line(points, fill=(63, 87, 105, 110), width=max(2, width - 1), joint="curve")

    visible = _path_prefix(points, progress)
    if len(visible) > 1:
        glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        glow_draw.line(visible, fill=(*color, 92), width=width * 4, joint="curve")
        image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(width * 1.4)))
        draw = ImageDraw.Draw(image, "RGBA")
        draw.line(visible, fill=(*color, 244), width=width, joint="curve")

    if arrow and progress >= 0.96:
        tip_x, tip_y = points[-1]
        prev_x, prev_y = points[-2]
        angle = math.atan2(tip_y - prev_y, tip_x - prev_x)
        wing = 13
        left = (tip_x - wing * math.cos(angle - 0.54), tip_y - wing * math.sin(angle - 0.54))
        right = (tip_x - wing * math.cos(angle + 0.54), tip_y - wing * math.sin(angle + 0.54))
        ImageDraw.Draw(image, "RGBA").polygon(((tip_x, tip_y), left, right), fill=(*color, 255))


def make_background(time_value: float) -> Image.Image:
    image = Image.new("RGBA", (WIDTH, HEIGHT), BG_TOP)
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        amount = y / (HEIGHT - 1)
        color = tuple(round(a * (1 - amount) + b * amount) for a, b in zip(BG_TOP, BG_BOTTOM))
        draw.line((0, y, WIDTH, y), fill=(*color, 255))

    glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    offset = int(math.sin(time_value * math.tau) * 22)
    glow_draw.ellipse((610 + offset, 260, 1330 + offset, 1040), fill=(34, 136, 128, 34))
    glow_draw.ellipse((-430, 970 - offset, 460, 1880 - offset), fill=(181, 124, 48, 23))
    image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(150)))

    grid = Image.new("RGBA", image.size, (0, 0, 0, 0))
    grid_draw = ImageDraw.Draw(grid)
    drift = int(time_value * 8) % 84
    for x in range(-84 + drift, WIDTH + 84, 84):
        grid_draw.line((x, 0, x, HEIGHT), fill=(142, 177, 200, 12), width=1)
    for y in range(-84 + drift, HEIGHT + 84, 84):
        grid_draw.line((0, y, WIDTH, y), fill=(142, 177, 200, 10), width=1)
    image.alpha_composite(grid)

    for index in range(17):
        x = 45 + (index * 173) % (WIDTH - 90)
        y = 350 + (index * 229) % 1300
        x += math.sin(time_value * 1.4 + index * 0.71) * 13
        y += math.cos(time_value + index * 0.49) * 11
        alpha = 35 + int((math.sin(time_value * 2.3 + index) + 1) * 14)
        color = MINT if index % 4 == 0 else GOLD
        ImageDraw.Draw(image).ellipse((x - 2, y - 2, x + 2, y + 2), fill=(*color, alpha))
    return image


CHAPTERS: dict[Scene, tuple[int, str, str, str]] = {
    "data": (1, "数据工作流", "先确认来源，再确认用途", "行情 / 宏观指标 / 财务材料 → 可核对的研究材料"),
    "research": (2, "研究工作流", "从宏观线索，到可检验的判断", "环境判断 → 标的研究 → 证据案卷 → 证伪回流"),
    "risk": (3, "风控工作流", "每一道约束，都有明确的下一步", "数据闸门 → 规则检查 → 阻断说明 / 人工确认"),
    "review": (4, "验证与复盘", "从历史验证，走到决策留痕", "历史回测 → 模拟交易 → 持仓跟踪 → 审计复盘"),
    "ai": (4, "AI 协作贯穿流程", "AI 参与工作流，确认边界仍清晰", "查数据 → 整理分析 → 提出方案 → 人工复核"),
}


def draw_header(image: Image.Image, scene: Scene, local: float) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    number, chapter, title, subtitle = CHAPTERS[scene]
    icon = Image.open(ICON_PATH).convert("RGBA").resize((78, 78), Image.Resampling.NEAREST)
    image.alpha_composite(icon, (48, 39))
    draw_text(draw, (144, 47), "AgomTradePro", 32, TEXT, bold=True)
    draw_text(draw, (146, 92), "个人工作台 · 研究与风控流程", 20, MUTED)

    draw_text(draw, (1015, 55), f"{number:02d} / 04", 21, GOLD if number < 3 else MINT, bold=True, anchor="ra")
    pill(draw, (841, 97, 1017, 143), "流程示意", MINT, size=19)

    segment_start = 72
    segment_gap = 8
    segment_width = 229
    for index in range(4):
        x1 = segment_start + index * (segment_width + segment_gap)
        x2 = x1 + segment_width
        draw.rounded_rectangle((x1, 158, x2, 165), radius=4, fill=(48, 67, 82, 180))
        fraction = 1.0 if index < number - 1 else (clamp(local) if index == number - 1 else 0.0)
        if fraction > 0:
            active_color = GOLD if index in (0, 1) else MINT
            draw.rounded_rectangle((x1, 158, x1 + max(5, int(segment_width * fraction)), 165), radius=4, fill=active_color)

    draw_text(draw, (540, 226), title, 49, TEXT, bold=True, anchor="mm")
    draw.rounded_rectangle((430, 271, 650, 277), radius=3, fill=GOLD if number in (1, 2) else MINT)
    draw_text(draw, (540, 315), subtitle, 22, MUTED, anchor="mm")


def draw_disclaimer(image: Image.Image) -> None:
    draw = ImageDraw.Draw(image)
    font_disclaimer = font(26)
    for y, line in ((1814, "AI不能替代人工决策"), (1855, "市场有风险 投资需谨慎")):
        width = draw.textbbox((0, 0), line, font=font_disclaimer)[2]
        draw.text((WIDTH - 26 - width, y), line, font=font_disclaimer, fill=(226, 233, 238))


def transform_content(content: Image.Image, zoom: float, pan_y: float) -> Image.Image:
    crop = content.crop((54, 340, 1026, 1744))
    target_width = int(crop.width * zoom)
    target_height = int(crop.height * zoom)
    scaled = crop.resize((target_width, target_height), Image.Resampling.BICUBIC)
    result = Image.new("RGBA", content.size, (0, 0, 0, 0))
    left = int(54 - (target_width - crop.width) / 2)
    top = int(340 - (target_height - crop.height) / 2 + pan_y)
    result.alpha_composite(scaled, (left, top))
    return result


def _number_badge(
    draw: ImageDraw.ImageDraw,
    center: tuple[int, int],
    number: str,
    color: tuple[int, int, int],
    dark: bool = True,
) -> None:
    cx, cy = center
    fill = (12, 26, 41) if dark else PAPER
    draw.ellipse((cx - 25, cy - 25, cx + 25, cy + 25), fill=fill, outline=color, width=2)
    draw_text(draw, center, number, 17, color, bold=True, anchor="mm")


def draw_data(image: Image.Image, layer: Image.Image, local: float) -> None:
    d = ImageDraw.Draw(layer, "RGBA")
    # Three source rails merge into a single, auditable dossier.
    source_boxes = [
        (82, 365, 660, 484, "行情资料", "来源 · 观测时间"),
        (82, 510, 660, 629, "宏观指标", "单位 · 来源 · 观测时间"),
        (82, 655, 660, 774, "财务材料", "报告期 · 来源 · 可用范围"),
    ]
    for index, (x1, y1, x2, y2, title, detail) in enumerate(source_boxes):
        panel(d, (x1, y1, x2, y2), fill=PANEL_LIFT, outline=(66, 99, 117))
        _number_badge(d, (x1 + 48, (y1 + y2) // 2), f"{index + 1:02d}", GOLD if index == 0 else MINT)
        draw_text(d, (x1 + 94, y1 + 25), title, 25, TEXT, bold=True)
        draw_text(d, (x1 + 94, y1 + 69), detail, 20, MUTED)
        connector(image, ((x2, (y1 + y2) // 2), (746, (y1 + y2) // 2), (746, 832)), ease_out(local * 1.35), MINT, 3, arrow=False)

    # Dossier is the merge target; fields are labels rather than fabricated observations.
    panel(d, (746, 365, 1003, 774), fill=PAPER, outline=(198, 213, 205), radius=20)
    draw_text(d, (777, 392), "研究材料", 27, PAPER_INK, bold=True)
    draw_text(d, (777, 442), "清单", 27, PAPER_INK, bold=True)
    d.line((777, 496, 972, 496), fill=(146, 166, 158), width=2)
    for index, label in enumerate(("来源可查", "时间可核", "范围明确")):
        y = 529 + index * 67
        d.ellipse((778, y + 5, 792, y + 19), fill=MINT)
        draw_text(d, (807, y), label, 20, PAPER_INK)
    d.line((777, 737, 970, 737), fill=(151, 169, 161), width=2)
    draw_text(d, (777, 750), "流程示意", 17, (70, 93, 91), bold=True)

    # Purpose gate: valid material advances, unusable material keeps its reason.
    connector(image, ((874, 774), (874, 843), (540, 843), (540, 894)), ease_out(local * 1.4), GOLD, 4)
    panel(d, (83, 900, 1000, 1086), fill=(17, 34, 51), outline=(89, 111, 127), radius=22)
    draw_text(d, (115, 925), "用途检查", 23, GOLD, bold=True)
    draw_text(d, (115, 972), "材料是否满足研究所需的来源、时点与可用范围？", 23, TEXT)
    pill(d, (733, 932, 960, 982), "不自动刷新", GOLD, size=19)

    connector(image, ((539, 1086), (539, 1144), (280, 1144), (280, 1191)), ease_out(local * 1.6), MINT, 4)
    connector(image, ((539, 1086), (539, 1144), (794, 1144), (794, 1191)), ease_out(local * 1.6), AMBER, 4)
    panel(d, (83, 1200, 490, 1540), fill=(17, 49, 51), outline=MINT, radius=24)
    _number_badge(d, (132, 1251), "✓", MINT)
    draw_text(d, (174, 1229), "材料可用", 26, TEXT, bold=True)
    draw_text(d, (116, 1305), "保留来源与观测时间", 21, (195, 221, 216))
    draw_text(d, (116, 1351), "进入研究案卷", 21, TEXT)
    connector(image, ((132, 1435), (402, 1435)), ease_out(local * 1.4), MINT, 4)
    draw_text(d, (116, 1471), "下一步：研究判断", 18, MINT, bold=True)

    panel(d, (555, 1200, 1000, 1540), fill=(49, 38, 29), outline=AMBER, radius=24)
    _number_badge(d, (604, 1251), "!", AMBER)
    draw_text(d, (646, 1229), "阻断 · 不可用于决策", 24, TEXT, bold=True)
    draw_text(d, (590, 1305), "不可用于决策：观测时间不满足要求", 19, (240, 210, 163))
    draw_text(d, (590, 1351), "保留来源与限制说明", 20, TEXT)
    draw_text(d, (590, 1434), "不会动画刷新成新数据", 18, AMBER, bold=True)
    d.line((590, 1485, 962, 1485), fill=(160, 114, 58), width=2)
    draw_text(d, (590, 1500), "示例状态 · 流程示意", 17, (220, 190, 143))


def draw_research(image: Image.Image, layer: Image.Image, local: float) -> None:
    d = ImageDraw.Draw(layer, "RGBA")
    # Top-down research path from environment to asset.
    panel(d, (78, 362, 480, 548), fill=PANEL, outline=(129, 104, 64), radius=22)
    _number_badge(d, (124, 408), "01", GOLD)
    draw_text(d, (163, 389), "环境观察", 25, TEXT, bold=True)
    draw_text(d, (112, 456), "增长  ·  通胀  ·  政策", 22, MUTED)
    draw_text(d, (112, 501), "先看背景，再进入标的研究", 18, GOLD)

    panel(d, (610, 362, 1002, 548), fill=PANEL_LIFT, outline=(74, 120, 119), radius=22)
    _number_badge(d, (657, 408), "02", MINT)
    draw_text(d, (696, 389), "研究对象", 25, TEXT, bold=True)
    draw_text(d, (644, 456), "行业  →  股票 / 基金", 22, MUTED)
    draw_text(d, (644, 501), "入口：行业观察 / 估值研究 / 因子分析", 16, MINT)
    connector(image, ((480, 455), (535, 455), (610, 455)), ease_out(local * 1.2), GOLD, 5)
    glow_dot(image, _point_on_path(((480, 455), (535, 455), (610, 455)), (local * 0.72) % 1.0), GOLD, radius=7, strength=75)

    connector(image, ((805, 548), (805, 610), (540, 610), (540, 653)), ease_out(local * 1.4), MINT, 4)
    # The dossier is a single light document with separate evidence rows.
    panel(d, (78, 664, 1002, 1085), fill=PAPER, outline=(198, 213, 205), radius=21)
    draw_text(d, (112, 692), "研究案卷", 28, PAPER_INK, bold=True)
    draw_text(d, (263, 700), "来源、时点与可用范围逐项核对", 20, (73, 94, 92))
    pill(d, (794, 683, 965, 730), "证据清单", MINT, dark=False, size=18)
    d.line((112, 752, 966, 752), fill=(161, 178, 171), width=2)
    dossier_rows = (
        ("宏观指标", "来源 · 单位 · 源观测时间", GOLD),
        ("政策材料", "材料来源 · 发布日期 · 对应观点", MINT),
        ("标的资料", "来源 · 报告期 · 可用范围", GOLD),
    )
    for index, (title, detail, tint) in enumerate(dossier_rows):
        y = 774 + index * 96
        d.rounded_rectangle((111, y + 1, 159, y + 47), radius=12, fill=PAPER_SHADE)
        draw_text(d, (135, y + 24), f"0{index + 1}", 17, PAPER_INK, bold=True, anchor="mm")
        draw_text(d, (182, y), title, 22, PAPER_INK, bold=True)
        draw_text(d, (182, y + 40), detail, 18, (80, 101, 98))
        d.ellipse((928, y + 13, 945, y + 30), fill=tint)
        d.line((112, y + 75, 966, y + 75), fill=(173, 188, 182), width=1)

    connector(image, ((540, 1085), (540, 1124)), ease_out(local * 1.7), GOLD, 4)
    panel(d, (78, 1135, 1002, 1640), fill=(14, 28, 45), outline=(99, 119, 133), radius=25)
    draw_text(d, (111, 1167), "研究信号", 28, TEXT, bold=True)
    pill(d, (774, 1156, 966, 1205), "流程示意", GOLD, size=18)
    draw_text(d, (112, 1232), "研究理由", 24, MINT, bold=True)
    bullet(d, 116, 1282, "环境如何影响研究对象", color=TEXT, dot_color=MINT, size=20)
    bullet(d, 116, 1327, "哪些证据支撑当前判断", color=TEXT, dot_color=MINT, size=20)
    d.line((536, 1230, 536, 1425), fill=(61, 81, 98), width=2)
    draw_text(d, (575, 1232), "证伪条件", 24, GOLD, bold=True)
    bullet(d, 578, 1282, "新证据出现 / 假设失效", color=TEXT, dot_color=GOLD, size=20)
    bullet(d, 578, 1327, "触发后：返回重新评估", color=TEXT, dot_color=GOLD, size=20)
    d.rounded_rectangle((112, 1405, 966, 1474), radius=16, fill=(21, 42, 58), outline=(79, 107, 123), width=1)
    draw_text(d, (539, 1439), "结论有依据，也有失效边界", 21, TEXT, bold=True, anchor="mm")
    # A falsification condition sends the idea back through the dossier, not to a buy action.
    loop_points = ((846, 1474), (846, 1589), (986, 1589), (986, 750), (963, 750))
    connector(image, loop_points, ease_out(local * 1.65), GOLD, 4)
    pill(d, (600, 1531, 905, 1590), "条件触发 → 重新评估", GOLD, size=18)
    glow_dot(image, _point_on_path(loop_points, (local * 0.82) % 1.0), GOLD, radius=7, strength=75)


def draw_gate_checklist(draw: ImageDraw.ImageDraw) -> None:
    draw_text(draw, (112, 937), "账户与策略约束", 24, TEXT, bold=True)
    draw_text(draw, (965, 943), "按已配置规则逐项核对", 18, MUTED, anchor="ra")
    rows = (
        ("总仓位", "组合整体边界", GOLD),
        ("单一标的集中度", "拟议操作前置检查", AMBER),
        ("现金底线", "账户可用现金约束", MINT),
        ("风险限制", "命中硬性排除即停止", AMBER),
    )
    for index, (title, detail, tint) in enumerate(rows):
        y = 986 + index * 55
        draw.ellipse((113, y + 7, 128, y + 22), fill=tint)
        draw_text(draw, (151, y), title, 20, TEXT, bold=True)
        draw_text(draw, (485, y), detail, 19, MUTED)
        draw.line((112, y + 40, 965, y + 40), fill=(54, 75, 91), width=1)


def draw_risk(image: Image.Image, layer: Image.Image, local: float) -> None:
    d = ImageDraw.Draw(layer, "RGBA")
    # The input gate makes data quality a first-class blocking branch.
    panel(d, (78, 357, 1002, 552), fill=PANEL, outline=(75, 101, 119), radius=22)
    draw_text(d, (111, 381), "输入 · 数据可用性", 23, GOLD, bold=True)
    input_fields = (("数据来源", 113), ("观测时间", 388), ("时效 / 可靠性", 663))
    for label, x in input_fields:
        d.rounded_rectangle((x, 431, x + 239, 502), radius=14, fill=(22, 42, 59), outline=(62, 87, 105), width=1)
        draw_text(d, (x + 19, 466), label, 18, TEXT, anchor="lm")
        d.ellipse((x + 205, 456, x + 220, 471), fill=MINT)
    pill(d, (805, 376, 969, 419), "先核验", MINT, size=17)
    connector(image, ((539, 552), (539, 594)), ease_out(local * 1.25), MINT, 4)
    # Data-use decision node and its two explicit outcomes.
    d.polygon(((539, 582), (575, 618), (539, 654), (503, 618)), fill=(17, 36, 51), outline=MINT)
    draw_text(d, (539, 618), "可用?", 16, TEXT, bold=True, anchor="mm")
    connector(image, ((503, 618), (290, 618), (290, 675)), ease_out(local * 1.5), MINT, 4)
    connector(image, ((575, 618), (790, 618), (790, 675)), ease_out(local * 1.5), AMBER, 4)

    panel(d, (78, 683, 491, 826), fill=(17, 49, 51), outline=MINT, radius=20)
    draw_text(d, (110, 703), "材料可用", 22, TEXT, bold=True)
    draw_text(d, (110, 748), "继续进入风险检查", 18, (188, 220, 211))
    pill(d, (338, 700, 466, 744), "通过", MINT, size=17)

    panel(d, (575, 683, 1002, 826), fill=(48, 38, 29), outline=AMBER, radius=20)
    draw_text(d, (604, 703), "阻断 01 · 数据条件", 21, TEXT, bold=True)
    draw_text(d, (604, 747), "时间缺失 / 时效不足", 18, (238, 205, 155))
    pill(d, (835, 770, 973, 810), "停止使用", AMBER, size=16)

    connector(image, ((285, 826), (285, 868), (539, 868), (539, 895)), ease_out(local * 1.75), MINT, 4)
    panel(d, (78, 902, 1002, 1233), fill=(13, 28, 44), outline=(76, 103, 120), radius=23)
    draw_text(d, (112, 925), "拟议买入 · 仓位与风险检查", 23, TEXT, bold=True)
    pill(d, (695, 915, 967, 958), "示例账户 / 示例配置", GOLD, size=16)
    rows = (
        ("总仓位", "按策略规则核对", GOLD),
        ("单一标的集中度", "对照示例上限", AMBER),
        ("现金底线", "检查账户约束", MINT),
        ("风险限制", "命中排除条件即停止", AMBER),
    )
    for index, (title, detail, tint) in enumerate(rows):
        y = 982 + index * 53
        d.ellipse((114, y + 8, 128, y + 22), fill=tint)
        draw_text(d, (151, y), title, 20, TEXT, bold=True)
        draw_text(d, (478, y), detail, 19, MUTED)
        d.line((112, y + 39, 967, y + 39), fill=(54, 75, 91), width=1)

    connector(image, ((539, 1233), (539, 1252)), ease_out(local * 1.85), AMBER, 4)
    panel(d, (78, 1260, 1002, 1434), fill=(48, 38, 29), outline=AMBER, radius=21)
    draw_text(d, (111, 1279), "首次检查 · 阻断", 22, TEXT, bold=True)
    pill(d, (731, 1271, 969, 1314), "示例账户 / 配置", AMBER, size=16)
    draw_text(d, (112, 1340), "18% 当前  +  4% 拟增加  =  22%", 27, TEXT, bold=True)
    draw_text(d, (963, 1340), "22%  >  上限 20%", 19, (243, 203, 143), anchor="ra")
    draw_text(d, (112, 1397), "阻断原因：单一标的集中度超限", 18, (242, 187, 106), bold=True)

    connector(image, ((539, 1434), (539, 1453)), ease_out(local * 1.95), MINT, 4)
    panel(d, (78, 1463, 1002, 1664), fill=(16, 45, 48), outline=MINT, radius=21)
    draw_text(d, (111, 1480), "调整后复核 · 待人工确认", 22, TEXT, bold=True)
    pill(d, (731, 1472, 969, 1515), "示例账户 / 配置", MINT, size=16)
    draw_text(d, (112, 1540), "18% 当前  +  1% 拟增加  =  19%", 27, TEXT, bold=True)
    draw_text(d, (963, 1540), "19%  ≤  上限 20%", 19, (172, 230, 213), anchor="ra")
    draw_text(d, (112, 1599), "其余条件满足 → 进入相应审批流程", 19, MINT, bold=True)


def draw_candles(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], time_value: float) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=15, fill=(10, 23, 38), outline=(61, 82, 101), width=1)
    draw_text(draw, (x1 + 16, y1 + 12), "历史序列 · 示意", 17, MUTED)
    baseline = y2 - 25
    draw.line((x1 + 18, baseline, x2 - 14, baseline), fill=(65, 88, 105), width=1)
    heights = (35, 57, 49, 74, 66, 48, 82, 69, 96, 78, 104, 88)
    for index, base_height in enumerate(heights):
        x = x1 + 34 + index * 19
        wobble = math.sin(time_value * 2 + index * 0.65) * 3
        h = base_height + int(wobble)
        color = A_SHARE_UP if index % 2 == 0 else A_SHARE_DOWN
        open_y = baseline - h + (9 if index % 2 == 0 else -8)
        close_y = baseline - h + (-8 if index % 2 == 0 else 9)
        low_y = max(y1 + 42, min(open_y, close_y) - 10 - index % 3 * 3)
        high_y = max(open_y, close_y) + 12 + index % 4 * 2
        draw.line((x, low_y, x, high_y), fill=color, width=2)
        draw.rectangle((x - 6, min(open_y, close_y), x + 6, max(open_y, close_y)), fill=color)


def draw_review(image: Image.Image, layer: Image.Image, local: float) -> None:
    d = ImageDraw.Draw(layer, "RGBA")
    # Distinct artifacts follow a single vertical audit rail.
    rail_x = 117
    node_y = (399, 723, 1033, 1347)
    for start, end in zip(node_y, node_y[1:]):
        connector(image, ((rail_x, start + 27), (rail_x, end - 27)), ease_out(local * 1.7), GOLD, 3, arrow=False, dashed=True)
    for index, cy in enumerate(node_y, start=1):
        _number_badge(d, (rail_x, cy), f"0{index}", GOLD if index == 1 else MINT)

    # Historical backtest: neutral schematic candles, no returns or performance figures.
    panel(d, (176, 355, 1003, 648), fill=PANEL, outline=(130, 103, 60), radius=22)
    draw_text(d, (210, 378), "历史回测", 24, TEXT, bold=True)
    pill(d, (801, 369, 968, 412), "历史数据", GOLD, size=17)
    draw_candles(d, (207, 427, 479, 616), local)
    draw_text(d, (520, 444), "验证研究想法", 21, TEXT, bold=True)
    bullet(d, 520, 491, "历史区间与规则条件", color=MUTED, dot_color=GOLD, size=19)
    bullet(d, 520, 534, "记录观察结果与限制", color=MUTED, dot_color=MINT, size=19)
    draw_text(d, (520, 587), "不代表未来表现", 17, GOLD)

    # Simulation module is a ledger, not a fake live trading screen.
    panel(d, (234, 681, 1003, 967), fill=(14, 34, 49), outline=(70, 128, 124), radius=22)
    draw_text(d, (270, 704), "模拟交易", 24, TEXT, bold=True)
    pill(d, (807, 695, 968, 738), "非实盘", MINT, size=17)
    draw_text(d, (270, 756), "过程记录", 18, MUTED)
    ledger_rows = (
        ("拟议操作", "模拟环境"),
        ("规则检查", "记录状态"),
        ("模拟回执", "留存结果"),
    )
    for index, (left, right) in enumerate(ledger_rows):
        y = 793 + index * 50
        d.rounded_rectangle((270, y, 958, y + 39), radius=9, fill=(19, 43, 58), outline=(47, 75, 91), width=1)
        draw_text(d, (290, y + 19), left, 18, TEXT, anchor="lm")
        draw_text(d, (931, y + 19), right, 17, MINT if index == 2 else MUTED, anchor="rm")

    # Portfolio tracking exposes change and alerts without sample account numbers.
    panel(d, (176, 991, 934, 1271), fill=PANEL_LIFT, outline=(73, 117, 112), radius=22)
    draw_text(d, (210, 1015), "持仓跟踪", 24, TEXT, bold=True)
    pill(d, (712, 1006, 897, 1049), "变化留痕", MINT, size=17)
    track_rows = (("持仓变化", GOLD), ("风险状态", AMBER), ("研究假设", MINT))
    for index, (label, color) in enumerate(track_rows):
        y = 1080 + index * 51
        draw_text(d, (216, y), label, 18, MUTED)
        d.rounded_rectangle((386, y + 2, 868, y + 22), radius=8, fill=(29, 48, 62))
        width = (256, 388, 328)[index]
        d.rounded_rectangle((386, y + 2, 386 + width, y + 22), radius=8, fill=(*color, 196))
        draw_text(d, (888, y + 11), "状态", 15, color, anchor="rm")

    # Audit receipt is a pale document with backward links to evidence.
    panel(d, (234, 1305, 1003, 1674), fill=PAPER, outline=(199, 213, 205), radius=22)
    draw_text(d, (270, 1330), "决策审计 · 复盘案卷", 25, PAPER_INK, bold=True)
    pill(d, (802, 1320, 968, 1364), "流程示意", MINT, dark=False, size=17)
    d.line((270, 1381, 968, 1381), fill=(156, 174, 166), width=2)
    receipt_rows = (
        ("01", "当时证据", "来源与时间"),
        ("02", "研究判断", "理由与证伪条件"),
        ("03", "风险结果", "通过 / 阻断原因"),
        ("04", "处理记录", "审批与后续复盘"),
    )
    for index, (num, label, detail) in enumerate(receipt_rows):
        y = 1398 + index * 57
        _number_badge(d, (294, y + 20), num, (75, 111, 103), dark=False)
        draw_text(d, (338, y + 6), label, 18, PAPER_INK, bold=True)
        draw_text(d, (568, y + 6), detail, 17, (76, 97, 91))
        d.line((338, y + 42, 968, y + 42), fill=(179, 192, 184), width=1)
    draw_text(d, (270, 1641), "风险日报 · 持仓日报 · 历史记录  →  下一轮研究", 16, (45, 91, 84), bold=True)

    # Loop marker on the right edge leads back to the next research pass.
    loop_points = ((1008, 1550), (1031, 1550), (1031, 340), (361, 340))
    connector(image, loop_points, ease_out(local * 1.3), MINT, 3, arrow=True, dashed=True)


def draw_ai(image: Image.Image, layer: Image.Image, local: float) -> None:
    d = ImageDraw.Draw(layer, "RGBA")
    # A support rail crosses the four workflows but stops at a human review gate.
    workflow_nodes = ((125, 403, "数据"), (125, 676, "研究"), (125, 949, "风控"), (125, 1222, "复盘"))
    for index, (x, y, label) in enumerate(workflow_nodes):
        panel(d, (80, y - 44, 277, y + 44), fill=PANEL_LIFT, outline=(62, 95, 111), radius=18)
        draw_text(d, (116, y), label, 22, TEXT, bold=True, anchor="lm")
        d.ellipse((235, y - 8, 251, y + 8), fill=MINT if index < 2 else GOLD)

    # Assistant mark and activity thread.
    panel(d, (373, 390, 1002, 1296), fill=(13, 28, 44), outline=(69, 104, 119), radius=26)
    icon = Image.open(ICON_PATH).convert("RGBA").resize((94, 94), Image.Resampling.NEAREST)
    image.alpha_composite(icon, (416, 423))
    draw_text(d, (532, 443), "AI 辅助轨", 26, TEXT, bold=True)
    draw_text(d, (532, 485), "查数 · 分析 · 方案整理", 19, MUTED)
    d.line((420, 544, 955, 544), fill=(61, 84, 101), width=2)
    activities = (
        ("查数据", "显示来源与观测时间"),
        ("整理分析", "把证据与判断关联"),
        ("提出方案", "形成待审阅内容"),
    )
    for index, (title, detail) in enumerate(activities):
        y = 582 + index * 189
        _number_badge(d, (455, y + 26), f"0{index + 1}", MINT if index < 2 else GOLD)
        draw_text(d, (500, y + 5), title, 24, TEXT, bold=True)
        draw_text(d, (500, y + 51), detail, 19, MUTED)
        if index < 2:
            connector(image, ((455, y + 54), (455, y + 156)), ease_out(local * 1.4), MINT, 3, arrow=False)
    # Cross-links from AI support to each of the four chapters.
    for index, (_, y, _) in enumerate(workflow_nodes):
        color = MINT if index < 2 else GOLD
        connector(image, ((277, y), (326, y), (373, y)), ease_out(local * 1.4), color, 3, arrow=False, dashed=True)

    connector(image, ((688, 1296), (688, 1360)), ease_out(local * 1.6), GOLD, 4)
    panel(d, (205, 1371, 1002, 1660), fill=(17, 38, 52), outline=GOLD, radius=24)
    draw_text(d, (244, 1400), "人工确认边界", 25, TEXT, bold=True)
    draw_text(d, (244, 1451), "重要操作先审阅，再按权限与流程继续", 20, MUTED)
    pill(d, (244, 1520, 560, 1572), "人工确认后继续", MINT, size=18)
    pill(d, (627, 1520, 955, 1572), "退回修改 / 保持阻断", AMBER, size=18)
    draw_text(d, (244, 1610), "重要操作保留审计记录 · 流程示意", 17, GOLD)


DRAWERS = {
    "data": draw_data,
    "research": draw_research,
    "risk": draw_risk,
    "review": draw_review,
    "ai": draw_ai,
}


def render_frame(scene: Scene, local: float = 0.78, camera: bool = True) -> Image.Image:
    local = clamp(local)
    image = make_background(local)
    draw_header(image, scene, local)
    content = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    DRAWERS[scene](image, content, local)

    if camera:
        focus = 1.0 + 0.035 * ease_out(local)
        pan_y = math.sin(local * math.pi) * -7
        image.alpha_composite(transform_content(content, focus, pan_y))
    else:
        image.alpha_composite(content)
    draw_disclaimer(image)
    return image.convert("RGB")


PREVIEW_SCENES: tuple[tuple[Scene, str, float], ...] = (
    ("research", "research-evidence-chain.png", 0.77),
    ("risk", "risk-gate-branches.png", 0.81),
    ("review", "review-audit-receipt.png", 0.76),
)


def write_previews(output_dir: Path = PREVIEW_DIR) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for scene, filename, local in PREVIEW_SCENES:
        output_path = output_dir / filename
        render_frame(scene, local=local).save(output_path, format="PNG", optimize=True)
        written.append(output_path)
        print(f"Preview image: {output_path}")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Render AgomTradePro v2 storyboard previews.")
    parser.add_argument("--scene", choices=tuple(DRAWERS), help="Render one scene instead of the three review previews.")
    parser.add_argument("--time", type=float, default=0.78, help="Normalized 0..1 animation position for --scene.")
    parser.add_argument("--output", type=Path, help="Optional output PNG path when --scene is set.")
    arguments = parser.parse_args()
    if arguments.scene:
        output_path = arguments.output or (PREVIEW_DIR / f"{arguments.scene}-preview.png")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        render_frame(arguments.scene, local=arguments.time).save(output_path, format="PNG", optimize=True)
        print(f"Preview image: {output_path}")
    else:
        write_previews()


if __name__ == "__main__":
    main()
