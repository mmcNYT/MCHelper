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

out = open(r"C:\maomaochongD\Coding\PythonProject\MCHelper\.temp\_exp_out2.txt", "w", encoding="utf-8")
# 触发 ≥40 级需要更高的累积惩罚：满级书套餐（剑 + 8 种满级书，其中多层书）
books = []
for eid, ename, lv in [("sharpness","锋利",5),("looting","抢夺",3),("fire_aspect","火焰附加",2),
                       ("knockback","击退",2),("sweeping_edge","横扫之刃",3),("mending","经验修补",1),
                       ("unbreaking","耐久",3),("vanishing_curse","消失诅咒",1),
                       ("bane_of_arthropods","节肢杀手",5),("smite","亡灵杀手",5)]:
    books.append(card("附魔书", (eid, ename, lv)))
# 注意互斥：锋利/节肢/亡灵互斥——最后合成会拦截。用 untested 大组合:
combos = {
  "剑+10书（含互斥组）": [card("剑")] + books,
}
for name, cards in combos.items():
    try:
        plan = opt.optimize(build_items_from_cards(cards))
        out.write(f"{name}: steps={len(plan.steps)} total={plan.total_cost} too_exp={plan.too_expensive_steps}\n")
        for i, s in enumerate(plan.steps):
            out.write(f"   step{i+1} cost={s.cost}\n")
    except Exception as e:
        out.write(f"{name}: EXC {e!r}\n")
out.write("DONE\n")
out.close()
