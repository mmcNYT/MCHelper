# MCHelper

Minecraft Java 版玩家工具合集（PySide6 桌面应用）。单窗口、Tab 切换多工具，围绕**种子逆推、结构预览、地图预览、战利品预测**等玩法场景提供本地化支持：

- 机制对齐：RNG/结构生成逻辑以 Wiki 与反编译源码为基准复刻，并与真实游戏数据核对；
- 精确逐种子：结构拼装、战利品计算按输入种子逐次复现游戏随机流，而非统计估算；
- 全本地运行：数据不出本机，无需联网；
- 版本覆盖：1.18 ~ 1.21+（已适配 Minecraft 26.2）。

## 项目结构

```
MCHelper/
├─ main.py                  程序入口
├─ main_window.py           主窗口（工具注册 / Tab 拖拽 / 顺序持久化 / 托盘）
├─ Tools/                   工具控制层：每工具一个 tool_*.py（继承 tool_base）
├─ Threads/                 后台任务线程（QThread / QRunnable + 信号回传）
├─ CodesUI/                 Qt Designer 生成的界面骨架（仅 UI，无业务逻辑）
├─ Utils/
│  ├─ Public/               跨工具公共模块（通知、图标、结构参数表、结构枚举引擎等）
│  ├─ MainWindow/           可拖拽 Tab 栏组件
│  ├─ Settings/             设置信号总线
│  ├─ AutoBackUp/           备份通知 / 进程监测组件
│  ├─ EnchantCaculator/     附魔计算核心（优化算法 / 步骤树 / 卡片控件）
│  ├─ MapPreviewer/         地图采样与配色（含 _native 原生扩展）
│  ├─ SeedReverser/         种子逆推核心算法库（RNG / 噪声 / NBT 模型 / 3D 视图）
│  └─ StructurePreviewer/   结构拼装与战利品引擎
├─ assets/
│  ├─ Public/               公共资源（群系图标、结构 EnvSprite、附魔流光）
│  ├─ SeedReverser/         结构模板 NBT / 方块纹理 / 六大结构拼装资产
│  ├─ StructurePreviewer/   容器 GUI 纹理 / 物品图标
│  └─ EnchantCaculator/     物品图标
├─ data/                    附魔定义（enchants.json）
└─ Docs/CODEBASE.md         代码库手册（每份源文件的功能/流程/函数/接口/变量）
```

> 每个工具在 `CodesUI/` 下还有同名的 Qt Designer 界面骨架（`setupUi` 纯布局，无业务逻辑），下文模块清单只列业务模块。

## 工具一览

### 自动备份（AutoBackUp）

按配置把指定文件/文件夹压缩备份到目标目录，线程池并发执行、逐任务进度反馈；内置进程监测，被监测程序启动时弹窗提醒；完成/失败通过桌面气泡通知反馈。

**模块构成**：
- `Threads/task_AutoBackUp` —— 备份压缩任务（QRunnable）：单文件/目录打包 zip，8KB 分块上报字节级进度
- `Utils/AutoBackUp/signals_AutoBackUp` —— 全局信号总线 `backup_bus`：任务开始/进度/完成三信号，负责子线程→主线程通信
- `Utils/AutoBackUp/process_monitor` —— 进程监测：定时轮询系统进程列表，发现被监测程序（默认 `java.exe`）启动即发信号
- `Utils/AutoBackUp/right_icon_delegate` —— 备份列表行尾图标绘制委托
- `Utils/Public/notification` —— 右下角可堆叠气泡通知（公共模块，4 个工具共用）

### 附魔计算器（EnchantCaculator）

选择物品与附魔后，自动规划**费用最优的铁砧合成顺序**；以合成步骤树展示每一步的合并方式与累计费用，配合物品卡片与流光动画。

**模块构成**：
- `Utils/EnchantCaculator/enchant_data_manager` —— 附魔定义数据管理：读写 `data/enchants.json`（附魔上限/稀有度/可附魔物品）
- `Utils/EnchantCaculator/choose_items` —— 物品/附魔选择对话框：附魔书白名单过滤、冲突附魔置灰、预填已选
- `Utils/EnchantCaculator/enchanted_item_card` —— 物品卡片控件：中文物品名→图标映射、附魔流光纹理绘制
- `Utils/EnchantCaculator/card_list_widget` —— 已选物品卡片列表（拖拽增删、延迟重建防闪烁）
- `Utils/EnchantCaculator/drop_list_widget` —— 可拖放列表基控件（`"ID:等级"` MIME 拖放约定）
- `Utils/EnchantCaculator/enchant_list_widget` —— 附魔等级列表：左键加级 / 右键减级
- `Utils/EnchantCaculator/conflict_resolver` —— 冲突决策对话框：并查集聚簇，非附魔书共有附魔自动决策归属
- `Utils/EnchantCaculator/anvil_optimizer` —— 核心算法：铁砧合成顺序优化，Dijkstra 精确搜索为主（状态=物品多重集合，按累计花费出堆）、贪心降级兜底，输出最小花费合并序列
- `Utils/EnchantCaculator/anvil_steps_tree` —— 合成步骤树：树/步骤双模式版面，逐节点渲染合并方向与累计等级花费

