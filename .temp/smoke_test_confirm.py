# -*- coding: utf-8 -*-
"""冒烟测试：验证「确认」按钮数据打包与调用方接收
1. 点击确认 → selected_data 结构正确（物品名称 + 已选附魔[名称+等级]）
2. 等级取已选列表中记录的等级（重复拖入取较高等级后打包正确）
3. 异常项（无 UserRole）不进数据包
4. 真实模态流程：exec() 返回后调用方 self.selected_stuff 接收到数据
5. 未点确认（拒绝/关闭）→ selected_data 保持 None，调用方拿到 None
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication, QListWidgetItem, QDialog
from PySide6.QtCore import Qt, QTimer

app = QApplication(sys.argv)

from Utils.choose_items import ChooseItemsWindow
from Tools.tool_EnchantCaculator import EnchantCalculatorWidget

# ---------- 1. 点击确认 → 数据包结构正确 ----------
win = ChooseItemsWindow()
win.on_enchant_dropped("fortune", 3)
win.on_enchant_dropped("sharpness", 5)
win.confirmItem.click()  # 触发打包（accept）
assert win.result() == QDialog.Accepted, "确认应以 accept 关闭对话框"
data = win.selected_data
assert data is not None, "确认后 selected_data 不应为 None"
assert data["item_name"] == "附魔书", f"物品名应为下拉框文本，实际: {data['item_name']}"
ids = [e["id"] for e in data["enchants"]]
assert ids == ["fortune", "sharpness"], f"应按列表顺序打包，实际: {ids}"
by_id = {e["id"]: e for e in data["enchants"]}
assert by_id["fortune"]["name"] == "时运" and by_id["fortune"]["level"] == 3, f"时运打包错误: {by_id['fortune']}"
assert by_id["sharpness"]["name"] == "锋利" and by_id["sharpness"]["level"] == 5, f"锋利打包错误: {by_id['sharpness']}"
print("1. 确认打包：结构 + 名称 + 等级 + 顺序 ✓")

# ---------- 2. 重复拖入取较高等级后打包正确（含溢出保护） ----------
win2 = ChooseItemsWindow()
win2.on_enchant_dropped("sharpness", 2)
win2.on_enchant_dropped("sharpness", 4)  # 同附魔更高等级 → 合并为 4（锋利 max_level=5，不触发截断）
win2.on_enchant_dropped("fortune", 99)   # 时运 max_level=3 → 溢出保护截断为 3
win2.confirmItem.click()
data2 = win2.selected_data
by_id2 = {e["id"]: e for e in data2["enchants"]}
assert len(data2["enchants"]) == 2, "重复拖入同附魔应合并为一条"
assert by_id2["sharpness"]["level"] == 4, f"锋利应取较高等级 4，实际: {by_id2['sharpness']['level']}"
assert by_id2["fortune"]["level"] == 3, f"时运应被 max_level 截断为 3，实际: {by_id2['fortune']['level']}"
print("2. 重复拖入合并 + 等级溢出保护打包正确 ✓")

# ---------- 3. 异常项（无 UserRole）不进数据包 ----------
win2.chosenEnchantmentList.addItem(QListWidgetItem("异常项"))
win2.confirmItem.click()
data2 = win2.selected_data
assert len(data2["enchants"]) == 2, f"异常项应被跳过，保留 2 条真实附魔，实际: {len(data2['enchants'])}"
assert all(e.get("id") for e in data2["enchants"]), "数据包中不应存在无 ID 条目"
print("3. 异常项跳过 ✓")

# ---------- 4. 真实模态流程：exec() 返回后调用方接收数据 ----------
widget = EnchantCalculatorWidget()

def confirm_modal():
    w = QApplication.activeModalWidget()
    assert isinstance(w, ChooseItemsWindow), f"当前模态窗口应为选择窗口，实际: {type(w)}"
    w.on_enchant_dropped("fortune", 3)
    w.confirmItem.click()  # accept → exec() 返回

QTimer.singleShot(0, confirm_modal)  # 在 do_choose_items 的 exec() 循环中触发
widget.do_choose_items()  # 内部 exec() 阻塞，直到确认后返回；返回后已同步完成赋值
assert widget.selected_stuff is not None, "调用方应接收到数据包"
assert widget.selected_stuff["enchants"][0]["id"] == "fortune", "接收内容应与打包一致"
assert widget.selected_stuff["enchants"][0]["level"] == 3, "接收等级应与打包一致"
print("4. exec() 返回后 selected_stuff 接收数据 ✓")

# ---------- 5. 未点确认 → selected_stuff 为 None ----------
widget2 = EnchantCalculatorWidget()

def cancel_modal():
    w = QApplication.activeModalWidget()
    w.reject()  # 模拟用户关闭/取消

QTimer.singleShot(0, cancel_modal)
widget2.do_choose_items()
assert widget2.selected_stuff is None, "未确认时 selected_stuff 应为 None"
print("5. 未确认时接收 None（不误用旧数据）✓")

print("\n全部冒烟测试通过")
