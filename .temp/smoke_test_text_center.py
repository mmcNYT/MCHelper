# -*- coding: utf-8 -*-
"""冒烟测试：验证拖拽图标文字居中（EnchantListWidget；DropListWidget 已无拖拽图标）
用法：python smoke_test_text_center.py [scale]  # scale 为模拟的屏幕缩放比，默认 1.0"""
import os
import sys

SCALE = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
if SCALE != 1.0:
    os.environ["QT_SCALE_FACTOR"] = str(SCALE)  # 必须在 QApplication 创建前设置
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint

app = QApplication(sys.argv)

from Utils.drop_list_widget import DropListWidget
from Utils.enchant_list_widget import EnchantListWidget


def ink_distribution(img, ink_max_lightness=170, margin=3):
    """统计内部区域的文字笔画分布（排除边缘 margin 逻辑像素，避开描边线），
    返回逻辑坐标（除以 dpr）；同时返回图标内部有效区域"""
    dpr = img.devicePixelRatio() or 1.0
    m = int(margin * dpr)
    xs, ys = [], []
    for y in range(m, img.height() - m):
        for x in range(m, img.width() - m):
            c = img.pixelColor(x, y)
            if c.lightness() < ink_max_lightness:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return {
        "x_min": min(xs) / dpr, "x_max": (max(xs) + 1) / dpr,
        "y_min": min(ys) / dpr, "y_max": (max(ys) + 1) / dpr,
        "cx": sum(xs) / len(xs) / dpr, "cy": sum(ys) / len(ys) / dpr,
        "inner_left": m / dpr, "inner_right": (img.width() - m) / dpr,
        "inner_top": m / dpr, "inner_bottom": (img.height() - m) / dpr,
    }


def assert_centered(widget, text, label, reference=None):
    """验证文字居中：
    - 绝对断言：文字完全落在图标内部区域（不越界、不裁剪）
    - 相对断言：墨水包络与 1x 基准一致（偏差 ≤2px）"""
    pix = widget._create_drag_pixmap(text)
    dpr = pix.devicePixelRatio()
    assert abs(dpr - SCALE) < 0.01, f"[{label}] dpr={dpr} 应为 {SCALE}"
    lw, lh = pix.width() / dpr, pix.height() / dpr

    img = pix.toImage()
    dist = ink_distribution(img)
    assert dist, f"[{label}] 未检测到文字笔画"

    assert dist["x_min"] >= dist["inner_left"] and dist["x_max"] <= dist["inner_right"], \
        f"[{label}] 文字水平越出内部区域: [{dist['x_min']:.1f}, {dist['x_max']:.1f}] vs [{dist['inner_left']:.1f}, {dist['inner_right']:.1f}]"
    assert dist["y_min"] >= dist["inner_top"] and dist["y_max"] <= dist["inner_bottom"], \
        f"[{label}] 文字垂直越出内部区域: [{dist['y_min']:.1f}, {dist['y_max']:.1f}] vs [{dist['inner_top']:.1f}, {dist['inner_bottom']:.1f}]"

    if reference is not None:
        for key in ("x_min", "x_max", "y_min", "y_max"):
            assert abs(dist[key] - reference[key]) <= 2, \
                f"[{label}] 包络 {key} 与基准偏差超限: {dist[key]:.2f} vs {reference[key]:.2f}"

    top_gap = dist["y_min"] - dist["inner_top"]
    bottom_gap = dist["inner_bottom"] - dist["y_max"]
    print(f"[scale={SCALE}][{label}] 包络 x[{dist['x_min']:.1f},{dist['x_max']:.1f}] "
          f"y[{dist['y_min']:.1f},{dist['y_max']:.1f}], 上边距={top_gap:.2f} 下边距={bottom_gap:.2f} ✓")
    return dist


def assert_hotspot(widget, text, label):
    """热点必须等于逻辑中心"""
    pix = widget._create_drag_pixmap(text)
    center = widget.logical_center(pix)
    lw, lh = pix.width() / (pix.devicePixelRatio() or 1), pix.height() / (pix.devicePixelRatio() or 1)
    assert center == QPoint(int(lw) // 2, int(lh) // 2), \
        f"[{label}] 热点应为中心 ({int(lw) // 2},{int(lh) // 2})，实际 {center}"
    print(f"[scale={SCALE}][{label}] 热点=逻辑中心 {center.x()},{center.y()} ✓")


lw = DropListWidget()
elw = EnchantListWidget()
print(f"[scale={SCALE}] 控件 dpr: {elw.devicePixelRatioF():.2f}")

assert not hasattr(lw, "_create_drag_pixmap"), "DropListWidget 不应再有拖拽图标方法"

import json
BASELINE = os.path.join(os.path.dirname(__file__), "text_center_baseline.json")

texts = ("锋利 (等级 5)", "深海探索者 (等级 3)")
if SCALE == 1.0:
    baseline = {}
    for text in texts:
        pix = elw._create_drag_pixmap(text)
        dist = ink_distribution(pix.toImage())
        assert dist, f"基准生成失败: {text}"
        baseline[f"EnchantListWidget|{text}"] = dist
    with open(BASELINE, "w", encoding="utf-8") as f:
        json.dump(baseline, f, ensure_ascii=False)
    print(f"[scale=1.0] 基准已写入 {BASELINE}")
    ref_source = baseline
else:
    with open(BASELINE, encoding="utf-8") as f:
        ref_source = json.load(f)

for text in texts:
    ref = ref_source.get(f"EnchantListWidget|{text}")
    assert_centered(elw, text, "EnchantListWidget", reference=ref)
assert_hotspot(elw, "时运 (等级 3)", "EnchantListWidget")

print(f"[scale={SCALE}] 全部居中/热点断言通过\n")
