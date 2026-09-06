# -*- coding: utf-8 -*-
"""冒烟测试：物品类型选择约束 + 清空联动步骤图

1. ChooseItemsWindow 白名单过滤：allowed_item_names 移除下拉框其余项
2. allowed_item_types：无卡片 → None（全量）；有剑卡片 → {附魔书, 剑}；
   只有书卡片 → None；理论不可达的多类型 → 空集
3. do_choose_items 端到端：mock 窗口类，验证按当前卡片传约束、
   确认数据入卡片列表
4. 清空按钮：清卡片 + 决策清零 + 步骤图恢复占位；空状态清空幂等；
   清空后允许重新选择任意类型
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import Qt

app = QApplication(sys.argv)

import Tools.tool_EnchantCaculator as tec
from Utils.choose_items import ChooseItemsWindow
from Utils.anvil_steps_tree import AnvilStepsTree

# ========== 1. 白名单过滤：下拉框只留白名单类型 ==========
win = ChooseItemsWindow(allowed_item_names={"附魔书", "剑"})
texts = [win.itemsList.itemText(i) for i in range(win.itemsList.count())]
assert texts == ["附魔书", "剑"], f"下拉框应只剩 附魔书/剑，实际 {texts}"
assert win.itemsList.currentText() == "附魔书", "当前项应保持第 0 项"
win.close()
print("1. 白名单过滤：下拉框只留 附魔书+剑 ✓")

# 全量（None）不过滤
win = ChooseItemsWindow()
assert win.itemsList.count() == 16, "无白名单时应有全部 16 个类型"
win.close()
print("1b. 无白名单：全部类型可选 ✓")

# ========== 2. allowed_item_types 逻辑 ==========
w = tec.EnchantCalculatorWidget()
assert w.allowed_item_types() is None, "无卡片应返回 None（全量）"
w.chosenItemList.add_card({"item_name": "附魔书", "enchants": []})
assert w.allowed_item_types() is None, "只有书卡片仍应全量"
w.chosenItemList.add_card({"item_name": "剑", "enchants": []})
assert w.allowed_item_types() == {"附魔书", "剑"}, \
    f"有剑卡片应只允许 附魔书/剑，实际 {w.allowed_item_types()}"
# 理论不可达：手工构造双类型状态验证双保险
w.chosenItemList.add_card({"item_name": "镐", "enchants": []})
assert w.allowed_item_types() == set(), "多类型应返回空集兜底"
w.close()
print("2. allowed_item_types 四种状态正确 ✓")

# ========== 3. do_choose_items 端到端（mock 窗口类） ==========
captured = {}

class FakeChooseWin:
    selected_data = None

    def __init__(self, parent=None, allowed_item_names=None):
        captured["allowed"] = allowed_item_names

    def exec(self):
        return QDialog.Accepted

orig_choose = tec.ChooseItemsWindow
tec.ChooseItemsWindow = FakeChooseWin
try:
    w = tec.EnchantCalculatorWidget()
    # 无卡片：约束为 None
    w.do_choose_items()
    assert captured["allowed"] is None
    # 添加剑卡片：约束变为 {附魔书, 剑}
    FakeChooseWin.selected_data = {"item_name": "剑", "enchants": []}
    w.do_choose_items()
    assert w.chosenItemList.count() == 1
    # 再开窗口：此时已有剑卡片 → 约束收窄
    w.do_choose_items()
    assert captured["allowed"] == {"附魔书", "剑"}, captured["allowed"]
    # 清空后重新打开：恢复全量
    w.do_clear_cards()
    w.do_choose_items()
    assert captured["allowed"] is None, "清空后应恢复全量"
    w.close()
finally:
    tec.ChooseItemsWindow = orig_choose
print("3. do_choose_items 端到端：约束随卡片实时计算 ✓")

# ========== 4. 清空按钮联动步骤图 ==========
w2 = tec.EnchantCalculatorWidget()
w2.resize(658, 518)
w2.show()
app.processEvents()
# 构造有方案的状态：加剑+书卡片，走真实计算（无冲突，不弹窗）
w2.chosenItemList.add_card({"item_name": "剑", "enchants": []})
w2.chosenItemList.add_card({"item_name": "附魔书",
                            "enchants": [{"id": "sharpness",
                                          "name": "锋利", "level": 5}]})
app.processEvents()
w2.do_start_calculate()
app.processEvents()
fb = w2.realSteps.final_box()
assert fb is not None and fb.anvil_item.name == "剑", "前置：应有计算结果"
assert len(w2.realSteps.boxes()) == 3, "前置：1 物品+1 步 = 3 框"
# 点击清空按钮 → 卡片清空 + 步骤图恢复占位
w2.clearItems.click()
app.processEvents()
assert w2.chosenItemList.count() == 0, "清空后卡片应清空"
assert w2.realSteps.is_placeholder(), "清空后步骤图应恢复占位提示"
assert "开始计算" in w2.realSteps.placeholder_text
assert w2.conflict_choices == {}, "清空后决策应清零"
# 空状态再次点击清空：幂等无异常
w2.clearItems.click()
app.processEvents()
assert w2.realSteps.is_placeholder()
# 清空后允许重新选择任意类型：空状态约束全量，选弓后约束允许弓
assert w2.allowed_item_types() is None, "清空后（空状态）应恢复全量"
w2.chosenItemList.add_card({"item_name": "弓", "enchants": []})
assert w2.allowed_item_types() == {"附魔书", "弓"}, \
    "清空后应可重新选择任意类型（此处选了弓）"
w2.close()
print("4. 清空按钮：卡片+步骤图+决策同步清空，且可重新选择任意类型 ✓")

# ========== 5. 回归：clearItems 走 do_clear_cards（清图生效） ==========
w3 = tec.EnchantCalculatorWidget()
w3.chosenItemList.add_card({"item_name": "剑", "enchants": []})
w3.do_start_calculate()  # 单物品方案
app.processEvents()
assert not w3.realSteps.is_placeholder()
w3.chosenItemList.clear_cards()  # 模拟旧路径（直连效果）
app.processEvents()
assert not w3.realSteps.is_placeholder(), \
    "直连 clear_cards 不应清步骤图（证明清图逻辑在 do_clear_cards 中）"
w3.close()
print("5. 回归：清图逻辑位于 do_clear_cards ✓")

print("\n全部冒烟测试通过")
