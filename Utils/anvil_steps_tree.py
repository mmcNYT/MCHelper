# utils/anvil_steps_tree.py
# 铁砧合成步骤树控件：把优化器输出的合并方案渲染成树状图。
#
# 展示约定（与铁砧界面对应）：
# - 每个内部节点是一次铁砧操作：左侧子节点 = 目标物品（铁砧第一格/左），
#   右侧子节点 = 牺牲物品（铁砧第二格/右）
# - 节点文本：物品描述 + （内部节点）本次花费；根节点带总花费标记
# - 步骤按执行顺序编号（第1步先做），计费明细放在各操作节点的子说明中
from PySide6.QtWidgets import (QTreeWidget, QTreeWidgetItem, QAbstractItemView)
from PySide6.QtGui import QColor, QBrush, QFont, QPalette

from Utils.anvil_optimizer import AnvilPlan, MergeStep

_TEXT_BASE = QColor(60, 60, 60)        # 普通文字
_TEXT_STEP = QColor(30, 30, 160)       # 步骤标题（蓝）
_TEXT_RESULT = QColor(0, 110, 40)      # 合成结果（绿）
_TEXT_WARN = QColor(190, 30, 30)       # 过于昂贵警告（红）


class AnvilStepsTree(QTreeWidget):
    """铁砧合成步骤树：根=最终合成物，子树=每次合并（左目标/右牺牲）

    用法：
        tree = AnvilStepsTree()
        tree.show_plan(plan)   # plan: AnvilOptimizer.optimize() 的返回值
        tree.clear_plan()      # 清空回到占位提示
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(1)
        self.setHeaderHidden(True)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setExpandsOnDoubleClick(True)
        self.setIndentation(22)
        self.setAnimated(True)
        # 视口淡灰背景（与卡片列表画布一致）
        vp = self.viewport()
        pal = vp.palette()
        pal.setColor(QPalette.Base, QColor("#ECECEC"))
        vp.setPalette(pal)
        vp.setAutoFillBackground(True)
        self._placeholder = "添加物品后点击「开始计算」，这里将显示最优合成步骤"
        self.clear_plan()

    # ---------- 对外接口 ----------
    def clear_plan(self):
        """清空树并显示占位提示"""
        self.clear()
        root = QTreeWidgetItem([self._placeholder])
        root.setDisabled(True)
        f = root.font(0)
        f.setItalic(True)
        root.setFont(0, f)
        root.setForeground(0, QBrush(QColor(140, 140, 140)))
        self.addTopLevelItem(root)

    def show_plan(self, plan: AnvilPlan, data_manager=None):
        """渲染完整合并方案

        plan: AnvilOptimizer.optimize() 返回的 AnvilPlan
        data_manager: 可选，用于把附魔 ID 翻译为中文名（detail 中使用）
        """
        self.clear()
        if not plan.steps:
            # 单物品：无步骤，直接展示物品
            root = self._make_label_item(f"{plan.final_item.label}", bold=True)
            self.addTopLevelItem(root)
            return

        # 根节点 = 最终合成物
        root_text = (f"最终合成物：{plan.final_item.label}"
                     f"　—　总花费 {plan.total_cost} 级")
        root = self._make_label_item(root_text, bold=True,
                                     color=_TEXT_RESULT)
        if plan.too_expensive_steps:
            warn = QTreeWidgetItem(
                [f"（注意：第 {'、'.join(map(str, plan.too_expensive_steps))} 步"
                 f" 花费超过 39 级，生存模式中铁砧会显示「过于昂贵！」）"])
            warn.setForeground(0, QBrush(_TEXT_WARN))
            root.addChild(warn)
        self.addTopLevelItem(root)

        # 按"最后一次合并为根"递归构建树：步骤列表天然是自底向上的执行序
        self._build_nodes(root, plan.steps, len(plan.steps) - 1,
                          plan.steps[-1].result, data_manager)
        self.expandAll()

    # ---------- 内部构建 ----------
    def _build_nodes(self, parent_item, steps: list, idx: int,
                     expected_result, data_manager):
        """递归构建：steps[idx] 的 result 应等于 expected_result

        步骤按执行序排列，后面的步骤消费前面的产物——从最后一步
        向前回溯：某步的 target/sacrifice 若是此前某步的 result，
        则该子节点继续展开为那一步。
        """
        step = steps[idx]
        node = QTreeWidgetItem([f"第 {idx + 1} 步（花费 {step.cost} 级）"])
        node.setForeground(0, QBrush(_TEXT_STEP))
        bold = QFont()
        bold.setBold(True)
        node.setFont(0, bold)
        parent_item.addChild(node)

        # 明细子节点（计费细节）
        if step.detail:
            detail_text = self._detail_text(step, data_manager)
            if detail_text:
                d = QTreeWidgetItem([detail_text])
                d.setForeground(0, QBrush(_TEXT_BASE))
                node.addChild(d)

        # 左子节点 = 目标物品；右子节点 = 牺牲物品
        for item_obj, role in ((step.target, "目标（左格）"),
                               (step.sacrifice, "牺牲（右格）")):
            child_idx = self._find_producer(steps, idx, item_obj)
            if child_idx is not None:
                # 该物品是之前某步的产物 → 递归展开
                self._build_nodes(node, steps, child_idx, item_obj,
                                  data_manager)
            else:
                # 叶子：原始卡片物品
                leaf = QTreeWidgetItem([f"[{role}] {item_obj.label}"])
                leaf.setForeground(0, QBrush(_TEXT_BASE))
                node.addChild(leaf)

    @staticmethod
    def _find_producer(steps: list, before: int, item):
        """在 steps[0..before) 中找到产出 item 的步骤序号

        AnvilItem 不可变且字段相等即视为同一物品（dataclass eq）；
        产物一旦被后续步骤消费就不会再被复用，故从后往前找最近的
        产出者即可唯一确定父子关系。
        """
        for k in range(before - 1, -1, -1):
            if steps[k].result == item:
                return k
        return None

    def _detail_text(self, step: MergeStep, data_manager) -> str:
        """把计费明细拼成一段说明文字"""
        parts = []
        d = step.detail
        if d.get("pwp_cost"):
            parts.append(f"累积惩罚 {d['pwp_cost']} 级")
        for eid, lv, fee, reason in d.get("enchant_costs", []):
            name = eid
            if data_manager is not None:
                ench = data_manager.get_enchant_by_id(eid)
                if ench:
                    name = ench["name"]
            parts.append(f"{name}：{reason}，+{fee} 级")
        for eid, reason in d.get("ignored", []):
            name = eid
            if data_manager is not None:
                ench = data_manager.get_enchant_by_id(eid)
                if ench:
                    name = ench["name"]
            parts.append(f"{name}：{reason}")
        return "；".join(parts)

    @staticmethod
    def _make_label_item(text: str, bold=False, color=None) -> QTreeWidgetItem:
        item = QTreeWidgetItem([text])
        if bold:
            f = item.font(0)
            f.setBold(True)
            item.setFont(0, f)
        if color is not None:
            item.setForeground(0, QBrush(color))
        return item
