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

w = tec.EnchantCalculatorWidget()
w.resize(658, 518)
w.show()
app.processEvents()

# ========== 1. realSteps 已替换为步骤树 ==========
assert isinstance(w.realSteps, AnvilStepsTree), \
    f"realSteps 应为 AnvilStepsTree，实际 {type(w.realSteps).__name__}"
assert w.realSteps.topLevelItemCount() == 1
assert "开始计算" in w.realSteps.topLevelItem(0).text(0)
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
root = w.realSteps.topLevelItem(0)
assert root is not None and "剑（锋利V、耐久III）" in root.text(0), \
    f"单物品方案树应直接展示物品，实际 {root.text(0) if root else None}"
assert w.conflict_choices == {}, "无冲突时决策为空"
print(f"3. 无冲突直接计算：{root.text(0)} ✓")

# ========== 4. 有冲突卡片 → 冲突弹窗（预选上次决策）→ 按决策计算 ==========
# add_card 走列表直加不弹窗（弹窗只在 add_item_card / do_start_calculate 中）
w.chosenItemList.add_card(card("附魔书", ("smite", "亡灵杀手", 3)))
app.processEvents()
# 开始计算时首次弹冲突窗：拒绝（暂不处理）→ 本次不计算
FakeConflictDlg._keep = None
FakeConflictDlg.instances.clear()
w.do_start_calculate()
app.processEvents()
assert len(FakeConflictDlg.instances) == 1, "开始计算应重新检测冲突并弹窗"
assert FakeConflictDlg.instances[0].defaults == {}, "首次计算无决策可预选"
# 冲突弹窗取消（暂不处理）→ 本次不计算，树维持第 3 步的旧方案
assert w.realSteps.topLevelItem(0).text(0).startswith("剑（锋利V、耐久III）"), \
    "取消冲突窗后本次不计算，树应维持旧方案"
FakeMsgBox.calls.clear()
# 再来一次：这次选择保留亡灵杀手
# 注意：剑已自带锋利V（物品附魔不可移除），保留亡灵杀手与锋利互斥 →
# 计算会失败并弹警告。这正是约束生效的证据——改为保留锋利才可计算
FakeConflictDlg._keep = "smite"
FakeConflictDlg.instances.clear()
w.do_start_calculate()
app.processEvents()
assert len(FakeConflictDlg.instances) == 1
assert w.conflict_choices == {0: "smite"}, f"决策应更新，实际 {w.conflict_choices}"
assert len(FakeMsgBox.calls) == 1 and FakeMsgBox.calls[0][0] == "warning", \
    f"自带锋利的剑 + 保留亡灵杀手 → 应警告无法计算，实际 {FakeMsgBox.calls}"
assert "亡灵杀手" in FakeMsgBox.calls[0][2]
assert w.realSteps.topLevelItem(0).text(0).startswith("剑（锋利V、耐久III）"), \
    "失败后树维持旧方案"
print("4a. 保留亡灵杀手 + 剑自带锋利 → 正确警告（约束生效）✓")

# 换无冲突组合验证成功路径：清空重来，剑不带附魔
FakeMsgBox.calls.clear()
FakeConflictDlg.instances.clear()
w.chosenItemList.clear_cards()
app.processEvents()
w.chosenItemList.add_card(card("剑"))
w.chosenItemList.add_card(card("附魔书", ("sharpness", "锋利", 5)))
w.chosenItemList.add_card(card("附魔书", ("smite", "亡灵杀手", 3)))
app.processEvents()
# 冲突：锋利 vs 亡灵杀手（两本书上）→ 弹窗选择保留亡灵杀手 → 计算成功
FakeConflictDlg._keep = "smite"
w.do_start_calculate()
app.processEvents()
assert len(FakeConflictDlg.instances) == 1
assert w.conflict_choices == {0: "smite"}
assert FakeMsgBox.calls == [], f"应计算成功无警告，实际 {FakeMsgBox.calls}"
root = w.realSteps.topLevelItem(0)
assert root is not None and "最终合成物" in root.text(0), \
    f"树应显示新方案，实际 {root.text(0) if root else None}"
step_texts = []
def walk(item):
    step_texts.append(item.text(0))
    for i in range(item.childCount()):
        walk(item.child(i))
walk(root)
assert any("亡灵杀手" in t for t in step_texts), \
    f"树中应出现亡灵杀手（保留决策生效），实际 {step_texts}"
assert any("锋利" in t for t in step_texts), "树中应出现被拦截的锋利（计费明细）"
print("4b. 冲突弹窗（预选决策）→ 计算成功且保留亡灵杀手 ✓")

# ========== 5. 冲突弹窗取消 → 本次不计算，树维持原状 ==========
old_root_text = w.realSteps.topLevelItem(0).text(0)
FakeConflictDlg._keep = None
FakeConflictDlg.instances.clear()
FakeMsgBox.calls.clear()
w.do_start_calculate()
app.processEvents()
assert len(FakeConflictDlg.instances) == 1
assert w.realSteps.topLevelItem(0).text(0) == old_root_text, "取消后树应维持原状"
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
assert "开始计算" in w2.realSteps.topLevelItem(0).text(0), \
    "失败后树应保持占位提示"
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
final_label = w3.realSteps.topLevelItem(0).text(0)
assert "最终合成物" in final_label and "锋利" in final_label, final_label
assert "亡灵杀手" not in final_label, "保留锋利时最终合成物不应含亡灵杀手"
w3.close()
print("7. 对称决策（保留锋利）→ 最终合成物含锋利不含亡灵杀手 ✓")

w.close()
print("\n全部冒烟测试通过")
