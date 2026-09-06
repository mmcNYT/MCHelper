# -*- coding: utf-8 -*-
"""Wiki 铁砧机制例题验证：机制模拟层（AnvilMechanics.merge）"""
import os
import sys

sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from Utils.enchant_data_manager import DataManager
from Utils.anvil_optimizer import AnvilMechanics, AnvilItem

dm = DataManager()
mech = AnvilMechanics(dm)

# ========== 例题 1：Wiki 16 级 ==========
# 目标剑：锋利III 击退II 抢夺III；牺牲剑：锋利III 抢夺III
# 锋利III→IV 计 1×4=4；抢夺III 同级→III（已满级）计 4×3=12 → 合计 16
t = AnvilItem.make("剑", [("sharpness", 3), ("knockback", 2), ("looting", 3)])
s = AnvilItem.make("剑", [("sharpness", 3), ("looting", 3)])
r, cost, detail = mech.merge(t, s)
assert cost == 16, f"例题1花费应为 16，实际 {cost}"
assert r.enchant_map() == {"sharpness": 4, "knockback": 2, "looting": 3}, r.enchant_map()
print("例题1 目标3附魔剑+牺牲2附魔剑 = 16 级 ✓", detail["enchant_costs"])

# 反向（3附魔剑作牺牲）：多计击退II 2×2=4 → 20
r2, cost2, _ = mech.merge(s, t)
assert cost2 == 20, f"反向合并应为 20，实际 {cost2}"
print("例题1b 反向合并 = 20 级 ✓")

# ========== 例题 2：Wiki 15 级 ==========
# 目标剑：锋利III 击退II 抢夺I；牺牲剑：锋利I 抢夺III
# 锋利I 目标更高 → 按输出锋利III 计 1×3=3；抢夺III 目标更低 → 升至III 计 4×3=12 → 15
t2 = AnvilItem.make("剑", [("sharpness", 3), ("knockback", 2), ("looting", 1)])
s2 = AnvilItem.make("剑", [("sharpness", 1), ("looting", 3)])
r, cost, detail = mech.merge(t2, s2)
assert cost == 15, f"例题2花费应为 15，实际 {cost}"
assert r.enchant_map() == {"sharpness": 3, "knockback": 2, "looting": 3}
print("例题2 不同等级魔咒 = 15 级 ✓")

# 反向合并（3附魔剑作牺牲）：多计击退II 2×2=4 → 19
r2b, cost2b, _ = mech.merge(s2, t2)
assert cost2b == 19, f"反向合并应为 19，实际 {cost2b}"
print("例题2b 反向合并 = 19 级 ✓")

# ========== 例题 3：Wiki 7 级（附魔书） ==========
# 目标剑：抢夺II；牺牲书：保护III 锋利I 抢夺II
# 保护III 不适用于剑 → 忽略；锋利I 目标无 → 获得I 计 1×1=1；
# 抢夺II 同级 → III 计 书乘数2×3=6 → 7
t3 = AnvilItem.make("剑", [("looting", 2)])
s3 = AnvilItem.make("附魔书", [("protection", 3), ("sharpness", 1), ("looting", 2)])
r, cost, detail = mech.merge(t3, s3)
assert cost == 7, f"例题3花费应为 7，实际 {cost}"
assert r.enchant_map() == {"looting": 3, "sharpness": 1}, r.enchant_map()
assert ("protection", "不适用于该物品类型，忽略不计费") in detail["ignored"]
print("例题3 剑(抢夺II)+书(保护III锋利I抢夺II) = 7 级 ✓")

# ========== 例题 4：Wiki 13 级（互斥魔咒） ==========
# 目标剑：锋利II 抢夺II；牺牲剑：亡灵杀手V 抢夺II
# 亡灵杀手V 与锋利互斥 → +1 不转移；抢夺II 同级 → III 计 4×3=12 → 13
t4 = AnvilItem.make("剑", [("sharpness", 2), ("looting", 2)])
s4 = AnvilItem.make("剑", [("smite", 5), ("looting", 2)])
r, cost, detail = mech.merge(t4, s4)
assert cost == 13, f"例题4花费应为 13，实际 {cost}"
assert "smite" not in r.enchant_map() and r.enchant_map()["looting"] == 3
print("例题4 互斥魔咒（亡灵杀手遇锋利）= 13 级 ✓")
# 反向合并：花费仍 13，但结果是亡灵杀手V+抢夺III
r4b, cost4b, _ = mech.merge(s4, t4)
assert cost4b == 13, f"反向应为 13，实际 {cost4b}"
assert r4b.enchant_map() == {"smite": 5, "looting": 3}, r4b.enchant_map()
print("例题4b 反向合并仍 13 级（结果变亡灵杀手V）✓")

# ========== PWP 规则 ==========
# 合并 PWP 3 与 7 → 结果 15；花费含 3+7=10
t5 = AnvilItem.make("剑", [("sharpness", 5)], pwp=3)
s5 = AnvilItem.make("剑", [("looting", 3)], pwp=7)
r5, cost5, _ = mech.merge(t5, s5)
assert r5.pwp == 15, f"结果 PWP 应为 15，实际 {r5.pwp}"
assert cost5 == 10 + 12, f"花费应为 PWP10+抢夺III(4×3)=22，实际 {cost5}"
print("PWP：3+7 合并 → 结果 15、花费含双方惩罚 ✓")

# ========== 冲突拦截计费（仅互斥 +1） ==========
t6 = AnvilItem.make("剑", [("sharpness", 3)])
s6 = AnvilItem.make("剑", [("smite", 3)])
r6, cost6, _ = mech.merge(t6, s6)
assert cost6 == 1, f"互斥拦截应只 +1，实际 {cost6}"
assert "smite" not in r6.enchant_map(), "亡灵杀手不应转移"
print("互斥拦截：牺牲亡灵杀手遇锋利 → +1 级不转移 ✓")

# ========== 不适用忽略 ==========
t7 = AnvilItem.make("剑", [("sharpness", 5)])
s7 = AnvilItem.make("附魔书", [("protection", 4)])
r7, cost7, _ = mech.merge(t7, s7)
assert cost7 == 0, f"不适用魔咒应忽略不计费，实际 {cost7}"
assert "protection" not in r7.enchant_map()
print("不适用魔咒：保护IV 入剑被忽略，0 级 ✓")

print("\n机制模拟层全部例题通过")
