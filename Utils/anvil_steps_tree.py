# utils/anvil_steps_tree.py
# 铁砧合成步骤图（图形化方框树）
#
# 版面参照用户手绘稿，自上而下：
# - 顶层 = 全部原始物品（叶子框）；向下每层 = 一次铁砧合并的产物框；最底部 = 最终合成物
# - 方框内为物品图标；悬停方框弹出游戏 tooltip 风格提示（深紫背景+紫描边），
#   显示物品名与附魔（罗马数字等级）
# - 每个合并节点严格按铁砧摆放顺序：左框 = 目标物品（铁砧第一格），
#   右框 = 牺牲物品（铁砧第二格）
# - 汇合线汇入产物框的竖线上挂圆形经验标记（数字 = 该步花费等级），
#   悬停圆标显示该步计费明细；花费 ≥40（生存模式"过于昂贵"）的步骤圆标为红色
# - 最终合成物方框加粗描边，下方标注总花费（及过于昂贵警告）
#
# 另含"步骤图"线性模式（displayMode 下拉框切换）：每步一行依次排列，
# 行内 = [目标框] + [牺牲框] = [产物框]，行首行末标注步骤序号与花费；
# 其余交互（悬停 tooltip / 花费圆标 / 最终框加粗 / 总花费标注）与树模式一致。
from PySide6.QtCore import Qt, QRectF, QPoint, QTimer
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QPainter, QPen,
                           QBrush, QPixmap, QPainterPath, QCursor, QRegion)
from PySide6.QtWidgets import (QGraphicsView, QGraphicsScene, QGraphicsItem,
                               QGraphicsPathItem, QGraphicsSimpleTextItem,
                               QWidget)

from Utils.anvil_optimizer import AnvilPlan
from Utils.enchanted_item_card import (int_to_roman, get_item_icon_path,
                                        TOOLTIP_BG_TOP,
                                        TOOLTIP_BORDER_OUTER_START,
                                        TOOLTIP_BORDER_INNER_START,
                                        TOOLTIP_TEXT, TOOLTIP_HEADER)

_GLINT_TEX_PATH = None  # 光效纹理路径（首用时解析，避免模块导入期路径依赖）


def _glint_texture() -> QPixmap:
    """附魔光效纹理（类外缓存，全部方框共享同一份 QPixmap；不可用返回 null）"""
    global _GLINT_TEX_PATH
    if _GLINT_TEX_PATH is None:
        import os
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _GLINT_TEX_PATH = os.path.join(
            base_dir, "assets", "icons", "enchanted_glint.png")
    pix = QPixmap(_GLINT_TEX_PATH)
    return pix  # 文件不存在时为 null pixmap，调用方按无光效处理

# ---------- 版面常量 ----------
_BOX_W, _BOX_H = 68, 60    # 物品方框尺寸（内含 48px 图标）
_ICON = 48                 # 图标显示边长（与卡片一致）
_LEAF_GAP = 18             # 相邻叶子框间隔
_SIBLING_GAP = 30          # 两棵子树间隔
_ROW_H = 88                # 行高（框高 + 连线空间）
_STEP_GAP = 44             # 步骤图模式：框与运算符（+/=）间隔
_MARGIN = 16               # 场景边距
_LINE_COLOR = QColor("#1A1A1A")     # 连线/方框描边
_TEXT_COLOR = QColor(70, 70, 70)    # 总花费文字
_WARN_COLOR = QColor(190, 30, 30)   # 过于昂贵（红）
_COST_COLOR = QColor(30, 130, 30)   # 经验花费圆标（绿）


