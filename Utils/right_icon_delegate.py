# -*- coding: utf-8 -*-
"""列表项图标固定显示在行最右侧的委托（Delegate）

背景：QListWidget 的默认图标（DecorationRole）由风格绘制在文字左侧，
无法满足"图标统一靠在最右边"的需求。本委托把背景/选中高亮交给默认风格
按完整行宽绘制，文字按剩余宽度自动省略（尾部显示 …），再把自定义数据
角色里携带的 QPixmap 固定画在行的右缘。
用途：AutoBackUp 存档列表——当文件夹内含 icon 文件（即为 MC 地图存档）时，
把世界封面图标画在该行最右侧，一眼区分哪些文件夹是可玩的世界存档。
"""
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QFontMetrics, QPixmap
from PySide6.QtWidgets import (QApplication, QStyle, QStyledItemDelegate,
                               QStyleOptionViewItem)

# 自定义数据角色：存放在行右缘显示的小图标（QPixmap）
ICON_ROLE = Qt.ItemDataRole.UserRole + 1

ICON_RIGHT_MARGIN = 6   # 图标与行右缘的留白
ICON_TEXT_GAP = 8       # 文字（省略号）与图标之间的最小间距
DEFAULT_ICON_SIZE = 32  # 图标显示尺寸（MC 存档 icon.png 源图为 64×64，2:1 整数缩小保持像素风清晰）


class RightIconDelegate(QStyledItemDelegate):
    """列表项委托：背景/选中高亮/文字由默认风格绘制，图标固定画在行最右侧"""

    def __init__(self, icon_size=DEFAULT_ICON_SIZE, parent=None):
        super().__init__(parent)
        self.icon_size = icon_size

    @staticmethod
    def set_right_icon(item, pixmap):
        """为列表项挂上要显示在行右缘的小图标（传 None 表示清除图标）"""
        if isinstance(pixmap, QPixmap) and not pixmap.isNull():
            item.setData(ICON_ROLE, pixmap)
        else:
            item.setData(ICON_ROLE, None)

    def paint(self, painter, option, index):
        pixmap = index.data(ICON_ROLE)
        if not isinstance(pixmap, QPixmap) or pixmap.isNull():
            super().paint(painter, option, index)  # 无图标：完全默认绘制
            return

        # 1. 背景/选中高亮按完整行宽绘制；文字按剩余宽度预省略（尾部 …），为右侧图标让位
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.textElideMode = Qt.TextElideMode.ElideRight
        metrics = QFontMetrics(opt.font)
        avail = option.rect.width() - ICON_RIGHT_MARGIN - self.icon_size - ICON_TEXT_GAP
        opt.text = metrics.elidedText(opt.text, Qt.TextElideMode.ElideRight, max(0, avail))
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, option.widget)

        # 2. 图标固定画在行最右侧（右缘留白），垂直居中
        slot = max(0, min(self.icon_size, option.rect.width() - ICON_RIGHT_MARGIN))
        icon_x = option.rect.left() + option.rect.width() - ICON_RIGHT_MARGIN - slot
        icon_y = option.rect.top() + (option.rect.height() - slot) // 2
        # 非正方形图标的兜底处理（罕见）：按纵横比缩放到图标槽内并居中
        fit = pixmap.size().scaled(slot, slot, Qt.AspectRatioMode.KeepAspectRatio)
        target = QRect(
            icon_x + (slot - fit.width()) // 2,
            icon_y + (slot - fit.height()) // 2,
            fit.width(), fit.height(),
        )
        painter.save()
        painter.drawPixmap(target, pixmap)
        painter.restore()

    def sizeHint(self, option, index):
        """所有行统一预留图标高度（无图标行保持同高，列表视觉整齐）"""
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), self.icon_size + 4))
        return size
