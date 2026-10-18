# -*- coding: utf-8 -*-
"""CommandGenerator：指令的**声明式参数规格**。

一条指令 = 一个 spec dict，由 `cmd_form.py` 的通用渲染器渲染成
控件并收集参数字典 —— 新增指令只写规格，不写 UI 代码。

spec 结构：
    {
      "title":   "显示名",
      "fields":  [field, ...],            # 无分支时用
      # 或（有分支时）：
      "branch_key": "branch",             # 参数字典里放分支名的键
      "branch_field": "branch",           # UI 上分支选择器的标题
      "branches": {"give": {"fields": [...]}, ...},
    }

field 结构：
    {
      "key":     "targets",               # 参数字典的键
      "label":   "目标",                  # UI 标签
      "kind":    "targets",               # 控件类型（见下）
      "source":  "effect",                # resource 类的数据源名
      "choices": ["a", "b"],              # enum 类的候选项
      "labels":  {"a": "A"},              # enum 类的显示名（可选）
      "default": ...,                     # 初值
      "optional": True,                   # 可留空（serializer 里体现）
      "hint":    "说明文字",              # 附加提示
      "minimum"/"maximum": 0, 100,        # int/float 范围
    }

kind 取值：
    targets   目标选择器（可编辑下拉，带常用预设）
    resource  资源 id（可搜索下拉，数据源由 source 指定）
    enum      固定枚举（下拉）
    int       整数
    float     浮点数
    bool      布尔
    text      单行文本
    pos       坐标（单行文本 + 常用占位）
    block     方块（id[state] 单行文本）
    nbt       NBT 复合（单行文本）
"""

# 常用目标选择器预设
TARGET_PRESETS = ["@p", "@a", "@e", "@r", "@s", "@e[type=zombie]",
                  "@a[distance=..10]", "@p[level=1..]"]

# 坐标占位预设
POS_PRESETS = ["~ ~ ~", "~ ~ ~1", "~-1 ~ ~", "^ ^ ^", "0 64 0"]

# 常用方块
COMMON_BLOCKS = ["stone", "air", "glass", "oak_planks", "cobblestone",
                 "dirt", "sand", "gravel", "oak_log", "water",
                 "oak_stairs[facing=north]", "oak_slab[type=top]"]


# ---------------------------------------------------------------------------
# 合并剩余 26 条（cmd_specs3.py）
#
# **_merge_extra() 必须在 SPECS 定义之后调用** —— 早先放在 _f 之前，
# SPECS 还不存在，合并静默丢失（表现为 26 条新指令全部落到「未实现」页）。
# 函数定义见本文件末尾。
# ---------------------------------------------------------------------------


def _f(key, label, kind, **kw):
    d = {"key": key, "label": label, "kind": kind}
    d.update(kw)
    return d


# ---------------------------------------------------------------------------
# 规格表
# ---------------------------------------------------------------------------