class _Node:
    """合并树节点（leaf=原始物品 / merge=一次铁砧合并，item 为其产物）"""
    def __init__(self, kind, item=None, step=None, step_index=None):
        self.kind = kind
        self.item = item            # AnvilItem（框内展示的物品）
        self.step = step            # MergeStep（仅 merge 节点）
        self.step_index = step_index  # 0-based 步骤序号（仅 merge 节点）
        self.role = ""              # "final" / "target" / "sacrifice"
        self.left = None
        self.right = None
        self.row = 0                # 自顶向下行号（叶子=0）
        self.cx = 0.0               # 中心 x
        self.box = None             # 对应的 _ItemBox


def _find_producer(steps, before, item):
    """在 steps[0..before) 中找到产出 item 的步骤序号（无则 None）

    按对象身份匹配：优化器构造步骤表时后一步的 target/sacrifice 就是
    前一步 result 的同一对象（引用传递，身份链完整），因此 `is` 可唯一
    确定父子关系；值相等匹配在两条路径产出完全相同中间物品（如两对
    相同附魔书分别合并）时会重复展开同一产出者、丢失真正的原始物品。
    """
    for k in range(before - 1, -1, -1):
        if steps[k].result is item:
            return k
    return None


def _build_tree(steps):
    """按执行序步骤表递归构建合并树（根 = 最后一步 = 最终合成物）

    某步的 target/sacrifice 若是此前某步的产物，则该子节点继续展开为那一步，
    否则为原始物品叶子。左子树 = 目标（第一格），右子树 = 牺牲（第二格）。
    """
    def build(idx):
        step = steps[idx]
        node = _Node("merge", item=step.result,
                     step=step, step_index=idx)
        node.left = _wrap(idx, step.target)
        node.right = _wrap(idx, step.sacrifice)
        node.left.role = "target"
        node.right.role = "sacrifice"
        return node

    def wrap_build(idx, item):
        k = _find_producer(steps, idx, item)
        return build(k) if k is not None else _Node("leaf", item=item)

    # build/wrap 互相递归（用包装函数实现）
    def _wrap(idx, item):
        return wrap_build(idx, item)

    return build(len(steps) - 1)


def _set_rows(node):
    """自底向上计算行号：叶子=0，合并节点=max(子行)+1；返回节点行号"""
    if node.kind == "leaf":
        node.row = 0
        return 0
    node.row = max(_set_rows(node.left), _set_rows(node.right)) + 1
    return node.row


def _place_x(node, x_left):
    """中序布置子树横向位置：叶子占固定槽位，合并节点居中于两子之间；
    返回子树占用宽度"""
    if node.kind == "leaf":
        node.cx = x_left + _LEAF_GAP / 2 + _BOX_W / 2
        return _LEAF_GAP + _BOX_W
    w_left = _place_x(node.left, x_left)
    w_right = _place_x(node.right, x_left + w_left + _SIBLING_GAP)
    node.cx = (node.left.cx + node.right.cx) / 2
    return w_left + _SIBLING_GAP + w_right


