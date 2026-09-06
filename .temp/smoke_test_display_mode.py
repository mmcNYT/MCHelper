# -*- coding: utf-8 -*-
"""冒烟测试：displayMode 展示模式切换（树状图 / 步骤图）

1. 步骤图渲染：每步一行 [目标] + [牺牲] = [产物]，步骤数=行数；
   框数 = 3×步骤数；每步一个花费圆标；最后一行产物框为 final（加粗）
2. 步骤信息标签：每行有「第 N 步 · 花费 X 级」文字
3. 树状图模式保持原行为（show_plan 默认 mode="tree"）
4. displayMode 切换（0→1→0）即时重渲染；无方案时切换不动结果区
5. 清空物品后步骤图恢复占位，切换模式不再重渲染
6. 步骤图模式下圆标 tooltip 仍可用（明细行含计费信息）
7. 过于昂贵步骤：行末标签红色提示
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication, QGraphicsSimpleTextItem
from PySide6.QtCore import QPointF

app = QApplication(sys.argv)

from Utils.anvil_steps_tree import AnvilStepsTree, _ItemBox, _CostCircle
from Utils.enchant_data_manager import DataManager
from Utils.anvil_optimizer import AnvilOptimizer, build_items_from_cards

dm = DataManager()
opt = AnvilOptimizer(dm)


def card(item_name, *enchs):
    return {"item_name": item_name,
            "enchants": [{"id": e[0], "name": e[1], "level": e[2]} for e in enchs]}


# 构造一个 2 步方案：剑 + 锋利书 + 耐久书
cards = [card("剑"),
         card("附魔书", ("sharpness", "锋利", 5)),
         card("附魔书", ("unbreaking", "耐久", 3))]
plan = opt.optimize(build_items_from_cards(cards))
assert len(plan.steps) == 2, len(plan.steps)

# ========== 1. 步骤图渲染 ==========
tree = AnvilStepsTree()
tree.resize(658, 518)
tree.show_plan(plan, dm, mode="steps")
boxes = tree.boxes()
circles = tree.cost_circles()
assert len(circles) == 2, f"2 步应有 2 个圆标，实际 {len(circles)}"
assert len(boxes) == 6, f"每步 3 框，2 步 = 6 框，实际 {len(boxes)}"
# 每行：目标 y == 牺牲 y == 产物 y；产物 x > 牺牲 x > 目标 x
finals = [b for b in boxes if b.role == "final"]
assert len(finals) == 1, f"只应有 1 个 final 框（最后一步产物），实际 {len(finals)}"
fb = finals[0]
# 最后一行 = 第二步：其产物框是 final
by_row = {}
for b in boxes:
    by_row.setdefault(round(b.pos().y()), []).append(b)
assert len(by_row) == 2, f"应有 2 行，实际 {len(by_row)} 行"
rows = sorted(by_row.values(), key=lambda r: r[0].pos().y())
last_row = rows[-1]
assert fb in last_row, "final 框应在最后一行"
for row in rows:
    row.sort(key=lambda b: b.pos().x())
    assert len(row) == 3, f"每行 3 框，实际 {len(row)}"
    assert row[0].pos().x() < row[1].pos().x() < row[2].pos().x(), \
        "行内顺序应为 目标 < 牺牲 < 产物"
    # y 一致（同行）
    assert len({round(b.pos().y()) for b in row}) == 1
# 最后一步产物 = 优化器 final_item
assert fb.anvil_item is plan.final_item or fb.anvil_item == plan.final_item
print("1. 步骤图渲染：每步一行 [目标]+[牺牲]=[产物]，行序正确 ✓")

def _scene_texts(tree):
    """提取场景全部文本项内容（QGraphicsSimpleTextItem 用 text()）"""
    return [it.text() for it in tree._scene.items()
            if isinstance(it, QGraphicsSimpleTextItem)]


# ========== 2. 步骤信息标签 ==========
texts = _scene_texts(tree)
assert any("第 1 步" in t for t in texts), texts
assert any("第 2 步" in t for t in texts), texts
assert any(f"总花费 {plan.total_cost} 级" in t for t in texts), texts
print("2. 步骤信息标签（第 N 步 · 花费 / 总花费）✓")

# ========== 3. 树状图模式默认行为不变 ==========
tree.clear_plan()
tree.show_plan(plan, dm)   # 默认 mode="tree"
tboxes = tree.boxes()
# 剑+书+书 2 步方案树：3 叶子 + 2 合并节点 = 5 框
assert len(tboxes) == 5, f"树模式应有 5 框（3 叶 + 2 合并），实际 {len(tboxes)}"
assert len(tree.final_box().left_box.left_box.__class__ and
           [b for b in tboxes if b.role == "final"]) == 1
print("3. 树状图模式默认行为不变（5 框）✓")

# ========== 4. 模式切换即时重渲染（UI 集成） ==========
import Tools.tool_EnchantCaculator as tec

w = tec.EnchantCalculatorWidget()
w.resize(800, 600)
w.show()
app.processEvents()

# 无方案时切换不动结果区（保持占位）
assert w.realSteps.is_placeholder()
w.displayMode.setCurrentIndex(1)
app.processEvents()
assert w.realSteps.is_placeholder(), "无方案切换模式不应影响占位"

# 加卡片计算（默认树状图）
w.chosenItemList.add_card(cards[0])
w.chosenItemList.add_card(cards[1])
w.chosenItemList.add_card(cards[2])
app.processEvents()
w.displayMode.setCurrentIndex(0)
w.do_start_calculate()
app.processEvents()
assert not w.realSteps.is_placeholder()
assert len(w.realSteps.boxes()) == 5, "树状图模式应显示 5 框树"

# 切到步骤图：即时变为 6 框线性
w.displayMode.setCurrentIndex(1)
app.processEvents()
assert len(w.realSteps.boxes()) == 6, \
    f"切到步骤图应 6 框，实际 {len(w.realSteps.boxes())}"
# 切回树状图：恢复 5 框
w.displayMode.setCurrentIndex(0)
app.processEvents()
assert len(w.realSteps.boxes()) == 5, "切回树状图应恢复 5 框树"
print("4. displayMode 切换即时重渲染（5 框树 ↔ 6 框线性）✓")

# ========== 5. 清空后恢复占位，切换不再重渲染 ==========
w.clearItems.click()
app.processEvents()
assert w.realSteps.is_placeholder(), "清空后应恢复占位"
w.displayMode.setCurrentIndex(1)
app.processEvents()
assert w.realSteps.is_placeholder(), "无方案时切换模式应保持占位"
print("5. 清空后恢复占位，模式切换不再渲染 ✓")

# ========== 6. 步骤图圆标 tooltip 可用 ==========
w.do_start_calculate()   # 当前 displayMode=1（步骤图）
app.processEvents()
assert len(w.realSteps.boxes()) == 6, "步骤图模式下计算应直接渲染线性"
circle = w.realSteps.cost_circles()[0]
lines = circle._tooltip_lines()
assert any("第 1 步" in t for t, _ in lines), lines
assert any("累积惩罚" in t or "级" in t for t, _ in lines), lines
print("6. 步骤图圆标 tooltip（步骤序号+计费明细）✓")

# ========== 7. 过于昂贵步骤标签红色提示 ==========
# 构造一个高花费方案：大量附魔书合并（锋利V 书合成多级）
cards7 = [card("剑"),
          card("附魔书", ("sharpness", "锋利", 5), ("looting", "抢夺", 3),
               ("fire_aspect", "火焰附加", 2), ("knockback", "击退", 2),
               ("sweeping_edge", "横扫之刃", 3)),
          card("附魔书", ("mending", "经验修补", 1), ("unbreaking", "耐久", 3),
               ("vanishing_curse", "消失诅咒", 1))]
plan7 = opt.optimize(build_items_from_cards(cards7))
assert plan7.too_expensive_steps, "测试前提：应有过于昂贵步骤"
tree.clear_plan()
tree.show_plan(plan7, dm, mode="steps")
texts = _scene_texts(tree)
assert any("过于昂贵" in t for t in texts), texts
from PySide6.QtGui import QBrush
from Utils.anvil_steps_tree import _WARN_COLOR
labels = [it for it in tree._scene.items()
          if isinstance(it, QGraphicsSimpleTextItem)
          and "过于昂贵" in it.text()]
assert any(it.brush().color() == _WARN_COLOR for it in labels), \
    "过于昂贵标签应为红色"
print("7. 过于昂贵步骤：行末红色标签提示 ✓")

w.close()
print("\n全部冒烟测试通过")
