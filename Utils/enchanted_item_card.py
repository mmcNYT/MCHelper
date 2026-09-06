# utils/enchanted_item_card.py
# 附魔物品卡片组件：物品图标 + 游戏 tooltip 风格的附魔列表方框
# 视觉参照 Minecraft 游戏内鼠标悬停物品时显示的提示框（深紫背景 + 紫色描边）
import os

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QPixmap, QColor, QFont, QPainter, QPen, QRegion

# ---------- 游戏内 tooltip 配色（取自 Minecraft 原版提示框渐变色） ----------
TOOLTIP_BG_TOP = QColor(16, 0, 16, 240)        # 背景渐变顶部（近黑紫）
TOOLTIP_BG_BOTTOM = QColor(16, 0, 16, 240)     # 背景渐变底部
TOOLTIP_BORDER_OUTER_START = QColor(80, 0, 255, 155)   # 外描边渐变起点（紫）
TOOLTIP_BORDER_OUTER_END = QColor(40, 0, 127, 155)     # 外描边渐变终点（深紫）
TOOLTIP_BORDER_INNER_START = QColor(40, 15, 66, 190)   # 内描边渐变起点
TOOLTIP_BORDER_INNER_END = QColor(20, 5, 33, 190)      # 内描边渐变终点
TOOLTIP_TEXT = QColor(164, 166, 166)           # 附魔文本灰白（普通附魔行）
TOOLTIP_HEADER = QColor(255, 255, 255)         # 物品名白字

# 罗马数字表（1-10 覆盖全部附魔最大等级）
ROMAN_NUMERALS = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]


def int_to_roman(level: int) -> str:
    """附魔等级转罗马数字；超出 10 或非法时回退为阿拉伯数字字符串"""
    if 1 <= level <= 10:
        return ROMAN_NUMERALS[level]
    return str(level) if level > 0 else "I"


def get_item_icon_path(item_name: str) -> str:
    """根据物品中文名映射 assets/icons/ 下的图标文件路径

    - 下拉框物品名 → 图标文件名（全为钻石质，盔甲/工具取钻石材质）
    - 找不到映射或文件不存在时返回空字符串（卡片隐藏图标区域）
    """
    mapping = {
        "附魔书": "enchanted_book",
        "剑": "diamond_sword",
        "斧": "diamond_axe",
        "矛": "diamond_spear",
        "镐": "diamond_pickaxe",
        "锹": "diamond_shovel",
        "铲": "diamond_shovel",  # 下拉框物品名用"铲"（与数据 applicable 一致），与"锹"同图标
        "锄": "diamond_hoe",
        "弓": "bow",
        "弩": "crossbow",
        "三叉戟": "trident",
        "重锤": "mace",
        "头盔": "diamond_helmet",
        "胸甲": "diamond_chestplate",
        "护腿": "diamond_leggings",
        "靴子": "diamond_boots",
        "钓鱼竿": "fishing_rod",
    }
    # 海龟壳特殊：物品全名"海龟壳"，在部分版本下拉框中可能显示为"海龟壳"
    if "海龟" in item_name:
        fname = "turtle_helmet"
    else:
        fname = mapping.get(item_name, "")
    if not fname:
        return ""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base_dir, "assets", "icons", f"{fname}.png")
    return path if os.path.exists(path) else ""


