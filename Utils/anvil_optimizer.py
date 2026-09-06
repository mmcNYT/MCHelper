# utils/anvil_optimizer.py
# 铁砧合成优化器：模拟 Java 版铁砧机制（累积惩罚 / 合并魔咒花费 / 合法性判定），
# 并搜索把多件物品（含附魔书）合并成一件的最少总花费方案。
#
# 机制依据（中文 Minecraft Wiki「铁砧机制」）：
# - 单次合并总花费 = 目标PWP + 牺牲PWP + 合并魔咒花费（本工具不考虑维修费/重命名费，
#   假设物品满耐久且不重命名）
# - 累积惩罚（PWP）：物品每经历一次铁砧合并，惩罚在前值基础上 ×2+1（n 次后为 2^n-1）；
#   合并时玩家支付双方 PWP 之和，结果物品 PWP 基于两者中较高者计算下一层
#   （合并 PWP 3 与 7 的物品 → 结果 15）
# - 合并魔咒花费（Java 版按输出物品上的最终等级计费）：对牺牲物品的每条魔咒——
#   不适用于目标物品类型 → 直接忽略，不计费；
#   输出物品已有互斥魔咒 → 不转移，每有一个互斥魔咒 +1 级；
#   否则计费 = 乘数 × 输出物品上该魔咒的最终等级（牺牲是书用书乘数，否则物品乘数）
#   （即使牺牲等级低于目标、等级不上升，仍按输出最终等级计费）
# - 等级合并：目标无此魔咒 → 获得牺牲等级；牺牲等级高 → 升至牺牲等级；
#   相同 → +1（均不超上限）；低 → 目标等级不变
# - 合法性：相同物品类型两两可合（书+书视为同类型）；任意非书物品可与附魔书合并；
#   不同类型非书物品无法合并（本工具以此报"无法合成一件"）
# - 生存模式单次操作 ≤39 级，否则铁砧显示"过于昂贵！"（本优化器在方案中标记此类步骤）
#
# 本模块为纯逻辑（不依赖 Qt），便于单元测试。
import heapq
import itertools
from dataclasses import dataclass, field

BOOK_ITEM = "附魔书"

_ROMAN = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]


def _roman(lv: int) -> str:
    """附魔等级转罗马数字（超界回退阿拉伯数字）"""
    return _ROMAN[lv] if 0 < lv <= 10 else str(lv)


class AnvilError(Exception):
    """优化无法完成时抛出（原因见 message）"""


@dataclass(frozen=True)
class AnvilItem:
    """铁砧世界中的一件物品（不可变，作为搜索状态使用）

    name:     物品类型名（UI 下拉框文本，附魔书用 "附魔书"）
    enchants: 魔咒集合 {("附魔ID", 等级), ...}（frozenset 保证可哈希）
    pwp:      累积惩罚（Prior Work Penalty）
    label:    展示标签（叶子=卡片描述，合并结果=合成物描述）
    """
    name: str
    enchants: frozenset
    pwp: int
    label: str = ""

    @classmethod
    def make(cls, name: str, enchant_pairs, pwp: int = 0, label: str = ""):
        return cls(name, frozenset(enchant_pairs), pwp, label)

    def enchant_map(self) -> dict:
        return {eid: lv for eid, lv in self.enchants}

    def has_enchant(self, eid) -> bool:
        return any(e == eid for e, _ in self.enchants)

    def is_book(self) -> bool:
        return self.name == BOOK_ITEM


@dataclass
class MergeStep:
    """一次铁砧操作（目标在左/第一格，牺牲在右/第二格）"""
    target: AnvilItem
    sacrifice: AnvilItem
    result: AnvilItem
    cost: int
    detail: dict = field(default_factory=dict)  # 计费明细（魔咒逐条 + PWP）


@dataclass
class AnvilPlan:
    """完整合并方案"""
    steps: list          # [MergeStep, ...]（按执行顺序）
    total_cost: int      # 总花费（各步之和）
    final_item: AnvilItem
    too_expensive_steps: list = field(default_factory=list)  # 花费 ≥40 的步骤序号


