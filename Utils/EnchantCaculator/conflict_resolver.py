# utils/conflict_resolver.py
# 跨卡片附魔冲突检测与解决：
# 多件物品最终合成到一件时，互斥附魔（conflicts 列表）不能共存于最终合成物。
# 冲突处理规则（供开始计算时统一调用）：
# - 自动决策：出现在全部非附魔书卡片上的附魔必然保留——非书物品在所有
#   合并中只能做铁砧第一格，其附魔必定传入最终合成物（且互斥附魔不可能
#   同时存在于同一物品上把它拦掉）。这类冲突无需询问用户，如只有一把剑
#   且剑上有锋利，锋利必保留，书上的亡灵杀手必然被拦截计费。
# - 其余冲突弹窗让用户为每组选择最终合成物要保留的附魔。
# 注意：弹窗只记录决策，不从卡片移除任何附魔——未保留的附魔仍留在卡片上
# 并正常计入合成花费（互斥不转移时每次 +1 级），只是不会出现在最终合成物中。
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QGroupBox, QRadioButton, QLabel,
    QPushButton, QHBoxLayout
)

from Utils.EnchantCaculator.enchanted_item_card import int_to_roman


def find_conflict_clusters(cards_data: list, data_manager) -> list:
    """检测多张卡片之间互斥的附魔，按冲突关系聚簇

    算法：把当前所有卡片上存在的附魔作为节点，互斥关系作为边，
    用并查集连成簇（如 锋利×亡灵杀手×节肢杀手 三者两两互斥 → 一个簇）。
    同一附魔出现在多张卡片不构成冲突（合成时正常合并等级），自动按 id 去重。

    参数：
        cards_data: 卡片数据列表
                    [{"item_name": str, "enchants": [{"id","name","level"}, ...]}, ...]
        data_manager: DataManager 单例（提供 get_conflicts 查询）

    返回：
        需要用户决策的簇列表（仅簇内存在 ≥2 种不同附魔时），
        每簇为成员信息列表（簇内按 id 排序，簇间按首个 id 排序保证顺序稳定）：
            [{"id": str, "name": str, "level": int(最高等级), "items": [物品名, ...]}, ...]
    """
    # 1. 汇总当前存在的附魔（同 id 多卡片合并：等级取最高，物品名去重收集）
    present = {}
    for card in cards_data:
        item_name = card.get("item_name", "")
        for e in card.get("enchants", []):
            ent = present.setdefault(e["id"], {
                "id": e["id"],
                "name": e.get("name", e["id"]),
                "level": 0,
                "items": [],
            })
            ent["level"] = max(ent["level"], e.get("level", 1))
            if item_name and item_name not in ent["items"]:
                ent["items"].append(item_name)

    # 2. 并查集：互斥且同时存在的附魔连成一个簇
    parent = {eid: eid for eid in present}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # 路径压缩
            x = parent[x]
        return x

    for eid in list(present):
        for cid in data_manager.get_conflicts(eid):
            if cid in present:
                ra, rb = find(eid), find(cid)
                if ra != rb:
                    parent[rb] = ra

    # 3. 收集簇，只保留需要决策的（≥2 种不同附魔）
    groups = {}
    for eid in present:
        groups.setdefault(find(eid), []).append(present[eid])

    clusters = [sorted(members, key=lambda m: m["id"])
                for members in groups.values() if len(members) > 1]
    clusters.sort(key=lambda ms: ms[0]["id"])
    return clusters


