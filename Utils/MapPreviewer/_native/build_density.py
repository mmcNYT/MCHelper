# -*- coding: utf-8 -*-
"""构建 MapPreviewer 逐方块密度采样扩展（_density_sampler.pyd）。

用法（任意目录）：
    python Utils/MapPreviewer/_native/build_density.py

环境要求与 build_map.py 一致：MSVC cl.exe 在 PATH + venv 有 pybind11。
产物：Utils/MapPreviewer/_native/_density_sampler.pyd
"""

import os
import subprocess
import sys
import sysconfig

import pybind11

NATIVE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(NATIVE_DIR, "_density_module.cpp")
PYD = os.path.join(NATIVE_DIR, "_density_sampler.pyd")
LOG = os.path.join(NATIVE_DIR, "_build_density_log.txt")

PY_INCLUDE = sysconfig.get_paths()["include"]
PY_LIBS = os.path.join(sys.base_prefix, "libs")
PB_INCLUDE = pybind11.get_include()

FLAGS = [
    "/nologo", "/std:c++20", "/utf-8", "/O2", "/EHsc", "/MD", "/LD",
    f"/I{PB_INCLUDE}", f"/I{PY_INCLUDE}", f"/I{NATIVE_DIR}",
]

LINK = ["/link", f"/LIBPATH:{PY_LIBS}", "python313.lib"]


def main():
    if not os.path.exists(SRC):
        print(f"[build] 源文件不存在：{SRC}")
        return 2
    obj = os.path.join(NATIVE_DIR, "_density_module.obj")
    cmd = ["cl", *FLAGS, SRC, f"/Fe:{PYD}", f"/Fo:{obj}", *LINK]
    print("[build] cl " + " ".join(FLAGS))
    proc = subprocess.run(cmd, cwd=NATIVE_DIR, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    out = (proc.stdout or "") + (proc.stderr or "")
    with open(LOG, "w", encoding="utf-8") as f:
        f.write(out)
    errs = [ln for ln in out.splitlines() if " error " in ln or "error C" in ln]
    if proc.returncode == 0 and os.path.exists(PYD):
        print(f"[build] OK -> {PYD}")
        if errs:
            print("[build] 警告/错误行：")
            for e in errs[:20]:
                print("   ", e)
        return 0
    print(f"[build] 失败 exit={proc.returncode}")
    for ln in (errs or out.splitlines()[-40:]):
        print("   ", ln)
    return proc.returncode or 2


if __name__ == "__main__":
    sys.exit(main())