class AnvilMechanics:
    """Java 版铁砧机制模拟（纯函数式，不依赖 Qt，便于测试）"""

    def __init__(self, data_manager):
        """data_manager: DataManager 单例（提供乘数表 / 冲突 / 适用性查询）"""
        self.dm = data_manager

    # ---------- 查询辅助 ----------
    def _enchant(self, eid):
        return self.dm.get_enchant_by_id(eid)

    def _name_of(self, eid) -> str:
        ench = self._enchant(eid)
        return ench["name"] if ench else str(eid)

    def _applicable_to(self, eid, item_name) -> bool:
        """魔咒是否适用于某物品类型（数据中所有附魔的 applicable 均含"附魔书"，
        因此书与书互并时魔咒正常转移）"""
        ench = self._enchant(eid)
        if not ench:
            return False
        return item_name in ench.get("applicable", [])

    def _cost(self, eid, final_level, from_book: bool) -> int:
        """按输出最终等级查乘数表计费（items/book 两表已验证为线性表）"""
        c = self.dm.get_level_cost(eid, final_level, from_book)
        return c if c is not None else 0

    # ---------- 合并合法性 ----------
    def can_merge(self, a: AnvilItem, b: AnvilItem) -> bool:
        """两件物品能否放进同一铁砧（顺序无关）：
        同类型物品（含 书+书），或一方为附魔书而另一方为任意非书物品"""
        if a.name == b.name:
            return True
        return a.is_book() or b.is_book()
    # ---------- 核心：一次合并模拟 ----------
    def merge(self, target: AnvilItem, sacrifice: AnvilItem) -> tuple:
        """把 sacrifice 合并进 target（target 在铁砧第一格/左侧）

        返回 (result: AnvilItem, cost: int, detail: dict)
        detail: {"pwp_cost": 双方惩罚和,
                 "enchant_costs": [(id, 输出等级, 费用, 原因), ...],
                 "ignored": [(id, 原因), ...]}
        假设满耐久（无维修费）、不重命名。
        """
        assert self.can_merge(target, sacrifice), "内部错误：非法合并对"

        t_map = target.enchant_map()
        s_map = sacrifice.enchant_map()
        out = dict(t_map)  # 输出魔咒 = 目标魔咒 + 转移结果（实时更新，冲突检查基于它）

        # 输出物品类型 = 目标（左格）物品类型（Java 版输出是目标物品的副本：
        # 剑+书→剑；书+书→书；书+剑→书——物品附魔可"降级"到书上）
        out_name = target.name

        sacrifice_is_book = sacrifice.is_book()  # 决定乘数表

        cost = target.pwp + sacrifice.pwp
        detail = {"pwp_cost": cost, "enchant_costs": [], "ignored": []}

        for eid, s_lv in sorted(s_map.items()):
            ench = self._enchant(eid)
            if not ench:
                continue
            # 1. 不适用于输出物品类型 → 直接忽略，不计费
            if not self._applicable_to(eid, out_name):
                detail["ignored"].append(
                    (eid, "不适用于该物品类型，忽略不计费"))
                continue
            # 2. 输出物品已有互斥魔咒（含目标原有或本次已转移的）→ 不转移，
            #    每有一个互斥魔咒 +1 级
            conflicts_here = [c for c in (ench.get("conflicts") or [])
                              if c in out]
            if conflicts_here:
                c_names = "、".join(self._name_of(c) for c in conflicts_here)
                cost += len(conflicts_here)
                detail["enchant_costs"].append(
                    (eid, 0, len(conflicts_here),
                     f"与{c_names}互斥，未转移（+{len(conflicts_here)}级）"))
                continue
            # 3. 等级合并 + 按输出最终等级计费（等级不上升也计费）
            t_lv = t_map.get(eid, 0)
            max_lv = ench.get("max_level", 5)
            if eid not in t_map:
                final_lv = min(s_lv, max_lv)
                reason = f"获得{_roman(final_lv)}"
            elif s_lv > t_lv:
                final_lv = min(s_lv, max_lv)
                reason = f"升级至{_roman(final_lv)}"
            elif s_lv == t_lv:
                final_lv = min(s_lv + 1, max_lv)
                reason = f"同级合并升级至{_roman(final_lv)}"
            else:
                final_lv = t_lv
                reason = f"目标等级已更高，按输出{_roman(final_lv)}计费"
            fee = self._cost(eid, final_lv, sacrifice_is_book)
            cost += fee
            out[eid] = final_lv
            detail["enchant_costs"].append((eid, final_lv, fee, reason))

        # 结果 PWP：基于双方中较高者再算下一层（max 操作数 +1 → 2^(max+1)-1）
        # 反解操作次数：pwp = 2^n - 1 的二进制恰为 n 个 1，故 n = pwp 的位长
        n_ops = max(target.pwp.bit_length() if target.pwp else 0,
                    sacrifice.pwp.bit_length() if sacrifice.pwp else 0)
        out_pwp = (2 ** (n_ops + 1)) - 1

        if out:
            desc = "、".join(f"{self._name_of(e)}{_roman(lv)}"
                             for e, lv in sorted(out.items()))
            label = f"{out_name}（{desc}）"
        else:
            label = out_name
        result = AnvilItem(out_name, frozenset(out.items()), out_pwp, label)
        return result, cost, detail


