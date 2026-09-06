# -*- coding: utf-8 -*-
"""冒烟测试：物品卡片列表四项交互
1. 清空物品按钮 → 清空全部卡片 + cardsCleared 信号携带附魔 ID 并集
2. Del 键删除当前选中卡片 + cardRemoved 信号
3. 再次点击已选中卡片取消选中（点击未选中卡片正常选中、拖动不误触发取消）
4. 拖动卡片交换位置（信号发射 + 卡片控件随行 + 顺序正确）
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPoint, QMimeData, QByteArray

app = QApplication(sys.argv)

from Tools.tool_EnchantCaculator import EnchantCalculatorWidget
from Utils.card_list_widget import CardListWidget
from Utils.enchanted_item_card import EnchantedItemCard

# ---------- 会话隔离：移走用户真实卡片会话，防止 _restore_session 污染初始列表 ----------
_session_path = EnchantCalculatorWidget()._session_path()
_saved_session = open(_session_path, "r", encoding="utf-8").read() \
    if os.path.exists(_session_path) else None
if os.path.exists(_session_path):
    os.remove(_session_path)


def _restore_session_file():
    """测试结束后恢复用户真实会话文件（移走前的内容）"""
    if _saved_session is not None:
        with open(_session_path, "w", encoding="utf-8") as f:
            f.write(_saved_session)


widget = EnchantCalculatorWidget()
widget.resize(658, 518)
widget.show()
app.processEvents()
lst = widget.chosenItemList
assert isinstance(lst, CardListWidget), "chosenItemList 应为增强型 CardListWidget"

# 添加三张卡片：剑(锋利)、弓(力量)、镐(效率+时运)
widget.add_item_card({"item_name": "剑", "enchants": [{"id": "sharpness", "name": "锋利", "level": 5}]})
widget.add_item_card({"item_name": "弓", "enchants": [{"id": "power", "name": "力量", "level": 5}]})
widget.add_item_card({"item_name": "镐", "enchants": [{"id": "efficiency", "name": "效率", "level": 5},
                                                      {"id": "fortune", "name": "时运", "level": 3}]})
app.processEvents()
assert lst.count() == 3


def item_ids(row):
    return lst.card_enchant_ids(lst.item(row))


# ---------- 1. 清空物品按钮 ----------
removed_log = []
cleared_log = []
lst.cardRemoved.connect(lambda ids: removed_log.append(list(ids)))
lst.cardsCleared.connect(lambda ids: cleared_log.append(list(ids)))

widget.clearItems.click()
app.processEvents()
assert lst.count() == 0, "清空物品后卡片列表应为空"
assert cleared_log == [["sharpness", "power", "efficiency", "fortune"]], \
    f"cardsCleared 应携带全部附魔 ID 并集，实际 {cleared_log}"
# 空列表再点清空：无副作用、不崩溃
widget.clearItems.click()
app.processEvents()
assert cleared_log == [["sharpness", "power", "efficiency", "fortune"]], "空列表点击清空不应再发信号"
print("1. 清空物品按钮：全部卡片清空 + ID 并集信号 + 空表幂等 ✓")

# ---------- 2. Del 键删除 ----------
widget.add_item_card({"item_name": "剑", "enchants": [{"id": "sharpness", "name": "锋利", "level": 5}]})
widget.add_item_card({"item_name": "弓", "enchants": [{"id": "power", "name": "力量", "level": 5}]})
widget.add_item_card({"item_name": "镐", "enchants": [{"id": "efficiency", "name": "效率", "level": 5}]})
app.processEvents()
assert lst.count() == 3
# 选中第二张（弓）后按 Del
lst.setCurrentRow(1)
from PySide6.QtGui import QKeyEvent
from PySide6.QtCore import QEvent
del_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier)
app.sendEvent(lst, del_event)
app.processEvents()
assert lst.count() == 2, "Del 后应剩 2 张卡片"
assert removed_log == [["power"]], f"cardRemoved 应携带被删卡片附魔 ID，实际 {removed_log}"
assert item_ids(0) == ["sharpness"] and item_ids(1) == ["efficiency"], "剩余卡片顺序应正确"
assert lst.itemWidget(lst.item(0)) is not None and lst.itemWidget(lst.item(1)) is not None, \
    "剩余卡片控件应完好"
# Backspace 同样删除
bs_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Backspace, Qt.NoModifier)
lst.setCurrentRow(0)
app.sendEvent(lst, bs_event)
app.processEvents()
assert lst.count() == 1 and removed_log == [["power"], ["sharpness"]], "Backspace 应同样删除"
# 无选中（显式取消）按 Del：不崩溃且不误删
lst.setCurrentRow(-1)
app.sendEvent(lst, del_event)
app.processEvents()
assert lst.count() == 1, "无选中按 Del 不应删除任何卡片"
# 真正空列表按 Del：不崩溃
lst.clear_cards()
app.processEvents()
app.sendEvent(lst, del_event)
app.processEvents()
assert lst.count() == 0
print("2. Del/Backspace 键删除选中卡片 + 信号携带 ID ✓")

# ---------- 3. 再次点击取消选中 ----------
# 重建三张卡片
widget.add_item_card({"item_name": "剑", "enchants": [{"id": "sharpness", "name": "锋利", "level": 5}]})
widget.add_item_card({"item_name": "弓", "enchants": [{"id": "power", "name": "力量", "level": 5}]})
widget.add_item_card({"item_name": "镐", "enchants": [{"id": "efficiency", "name": "效率", "level": 5}]})
app.processEvents()
assert lst.count() == 3
r1 = lst.visualItemRect(lst.item(0))
r2 = lst.visualItemRect(lst.item(1))
center1 = r1.center()
center2 = r2.center()
# 3a. 点击未选中卡片 → 正常选中
from PySide6.QtGui import QMouseEvent
press = QMouseEvent(QEvent.MouseButtonPress, center1, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
release = QMouseEvent(QEvent.MouseButtonRelease, center1, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
app.sendEvent(lst.viewport(), press)
app.sendEvent(lst.viewport(), release)
app.processEvents()
assert lst.currentItem() is lst.item(0), "点击卡片 0 应选中"
# 3b. 再次点击同一张 → 取消选中
app.sendEvent(lst.viewport(), press)
app.sendEvent(lst.viewport(), release)
app.processEvents()
assert lst.currentItem() is None and not lst.selectedItems(), "再次点击已选中卡片应取消选中"
# 3c. 点击另一张 → 切换选中（取消逻辑不影响正常切换）
app.sendEvent(lst.viewport(), press)
app.sendEvent(lst.viewport(), release)
app.sendEvent(lst.viewport(),
              QMouseEvent(QEvent.MouseButtonPress, center2, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
app.sendEvent(lst.viewport(),
              QMouseEvent(QEvent.MouseButtonRelease, center2, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
app.processEvents()
assert lst.currentItem() is lst.item(1), "点击另一张应切换选中"
print("3. 再次点击取消选中 / 点击未选中正常选中 ✓")

# ---------- 4. 拖动卡片交换位置 ----------
reordered = [0]
def _on_reordered():
    reordered[0] += 1
lst.cardReordered.connect(_on_reordered)
# 程序化模拟拖放：直接构造 MIME（与 _start_reorder_drag 同格式），绕过真实鼠标拖拽
mime = QMimeData()
mime.setData("application/x-card-reorder", b"1")  # 拖起第 1 张（弓）
from PySide6.QtGui import QDragMoveEvent, QDropEvent, QDragEnterEvent
pos_drop = lst.visualItemRect(lst.item(0)).center()  # 丢到第 0 张（剑）上
enter = QDragEnterEvent(pos_drop, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
app.sendEvent(lst.viewport(), enter)
assert enter.isAccepted(), "卡片拖动进入应被接受"
drop = QDropEvent(pos_drop, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
app.sendEvent(lst.viewport(), drop)
app.processEvents()
assert reordered[0] == 1, "拖动成功应发射 cardReordered"
assert item_ids(0) == ["power"] and item_ids(1) == ["sharpness"] and item_ids(2) == ["efficiency"], \
    f"拖动后顺序应为 弓/剑/镐，实际 {[item_ids(i) for i in range(3)]}"
assert lst.itemWidget(lst.item(0)) is not None, "拖动后卡片控件应重新绑定（itemWidget 不丢失）"
assert isinstance(lst.itemWidget(lst.item(0)), EnchantedItemCard), "卡片控件类型应保持"
# 移到末尾（空白处 drop）：indexAt 无效 → append
# （真实拖放流程总是 enter→drop 连续投递，测试同样补发 enter）
mime2 = QMimeData()
mime2.setData("application/x-card-reorder", b"0")  # 拖起第 0 张（弓）
tail = QPoint(lst.viewport().width() - 4, lst.viewport().height() - 4)
app.sendEvent(lst.viewport(),
              QDragEnterEvent(tail, Qt.MoveAction, mime2, Qt.LeftButton, Qt.NoModifier))
drop2 = QDropEvent(tail, Qt.MoveAction, mime2, Qt.LeftButton, Qt.NoModifier)
app.sendEvent(lst.viewport(), drop2)
app.processEvents()
assert item_ids(2) == ["power"], "拖到空白处应移到末尾"
assert reordered[0] == 2
# 拖回原位：不发射信号
before = reordered[0]
mime3 = QMimeData()
mime3.setData("application/x-card-reorder", b"2")
same_pos = lst.visualItemRect(lst.item(2)).center()
app.sendEvent(lst.viewport(),
              QDragEnterEvent(same_pos, Qt.MoveAction, mime3, Qt.LeftButton, Qt.NoModifier))
drop3 = QDropEvent(same_pos, Qt.MoveAction, mime3, Qt.LeftButton, Qt.NoModifier)
app.sendEvent(lst.viewport(), drop3)
app.processEvents()
assert reordered[0] == before, "落回原位不应发射 cardReordered"
print("4. 拖动交换位置：顺序正确 + 控件随行 + 移到末尾 + 原位不发射 ✓")

# ---------- 5. 拖动快照透明 + 视口淡灰背景 ----------
from PySide6.QtGui import QImage, QColor

# 5a. 透明快照：四角 alpha=0（无灰底），内容不透明像素充足（卡片可见）
snap = CardListWidget._transparent_snapshot(lst.itemWidget(lst.item(0)))
snap_img = snap.toImage().convertToFormat(QImage.Format_ARGB32)
corner_alphas = [snap_img.pixelColor(x, y).alpha()
                 for x, y in ((0, 0), (snap_img.width() - 1, 0),
                              (0, snap_img.height() - 1), (snap_img.width() - 1, snap_img.height() - 1))]
assert all(a == 0 for a in corner_alphas), f"快照四角应完全透明，实际 {corner_alphas}"
opaque = sum(1 for y in range(snap_img.height()) for x in range(snap_img.width())
             if snap_img.pixelColor(x, y).alpha() > 0)
total = snap_img.width() * snap_img.height()
assert opaque > total * 0.3, f"快照内容像素应充足（实际不透明 {opaque}/{total}）"
# 与旧 grab() 对比：grab 四角为不透明灰底
g_img = lst.itemWidget(lst.item(0)).grab().toImage().convertToFormat(QImage.Format_ARGB32)
g_corner = g_img.pixelColor(0, 0).alpha()
assert g_corner == 255 and corner_alphas[0] == 0, "grab() 应带不透明底而新快照应透明"
print(f"5a. 拖动快照透明：四角 alpha 全 0，内容 {opaque}/{total} 像素可见 ✓")

# 5b. 视口淡灰背景：实测像素为 #ECECEC (236,236,236)
lst.clear_cards()
app.processEvents()
vp_img = lst.viewport().grab().toImage().convertToFormat(QImage.Format_ARGB32)
c5 = vp_img.pixelColor(2, 2)
assert (c5.red(), c5.green(), c5.blue()) == (236, 236, 236), \
    f"视口背景应为 #ECECEC，实际 ({c5.red()}, {c5.green()}, {c5.blue()})"
print("5b. 视口淡灰背景 #ECECEC 实测生效 ✓")

widget.close()
_restore_session_file()
print("\n全部冒烟测试通过")
