# -*- coding: utf-8 -*-
"""构建 SeedReverser 的 C++ 层 2 扩展（_solver_native.pyd）。

用法（项目根目录）：
    python Utils/SeedReverser/_native/build_native.py

环境要求：
    - MSVC（cl.exe）在 PATH 中（建议在 "x64 Native Tools Command Prompt
      for VS" 里运行；或从 PyCharm 的 VS 环境终端运行）
    - venv 已安装 pybind11（pip install pybind11）

产物：Utils/SeedReverser/_native/_solver_native.pyd
    失败时 structure_math.py 自动降级 numpy 路径，不影响工具可用性。
"""

import os
import subprocess
import sys
import sysconfig

import pybind11

NATIVE_DIR = os.path.dirname(os.path.abspath(__file__))
CPP = os.path.join(NATIVE_DIR, "_solver_native.cpp")
PYD = os.path.join(NATIVE_DIR, "_solver_native.pyd")
LOG = os.path.join(NATIVE_DIR, "_build_log.txt")

PY_INCLUDE = sysconfig.get_paths()["include"]
# sysconfig 的 nt 方案无 "libs" 键：python313.lib 位于安装根的 libs/ 下
PY_LIBS = os.path.join(sys.base_prefix, "libs")
PB_INCLUDE = pybind11.get_include()

# /MD：与官方 Python 发行版运行时一致（vcruntime 由 python313.dll 提供）。
FLAGS = [
    "/nologo", "/std:c++20", "/utf-8", "/O2", "/EHsc", "/MD", "/LD",
    f"/I{PB_INCLUDE}", f"/I{PY_INCLUDE}",
]

LINK = [
    "/link",
    f"/LIBPATH:{PY_LIBS}",
    "python313.lib",
]


def main():
    if not os.path.exists(CPP):
        print(f"[build] 源文件不存在：{CPP}")
        return 2
    cmd = ["cl", *FLAGS, CPP, f"/Fe:{PYD}",
           f"/Fo:{os.path.join(NATIVE_DIR, '_solver_native.obj')}", *LINK]
    print("[build] " + " ".join(cl for cl in cmd))
    proc = subprocess.run(cmd, cwd=NATIVE_DIR, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    with open(LOG, "w", encoding="utf-8") as f:
        f.write((proc.stdout or "") + (proc.stderr or ""))
    print(f"[build] exit={proc.returncode}，详细输出见 {LOG}")
    if proc.returncode == 0:
        if os.path.exists(PYD):
            print(f"[build] OK -> {PYD}")
            return 0
        print("[build] 编译器返回 0 但未找到 .pyd，请检查 _build_log.txt")
        return 2
    print("[build] 编译失败，请检查 _build_log.txt")
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
