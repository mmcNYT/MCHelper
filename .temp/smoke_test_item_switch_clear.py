# -*- coding: utf-8 -*-
"""冒烟测试：物品切换时清空已选附魔列表
1. 拖入附魔后切换物品 → chosenEnchantmentList 清空
2. 清空后冲突禁用恢复（被禁用的冲突附魔重新可选）
3. 连续切换多次 → 仍为空（幂等）
4. 切换到不兼容物品后拖入新附魔 → 数据正确（不受旧状态污染）
5. 端到端：切换物品后确认 → selected_data.enchants 为空
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

app = QApplication(sys.argv)

from Utils.choose_items import ChooseItemsWindow
from Utils.enchant_data_manager import DataManager

win = ChooseItemsWindow()
win.show()
app.processEvents()

dm = DataManager()

# ---------- 1. 拖入附魔 → 切换物品 → 列表清空 ----------
win.on_enchant_dropped("fortune", 3)  # 时运（附魔书/工具兼容）
assert win.chosenEnchantmentList.count() == 1, "拖入后应有 1 条"
# 切换物品（触发 currentIndexChanged → on_item_type_changed）
win.itemsList.setCurrentIndex(1)  # 附魔书 → 剑
app.processEvents()
assert win.chosenEnchantmentList.count() == 0, f"切换物品后已选列表应清空，实际 {win.chosenEnchantmentList.count()} 条"
print("1. 拖入附魔后切换物品 → 已选列表清空 ✓")

# ---------- 2. 清空后冲突禁用恢复 ----------
# 时运与精准采集冲突：拖入时运后精准采集应被禁用；切换物品清空后应恢复
win2 = ChooseItemsWindow()
win2.show()
app.processEvents()
win2.on_enchant_dropped("fortune", 3)
# 找到精准采集项确认被禁用
silktouch_item = None
for lw in win2.category_widgets.values():
    for i in range(lw.count()):
        it = lw.item(i)
        if it.data(Qt.UserRole) == "silk_touch":
            silktouch_item = it
enabled_before = bool(silktouch_item.flags() & Qt.ItemIsEnabled)
assert enabled_before is False, "拖入时运后精准采集应被禁用"
# 切换物品触发清空
win2.itemsList.setCurrentIndex(2)  # 附魔书 → 斧
app.processEvents()
# 重新查找（update_tabs_and_lists 重建了列表项）
silktouch_item2 = None
for lw in win2.category_widgets.values():
    for i in range(lw.count()):
        it = lw.item(i)
        if it.data(Qt.UserRole) == "silk_touch":
            silktouch_item2 = it
assert silktouch_item2 is not None
assert bool(silktouch_item2.flags() & Qt.ItemIsEnabled), "切换清空后精准采集应恢复可选"
print("2. 切换清空后冲突禁用恢复（时运→精准采集重新可选） ✓")

# ---------- 3. 连续切换多次 → 仍为空（幂等安全） ----------
for idx in (3, 4, 5):
    win2.itemsList.setCurrentIndex(idx)
    app.processEvents()
    assert win2.chosenEnchantmentList.count() == 0, f"连续切换后应保持为空（index={idx}）"
print("3. 连续切换多次列表保持为空 ✓")

# ---------- 4. 切换到不兼容物品后拖入新附魔 → 数据正确 ----------
# 剑不兼容时运：切换到剑后拖入锋利，应正常入列且等级正确
win3 = ChooseItemsWindow()
win3.show()
app.processEvents()
win3.on_enchant_dropped("fortune", 3)
win3.itemsList.setCurrentIndex(1)  # → 剑（时运被清空）
win3.on_enchant_dropped("sharpness", 5)  # 锋利（剑兼容）
assert win3.chosenEnchantmentList.count() == 1, "切换后拖入新附魔应正常入列"
item0 = win3.chosenEnchantmentList.item(0)
assert item0.data(Qt.UserRole) == "sharpness"
assert item0.data(Qt.UserRole + 1) == 5
print("4. 切换到不兼容物品后拖入新附魔数据正确 ✓")

# ---------- 5. 端到端：切换物品后确认 → 数据包附魔为空 ----------
win3.itemsList.setCurrentIndex(7)  # 剑 → 弓（锋利被清空）
win3.on_confirm_clicked()
assert win3.selected_data is not None
assert win3.selected_data["item_name"] == "弓"
assert win3.selected_data["enchants"] == [], f"切换物品后确认，附魔应为空，实际 {win3.selected_data['enchants']}"
print("5. 端到端：切换物品后确认 → 数据包 item_name=弓、enchants=[] ✓")

win.close()
win2.close()
win3.close()
print("\n全部冒烟测试通过")
