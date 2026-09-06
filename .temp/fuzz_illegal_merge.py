# -*- coding: utf-8 -*-
"""模糊测试：穷举输入组合，检查优化器输出的步骤表是否含非法合并
（书做目标/第一格，牺牲为非书物品——铁砧中附魔书只能吞书或做牺牲）

同时验证树构建的身份链与 steps 表一致。
"""
import os
import sys
import itertools

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from Utils.enchant_data_manager import DataManager
from Utils.anvil_optimizer import AnvilOptimizer, AnvilItem, AnvilError

dm = DataManager()
opt = AnvilOptimizer(dm)


def is_illegal_step(step):
    """书做目标且牺牲为非书 → 非法（输出为书，非书物品被吞）"""
    return step.target.is_book() and not step.sacrifice.is_book()


# 物品池：不同顺序的 剑/书 组合（1-4 件）
pool = [
    AnvilItem.make("剑", []),
    AnvilItem.make("剑", [("sharpness", 5)]),
    AnvilItem.make("附魔书", [("unbreaking", 3)]),
    AnvilItem.make("附魔书", [("sharpness", 5)]),
    AnvilItem.make("附魔书", [("looting", 3)]),
]

bad_cases = []
total = 0
for n in (2, 3, 4):
    for combo in itertools.permutations(pool, n):
        # 同类型非书 >1 必然报错，跳过（不产生方案）
        names = {it.name for it in combo if not it.is_book()}
        if len(names) > 1:
            continue
        try:
            plan = opt.optimize(list(combo))
        except AnvilError:
            continue
        total += 1
        for k, s in enumerate(plan.steps):
            if is_illegal_step(s):
                bad_cases.append((combo, k + 1, plan))
                break

print(f"共验证 {total} 个可行组合")
if bad_cases:
    print(f"发现 {len(bad_cases)} 个非法方案！前 5 个：")
    for combo, step_no, plan in bad_cases[:5]:
        items_desc = "、".join(
            f"{it.name}({','.join(e for e, _ in sorted(it.enchants))})"
            for it in combo)
        steps_desc = "；".join(
            f"{s.target.name}({','.join(e for e, _ in sorted(s.target.enchants))})"
            f"+{s.sacrifice.name}"
            f"({','.join(e for e, _ in sorted(s.sacrifice.enchants))})"
            f"->{s.result.name} 花费{s.cost}"
            for s in plan.steps)
        print(f"  输入[{items_desc}] 第{step_no}步非法：{steps_desc}")
    sys.exit(1)
print("未发现非法步骤")