### 地图预览器（MapPreviewer）

输入种子即可渲染主世界/下界/末地的群系地图，支持版本与维度切换、结构标注、群系定位锚点收藏、图例与悬浮信息。

**模块构成**：
- `Threads/task_MapPreviewer` —— 后台渲染线程：把视野分块调度采样→numpy 数组组装，进度上报与取消
- `Utils/MapPreviewer/map_sampler` —— 主世界群系采样：按 scale 分层调用 cubiomes 噪声查询，原生扩展优先、纯 Python 兜底
- `Utils/MapPreviewer/nether_end_sampler` —— 下界/末地采样：下界双 Perlin 噪声 5 点最近邻，末地岛屿 chunk 级窗口展开
- `Utils/SeedReverser/mc_random` —— Java Random 函数式 LCG（标量 + numpy 向量化），复刻采样随机流（SeedReverser 核心库，跨工具复用）
- `Utils/SeedReverser/biome_noise` —— 群系噪声查询核心：B 树查找表（`btree_tables.npz`）把温度/湿度等气候参数映射为群系 id
- `Utils/MapPreviewer/biome_colors` —— 群系 id→RGB 配色表（悬停/图例中文群系名）
- `Utils/MapPreviewer/block_colors` —— 方块级渲染色：树冠结构色、水体三档深度色、恶地形色带与光照
- `Utils/Public/structure_map` —— 结构枚举引擎：盐值→区域种子→块坐标逐结构判定与包围盒（公共模块）
- `Utils/Public/structure_params` —— 结构参数总表（salt/区域尺寸/间距/版本下限/维度，公共模块）
- `Utils/Public/structure_icons`、`biome_names`、`biome_signature_colors` —— 结构 EnvSprite 图标、群系 id/中文名/图标表、群系签名色（公共模块）
- `Utils/MapPreviewer/choose_structure` —— 结构选择对话框（图标预览 + 多选）
- `Utils/MapPreviewer/_native` —— pybind11 原生扩展：cubiomes 群系噪声加速（可选，缺则纯 Python 回退）

### 要塞定位（StrongHoldFinder）

从剪贴板监听 F3+C 调试数据，解析两条投掷末影之眼的射线，计算交汇点并给出要塞坐标与 `/tp` 命令；带输入防抖与合法性预判，定位完成弹窗通知。

**模块构成**：
- `Threads/task_StrongHoldFinder` —— 剪贴板监听线程：Win32 API 轮询剪贴板序号，F3+C 数据到达即解析上屏
- `Utils/Public/stronghold_math` —— F3C 命令解析（两次投掷的位置+偏航角）与双射线交汇求解，输出交汇坐标与 `/tp` 命令（公共模块，SeedReverser 也复用其解析）
- `Utils/Public/notification` —— 桌面气泡通知（公共模块）

### 种子逆推（SeedReverser）

从观察到的结构生成位置（如"沉船在区块 (x, z)"）逆推 48 位结构种子，再经高位精细化还原世界种子；支持多观察值联立、信息熵提示、容差设置与候选种子验证，内置结构 2D/3D 视图辅助对照。

