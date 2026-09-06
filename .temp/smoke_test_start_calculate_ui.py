# -*- coding: utf-8 -*-
"""冒烟测试：开始计算按钮全链路（UI 集成）

覆盖：
1. realSteps 已被替换为 AnvilStepsTree（占位提示状态）
2. 无卡片点开始 → 提示弹窗（QMessageBox mock，不计算）
3. 无冲突卡片点开始 → 不弹冲突窗，直接计算，树显示方案
4. 有冲突卡片点开始 → 冲突弹窗（预选上次决策）→ 按决策计算
5. 冲突弹窗取消 → 本次不计算（树维持原状）
6. 计算失败（多类型物品）→ 警告弹窗提示原因
7. 决策约束生效：保留亡灵杀手 → 最终合成物含亡灵杀手
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import QObject
from PySide6.QtCore import Signal as PySignal

app = QApplication(sys.argv)

import Tools.tool_EnchantCaculator as tec
from Utils.anvil_steps_tree import AnvilStepsTree
from Utils.conflict_resolver import find_conflict_clusters


def card(item_name, *enchs):
    return {"item_name": item_name,
            "enchants": [{"id": e[0], "name": e[1], "level": e[2]} for e in enchs]}


# ---------- mock 冲突弹窗 / 消息框（记录调用，不真弹） ----------
class FakeConflictDlg:
    DialogCode = QDialog.DialogCode
    _keep = None       # None → 拒绝（暂不处理/取消）；否则保留该附魔 ID
    instances = []

    def __init__(self, clusters, parent=None, defaults=None):
        self.clusters = clusters
        self.defaults = defaults
        FakeConflictDlg.instances.append(self)

    def exec(self):
        return (QDialog.Accepted if FakeConflictDlg._keep is not None
                else QDialog.Rejected)

    def choices(self):
        for ci, members in enumerate(self.clusters):
            if any(m["id"] == FakeConflictDlg._keep for m in members):
                return {ci: FakeConflictDlg._keep}
        return {}


class FakeMsgBox(QObject):
    """静态方法 mock：记录 (方法, 标题, 文本)"""
    calls = []

    @staticmethod
    def information(parent, title, text):
        FakeMsgBox.calls.append(("information", title, text))

    @staticmethod
    def warning(parent, title, text):
        FakeMsgBox.calls.append(("warning", title, text))


tec.ConflictResolveDialog = FakeConflictDlg
tec.QMessageBox = FakeMsgBox

# ---------- 会话隔离：移走用户真实卡片会话，防止 _restore_session 污染测试初始状态 ----------
_session_path = tec.EnchantCalculatorWidget()._session_path()
_saved_session = open(_session_path, "r", encoding="utf-8").read() \
    if os.path.exists(_session_path) else None
if os.path.exists(_session_path):
    os.remove(_session_path)


def _restore_session_file():
    """测试结束后恢复用户真实会话文件（移走前的内容）"""
    if _saved_session is not None:
        with open(_session_path, "w", encoding="utf-8") as f:
            f.write(_saved_session)


w = tec.EnchantCalculatorWidget()
w.resize(658, 518)
w.show()
app.processEvents()


def final_label(widget):
    """当前树中最终合成物的展示标签（占位状态返回 None）"""
    fb = widget.realSteps.final_box()
    return None if fb is None else fb.anvil_item.display_label(
        tec.DataManager())


# ========== 1. realSteps 已替换为步骤树 ==========
assert isinstance(w.realSteps, AnvilStepsTree), \
    f"realSteps 应为 AnvilStepsTree，实际 {type(w.realSteps).__name__}"
assert w.realSteps.is_placeholder(), "初始应为占位提示状态"
assert "开始计算" in w.realSteps.placeholder_text
assert isinstance(w.chosenItemList, tec.CardListWidget), "chosenItemList 仍应为卡片列表"
print("1. realSteps 已替换为 AnvilStepsTree（占位提示）✓")

# ========== 2. 无卡片点开始 → 提示，不计算 ==========
FakeMsgBox.calls.clear()
FakeConflictDlg._keep = None
FakeConflictDlg.instances.clear()
w.do_start_calculate()
app.processEvents()
assert len(FakeMsgBox.calls) == 1, f"应弹一次提示，实际 {FakeMsgBox.calls}"
assert FakeMsgBox.calls[0][0] == "information" and "添加物品" in FakeMsgBox.calls[0][2]
assert FakeConflictDlg.instances == [], "无卡片不应弹冲突窗"
assert w.realSteps.is_placeholder(), "无卡片不应清掉占位"
print("2. 无卡片 → 提示弹窗，不计算 ✓")

# ========== 3. 无冲突卡片 → 直接计算，树显示方案 ==========
w.chosenItemList.add_card(card("剑", ("sharpness", "锋利", 5),
                               ("unbreaking", "耐久", 3)))
app.processEvents()
FakeMsgBox.calls.clear()
w.do_start_calculate()
app.processEvents()
assert FakeMsgBox.calls == [], f"不应有错误弹窗，实际 {FakeMsgBox.calls}"
assert FakeConflictDlg.instances == [], "无冲突不应弹冲突窗"
assert not w.realSteps.is_placeholder(), "计算后应退出占位状态"
fb = w.realSteps.final_box()
assert fb is not None and fb.anvil_item.name == "剑", "应显示剑"
assert fb.anvil_item.has_enchant("sharpness") and \
    fb.anvil_item.has_enchant("unbreaking"), "最终物品应含锋利+耐久"
assert w.realSteps.boxes() == [fb], "单物品方案应只有最终框"
assert w.conflict_choices == {}, "无冲突时决策为空"
print(f"3. 无冲突直接计算：{final_label(w)} ✓")

# ========== 4. 冲突处理：自动决策 + 弹窗决策混合流 ==========
# add_card 走列表直加不弹窗（弹窗只在 do_start_calculate 中）
w.chosenItemList.add_card(card("附魔书", ("smite", "亡灵杀手", 3)))
app.processEvents()
old_plan_boxes = len(w.realSteps.boxes())
# 剑自带锋利 → 锋利必然保留，整簇自动决策，不弹窗直接计算
FakeMsgBox.calls.clear()
FakeConflictDlg._keep = None
FakeConflictDlg.instances.clear()
w.do_start_calculate()
app.processEvents()
assert FakeConflictDlg.instances == [], \
    "唯一剑自带锋利 → 自动决策，不应弹冲突窗"
assert FakeMsgBox.calls == [], f"应计算成功无警告，实际 {FakeMsgBox.calls}"
assert w.conflict_choices == {0: "sharpness"}, w.conflict_choices
fb = w.realSteps.final_box()
assert fb.anvil_item.has_enchant("sharpness"), "锋利应保留"
assert not fb.anvil_item.has_enchant("smite"), "亡灵杀手应被拦截"
# 被拦截的亡灵杀手应出现在计费明细中（圆标 tooltip）
all_detail = [t for c in w.realSteps.cost_circles()
              for t, _ in c._tooltip_lines()]
assert any("亡灵杀手" in t and "互斥" in t for t in all_detail), all_detail
print("4a. 剑自带锋利 → 自动保留锋利，亡灵杀手拦截计费（不弹窗）✓")

# 换无冲突组合验证成功路径：清空重来，剑不带附魔（决策作废验证兼项）
FakeMsgBox.calls.clear()
FakeConflictDlg.instances.clear()
w.clearItems.click()  # 走真实清空链路（按钮→do_clear_cards：卡片+决策+步骤图）
app.processEvents()
assert w.conflict_choices == {}, "清空后决策应作废"
assert w.realSteps.is_placeholder(), "清空后树应恢复占位"
assert w.chosenItemList.count() == 0, "清空后卡片列表应为空"
w.chosenItemList.add_card(card("剑"))
w.chosenItemList.add_card(card("附魔书", ("sharpness", "锋利", 5)))
w.chosenItemList.add_card(card("附魔书", ("smite", "亡灵杀手", 3)))
app.processEvents()
# 冲突：锋利 vs 亡灵杀手（两本书上，剑无附魔 → 待决策弹窗）
# 首次拒绝（暂不处理）→ 本次不计算，树维持占位
FakeConflictDlg._keep = None
FakeConflictDlg.instances.clear()
w.do_start_calculate()
app.processEvents()
assert len(FakeConflictDlg.instances) == 1, "应弹待决策冲突窗"
assert FakeConflictDlg.instances[0].defaults == {}, "首次无决策可预选"
assert w.realSteps.is_placeholder(), "取消后树应维持占位"
# 再来一次：选择保留亡灵杀手 → 计算成功
FakeConflictDlg._keep = "smite"
FakeConflictDlg.instances.clear()
w.do_start_calculate()
app.processEvents()
assert len(FakeConflictDlg.instances) == 1
assert w.conflict_choices == {0: "smite"}
assert FakeMsgBox.calls == [], f"应计算成功无警告，实际 {FakeMsgBox.calls}"
fb = w.realSteps.final_box()
assert fb is not None and fb.anvil_item is not None, "应显示新方案"
# 3 物品 2 步 = 5 框
assert len(w.realSteps.boxes()) == 5, \
    f"3 物品 + 2 步 = 5 框，实际 {len(w.realSteps.boxes())}"
assert fb.anvil_item.has_enchant("smite"), \
    "保留决策应生效：最终合成物含亡灵杀手"
assert not fb.anvil_item.has_enchant("sharpness"), \
    "锋利被互斥拦截，不应出现在最终合成物"
# 被拦截的锋利应出现在计费明细中（圆标 tooltip）
all_detail = [t for c in w.realSteps.cost_circles()
              for t, _ in c._tooltip_lines()]
assert any("锋利" in t for t in all_detail), \
    f"计费明细应含被拦截的锋利，实际 {all_detail}"
print("4b. 待决策簇弹窗（预选决策）→ 计算成功且保留亡灵杀手 ✓")

# ========== 5. 冲突弹窗取消 → 本次不计算，树维持原状 ==========
old_fb = w.realSteps.final_box().anvil_item
old_boxes = len(w.realSteps.boxes())
FakeConflictDlg._keep = None
FakeConflictDlg.instances.clear()
FakeMsgBox.calls.clear()
w.do_start_calculate()
app.processEvents()
assert len(FakeConflictDlg.instances) == 1
assert w.realSteps.final_box().anvil_item is old_fb, "取消后树应维持原状"
assert len(w.realSteps.boxes()) == old_boxes
assert w.conflict_choices == {0: "smite"}, "取消后决策应维持原值"
print("5. 冲突窗取消 → 本次不计算，树维持原状 ✓")

# ========== 6. 计算失败（多类型非书物品）→ 警告弹窗 ==========
w2 = tec.EnchantCalculatorWidget()
w2.chosenItemList.add_card(card("剑", ("sharpness", "锋利", 5)))
w2.chosenItemList.add_card(card("镐", ("efficiency", "效率", 5)))
app.processEvents()
FakeMsgBox.calls.clear()
w2.do_start_calculate()
app.processEvents()
assert len(FakeMsgBox.calls) == 1 and FakeMsgBox.calls[0][0] == "warning", \
    f"应弹警告，实际 {FakeMsgBox.calls}"
assert "无法" in FakeMsgBox.calls[0][2], FakeMsgBox.calls[0][2]
assert w2.realSteps.is_placeholder(), "失败后树应保持占位提示"
w2.close()
print("6. 多类型物品 → 警告弹窗，树保持占位 ✓")

# ========== 7. 对称性验证：保留锋利（与 4b 相反的决策） ==========
w3 = tec.EnchantCalculatorWidget()
w3.chosenItemList.add_card(card("剑"))
w3.chosenItemList.add_card(card("附魔书", ("sharpness", "锋利", 5)))
w3.chosenItemList.add_card(card("附魔书", ("smite", "亡灵杀手", 3)))
app.processEvents()
FakeMsgBox.calls.clear()
FakeConflictDlg.instances.clear()
FakeConflictDlg._keep = "sharpness"   # 这次保留锋利
w3.do_start_calculate()
app.processEvents()
assert FakeMsgBox.calls == [], f"应计算成功，实际 {FakeMsgBox.calls}"
assert w3.conflict_choices == {0: "sharpness"}
fb3 = w3.realSteps.final_box()
assert fb3.anvil_item.has_enchant("sharpness"), "保留锋利时最终合成物应含锋利"
assert not fb3.anvil_item.has_enchant("smite"), \
    "保留锋利时最终合成物不应含亡灵杀手"
w3.close()
print("7. 对称决策（保留锋利）→ 最终合成物含锋利不含亡灵杀手 ✓")

# ========== 8. 约束互斥验证：保留不适用于剑的附魔 → 优化器报错 ==========
# 弓附魔"无限"与"经验修补"互斥；无限只适用于弓，合并到剑上
# 会被"不适用"忽略——用户选保留无限 → 约束不可满足 → 警告弹窗
w4 = tec.EnchantCalculatorWidget()
w4.chosenItemList.add_card(card("剑"))
w4.chosenItemList.add_card(card("附魔书", ("infinity", "无限", 1)))
w4.chosenItemList.add_card(card("附魔书", ("mending", "经验修补", 1)))
app.processEvents()
FakeMsgBox.calls.clear()
FakeConflictDlg.instances.clear()
FakeConflictDlg._keep = "infinity"   # 保留不适用于剑的无限
w4.do_start_calculate()
app.processEvents()
assert len(FakeConflictDlg.instances) == 1, "应弹待决策窗（都在书上）"
assert len(FakeMsgBox.calls) == 1 and FakeMsgBox.calls[0][0] == "warning", \
    f"保留不适用于剑的无限 → 应警告无法计算，实际 {FakeMsgBox.calls}"
assert "无限" in FakeMsgBox.calls[0][2], FakeMsgBox.calls[0][2]
assert w4.realSteps.is_placeholder(), "失败后树应保持占位提示"
w4.close()
print("8. 保留不适用于剑的无限 → 警告“无法合成一件”（约束互斥生效）✓")

w.close()
_restore_session_file()
print("\n全部冒烟测试通过")
