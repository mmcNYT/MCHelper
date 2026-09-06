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

out = open(r"C:\maomaochongD\Coding\PythonProject\MCHelper\.temp\_exp_out4.txt", "w", encoding="utf-8")
# 优化器总能找到平衡合并规避 40。要触发 too_expensive 须卡住它：
# 多种满级书一次全往一把剑上堆（贪心直链），或用数量足够大的组合
books = []
for eid, ename, lv in [("sharpness","锋利",5),("looting","抢夺",3),("fire_aspect","火焰附加",2),
                       ("knockback","击退",2),("sweeping_edge","横扫之刃",3),("mending","经验修补",1),
                       ("unbreaking","耐久",3),("vanishing_curse","消失诅咒",1)]:
    for _ in range(4):  # 每种 4 本
        books.append(card("附魔书", (eid, ename, lv)))
cards = [card("剑")] + books
try:
    plan = opt.optimize(build_items_from_cards(cards))
    out.write(f"剑+32书(8种x4): steps={len(plan.steps)} total={plan.total_cost} too_exp={plan.too_expensive_steps}\n")
    costs = [s.cost for s in plan.steps]
    out.write(f"   costs={costs}\n")
except Exception as e:
    out.write(f"EXC {e!r}\n")
out.write("DONE\n")
out.close()
