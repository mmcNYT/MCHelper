# -*- coding: utf-8 -*-
"""StrongHoldFinder 冒烟测试（结果写入 txt，规避 stdout 偶发被吞的问题）。

覆盖：F3+C 解析（标准/纯数字/兼容性/错误输入）、yaw 方向向量与八方位、
直线交点几何正确性、反方向警示参数、平行/同位置报错、offscreen UI 全流程。
"""

import math
import re
import sys

PROJECT_ROOT = r"C:\maomaochongD\Coding\PythonProject\MCHelper"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Utils.StrongHoldFinder.stronghold_math import (  # noqa: E402
    intersect_rays,
    normalize_yaw,
    parse_f3c_command,
    yaw_to_compass,
    yaw_to_direction,
)

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))


def yaw_towards(from_x, from_z, to_x, to_z):
    """构造「从观测点指向目标点」的 yaw（MC 角度系），用于几何测试。"""
    dx, dz = to_x - from_x, to_z - from_z
    return math.degrees(math.atan2(-dx, dz))


# ---------- 1. F3+C 命令解析 ----------
cmd = "/execute in minecraft:overworld run tp @s 123.45 64.00 -678.90 120.5 15.0"
x, z, yaw = parse_f3c_command(cmd)
check("解析标准 F3+C 命令", (x, z, yaw) == (123.45, -678.90, 120.5), f"{x},{z},{yaw}")

x, z, yaw = parse_f3c_command("123.45 64 -678.9 120.5 15.5")
check("解析手打纯数字", (x, z, yaw) == (123.45, -678.9, 120.5), f"{x},{z},{yaw}")

x, z, yaw = parse_f3c_command("/tp @p 12.5 70 -3.5 -90 0")
check("解析旧版短命令", (x, z, yaw) == (12.5, -3.5, -90.0), f"{x},{z},{yaw}")

x, z, yaw = parse_f3c_command("tp @s 1 2 3 4 5 6 7 8 9 123.4 65.0 -6.7 88.8 5.0")
check("多余数字时取最后 5 个", (x, z, yaw) == (123.4, -6.7, 88.8), f"{x},{z},{yaw}")

try:
    parse_f3c_command("/execute in minecraft:overworld run tp @s 1 2 3")
    check("数字不足报错", False, "未抛出 ValueError")
except ValueError:
    check("数字不足报错", True)

try:
    parse_f3c_command("   ")
    check("空输入报错", False, "未抛出 ValueError")
except ValueError:
    check("空输入报错", True)

# ---------- 2. yaw 方向向量与八方位 ----------
cases = [(0.0, (0, 1), "南"), (90.0, (-1, 0), "西"), (180.0, (0, -1), "北"),
         (270.0, (1, 0), "东"), (-90.0, (1, 0), "东"), (45.0, None, "西南")]
ok_dir = ok_compass = True
details = []
for yaw0, expect, comp in cases:
    dx, dz = yaw_to_direction(yaw0)
    if expect is not None and (abs(dx - expect[0]) > 1e-9 or abs(dz - expect[1]) > 1e-9):
        ok_dir = False
        details.append(f"yaw={yaw0}: ({dx:.3f},{dz:.3f})")
    if yaw_to_compass(yaw0) != comp:
        ok_compass = False
        details.append(f"yaw={yaw0}: {yaw_to_compass(yaw0)}!={comp}")
check("yaw 方向向量（0=南,90=西,180=北,270=东）", ok_dir, "; ".join(details))
check("yaw 八方位映射", ok_compass, "; ".join(details))
check("normalize_yaw 规范到 [-180,180)", normalize_yaw(270) == -90 and normalize_yaw(-180) == -180,
      f"270->{normalize_yaw(270)}, -180->{normalize_yaw(-180)}")

# ---------- 3. 直线交点几何正确性 ----------
stronghold = (300.0, -200.0)  # 假想要塞
p1, p2 = (0.0, 0.0), (500.0, 100.0)
r = intersect_rays(p1[0], p1[1], yaw_towards(*p1, *stronghold),
                   p2[0], p2[1], yaw_towards(*p2, *stronghold))
check("交点坐标正确", abs(r["x"] - 300) < 1e-6 and abs(r["z"] + 200) < 1e-6,
      f"({r['x']:.4f},{r['z']:.4f})")
check("交点在两条视线前方(t>0)", r["t1"] > 0 and r["t2"] > 0, f"t1={r['t1']:.2f}, t2={r['t2']:.2f}")
d1 = math.hypot(stronghold[0] - p1[0], stronghold[1] - p1[1])
check("距离正确", abs(r["dist1"] - d1) < 1e-6, f"dist1={r['dist1']:.4f} vs {d1:.4f}")

