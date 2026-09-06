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

out = open(r"C:\maomaochongD\Coding\PythonProject\MCHelper\.temp\_exp_out.txt", "w", encoding="utf-8")
# 逐步加码找会触发过于昂贵的组合
combos = {
  "原组合": [card("剑"), card("附魔书", ("sharpness","锋利",5),("looting","抢夺",3),("fire_aspect","火焰附加",2),("knockback","击退",2),("sweeping_edge","横扫之刃",3)), card("附魔书", ("mending","经验修补",1),("unbreaking","耐久",3),("vanishing_curse","消失诅咒",1))],
  "加更多书": [card("剑")] + [card("附魔书", (eid, ename, lv)) for eid, ename, lv in [("sharpness","锋利",5),("looting","抢夺",3),("fire_aspect","火焰附加",2),("knockback","击退",2),("sweeping_edge","横扫之刃",3),("mending","经验修补",1),("unbreaking","耐久",3),("vanishing_curse","消失诅咒",1)]],
}
for name, cards in combos.items():
    try:
        plan = opt.optimize(build_items_from_cards(cards))
        out.write(f"{name}: steps={len(plan.steps)} total_cost={plan.total_cost} too_expensive={len(plan.too_expensive_steps)}\n")
        for s in plan.steps:
            out.write(f"   cost={s.cost} prior={getattr(s,'prior_work',None)}\n")
    except Exception as e:
        out.write(f"{name}: EXC {e!r}\n")
out.write("DONE\n")
out.close()
