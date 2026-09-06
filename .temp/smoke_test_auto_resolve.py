# -*- coding: utf-8 -*-
"""冒烟测试：冲突统一在开始计算时处理 + 必然保留附魔自动决策

1. resolve_conflicts 纯函数：非书共有附魔 → 自动保留；零共有 → 待决策；
   全书卡片 → 全部待决策；无卡片 → 全部待决策
2. 添加冲突卡片不再弹窗（决策保持现状）
3. 全链路：剑(锋利V) + 书(亡灵杀手V) → 开始计算自动保留锋利，
   不弹冲突窗，计算成功，最终合成物含锋利不含亡灵杀手（+1 拦截计费）
4. 混合场景：自动簇（剑上锋利）+ 待决策簇（两本书上的无限/经验修补）
   → 只弹一个簇的窗，确定后两个簇决策齐全，计算成功
5. 待决策簇取消弹窗 → 本次不计算，树维持原状，决策不变
6. 自动决策的 defaults 记忆：上次用户选过某簇，下次若该簇变为自动
   决策则以自动决策为准
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import QObject

app = QApplication(sys.argv)

import Tools.tool_EnchantCaculator as tec
from Utils.conflict_resolver import find_conflict_clusters, resolve_conflicts
from Utils.enchant_data_manager import DataManager

dm = DataManager()

# ---------- mock 弹窗（记录调用） ----------
class FakeConflictDlg:
    DialogCode = QDialog.DialogCode
    _keep = None
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
    calls = []

    @staticmethod
    def information(parent, title, text):
        FakeMsgBox.calls.append(("information", title, text))

    @staticmethod
    def warning(parent, title, text):
        FakeMsgBox.calls.append(("warning", title, text))


tec.ConflictResolveDialog = FakeConflictDlg
tec.QMessageBox = FakeMsgBox


def card(item_name, *enchs):
    return {"item_name": item_name,
            "enchants": [{"id": e[0], "name": e[1], "level": e[2]} for e in enchs]}


# ========== 1. resolve_conflicts 纯函数 ==========
# 1a. 剑(锋利) + 书(亡灵杀手)：锋利在唯一非书卡片上 → 自动保留
cards = [card("剑", ("sharpness", "锋利", 5)),
         card("附魔书", ("smite", "亡灵杀手", 5))]
clusters = find_conflict_clusters(cards, dm)
assert len(clusters) == 1
auto, pending = resolve_conflicts(clusters, cards)
assert auto == {0: "sharpness"} and pending == [], (auto, pending)
print("1a. 剑锋利 vs 书亡灵杀手 → 自动保留锋利 ✓")

# 1b. 两把剑各带不同附魔：无共有 → 待决策（第二把剑可做牺牲被吞）
cards = [card("剑", ("sharpness", "锋利", 5)),
         card("剑", ("smite", "亡灵杀手", 5))]
clusters = find_conflict_clusters(cards, dm)
auto, pending = resolve_conflicts(clusters, cards)
assert auto == {} and len(pending) == 1, (auto, pending)
print("1b. 两把剑各带互斥附魔 → 仍需用户决策 ✓")

# 1c. 两把剑都带锋利 + 书带亡灵杀手：锋利在全部非书卡片上 → 自动保留
cards = [card("剑", ("sharpness", "锋利", 5)),
         card("剑", ("sharpness", "锋利", 4)),
         card("附魔书", ("smite", "亡灵杀手", 5))]
clusters = find_conflict_clusters(cards, dm)
auto, pending = resolve_conflicts(clusters, cards)
assert auto == {0: "sharpness"} and pending == []
print("1c. 锋利在全部非书卡片上 → 自动保留 ✓")

# 1d. 全书卡片冲突 → 全部待决策
cards = [card("附魔书", ("sharpness", "锋利", 5)),
         card("附魔书", ("smite", "亡灵杀手", 5))]
clusters = find_conflict_clusters(cards, dm)
auto, pending = resolve_conflicts(clusters, cards)
assert auto == {} and len(pending) == 1
print("1d. 全书冲突 → 弹窗决策 ✓")

# 1e. 无非书卡片（books 空 cards 特例）：空 cards → 全部待决策
auto, pending = resolve_conflicts([[
    {"id": "sharpness", "name": "锋利", "level": 5},
    {"id": "smite", "name": "亡灵杀手", "level": 5}]], [])
assert auto == {} and len(pending) == 1
print("1e. 空 cards 防御 → 全部待决策 ✓")

# ========== 2. 添加冲突卡片不再弹窗 ==========
w = tec.EnchantCalculatorWidget()
FakeConflictDlg.instances.clear()
w.add_item_card(card("剑", ("sharpness", "锋利", 5)))
w.add_item_card(card("附魔书", ("smite", "亡灵杀手", 5)))
app.processEvents()
assert FakeConflictDlg.instances == [], "添加卡片时不应弹冲突窗"
assert w.conflict_choices == {}, "添加阶段决策应为空（开始计算时统一处理）"
print("2. 添加冲突卡片不弹窗 ✓")

# ========== 3. 全链路：唯一剑上的锋利自动保留 ==========
FakeMsgBox.calls.clear()
FakeConflictDlg.instances.clear()
w.do_start_calculate()
app.processEvents()
assert FakeConflictDlg.instances == [], "自动决策场景不应弹冲突窗"
assert FakeMsgBox.calls == [], f"应计算成功无警告，实际 {FakeMsgBox.calls}"
assert w.conflict_choices == {0: "sharpness"}, w.conflict_choices
fb = w.realSteps.final_box()
assert fb is not None and fb.anvil_item.name == "剑"
assert fb.anvil_item.has_enchant("sharpness"), "锋利应保留"
assert not fb.anvil_item.has_enchant("smite"), "亡灵杀手应被拦截"
assert len(w.realSteps.boxes()) == 3, "剑+书 1 步 = 3 框"
# 计费明细应含亡灵杀手拦截（+1 级）
all_detail = [t for c in w.realSteps.cost_circles()
              for t, _ in c._tooltip_lines()]
assert any("亡灵杀手" in t and "互斥" in t for t in all_detail), all_detail
print("3. 剑锋利自动保留，亡灵杀手拦截计费（不弹窗直接计算成功）✓")

# ========== 4. 三附魔互斥簇：锋利在剑上 → 整簇自动决策 ==========
# 锋利×亡灵杀手×节肢杀手 两两互斥 → 并查集连成一簇；锋利在唯一剑上
# 必然保留，亡灵杀手/节肢杀手注定被拦截（+1 计费，无需用户选择）
w2 = tec.EnchantCalculatorWidget()
w2.add_item_card(card("剑", ("sharpness", "锋利", 5)))
w2.add_item_card(card("附魔书", ("smite", "亡灵杀手", 5)))
w2.add_item_card(card("附魔书", ("bane_of_arthropods", "节肢杀手", 5)))
FakeConflictDlg.instances.clear()
FakeMsgBox.calls.clear()
FakeConflictDlg._keep = "smite"
w2.do_start_calculate()
app.processEvents()
assert FakeConflictDlg.instances == [], "整簇自动决策不应弹窗"
assert FakeMsgBox.calls == [], f"应计算成功无警告，实际 {FakeMsgBox.calls}"
assert w2.conflict_choices == {0: "sharpness"}, w2.conflict_choices
fb2 = w2.realSteps.final_box()
assert fb2.anvil_item.has_enchant("sharpness"), "锋利应保留"
assert not fb2.anvil_item.has_enchant("smite") and \
    not fb2.anvil_item.has_enchant("bane_of_arthropods"), \
    "亡灵杀手/节肢杀手应被拦截"
all_detail = [t for c in w2.realSteps.cost_circles()
              for t, _ in c._tooltip_lines()]
assert "亡灵杀手" in "".join(all_detail) and \
    "节肢杀手" in "".join(all_detail), "拦截计费明细应含两个被拦附魔"
print("4. 三附魔互斥簇：剑上锋利必然保留，其余被拦截（整簇自动）✓")

# ========== 4b. 混合场景：自动簇 + 独立待决策簇 ==========
# 簇1：锋利×亡灵杀手×节肢杀手（剑锋利自动）；簇2：无限×经验修补
# （都在书上且与锋利不互斥 → 独立簇，需用户决策）。
# 注：无限只适用于弓，合并到剑上会被"不适用"忽略；用户保留经验修补
# （适用于剑）才可满足约束，故 _keep 设为 mending
w2b = tec.EnchantCalculatorWidget()
w2b.add_item_card(card("剑", ("sharpness", "锋利", 5)))
w2b.add_item_card(card("附魔书", ("smite", "亡灵杀手", 5),
                       ("infinity", "无限", 1)))
w2b.add_item_card(card("附魔书", ("bane_of_arthropods", "节肢杀手", 5),
                       ("mending", "经验修补", 1)))
FakeConflictDlg.instances.clear()
FakeMsgBox.calls.clear()
FakeConflictDlg._keep = "mending"
w2b.do_start_calculate()
app.processEvents()
assert len(FakeConflictDlg.instances) == 1, "只应弹一次窗（仅待决策簇）"
dlg = FakeConflictDlg.instances[0]
assert len(dlg.clusters) == 1 and \
    {m["id"] for m in dlg.clusters[0]} == {"infinity", "mending"}, \
    f"弹窗应只含书上无限簇，实际 {dlg.clusters}"
kept_ids = set(w2b.conflict_choices.values())
assert kept_ids == {"sharpness", "mending"}, w2b.conflict_choices
assert FakeMsgBox.calls == [], f"应计算成功无警告，实际 {FakeMsgBox.calls}"
fb2b = w2b.realSteps.final_box()
assert fb2b.anvil_item.has_enchant("sharpness") and \
    fb2b.anvil_item.has_enchant("mending")
assert not fb2b.anvil_item.has_enchant("smite") and \
    not fb2b.anvil_item.has_enchant("bane_of_arthropods") and \
    not fb2b.anvil_item.has_enchant("infinity")
print("4b. 自动簇+待决策簇并存：只弹待决策簇的窗 ✓")

# ========== 5. 待决策簇取消弹窗 → 本次不计算 ==========
old_final = w2b.realSteps.final_box().anvil_item
old_choices = dict(w2b.conflict_choices)
FakeConflictDlg._keep = None
FakeConflictDlg.instances.clear()
FakeMsgBox.calls.clear()
w2b.do_start_calculate()
app.processEvents()
assert len(FakeConflictDlg.instances) == 1
assert w2b.realSteps.final_box().anvil_item is old_final, "取消后树应维持原状"
assert w2b.conflict_choices == old_choices, "取消后决策应维持原值"
assert FakeMsgBox.calls == [], "取消后不应进入计算/报错"
print("5. 待决策簇取消 → 不计算，决策维持原状 ✓")

# ========== 6. 决策记忆映射：defaults 按待决策簇序号预选 ==========
# w2b 上次决策：原簇序号自动簇 sharpness + 弹窗簇 mending；
# 再触发弹窗时 defaults 应把待决策簇的决策映射到弹窗内序号 0
FakeConflictDlg._keep = "mending"
FakeConflictDlg.instances.clear()
w2b.do_start_calculate()
app.processEvents()
dlg = FakeConflictDlg.instances[0]
assert dlg.defaults == {0: "mending"}, \
    f"defaults 应映射为弹窗内序号，实际 {dlg.defaults}"
print("6. defaults 记忆按待决策簇映射 ✓")

w.close()
w2.close()
w2b.close()
print("\n全部冒烟测试通过")
