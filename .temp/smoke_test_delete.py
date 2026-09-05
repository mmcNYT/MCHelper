# -*- coding: utf-8 -*-
"""冒烟测试：验证 chosenEnchantmentList 的三种删除方式（Del 键 / × 图标 / 拖出）
均正确移除条目并触发 removed 信号，且冲突禁用状态联动正确"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication, QListWidgetItem
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest

app = QApplication(sys.argv)

from Utils.choose_items import ChooseItemsWindow

win = ChooseItemsWindow()
removed_events = []
win.chosenEnchantmentList.removed.connect(lambda eid: removed_events.append(eid))


def chosen_ids(win):
    return [win.chosenEnchantmentList.item(i).data(Qt.UserRole)
            for i in range(win.chosenEnchantmentList.count())]


def find_item_flags(win, enchant_id):
    """在下方分类列表中找到指定附魔项，返回 (找到, 是否启用)"""
    for lw in win.category_widgets.values():
        for i in range(lw.count()):
            item = lw.item(i)
            if item.data(Qt.UserRole) == enchant_id:
                enabled = bool(item.flags() & Qt.ItemIsEnabled)
                return True, enabled
    return False, False


# ---------- 1. Del 键删除 ----------
win.on_enchant_dropped("fortune", 3)
win.chosenEnchantmentList.setCurrentRow(0)
QTest.keyClick(win.chosenEnchantmentList, Qt.Key_Delete)
assert "fortune" not in chosen_ids(win), "Del 键应删除选中项"
assert removed_events == ["fortune"], f"removed 信号应收 fortune，实际: {removed_events}"
print("1. Del 键删除：条目移除 + removed 信号发射 ✓")

# ---------- 2. Del 键在空列表上不崩溃 ----------
QTest.keyClick(win.chosenEnchantmentList, Qt.Key_Delete)
assert chosen_ids(win) == [], "空列表 Del 不应有副作用"
print("2. Del 键空列表边界 ✓")

# ---------- 3. Backspace 键同样删除 ----------
removed_events.clear()
win.on_enchant_dropped("sharpness", 5)
win.chosenEnchantmentList.setCurrentRow(0)
QTest.keyClick(win.chosenEnchantmentList, Qt.Key_Backspace)
assert "sharpness" not in chosen_ids(win), "Backspace 键应删除选中项"
assert removed_events == ["sharpness"], f"实际: {removed_events}"
print("3. Backspace 键删除 ✓")

# ---------- 4. × 图标点击删除（模拟鼠标点击图标区域） ----------
removed_events.clear()
win.on_enchant_dropped("fortune", 3)      # 拖入时运
win.on_enchant_dropped("sharpness", 1)    # 拖入锋利
assert len(chosen_ids(win)) == 2

lw = win.chosenEnchantmentList
item0 = lw.item(0)  # fortune
# 计算第 0 行 × 图标中心点
from Utils.drop_list_widget import CloseButtonDelegate
opt = QStyleOptionViewItem() if False else None
rect = lw.visualItemRect(item0)
icon_rect = lw._close_delegate._icon_rect(type("Opt", (), {"rect": rect})())
center = icon_rect.center()
# 先确认命中检测逻辑正确
assert lw._hit_close_icon(item0, center), "图标中心点应命中"
assert not lw._hit_close_icon(item0, QPoint(rect.left() + 5, rect.center().y())), "行左侧不应命中"
# 模拟点击
QTest.mouseClick(lw.viewport(), Qt.LeftButton, Qt.NoModifier, center)
app.processEvents()
assert "fortune" not in chosen_ids(win), "× 点击应删除对应项"
assert removed_events == ["fortune"], f"实际: {removed_events}"
print("4. × 图标点击删除 ✓")

# ---------- 5. × 点击后冲突禁用恢复（与 ChooseItemsWindow 联动） ----------
removed_events.clear()
win.on_enchant_dropped("fortune", 2)  # 重新拖入时运（当前 chosen 里只有锋利）
ok_silk, en_silk = find_item_flags(win, "silk_touch")
assert not en_silk, "前置：时运已选时精准采集应被禁用"
# 逐个 × 删除全部已选项
while lw.count() > 0:
    item0 = lw.item(0)
    rect = lw.visualItemRect(item0)
    icon_rect = lw._close_delegate._icon_rect(type("Opt", (), {"rect": rect})())
    QTest.mouseClick(lw.viewport(), Qt.LeftButton, Qt.NoModifier, icon_rect.center())
    app.processEvents()
assert chosen_ids(win) == [], "全部删除后已选列表应为空"
ok_silk, en_silk = find_item_flags(win, "silk_touch")
assert en_silk, "全部删除后精准采集应恢复可用"
print("5. × 删除后冲突禁用恢复联动 ✓")

# ---------- 6. 悬停高亮状态切换 ----------
removed_events.clear()
win.on_enchant_dropped("fortune", 2)
item0 = lw.item(0)
rect = lw.visualItemRect(item0)
# 移动到图标位置 → hover 行 0（offscreen 平台不支持 QTest.mouseMove 触发 hover，
# 直接调用控件的处理方法验证逻辑；真实平台由 Qt 事件循环自动触发）
lw._update_hover_row(rect.center())
assert lw._close_delegate._hover_row == 0, "悬停行应为 0"
# 移走（空白区域）→ hover 清除
lw._update_hover_row(QPoint(5, rect.bottom() + 50))
assert lw._close_delegate._hover_row == -1, "移开后悬停行应清除"
# leaveEvent 同样清除（模拟鼠标离开控件）
lw._close_delegate.set_hover_row(0)  # 先置回悬停
from PySide6.QtCore import QEvent
lw.leaveEvent(QEvent(QEvent.Leave))
assert lw._close_delegate._hover_row == -1, "leaveEvent 应清除悬停高亮"
print("6. 悬停高亮切换 ✓")

# ---------- 7. 悬停期间 Del 键删除不破坏 hover 状态 ----------
win.chosenEnchantmentList.setCurrentRow(0)
QTest.keyClick(win.chosenEnchantmentList, Qt.Key_Delete)
assert chosen_ids(win) == []
# hover 行 0 已无内容，再移动也不崩溃
QTest.mouseMove(lw.viewport(), rect.center())
app.processEvents()
print("7. 删除后悬停状态安全 ✓")

# ---------- 8. 无效 ID（UserRole 为 None）的项 Del 不崩溃 ----------
removed_events.clear()  # 清除第 6/7 步遗留的信号记录
none_item = QListWidgetItem("异常项")
lw.addItem(none_item)  # UserRole 为空
lw.setCurrentRow(0)
QTest.keyClick(lw, Qt.Key_Delete)
assert lw.count() == 0, "UserRole 为 None 的项也应被移除（不发射信号）"
assert removed_events == [], "UserRole 为 None 不应发射 removed 信号"
print("8. 异常项（无 ID）删除安全 ✓")

# ---------- 9. 拖拽删除已移除：自身项不可拖拽 ----------
assert not lw.dragEnabled(), "DropListWidget 不应再开启 dragEnabled"
removed_events.clear()
win.on_enchant_dropped("fortune", 4)
assert chosen_ids(win) == ["fortune"]
# 模拟按住左键拖动（无真实 QDrag，验证不会触发删除路径）
item0 = lw.item(0)
QTest.mousePress(lw.viewport(), Qt.LeftButton, Qt.NoModifier, lw.visualItemRect(item0).center())
QTest.mouseMove(lw.viewport(), lw.visualItemRect(item0).center() + QPoint(50, 50))
QTest.mouseRelease(lw.viewport(), Qt.LeftButton, Qt.NoModifier, lw.visualItemRect(item0).center() + QPoint(50, 50))
app.processEvents()
assert chosen_ids(win) == ["fortune"], "拖动自身项不应删除"
assert removed_events == [], "拖动自身项不应发射 removed 信号"
# dropEvent 自拖分支已删：模拟自身 source 的 drop 不应误删
print("9. 拖拽删除已移除：拖动/释放不删除条目 ✓")

print("\n全部冒烟测试通过")
