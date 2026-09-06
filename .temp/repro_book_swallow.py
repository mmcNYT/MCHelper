# -*- coding: utf-8 -*-
"""复现：优化器是否会把「书做目标吞非书」作为方案返回"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from Utils.enchant_data_manager import DataManager
from Utils.anvil_optimizer import AnvilOptimizer, AnvilItem

dm = DataManager()
opt = AnvilOptimizer(dm)

cases = {
    "1. 书(u3) + 剑()": [
        AnvilItem.make("附魔书", [("unbreaking", 3)]),
        AnvilItem.make("剑", []),
    ],
    "2. 剑() + 书(u3)": [
        AnvilItem.make("剑", []),
        AnvilItem.make("附魔书", [("unbreaking", 3)]),
    ],
    "3. 书(u3) + 剑(u3)": [
        AnvilItem.make("附魔书", [("unbreaking", 3)]),
        AnvilItem.make("剑", [("unbreaking", 3)]),
    ],
    "4. 书(u3) + 书(u3) + 剑()": [
        AnvilItem.make("附魔书", [("unbreaking", 3)]),
        AnvilItem.make("附魔书", [("unbreaking", 3)]),
        AnvilItem.make("剑", []),
    ],
    "5. 剑() + 书(u3) + 书(sh5)": [
        AnvilItem.make("剑", []),
        AnvilItem.make("附魔书", [("unbreaking", 3)]),
        AnvilItem.make("附魔书", [("sharpness", 5)]),
    ],
}

for name, items in cases.items():
    try:
        plan = opt.optimize(items)
        steps_desc = [
            f"[{s.target.name}({','.join(e for e, _ in sorted(s.target.enchants))})"
            f" + {s.sacrifice.name}"
            f"({','.join(e for e, _ in sorted(s.sacrifice.enchants))})"
            f" -> {s.result.name}({','.join(e for e, _ in sorted(s.result.enchants))})"
            f" 花费{s.cost}]"
            for s in plan.steps
        ]
        final = f"{plan.final_item.name}({','.join(e for e, _ in sorted(plan.final_item.enchants))})"
        print(f"{name}:")
        print(f"  终态: {final}  总花费 {plan.total_cost}")
        for sd in steps_desc:
            print(f"  {sd}")
        bad = plan.final_item.is_book() and any(not it.is_book() for it in items)
        if bad:
            print("  >>> 复现成功：有非书物品却返回书终态！")
    except Exception as e:
        print(f"{name}: 异常 {e}")
    print()
