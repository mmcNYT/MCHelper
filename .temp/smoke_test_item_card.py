# -*- coding: utf-8 -*-
"""冒烟测试：物品卡片（图标 + 游戏 tooltip 风格附魔方框）
1. 罗马数字转换边界
2. 物品图标映射全部有效（下拉框 16 个物品全有图标文件）
3. 卡片创建渲染（有附魔/无附魔/未知物品）
4. tooltip 方框绘制尺寸与文本行
5. add_item_card 完整链路（模拟确认后卡片进入 listWidget）
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

app = QApplication(sys.argv)

from Utils.enchanted_item_card import (
    int_to_roman, get_item_icon_path, EnchantedItemCard, _TooltipBox, ROMAN_NUMERALS
)

# ---------- 1. 罗马数字转换 ----------
assert ROMAN_NUMERALS[1] == "I" and ROMAN_NUMERALS[5] == "V" and ROMAN_NUMERALS[10] == "X"
assert int_to_roman(1) == "I"
assert int_to_roman(3) == "III"
assert int_to_roman(5) == "V"
assert int_to_roman(10) == "X"
assert int_to_roman(11) == "11", "超过 10 应回退阿拉伯数字"
assert int_to_roman(0) == "I", "非法等级 0 回退 I"
assert int_to_roman(-1) == "I", "负数回退 I"
print("1. 罗马数字转换（含边界回退） ✓")

# ---------- 2. 下拉框全部物品图标映射有效 ----------
item_names = ["附魔书", "剑", "斧", "矛", "镐", "锹", "锄", "弓", "弩",
              "三叉戟", "重锤", "头盔", "胸甲", "护腿", "靴子", "钓鱼竿"]
missing = []
for name in item_names:
    p = get_item_icon_path(name)
    if not p or not os.path.exists(p):
        missing.append(name)
assert not missing, f"缺少图标的物品: {missing}"
# 海龟壳（不在下拉框但是防具类附魔适用物品）
assert os.path.exists(get_item_icon_path("海龟壳")), "海龟壳图标缺失"
# 未知物品回退
assert get_item_icon_path("不存在的物品") == "", "未知物品应返回空路径"
print("2. 全部 16+1 个物品图标映射有效 ✓")

# ---------- 3. 卡片创建渲染（三种情形） ----------
enchants = [
    {"id": "sharpness", "name": "锋利", "level": 5},
    {"id": "unbreaking", "name": "耐久", "level": 3},
    {"id": "mending", "name": "经验修补", "level": 1},
]
# 3a. 正常卡片
card = EnchantedItemCard("剑", enchants)
card.grab()  # 强制渲染一次，paintEvent 执行
assert card.layout() is not None and card.layout().count() == 2, "卡片应含图标+方框两个区域"
# 3b. 无附魔卡片（仅物品名行）
card_empty = EnchantedItemCard("弓", [])
card_empty.grab()
assert card_empty.layout().count() == 2
# 3c. 未知物品（无图标路径也应正常创建，图标区空白）
card_unknown = EnchantedItemCard("神秘物品", enchants[:1])
card_unknown.grab()
print("3. 卡片创建渲染（正常/无附魔/未知物品） ✓")

# ---------- 4. tooltip 方框尺寸与文本 ----------
box = _TooltipBox("剑", enchants)
assert box._line_texts == ["剑", "锋利 V", "耐久 III", "经验修补 I"], f"文本行错误: {box._line_texts}"
fm_w = box._fixed_w
assert fm_w > 16 and box._fixed_h >= 10 + 4 * box._line_height, "方框尺寸应容纳全部行"
box.grab()  # 触发 paintEvent（无异常即通过）
print("4. tooltip 方框文本行与尺寸 ✓")

# ---------- 5. add_item_card 完整链路 ----------
from Tools.tool_EnchantCaculator import EnchantCalculatorWidget

widget = EnchantCalculatorWidget()
assert widget.chosenItemList.count() == 0, "初始列表应为空"
data = {"item_name": "剑", "enchants": enchants}
widget.add_item_card(data)
assert widget.chosenItemList.count() == 1, "添加后应有一条目"
inner = widget.chosenItemList.itemWidget(widget.chosenItemList.item(0))
assert isinstance(inner, EnchantedItemCard), "条目控件应为物品卡片"
inner.grab()
# 第二次确认（多物品堆叠）
data2 = {"item_name": "弓", "enchants": [{"id": "power", "name": "力量", "level": 5}]}
widget.add_item_card(data2)
assert widget.chosenItemList.count() == 2, "第二次添加应累计"
print("5. add_item_card 完整链路（含多次添加） ✓")

# ---------- 6. 确认→卡片 端到端（复用模态流程） ----------
from PySide6.QtCore import QTimer
from Utils.choose_items import ChooseItemsWindow

widget2 = EnchantCalculatorWidget()

def confirm_modal():
    w = QApplication.activeModalWidget()
    w.on_enchant_dropped("fortune", 3)
    w.on_enchant_dropped("sharpness", 5)
    w.confirmItem.click()

QTimer.singleShot(0, confirm_modal)
widget2.do_choose_items()
assert widget2.chosenItemList.count() == 1, "端到端：确认后应自动出现 1 张卡片"
card_in_list = widget2.chosenItemList.itemWidget(widget2.chosenItemList.item(0))
assert isinstance(card_in_list, EnchantedItemCard)
box_in_card = card_in_card = card_in_list.layout().itemAt(1).widget()
assert box_in_card._line_texts[0] == "附魔书", f"物品名应为附魔书: {box_in_card._line_texts[0]}"
assert any("锋利 V" in t for t in box_in_card._line_texts), "应含 锋利 V 行"
assert any("时运 III" in t for t in box_in_card._line_texts), "应含 时运 III 行"
print("6. 端到端：确认选择 → 卡片显示（名称+罗马数字附魔） ✓")

print("\n全部冒烟测试通过")
