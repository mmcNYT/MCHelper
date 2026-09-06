# -*- coding: utf-8 -*-
"""冒烟测试：铁砧合成步骤树控件
1. 占位提示（初始/清空后）
2. 单物品方案（无步骤）
3. 多步方案树结构（根=最终合成物，步骤节点，左=目标右=牺牲叶子）
4. 递归展开（中间产物节点）
5. 过于昂贵警告行
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from Utils.enchant_data_manager import DataManager
from Utils.anvil_optimizer import AnvilOptimizer, AnvilItem, AnvilPlan
from Utils.anvil_steps_tree import AnvilStepsTree

dm = DataManager()
opt = AnvilOptimizer(dm)
tree = AnvilStepsTree()
tree.resize(500, 400)

# ========== 1. 占位提示 ==========
assert tree.topLevelItemCount() == 1
assert "开始计算" in tree.topLevelItem(0).text(0)
assert tree.topLevelItem(0).isDisabled(), "占位行应为禁用态"
print("1. 初始占位提示 ✓")

# ========== 2. 单物品方案 ==========
single = AnvilPlan(steps=[], total_cost=0,
                   final_item=AnvilItem.make("剑", [("sharpness", 5)]))
tree.show_plan(single)
assert tree.topLevelItemCount() == 1
assert "剑" in tree.topLevelItem(0).text(0)
print("2. 单物品方案直接展示物品 ✓")

# ========== 3. 多步方案树结构 ==========
items = [
    AnvilItem.make("剑", []),
    AnvilItem.make("附魔书", [("sharpness", 5)]),
    AnvilItem.make("附魔书", [("looting", 3)]),
]
plan = opt.optimize(items)
tree.show_plan(plan, dm)
assert tree.topLevelItemCount() == 1, "应只有一个根节点"
root = tree.topLevelItem(0)
assert "最终合成物" in root.text(0) and "总花费" in root.text(0), root.text(0)
assert plan.total_cost > 0 and str(plan.total_cost) in root.text(0)
# 根下应有步骤节点
step_nodes = [root.child(i) for i in range(root.childCount())
              if root.child(i).text(0).startswith("第")]
assert len(step_nodes) >= 1, "应至少有一个步骤节点"
# 最后一步节点：目标应是上一步产物的递归节点，牺牲是原始物品叶子
last_step = step_nodes[0]
children = [last_step.child(i) for i in range(last_step.childCount())]
rec = [c for c in children if c.text(0).startswith("第")]
leaf = [c for c in children if c.text(0).startswith("[")]
detail = [c for c in children if c.text(0) not in
          {c.text(0) for c in rec + leaf}]
assert len(rec) == 1 and len(leaf) == 1, \
    f"最后一步应为 1 个递归步骤 + 1 个物品叶子，实际 {[c.text(0) for c in children]}"
assert leaf[0].text(0).startswith("[牺牲（右格）]"), \
    f"叶子应为牺牲（右格），实际 {leaf[0].text(0)}"
# 递归的上一级步骤节点下应恰好有两个原始物品叶子（目标在左、牺牲在右）
inner = [rec[0].child(i) for i in range(rec[0].childCount())]
inner_leaves = [c.text(0) for c in inner if c.text(0).startswith("[")]
assert inner_leaves == [f"[目标（左格）] {items[0].display_label(dm)}",
                        f"[牺牲（右格）] {items[1].display_label(dm)}"], inner_leaves
print("3. 多步方案树结构（根/步骤/左右物品/递归）✓")

# ========== 4. 递归展开（中间产物） ==========
# 4 本书的方案必然存在"某步的输入是另一步的产物"——验证嵌套步骤节点存在
items4 = [
    AnvilItem.make("剑", []),
    AnvilItem.make("附魔书", [("sharpness", 5)]),
    AnvilItem.make("附魔书", [("looting", 3)]),
    AnvilItem.make("附魔书", [("unbreaking", 3)]),
    AnvilItem.make("附魔书", [("sweeping_edge", 3)]),
]
plan4 = opt.optimize(items4)
tree.show_plan(plan4, dm)
root = tree.topLevelItem(0)

def walk(item, depth=0):
    """收集全部 (深度, 文本)"""
    out = []
    for i in range(item.childCount()):
        c = item.child(i)
        out.append((depth, c.text(0)))
        out.extend(walk(c, depth + 1))
    return out

all_nodes = walk(root)
step_depths = [d for d, t in all_nodes if t.startswith("第")]
assert len(step_depths) == len(plan4.steps), \
    f"树中步骤节点数 {len(step_depths)} 应等于方案步骤数 {len(plan4.steps)}"
assert max(step_depths) >= 1, "应存在嵌套步骤（中间产物展开）"
# 每个非根步骤节点下都有恰好 2 个物品子节点或递归步骤
print(f"4. 递归展开：{len(plan4.steps)} 个步骤节点，最深 {max(step_depths)+1} 层 ✓")

# ========== 5. 过于昂贵警告 ==========
# 构造一个总花费超 39 的方案：8 本各带多附魔的书合并
items5 = [
    AnvilItem.make("附魔书", [(e, lv)])
    for e, lv in [("thorns", 3), ("protection", 4), ("respiration", 3),
                  ("aqua_affinity", 1), ("unbreaking", 3), ("mending", 1),
                  ("blast_protection", 4), ("fire_protection", 4)]
]
# 全书方案中刺甲/爆炸保护/火焰保护/保护互斥——约束为空时允许只留一个
plan5 = opt.optimize(items5)
tree.show_plan(plan5, dm)
root = tree.topLevelItem(0)
if plan5.too_expensive_steps:
    texts = [root.child(i).text(0) for i in range(root.childCount())]
    assert any("过于昂贵" in t for t in texts), f"应显示过于昂贵警告，实际 {texts}"
    print(f"5. 过于昂贵警告行（步骤 {plan5.too_expensive_steps}）✓")
else:
    # 手工构造带警告的 plan 验证警告行渲染
    fake = AnvilPlan(steps=plan5.steps, total_cost=plan5.total_cost,
                     final_item=plan5.final_item,
                     too_expensive_steps=[2])
    tree.show_plan(fake, dm)
    root = tree.topLevelItem(0)
    texts = [root.child(i).text(0) for i in range(root.childCount())]
    assert any("过于昂贵" in t for t in texts), f"应显示过于昂贵警告，实际 {texts}"
    print("5. 过于昂贵警告行（构造方案）✓")

# ========== 6. clear_plan 恢复占位 ==========
tree.clear_plan()
assert tree.topLevelItemCount() == 1 and "开始计算" in tree.topLevelItem(0).text(0)
print("6. clear_plan 恢复占位提示 ✓")

print("\n全部冒烟测试通过")
