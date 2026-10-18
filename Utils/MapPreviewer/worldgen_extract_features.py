# -*- coding: utf-8 -*-
"""从 26.2 jar 提取地物/结构相关 worldgen JSON 到 _native/worldgen/26.2。

只提取植被与结构渲染需要的目录，避免全量膨胀。产物供 vegetation.py / 结构
footprint 解析。幂等：重复运行覆盖。
"""
import json
import os
import zipfile

JAR = r"C:\maomaochongD\.minecraft\.minecraft\versions\26.2-NeoForge\26.2-NeoForge.jar"
OUT = (r"C:\maomaochongD\Coding\PythonProject\MCHelper\Utils\MapPreviewer"
       r"\_native\worldgen\26.2")

DIRS = {
    "biome": "data/minecraft/worldgen/biome/",
    "placed_feature": "data/minecraft/worldgen/placed_feature/",
    "configured_feature": "data/minecraft/worldgen/configured_feature/",
    "structure": "data/minecraft/worldgen/structure/",
    "structure_set": "data/minecraft/worldgen/structure_set/",
}


def main():
    z = zipfile.ZipFile(JAR)
    names = z.namelist()
    total = 0
    for key, prefix in DIRS.items():
        outd = os.path.join(OUT, key)
        os.makedirs(outd, exist_ok=True)
        cnt = 0
        for n in names:
            if not n.startswith(prefix) or not n.endswith(".json"):
                continue
            base = n[len(prefix):-5]          # 去掉前缀目录与 .json
            if "/" in base:                    # 子目录（少见）压平为 __
                base = base.replace("/", "__")
            data = z.read(n)
            try:
                obj = json.loads(data)         # 校验可解析
            except Exception as e:
                print("  skip %s: %s" % (n, e))
                continue
            with open(os.path.join(outd, base + ".json"), "w",
                      encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False)
            cnt += 1
        print("%-20s %d" % (key, cnt))
        total += cnt
    print("total extracted:", total)


if __name__ == "__main__":
    main()
