# -*- coding: utf-8 -*-
"""冒烟测试：验证「清空」按钮（clearEnchantList）功能
1. 点击清空按钮 → 已选列表清空
2. 清空后冲突禁用状态联动恢复（下方被禁用的冲突附魔重新可选）
3. 空列表点击清空不崩溃、无副作用
4. 清空不误删下方分类列表内容，等级记录不受影响
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

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


def category_item_count(win):
    """统计下方所有分类列表的总条目数"""
    return sum(lw.count() for lw in win.category_widgets.values())


# ---------- 1. 点击清空按钮 → 已选列表清空 ----------
win.on_enchant_dropped("fortune", 3)
win.on_enchant_dropped("sharpness", 5)
win.on_enchant_dropped("power", 4)
assert len(chosen_ids(win)) == 3, "前置：应已拖入 3 个附魔"
win.clearEnchantList.click()  # 直接模拟点击清空按钮
assert chosen_ids(win) == [], "点击清空后已选列表应为空"
print("1. 点击清空按钮：已选列表清空 ✓")

# ---------- 2. 清空后冲突禁用状态联动恢复 ----------
# 重新拖入时运（与精准采集冲突），下方"精准采集"应被禁用
win.on_enchant_dropped("fortune", 2)
ok_silk, en_silk = find_item_flags(win, "silk_touch")
assert ok_silk and not en_silk, "前置：时运已选时精准采集应被禁用"
win.clearEnchantList.click()
assert chosen_ids(win) == [], "清空后列表应为空"
ok_silk, en_silk = find_item_flags(win, "silk_touch")
assert ok_silk and en_silk, "清空后精准采集应恢复可用"
print("2. 清空后冲突禁用状态恢复联动 ✓")

# ---------- 3. 空列表点击清空不崩溃、无副作用 ----------
removed_events.clear()
assert win.chosenEnchantmentList.count() == 0, "前置：已选列表应为空"
win.clearEnchantList.click()  # 空列表点击
app.processEvents()
assert chosen_ids(win) == [], "空列表清空不应产生条目"
assert removed_events == [], "清空路径不应发射 removed 信号（仅按钮清空生效）"
print("3. 空列表点击清空：不崩溃、无副作用 ✓")

# ---------- 4. 清空不误删下方分类列表，等级记录不受影响 ----------
before_count = category_item_count(win)
assert before_count > 0, "前置：下方分类列表应有条目"
levels_snapshot = dict(win.enchant_levels)  # 等级字典快照
win.on_enchant_dropped("fortune", 3)  # 拖入等级 3（该附魔最大等级）
win.clearEnchantList.click()
after_count = category_item_count(win)
assert after_count == before_count, "清空不应影响下方分类列表"
assert win.enchant_levels == levels_snapshot, "清空不应重置等级记录字典"
print("4. 清空不影响下方列表与等级记录 ✓")

# ---------- 5. 连续多次点击清空（重复点击幂等） ----------
win.on_enchant_dropped("silk_touch", 1)
win.clearEnchantList.click()
win.clearEnchantList.click()
win.clearEnchantList.click()
app.processEvents()
assert chosen_ids(win) == [], "重复清空后列表仍应为空"
print("5. 重复点击清空：幂等安全 ✓")

print("\n全部冒烟测试通过")