class AnvilOptimizer:
    """最优合并树搜索：多件物品 → 一件，总花费最少

    算法：状态 = 剩余物品多重集合，Dijkstra 按（总花费, 步骤数, 序号）取出
    最优状态，枚举所有有序对 (target=左, sacrifice=右) 合并，直到剩余一件。
    终态约束：最终物品须包含用户保留的全部冲突附魔（required_enchants），
    且类型符合要求（含非书物品时最终必须为该非书类型）。
    n ≤ max_items_for_exact 用精确搜索，超出降级贪心（拦截保留附魔的对加大惩罚）。
    """

    def __init__(self, data_manager, max_items_for_exact: int = 8):
        self.mech = AnvilMechanics(data_manager)
        self.max_items_for_exact = max_items_for_exact

    # ---------- 入口 ----------
    def optimize(self, items: list, required_enchants=frozenset()) -> AnvilPlan:
        """items: [AnvilItem, ...]；required_enchants: 最终物品必须包含的附魔 ID 集

        返回最优 AnvilPlan；无法合并成一件 / 约束无法满足时抛出 AnvilError。
        """
        if not items:
            raise AnvilError("没有物品可计算")
        if len(items) == 1:
            it = items[0]
            missing = [e for e in required_enchants if not it.has_enchant(e)]
            if missing:
                names = "、".join(self.mech._name_of(e) for e in sorted(missing))
                raise AnvilError(f"无法满足要求：最终物品缺少 {names}")
            return AnvilPlan(steps=[], total_cost=0, final_item=it)

        # 合法性预检：非书物品必须类型一致（书可与任意非书合并）
        non_books = [it for it in items if not it.is_book()]
        non_book_names = {it.name for it in non_books}
        if len(non_book_names) > 1:
            names = "、".join(sorted(non_book_names))
            raise AnvilError(
                f"无法合成一件：同时存在多种非附魔书物品（{names}），"
                f"铁砧不能合并不同类型的物品")
        # 终态类型约束：有非书物品 → 最终必须是该类型；全为书 → 附魔书
        required_type = non_books[0].name if non_books else BOOK_ITEM

        if len(items) <= self.max_items_for_exact:
            return self._search_exact(items, required_enchants, required_type)
        return self._search_greedy(items, required_enchants, required_type)

    # ---------- 终态判定 ----------
    def _is_goal(self, item: AnvilItem, required_enchants, required_type) -> bool:
        if required_type and item.name != required_type:
            return False
        return all(item.has_enchant(e) for e in required_enchants)

    # ---------- 精确搜索（Dijkstra over 物品多重集合状态） ----------
    def _search_exact(self, items, required_enchants, required_type) -> AnvilPlan:
        counter = itertools.count()  # 堆序决胜键：保证元组比较止步于整数，永不触及列表
        start = list(items)
        start_key = tuple(sorted(start, key=repr))
        heap = [(0, 0, next(counter), start_key, [], start)]
        best = {start_key: 0}
        goal_steps = None
        goal_item = None

        while heap:
            cost, n_steps, _, key, steps, cur = heapq.heappop(heap)
            if cost > best.get(key, float("inf")):
                continue  # 已有更优路径到达此状态
            if len(cur) == 1:
                if self._is_goal(cur[0], required_enchants, required_type):
                    goal_steps, goal_item = steps, cur[0]
                    break
                continue  # 单物品但不含所需附魔/类型：死状态，不再扩展
            for i in range(len(cur)):
                for j in range(len(cur)):
                    if i == j:
                        continue
                    target, sacrifice = cur[i], cur[j]
                    if not self.mech.can_merge(target, sacrifice):
                        continue
                    result, fee, detail = self.mech.merge(target, sacrifice)
                    # 可行性剪枝：若目标已有某保留附魔且本次牺牲会把它挤掉的
                    # 组合在终态必然不满足（保留附魔被拦截后无法找回）——
                    # 保守起见不剪，交由终态判定处理（状态数有限，正确性优先）
                    nxt = [cur[k] for k in range(len(cur)) if k not in (i, j)]
                    nxt.append(result)
                    nxt_key = tuple(sorted(nxt, key=repr))
                    new_cost = cost + fee
                    if new_cost < best.get(nxt_key, float("inf")):
                        best[nxt_key] = new_cost
                        step = MergeStep(target, sacrifice, result, fee, detail)
                        heapq.heappush(heap, (new_cost, n_steps + 1,
                                              next(counter), nxt_key,
                                              steps + [step], nxt))

        if goal_steps is None:
            kept = "、".join(self.mech._name_of(e)
                            for e in sorted(required_enchants))
            hint = f"（需保留 {kept}）" if kept else ""
            raise AnvilError(
                f"无法合成一件{hint}：在保证保留所选附魔的前提下，给定的物品"
                "无法通过铁砧合并成一件（物品自带的互斥附魔无法移除，"
                "会把所选附魔拦在铁砧外）")

        too_exp = [i + 1 for i, s in enumerate(goal_steps) if s.cost >= 40]
        return AnvilPlan(steps=goal_steps,
                         total_cost=sum(s.cost for s in goal_steps),
                         final_item=goal_item, too_expensive_steps=too_exp)

    # ---------- 贪心降级（物品过多时） ----------
    def _search_greedy(self, items, required_enchants, required_type) -> AnvilPlan:
        """每轮选合并对：优先不拦截保留附魔，其次本次花费最小，直到剩一件"""
        cur = list(items)
        steps = []
        while len(cur) > 1:
            best_pair = None
            for i in range(len(cur)):
                for j in range(len(cur)):
                    if i == j:
                        continue
                    if not self.mech.can_merge(cur[i], cur[j]):
                        continue
                    result, fee, detail = self.mech.merge(cur[i], cur[j])
                    # 拦截了保留附魔的组合加重惩罚（虚拟代价，不改变实际花费）
                    blocked_kept = any(
                        ec[0] in required_enchants and "互斥" in ec[3]
                        for ec in detail["enchant_costs"])
                    rank = (0 if not blocked_kept else 1, fee)
                    if best_pair is None or rank < best_pair[0]:
                        best_pair = (rank, i, j, result, fee, detail)
            if best_pair is None:
                raise AnvilError("无法合成一件：给定的物品无法通过铁砧合并")
            _, i, j, result, fee, detail = best_pair
            steps.append(MergeStep(cur[i], cur[j], result, fee, detail))
            cur = [cur[k] for k in range(len(cur)) if k not in (i, j)] + [result]
        too_exp = [n + 1 for n, s in enumerate(steps) if s.cost >= 40]
        return AnvilPlan(steps=steps, total_cost=sum(s.cost for s in steps),
                         final_item=cur[0], too_expensive_steps=too_exp)


# ---------- 面向 UI 的入口：卡片数据 → AnvilItem ----------
def build_items_from_cards(cards_data: list) -> list:
    """把卡片数据包列表转成 AnvilItem 列表

    cards_data: [{"item_name": str, "enchants": [{"id","name","level"},...]}, ...]
    展示标签：如 "剑（锋利V、抢夺III）" 或无附魔时 "剑"。
    """
    items = []
    for card in cards_data:
        name = card.get("item_name", "")
        pairs = [(e["id"], int(e.get("level", 1)))
                 for e in card.get("enchants", [])]
        if pairs:
            desc = "、".join(f"{e.get('name', e['id'])}{_roman(int(e.get('level', 1)))}"
                             for e in card.get("enchants", []))
            label = f"{name}（{desc}）"
        else:
            label = name
        items.append(AnvilItem.make(name, pairs, 0, label))
    return items