class _GlintIcon(QWidget):
    """附魔流光图标控件：物品纹理上叠加游戏附魔光效（紫色流光双层反向滚动）

    - 光效纹理 assets/icons/enchanted_glint.png（游戏原版 128x128，透明底紫色流纹）
    - QTimer 每帧平移光效贴图坐标（两层不同速度/相位反向滚动），仅重绘本控件
    - 实现游戏内附魔物品的"微微发光"视觉效果
    """

    FRAME_MS = 50        # 每帧间隔（~20fps，与游戏观感一致且开销低）
    SCROLL_FAST = 1      # 快速层每帧位移（px，缓慢流光，全周期约 2.4s）
    SCROLL_SLOW = 1      # 慢速层每帧位移（px，反向）

    _glint_tex = None  # 类级缓存光效纹理（多卡片共享同一份 QPixmap）

    def __init__(self, item_name: str, icon_size: int, parent=None):
        """初始化流光图标

        参数：
            item_name: 物品中文名（用于查找物品纹理）
            icon_size: 图标显示边长
        """
        super().__init__(parent)
        self._icon_size = icon_size
        self._offset_fast = 0   # 快速层当前位移
        self._offset_slow = 0   # 慢速层当前位移

        # 加载物品纹理（FastTransformation 保持像素锐利）
        self._item_pix = QPixmap()
        icon_path = get_item_icon_path(item_name)
        if icon_path:
            self._item_pix = QPixmap(icon_path).scaled(
                icon_size, icon_size, Qt.KeepAspectRatio, Qt.FastTransformation)

        # 加载光效纹理（类级缓存，所有卡片共享）
        if _GlintIcon._glint_tex is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            glint_path = os.path.join(base_dir, "assets", "icons", "enchanted_glint.png")
            if os.path.exists(glint_path):
                _GlintIcon._glint_tex = QPixmap(glint_path)
        self._has_glint = _GlintIcon._glint_tex is not None and not self._item_pix.isNull()

        if self._has_glint:
            # 光效纹理预缩放到 2x 平铺尺寸（paintEvent 每帧直接绘制，避免重复 scaled 开销）
            self._glint_scaled = _GlintIcon._glint_tex.scaled(
                icon_size * 2, icon_size * 2,
                Qt.KeepAspectRatioByExpanding, Qt.FastTransformation)
            # 剪辑区域 = 物品不透明像素区域（构造时算一次，光效不外溢到透明区）
            # MaskInColor：透明像素在掩码中置 1（白），物品像素置 0（黑）；
            # QRegion(位图) 取黑色像素构成区域 → 直接得到物品不透明区
            mask = self._item_pix.createMaskFromColor(Qt.transparent, Qt.MaskInColor)
            self._clip_region = QRegion(mask)

        self.setFixedSize(icon_size, icon_size)
        # 光效纹理可用才启动动画定时器
        if self._has_glint:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._advance)
            self._timer.start(self.FRAME_MS)

    def _advance(self):
        """每帧推进两层滚动位移（各自取模循环）并触发重绘"""
        self._offset_fast = (self._offset_fast + self.SCROLL_FAST) % self._icon_size
        self._offset_slow = (self._offset_slow - self.SCROLL_SLOW) % self._icon_size
        self.update()

    def paintEvent(self, event):
        """绘制：物品纹理 → 剪辑到不透明区域后加法混合叠两层滚动光效

        光效用 CompositionMode_Plus（加法混合，只提亮不遮盖物品原色，
        呈现游戏内"微微发光"效果），并对光效纹理整体降低不透明度避免过艳。
        """
        painter = QPainter(self)
        if self._item_pix.isNull():
            painter.end()
            return
        painter.drawPixmap(0, 0, self._item_pix)

        if self._has_glint:
            tex = self._glint_scaled
            # 光效仅绘制在物品不透明区域（构造时预计算的剪辑区域）
            painter.setClipRegion(self._clip_region)
            # 加法混合：光效颜色与物品颜色相加提亮（深紫底色不再压暗物品）
            painter.setCompositionMode(QPainter.CompositionMode_Plus)
            painter.setOpacity(0.35)

            size = self._icon_size
            # 两层平铺绘制（覆盖 2x2 格，位移取模后保证无空隙）
            for off_x, off_y in ((self._offset_fast, self._offset_fast),
                                 (self._offset_slow, self._offset_slow)):
                ox, oy = off_x - size, off_y - size
                for dx in (0, size * 2):
                    for dy in (0, size * 2):
                        painter.drawPixmap(ox + dx, oy + dy, tex)
        painter.end()


