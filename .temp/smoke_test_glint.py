# -*- coding: utf-8 -*-
"""冒烟测试：附魔流光图标（_GlintIcon）
1. 有附魔 → _GlintIcon 且定时器运行；无附魔 → 静态 QLabel
2. 动画推进：多帧渲染后像素变化（光效在动）
3. 光效剪辑：物品透明区域不应出现光效像素
4. 光效纹理加载与类级缓存
5. 卡片集成 + 端到端（确认 → 卡片带流光图标）
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtCore import Qt, QTimer

app = QApplication(sys.argv)

from Utils.enchanted_item_card import _GlintIcon, EnchantedItemCard, get_item_icon_path

enchants = [{"id": "sharpness", "name": "锋利", "level": 5}]

# ---------- 1. 分支选择：有附魔流光 / 无附魔静态 ----------
card1 = EnchantedItemCard("剑", enchants)
icon1 = card1.layout().itemAt(0).widget()
assert isinstance(icon1, _GlintIcon), "有附魔应为流光图标控件"
assert icon1._has_glint, "光效纹理应加载成功"
assert icon1._timer.isActive(), "流光动画定时器应运行"
assert icon1._timer.interval() == _GlintIcon.FRAME_MS

card2 = EnchantedItemCard("剑", [])
icon2 = card2.layout().itemAt(0).widget()
assert isinstance(icon2, QLabel), "无附魔应为静态 QLabel"
assert not hasattr(icon2, "_timer"), "静态图标不应有定时器"
print("1. 分支选择：流光/静态 ✓")

# ---------- 2. 动画推进：帧间像素变化 ----------
def image_diff(img_a, img_b):
    """统计两帧图像不同像素数（限制采样步长提速）"""
    diff = 0
    w, h = min(img_a.width(), img_b.width()), min(img_a.height(), img_b.height())
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            ca, cb = img_a.pixelColor(x, y), img_b.pixelColor(x, y)
            if ca != cb:
                diff += 1
    return diff

frame1 = icon1.grab().toImage()
for _ in range(12):
    icon1._advance()  # 手动推进 12 帧（快层 12px、慢层反向 12px）
    app.processEvents()
frame2 = icon1.grab().toImage()
diff = image_diff(frame1, frame2)
assert diff > 20, f"动画帧间应有像素变化，实际 diff={diff}"
# 位移推进正确性（Python 负数取模结果为非负：-12 % 48 = 36，循环等价）
assert icon1._offset_fast == 12, f"快速层位移应为 12（12帧x1px），实际 {icon1._offset_fast}"
assert icon1._offset_slow == 36, f"慢速层位移应为 36（-12 % 48），实际 {icon1._offset_slow}"
print(f"2. 动画推进（帧间 diff={diff}） ✓")

# ---------- 3. 光效剪辑 + 加法混合提亮 ----------
img = icon1.grab().toImage()
# 以纹理 alpha 图为准找出全部透明像素，逐个检查渲染结果未被紫色光效污染
# （offscreen 下 grab 背景为不透明灰白 239,239,239，不能靠渲染 alpha 判断）
tex_img = icon1._item_pix.toImage()
glint_like = 0
checked = 0
for y in range(img.height()):
    for x in range(img.width()):
        if tex_img.pixelColor(x, y).alpha() == 0:
            checked += 1
            c = img.pixelColor(x, y)
            # 紫色光效特征：蓝分量明显高于绿（如 97,47,157）；背景/物品纹理无此特征
            if c.blue() > c.green() + 40:
                glint_like += 1
assert checked > 100, f"透明像素样本应足够（实际 {checked}）"
assert glint_like == 0, f"物品透明区不应有光效像素，检出 {glint_like} 处"
# 反向确认：加法混合只提亮不压暗（对比无光效静态参照，物品像素亮度应不变或提高）
ref = QLabel()
ref.setPixmap(icon1._item_pix)
ref.setFixedSize(48, 48)
ref_img = ref.grab().toImage()
brighter = darker = 0
for y in range(img.height()):
    for x in range(img.width()):
        if tex_img.pixelColor(x, y).alpha() == 0:
            continue
        ca, cg = img.pixelColor(x, y), ref_img.pixelColor(x, y)
        lum_a = 0.299 * ca.red() + 0.587 * ca.green() + 0.114 * ca.blue()
        lum_g = 0.299 * cg.red() + 0.587 * cg.green() + 0.114 * cg.blue()
        if lum_a - lum_g > 1:
            brighter += 1
        elif lum_a - lum_g < -1:
            darker += 1
assert brighter > 100, f"加法混合应明显提亮物品（实际提亮 {brighter} 像素）"
assert darker == 0, f"加法混合不应压暗任何像素，实际压暗 {darker} 个"
print(f"3. 光效剪辑（透明区 {checked} 像素零污染）+ 加法提亮（{brighter} 像素提亮 0 压暗） ✓")

# ---------- 4. 光效纹理类级缓存 ----------
tex1 = _GlintIcon._glint_tex
assert tex1 is not None and not tex1.isNull(), "光效纹理应加载"
icon3 = _GlintIcon("弓", 48)
assert _GlintIcon._glint_tex is tex1, "光效纹理应类级共享（不重复加载）"
print("4. 光效纹理类级缓存 ✓")

# ---------- 5. 端到端：确认 → 卡片带流光 ----------
from Tools.tool_EnchantCaculator import EnchantCalculatorWidget

widget = EnchantCalculatorWidget()

def confirm_modal():
    w = QApplication.activeModalWidget()
    w.on_enchant_dropped("fortune", 3)
    w.confirmItem.click()

QTimer.singleShot(0, confirm_modal)
widget.do_choose_items()
assert widget.listWidget.count() == 1
card_in = widget.listWidget.itemWidget(widget.listWidget.item(0))
assert isinstance(card_in, EnchantedItemCard)
icon_in = card_in.layout().itemAt(0).widget()
assert isinstance(icon_in, _GlintIcon) and icon_in._timer.isActive(), "端到端：卡片图标应为流光动画"
print("5. 端到端：确认 → 流光卡片 ✓")

print("\n全部冒烟测试通过")