SPECS = {
    # ------------------------------------------------------------------ item
    "item": {
        "title": "item — 修改容器/实体持有物品",
        "branch_key": "branch",
        "branch_field": "分支",
        "branches": {
            "replace": {
                "label": "replace（替换）",
                "fields": [
                    _f("kind", "目标类型", "enum",
                       choices=["block", "entity"], default="block"),
                    _f("pos", "坐标", "pos", optional=True,
                       default="~ ~ ~", show_when=("kind", ["block"])),
                    _f("targets", "实体", "targets",
                       optional=True, default="@s",
                       show_when=("kind", ["entity"])),
                    _f("slot", "槽位", "int", minimum=0, maximum=105,
                       default=0,
                       hint="container.0 起的编号；0-53 常用"),
                    _f("sub", "子分支", "enum",
                       choices=["with", "from"], default="with"),
                    _f("item", "新物品", "block",
                       optional=True, default="stone",
                       presets=COMMON_BLOCKS,
                       show_when=("sub", ["with"])),
                    _f("count", "数量", "int", optional=True,
                       minimum=1, maximum=99, default=None,
                       show_when=("sub", ["with"])),
                    _f("source_kind", "来源类型", "enum",
                       choices=["block", "entity"], optional=True,
                       default="block", show_when=("sub", ["from"])),
                    _f("source_pos", "来源坐标", "pos", optional=True,
                       default="~ ~ ~",
                       show_when=("sub", ["from", None])),
                    _f("source_targets", "来源实体", "targets",
                       optional=True, default="@s",
                       show_when=("sub", ["from"])),
                    _f("source_slot", "来源槽位", "int",
                       optional=True, minimum=0, maximum=105, default=0,
                       show_when=("sub", ["from"])),
                    _f("modifier", "战利品修饰符", "text",
                       optional=True, default="",
                       hint="数据包 modifier id，留空不填"),
                ],
            },
            "modify": {
                "label": "modify（应用修饰符）",
                "fields": [
                    _f("kind", "目标类型", "enum",
                       choices=["block", "entity"], default="block"),
                    _f("pos", "坐标", "pos", optional=True,
                       default="~ ~ ~", show_when=("kind", ["block"])),
                    _f("targets", "实体", "targets",
                       optional=True, default="@s",
                       show_when=("kind", ["entity"])),
                    _f("slot", "槽位", "int", minimum=0, maximum=105,
                       default=0),
                    _f("modifier", "战利品修饰符 id", "text",
                       default=""),
                ],
            },
        },
    },

    # ------------------------------------------------------------------ loot
    "loot": {
        "title": "loot — 掉落战利品",
        "branch_key": "source",
        "branch_field": "来源",
        "branches": {
            "loot": {
                "label": "loot（直接指定战利品表）",
                "fields": [
                    _f("loot_table", "战利品表", "loot_table_res",
                       default="chests/simple_dungeon",
                       hint="119 个官方表（chests/ entities/ gameplay/）"),
                ],
            },
            "fish": {
                "label": "fish（钓鱼）",
                "fields": [
                    _f("loot_table", "战利品表", "loot_table_res",
                       default="gameplay/fishing"),
                    _f("source_pos", "位置", "pos", default="~ ~ ~"),
                    _f("tool", "工具", "block", optional=True,
                       default="", presets=COMMON_BLOCKS),
                ],
            },
            "mine": {
                "label": "mine（挖掘）",
                "fields": [
                    _f("source_pos", "位置", "pos", default="~ ~ ~"),
                    _f("tool", "工具", "enum", optional=True,
                       choices=["mainhand"], default=None,
                       hint="mainhand = 主手物品；也可填物品 id"),
                ],
            },
            "kill": {
                "label": "kill（击杀掉落）",
                "fields": [
                    _f("source_entity", "被杀实体", "targets",
                       default="@e[type=zombie,limit=1]"),
                ],
            },
        },
        # 目标段是所有来源共享的尾参（用公共字段表达）
        "_target_fields": [
            _f("target", "目标动作", "enum",
               choices=["give", "spawn", "insert", "replace"],
               default="give"),
            _f("players", "玩家", "targets", optional=True,
               default="@p", show_when=("target", ["give"])),
            _f("target_pos", "坐标", "pos", optional=True,
               default="~ ~ ~",
               show_when=("target", ["spawn", "insert", "replace"])),
            _f("target_kind", "替换目标类型", "enum",
               choices=["entity", "block"], optional=True,
               default="entity", show_when=("target", ["replace"])),
            _f("target_targets", "实体", "targets",
               optional=True, default="@s",
               show_when=("target_kind", ["entity"])),
            _f("target_slot", "槽位", "int", optional=True,
               minimum=0, maximum=105, default=0,
               show_when=("target", ["replace"])),
            _f("target_count", "数量", "int",
               optional=True, minimum=1, maximum=99, default=None,
               show_when=("target", ["replace"])),
        ],
    },

    # ------------------------------------------------------------- attribute
    "attribute": {
        "title": "attribute — 实体属性",
        "fields": [
            _f("targets", "目标", "targets", default="@s"),
            _f("attribute", "属性 id", "resource", source="attribute",
               default="armor",
               hint="35 项；id 无 generic. 前缀（前缀由实体类型决定）"),
            _f("branch", "分支", "enum",
               choices=["get", "base", "modifier", "reset"],
               default="get"),
            _f("scale", "显示倍率", "float", optional=True,
               minimum=-1e9, maximum=1e9, default=None,
               hint="留空 = 1.0", show_when=("branch", ["get"])),
            _f("base_sub", "base 子分支", "enum",
               choices=["get", "set"], optional=True, default="get",
               show_when=("branch", ["base"])),
            _f("value", "数值", "float",
               optional=True, minimum=-1e9, maximum=1e9, default=None,
               show_when=("base_sub", ["set"])),
            _f("modifier_sub", "modifier 子分支", "enum",
               choices=["add", "remove", "value"], optional=True,
               default="add", show_when=("branch", ["modifier"])),
            _f("id", "修饰符 id", "text", optional=True,
               default="", show_when=("branch", ["modifier"])),
            _f("operation", "运算", "enum",
               choices=["add_value", "add_multiplied_base",
                        "add_multiplied_total"], optional=True,
               default="add_value",
               show_when=("modifier_sub", ["add"])),
        ],
    },

    # ---------------------------------------------------------------- damage
    "damage": {
        "title": "damage — 对实体造成伤害",
        "fields": [
            _f("target", "目标", "targets", default="@s",
               hint="单数实体（源码 EntityArgument.entity()）"),
            _f("amount", "伤害值", "float", minimum=0.0, maximum=3.4e38,
               default=1.0),
            _f("damage_type", "伤害类型", "resource",
               source="damage_type", default="lava",
               hint="50 项，显示致死语中文名"),
            _f("tag", "附加修饰", "enum",
               choices=["", "at", "by"], optional=True, default=None,
               hint="at = 在某位置；by = 由某实体造成"),
            _f("location", "位置", "pos", optional=True,
               default="~ ~ ~", show_when=("tag", ["at"])),
            _f("by", "来源实体", "targets", optional=True,
               default="@e[type=zombie,limit=1]", show_when=("tag", ["by"])),
            _f("cause", "归因实体", "targets",
               optional=True, default="", show_when=("tag", ["by"])),
        ],
    },

    # ------------------------------------------------------------- playsound
    "playsound": {
        "title": "playsound — 播放音效",
        "fields": [
            _f("sound", "音效", "resource", source="sound",
               default="entity.player.levelup",
               hint="1637 个官方音效，可搜索"),
            _f("targets", "目标", "targets", default="@p"),
            _f("pos", "位置", "pos", optional=True, default="~ ~ ~"),
            _f("volume", "音量", "float", optional=True, minimum=0.0,
               maximum=100.0, default=None, hint="留空 = 1.0"),
            _f("pitch", "音调", "float", optional=True, minimum=0.0,
               maximum=100.0, default=None, hint="留空 = 1.0"),
            _f("min_volume", "最小音量", "float", optional=True,
               minimum=0.0, maximum=100.0, default=None,
               hint="留空 = 1.0"),
        ],
    },

    # -------------------------------------------------------------- particle
    "particle": {
        "title": "particle — 生成粒子",
        "fields": [
            _f("name", "粒子", "resource", source="particle",
               default="heart",
               hint="115 项；部分粒子需额外参数（dust 等）"),
            _f("pos", "位置", "pos", optional=True, default="~ ~ ~"),
            _f("delta", "扩散", "pos", optional=True,
               default="0 0 0",
               hint="三维向量；count=0 时表示运动方向"),
            _f("speed", "速度", "float", optional=True, minimum=0.0,
               maximum=100.0, default=None),
            _f("count", "数量", "int", optional=True, minimum=0,
               maximum=10000, default=None),
            _f("mode", "显示模式", "enum",
               choices=["normal", "force"], optional=True,
               default=None, hint="force = 超出常规可视距离也显示"),
            _f("viewers", "观看者", "targets", optional=True,
               default=""),
        ],
    },

    # ----------------------------------------------------- spawn_armor_trims
    "spawn_armor_trims": {
        "title": "spawn_armor_trims — 生成盔甲纹饰展示实体",
        "fields": [
            _f("pattern", "纹饰图案", "resource",
               source="trim_pattern", default="sentry"),
        ],
    },

    # ---------------------------------------------------------------- kill
    "kill": {
        "title": "kill — 杀死实体",
        "fields": [
            _f("targets", "目标", "targets", optional=True,
               default="",
               hint="留空 = 作用于命令执行者自身（源码 L18）"),
        ],
    },

    # ------------------------------------------------------------- enchant
    "enchant": {
        "title": "enchant — 给手持物品附魔",
        "fields": [
            _f("targets", "目标", "targets", default="@s"),
            _f("enchantment", "附魔", "resource", source="enchant",
               default="sharpness"),
            _f("level", "等级", "int", optional=True, minimum=0,
               maximum=255, default=None,
               hint="留空 = 官方默认 1；允许 0（源码 integer(0)）"),
        ],
    },

    # -------------------------------------------------------------- effect
    "effect": {
        "title": "effect — 状态效果",
        "branch_key": "branch",
        "branch_field": "分支",
        "branches": {
            "give": {
                "label": "give（施加有限时长）",
                "fields": [
                    _f("targets", "目标", "targets", default="@s"),
                    _f("effect", "状态效果", "resource",
                       source="effect", default="speed"),
                    _f("seconds", "时长(秒)", "int", optional=True,
                       minimum=1, maximum=1000000, default=None,
                       hint="1~1000000；留空则默认按无限处理"),
                    _f("amplifier", "等级(amplifier)", "int",
                       optional=True, minimum=0, maximum=255,
                       default=None,
                       hint="0 = I 级，1 = II 级；留空 = 0"),
                    _f("hide_particles", "隐藏粒子", "bool",
                       optional=True, default=None),
                ],
            },
            "infinite": {
                "label": "infinite（无限时长）",
                "fields": [
                    _f("targets", "目标", "targets", default="@s"),
                    _f("effect", "状态效果", "resource",
                       source="effect", default="speed"),
                    _f("amplifier", "等级(amplifier)", "int",
                       optional=True, minimum=0, maximum=255,
                       default=None),
                    _f("hide_particles", "隐藏粒子", "bool",
                       optional=True, default=None),
                ],
            },
            "clear": {
                "label": "clear（清除效果）",
                "fields": [
                    _f("targets", "目标", "targets", optional=True,
                       default="",
                       hint="留空 = 清除自身全部效果"),
                    _f("effect", "仅清除该效果", "resource",
                       source="effect", optional=True, default=None,
                       hint="需先填目标；留空 = 清除全部"),
                ],
            },
        },
    },

    # ------------------------------------------------------------ setblock
    "setblock": {
        "title": "setblock — 放置单个方块",
        "fields": [
            _f("pos", "坐标", "pos", default="~ ~ ~",
               presets=POS_PRESETS),
            _f("block", "方块", "block", default="stone",
               presets=COMMON_BLOCKS),
            _f("mode", "模式", "enum",
               choices=["replace", "destroy", "keep"],
               default="replace",
               hint="replace 为默认，省略不写"),
        ],
    },

    # ---------------------------------------------------------------- fill
    "fill": {
        "title": "fill — 填充区域",
        "fields": [
            _f("from", "起点", "pos", default="~ ~ ~",
               presets=POS_PRESETS),
            _f("to", "终点", "pos", default="~5 ~5 ~5",
               presets=POS_PRESETS),
            _f("block", "方块", "block", default="stone",
               presets=COMMON_BLOCKS),
            _f("mode", "模式", "enum",
               choices=["replace", "keep", "outline", "hollow",
                        "destroy", "strict"],
               default="replace"),
            _f("filter", "替换过滤（仅 replace）", "block",
               optional=True, default="",
               presets=["minecraft:air"],
               hint="留空 = 全部替换；从下拉选要被替换掉的方块"),
        ],
    },

    # -------------------------------------------------------------- summon
    "summon": {
        "title": "summon — 生成实体",
        "fields": [
            _f("entity", "实体", "resource", source="entity",
               default="pig"),
            _f("pos", "坐标", "pos", optional=True, default="",
               presets=POS_PRESETS,
               hint="留空 = 命令执行位置"),
            _f("nbt", "NBT", "nbt", optional=True, default="",
               hint="留空 = 无额外数据；弹窗里可视化构造"),
        ],
    },

    # -------------------------------------------------------------- locate
    "locate": {
        "title": "locate — 定位结构/群系",
        "branch_key": "branch",
        "branch_field": "定位类型",
        "branches": {
            "structure": {
                "label": "structure（结构）",
                "fields": [
                    _f("target", "结构", "resource",
                       source="structure", default="village_plains"),
                ],
            },
            "biome": {
                "label": "biome（群系）",
                "fields": [
                    _f("target", "群系", "resource",
                       source="biome", default="plains"),
                ],
            },
            "poi": {
                "label": "poi（兴趣点）",
                "fields": [
                    _f("target", "兴趣点", "resource",
                       source="poi", default="armorer"),
                ],
            },
        },
    },
}


