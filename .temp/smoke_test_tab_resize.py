# -*- coding: utf-8 -*-
"""冒烟测试：切换 tab 时主窗口自适应当前工具 preferred_size。

用例：
1. 已注册工具类都声明了正确的 preferred_size（按名字匹配，不限定总数）
2. 启动后（singleShot 补偿）首个 tab 即自适应：不保持默认 800x600
3. 切到附魔计算器（634×518）：工具页实际尺寸 ≈ 634×518
4. 切回自动备份（628×475）：工具页实际尺寸 ≈ 628×475
5. 从任意窗口尺寸出发自适应依然成立（先改窗口大小再切换）
6. 最大化状态下切换 tab：不干预（保持最大化、不崩溃）
7. 未声明 preferred_size 的工具（None）：窗口大小保持不动
8. closeEvent 的 can_close 检查：备份中阻止关窗，非备份状态放行
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtCore import QTimer

RESULTS = []
TOL = 4  # 允许的风格边框像素误差（QTabWidget 页面 pane 边框等）


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))


def approx(a, b):
    return abs(a - b) <= TOL


def main():
    app = QApplication(sys.argv)
    from main_window import MainWindow
    from Tools import TOOL_CLASSES
    from Tools.tool_base import BaseToolWidget

    win = MainWindow()
    win.move(60, 60)
    win.show()
    for _ in range(5):
        app.processEvents()

    # 用例 1：类属性声明（按名字匹配，兼容后续新增工具）
    name_set = {c.__name__ for c in TOOL_CLASSES}
    by_name = {c.__name__: c for c in TOOL_CLASSES}
    check("1a 已注册工具均已声明 preferred_size",
          "AutoBackUpWidget" in name_set and "EnchantCalculatorWidget" in name_set
          and all(getattr(c, "preferred_size", None) for c in TOOL_CLASSES),
          str(sorted(name_set)))
    check("1b AutoBackUp preferred_size", getattr(by_name.get("AutoBackUpWidget"), "preferred_size", None) == (628, 475))
    check("1c Enchant preferred_size", getattr(by_name.get("EnchantCalculatorWidget"), "preferred_size", None) == (634, 518))

    # 用例 2：启动自适应——不依赖手动切 tab，首次显示即为当前工具尺寸
    win0 = MainWindow()
    win0.move(60, 60)
    win0.show()
    for _ in range(20):
        app.processEvents()
    idx0 = win0.tabWidget.currentIndex()
    w_startup = win0.tabWidget.widget(idx0)
    pref0 = getattr(w_startup, "preferred_size", None)
    check("2 启动即自适应（非默认 800x600）",
          pref0 and approx(w_startup.width(), pref0[0]) and approx(w_startup.height(), pref0[1]),
          f"idx={idx0} actual={w_startup.width()}x{w_startup.height()} preferred={pref0}")
    win0.close()

    # 用例 3：切到附魔计算器 tab（按名字定位，不依赖索引）
    ench_idx = [i for i in range(win.tabWidget.count())
                if win.tabWidget.widget(i).__class__.__name__ == "EnchantCalculatorWidget"][0]
    win.tabWidget.setCurrentIndex(ench_idx)
    for _ in range(8):
        app.processEvents()
    w1 = win.tabWidget.widget(ench_idx)
    check("3 附魔页自适应 634x518",
          approx(w1.width(), 634) and approx(w1.height(), 518),
          f"actual={w1.width()}x{w1.height()} win={win.width()}x{win.height()}")

    # 用例 4：切回自动备份 tab（index 0）
    win.tabWidget.setCurrentIndex(0)
    for _ in range(8):
        app.processEvents()
    w0 = win.tabWidget.widget(0)
    check("4 备份页自适应 628x475",
          approx(w0.width(), 628) and approx(w0.height(), 475),
          f"actual={w0.width()}x{w0.height()} win={win.width()}x{win.height()}")

    # 用例 5：从另一个窗口尺寸出发（用户手动拉大过窗口）
    win.resize(1000, 700)
    for _ in range(5):
        app.processEvents()
    win.tabWidget.setCurrentIndex(ench_idx)
    for _ in range(8):
        app.processEvents()
    w1 = win.tabWidget.widget(ench_idx)
    check("5 任意起点尺寸自适应",
          approx(w1.width(), 634) and approx(w1.height(), 518),
          f"actual={w1.width()}x{w1.height()} win={win.width()}x{win.height()}")

    # 用例 6：最大化保护
    win.showMaximized()
    for _ in range(5):
        app.processEvents()
    was_max = win.isMaximized()
    win.tabWidget.setCurrentIndex(0)
    for _ in range(8):
        app.processEvents()
    check("6 最大化时切换不干预", was_max and win.isMaximized(), f"was_max={was_max}")

    # 用例 7：未声明 preferred_size 的工具
    win.showNormal()
    for _ in range(5):
        app.processEvents()

    class DummyTool(BaseToolWidget):
        preferred_size = None

        @classmethod
        def tool_name(cls):
            return "Dummy"

    dummy = DummyTool()
    idx = win.tabWidget.addTab(dummy, "Dummy")
    size_before = (win.width(), win.height())
    win.tabWidget.setCurrentIndex(idx)
    for _ in range(8):
        app.processEvents()
    size_after = (win.width(), win.height())
    check("7 无声明工具窗口不变", size_before == size_after, f"{size_before} -> {size_after}")

    # 用例 8：closeEvent 的 can_close 检查（备份中阻止关窗，非备份状态放行）
    # 注意：真实 closeEvent 会弹模态 QMessageBox（备份中警告），自动化里必须
    # 替换为记录器，否则会阻塞等待用户点击导致测试挂死
    import main_window as mw_mod

    warned = []
    mw_mod.QMessageBox.warning = staticmethod(lambda *a, **k: warned.append(a))
    from PySide6.QtGui import QCloseEvent

    abu = win.tabWidget.widget(0)
    # 备份进行中：can_close 返回 False → 关窗被 ignore + 弹警告
    abu.is_backing_up = True
    ev1 = QCloseEvent()
    win.closeEvent(ev1)
    check("8a 备份中关窗被阻止", ev1.isAccepted() is False and len(warned) == 1,
          f"accepted={ev1.isAccepted()} warned={len(warned)}")
    abu.is_backing_up = False
    # 非备份状态：can_close 返回 True → 不走 ignore 分支（accept 或托盘隐藏均可）、无警告
    ev2 = QCloseEvent()
    win.closeEvent(ev2)
    check("8b 非备份状态不阻止关窗", ev2.isAccepted() is not False and len(warned) == 1,
          f"accepted={ev2.isAccepted()}")

    win.close()
    app.processEvents()

    # 输出结果（stdout 可能被吞，同时写文件）
    lines = []
    passed = 0
    for name, ok, detail in RESULTS:
        mark = "PASS" if ok else "FAIL"
        passed += ok
        lines.append(f"[{mark}] {name}  {detail}")
    lines.append(f"合计: {passed}/{len(RESULTS)} 通过")
    report = "\n".join(lines)
    print(report)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_tab_resize_result.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(report + "\n")


if __name__ == "__main__":
    main()
