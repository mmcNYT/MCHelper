# -*- coding: utf-8 -*-
"""冒烟测试：铁砧合成步骤图（图形化方框树，QGraphicsView 版）

1. 占位提示（初始）
2. 单物品方案（无步骤，仅最终框 + 总花费文字；无 dm 时附魔名回退 ID）
3. 多步方案结构：框数 = 物品数 + 步骤数、身份链（左=目标/右=牺牲）、
   层级（父框在子框下方）、圆标数字与步骤花费一致、tooltip 内容
4. 递归展开（5 物品 4 步全嵌套渲染）
5. 过于昂贵（红圆标态 + 画布警告文字 + 圆标 tooltip 红字警告行）
6. 身份匹配回归：两对值完全相同的书（值相等 ≠ 同一对象，防重复展开）
7. clear_plan 恢复占位
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication, QGraphicsSimpleTextItem

app = QApplication(sys.argv)

from Utils.enchant_data_manager import DataManager
from Utils.anvil_optimizer import (AnvilOptimizer, AnvilItem, AnvilPlan,
                                   MergeStep, AnvilMechanics)
from Utils.anvil_steps_tree import AnvilStepsTree
from Utils.enchanted_item_card import TOOLTIP_HEADER, TOOLTIP_TEXT

dm = DataManager()
opt = AnvilOptimizer(dm)
tree = AnvilStepsTree()
tree.resize(700, 520)
tree.show()
app.processEvents()


def scene_texts():
    """场景中全部静态文字（总花费 / 警告 / 占位提示）"""
    return [it.text() for it in tree.scene().items()
            if isinstance(it, QGraphicsSimpleTextItem)]


def check_identity_chain(plan):
    """结构不变式：每步恰有一个产物框；其左框=目标（铁砧第一格）、
    右框=牺牲（第二格），均按对象身份一致；目标框在牺牲框左侧、
    产物框在两输入框下方；final_box 即方案最终合成物"""
    for k, step in enumerate(plan.steps):
        box = next((b for b in tree.boxes()
                    if b.anvil_item is step.result), None)
        assert box is not None, f"第 {k+1} 步缺少产物框"
        assert box.left_box is not None and \
            box.left_box.anvil_item is step.target, \
            f"第 {k+1} 步左框应为目标（第一格）物品"
        assert box.right_box is not None and \
            box.right_box.anvil_item is step.sacrifice, \
            f"第 {k+1} 步右框应为牺牲（第二格）物品"
        assert box.left_box.x() < box.right_box.x(), \
            f"第 {k+1} 步目标框应在牺牲框左侧"
        assert box.y() > box.left_box.y() and box.y() > box.right_box.y(), \
            f"第 {k+1} 步产物框应在两输入框下方"
    fb = tree.final_box()
    assert fb is not None and fb.role == "final"
    assert fb.anvil_item is plan.final_item, "最终框应为方案最终合成物"


# ========== 1. 占位提示 ==========
assert tree.is_placeholder()
assert "开始计算" in tree.placeholder_text
assert tree.boxes() == [] and tree.cost_circles() == []
assert tree.final_box() is None
assert any("开始计算" in t for t in scene_texts())
print("1. 初始占位提示 ✓")

# ========== 2. 单物品方案（无 data_manager，附魔名回退 ID）==========
sword = AnvilItem.make("剑", [("sharpness", 5)])
tree.show_plan(AnvilPlan(steps=[], total_cost=0, final_item=sword))
assert not tree.is_placeholder()
assert len(tree.boxes()) == 1 and tree.cost_circles() == []
fb = tree.final_box()
assert fb.anvil_item is sword and fb.role == "final"
assert any("总花费 0 级" in t for t in scene_texts())
lines = fb._tooltip_lines()
assert lines[0] == ("剑", TOOLTIP_HEADER)
assert any(t == "sharpness V" for t, _ in lines), \
    f"无 dm 时附魔行应回退 ID + 罗马数字，实际 {lines}"
print("2. 单物品方案直接展示物品 ✓")

# ========== 3. 多步方案结构 ==========
items = [
    AnvilItem.make("剑", []),
    AnvilItem.make("附魔书", [("sharpness", 5)]),
    AnvilItem.make("附魔书", [("looting", 3)]),
]
plan = opt.optimize(items)
tree.show_plan(plan, dm)
assert not tree.is_placeholder()
assert len(tree.boxes()) == len(items) + len(plan.steps), \
    f"框数应 = 物品数 + 步骤数 = {len(items) + len(plan.steps)}"
assert len(tree.cost_circles()) == len(plan.steps)
circles = sorted(tree.cost_circles(), key=lambda c: c.step_no)
assert [c.step_no for c in circles] == list(range(1, len(plan.steps) + 1))
assert all(c.step is plan.steps[c.step_no - 1] for c in circles)
assert [c.cost for c in circles] == [s.cost for s in plan.steps]
assert sum(c.cost for c in circles) == plan.total_cost
assert all(not c.is_too_expensive for c in circles)
check_identity_chain(plan)
leaves = [b for b in tree.boxes() if b.left_box is None]
assert len(leaves) == len(items), "叶子框数应等于原始物品数"
assert any(f"总花费 {plan.total_cost} 级" in t for t in scene_texts())
# 物品框 tooltip（有 dm：附魔中文名 + 罗马数字）
sharp_box = next(b for b in tree.boxes() if b.anvil_item is items[1])
lines = sharp_box._tooltip_lines()
assert lines[0] == ("附魔书", TOOLTIP_HEADER)
assert ("锋利 V", TOOLTIP_TEXT) in lines
assert ("抢夺 III", TOOLTIP_TEXT) not in lines
loot_box = next(b for b in tree.boxes() if b.anvil_item is items[2])
assert ("抢夺 III", TOOLTIP_TEXT) in loot_box._tooltip_lines()
# 圆标 tooltip：标题行 + 计费明细（无过于昂贵警告）
tl = circles[0]._tooltip_lines()
assert tl[0][0] == f"第 1 步 · 花费 {circles[0].cost} 级"
assert any("级" in t for t, _ in tl[1:])
assert not any("过于昂贵" in t for t, _ in tl)
# 悬浮框组件：show_tooltip / hide_tooltip
tree.show_tooltip([("测试", TOOLTIP_HEADER)])
app.processEvents()
assert not tree._tooltip.isHidden(), "show_tooltip 后悬浮框应可见"
tree.hide_tooltip()
assert tree._tooltip.isHidden(), "hide_tooltip 后悬浮框应隐藏"
print(f"3. 多步方案（{len(plan.steps)} 步 / {len(tree.boxes())} 框 / "
      f"总花费 {plan.total_cost} 级）✓")

# ========== 4. 递归展开（5 物品 4 步）==========
items4 = [
    AnvilItem.make("剑", []),
    AnvilItem.make("附魔书", [("sharpness", 5)]),
    AnvilItem.make("附魔书", [("looting", 3)]),
    AnvilItem.make("附魔书", [("unbreaking", 3)]),
    AnvilItem.make("附魔书", [("sweeping_edge", 3)]),
]
plan4 = opt.optimize(items4)
tree.show_plan(plan4, dm)
assert len(tree.boxes()) == 9, f"5 物品 + 4 步 = 9 框，实际 {len(tree.boxes())}"
assert sorted(c.step_no for c in tree.cost_circles()) == [1, 2, 3, 4]
assert sum(c.cost for c in tree.cost_circles()) == plan4.total_cost
check_identity_chain(plan4)
assert len([b for b in tree.boxes() if b.left_box is None]) == 5
print(f"4. 递归展开：{len(plan4.steps)} 步全嵌套渲染，"
      f"总花费 {plan4.total_cost} 级 ✓")

# ========== 5. 过于昂贵 ==========
# 手工构造高惩罚步骤：PWP 31 的剑 + PWP 7 的耐久书 → 花费必然 ≥40
t5 = AnvilItem.make("剑", [("sharpness", 5)], 31)
s5 = AnvilItem.make("附魔书", [("unbreaking", 3)], 7)
res5, cost5, detail5 = AnvilMechanics(dm).merge(t5, s5)
assert cost5 >= 40, f"构造的花费应 ≥40，实际 {cost5}"
plan5 = AnvilPlan(steps=[MergeStep(t5, s5, res5, cost5, detail5)],
                  total_cost=cost5, final_item=res5,
                  too_expensive_steps=[1])
tree.show_plan(plan5, dm)
assert len(tree.cost_circles()) == 1
c5 = tree.cost_circles()[0]
assert c5.is_too_expensive, "花费 ≥40 的步骤圆标应为红色态"
tl5 = c5._tooltip_lines()
assert any("过于昂贵" in t for t, _ in tl5), "圆标 tooltip 应含过于昂贵警告"
assert any("过于昂贵" in t for t in scene_texts()), "画布应绘制过于昂贵警告文字"
assert any("累积惩罚 38 级" in t for t, _ in tl5), "计费明细应含 PWP 行"
print(f"5. 过于昂贵（花费 {cost5} 级 → 红圆标 + 警告）✓")

# ========== 6. 身份匹配回归：两对值完全相同的书 ==========
# 4 本相同的锋利V书两两合并会产出两个值完全相同的中间书；
# 若按值相等匹配产出者，会把同一产出步骤展开两次、丢失另一半原始物品
items6 = [AnvilItem.make("附魔书", [("sharpness", 5)]) for _ in range(4)]
plan6 = opt.optimize(items6)
tree.show_plan(plan6, dm)
assert len(tree.boxes()) == 7, f"4 书 + 3 步 = 7 框，实际 {len(tree.boxes())}"
assert sorted(c.step_no for c in tree.cost_circles()) == [1, 2, 3], \
    "每个步骤应恰好出现一次（步骤 1 不应丢失）"
check_identity_chain(plan6)
assert len([b for b in tree.boxes() if b.left_box is None]) == 4, \
    "4 本原始书应全部作为叶子出现"
print("6. 相同值中间产物身份匹配（4 本相同的书）✓")

# ========== 7. clear_plan 恢复占位 ==========
tree.clear_plan()
assert tree.is_placeholder()
assert tree.boxes() == [] and tree.cost_circles() == []
assert tree.final_box() is None
assert any("开始计算" in t for t in scene_texts())
print("7. clear_plan 恢复占位提示 ✓")

print("\n全部冒烟测试通过")