def _merge_extra():
    """把 cmd_specs3.SPECS3 并入 SPECS（gamerule 特殊处理）。

    **必须在 SPECS 定义之后调用**（早先误放在 _f 之前，SPECS 还不
    存在，合并静默丢失 —— 表现为 26 条新指令全部落到「未实现」页）。
    """
    from Utils.CommandGenerator import cmd_specs3 as S3
    from Utils.CommandGenerator import resource_lists as _RL
    for cmd, spec in S3.SPECS3.items():
        if cmd == "gamerule":
            # 动态枚举：59 条规则，选中后值类型随规则变化
            rule_field = spec["fields"][0]
            rule_field["choices"] = [r[0] for r in _RL.GAMERULES]
            rule_field["labels"] = {r[0]: r[2] for r in _RL.GAMERULES}
            rule_field["kinds"] = {r[0]: r[1] for r in _RL.GAMERULES}
        SPECS[cmd] = spec

    # advancement 的 _mode_fields 追加到 grant/revoke 两分支
    adv = SPECS.get("advancement")
    if adv and "_mode_fields" in adv:
        extra = adv.pop("_mode_fields")
        for br in ("grant", "revoke"):
            adv["branches"][br]["fields"] = (
                list(adv["branches"][br].get("fields", [])) + extra)


