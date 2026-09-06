# -*- coding: utf-8 -*-
"""冒烟测试：物品卡片横向排列
1. listWidget 流方向为 LeftToRight 且开启自动换行
2. 多张卡片几何位置：第二张在第一张右侧（同一行）
3. 卡片内部结构不变：图标在上、附魔方框在下
4. add_item_card 链路 + 端到端仍然可用
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtCore import Qt

app = QApplication(sys.argv)

from Tools.tool_EnchantCaculator import EnchantCalculatorWidget
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


# ---------- 1. 流方向与换行配置 ----------
widget = EnchantCalculatorWidget()
widget.resize(658, 518)
from PySide6.QtWidgets import QListView
assert widget.chosenItemList.flow() == QListView.LeftToRight, "listWidget 应为横向流"
assert widget.chosenItemList.isWrapping(), "listWidget 应开启自动换行"
print("1. 横向流 + 自动换行配置 ✓")

# ---------- 2. 多卡片几何位置：从左到右 ----------
data1 = {"item_name": "剑", "enchants": [{"id": "sharpness", "name": "锋利", "level": 5}]}
data2 = {"item_name": "弓", "enchants": [{"id": "power", "name": "力量", "level": 5}]}
data3 = {"item_name": "镐", "enchants": [{"id": "efficiency", "name": "效率", "level": 5}]}
widget.add_item_card(data1)
widget.add_item_card(data2)
widget.add_item_card(data3)
widget.show()
app.processEvents()

assert widget.chosenItemList.count() == 3
r1 = widget.chosenItemList.visualItemRect(widget.chosenItemList.item(0))
r2 = widget.chosenItemList.visualItemRect(widget.chosenItemList.item(1))
r3 = widget.chosenItemList.visualItemRect(widget.chosenItemList.item(2))
assert r1.isValid() and r2.isValid() and r3.isValid(), "三项均应有有效几何位置"
# 横排特征：第二张在第一张右侧（左边缘大于第一张右边缘），第三张更靠右
assert r2.left() >= r1.right(), f"第二张应在第一张右侧（r1={r1}, r2={r2}）"
assert r3.left() >= r2.right(), f"第三张应在第二张右侧（r2={r2}, r3={r3}）"
# 同一行特征：垂直位置接近（横排后 y 应相同或接近，竖排则逐项下移）
assert abs(r1.top() - r2.top()) <= 2, f"同行卡片顶部 y 应接近（r1.top={r1.top()}, r2.top={r2.top()}）"
print(f"2. 三卡片从左到右同行排列（x: {r1.left()}→{r2.left()}→{r3.left()}，y 均为 {r1.top()}） ✓")

# ---------- 3. 卡片内部结构：图标在上、附魔框在下 ----------
card = widget.chosenItemList.itemWidget(widget.chosenItemList.item(0))
assert isinstance(card, EnchantedItemCard)
icon_w = card.layout().itemAt(0).widget()
box_w = card.layout().itemAt(1).widget()
assert icon_w.geometry().bottom() <= box_w.geometry().top(), "卡片内图标应在附魔方框上方（图标在上、附魔在下）"
print("3. 卡片内部结构：图标在上、附魔方框在下 ✓")

# ---------- 4. 端到端：确认 → 横排列表新增卡片 ----------
from PySide6.QtCore import QTimer

widget2 = EnchantCalculatorWidget()
widget2.resize(658, 518)

def confirm_modal():
    w = QApplication.activeModalWidget()
    w.on_enchant_dropped("fortune", 3)
    w.confirmItem.click()

QTimer.singleShot(0, confirm_modal)
widget2.do_choose_items()
assert widget2.chosenItemList.count() == 1
card_in = widget2.chosenItemList.itemWidget(widget2.chosenItemList.item(0))
assert isinstance(card_in, EnchantedItemCard)
print("4. 端到端：确认 → 卡片进入横排列表 ✓")

widget.close()
widget2.close()
_restore_session_file()
print("\n全部冒烟测试通过")