class _ItemBox(QGraphicsItem):
    """物品方框：白底黑描边矩形，内部居中放物品图标（缺图标回退物品名）。

    带附魔的物品叠加游戏附魔流光（紫色流光双层反向滚动，由视图级
    QTimer 统一驱动重绘——QGraphicsItem 非 QObject 不能自挂定时器）。
    悬停时经由所属视图弹出游戏 tooltip 风格提示（物品名 + 附魔列表）。
    left_box / right_box 仅合并节点使用，指向左（目标）/右（牺牲）子框。
    """

    def __init__(self, anvil_item, role, view):
        super().__init__()
        self.setAcceptHoverEvents(True)
        self.setZValue(2)
        self.anvil_item = anvil_item
        self.role = role
        self._view = view
        self.left_box = None
        self.right_box = None
        pix = QPixmap(get_item_icon_path(anvil_item.name))
        if not pix.isNull():
            self._pix = pix.scaled(_ICON, _ICON,
                                   Qt.KeepAspectRatio, Qt.FastTransformation)
        else:
            self._pix = QPixmap()
        # 附魔流光：有附魔且物品纹理可用时叠加（与卡片 _GlintIcon 同视觉）
        self._offset_fast = 0
        self._offset_slow = 0
        self._glint_scaled = None
        self._clip_region = None
        if anvil_item.enchants and not self._pix.isNull():
            tex = _glint_texture()
            if not tex.isNull():
                # 预缩放到 2x 平铺尺寸（paint 每帧直接绘制，避免重复 scaled）
                self._glint_scaled = tex.scaled(
                    _ICON * 2, _ICON * 2,
                    Qt.KeepAspectRatioByExpanding, Qt.FastTransformation)
                # 剪辑区域 = 物品不透明像素区域（同卡片 _GlintIcon 的掩码法）
                mask = self._pix.createMaskFromColor(Qt.transparent,
                                                     Qt.MaskInColor)
                self._clip_region = QRegion(mask)

    def advance_glint(self):
        """推进流光位移一帧（由视图级定时器统一调用）并重绘本框

        两层反向滚动（同卡片 _GlintIcon）：快速层正向、慢速层反向
        """
        if self._glint_scaled is not None:
            self._offset_fast = (self._offset_fast + 1) % _ICON
            self._offset_slow = (self._offset_slow - 1) % _ICON
            self.update()

    def boundingRect(self):
        return QRectF(-3, -3, _BOX_W + 6, _BOX_H + 6)

    def paint(self, painter, option, widget=None):
        painter.fillRect(QRectF(0, 0, _BOX_W, _BOX_H), QBrush(QColor("white")))
        painter.setPen(QPen(_LINE_COLOR, 3 if self.role == "final" else 2))
        painter.drawRect(QRectF(0, 0, _BOX_W, _BOX_H))
        if not self._pix.isNull():
            ix = (_BOX_W - _ICON) // 2
            iy = (_BOX_H - _ICON) // 2
            painter.drawPixmap(ix, iy, self._pix)
            if self._glint_scaled is not None:
                # 光效仅绘制在物品不透明区域，加法混合提亮（同卡片实现）
                # 平铺间距必须 = 纹理边长（96px）：间距小于纹理边长会使相邻
                # 瓦片在图标区内重叠，加法混合重复叠加形成周期性亮斑。
                # 纹理 96x96 平移量在 [-48,-1] 时单片即完整覆盖 48x48
                # 图标区，故每层只需绘制一次（与卡片 2x2 平铺数学等价）
                painter.save()
                painter.setClipRegion(self._clip_region)
                painter.setCompositionMode(QPainter.CompositionMode_Plus)
                painter.setOpacity(0.35)
                tex = self._glint_scaled
                for off in (self._offset_fast, self._offset_slow):
                    painter.drawPixmap(ix + off - _ICON,
                                       iy + off - _ICON, tex)
                painter.restore()
        else:
            painter.setPen(QPen(QColor(110, 110, 110)))
            f = QFont()
            f.setPointSize(9)
            painter.setFont(f)
            painter.drawText(QRectF(0, 0, _BOX_W, _BOX_H), Qt.AlignCenter,
                             self.anvil_item.name)

    def hoverEnterEvent(self, event):
        self._view.show_tooltip(self._tooltip_lines())
        event.accept()

    def hoverLeaveEvent(self, event):
        self._view.hide_tooltip()
        event.accept()

    def _tooltip_lines(self):
        """游戏风格提示内容：物品名（白）+ 附魔行（灰，罗马数字）"""
        lines = [(self.anvil_item.name, TOOLTIP_HEADER)]
        for eid, lv in sorted(self.anvil_item.enchants):
            lines.append((f"{self._view._ench_name(eid)} {int_to_roman(lv)}",
                          TOOLTIP_TEXT))
        return lines