**模块构成**：
- `Threads/task_SeedReverser` —— 逆推线程：48 位结构种子枚举（低位 lifting 预筛 + 容差判定），进度与取消
- `Threads/task_WorldSeedRefine` —— 世界种子精细化线程：结构种子→枚举世界种子高 16 位并二次校验
- `Utils/SeedReverser/structure_math` —— 逆推核心：观察值→区域种子→正向重放 RNG→偏移比对验证，numpy 批量向量化筛选
- `Utils/SeedReverser/seed_math` —— 区域/偏移坐标换算与信息量估算（提示当前观察值证据是否足够）
- `Utils/SeedReverser/mc_random` —— Java Random 函数式 LCG：set_seed / next / next_int（拒绝采样）/ 区域种子等原语
- `Utils/SeedReverser/mc_rng` —— 结构布局 RNG：LegacyRandomSource、setLargeFeatureSeed、Mth.getSeed 复刻
- `Utils/SeedReverser/world_seed_refine` —— 结构种子→世界种子：高 16 位枚举 + 群系噪声逐候选校验
- `Utils/SeedReverser/biome_noise` —— 群系噪声查询（候选种子群系校验的数据源）
- `Utils/Public/structure_params`、`stronghold_math`、`biome_names`、`biome_signature_colors`、`structure_icons` —— 结构参数/F3C 辅助解析/群系表/签名色/结构图标（公共模块）
- `Utils/SeedReverser/structure_models` —— NBT 结构模板解析与体素网格构建（3D 视图数据源）
- `Utils/SeedReverser/block_shapes` —— 方块形状码体系（楼梯/栅栏/门等几何与朝向）
- `Utils/SeedReverser/structure_blueprints` —— 非模板结构的程序化蓝图（不走 NBT 的结构包围盒/层定义）
- `Utils/SeedReverser/structure_3dview` —— OpenGL 3D 结构视图：纹理图集、轨道/飞行双相机
- `Utils/SeedReverser/structure_preview` —— 2D 俯视预览图（已被 3D 视图取代，保留）
- `Utils/SeedReverser/_native` —— pybind11 原生扩展：噪声与逆推加速（可选，缺则纯 Python 回退）

### 结构预览器（StructurePreviewer）

输入种子与坐标，**逐种子精确复现结构拼装**，3D 视图内可自由飞行、开箱预览；战利品按游戏同款 RNG 流与分版本快照模拟，逐容器展示可开出内容。

**模块构成**：
- `Utils/StructurePreviewer/locator` —— 定位门面：结构枚举→拼装→显示模型三步流水线
- `Utils/StructurePreviewer/composition` —— 拼装总引擎：按结构类型分派，逐种子复现每块体素的方块/材质/朝向（箱子等容器位置随拼装产出）
- `Utils/StructurePreviewer/village_assembly`、`outpost_assembly`、`trial_assembly`、`ancient_city_assembly` —— 村庄/前哨站/试炼密室/远古城市的 jigsaw 拼装：加载各自 `assets/SeedReverser/<结构>/` 模板与 template_pool，复用通用引擎
- `Utils/StructurePreviewer/stronghold_pieces`、`mansion_pieces`、`end_city_pieces`、`fortress_pieces`、`pyramid_pieces` —— 要塞/林地府邸/末地城/下界堡垒/沙漠神殿+丛林神庙的结构件生成（递归/队列组装或 postProcess 逐行转写，复刻游戏逐件 RNG 消耗）
- `Utils/SeedReverser/jigsaw_assembly` —— jigsaw 通用拼装引擎：模板池解析、连接块匹配、旋转与放置（SeedReverser 核心库，跨工具复用）
- `Utils/SeedReverser/structure_models` —— NBT 模板解析与材质映射（体素与纹理键来源）
- `Utils/SeedReverser/mc_random`、`mc_rng` —— Java Random LCG 与布局 RNG 常量（拼装随机流复刻）
- `Utils/StructurePreviewer/loot_rng` —— 战利品 RNG：population seed→LootTableSeed 派生，Java 48 位 LCG + Xoroshiro128++ 双随机线
- `Utils/StructurePreviewer/loot_engine` —— 战利品表求值引擎：pool 条件→rolls→entry 加权抽取→LootFunction 执行（含附魔等级随机）
- `Utils/StructurePreviewer/data/loot` —— 分版本战利品表快照（`<表>.<版本档>.json`）
- `Utils/Public/structure_map`、`structure_params`、`biome_names`、`structure_icons` —— 结构枚举/参数/群系名/结构图标（公共模块）
- `Utils/SeedReverser/structure_3dview`、`block_shapes` —— 3D 视图（FP 飞行+开箱交互）与方块形状几何
- `assets/StructurePreviewer/gui`、`items` —— 容器槽位/面板纹理与 253 张物品图标

### 设置（Settings）

开机自启（注册表写入）与系统托盘开关，经全局信号总线实时广播生效。

**模块构成**：
- `Utils/Settings/signals_Settings` —— 全局信号总线 `settings_bus`：开机自启/托盘开关状态变化实时广播给主窗口

## 运行

```
Python 3 + PySide6 + numpy + psutil
> python main.py
```

原生扩展（群系噪声加速，可选）：需 MSVC 与 pybind11，分别运行 `Utils/MapPreviewer/_native/build_map.py`、`Utils/SeedReverser/_native/build_biome.py` 构建；未构建时程序以纯 Python 回退运行。

## 已知问题

- 渲染器性能不佳：地图预览与结构 3D 渲染在复杂场景下帧率/耗时表现一般，后续版本将持续优化。