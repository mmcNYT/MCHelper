# -*- coding: utf-8 -*-
"""从 MC jar 提取官方 worldgen JSON 数据到项目 worldgen/ 目录（P0 数据底座）。

仅提取主世界（overworld）精确地形生成所需的三类官方数据：
    density_function/overworld/*.json   —— 密度函数（决定地表高度，P1）
    noise_settings/overworld.json       —— 噪声设置 + 内嵌 surface rule（决定方块，P2）
    noise/*.json                        —— 密度函数/表面规则依赖的噪声参数

数据只读自官方 jar，不做任何改动，供 Python density function 解释器原样解析。
"""
from __future__ import annotations

import json
import os
import sys
import zipfile

JAR_26_2 = r"C:\maomaochongD\.minecraft\.minecraft\versions\26.2-NeoForge\26.2-NeoForge.jar"

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worldgen")


def _collect_noise_refs(density: dict, noise_settings: dict) -> set:
    """递归扫描 density function / noise settings 里引用的 noise 名。"""
    refs = set()

    def walk(node):
        if isinstance(node, dict):
            # type 为 "minecraft:noise" 或 "minecraft:shifted_noise" 时，
            # noise 字段是噪声引用（continentalness/jagged 等）
            t = node.get("type")
            if t in ("minecraft:noise", "minecraft:shifted_noise") \
                    and isinstance(node.get("noise"), str):
                refs.add(node["noise"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for df in density.values():
        walk(df)
    walk(noise_settings)
    return refs


def _json_by_name(zf: zipfile.ZipFile, prefix: str, want=None) -> dict:
    found = {}
    for entry in zf.namelist():
        if not (entry.startswith(prefix) and entry.endswith(".json")):
            continue
        name = entry[len(prefix):].rstrip("/")
        if want is not None and name != want:
            continue
        with zf.open(entry) as f:
            found[name] = json.loads(f.read().decode("utf-8"))
    return found


def _dump(root: str, sub: str, name: str, data) -> None:
    d = os.path.join(root, sub, os.path.dirname(name))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(root, sub, name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def extract_version(jar_path: str, tag: str) -> None:
    with zipfile.ZipFile(jar_path) as zf:
        df_prefix = "data/minecraft/worldgen/density_function/overworld/"
        ns_prefix = "data/minecraft/worldgen/noise_settings/"
        noise_prefix = "data/minecraft/worldgen/noise/"

        density = _json_by_name(zf, df_prefix)
        noise_settings = _json_by_name(zf, ns_prefix, want="overworld.json")
        noise = _json_by_name(zf, noise_prefix)
        # 全局 density function（shift_x/shift_z/y/zero），供 overworld 引用
        g_prefix = "data/minecraft/worldgen/density_function/"
        global_df = {}
        for rel, data in _json_by_name(zf, g_prefix, want=None).items():
            if rel in ("shift_x.json", "shift_z.json", "y.json", "zero.json"):
                global_df[rel] = data

    refs = _collect_noise_refs(density, noise_settings)
    # 引用名形如 "minecraft:jagged"，去掉命名空间前缀后与 noise/xxx.json 匹配
    ref_names = {r.split(":", 1)[-1] + ".json" for r in refs}
    used_noise = {k: noise[k] for k in noise if k in ref_names}
    missing = ref_names - set(noise.keys())

    dst = os.path.join(OUT_DIR, tag)
    for rel, data in density.items():
        _dump(dst, "density_function", rel, data)
    _dump(dst, "noise_settings", "overworld.json", noise_settings.get("overworld.json", {}))
    for name, data in used_noise.items():
        _dump(dst, "noise", name, data)
    for rel, data in global_df.items():
        _dump(dst, "density_function", rel, data)

    if missing:
        raise RuntimeError(f"[{tag}] 缺失噪声引用: {sorted(missing)}")

    # 汇总统计
    print(f"[{tag}] 密度函数={len(density)} 噪声={len(used_noise)} "
          f"噪声设置=1 引用缺失={sorted(missing) if missing else 0}")


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    print("输出目录:", OUT_DIR)
    extract_version(JAR_26_2, "26.2")
    print("完成。")