# 准星没对准（yaw 反向 180°）→ t 为负，结果仍返回（UI 层警示）
r_back = intersect_rays(p1[0], p1[1], yaw_towards(*p1, *stronghold),
                        p2[0], p2[1], yaw_towards(*p2, *stronghold) + 180)
check("反向瞄准 t2<0", r_back["t2"] < 0, f"t2={r_back['t2']:.2f}")

# ---------- 4. 异常场景 ----------
try:
    intersect_rays(0, 0, 0, 100, 0, 0)  # 平行（同 yaw 不同位置）
    check("平行视线报错", False, "未抛出 ValueError")
except ValueError as e:
    check("平行视线报错", "平行" in str(e), str(e)[:40])

try:
    intersect_rays(0, 0, 0, 0.1, 0, 90)  # 几乎同位置
    check("同位置报错", False, "未抛出 ValueError")
except ValueError as e:
    check("同位置报错", "同一位置" in str(e), str(e)[:40])

# ---------- 5. UI 全流程（offscreen） ----------
os_ok = ui_detail = ""
try:
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from Tools import TOOL_CLASSES

    app = QApplication.instance() or QApplication([])
    widget_cls = next(c for c in TOOL_CLASSES if c.tool_name() == "StrongHoldFinder")
    w = widget_cls()

    def f3c(px, pz, y):
        return f"/execute in minecraft:overworld run tp @s {px} 64.00 {pz} {y} 15.0"

    # 初始说明文字
    check("打开工具有使用说明", "使用方法" in w.informationBrowser.toPlainText())

    # 空输入点击计算 → 提示
    w.doCaculate.click()
    check("空输入提示", "粘贴" in w.informationBrowser.toPlainText())

    # 正常计算（按钮信号触发）
    w.coordinate1Edit.setText(f3c(p1[0], p1[1], round(yaw_towards(*p1, *stronghold), 1)))
    w.coordinate2Edit.setText(f3c(p2[0], p2[1], round(yaw_towards(*p2, *stronghold), 1)))
    w.doCaculate.click()
    out = w.informationBrowser.toPlainText()
    m = re.search(r"交点（要塞水平位置）：X = ([-\d.]+)，Z = ([-\d.]+)", out)
    check("计算结果输出",
          bool(m) and abs(float(m.group(1)) - 300) < 0.5 and abs(float(m.group(2)) + 200) < 0.5,
          out.replace("\n", " | ")[:150])

    # 错误输入 → 计算失败提示
    w.coordinate1Edit.setText("随便写的文字")
    w.doCaculate.click()
    check("错误输入提示", "计算失败" in w.informationBrowser.toPlainText())

    # 清除按钮
    w.clearCoordinates.click()
    check("清除按钮生效",
          w.coordinate1Edit.text() == "" and w.coordinate2Edit.text() == ""
          and w.informationBrowser.toPlainText() == "")

    # 主窗口注册表包含本工具
    check("TOOL_CLASSES 注册", widget_cls is not None and widget_cls.tool_name() == "StrongHoldFinder")
except Exception as e:  # noqa: BLE001
    os_ok = f"{type(e).__name__}: {e}"
    check("UI 全流程", False, os_ok)

# ---------- 6. looks_like_f3c 预判（剪贴板自动填入门槛） ----------
from Utils.StrongHoldFinder.stronghold_math import looks_like_f3c  # noqa: E402

check("预判：标准 F3+C 命令", looks_like_f3c(cmd) is True)
check("预判：手打纯数字", looks_like_f3c("123.45 64 -678.9 120.5 15.5") is True)
check("预判：无小数点拒绝", looks_like_f3c("1 2 3 4 5") is False)
check("预判：数字太少拒绝", looks_like_f3c("价格 19.99 元") is False)
check("预判：版本号文本拒绝", looks_like_f3c("version 1.2.3 build 4567") is False)
check("预判：纯文字拒绝", looks_like_f3c("hello world") is False)
check("预判：空文本拒绝", looks_like_f3c("") is False)
check("预判：超长文本拒绝", looks_like_f3c("1.1 " * 60) is False)

