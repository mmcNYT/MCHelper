# -*- coding: utf-8 -*-
"""MCHelper「关于/使用说明」窗口：分工具的使用方法手册，左侧导航 + 右侧内容。"""
from PySide6.QtWidgets import QDialog

# 导航项：(标签, markdown 内容)
ABOUT_SECTIONS = [
    ("总览", """# MCHelper — Minecraft 玩家工具合集

Minecraft Java 版玩家工具合集（PySide6 桌面应用）。单窗口、Tab 切换多工具，围绕**种子逆推、结构预览、地图预览、附魔计算**等玩法场景提供本地化支持。

- **机制对齐**：结构生成 / RNG 逻辑以 Wiki 与反编译源码为基准复刻，并与真实游戏数据核对；
- **精确逐种子**：结构拼装、战利品按输入种子逐次复现游戏随机流，而非统计估算；
- **全本地运行**：数据不出本机，无需联网；
- **版本覆盖**：1.18 ~ 1.21+（已适配 Minecraft 26.2）。

## 标签页
窗口上方为各工具标签，点击切换；菜单栏提供「设置」与「使用说明」。从左侧列表选择工具查看详细使用方法。
"""),

    ("附魔计算器", """# 附魔计算器

## 用途
选择物品与附魔，自动规划**费用最优的铁砧合成顺序**，以合成步骤树展示每一步的合并方式与累计费用。

## 使用方法
1. 打开「附魔计算器」标签；
2. 添加要合成的物品，并为其选择附魔书与等级；
3. 程序自动生成最优合成方案；
4. 在「树 / 步骤」双模式中查看每一步的合并方向与累计费用；
5. 查看最小费用卡片与合并顺序。

## 说明
- 核心算法：铁砧合成顺序优化（Dijkstra 精确搜索为主、贪心降级兜底）；
- 冲突附魔自动决策归属（非附魔书共有附魔自动分配）；
- 物品卡片带图标与流光，列表可拖拽增删、左键加级 / 右键减级。
"""),

    ("地图预览器", """# 地图预览器

## 用途
输入种子即可渲染主世界 / 下界 / 末地的群系地图，支持版本与维度切换、结构标注、群系定位锚点收藏、图例与悬浮信息。

## 使用方法
1. 打开「地图预览器」标签；
2. 输入世界种子；
3. 选择版本与维度（主世界 / 下界 / 末地）；
4. 选择要标注的结构类型；
5. 渲染地图：缩放浏览、悬停查看群系名，可收藏群系定位锚点。

## 说明
- 群系采样：原生加速扩展优先，缺则纯 Python 回退；
- 方块级配色（树冠结构色、水体三档深度色、恶地形色带与光照）。
"""),

    ("要塞定位", """# 要塞定位

## 用途
监听剪贴板中的 F3+C 调试数据，解析两次投掷末影之眼的射线，计算交汇点并给出要塞坐标与 `/tp` 命令。

## 使用方法
1. 打开「要塞定位」标签；
2. 在游戏内按 F3+C 复制调试数据（程序自动监听剪贴板）；
3. 分别记录两次投掷的坐标与偏航角；
4. 程序自动计算两射线交汇点；
5. 给出要塞坐标与 `/tp` 命令；定位完成弹窗通知。

## 说明
- 输入带防抖与合法性预判；
- 剪贴板用 Win32 序号监听（一次系统调用，不打开剪贴板），序号变化即更新；
- 与种子逆推共用 F3+C 解析逻辑。
"""),

    ("种子逆推", """# 种子逆推

## 用途
从观察到的结构生成位置逆推 48 位结构种子，再经高位精细化还原世界种子；支持多观察值、信息熵提示、容差设置与候选验证，内置结构 2D / 3D 视图。

## 使用方法
1. 在游戏中找 3~6 个不同结构的坐标（推荐沉船——海滩常见、易辨认）；
2. 站在结构旁按 F3 读出 X/Z 坐标（或 F3+C 复制后点「粘贴 F3+C」）；
3. 点「添加」录入；列表逐行可设「容差」（大型 / 深埋结构用大容差，但会降低信息量）；
4. 看「信息量」进度条，达标后点「计算」；
5. 计算完成自动批量验证全部候选，并显示汇总与首个候选的逐条比对明细；
6. 在结果区双击候选种子即可复制（hex + 十进制双格式）；
7. 也可点「验证候选种子」对任意 48 位种子做正向全量比对。

## 群系模式（世界种子精化）
1. 勾选「群系模式」展开下方精化面板；
2. 录入 ≥7 个群系观测点（F3 群系名 + 站位坐标，可选 Y）；
3. 从候选结构种枚举高 16 位，还原完整 64 位世界种子（原生引擎秒级）。

## 快捷键
| 键 | 作用 |
|---|---|
| Enter | 添加观测 |
| Ctrl+Enter | 计算 / 取消 |
| Esc | 取消计算验证或清空输入 |
| Delete | 删除选中观测（列表获得焦点时） |

## 提示
- 结构类型下拉分「可逆推 / 仅验证」两组：可逆推（mod≥2 线性结构）参与预筛，其余只作验证；
- 容差会大幅降低信息量，以小型结构（mod 8）为主更易达标。
"""),

    ("结构预览器", """# 结构预览器

## 用途
输入种子与坐标，**逐种子精确复现结构拼装**，3D 视图内自由飞行、开箱预览；战利品按游戏同款 RNG 流与分版本快照模拟，逐容器展示可开出内容。

## 使用方法
1. 打开「结构预览器」标签；
2. 输入种子与坐标；
3. 选择要预览的结构类型；
4. 在 3D 视图中查看：右键拖拽旋转 / 滚轮缩放 / 左键拖拽平移；双击可复制；
5. 开箱预览容器内的战利品（按版本快照展示每个容器可开出内容）。

## 覆盖结构
村庄 / 前哨站 / 试炼密室 / 远古城市（jigsaw 拼装）、要塞 / 林地府邸 / 末地城 / 下界堡垒 / 沙漠神殿 + 丛林神庙 / 废弃传送门 + 埋藏的宝藏 等。
"""),

    ("指令生成器", """# 指令生成器

## 用途
按表单填写参数，自动生成正确的 Minecraft 指令文本（含 **1.20.5+ 数据组件**语法），并做实时校验。免去手写 NBT / SNBT 的易错环节。

## 使用方法
1. 打开「指令生成器」标签；
2. 在左侧指令树选择指令（**41 条全部可用**）；
3. 中栏填写参数：
   - `give`：基础参数 + 数据组件卡片区（附魔、自定义名称、描述、无法破坏等）；
   - 其余指令：按声明式规格自动生成表单（分支指令会先出现「分支」下拉）；
4. 右栏实时查看**预览**（图标 / 中文名 / 说明）、**输出**指令与**校验**结果；
5. 点「复制指令」复制到剪贴板。

## 支持的全部指令
**41 / 41 条全部可用**：

| 组 | 指令 |
|---|---|
| 物品与实体 | give item summon loot enchant effect kill attribute damage playsound particle spawn_armor_trims |
| 方块与世界 | setblock fill clone fillbiome place locate forceload data worldborder gamerule tick schedule |
| 玩家与进度 | experience advancement title scoreboard team bossbar waypoint |
| 执行与控制 | dialog random spreadplayers teleport rotate debugconfig chase datapack raid execute |

其中 `gamerule` 内置 **59 条规则表**（26.2 的 snake_case 新命名），
选中规则后值类型自动切换 bool/int。

**目标选择器可视化构建器**：所有 `targets` 字段（kill / effect / give / tp 等）
不再手写 `@e[type=zombie,distance=..10]` —— 用下拉 + 参数行 + 实时预览：
选择器类型（@p/@a/@e/@r/@s）+ 18 个预设 + 20 种参数（type/name/tag/team/
x/y/z/distance/level/gamemode/limit 等），参数值按类型分配控件（实体下拉 /
整数步进框 / 范围校验 / 游戏模式枚举）；可选字段显示「可选」标识。

**药水与药水箭中文名**：46 种药水（含长效/强烈变体）与 25 种药水箭
全部有中文译名（抗火药水、迅捷药水、神龟药水、抗火之箭、迅捷之箭 等）。

**物品清单纯净**：物品下拉只收录真实物品（1708 个），已剔除 jar 语言
文件中混入的 928 个翻译键条目与 132 个图标变体名（如 `potion_awkward`），
因此每一项都能正确显示中文译名。

**NBT key 显示**：键列显示 `key（中文）` 格式（如 `NoAI（禁用 AI）`），
序列化时自动提取 key 部分；编辑键名时 tooltip 同步更新中文说明。

**`execute` 用链式构建器**（管道语法）：按顺序添加子命令，
每行只显示该子命令相关的参数，可拖动排序/删除，最后以 run 收尾。
内置 36 个子命令（执行者位置 / 条件 if·unless / 存储 store / run）。

## 版本差异（自动处理）
顶部「版本」决定输出语法。**附魔组件格式随版本变化**：

| 版本 | 输出形式 |
|---|---|
| 1.21 | `minecraft:enchantments={levels:{"minecraft:sharpness":5}}` |
| 1.21.11 / 26.2 | `minecraft:enchantments={"minecraft:sharpness":5}` |

依据：`ItemEnchantments.CODEC` 为裸映射，而 `TooltipDisplayComponentFix`（schema 4307）会把旧的 `levels` 包装键剥掉，故只有 data version < 4307（1.21 = 3953）才需 `levels` 包装。

## 校验项
- 括号配平、指令长度上限（25600）、数量范围；
- 附魔：等级上限、互斥冲突（如锋利 ↔ 亡灵杀手）、`stored_enchantments` 仅用于附魔书；
- `effect`：时长须 ≥ 1 秒、`infinite` 无时长参数提示；
- `fill`：32768 方块上限、过滤仅对 replace 生效；
- `summon`：NBT 必须是 `{…}` 复合标签；
- `locate`：使用 `#标签` 时会定位到最近的一个。

## 说明
- **全程只选不写**：所有资源类字段都是**可搜索下拉**（含中文名），覆盖物品 2636、音效 1637、方块 1053、实体 215、药水 46、粒子 115、状态效果 40、旗帜图案 43、生物群系 66、唱片 21、结构 34、兴趣点 20、伤害类型 50、属性 35、盔甲纹饰材料/图案、乐器等（约 3300 项）；
- **NBT 可视化编辑**：`summon` 等指令的 NBT 字段不需要手写 SNBT ——
  点「编辑 NBT…」弹出**全内联编辑器**：键 / 类型 / 值三列直接修改
  （byte·short·int 用上下箭头步进框，long·float·double 带格式校验），
  「快速添加」内置常用标签库（禁用 AI、无敌、自定义名字、生命值、
  朝向、运动向量、主副手与盔甲物品、盔甲架姿态、容器上锁与物品栏等，
  共 24 项，键名类型默认值均已备好）；支持右键添加兄弟 / 复制节点 /
  上下移动 / 删除，重复与空键名自动标红，查找框回车定位；
  也支持把现成 NBT 粘贴进去反向解析成树再编辑；
- **数据组件全支持（79 个，其中 75 个有结构化编辑器）**：组件清单来自反编译 `DataComponents.java`；每个组件的字段（键名/类型/可选性/默认值）由各组件的 `CODEC` 定义**自动提取**。「添加组件」下拉按 7 组分类（常用 / 战斗与工具 / 消耗与食物 / 装备与外观 / 容器与存储 / 地图与书籍 / 其他）；
- **容器与列表类**均有专用控件：收纳袋/容器内容（槽位表）、迷之炖菜（效果 + 时长）、旗帜图案（图案 + 颜色）、方块状态（键值表）、地图标记、药水内容、蜜蜂（实体 + 在巢刻数）、可破坏/可放置（方块 id 或 #标签）等；
- 少数语义特殊的组件有专用控件：附魔（表 + 互斥校验）、自定义名称与描述（文本组件）、属性修饰符（属性表）、染色（取色器）、头颅皮肤（玩家名/UUID）等；
- 剩余 4 个（自定义数据 / 实体数据 / 方块实体数据 / 桶装实体数据）的值本身就是**任意 NBT**，用 SNBT 弹窗编辑是正确方式；
- 参数区与序列化逻辑解耦：序列化层为纯函数（`Utils/CommandGenerator/`），可独立单测；新增指令只需写一段声明式规格（`cmd_specs.py`）。

## 已知需手填的字段
个别组件的必填字段无法给出默认值，留空时校验区会明确提示
（而非静默产出非法指令）：

| 组件 | 必填字段 | 说明 |
|---|---|---|
| `container_loot` | `loot_table` | 战利品表 id，如 `minecraft:chests/simple_dungeon` |
| `tool` | `rules` | 挖掘规则列表 |
"""),
]


class AboutDialog(QDialog):
    """「使用说明 / 关于」窗口：左侧导航（工具列表）+ 右侧 Markdown 内容。"""

    def __init__(self, parent=None):
        from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout,
                                       QPushButton, QTextBrowser, QListWidget)
        super().__init__(parent)
        self.setWindowTitle("MCHelper 使用说明")
        self.resize(900, 560)

        outer = QVBoxLayout(self)
        body = QHBoxLayout()
        self.nav = QListWidget()
        self.nav.setFixedWidth(150)
        for label, _ in ABOUT_SECTIONS:
            self.nav.addItem(label)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setStyleSheet("font-size: 13px;")
        body.addWidget(self.nav)
        body.addWidget(self.browser, 1)
        outer.addLayout(body, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        ok = QPushButton("确定")
        ok.clicked.connect(self.accept)
        btn_row.addWidget(ok)
        outer.addLayout(btn_row)

        self.nav.currentRowChanged.connect(self._show_section)
        self.nav.setCurrentRow(0)

    def _show_section(self, row: int):
        """根据左侧导航行号，在右侧渲染对应工具的说明。"""
        if 0 <= row < len(ABOUT_SECTIONS):
            _, text = ABOUT_SECTIONS[row]
            self.browser.setMarkdown(text)