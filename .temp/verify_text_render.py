# -*- coding: utf-8 -*-
"""像素级确认：圆标内数字与总花费文字是否真实渲染（视觉模型对
小字号文本会误判为方块，以像素分析为准）"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF

app = QApplication(sys.argv)

from Utils.enchant_data_manager import DataManager
from Utils.anvil_optimizer import AnvilOptimizer, AnvilItem
from Utils.anvil_steps_tree import AnvilStepsTree

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

def vp(p):
    return tree.mapFromScene(p)

def text_pixels(x0, x1, y0, y1, text_color):
    """区域内疑似文字笔画像素（接近文字颜色且非白非背景）"""
    n = 0
    for yy in range(y0, y1):
        for xx in range(x0, x1):
            if 0 <= xx < img.width() and 0 <= yy < img.height():
                c = img.pixelColor(xx, yy)
                if (abs(c.red() - text_color.red()) < 90 and
                        abs(c.green() - text_color.green()) < 90 and
                        abs(c.blue() - text_color.blue()) < 90):
                    n += 1
    return n

from Utils.anvil_steps_tree import _COST_COLOR, _TEXT_COLOR

# 1. 每个圆标中心区域有数字笔画（绿色系）
ok = 0
for cc in tree.cost_circles():
    center = vp(cc.mapToScene(0, 0))
    cx, cy = int(center.x()), int(center.y())
    n = text_pixels(cx - 10, cx + 11, cy - 9, cy + 10, _COST_COLOR)
    if n >= 8:  # 一两位数字的笔画像素
        ok += 1
    else:
        print(f"  圆标 step {cc.step_no} 数字像素不足: {n}")
assert ok == len(tree.cost_circles()), \
    f"圆标数字渲染 {ok}/{len(tree.cost_circles())}"
print(f"1. 圆标数字真实渲染（{ok}/{len(tree.cost_circles())} 个，笔画像素充足）✓")

# 2. 总花费文字存在（灰色系）
root = tree.final_box()
bottom = vp(root.mapToScene(0, 0))
ys = int(bottom.y()) + 60  # 框下方文字行
n = text_pixels(0, img.width(), ys, ys + 24, _TEXT_COLOR)
assert n >= 20, f"总花费文字像素不足: {n}"
print(f"2. 总花费文字真实渲染（{n} 个笔画像素）✓")

# 3. 文字不为豆腐块：豆腐块特征是等宽矩形/方块密集且字符间空隙规律，
#    真实汉字"总花费 X 级"笔画分布不均（横竖撇捺），检查列直方图方差
import statistics
cols = []
for xx in range(int(vp(root.mapToScene(-34, 0)).x()),
                int(vp(root.mapToScene(34, 0)).x())):
    col_n = 0
    for yy in range(ys, ys + 24):
        if 0 <= xx < img.width() and 0 <= yy < img.height():
            c = img.pixelColor(xx, yy)
            if c.value() < 140 and not (c.red() > 230 and c.green() > 230):
                col_n += 1
    cols.append(col_n)
nz = [c for c in cols if c > 0]
assert len(nz) >= 10, "文字覆盖列数过少"
cv = statistics.pstdev(nz) / (statistics.mean(nz) + 1e-6)
# 豆腐块每列像素数高度一致（cv 很小）；真实汉字列分布波动大
assert cv > 0.3, f"文字列分布过于均匀（cv={cv:.2f}），疑似豆腐块"
print(f"3. 文字形态正常（列分布变异系数 {cv:.2f} > 0.3，非豆腐块）✓")

print("\n像素级确认全部通过：圆标数字与总花费文字均真实渲染")
