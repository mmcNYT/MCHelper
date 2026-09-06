# -*- coding: utf-8 -*-
"""生成预览图：模拟真实 saves 目录（用项目 assets 里的 MC 物品纹理充当世界封面）
图标固定显示在行最右侧（含一个超长名世界验证省略效果）
"""
import os
import shutil
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from Tools.tool_AutoBackUp import AutoBackUpWidget

ROOT = r"C:\maomaochongD\Coding\PythonProject\MCHelper"
base = tempfile.mkdtemp(prefix="mc_preview_")
try:
    fake_icons = {
        "我的生存世界": "diamond_sword.png",
        "创造练习图": "diamond_pickaxe.png",
        "服务器下载图": "bow.png",
        "超长名字的世界用来展示文字省略号效果是否正常显示不与图标重叠": "trident.png",
    }
    for name, tex in fake_icons.items():
        world = os.path.join(base, name)
        os.makedirs(world)
        src = os.path.join(ROOT, "assets", "icons", tex)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(world, "icon.png"))
    os.makedirs(os.path.join(base, "无封面文件夹"))
    os.makedirs(os.path.join(base, "新世界（还没有icon）"))
    with open(os.path.join(base, "session.lock"), "w") as f:
        f.write("x")

    widget = AutoBackUpWidget()
    widget.back_up_list = {}
    widget.target_dir_path = base
    widget.targetDirPath.setText(base)
    widget._do_refresh_dir_list()  # 防抖 300ms，预览直接执行实际刷新
    app.processEvents()

    widget.resize(900, 800)
    widget.layoutWidget.setGeometry(40, 30, 800, 700)
    app.processEvents()
    app.processEvents()
    out = os.path.join(ROOT, ".temp", "preview_autobackup_icon.png")
    widget.grab().save(out, "PNG")
    print("预览图已保存:", out, "存在:", os.path.exists(out))

    # 顺带像素自检：每个有图标的行，图标是否贴右缘
    from PySide6.QtGui import QColor
    lw = widget.targetDirList
    img = lw.grab().toImage()
    view_w = lw.viewport().width()
    for i in range(lw.count()):
        li = lw.item(i)
        rect = lw.visualItemRect(li)
        color_xs = []
        for y in range(max(0, rect.top()), min(img.height(), rect.bottom())):
            for x in range(max(0, rect.left()), min(img.width(), rect.right())):
                c = QColor(img.pixel(x, y))
                if (max(c.red(), c.green(), c.blue()) - min(c.red(), c.green(), c.blue())) > 40:
                    color_xs.append(x)
        if color_xs:
            print(f"  {li.text()[:12]}...: 图标 x[{min(color_xs)}-{max(color_xs)}]，"
                  f"距右缘 {view_w - max(color_xs)}px {'✓' if view_w - max(color_xs) <= 8 else '✗'}")
finally:
    shutil.rmtree(base, ignore_errors=True)