class EnchantedItemCard(QWidget):
    """单个已添加物品的卡片：物品图标在上，附魔 tooltip 方框在下

    数据来自 ChooseItemsWindow.on_confirm_clicked 打包的 selected_data：
        {"item_name": "剑", "enchants": [{"id", "name", "level"}, ...]}
    """

    ICON_SIZE = 48  # 物品图标显示边长（16x16 纹理放大 3 倍，保留像素锐利感）

    def __init__(self, item_name: str, enchants: list, parent=None):
        """初始化卡片

        参数：
            item_name: 物品中文名（如"剑"）
            enchants: 附魔列表 [{"id","name","level"}, ...]
        """
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # 1. 物品图标（居中）：有附魔 → 流光动画图标；无附魔 → 静态图标
        icon_path = get_item_icon_path(item_name)
        if enchants and icon_path:
            icon_label = _GlintIcon(item_name, self.ICON_SIZE)
        else:
            icon_label = QLabel()
            if icon_path:
                pix = QPixmap(icon_path)
                # FastTransformation 保持像素风锐利边缘（平滑会模糊像素画）
                icon_label.setPixmap(pix.scaled(
                    self.ICON_SIZE, self.ICON_SIZE,
                    Qt.KeepAspectRatio, Qt.FastTransformation))
            icon_label.setFixedSize(self.ICON_SIZE, self.ICON_SIZE)
            icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_label, 0, Qt.AlignHCenter)

        # 2. 附魔 tooltip 方框（游戏提示框风格）
        tooltip_box = _TooltipBox(item_name, enchants)
        layout.addWidget(tooltip_box, 0, Qt.AlignHCenter)


class _TooltipBox(QWidget):
    """游戏 tooltip 风格方框：paintEvent 自绘背景描边 + 布局文本行"""

    def __init__(self, item_name: str, enchants: list, parent=None):
        super().__init__(parent)
        self._item_name = item_name
        self._enchants = enchants

        # 文本行：物品名 + 每条附魔一行（名称 + 空格 + 罗马数字等级）
        # 使用应用默认字体（真实运行环境自动匹配系统中文字体，避免写死字体名跨环境失效）
        font = QFont()
        font.setPointSize(9)
        self.setFont(font)
        fm = self.fontMetrics()

        lines = [item_name] if item_name else []
        for ench in enchants:
            level_text = int_to_roman(ench.get("level", 1))
            lines.append(f"{ench.get('name', '')} {level_text}")

        self._line_texts = lines
        # 计算方框尺寸：文本宽 + 内边距（左右 8px），行高 + 上下 6px
        text_width = max((fm.horizontalAdvance(t) for t in lines), default=0)
        line_height = fm.height()
        self._line_height = line_height
        self._fixed_w = text_width + 16
        self._fixed_h = line_height * max(len(lines), 1) + 10
        self.setFixedSize(QSize(self._fixed_w, self._fixed_h))

    def paintEvent(self, event):
        """绘制：紫色渐变描边背景 → 物品名白字 → 附魔灰字（罗马数字）"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)  # 像素风格不需要抗锯齿

        w, h = self.width(), self.height()

        # 1. 背景（深紫近黑）
        painter.fillRect(self.rect(), TOOLTIP_BG_TOP)

        # 2. 内描边（一圈 1px 深紫渐变模拟，用纯色简化）
        painter.setPen(QPen(TOOLTIP_BORDER_INNER_START))
        painter.drawRect(0, 0, w - 1, h - 1)

        # 3. 外描边（2px 紫色，游戏外框最显眼的紫边）
        painter.setPen(QPen(TOOLTIP_BORDER_OUTER_START, 2))
        painter.drawRect(1, 1, w - 3, h - 3)

        # 4. 文本：第一行物品名白色，其余附魔灰白
        y = 5
        for i, text in enumerate(self._line_texts):
            painter.setPen(QPen(TOOLTIP_HEADER if i == 0 else TOOLTIP_TEXT))
            painter.drawText(8, y + self._line_height - 3, text)
            y += self._line_height
        painter.end()
