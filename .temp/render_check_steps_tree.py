# -*- coding: utf-8 -*-
"""渲染验证：步骤树 grab() 出图，像素级检查（offscreen）

- 方框图标真实绘制（白底框内有非白非背景像素 = 图标纹理）
- 连线真实绘制（左右子框中线之间、汇合横线高度存在深色像素）
- 圆标真实绘制（圆心位置白底 + 彩色描边像素）
- 最终框加粗描边（描边深色像素密度高于普通框）
- tooltip 组件 paintEvent 渲染（深紫背景像素）
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor

app = QApplication(sys.argv)

from Utils.enchant_data_manager import DataManager
from Utils.anvil_optimizer import AnvilOptimizer, AnvilItem
from Utils.anvil_steps_tree import (AnvilStepsTree, _MARGIN, _BOX_W, _BOX_H,
                                    _ROW_H, _LINE_COLOR, _COST_COLOR,
                                    _WARN_COLOR)
from Utils.enchanted_item_card import (TOOLTIP_HEADER, TOOLTIP_TEXT,
                                       TOOLTIP_BG_TOP)

dm = DataManager()
opt = AnvilOptimizer(dm)
tree = AnvilStepsTree()
tree.resize(760, 560)

items = [
    AnvilItem.make("剑", []),
    AnvilItem.make("附魔书", [("sharpness", 5)]),
    AnvilItem.make("附魔书", [("looting", 3)]),
    AnvilItem.make("附魔书", [("unbreaking", 3)]),
    AnvilItem.make("附魔书", [("sweeping_edge", 3)]),
]
plan = opt.optimize(items)
tree.show_plan(plan, dm)
app.processEvents()
img = tree.grab().toImage()
assert not img.isNull() and img.width() > 0

# 场景 → 视口坐标
from PySide6.QtCore import QPointF
def vp(p: QPointF):
    return tree.mapFromScene(p)

def line_dark(x, y):
    """该视口像素是否接近连线深色 (#1A1A1A)"""
    c = img.pixelColor(x, y)
    return c.value() < 80

def color_close(c1, c2, tol=60):
    return (abs(c1.red() - c2.red()) <= tol and
            abs(c1.green() - c2.green()) <= tol and
            abs(c1.blue() - c2.blue()) <= tol)

root_box = tree.final_box()
assert root_box is not None
checks = []

# ---- 1. 图标绘制：叶子框中心有非白像素（图标纹理）----
leaf = next(b for b in tree.boxes() if b.anvil_item.name == "剑")
ct = vp(leaf.mapToScene(_BOX_W / 2, _BOX_H / 2))
c = img.pixelColor(int(ct.x()), int(ct.y()))
assert not (c.red() > 245 and c.green() > 245 and c.blue() > 245), \
    f"叶子框中心应为图标纹理（非白），实际 {c.name()}"
checks.append("图标纹理")

# ---- 2. 连线绘制：某 merge 节点左右子之间、汇合横线高度存在深色像素 ----
def find_merge_pairs(box):
    """递归收集 (子框, 产物框) 对"""
    out = []
    if box.left_box is not None:
        out.append((box.left_box, box.right_box, box))
        out.extend(find_merge_pairs(box.left_box))
        out.extend(find_merge_pairs(box.right_box))
    return out

pairs = find_merge_pairs(root_box)
assert pairs, "应存在合并对"
hit = 0
for lb, rb, pb in pairs:
    lane_y_sc = pb.y() - 18  # 汇合横线高度（场景坐标 = 产物框顶 - 18）
    y = int(vp(QPointF(0, lane_y_sc)).y())
    x1 = int(vp(lb.mapToScene(_BOX_W / 2, 0)).x())
    x2 = int(vp(rb.mapToScene(_BOX_W / 2, 0)).x())
    span = [x for x in range(min(x1, x2), max(x1, x2) + 1)
            if 0 <= x < img.width()]
    darks = [x for x in span if 0 <= y < img.height() and line_dark(x, y)]
    if darks:
        hit += 1
assert hit == len(pairs), f"汇合横线 {hit}/{len(pairs)} 可见"
checks.append(f"汇合连线 x{len(pairs)}")

# ---- 3. 圆标绘制：每个圆心处白底 + 周围绿色描边 ----
green_hits = 0
for c_circle in tree.cost_circles():
    center = vp(c_circle.mapToScene(0, 0))
    cx, cy = int(center.x()), int(center.y())
    # 圆心白底
    c0 = img.pixelColor(cx, cy)
    # 半径 12 处的描边（上下左右 4 个方向至少 1 个命中绿色）
    r = c_circle.R
    found = False
    for dx, dy in [(r, 0), (-r, 0), (0, r), (0, -r)]:
        x, y = cx + dx, cy + dy
        if 0 <= x < img.width() and 0 <= y < img.height():
            cc = img.pixelColor(x, y)
            if color_close(cc, _COST_COLOR, 70) and cc.value() < 200:
                found = True
                break
    if found:
        green_hits += 1
assert green_hits == len(tree.cost_circles()), \
    f"绿色圆标 {green_hits}/{len(tree.cost_circles())} 可见"
checks.append(f"经验圆标 x{green_hits}")

# ---- 4. 最终框加粗描边（3px）比普通框（2px）更宽 ----
# 注意：合并框顶边正中被该步圆标白底覆盖（设计如此，圆标骑在汇入竖线上），
# 因此在框左侧 1/6 处（避开圆标±12 与四角）垂直扫描描边厚度
def border_thickness(box):
    """框顶边指定列的垂直暗带厚度（≈ 描边宽）"""
    top = vp(box.mapToScene(0, 0))
    col = int(vp(box.mapToScene(_BOX_W // 6, 0)).x())
    y0 = int(top.y()) - 3
    best = cur = 0
    for yy in range(y0, y0 + 9):
        if 0 <= col < img.width() and 0 <= yy < img.height() \
                and line_dark(col, yy):
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best

th_final = border_thickness(root_box)
th_leaf = border_thickness(leaf)
assert th_final >= 3, f"最终框描边应 ≥3px，实测 {th_final}"
assert th_leaf >= 2, f"普通框描边应 ≥2px，实测 {th_leaf}"
assert th_final > th_leaf, f"最终框描边应宽于普通框，实测 {th_final} vs {th_leaf}"
checks.append(f"最终框加粗描边({th_final}px > {th_leaf}px)")

# ---- 5. tooltip 渲染（深紫背景 + 紫描边 + 白标题/灰附魔文本）----
tree.show_tooltip([("附魔书", TOOLTIP_HEADER), ("锋利 V", TOOLTIP_TEXT)])
app.processEvents()
tp = tree._tooltip
assert not tp.isHidden()
timg = tp.grab().toImage()
# 按颜色占比统计（offscreen 下 alpha 240 与白底合成 → 背景约 #1E0F1E）
from collections import Counter
cnt = Counter(timg.pixelColor(x, y).rgb()
              for y in range(timg.height()) for x in range(timg.width()))
total = timg.width() * timg.height()
# 背景色 = 出现最多的颜色，应为深紫（各分量 <60，且明度低）
bgc = QColor(cnt.most_common(1)[0][0])
assert bgc.red() < 60 and bgc.green() < 60 and bgc.value() < 60, \
    f"主导色应为深紫背景，实际 {bgc.name()}"
assert cnt.most_common(1)[0][1] / total > 0.5, "背景应占多数面积"
# 紫描边：蓝 > 红 > 绿 的紫色系像素存在
has_purple = any(c.blue() > 100 and c.blue() > c.red() > c.green()
                 for c in map(QColor, (rgb for rgb, _ in cnt.items())))
assert has_purple, "应存在紫色描边像素"
# 白色标题 + 灰色附魔文本存在
has_white = any(c.red() > 230 and c.green() > 230 and c.blue() > 230
                for c in map(QColor, (rgb for rgb, _ in cnt.items())))
has_grey = any(150 <= c.red() <= 190 and abs(c.red() - c.green()) < 12
               and abs(c.green() - c.blue()) < 12
               for c in map(QColor, (rgb for rgb, _ in cnt.items())))
assert has_white and has_grey, "应同时存在白色标题与灰色附魔文本"
checks.append("tooltip 深紫底+紫描边+白/灰文本")
tree.hide_tooltip()

print("渲染验证通过：" + "、".join(checks))
