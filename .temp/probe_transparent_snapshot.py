# -*- coding: utf-8 -*-
"""探针：拖动快照透明化 + 视口淡灰背景 方案实测
1. widget.grab() 现状四角 alpha（预期 255，证明不透明）
2. render 到 ARGB32_Premultiplied（排除 DrawWindowBackground）四角 alpha（预期 0）+ 内容完整性
3. 视口背景：默认色 / QPalette / QSS 三种方式实测像素
4. QSS 方案副作用检查：itemWidget（卡片）是否被污染
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QImage, QPainter, QPixmap, QRegion, QColor, QPalette

app = QApplication(sys.argv)

from Tools.tool_EnchantCaculator import EnchantCalculatorWidget
from Utils.card_list_widget import CardListWidget
from Utils.enchanted_item_card import EnchantedItemCard

widget = EnchantCalculatorWidget()
widget.resize(658, 518)
widget.show()
app.processEvents()
lst = widget.chosenItemList

# 一张带附魔（流光图标）+ 一张无附魔（静态 QLabel 图标）卡片
widget.add_item_card({"item_name": "剑", "enchants": [{"id": "sharpness", "name": "锋利", "level": 5}]})
widget.add_item_card({"item_name": "钓鱼竿", "enchants": []})
app.processEvents()
card = lst.itemWidget(lst.item(0))
card_static = lst.itemWidget(lst.item(1))
assert isinstance(card, EnchantedItemCard) and isinstance(card_static, EnchantedItemCard)


def corners(img):
    w, h = img.width(), img.height()
    return [(img.pixelColor(x, y).alpha(), img.pixelColor(x, y).red(),
             img.pixelColor(x, y).green(), img.pixelColor(x, y).blue())
            for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]


# ========== 1. grab() 现状 ==========
g_img = card.grab().toImage().convertToFormat(QImage.Format_ARGB32)
print(f"[1] grab() 尺寸 {g_img.width()}x{g_img.height()} 四角(a,r,g,b):")
for c in corners(g_img):
    print("   ", c)

# ========== 2. render 排除 DrawWindowBackground ==========
img = QImage(card.size(), QImage.Format_ARGB32_Premultiplied)
img.fill(Qt.transparent)
p = QPainter(img)
card.render(p, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
p.end()
r_img = img.convertToFormat(QImage.Format_ARGB32)
print(f"[2] render(DrawChildren) 尺寸 {r_img.width()}x{r_img.height()} 四角(a,r,g,b):")
for c in corners(r_img):
    print("   ", c)
# 内容完整性：tooltip 框区域应有大量不透明像素（深紫背景）
w, h = r_img.width(), r_img.height()
opaque_total = 0
sampled = 0
for y in range(0, h, 2):
    for x in range(0, w, 2):
        sampled += 1
        if r_img.pixelColor(x, y).alpha() > 0:
            opaque_total += 1
print(f"[2] 抽样像素 {sampled}，不透明 {opaque_total}（{100 * opaque_total / sampled:.0f}%）")
# 深紫背景色值抽查（tooltip 框中心）
center = r_img.pixelColor(w // 2, int(h * 0.8))
print(f"[2] tooltip 框中心像素 (a={center.alpha()}, r={center.red()}, g={center.green()}, b={center.blue()})")
# 与 grab() 的内容一致性：逐像素比对不透明区 RGB
diff = 0
for y in range(0, h):
    for x in range(0, w):
        a1 = r_img.pixelColor(x, y).alpha()
        a2 = g_img.pixelColor(x, y).alpha()
        if a1 > 0 and a2 > 0:
            c1, c2 = r_img.pixelColor(x, y), g_img.pixelColor(x, y)
            if (c1.red(), c1.green(), c1.blue()) != (c2.red(), c2.green(), c2.blue()):
                diff += 1
print(f"[2] 不透明区 RGB 与 grab() 不一致像素数: {diff}")
pm = QPixmap.fromImage(img)
print(f"[2] fromImage 非空: {not pm.isNull()}, 尺寸 {pm.width()}x{pm.height()}")

# ========== 3. 视口背景 ==========
vp = lst.viewport()
vp_img = vp.grab().toImage().convertToFormat(QImage.Format_ARGB32)
c = vp_img.pixelColor(1, 1)
print(f"[3] 默认视口角像素 (a={c.alpha()}, r={c.red()}, g={c.green()}, b={c.blue()})")

# 方案 A：QPalette.Window + autoFillBackground
pal = vp.palette()
pal.setColor(QPalette.Window, QColor("#ECECEC"))
vp.setPalette(pal)
vp.setAutoFillBackground(True)
app.processEvents()
t1 = vp.grab().toImage().convertToFormat(QImage.Format_ARGB32).pixelColor(1, 1)
print(f"[3] QPalette.Window 后角像素 (a={t1.alpha()}, r={t1.red()}, g={t1.green()}, b={t1.blue()})")

# 方案 B：QPalette.Base
pal2 = vp.palette()
pal2.setColor(QPalette.Base, QColor("#ECECEC"))
vp.setPalette(pal2)
app.processEvents()
t2 = vp.grab().toImage().convertToFormat(QImage.Format_ARGB32).pixelColor(1, 1)
print(f"[3] QPalette.Base 后角像素 (a={t2.alpha()}, r={t2.red()}, g={t2.green()}, b={t2.blue()})")

# 还原 palette，试方案 C：viewport 精确 objectName QSS
pal3 = vp.palette()
pal3.setColor(QPalette.Window, vp.palette().color(QPalette.Window).name())
pal3.setColor(QPalette.Base, QColor("#FFFFFF"))
vp.setPalette(pal3)
vp.setAutoFillBackground(False)
vp.setStyleSheet("#qt_scrollarea_viewport { background: #ECECEC; }")
app.processEvents()
t3 = vp.grab().toImage().convertToFormat(QImage.Format_ARGB32).pixelColor(1, 1)
print(f"[3] QSS(viewport objectName) 后角像素 (a={t3.alpha()}, r={t3.red()}, g={t3.green()}, b={t3.blue()})")

# ========== 4. QSS 副作用检查 ==========
# 静态图标 QLabel（钓鱼竿卡片）：QSS 若级联到 itemWidget，图标透明区会变灰
card_static_img = card_static.grab().toImage().convertToFormat(QImage.Format_ARGB32)
# 图标区域四角（卡片顶部图标区，图标 48x48 居中，margin 4px）
probe_pts = [(6, 6), (40, 6), (6, 40), (40, 40)]
print("[4] 无附魔卡片图标区四角 (a,r,g,b):")
for x, y in probe_pts:
    c4 = card_static_img.pixelColor(x, y)
    print(f"    ({x},{y}) -> (a={c4.alpha()}, r={c4.red()}, g={c4.green()}, b={c4.blue()})")

# 流光卡片（自绘）检查：tooltip 框外卡片角落是否被 QSS 污染
card_img = card.grab().toImage().convertToFormat(QImage.Format_ARGB32)
cc = card_img.pixelColor(1, 1)
print(f"[4] 带附魔卡片自身角落 (a={cc.alpha()}, r={cc.red()}, g={cc.green()}, b={cc.blue()})")

print("\n探针完成")