_merge_extra()


# ---------------------------------------------------------------------------
# 兴趣点（POI）id
#
# 来源：PoiTypes.java 的 `ResourceKey<PoiType> X = createKey("id")`
# 声明处（声明 21 处，其中 `test_instance` 是测试专用，不作为
# 可定位兴趣点，故实收 **20** 个）。
#
# 注意：**POI id 不等于方块名**。例如 POI `butcher` 对应的方块是
# smoker、`fisherman` 对应 barrel、`home` 对应床。早先凭直觉按
# 「方块名 = POI 名」列出的清单是错的（会产出游戏不认的 id）。
# ---------------------------------------------------------------------------
POI_IDS = [
    "armorer", "bee_nest", "beehive", "butcher", "cartographer",
    "cleric", "farmer", "fisherman", "fletcher", "home",
    "leatherworker", "librarian", "lightning_rod", "lodestone", "mason",
    "meeting", "nether_portal", "shepherd", "toolsmith", "weaponsmith",
]

# POI id -> 对应方块/说明（便于 UI 提示，来源同 PoiTypes 的 register 行）
POI_NOTE = {
    "armorer": "高炉", "butcher": "烟熏炉", "cartographer": "制图台",
    "cleric": "酿造台", "farmer": "堆肥桶", "fisherman": "木桶",
    "fletcher": "制箭台", "leatherworker": "炼药锅",
    "librarian": "讲台", "mason": "切石机", "shepherd": "织布机",
    "toolsmith": "锻造台", "weaponsmith": "砂轮", "home": "床",
    "meeting": "钟", "beehive": "蜂箱", "bee_nest": "蜂巢",
    "nether_portal": "下界传送门", "lodestone": "磁石",
    "lightning_rod": "避雷针",
}
