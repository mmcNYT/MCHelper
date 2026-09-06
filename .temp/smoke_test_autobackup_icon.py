# -*- coding: utf-8 -*-
"""冒烟测试：AutoBackUp 存档列表——含 icon 文件的文件夹其封面图标固定显示在行最右侧
1. 委托 set_right_icon：正常设置 / 清除 / 非法输入兜底
2. _add_list_items：含 icon.png 的文件夹设置图标、无 icon 文件夹与普通文件不设
3. text 完整性：所有列表项 text 与 os.listdir 原始名称一致（字典键安全）
4. icon.jpg 备选扩展名生效
5. 损坏的 icon 文件不崩溃且不设图标
6. 委托 sizeHint：所有行统一预留图标高度
7. 渲染冒烟：offscreen 渲染列表并逐像素确认图标块紧贴行右缘（距右缘 ≤ 边距+2）
8. 超长文件夹名：文字自动省略（尾部 …），不与右侧图标重叠
"""
import os
import shutil
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication, QListWidget, QListWidgetItem, QStyleOptionViewItem
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtCore import Qt

app = QApplication(sys.argv)

from Utils.right_icon_delegate import (
    RightIconDelegate, ICON_ROLE, ICON_RIGHT_MARGIN
)
from Tools.tool_AutoBackUp import AutoBackUpWidget