def resolve_conflicts(clusters: list, cards_data: list) -> tuple:
    """把冲突簇分为「自动决策」与「需用户决策」两组（开始计算时调用）

    自动决策规则：附魔出现在**全部**非附魔书卡片上 → 必然保留。
    依据：最终合成物由某张非书卡片沿铁砧第一格链传递而来，非书物品永远
    做第一格（附魔书不能吞非书物品），其自带附魔不可被移除；且互斥附魔
    不可能同时存在于同一物品上把它拦掉。如：只有一把剑且剑上有锋利，
    锋利必保留，书上的亡灵杀手必然被拦截——冲突虽存在但可直接忽略。

    参数：
        clusters: find_conflict_clusters 返回的簇列表
        cards_data: 卡片数据列表（同 find_conflict_clusters 入参）

    返回：
        (auto_choices, pending_clusters)
        auto_choices: {簇序号(相对传入 clusters): 必然保留的附魔 ID}
        pending_clusters: 仍需用户决策的簇列表（保持原相对顺序）
    """
    non_book_cards = [c for c in cards_data
                      if c.get("item_name") and c["item_name"] != "附魔书"]
    auto = {}
    pending = []
    if non_book_cards:
        # 全部非书卡片共有的附魔 = 必然保留的附魔
        common = {e["id"] for e in non_book_cards[0].get("enchants", [])}
        for c in non_book_cards[1:]:
            common &= {e["id"] for e in c.get("enchants", [])}
        for ci, members in enumerate(clusters):
            kept = [m["id"] for m in members if m["id"] in common]
            # 簇内恰有一个必然保留方 → 整簇自动决策：该附魔保留，
            # 簇内其余附魔注定被拦截计费（如 锋利×保护×爆炸保护 三者
            # 互斥成一簇，锋利在剑上 → 保护/爆炸保护无需选择，均被拦截）；
            # 零个 → 需用户选择；多个（同一卡片自带两个互斥附魔，正常
            # 操作无法产生）→ 交回弹窗，由优化器对任一选择给出精确报错
            if len(kept) == 1:
                auto[ci] = kept[0]
            else:
                pending.append(members)
    else:
        pending = list(clusters)
    return auto, pending


class ConflictResolveDialog(QDialog):
    """附魔冲突选择对话框：每个冲突簇一组单选，用户勾选最终合成物保留的附魔

    用法：
        dlg = ConflictResolveDialog(clusters, parent, defaults=last_choices)
        if dlg.exec() == QDialog.Accepted:
            choices = dlg.choices()   # {簇序号: 保留的附魔 ID}
    决策由调用方作为 required_enchants 约束传给优化器；
    本对话框不修改任何卡片数据（未保留的附魔也计费，不从卡片移除）。
    """

    def __init__(self, clusters: list, parent=None, defaults: dict = None):
        """defaults: 可选 {簇序号: 附魔ID}，预选上次的保留决策"""
        super().__init__(parent)
        self.setWindowTitle("检测到附魔冲突")
        self.setMinimumWidth(380)
        defaults = defaults or {}

        layout = QVBoxLayout(self)
        tip = QLabel("以下附魔互斥，不能同时存在于同一件物品。\n"
                     "请为每组选择最终合成物要保留的附魔。\n"
                     "未选中的附魔仍保留在卡片上并正常计入合成花费，"
                     "只是因互斥不会出现在最终合成物中：")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        # 每簇一个组框，组内每个附魔一个单选按钮
        # （预选 defaults 中记录的决策，无记录时选第一个）
        self._radios = []  # self._radios[簇序号] = [(附魔ID, QRadioButton), ...]
        for ci, members in enumerate(clusters):
            box = QGroupBox(f"冲突 {ci + 1}（{len(members)} 个附魔互斥）")
            vbox = QVBoxLayout(box)
            preselect = defaults.get(ci)
            pairs = []
            for m in members:
                items_text = "、".join(m["items"]) if m["items"] else "未知物品"
                rb = QRadioButton(
                    f"{m['name']} {int_to_roman(m['level'])} —— {items_text}")
                vbox.addWidget(rb)
                pairs.append((m["id"], rb))
            checked = False
            if preselect is not None:
                for eid, rb in pairs:
                    if eid == preselect:
                        rb.setChecked(True)
                        checked = True
                        break
            if not checked:
                pairs[0][1].setChecked(True)
            self._radios.append(pairs)
            layout.addWidget(box)

        # 按钮：确定（应用选择）/ 暂不处理（保持现状，冲突保留）
        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        ok_btn = QPushButton("确定")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        later_btn = QPushButton("暂不处理")
        later_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(later_btn)
        layout.addLayout(btn_layout)

    def choices(self) -> dict:
        """读取用户选择：{簇序号: 保留的附魔 ID}

        该决策将作为 required_enchants 约束传给优化器；
        未被选中的附魔不从卡片移除（仍计费）。
        """
        result = {}
        for ci, pairs in enumerate(self._radios):
            for eid, rb in pairs:
                if rb.isChecked():
                    result[ci] = eid
                    break
        return result
