# utils/enchant_list_widget.py
# 分类附魔列表控件：展示某类别的附魔，支持点击调级、拖拽到已选列表
from PySide6.QtWidgets import QListWidget, QApplication
from PySide6.QtCore import Qt, QMimeData, QPoint
from PySide6.QtGui import QDrag, QPixmap, QPainter, QColor, QPen, QFont


class EnchantListWidget(QListWidget):
    """分类附魔列表控件：展示某一类别（近战武器/工具/远程武器/防具/通用附魔/诅咒）下的所有附魔

    交互说明：
    - 左键拖拽：将附魔拖入上方已选附魔列表（DropListWidget）
    - 左键点击：附魔等级 +1（不超过最大等级）
    - 右键点击：附魔等级 -1（不低于 1 级）

    列表项数据存储约定（由 ChooseItemsWindow.load_enchant_data 填充）：
    - Qt.UserRole:     附魔 ID
    - Qt.UserRole + 1: 当前等级
    - Qt.UserRole + 2: 最大等级
    """
    def __init__(self, parent=None):
        """初始化分类附魔列表控件：开启拖出、禁止拖入"""
        super().__init__(parent)
        self.setDragEnabled(True)         # 允许拖出（把附魔拖到上方已选列表）
        self.setAcceptDrops(False)        # 不接受拖入（本列表只是附魔的来源）
        # 禁用右键菜单，防止右键弹出干扰
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self._drag_start_pos = QPoint()   # 鼠标按下时的起始位置（用于区分点击与拖拽）

    def mousePressEvent(self, event):
        """鼠标按下时触发：记录左键按下的起始位置，为拖拽距离判断做准备"""
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)  # 保留父类默认行为（选中项切换等）

    def mouseMoveEvent(self, event):
        """鼠标按住移动时触发：超过拖拽阈值后启动 QDrag，把附魔数据携带给拖放目标"""
        # 未按住左键直接返回
        if not (event.buttons() & Qt.LeftButton):
            return
        # 移动距离小于系统拖拽阈值，视为普通点击（由 mouseReleaseEvent 处理调级）
        if (event.pos() - self._drag_start_pos).manhattanLength() < QApplication.startDragDistance():
            return

        item = self.currentItem()
        if not item:
            return
        # 从列表项数据中取出附魔 ID 和当前等级
        enchant_id = item.data(Qt.UserRole)
        level = item.data(Qt.UserRole + 1)
        if not enchant_id:
            return

        # 生成拖拽图标
        pixmap = self._create_drag_pixmap(item.text())
        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setText(f"{enchant_id}:{level}")  # 拖拽数据格式："附魔ID:等级"
        drag.setMimeData(mime_data)
        drag.setPixmap(pixmap)                  # 拖拽时跟随鼠标的标签图标
        drag.setHotSpot(pixmap.rect().center())  # 热点为图标中心
        # 只允许复制动作（拖出后原列表项保留，不会从分类列表中删除）
        drag.exec_(Qt.CopyAction)

    def mouseReleaseEvent(self, event):
        """鼠标松开时触发：根据按键和移动距离处理等级调整

        功能说明：
        - 左键且未超过拖拽阈值（即点击）：等级 +1，同时更新项的显示文本
        - 右键（右键不用于拖拽，无需判断距离）：等级 -1，同时更新项的显示文本
        - 其他情况交回父类默认处理
        """
        # 左键点击：增加等级
        if event.button() == Qt.LeftButton:
            # 判断是点击（非拖拽）
            if (event.pos() - self._drag_start_pos).manhattanLength() < QApplication.startDragDistance():
                item = self.currentItem()
                if item:
                    level = item.data(Qt.UserRole + 1) or 1      # 当前等级（无数据时兜底为 1）
                    max_level = item.data(Qt.UserRole + 2) or 1  # 最大等级（无数据时兜底为 1）
                    if level < max_level:  # 已是最大等级则不再增加
                        level += 1
                        item.setData(Qt.UserRole + 1, level)  # 更新存储的等级
                        # 更新显示文本：取 "(" 之前的附魔名，重新拼上等级
                        base_name = item.text().split("(")[0].strip()
                        item.setText(f"{base_name} (等级 {level})")
        # 右键点击：减少等级（不判断拖拽距离，因为右键不用于拖拽）
        elif event.button() == Qt.RightButton:
            item = self.currentItem()
            if item:
                level = item.data(Qt.UserRole + 1) or 1
                if level > 1:  # 已是 1 级则不再减少
                    level -= 1
                    item.setData(Qt.UserRole + 1, level)
                    base_name = item.text().split("(")[0].strip()
                    item.setText(f"{base_name} (等级 {level})")

        super().mouseReleaseEvent(event)  # 保留父类默认行为

    def _create_drag_pixmap(self, text):
        """生成拖拽时跟随的标签图标

        功能说明：
        - 根据附魔名称文本绘制一个深色圆角标签图（拖拽时的视觉反馈）
        - 图标宽度随文本长度自适应，高度固定 30px

        参数：
            text: 显示在标签上的文本（通常为 "附魔名 (等级 N)"）

        返回：
            pixmap: 深色圆角背景 + 白色居中文字的 QPixmap
        """
        font = QFont("Arial", 10)
        width = max(120, len(text) * 10 + 30)  # 宽度至少 120px，按字符数自适应扩展
        height = 30
        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.transparent)  # 背景透明（只有圆角矩形部分可见）

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)  # 抗锯齿，圆角更平滑

        # 绘制深色半透明圆角背景 + 浅色描边
        painter.setBrush(QColor(40, 40, 40, 220))
        painter.setPen(QPen(QColor(255, 255, 255, 80), 1))
        painter.drawRoundedRect(0, 0, width - 1, height - 1, 8, 8)  # 圆角半径 8px

        # 绘制白色居中文本
        painter.setPen(Qt.white)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignCenter, text)

        painter.end()
        return pixmap
