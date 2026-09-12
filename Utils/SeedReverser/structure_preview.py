# -*- coding: utf-8 -*-
"""SeedReverser 结构锚点示意图渲染（Wiki 渲染图 + 真实方块纹理俯视图）。

布局（用户定稿）：
- 顶部：结构名 + 包围盒尺寸（W×D×H）与 Y 范围
- 左：Minecraft Wiki 信息框等轴测渲染图
  （assets/SeedReverser/previews/<key>.png）
- 右：俯视图（上=北、左=西），每个非空格按最高层方块贴真实纹理
  （assets/SeedReverser/textures/block/<方块名>.png，自客户端 jar 提取）；
  纹理缺失回退 BLOCK_COLORS 色块
- 锚点：俯视图左上角 (0,0) = 结构包围盒西北角 = cubiomes 生成锚点，
  红框 + 描边文字「锚点(0,0)」
- 无渲染图的蓝图（如 ocean_ruin warm/cold）：俯视图占满整幅
- 拼装结构（无整体蓝图）：有渲染图则铺满展示；否则虚线外框 +
  「内部布局随机拼装」示意

数据来源 Utils.SeedReverser.structure_blueprints（Wiki layered blueprint
字符画投影），网格北朝上、西朝左，与游戏坐标一致。
"""
import os

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QPainter, QPainterPath,
                           QPalette, QPen, QPixmap)
from PySide6.QtWidgets import QApplication

from Utils.SeedReverser import structure_blueprints as sb

# ---------------------------------------------------------------------------
# 资产目录：Utils/SeedReverser/ → 项目根 → assets/SeedReverser/
# ---------------------------------------------------------------------------
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
PREVIEW_DIR = os.path.join(_ROOT, "assets", "SeedReverser", "previews")
TEX_DIR = os.path.join(_ROOT, "assets", "SeedReverser", "textures", "block")

# 主题无关的强调色（红），中性色取应用主题 WindowText
_ANCHOR = QColor("#E5484D")          # 锚点标记红
_ANCHOR_OUTLINE = QColor("#1B1E22")  # 锚点文字描边（深浅底均可辨）

# 渲染图缓存（单条）：原图解码开销高，切换结构时只保留当前一份
_PREV_CACHE: dict = {"key": None, "pm": None}
# 渲染图缩放缓存（单条）：避免窗口拖拽 resize 时反复平滑缩放大图
_PREV_SCALED: dict = {"key": None, "w": 0, "h": 0, "pm": None}
# 方块纹理缓存（16x16 小图，可全量缓存；缺失项也缓存 None 避免重复探测）
_TEX_CACHE: dict = {}

# 工作副本最大边长：原图超过时先一次性降到该尺寸再参与每次缩放
_PREV_WORK_MAX = 1024


def _theme_color(alpha: int = 255) -> QColor:
    """应用主题文字色（无应用实例时回退中性灰）。"""
    app = QApplication.instance()
    if app is None:
        return QColor(200, 205, 210, alpha)
    c = app.palette().color(QPalette.ColorRole.WindowText)
    c.setAlpha(alpha)
    return c


def _norm_block(name: str) -> str:
    """Wiki 方块名 -> 纹理文件键（与提取探针归一化规则一致）。"""
    s = name.strip().lower()
    if s.startswith("entitysprite:"):
        s = s[len("entitysprite:"):]
    if "-rot" in s:                      # 去 -rotNNN 旋转后缀
        head, _, tail = s.rpartition("-rot")
        if tail.isdigit():
            s = head
    return s


def _block_color(bp: dict, ch: str) -> QColor:
    """纹理缺失时的回退色（BLOCK_COLORS 调色板）。"""
    return QColor(sb.BLOCK_COLORS.get(
        _norm_block(bp["palette"].get(ch, "")), sb.BLOCK_COLORS["NEUTRAL"]))


def _preview_pixmap(key: str) -> QPixmap | None:
    """结构键 -> Wiki 渲染图 QPixmap（缓存当前一份；缺失/解码失败返 None）。

    原图超过 _PREV_WORK_MAX 边长时先一次性降采样为工作副本（Smooth），
    后续每次绘制只需从工作副本缩到目标尺寸，避免大图反复缩放开销。
    """
    if _PREV_CACHE["key"] == key and _PREV_CACHE["pm"] is not None:
        return _PREV_CACHE["pm"]
    path = os.path.join(PREVIEW_DIR, key + ".png")
    if not os.path.isfile(path):
        return None
    pm = QPixmap(path)
    if pm.isNull():
        return None
    m = max(pm.width(), pm.height())
    if m > _PREV_WORK_MAX:
        k = _PREV_WORK_MAX / m
        small = pm.scaled(int(pm.width() * k), int(pm.height() * k),
                          Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
        if not small.isNull():
            pm = small
    _PREV_CACHE["key"] = key
    _PREV_CACHE["pm"] = pm
    return pm


def _tex_pixmap(name: str) -> QPixmap | None:
    """归一化方块名 -> 16x16 纹理 QPixmap（已知缺失直接返 None）。"""
    if name in _TEX_CACHE:
        return _TEX_CACHE[name]
    pm = None
    path = os.path.join(TEX_DIR, name + ".png")
    if os.path.isfile(path):
        loaded = QPixmap(path)
        if not loaded.isNull():
            pm = loaded
    _TEX_CACHE[name] = pm
    return pm


def _pt(x: float, y: float) -> QPointF:
    return QPointF(x, y)


def _draw_title(p: QPainter, rect: QRectF, text: str) -> None:
    f = QFont()
    f.setPixelSize(13)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QPen(_theme_color(235)))
    p.drawText(QRectF(rect.left(), rect.top(), rect.width(), 18),
               Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
               text)


