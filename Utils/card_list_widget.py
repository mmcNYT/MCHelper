# utils/card_list_widget.py
# 物品卡片列表控件：横排展示已添加的物品卡片
# 交互：清空按钮全清 / Del 键删除 / 再次点击取消选中 / 拖动交换位置
from PySide6.QtWidgets import QListWidget, QListView, QListWidgetItem
from PySide6.QtCore import Qt, Signal, QPoint, QMimeData, QTimer
from PySide6.QtGui import QDrag

from Utils.enchanted_item_card import EnchantedItemCard

_MIME_CARD = "application/x-card-reorder"  # 内部拖动交换位置的 MIME 类型


class CardListWidget(QListWidget):
    """物品卡片列表（横向流式布局，自动换行）

    在 QListWidget 默认行为之上的增强：
    - Del / Backspace 键：删除当前选中卡片，发射 cardRemoved(附魔ID列表)
    - 再次点击已选中卡片（未发生拖动）：取消选中
    - 左键拖动卡片：自实现 QDrag 内部拖放交换位置，发射 cardReordered
    - 清空：由外部按钮调用 clear_cards()，全清并发射 cardsCleared

    卡片控件管理策略：卡片数据完整存放在条目上（CARD_DATA_ROLE），
    结构变化（移动）后按数据重建全新卡片控件。不尝试保留旧控件——
    takeItem 时视图会对该行 editor 触发 closeEditor→deleteLater 异步销毁，
    重绑旧控件与销毁时序冲突（不同事件路径表现不同，已实测）。
    """

    CARD_IDS_ROLE = Qt.UserRole        # 附魔 ID 列表（list[str]）
    CARD_DATA_ROLE = Qt.UserRole + 3   # 卡片完整数据 dict：{"item_name", "enchants"}

    cardRemoved = Signal(list)   # 删除卡片信号，参数：该卡片的附魔 ID 列表
    cardReordered = Signal()     # 拖动交换位置成功后发射（顺序已变化）
    cardsCleared = Signal(list)  # 清空全部卡片信号，参数：被清空卡片的附魔 ID 并集

    DRAG_THRESHOLD = 8  # 启动拖动的最小位移（px，量级对齐 QApplication.startDragDistance）

    def __init__(self, parent=None):
        super().__init__(parent)
        # 横向流式布局 + 自动换行 + 卡片间距（UI 生成文件不携带此配置，在此统一设置）
        self.setViewMode(QListView.IconMode)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(True)
        self.setSpacing(8)
        # 拖放交换位置：关闭 Qt 内部拖动，改用自实现 QDrag（可完整控制卡片控件随行）
        self.setDragEnabled(False)
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setContextMenuPolicy(Qt.NoContextMenu)
        # 鼠标按下状态（点击取消选中 / 启动拖动共用）
        self._pressed_item = None
        self._press_pos = QPoint()
        self._press_on_selected = False  # 按下时该项是否已被选中
        self._drag_active = False        # 本次按下是否已启动拖动

    # ---------- 卡片添加 / 数据读取 ----------
    def add_card(self, data: dict):
        """按数据包添加一张物品卡片（数据包结构同 ChooseItemsWindow.selected_data）"""
        card = EnchantedItemCard(data["item_name"], data["enchants"])
        item = QListWidgetItem()
        item.setSizeHint(card.sizeHint())
        item.setData(self.CARD_IDS_ROLE, [e["id"] for e in data["enchants"]])
        item.setData(self.CARD_DATA_ROLE, data)
        self.addItem(item)
        self.setItemWidget(item, card)

    def card_enchant_ids(self, item) -> list:
        """读取卡片项上记录的附魔 ID 列表"""
        return item.data(self.CARD_IDS_ROLE) or []

    # ---------- 清空 ----------
    def clear_cards(self):
        """清空全部物品卡片（外部清空按钮调用），发射 cardsCleared 信号"""
        if self.count() == 0:
            return
        all_ids = []
        for i in range(self.count()):
            all_ids.extend(self.card_enchant_ids(self.item(i)))
        self.clear()
        self.cardsCleared.emit(all_ids)

    # ---------- Del 键删除 ----------
    def keyPressEvent(self, event):
        """Del / Backspace 删除当前选中卡片"""
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            item = self.currentItem()
            if item:
                self._remove_item(item)
            return  # 消费按键，不传给父类
        super().keyPressEvent(event)

    def _remove_item(self, item):
        """移除指定卡片项并发射 cardRemoved 信号"""
        if not item:
            return
        row = self.row(item)
        if row < 0:
            return
        ids = self.card_enchant_ids(item)
        self.takeItem(row)
        self.cardRemoved.emit(ids)

    # ---------- 鼠标：选中/取消选中 + 启动拖动 ----------
    def mousePressEvent(self, event):
        """左键按下：记录按下项与选中状态；选中/拖动交给父类"""
        if event.button() == Qt.LeftButton:
            self._pressed_item = self.itemAt(event.pos())
            self._press_pos = event.pos()
            self._press_on_selected = (self._pressed_item is not None
                                       and self._pressed_item is self.currentItem())
            self._drag_active = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """左键按住移动超过阈值 → 启动卡片拖动交换"""
        if ((event.buttons() & Qt.LeftButton) and not self._drag_active
                and self._pressed_item is not None
                and (event.pos() - self._press_pos).manhattanLength() >= self.DRAG_THRESHOLD):
            self._start_reorder_drag(self._pressed_item)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """左键松开：未发生拖动且按在已选中卡片上 → 取消选中（再次点击取消）

        注意：取消必须在 super().mouseReleaseEvent 之后执行——
        Qt 父类 release 处理会按按下时的 pressedIndex 恢复选中，先取消会被覆盖。
        """
        if (event.button() == Qt.LeftButton and not self._drag_active
                and self._press_on_selected):
            super().mouseReleaseEvent(event)  # 先完成 Qt 流程（clicked 信号等）
            self.clearSelection()
            self.setCurrentRow(-1)
            self._pressed_item = None
            self._press_on_selected = False
            return
        self._pressed_item = None
        self._press_on_selected = False
        super().mouseReleaseEvent(event)

    # ---------- 拖动交换位置（自实现） ----------
    # 判定依据只用自定义 MIME 类型：_MIME_CARD 仅本控件 _start_reorder_drag 会携带，
    # 天然排除外部拖入（下方附魔列表拖拽是 text/plain）；不依赖 event.source()
    # （手动构造的拖放事件 source() 为 None，依赖它会破坏可测试性）
    def _start_reorder_drag(self, item):
        """启动 QDrag：携带起始行号，拖动图标为卡片实时快照"""
        self._drag_active = True
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(_MIME_CARD, str(self.row(item)).encode())
        drag.setMimeData(mime)
        widget = self.itemWidget(item)
        if widget is not None:
            drag.setPixmap(widget.grab())  # 卡片快照跟随鼠标
        drag.exec_(Qt.MoveAction)  # 阻塞至松手，期间 dropEvent 被回调

    def dragEnterEvent(self, event):
        """只接受携带卡片交换 MIME 的拖动"""
        if event.mimeData().hasFormat(_MIME_CARD):
            event.setDropAction(Qt.MoveAction)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        """拖动经过时持续接受，防止鼠标显示禁止符号"""
        if event.mimeData().hasFormat(_MIME_CARD):
            event.setDropAction(Qt.MoveAction)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        """松手：解析起始行 + 光标处目标行，执行搬移交换"""
        if not event.mimeData().hasFormat(_MIME_CARD):
            event.ignore()
            return
        try:
            from_row = int(bytes(event.mimeData().data(_MIME_CARD)).decode())
        except ValueError:
            event.ignore()
            return
        if not (0 <= from_row < self.count()):
            event.ignore()
            return
        # 目标行 = 光标处项之前；光标在空白处 → 移到末尾
        index = self.indexAt(event.pos())
        to_row = index.row() if index.isValid() else self.count()
        if not self._move_item(from_row, to_row):
            event.ignore()
            return
        event.setDropAction(Qt.MoveAction)
        event.accept()

    def _move_item(self, from_row: int, to_row: int) -> bool:
        """把 from_row 卡片搬到 to_row（插到原 to_row 项之前），其余顺延

        返回是否发生实际移动。被移动行的卡片控件按数据重建
        （takeItem 会触发视图对该行 editor 的异步销毁，重绑旧控件不可靠），
        其余行不受影响。
        """
        if not (0 <= from_row < self.count()):
            return False
        to_row = max(0, min(to_row, self.count()))
        if to_row in (from_row, from_row + 1):
            return False  # 落回原位（原地或原位之后），不算移动
        item = self.item(from_row)
        if item is None:
            return False
        data = item.data(self.CARD_DATA_ROLE)
        taken = self.takeItem(from_row)
        insert_row = to_row - 1 if to_row > from_row else to_row
        self.insertItem(insert_row, taken)
        if data:
            # 按数据重建被移动行的卡片控件：推迟到事件循环下一拍，
            # 确保在旧控件 deleteLater 销毁完成之后执行，避免时序冲突
            target = taken
            QTimer.singleShot(
                0, lambda: self._rebuild_card_at_item(target, data))
        self.setCurrentItem(taken)
        self.cardReordered.emit()
        return True

    def _rebuild_card_at_item(self, item, data: dict):
        """在指定条目上按数据重建卡片控件（条目仍存在时）"""
        if self.row(item) < 0:
            return  # 条目已被移除（如重建前又删除/清空），放弃重建
        card = EnchantedItemCard(data["item_name"], data["enchants"])
        self.setItemWidget(item, card)