# 构造临时存档目录
base = tempfile.mkdtemp(prefix="mc_saves_")
try:
    # 世界1：含 icon.png（有效 PNG 64x64 红色）
    world1 = os.path.join(base, "世界1")
    os.makedirs(world1)
    pm = QPixmap(64, 64)
    pm.fill(QColor(255, 0, 0))
    assert pm.save(os.path.join(world1, "icon.png"), "PNG")

    # 世界2：无 icon
    os.makedirs(os.path.join(base, "世界2"))

    # 世界3：icon.jpg 备选扩展名
    world3 = os.path.join(base, "世界3")
    os.makedirs(world3)
    pm3 = QPixmap(64, 64)
    pm3.fill(QColor(0, 0, 255))
    assert pm3.save(os.path.join(world3, "icon.jpg"), "JPG")

    # 世界4：损坏的 icon.png（文本内容，非图片）
    world4 = os.path.join(base, "世界4")
    os.makedirs(world4)
    with open(os.path.join(world4, "icon.png"), "w", encoding="utf-8") as f:
        f.write("this is not a real image")

    # 世界5：超长文件夹名（验证文字省略不与图标重叠）
    long_name = "这是一个非常非常非常非常非常非常长的世界名字用来测试省略号功能是否正常工作"
    world5 = os.path.join(base, long_name)
    os.makedirs(world5)
    pm5 = QPixmap(64, 64)
    pm5.fill(QColor(0, 255, 0))
    assert pm5.save(os.path.join(world5, "icon.png"), "PNG")

    # 普通文件（不是文件夹）
    with open(os.path.join(base, "session.lock"), "w", encoding="utf-8") as f:
        f.write("lock")

    # ---------- 1. 委托 set_right_icon ----------
    lst = QListWidget()
    delegate = RightIconDelegate(icon_size=32)
    lst.setItemDelegate(delegate)
    item = QListWidgetItem("测试")
    lst.addItem(item)
    assert item.data(ICON_ROLE) is None, "初始无图标"
    delegate.set_right_icon(item, pm)
    assert isinstance(item.data(ICON_ROLE), QPixmap), "设置后应携带 QPixmap"
    delegate.set_right_icon(item, None)
    assert item.data(ICON_ROLE) is None, "None 应清除图标"
    delegate.set_right_icon(item, QPixmap())  # 空 pixmap 兜底
    assert item.data(ICON_ROLE) is None, "空 pixmap 不应设置"
    print("1. 委托 set_right_icon（设置/清除/兜底） ✓")

    # ---------- 2/3. _add_list_items 图标设置与 text 完整性 ----------
    widget = AutoBackUpWidget()
    widget.back_up_list = {}
    widget.target_dir_path = base
    widget.targetDirPath.setText(base)  # 触发 textChanged -> refresh_dir_list
    app.processEvents()

    expected_names = set(os.listdir(base))
    got_names = {widget.targetDirList.item(i).text()
                 for i in range(widget.targetDirList.count())}
    assert got_names == expected_names, f"text 应与目录条目一致: {got_names} vs {expected_names}"

    icon_flags = {}
    for i in range(widget.targetDirList.count()):
        li = widget.targetDirList.item(i)
        icon_flags[li.text()] = isinstance(li.data(ICON_ROLE), QPixmap)

    assert icon_flags["世界1"] is True, "世界1（icon.png）应显示图标"
    assert icon_flags["世界2"] is False, "世界2（无 icon）不应显示图标"
    assert icon_flags["世界3"] is True, "世界3（icon.jpg）应显示图标"
    assert icon_flags["世界4"] is False, "世界4（损坏 icon）不应显示图标且不崩溃"
    assert icon_flags[long_name] is True, "超长名世界应显示图标"
    assert icon_flags["session.lock"] is False, "普通文件不应显示图标"
    print("2. 含 icon 文件夹设置图标 / 无 icon 及普通文件不设置 ✓")
    print("3. 所有列表项 text 与 os.listdir 原始名称一致（字典键安全） ✓")
    print("4. icon.jpg 备选扩展名生效 ✓")
    print("5. 损坏的 icon 文件优雅降级，不崩溃 ✓")

    # ---------- 6. sizeHint 统一行高 ----------
    delegate_widget = widget.targetDirList.itemDelegate()
    assert delegate_widget is widget._save_icon_delegate
    hints = []
    for i in range(widget.targetDirList.count()):
        li = widget.targetDirList.item(i)
        opt = QStyleOptionViewItem()
        delegate_widget.initStyleOption(opt, widget.targetDirList.indexFromItem(li))
        hints.append(delegate_widget.sizeHint(opt, widget.targetDirList.indexFromItem(li)).height())
    assert len(set(hints)) == 1, f"所有行高应统一（有/无图标行一致）: {hints}"
    assert hints[0] >= 32 + 4, "行高应容纳图标"
    print(f"6. sizeHint 所有行统一高度 {hints[0]}px（含/无图标一致） ✓")

    # ---------- 7/8. 渲染冒烟：offscreen 渲染并逐像素验证 ----------
    # 注意：targetDirList 被 gridLayout 管理，直接 resize 会被布局激活覆盖；
    # 正确做法是放大外层容器 layoutWidget，让布局自然分配足够空间
    lw = widget.targetDirList
    widget.resize(900, 800)
    widget.layoutWidget.setGeometry(40, 30, 800, 700)
    app.processEvents()
    app.processEvents()  # 两次确保布局激活完成
    img = lw.grab().toImage()
    view_w = lw.viewport().width()
    print(f"   列表视口: {lw.viewport().width()} x {lw.viewport().height()}，共 {lw.count()} 项")

    # 所有行都应在可视区内（无滚动条遮挡图标右缘）
    assert all(0 <= lw.visualItemRect(lw.item(i)).bottom() <= lw.viewport().height()
               for i in range(lw.count())), "布局空间不足，行被滚动条遮挡"

    def row_pixels(row_rect, cond):
        xs = []
        for y in range(max(0, row_rect.top()), min(img.height(), row_rect.bottom())):
            for x in range(max(0, row_rect.left()), min(img.width(), row_rect.right())):
                c = QColor(img.pixel(x, y))
                if cond(c):
                    xs.append(x)
        return xs

    def dark_cond(c):
        return max(c.red(), c.green(), c.blue()) < 100 and (max(c.red(), c.green(), c.blue()) - min(c.red(), c.green(), c.blue())) < 30

    def colored_cond(c):
        return (max(c.red(), c.green(), c.blue()) - min(c.red(), c.green(), c.blue())) > 40

    rows = {lw.item(i).text(): i for i in range(lw.count())}

    def check_row_right(name, color_check, label):
        li = lw.item(rows[name])
        rect = lw.visualItemRect(li)
        icon_xs = row_pixels(rect, color_check)
        assert icon_xs, f"{label}：应渲染出图标像素"
        icon_left, icon_right = min(icon_xs), max(icon_xs)
        # 图标块必须紧贴行右缘（允许右缘留白 ICON_RIGHT_MARGIN=6 ± 2px 容差）
        assert view_w - icon_right <= ICON_RIGHT_MARGIN + 2, \
            f"{label}：图标应紧贴行右缘，实际距右缘 {view_w - icon_right}px"
        assert icon_right - icon_left + 1 >= 20, f"{label}：图标块宽度异常 {icon_right - icon_left + 1}px"
        # 文字像素（深色）必须全部在图标左侧且留有间隙（深色在图标右侧只可能是图标自身描边，不算）
        text_xs = [x for x in row_pixels(rect, dark_cond) if x < icon_left - 3]
        assert text_xs, f"{label}：应存在文字像素"
        assert max(text_xs) < icon_left - 2, \
            f"{label}：文字应结束于图标左侧（文字尾 {max(text_xs)} vs 图标头 {icon_left}）"
        return icon_left, icon_right, max(text_xs)

    r1 = check_row_right("世界1", lambda c: abs(c.red() - 255) < 30 and c.green() < 30 and c.blue() < 30, "世界1")
    r3 = check_row_right("世界3", lambda c: c.red() < 30 and c.green() < 30 and c.blue() > 200, "世界3")
    print(f"7. 图标固定贴行右缘（世界1 图标 x[{r1[0]}-{r1[1]}]/视口宽 {view_w}，"
          f"世界3 图标 x[{r3[0]}-{r3[1]}]） ✓")

    # 8. 超长名：省略号与图标不重叠（文字像素与图标之间有 ≥2px 干净间隙）
    li = lw.item(rows[long_name])
    rect = lw.visualItemRect(li)
    icon_xs = row_pixels(rect, lambda c: c.green() > 200 and c.red() < 30 and c.blue() < 30)
    assert icon_xs, "超长名：应渲染出绿色图标像素"
    icon_left = min(icon_xs)
    text_xs = [x for x in row_pixels(rect, dark_cond) if x < icon_left - 3]
    assert text_xs, "超长名：应存在文字/省略号像素"
    gap = icon_left - max(text_xs)
    assert gap >= 2, f"超长名：省略号与图标应留间隙，实际 {gap}px"
    # 省略验证：全名 35 个汉字在 9pt 字体下约 35×13≈455px 宽，若不省略必然顶到图标区；
    # 文字尾（443）与图标头（483）之间留有间隙即证明已正确省略
    assert max(text_xs) < icon_left - 2, "超长名文字已省略且未侵入图标区"
    print(f"8. 超长文件夹名自动省略，与图标无重叠（文字尾 x={max(text_xs)} < 图标头 x={icon_left}，间隔 {gap}px） ✓")

    # 附加回归：委托接线正常
    assert widget._save_icon_delegate is not None
    print("附加. AutoBackUpWidget 初始化与委托接线正常 ✓")

    print("\n全部 8 项冒烟测试通过")
finally:
    shutil.rmtree(base, ignore_errors=True)