def _draw_caption(p: QPainter, x: float, y: float, w: float,
                  text: str, over: bool = False) -> None:
    """区域下方居中小字；over=True 时叠在图上（加主题底色底衬）。"""
    f = QFont()
    f.setPixelSize(10)
    p.setFont(f)
    bg = QRectF(x, y, w, 14)
    if over:
        c = _theme_color(0)
        c.setAlpha(170)
        app = QApplication.instance()
        if app is not None:
            c = app.palette().color(QPalette.ColorRole.Window)
            c.setAlpha(180)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(c))
        p.drawRect(bg)
    p.setPen(QPen(_theme_color(170 if not over else 200)))
    p.drawText(bg,
               Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
               text)


def _draw_outlined_text(p: QPainter, x: float, y: float, text: str,
                        fill: QColor) -> None:
    """带深色描边的小字（叠在地图方块上仍可读），左上角定位。"""
    path = QPainterPath()
    f = QFont()
    f.setPixelSize(10)
    f.setBold(True)
    path.addText(x, y, f, text)
    p.setPen(QPen(_ANCHOR_OUTLINE, 3))
    p.setBrush(QBrush(fill))
    p.drawPath(path)


def _draw_anchor_mark(p: QPainter, gx: float, gy: float, cell: float) -> None:
    """锚点：格 (0,0) 红框 + 右侧描边文字（锚点恒在左上角）。"""
    p.setPen(QPen(_ANCHOR, 2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(gx - 0.5, gy - 0.5, cell + 1, cell + 1))
    _draw_outlined_text(p, gx + cell + 4, gy + cell + 2, "锚点(0,0)", _ANCHOR)


def _draw_preview(p: QPainter, key: str, rect: QRectF) -> bool:
    """在 rect 内等比缩放绘制 Wiki 渲染图；无图返回 False。"""
    pm = _preview_pixmap(key)
    if pm is None:
        return False
    tw, th = int(rect.width()), int(rect.height())
    if pm.width() <= 0 or pm.height() <= 0 or tw <= 1 or th <= 1:
        return False
    if (_PREV_SCALED["key"] == key and _PREV_SCALED["w"] == tw
            and _PREV_SCALED["h"] == th):
        scaled = _PREV_SCALED["pm"]
    else:
        scaled = pm.scaled(tw, th,
                           Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
        if scaled.isNull():
            return False
        _PREV_SCALED.update(key=key, w=tw, h=th, pm=scaled)
    x = rect.left() + (rect.width() - scaled.width()) / 2
    y = rect.top() + (rect.height() - scaled.height()) / 2
    p.drawPixmap(_pt(x, y), scaled)
    return True


def _draw_top_view(p: QPainter, bp: dict, rect: QRectF, dpr: float) -> None:
    """俯视图：最高层方块逐格贴真实纹理（缺失回退色块）+ 外框 + 锚点。"""
    W, D = bp["W"], bp["D"]
    tcol = bp["tcol"]

    cell_w = int(rect.width() // W) if W > 0 else 0
    cell_h = int(rect.height() // D) if D > 0 else 0
    cell = max(2, min(cell_w, cell_h, 24))
    tw, th = W * cell, D * cell
    tx = rect.left() + (rect.width() - tw) / 2
    ty = rect.top() + (rect.height() - th) / 2

    border_pen = QPen(_theme_color(150), 1)
    p.setPen(border_pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(tx - 0.5, ty - 0.5, tw + 1, th + 1))

    # 每种调色板字符的纹理只缩放一次（缩到整格边长，按 dpr 对齐物理像素）
    scaled: dict[str, QPixmap | None] = {}
    p.setPen(Qt.PenStyle.NoPen)
    for z in range(D):
        for x in range(W):
            ch = tcol[z][x]
            if ch == ".":
                continue
            tex = None
            if ch not in scaled:
                t = _tex_pixmap(_norm_block(bp["palette"].get(ch, "")))
                if t is not None and cell > 0:
                    s = t.scaled(int(round(cell * dpr)), int(round(cell * dpr)),
                                 Qt.AspectRatioMode.IgnoreAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
                    if not s.isNull():
                        s.setDevicePixelRatio(dpr if dpr > 0 else 1.0)
                        t = s
                    else:
                        t = None
                scaled[ch] = t
            tex = scaled[ch]
            if tex is not None:
                p.drawPixmap(_pt(tx + x * cell, ty + z * cell), tex)
            else:                      # 纹理缺失回退色块
                p.setBrush(QBrush(_block_color(bp, ch)))
                p.drawRect(QRectF(tx + x * cell, ty + z * cell, cell, cell))
                p.setBrush(Qt.BrushStyle.NoBrush)

    _draw_caption(p, tx, ty + th + 2, tw, "俯视（上=北，左=西）")
    _draw_anchor_mark(p, tx, ty, cell)


def _render_blueprint(p: QPainter, key: str, bp: dict, rect: QRectF,
                      name: str, dpr: float) -> None:
    """精确蓝图模式：左 Wiki 渲染图 + 右纹理俯视图 + 锚点标注。

    无渲染图时俯视图占满整幅。
    """
    W, D, H = bp["W"], bp["D"], bp["H"]
    margin = 6.0
    caption_h = 15.0
    title_h = 20.0
    gap = 12.0
    area = QRectF(rect.left() + margin,
                  rect.top() + title_h,
                  rect.width() - margin * 2,
                  rect.height() - title_h - caption_h - margin)

    has_prev = _preview_pixmap(key) is not None
    if has_prev:
        left_w = (area.width() - gap) / 2
        if _draw_preview(p, key, QRectF(area.left(), area.top(),
                                        left_w, area.height())):
            _draw_caption(p, area.left(), area.bottom() - caption_h + 3,
                          left_w, "Wiki 渲染图", over=True)
            top_rect = QRectF(area.left() + left_w + gap, area.top(),
                              area.width() - left_w - gap, area.height())
        else:                          # 图在但绘制失败（极端小尺寸）
            top_rect = area
    else:
        top_rect = area                # 无渲染图：俯视占满（ocean_ruin 等）
    _draw_top_view(p, bp, top_rect, dpr)

    y0, y1 = bp["y0"], bp["y1"]
    _draw_title(p, rect, f"{name}  {W}×{D}×{H}（Y {y0}~{y1}）")


def _render_fallback(p: QPainter, key: str, rect: QRectF, name: str,
                     size: tuple) -> None:
    """拼装结构兜底：有渲染图铺满展示；否则虚线外框 + 说明 + 锚点角标。"""
    W, D, H = size
    if _draw_preview(p, key, QRectF(rect.left(), rect.top() + 20.0,
                                    rect.width(), rect.height() - 20.0)):
        _draw_caption(p, rect.left(), rect.bottom() - 13, rect.width(),
                      "Wiki 渲染图（内部布局随机拼装）", over=True)
        _draw_title(p, rect, f"{name}  约 {W}×{D}×{H}（示意）")
        return

    margin = 10.0
    caption_h = 15.0
    title_h = 20.0
    area = QRectF(rect.left() + margin, rect.top() + title_h,
                  rect.width() - margin * 2,
                  rect.height() - title_h - caption_h - margin)
    ratio = min(area.width() / W, area.height() / D, 3.0)
    bw, bh = W * ratio, D * ratio
    box = QRectF(area.center().x() - bw / 2, area.center().y() - bh / 2,
                 bw, bh)

    p.setPen(QPen(_theme_color(150), 1.2, Qt.PenStyle.DashLine))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(box)
    # 内部一条淡虚线：表达「布局随机拼装」
    p.setPen(QPen(_theme_color(70), 1, Qt.PenStyle.DashLine))
    p.drawLine(_pt(box.left(), box.center().y()),
               _pt(box.right(), box.center().y()))

    f = QFont()
    f.setPixelSize(11)
    p.setFont(f)
    p.setPen(QPen(_theme_color(180)))
    p.drawText(box, Qt.AlignmentFlag.AlignCenter, "内部布局随机拼装\n（示意）")

    # 锚点角标：左上角红框 + 描边文字
    p.setPen(QPen(_ANCHOR, 2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(box.left() - 1, box.top() - 1, 7, 7))
    _draw_outlined_text(p, box.left() + 9, box.top() + 12,
                        "锚点(0,0)", _ANCHOR)

    _draw_caption(p, box.left(), box.bottom() + 3, box.width(),
                  "示意图（无固定蓝图）")
    _draw_title(p, rect, f"{name}  约 {W}×{D}×{H}（示意）")


def render(key: str, name: str, width: int, height: int,
           dpr: float = 1.0) -> QPixmap:
    """渲染结构锚点示意图。

    :param key: 结构内部键（structure_params 键）
    :param name: 中文结构名（标题显示）
    :param width/height: 逻辑像素（label 当前尺寸）
    :param dpr: 设备像素比（高分屏清晰渲染）
    :return: QPixmap；尺寸过小或无数据时返回空 QPixmap
    """
    if width < 40 or height < 40:
        return QPixmap()
    pm = QPixmap(int(width * dpr), int(height * dpr))
    pm.setDevicePixelRatio(dpr if dpr > 0 else 1.0)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    rect = QRectF(0, 0, width, height)
    bp = sb.blueprint(key)
    if bp is not None:
        _render_blueprint(p, key, bp, rect, name, dpr)
    else:
        size = sb.fallback_size(key)
        if size is None:
            p.end()
            return QPixmap()
        _render_fallback(p, key, rect, name, size)
    p.end()
    return pm
