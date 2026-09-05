# -*- coding: utf-8 -*-
"""离屏冒烟测试：验证冲突禁用/恢复逻辑（不需要真实鼠标拖拽，直接调槽函数）"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

app = QApplication(sys.argv)

from Utils.choose_items import ChooseItemsWindow


def find_item_flags(win, enchant_id):
    """在下方分类列表中找到指定附魔项，返回 (找到, 是否启用)"""
    for lw in win.category_widgets.values():
        for i in range(lw.count()):
            item = lw.item(i)
            if item.data(Qt.UserRole) == enchant_id:
                enabled = bool(item.flags() & Qt.ItemIsEnabled)
                return True, enabled
    return False, False


def simulate_remove(win, enchant_id):
    """模拟真实拖出删除：先从已选列表移除条目（对应 DropListWidget 内部 takeItem），再触发 removed 信号"""
    for i in range(win.chosenEnchantmentList.count()):
        if win.chosenEnchantmentList.item(i).data(Qt.UserRole) == enchant_id:
            win.chosenEnchantmentList.takeItem(i)
            break
    win.on_enchant_removed(enchant_id)


win = ChooseItemsWindow()

# 前置：确认当前物品类型为附魔书，两目标附魔都在列表中
ok_fortune, en_fortune = find_item_flags(win, "fortune")
ok_silk, en_silk = find_item_flags(win, "silk_touch")
assert ok_fortune and ok_silk, "列表中未找到时运/精准采集"
assert en_fortune and en_silk, "初始状态应全部可用"
print("1. 初始状态：时运/精准采集均可用 ✓")

# 模拟拖入时运（等级 3）
win.on_enchant_dropped("fortune", 3)
ok_silk, en_silk = find_item_flags(win, "silk_touch")
assert not en_silk, "拖入时运后精准采集应被禁用"
print("2. 拖入时运后：精准采集被禁用 ✓")

# 检查 tooltip
for lw in win.category_widgets.values():
    for i in range(lw.count()):
        it = lw.item(i)
        if it.data(Qt.UserRole) == "silk_touch":
            assert "时运" in it.toolTip(), "tooltip 应提示冲突来源，实际: " + it.toolTip()
print("3. tooltip 提示冲突来源 ✓")

# 模拟拖入与其无冲突的锋利
win.on_enchant_dropped("sharpness", 1)
ok_silk, en_silk = find_item_flags(win, "silk_touch")
assert not en_silk, "锋利与时运无冲突，精准采集应保持禁用"
# 锋利应禁用亡灵杀手/节肢杀手
ok_smite, en_smite = find_item_flags(win, "smite")
assert not en_smite, "拖入锋利后亡灵杀手应被禁用"
print("4. 多个已选附魔的冲突并集生效（时运→精准采集，锋利→亡灵杀手）✓")

# 模拟拖出删除时运（takeItem + removed 槽，与真实拖出流程一致）
simulate_remove(win, "fortune")
ok_silk, en_silk = find_item_flags(win, "silk_touch")
assert en_silk, "删除时运后精准采集应恢复可用"
ok_smite, en_smite = find_item_flags(win, "smite")
assert not en_smite, "锋利还在，亡灵杀手应保持禁用"
print("5. 删除时运后：精准采集恢复，亡灵杀手仍禁用 ✓")

# 模拟拖出删除锋利
simulate_remove(win, "sharpness")
ok_smite, en_smite = find_item_flags(win, "smite")
assert en_smite, "删除锋利后亡灵杀手应恢复可用"
print("6. 删除锋利后：亡灵杀手恢复 ✓")

# 重复拖入（已存在时取较高级分支）不破坏状态
win.on_enchant_dropped("protection", 2)
ok_fire, en_fire = find_item_flags(win, "fire_protection")
assert not en_fire, "拖入保护后火焰保护应禁用"
win.on_enchant_dropped("protection", 3)  # 重复拖入同附魔
ok_fire, en_fire = find_item_flags(win, "fire_protection")
assert not en_fire, "重复拖入后状态应保持"
print("7. 重复拖入同附魔（取较高等级分支）状态正常 ✓")

# 切换物品类型重建列表后，禁用状态应保持/重算（保护仍已选；力量是弓专属不在剑分类，改用亡灵杀手验证）
win.update_tabs_and_lists("剑")
ok_smite, en_smite = find_item_flags(win, "smite")
assert ok_smite, "剑分类列表中应存在亡灵杀手"
assert en_smite, "锋利已删除，重建列表后亡灵杀手应恢复可用"
ok_fire, en_fire = find_item_flags(win, "fire_protection")
if ok_fire:
    assert not en_fire, "保护仍已选，火焰保护应保持禁用"
print("8. 重建列表后禁用状态正确重算 ✓")

# 附加：验证修复后的 density×breach 互斥（重锤专属，需在附魔书分类下）
win.update_tabs_and_lists("附魔书")
win.on_enchant_dropped("density", 1)
ok_breach, en_breach = find_item_flags(win, "breach")
assert not en_breach, "拖入致密后破甲应被禁用"
simulate_remove(win, "density")
ok_breach, en_breach = find_item_flags(win, "breach")
assert en_breach, "删除致密后破甲应恢复可用"
print("9. 致密×破甲互斥禁用/恢复 ✓")

print("\n全部冒烟测试通过")