class _CostCircle(QGraphicsItem):
    """经验花费圆标：挂在汇合竖线上，数字 = 该步花费等级。

    花费 ≥40 时变红（生存模式铁砧会显示"过于昂贵"）；
    悬停显示该步计费明细（PWP / 各魔咒费用）。
    """

    R = 12

    def __init__(self, step, step_no, too_expensive, view):
        super().__init__()
        self.setAcceptHoverEvents(True)
        self.setZValue(3)
        self.step = step
        self.step_no = step_no
        self.cost = step.cost
        self.is_too_expensive = too_expensive
        self._view = view

    def boundingRect(self):
        r = self.R
        return QRectF(-r - 2, -r - 2, 2 * r + 4, 2 * r + 4)

    def paint(self, painter, option, widget=None):
        r = self.R
        color = _WARN_COLOR if self.is_too_expensive else _COST_COLOR
        painter.setBrush(QBrush(QColor("white")))
        painter.setPen(QPen(color, 2))
        painter.drawEllipse(QRectF(-r, -r, 2 * r, 2 * r))
        f = QFont()
        f.setPointSize(9)
        f.setBold(True)
        painter.setFont(f)
        painter.setPen(QPen(color))
        painter.drawText(QRectF(-r, -r, 2 * r, 2 * r), Qt.AlignCenter,
                         str(self.cost))

    def hoverEnterEvent(self, event):
        self._view.show_tooltip(self._tooltip_lines())
        event.accept()

    def hoverLeaveEvent(self, event):
        self._view.hide_tooltip()
        event.accept()

    def _tooltip_lines(self):
        lines = [(f"第 {self.step_no} 步 · 花费 {self.cost} 级",
                  TOOLTIP_HEADER)]
        if self.step.cost >= 40:
            lines.append(("超过 39 级，生存模式铁砧会显示「过于昂贵！」",
                          _WARN_COLOR))
        lines.extend(self._view._step_detail_lines(self.step))
        return lines