# ---------- 7. UI 自动填入（剪贴板 → 首个空输入框） ----------
os_ok2 = ui_detail2 = ""
try:
    import time
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    # 先把剪贴板换成无害文本，等真实监听线程消化掉这次变化，避免干扰后续断言
    QApplication.clipboard().setText("无数字的占位文本")
    time.sleep(0.5)
    for _ in range(25):
        app.processEvents()
        time.sleep(0.02)
    w._on_clear_coordinates_clicked()

    cmd_a = "/execute in minecraft:overworld run tp @s 10.50 64.00 20.25 -35.7 12.0"
    cmd_b = "/execute in minecraft:overworld run tp @s 210.75 65.00 -85.50 55.3 8.0"
    cmd_c = "/execute in minecraft:overworld run tp @s 1.00 64.00 2.00 90.0 0.0"

    # 复制第一条 → 槽触发 → 填入坐标一
    QApplication.clipboard().setText(cmd_a)
    w._on_clipboard_changed()
    check("自动填入坐标一", w.coordinate1Edit.text() == cmd_a and w.coordinate2Edit.text() == "")

    # 同一文本再次触发 → 不重复处理
    w._on_clipboard_changed()
    check("同一文本不重复填入", w.coordinate2Edit.text() == "")

    # 非 F3+C 内容 → 不填入
    QApplication.clipboard().setText("普通文本 123.45")
    w._on_clipboard_changed()
    check("非 F3+C 内容不填入", w.coordinate2Edit.text() == "")

    # 复制第二条 → 填入坐标二
    QApplication.clipboard().setText(cmd_b)
    w._on_clipboard_changed()
    check("自动填入坐标二", w.coordinate2Edit.text() == cmd_b
          and "计算" in w.informationBrowser.toPlainText())

    # 两框皆有内容 + 新内容 → 不覆盖
    QApplication.clipboard().setText(cmd_c)
    w._on_clipboard_changed()
    check("两框已满不覆盖", w.coordinate1Edit.text() == cmd_a and w.coordinate2Edit.text() == cmd_b)

    # 自动填入的数据可直接计算
    w.doCaculate.click()
    check("自动填入后可直接计算", "要塞定位结果" in w.informationBrowser.toPlainText())

    # 清除按钮
    w.clearCoordinates.click()
    check("清除按钮生效",
          w.coordinate1Edit.text() == "" and w.coordinate2Edit.text() == ""
          and w.informationBrowser.toPlainText() == "")

    # ---------- 8. 真实监听线程端到端 ----------
    # offscreen 平台的 Qt 剪贴板不一定写系统剪贴板，故用 ctypes 直接写系统剪贴板触发
    import ctypes

    def set_system_clipboard_text(s: str) -> bool:
        user32 = ctypes.WinDLL("user32")
        kernel32 = ctypes.WinDLL("kernel32")
        # 64 位下句柄是 64 位，必须显式声明，否则默认按 32 位截断
        user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        user32.OpenClipboard.restype = ctypes.c_bool
        user32.EmptyClipboard.restype = None
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        user32.CloseClipboard.restype = None
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        if not user32.OpenClipboard(None):
            return False
        try:
            user32.EmptyClipboard()
            data = s.encode("utf-16-le") + b"\x00\x00"
            h = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
            p = kernel32.GlobalLock(h)
            if not p:
                return False
            ctypes.memmove(p, data, len(data))
            kernel32.GlobalUnlock(h)
            user32.SetClipboardData(13, h)  # CF_UNICODETEXT
            return True
        finally:
            user32.CloseClipboard()

    from Threads.task_StrongHoldFinder import ClipboardListenerThread

    received = []
    listener = ClipboardListenerThread()
    listener.clipboard_changed.connect(lambda: received.append(1))
    listener.start()
    time.sleep(0.4)  # 记录基准序号
    written = set_system_clipboard_text(cmd_a)
    for _ in range(100):
        app.processEvents()
        time.sleep(0.02)
    listener.requestInterruption()
    listener.quit()
    check("真实线程检测到剪贴板变化", written and len(received) >= 1,
          f"written={written}, received={received}")
    check("线程可正常停止", listener.wait(1000) and listener.isFinished())

    # ---------- 9. closeEvent 停止工具内的监听线程 ----------
    w.closeEvent(QCloseEvent())
    check("closeEvent 停止监听线程",
          w._clipboard_thread.isFinished() or w._clipboard_thread.wait(1000))
except Exception as e:  # noqa: BLE001
    os_ok2 = f"{type(e).__name__}: {e}"
    check("UI 自动填入全流程", False, os_ok2)

# ---------- 输出结果 ----------
lines = []
passed = sum(1 for _, ok, _ in RESULTS if ok)
for name, ok, detail in RESULTS:
    lines.append(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  <- {detail}" if detail and not ok else ""))
lines.append(f"合计 {passed}/{len(RESULTS)} 通过")
text = "\n".join(lines)

out_path = PROJECT_ROOT + r"\.temp\smoke_test_stronghold_result.txt"
with open(out_path, "w", encoding="utf-8") as f:
    f.write(text + "\n")
print(text)
