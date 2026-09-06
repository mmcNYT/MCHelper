import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")
from Utils.anvil_optimizer import AnvilOptimizer, build_items_from_cards
from Utils.enchant_data_manager import DataManager

dm = DataManager()
opt = AnvilOptimizer(dm)

def card(item_name, *enchs):
    return {"item_name": item_name,
            "enchants": [{"id": e[0], "name": e[1], "level": e[2]} for e in enchs]}

out = open(r"C:\maomaochongD\Coding\PythonProject\MCHelper\.temp\_exp_out3.txt", "w", encoding="utf-8")
# 平衡二叉合并策略：惩罚翻倍按 log2(n) 层级走，最后一步 cost 随层级上涨
# 16 本书平衡合并 → 最深处 4 层惩罚（8+16+32+64 量级）必然 ≥40
books16 = []
for k in range(16):
    eid = f"unbreaking{'' if k==0 else ''}"
    # 用真实 id 轮换（同 id 多本会被合并等级，不影响惩罚层级）
    books16.append(card("附魔书", ("unbreaking", "耐久", 3)))
cards = [card("剑")] + books16
try:
    plan = opt.optimize(build_items_from_cards(cards))
    out.write(f"剑+16同种书: steps={len(plan.steps)} total={plan.total_cost} too_exp={plan.too_expensive_steps}\n")
    for i, s in enumerate(plan.steps):
        out.write(f"   step{i+1} cost={s.cost}\n")
except Exception as e:
    out.write(f"EXC {e!r}\n")
out.write("DONE\n")
out.close()