class _GameTooltip(QWidget):
    """游戏 tooltip 风格悬浮框（视图视口上的子控件，鼠标事件穿透）

    深紫近黑背景 + 紫色渐变描边；行内容 (文本, 颜色) 列表，
    首行习惯用白色物品名/标题，其余灰色明细行。
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.hide()
        self._lines = []
        self._font = QFont()
        self._font.setPointSize(9)
        self._fm = QFontMetrics(self._font)

    def popup(self, lines, cursor_local: QPoint):
        """按内容自适应尺寸，显示在光标右下（越界自动翻转/收边）"""
        self._lines = lines
        self.setFont(self._font)
        w = max((self._fm.horizontalAdvance(t) for t, _ in lines),
                default=0) + 16
        h = self._fm.height() * max(len(lines), 1) + 10
        self.setFixedSize(max(w, 40), h)
        vw = self.parentWidget().width()
        vh = self.parentWidget().height()
        x = cursor_local.x() + 14
        y = cursor_local.y() + 16
        if x + self.width() > vw - 2:
            x = cursor_local.x() - self.width() - 10
        if y + self.height() > vh - 2:
            y = cursor_local.y() - self.height() - 10
        x = max(0, min(x, vw - self.width() - 2))
        y = max(0, min(y, vh - self.height() - 2))
        self.move(x, y)
        self.show()
        self.raise_()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)  # 像素风格
        w, h = self.width(), self.height()
        # 深紫背景
        painter.fillRect(self.rect(), TOOLTIP_BG_TOP)
        # 内描边（深紫）
        painter.setPen(QPen(TOOLTIP_BORDER_INNER_START))
        painter.drawRect(0, 0, w - 1, h - 1)
        # 外描边（紫）
        painter.setPen(QPen(TOOLTIP_BORDER_OUTER_START, 2))
        painter.drawRect(1, 1, w - 3, h - 3)
        # 文本行
        y = 5
        for text, color in self._lines:
            painter.setPen(QPen(color))
            painter.drawText(8, y + self._fm.height() - 3, text)
            y += self._fm.height()
        painter.end()


class AnvilStepsTree(QGraphicsView):
    """铁砧合成步骤图（图形化方框树）

    用法：
        tree = AnvilStepsTree()
        tree.show_plan(plan, data_manager)   # 渲染优化器输出的合并方案
        tree.clear_plan()                    # 清空回到占位提示
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        # 画布淡灰背景（与卡片列表一致）
        self.setBackgroundBrush(QBrush(QColor("#ECECEC")))
        self.setRenderHint(QPainter.Antialiasing, False)
        self.setAlignment(Qt.AlignCenter)
        self._dm = None
        self._boxes = []
        self._circles = []
        self._placeholder_item = None
        self._tooltip = _GameTooltip(self.viewport())
        # 流光动画驱动：QGraphicsItem 非 QObject 不能自挂 QTimer，
        # 由视图级定时器统一推进全部带附魔方框（无带附魔框时自停）
        self._glint_timer = QTimer(self)
        self._glint_timer.timeout.connect(self._advance_glint)
        self._glint_timer.start(50)
        self._placeholder = ("添加物品后点击「开始计算」，"
                             "这里将显示最优合成步骤")
        self.clear_plan()

    # ---------- 对外接口 ----------
    @property
    def placeholder_text(self) -> str:
        return self._placeholder

    def is_placeholder(self) -> bool:
        return self._placeholder_item is not None

    def boxes(self) -> list:
        """当前全部物品方框（_ItemBox 列表，供测试/检查）"""
        return list(self._boxes)

    def cost_circles(self) -> list:
        """当前全部经验花费圆标（_CostCircle 列表）"""
        return list(self._circles)

    def final_box(self):
        """最终合成物方框；占位状态返回 None"""
        for b in self._boxes:
            if b.role == "final":
                return b
        return None

    def _advance_glint(self):
        """流光帧推进：推进全部带附魔方框；无带附魔框时自停省开销"""
        glint_boxes = [b for b in self._boxes if b._glint_scaled is not None]
        if not glint_boxes:
            self._glint_timer.stop()
            return
        for b in glint_boxes:
            b.advance_glint()

    def _ensure_glint_timer(self):
        """渲染新方案后按需重启流光定时器（无带附魔框时保持停止）"""
        if any(b._glint_scaled is not None for b in self._boxes):
            self._glint_timer.start(50)

    def clear_plan(self):
        """清空图形并显示占位提示"""
        self.hide_tooltip()
        self._scene.clear()
        self._boxes.clear()
        self._circles.clear()
        self._dm = None
        t = QGraphicsSimpleTextItem(self._placeholder)
        f = QFont()
        f.setItalic(True)
        t.setFont(f)
        t.setBrush(QBrush(QColor(140, 140, 140)))
        self._scene.addItem(t)
        self._scene.setSceneRect(t.boundingRect().adjusted(-12, -12, 12, 12))
        self._placeholder_item = t

    def show_plan(self, plan: AnvilPlan, data_manager=None, mode: str = "tree"):
        """渲染完整合并方案（plan: AnvilOptimizer.optimize() 返回值）

        mode: "tree" = 自上而下方框树（默认）；"steps" = 每步一行依次排列
        """
        self.hide_tooltip()
        self._scene.clear()
        self._boxes.clear()
        self._circles.clear()
        self._placeholder_item = None
        self._dm = data_manager
        too_exp = set(plan.too_expensive_steps)

        if mode == "steps":
            self._show_plan_steps(plan, too_exp)
            self._ensure_glint_timer()
            self._scene.setSceneRect(
                self._scene.itemsBoundingRect().adjusted(-8, -8, 8, 8))
            return

        if plan.steps:
            root = _build_tree(plan.steps)
            root.role = "final"
        else:
            # 单物品：无步骤，只画最终框
            root = _Node("leaf", item=plan.final_item)
            root.role = "final"

        _set_rows(root)
        _place_x(root, _MARGIN)
        self._draw_node(root, too_exp)
        self._draw_summary(plan, root.cx,
                           _MARGIN + root.row * _ROW_H + _BOX_H)
        self._ensure_glint_timer()
        self._scene.setSceneRect(
            self._scene.itemsBoundingRect().adjusted(-8, -8, 8, 8))

    # ---------- 内部绘制：步骤图模式 ----------
    def _show_plan_steps(self, plan, too_exp):
        """步骤图模式：每步一行依次排列 [目标] + [牺牲] = [产物]

        行内从左到右 = 铁砧第一格（目标）、+ 号、第二格（牺牲）、
        = 号、产物框；= 号上方挂花费圆标（悬停计费明细），行末标注
        步骤序号与花费；最后一步产物框为最终合成物（加粗描边）。
        """
        y = _MARGIN
        op_font = QFont()
        op_font.setPointSize(13)
        op_font.setBold(True)
        op_fm = QFontMetrics(op_font)
        label_font = QFont()
        label_font.setPointSize(9)

        if not plan.steps:
            # 单物品：无步骤，只画最终框
            box = _ItemBox(plan.final_item, "final", self)
            box.setPos(_MARGIN, y)
            self._scene.addItem(box)
            self._boxes.append(box)
            last_cx, last_bottom = _MARGIN + _BOX_W / 2, y + _BOX_H
        else:
            for idx, step in enumerate(plan.steps):
                is_final = idx == len(plan.steps) - 1
                tx = _MARGIN
                sx = tx + _BOX_W + _STEP_GAP
                rx = sx + _BOX_W + _STEP_GAP
                plus_cx = tx + _BOX_W + _STEP_GAP / 2
                eq_cx = sx + _BOX_W + _STEP_GAP / 2

                tb = _ItemBox(step.target, "", self)
                tb.setPos(tx, y)
                sb = _ItemBox(step.sacrifice, "", self)
                sb.setPos(sx, y)
                rb = _ItemBox(step.result, "final" if is_final else "", self)
                rb.setPos(rx, y)
                for b in (tb, sb, rb):
                    self._scene.addItem(b)
                    self._boxes.append(b)

                # + / = 运算符（垂直居中于框行）
                for text, cx in (("+", plus_cx), ("=", eq_cx)):
                    op = QGraphicsSimpleTextItem(text)
                    op.setFont(op_font)
                    op.setBrush(QBrush(_LINE_COLOR))
                    op.setPos(cx - op_fm.horizontalAdvance(text) / 2,
                              y + _BOX_H / 2 - op_fm.height() / 2)
                    self._scene.addItem(op)

                # 花费圆标（= 号上方，悬停显示该步计费明细）
                circle = _CostCircle(step, idx + 1,
                                     idx + 1 in too_exp, self)
                circle.setPos(eq_cx, y - 9)
                self._scene.addItem(circle)
                self._circles.append(circle)

                # 行末步骤信息（过于昂贵时红色）
                too = idx + 1 in too_exp
                label = QGraphicsSimpleTextItem(
                    f"第 {idx + 1} 步 · 花费 {step.cost} 级"
                    + ("（过于昂贵）" if too else ""))
                label.setFont(label_font)
                label.setBrush(QBrush(_WARN_COLOR if too else _TEXT_COLOR))
                label.setPos(rx + _BOX_W + 10,
                             y + _BOX_H / 2
                             - label.boundingRect().height() / 2)
                self._scene.addItem(label)

                y += _ROW_H
            last_cx, last_bottom = rx + _BOX_W / 2, y - _ROW_H + _BOX_H
        self._draw_summary(plan, last_cx, last_bottom)

    # ---------- 内部绘制：共用 ----------
    def _draw_node(self, node, too_exp):
        """递归绘制：先子后父（父框需引用子框），连线画在框下层"""
        if node.kind == "merge":
            self._draw_node(node.left, too_exp)
            self._draw_node(node.right, too_exp)
            self._draw_merge_links(node, too_exp)
        y = _MARGIN + node.row * _ROW_H
        box = _ItemBox(node.item, node.role, self)
        box.setPos(node.cx - _BOX_W / 2, y)
        self._scene.addItem(box)
        self._boxes.append(box)
        node.box = box
        if node.kind == "merge":
            box.left_box = node.left.box
            box.right_box = node.right.box

    def _draw_merge_links(self, node, too_exp):
        """直角汇合连线（子框底部 → 汇合横线 → 竖线 → 产物框顶部）+
        经验花费圆标"""
        y = _MARGIN + node.row * _ROW_H
        lane_y = y - 18  # 汇合横线所在高度（产物框顶上方）
        path = QPainterPath()
        for child in (node.left, node.right):
            child_bottom = _MARGIN + child.row * _ROW_H + _BOX_H
            path.moveTo(child.cx, child_bottom)
            path.lineTo(child.cx, lane_y)
        path.moveTo(node.left.cx, lane_y)
        path.lineTo(node.right.cx, lane_y)
        path.moveTo(node.cx, lane_y)
        path.lineTo(node.cx, y)
        links = QGraphicsPathItem(path)
        links.setPen(QPen(_LINE_COLOR, 2))
        links.setZValue(0)
        self._scene.addItem(links)

        circle = _CostCircle(node.step, node.step_index + 1,
                             node.step_index + 1 in too_exp, self)
        circle.setPos(node.cx, y - 9)
        self._scene.addItem(circle)
        self._circles.append(circle)

    def _draw_summary(self, plan, cx: float, bottom_y: float):
        """最终框下方：总花费文字（+ 过于昂贵警告）

        cx = 最终框中心 x，bottom_y = 最终框底边 y（树/步骤两模式共用）
        """
        ty = bottom_y + 6
        f = QFont()
        f.setPointSize(9)
        total = QGraphicsSimpleTextItem(f"总花费 {plan.total_cost} 级")
        total.setFont(f)
        total.setBrush(QBrush(_TEXT_COLOR))
        total.setPos(cx - total.boundingRect().width() / 2, ty)
        self._scene.addItem(total)
        if plan.too_expensive_steps:
            warn = QGraphicsSimpleTextItem(
                f"注意：第 {'、'.join(map(str, plan.too_expensive_steps))} 步"
                f"超过 39 级，生存模式中铁砧会显示「过于昂贵！」")
            warn.setFont(f)
            warn.setBrush(QBrush(_WARN_COLOR))
            warn.setPos(cx - warn.boundingRect().width() / 2, ty + 18)
            self._scene.addItem(warn)

    # ---------- tooltip ----------
    def _ench_name(self, eid) -> str:
        if self._dm is not None:
            ench = self._dm.get_enchant_by_id(eid)
            if ench:
                return ench["name"]
        return eid

    def _step_detail_lines(self, step) -> list:
        """某步计费明细行（灰色部分）"""
        lines = []
        d = step.detail
        if d.get("pwp_cost"):
            lines.append((f"累积惩罚 {d['pwp_cost']} 级", TOOLTIP_TEXT))
        for eid, lv, fee, reason in d.get("enchant_costs", []):
            lines.append((f"{self._ench_name(eid)}：{reason}，+{fee} 级",
                          TOOLTIP_TEXT))
        for eid, reason in d.get("ignored", []):
            lines.append((f"{self._ench_name(eid)}：{reason}", TOOLTIP_TEXT))
        return lines

    def show_tooltip(self, lines):
        """在光标附近显示游戏风格悬浮框（items 亦可悬停项直接调用）"""
        local = self.viewport().mapFromGlobal(QCursor.pos())
        self._tooltip.popup(lines, local)

    def hide_tooltip(self):
        self._tooltip.hide()
