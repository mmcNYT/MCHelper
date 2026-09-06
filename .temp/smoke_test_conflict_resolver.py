# -*- coding: utf-8 -*-
"""冒烟测试：跨卡片附魔冲突检测与解决
1. 簇检测：无冲突 / 两附魔互斥 / 同附魔多卡合并 / 三方互斥 / 多簇独立
2. 对话框：单选默认值 / choices 读取 / 多簇 / defaults 预选
3. remove_enchants_everywhere：按物品名移除附魔并重绘、无关节卡不动
4. 集成：冲突统一在开始计算时处理（添加卡片不再弹窗）——
   必然保留自动决策；待决策簇弹窗；决策只记录不移除卡片
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication, QRadioButton
from PySide6.QtCore import Qt

app = QApplication(sys.argv)

from Utils.conflict_resolver import find_conflict_clusters, ConflictResolveDialog
from Utils.enchant_data_manager import DataManager
from Utils.card_list_widget import CardListWidget

dm = DataManager()


def card(item_name, *enchs):
    return {"item_name": item_name,
            "enchants": [{"id": e[0], "name": e[1], "level": e[2]} for e in enchs]}


# ========== 1. 簇检测 ==========
# 1a. 无冲突
clusters = find_conflict_clusters(
    [card("剑", ("sharpness", "锋利", 5)),
     card("弓", ("power", "力量", 5))], dm)
assert clusters == [], f"无冲突应返回空列表，实际 {clusters}"
print("1a. 无冲突 → 空簇列表 ✓")

# 1b. 两附魔互斥（剑·锋利 vs 附魔书·亡灵杀手）
clusters = find_conflict_clusters(
    [card("剑", ("sharpness", "锋利", 5)),
     card("附魔书", ("smite", "亡灵杀手", 3))], dm)
assert len(clusters) == 1, f"应检测出 1 个冲突簇，实际 {len(clusters)}"
ids = {m["id"] for m in clusters[0]}
assert ids == {"sharpness", "smite"}, f"簇成员应为锋利+亡灵杀手，实际 {ids}"
smite_m = next(m for m in clusters[0] if m["id"] == "smite")
assert smite_m["level"] == 3 and smite_m["items"] == ["附魔书"], \
    f"成员应携带等级与物品名，实际 {smite_m}"
print("1b. 两附魔互斥 → 1 簇（含等级/物品名信息）✓")

# 1c. 同一附魔出现在多张卡片：不构成冲突（等级取最高、物品名合并）
clusters = find_conflict_clusters(
    [card("剑", ("sharpness", "锋利", 5)),
     card("斧", ("sharpness", "锋利", 3))], dm)
assert clusters == [], "同附魔多卡片不应构成冲突"
print("1c. 同附魔多卡合并（不构成冲突）✓")

# 1d. 三方互斥聚成一个簇（锋利×亡灵杀手×节肢杀手）
clusters = find_conflict_clusters(
    [card("剑", ("sharpness", "锋利", 5)),
     card("附魔书", ("smite", "亡灵杀手", 3)),
     card("附魔书", ("bane_of_arthropods", "节肢杀手", 2))], dm)
assert len(clusters) == 1 and len(clusters[0]) == 3, \
    f"三方互斥应聚为 1 簇 3 成员，实际 {clusters}"
print("1d. 三方互斥聚成 1 簇 ✓")

# 1e. 两个独立冲突簇（锋利系 + 保护系）
clusters = find_conflict_clusters(
    [card("剑", ("sharpness", "锋利", 5)),
     card("附魔书", ("smite", "亡灵杀手", 3)),
     card("头盔", ("protection", "保护", 4)),
     card("附魔书", ("fire_protection", "火焰保护", 2))], dm)
assert len(clusters) == 2, f"两个独立簇应检出 2 组，实际 {len(clusters)}"
all_ids = [{m["id"] for m in c} for c in clusters]
assert {"sharpness", "smite"} in all_ids and {"protection", "fire_protection"} in all_ids
print("1e. 两个独立簇分别检出 ✓")

# ========== 2. 对话框 ==========
clusters = find_conflict_clusters(
    [card("剑", ("sharpness", "锋利", 5)),
     card("附魔书", ("smite", "亡灵杀手", 3))], dm)
dlg = ConflictResolveDialog(clusters)
radios = dlg.findChildren(QRadioButton)
assert len(radios) == 2, "应有两个单选按钮"
assert radios[0].isChecked(), "默认应选中第一个"
texts = [rb.text() for rb in radios]
assert any("锋利" in t and "剑" in t for t in texts), f"单选文本应含附魔名与物品名，实际 {texts}"
assert any("亡灵杀手" in t and "III" in t for t in texts), "单选文本应含罗马数字等级"
radios[1].setChecked(True)
assert dlg.choices() == {0: "smite"}, f"choices 应返回选中项，实际 {dlg.choices()}"
# 多簇：各自独立读取（按按钮文本定位，findChildren 顺序跨 GroupBox 不可靠）
clusters2 = find_conflict_clusters(
    [card("头盔", ("protection", "保护", 4)),
     card("附魔书", ("fire_protection", "火焰保护", 2))], dm)
dlg2 = ConflictResolveDialog(clusters + clusters2)
radios2 = dlg2.findChildren(QRadioButton)
assert len(radios2) == 4
id_by_rb = {}
for ci, pairs in enumerate(dlg2._radios):
    for eid, rb in pairs:
        id_by_rb[rb] = (ci, eid)
checked = [rb for rb in radios2 if rb.isChecked()]
assert len(checked) == 2, "每簇应恰好默认选中一项"
for rb in checked:
    ci, eid = id_by_rb[rb]
    rb.setChecked(False)
# 簇 0 勾选亡灵杀手，簇 1 勾选保护
for rb, (ci, eid) in id_by_rb.items():
    if (ci, eid) in {(0, "smite"), (1, "protection")}:
        rb.setChecked(True)
c = dlg2.choices()
assert c == {0: "smite", 1: "protection"}, f"多簇 choices 应独立，实际 {c}"
print("2. 对话框：默认选中/choices 读取/多簇独立 ✓")

# 2b. defaults 预选上次决策
dlg3 = ConflictResolveDialog(clusters + clusters2,
                             defaults={0: "sharpness", 1: "fire_protection"})
checked3 = {eid for pairs in dlg3._radios for eid, rb in pairs if rb.isChecked()}
assert checked3 == {"sharpness", "fire_protection"}, \
    f"defaults 应预选上次决策，实际 {checked3}"
# defaults 中的 ID 不在簇内（卡片已变）→ 回退选第一个
dlg4 = ConflictResolveDialog(clusters, defaults={0: "protection"})
checked4 = {eid for pairs in dlg4._radios for eid, rb in pairs if rb.isChecked()}
assert len(checked4) == 1 and checked4 <= {"sharpness", "smite"}, \
    f"无效 defaults 应回退选第一个，实际 {checked4}"
# 文案：不再宣称"从卡片移除"，且说明未保留附魔仍计费
from PySide6.QtWidgets import QLabel
tip_text = " ".join(lb.text() for lb in dlg4.findChildren(QLabel))
assert "移除" not in tip_text, f"文案不应包含'移除'，实际 {tip_text}"
assert "计入合成花费" in tip_text, "文案应说明未保留附魔仍计费"
print("2b. defaults 预选/无效回退/文案不提移除 ✓")

# ========== 3. remove_enchants_everywhere ==========
lst = CardListWidget()
lst.add_card(card("剑", ("sharpness", "锋利", 5), ("unbreaking", "耐久", 3)))
lst.add_card(card("附魔书", ("smite", "亡灵杀手", 3), ("power", "力量", 5)))
lst.add_card(card("弓", ("power", "力量", 4)))
app.processEvents()

before_sword = lst.item(0).data(lst.CARD_DATA_ROLE)
before_bow = lst.item(2).data(lst.CARD_DATA_ROLE)
lst.remove_enchants_everywhere({"附魔书": ["smite"]})
app.processEvents()
book_data = lst.item(1).data(lst.CARD_DATA_ROLE)
assert [e["id"] for e in book_data["enchants"]] == ["power"], \
    f"附魔书卡片应仅剩力量，实际 {book_data['enchants']}"
assert lst.card_enchant_ids(lst.item(1)) == ["power"], "CARD_IDS_ROLE 应同步更新"
rebuilt = lst.itemWidget(lst.item(1))
assert rebuilt is not None, "受影响卡片控件应重建"
assert lst.item(0).data(lst.CARD_DATA_ROLE) == before_sword, "无关节卡（剑）数据不应变化"
assert lst.item(2).data(lst.CARD_DATA_ROLE) == before_bow, "无关节卡（弓）数据不应变化"
# 移除后同物品不存在指定附魔：无变化不报错
lst.remove_enchants_everywhere({"附魔书": ["smite"]})
app.processEvents()
assert [e["id"] for e in lst.item(1).data(lst.CARD_DATA_ROLE)["enchants"]] == ["power"]
print("3. remove_enchants_everywhere：目标卡移除重绘/无关节卡不动/幂等 ✓")

# ========== 4. 集成：冲突统一在开始计算时处理 ==========
import Tools.tool_EnchantCaculator as tec
from PySide6.QtWidgets import QDialog
from PySide6.QtCore import QObject


class FakeDlg:
    """替换 ConflictResolveDialog：自动应答（_keep=None → 拒绝；否则保留该附魔）"""
    DialogCode = QDialog.DialogCode
    _keep = None
    instances = []

    def __init__(self, clusters, parent=None, defaults=None):
        self.clusters = clusters
        self.defaults = defaults
        FakeDlg.instances.append(self)

    def exec(self):
        return QDialog.Accepted if FakeDlg._keep is not None else QDialog.Rejected

    def choices(self):
        for ci, members in enumerate(self.clusters):
            if any(m["id"] == FakeDlg._keep for m in members):
                return {ci: FakeDlg._keep}
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


tec.ConflictResolveDialog = FakeDlg
tec.QMessageBox = FakeMsgBox

w = tec.EnchantCalculatorWidget()
w.resize(658, 518)
w.show()
app.processEvents()

# 4a. 添加无冲突物品：不弹窗
FakeDlg._keep = None
FakeDlg.instances.clear()
w.add_item_card(card("剑", ("sharpness", "锋利", 5), ("unbreaking", "耐久", 3)))
app.processEvents()
assert FakeDlg.instances == [], "无冲突不应弹窗"
assert w.conflict_choices == {}, "无冲突时决策应为空"
print("4a. 添加无冲突物品不弹窗 ✓")

# 4b. 新语义：添加带互斥附魔的物品 → 也不弹窗（决策保持现状）
FakeDlg._keep = "smite"
w.add_item_card(card("附魔书", ("smite", "亡灵杀手", 3), ("power", "力量", 5)))
app.processEvents()
assert FakeDlg.instances == [], "添加阶段不应弹冲突窗（统一在开始计算时处理）"
assert w.conflict_choices == {}, "添加阶段决策应保持空"
print("4b. 添加带互斥附魔的物品不弹窗（新语义）✓")

# 4c. 开始计算：锋利在唯一剑上 → 自动决策不弹窗，卡片不变
FakeDlg._keep = None
FakeDlg.instances.clear()
FakeMsgBox.calls.clear()
w.do_start_calculate()
app.processEvents()
assert FakeDlg.instances == [], "唯一剑上的锋利应自动决策，不弹窗"
assert w.conflict_choices == {0: "sharpness"}, \
    f"自动决策应记录保留锋利，实际 {w.conflict_choices}"
assert FakeMsgBox.calls == [], f"应计算成功无警告，实际 {FakeMsgBox.calls}"
book_data = w.chosenItemList.item(1).data(w.chosenItemList.CARD_DATA_ROLE)
assert [e["id"] for e in book_data["enchants"]] == ["smite", "power"], \
    f"卡片不应被移除任何附魔（未保留的仍计费），实际 {book_data['enchants']}"
sword_data = w.chosenItemList.item(0).data(w.chosenItemList.CARD_DATA_ROLE)
assert [e["id"] for e in sword_data["enchants"]] == ["sharpness", "unbreaking"], "剑卡应保持不变"
fb = w.realSteps.final_box()
assert fb is not None and fb.anvil_item.has_enchant("sharpness") and \
    not fb.anvil_item.has_enchant("smite"), "最终合成物应含锋利不含亡灵杀手"
print("4c. 开始计算：剑锋利自动决策（不弹窗），卡片不变 ✓")

# 4d. 全书冲突 → 开始计算时弹窗，选择保留亡灵杀手 → 决策记录，卡片不变
w2 = tec.EnchantCalculatorWidget()
w2.add_item_card(card("附魔书", ("sharpness", "锋利", 5)))
w2.add_item_card(card("附魔书", ("smite", "亡灵杀手", 3), ("power", "力量", 5)))
app.processEvents()
FakeDlg._keep = "smite"
FakeDlg.instances.clear()
FakeMsgBox.calls.clear()
w2.do_start_calculate()
app.processEvents()
assert len(FakeDlg.instances) == 1, "全书冲突应弹窗一次"
assert w2.conflict_choices == {0: "smite"}, \
    f"确定后决策应记录为保留亡灵杀手，实际 {w2.conflict_choices}"
assert FakeMsgBox.calls == [], f"应计算成功无警告，实际 {FakeMsgBox.calls}"
data1 = w2.chosenItemList.item(1).data(w2.chosenItemList.CARD_DATA_ROLE)
assert [e["id"] for e in data1["enchants"]] == ["smite", "power"], \
    f"卡片不应被移除任何附魔，实际 {data1['enchants']}"
fb2 = w2.realSteps.final_box()
assert fb2 is not None and fb2.anvil_item.has_enchant("smite") and \
    not fb2.anvil_item.has_enchant("sharpness"), "最终合成物应含亡灵杀手不含锋利"
print("4d. 全书冲突：弹窗选择保留亡灵杀手，卡片不变 ✓")

# 4e. 再次计算：弹窗预选上次决策（defaults 映射）；改选锋利 → 决策更新
FakeDlg._keep = "sharpness"
FakeDlg.instances.clear()
w2.do_start_calculate()
app.processEvents()
assert len(FakeDlg.instances) == 1
assert FakeDlg.instances[0].defaults == {0: "smite"}, \
    f"弹窗应预选上次决策，实际 {FakeDlg.instances[0].defaults}"
assert w2.conflict_choices == {0: "sharpness"}, \
    f"改选锋利后决策应更新，实际 {w2.conflict_choices}"
fb3 = w2.realSteps.final_box()
assert fb3 is not None and fb3.anvil_item.has_enchant("sharpness") and \
    not fb3.anvil_item.has_enchant("smite"), "决策更新后最终合成物应含锋利"
print("4e. 再次计算：预选上次决策 + 改选更新（卡片始终不变）✓")

w.close()
w2.close()
print("\n全部冒烟测试通过")
