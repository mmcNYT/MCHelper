# MCHelper 代码库手册

> 版本：2026-09-23（Utils/Public 与 assets/Public 结构整理后）。覆盖全部 60 份 Python 源文件与全部资源：每份文件含功能（含计算流程）、类与函数、接口、关键变量四节；接口引用关系均经全项目 grep 实证。

## 目录
- 0. 项目总览
- 1. 入口层（main.py / main_window.py）
- 2. 公共模块（Utils/Public）
- 3. 工具控制层与后台线程（Tools / Threads）
- 4. 附魔计算器（Utils/EnchantCaculator）
- 5. 备份组件与主窗口部件（AutoBackUp / Settings / MainWindow）
- 6. 地图预览器逻辑层（Utils/MapPreviewer）
- 7. 种子逆推核心库（Utils/SeedReverser · 算法）
- 8. 结构模型与渲染（Utils/SeedReverser · 引擎）
- 9. 结构预览器逻辑层（Utils/StructurePreviewer）
- 10. 界面骨架层（CodesUI）
- 11. 资源与数据

# 0. 项目总览

## 0.1 项目定位

MCHelper 是一个面向 Minecraft Java 版玩家的桌面工具合集（PySide6 单窗口、Tab 切换多工具），覆盖种子逆推、结构预览、地图预览、要塞定位、附魔计算、自动备份、设置管理等场景。数据全部本地处理，不依赖网络（除 Wiki 图标等静态资产已预先下载入库）。

**技术栈**：Python 3 + PySide6（UI 与 OpenGL 视图）+ numpy（向量化 RNG/采样）+ pybind11（cubiomes 群系噪声原生扩展，MSVC 编译）+ ctypes（3D 视图直接调用原生 glDrawElements / cubiomes 函数）。

## 0.2 架构分层

```
main.py                          入口：软件 OpenGL 属性 → QApplication → MainWindow
  └─ main_window.py              主窗口：工具注册/Tab 拖拽/顺序持久化/托盘/开机自启
       ├─ Tools/                 工具控制层（每工具一个 tool_*.py，继承 tool_base.BaseToolWidget）
       │    ├─ CodesUI/*         各工具的 Qt Designer 界面骨架（Ui_xxx.setupUi）
       │    ├─ Threads/task_*    后台任务线程（QThread/QRunnable，经信号总线回传主线程）
       │    └─ Utils/…           逻辑核心层（算法、采样、拼装、渲染、数据）
       └─ Utils/Public/          ★ 公共模块包：被 ≥2 个工具共用的模块
assets/Public/                   ★ 公共资源包：群系图标、结构 EnvSprite、附魔流光纹理
```

分层约定：
- **CodesUI 只做界面骨架**，不含业务逻辑；业务全部在 Tools 层。
- **Tools 层只做控制**（信号连接、UI 状态、会话持久化），重计算全部下沉 Utils / Threads。
- **Utils 层禁止反向依赖 Tools/Threads**；跨工具复用的模块放 `Utils/Public`。
- Qt 控件只在主线程创建；子线程通过信号总线（backup_bus / settings_bus）通信。

## 0.3 目录结构（整理后）

```
MCHelper/
├─ main.py / main_window.py      入口与主窗口
├─ Tools/                        7 个工具控制层 + tool_base 基类 + TOOL_CLASSES 注册表(__init__)
├─ Threads/                      4 个后台任务线程
├─ CodesUI/                      11 个 Qt Designer 生成的 UI 骨架
├─ Utils/
│  ├─ Public/                    ★ 公共模块（7 个，见 0.4）
│  ├─ MainWindow/                可拖拽 Tab 栏（主窗口专用）
│  ├─ Settings/                  设置信号总线
│  ├─ AutoBackUp/                备份通知/进程监测/图标委托/信号总线
│  ├─ EnchantCaculator/          附魔计算器 9 个模块
│  ├─ MapPreviewer/              地图采样与配色 6 个模块 + _native 原生构建
│  ├─ SeedReverser/              种子逆推核心库 14 个模块 + _native 原生构建
│  │                             （mc_random/mc_rng/structure_math/biome_noise/
│  │                              structure_models/jigsaw_assembly 等同时被
│  │                              MapPreviewer、StructurePreviewer 复用，定位为
│  │                              "SeedReverser 核心算法库"，因与 _native 编译扩展
│  │                              强耦合而保留原位，详见 07/08 章）
│  └─ StructurePreviewer/        结构拼装/战利品 14 个模块 + data/loot 快照
├─ assets/
│  ├─ Public/                    ★ 公共资源（群系图标 54 + EnvSprite 26 + 附魔流光 1）
│  ├─ SeedReverser/              结构模板 NBT/方块纹理/预览图/六大结构拼装资产（私有）
│  ├─ StructurePreviewer/        GUI 纹理与物品图标（私有）
│  └─ EnchantCaculator/          物品图标（私有）
├─ data/enchants.json            附魔计算器数据
└─ Docs/CODEBASE.md              本手册
```

## 0.4 公共模块清单（Utils/Public）

| 模块 | 职责 | 共用工具 |
|---|---|---|
| notification.py | 屏幕右下角可堆叠气泡通知（NotificationWidget.Show） | AutoBackUp、MapPreviewer、SeedReverser、StrongHoldFinder |
| structure_icons.py | Wiki EnvSprite 结构图标加载（结构键+群系→PNG 路径） | MapPreviewer、SeedReverser、StructurePreviewer |
| biome_names.py | 群系 id↔内部键↔中文名表 + 群系图标路径 | MapPreviewer、SeedReverser、StructurePreviewer |
| structure_params.py | 结构参数总表（salt/区域尺寸/间距/版本/维度/可逆性） | MapPreviewer、SeedReverser、StructurePreviewer |
| biome_signature_colors.py | 群系 Wiki 签名色（信息框草地/水体色） | MapPreviewer、SeedReverser |
| stronghold_math.py | F3C 解析与要塞射线交汇数学 | StrongHoldFinder、SeedReverser |
| structure_map.py | 结构→世界枚举/单点判定引擎（RNG 复刻核心） | MapPreviewer、StructurePreviewer |

## 0.5 2026-09-23 整理记录

**代码迁移**（git mv，保留历史；全部 import 已同步更新，py_compile 全量通过 + GUI 冒烟通过）：

| 原位置 | 新位置 |
|---|---|
| Utils/AutoBackUp/notification.py | Utils/Public/notification.py |
| Utils/MapPreviewer/structure_icons.py | Utils/Public/structure_icons.py |
| Utils/MapPreviewer/structure_map.py | Utils/Public/structure_map.py |
| Utils/SeedReverser/biome_names.py | Utils/Public/biome_names.py |
| Utils/SeedReverser/structure_params.py | Utils/Public/structure_params.py |
| Utils/SeedReverser/biome_signature_colors.py | Utils/Public/biome_signature_colors.py |
| Utils/StrongHoldFinder/stronghold_math.py | Utils/Public/stronghold_math.py |

**代码清理**：删除死代码 `Utils/progress_file.py`（全项目零引用）。

**资源迁移**（80 个文件 → assets/Public/）：54 个群系图标（原 assets/SeedReverser/*.png）、26 个 EnvSprite（原 assets/MapPreviewer/*.png）、enchanted_glint.png（原 assets/EnchantCaculator/，同时消除与 enchanted_glint_item.png 的重复——两文件 MD5 相同，StructurePreviewer 引用已并轨）。

**资源清理**：
- `assets/minecraft/`（models/textures 空目录，零引用）— 已删
- `assets/StructurePreviewer/items_iso/`（12 张 PNG，零引用）— 已删
- `assets/SeedReverser/textures/block/` 下 11 个无扩展名残片（`acacia leaves` 等，代码一律按 `键 + ".png"` 拼接，永远加载不到，对应 .png 均存在）— 已删
- `assets/EnchantCaculator/enchanted_glint_item.png`（与 enchanted_glint.png 重复）— 已删

## 0.6 阅读指南

- 先读本章与 `01_root.md`（入口层），再按所关注工具跳转对应章节。
- 算法类模块（structure_map、structure_math、biome_noise、loot_engine、composition 等）的功能小节都写到"每步 RNG 如何消耗"的粒度，可与反编译源码逐符号对拍。
- 各文件节统一格式：**功能**（含计算流程）→ **类与函数**（表格）→ **接口**（引用关系，均经全项目 grep 实证）→ **关键变量/常量**。

# 1. 入口层（main.py / main_window.py）

# 根目录模块文档（main.py / main_window.py）

> 项目：MCHelper（PySide6 MC Java 版工具合集，tab 切换多工具单窗口）
> 本文基于源码精读编写，覆盖项目根目录下两个核心文件。

## `main.py`

**功能**：程序唯一入口脚本，共 18 行，职责是"设置渲染后端 → 创建应用 → 创建主窗口 → 进入事件循环"，不含任何业务逻辑。

实现原理与启动流程（`if __name__ == "__main__":` 内，按顺序执行）：

1. **强制软件渲染（关键的崩溃规避）**：在创建 `QApplication` **之前**调用 `QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)`。源码注释写明原因：NVIDIA 桌面 GL 驱动（`nvoglv64.dll`）在 Qt 6.11 的 `QOpenGLWidget` 第二次模型绘制的 begin-paint 阶段存在 `0xC0000409`（栈缓冲区溢出类）崩溃，改用软件渲染后端（opengl32sw/llvmpipe）绕开。该属性必须先于 `QApplication` 构造设置，否则不生效——这决定了它必须是本文件的第一行实质代码。
2. **创建应用对象**：`app = QApplication(sys.argv)`，传入命令行参数。
3. **创建主窗口**：`window = MainWindow()`（实例化过程中完成工具加载、TabBar 替换、菜单/托盘创建等，详见 `main_window.py` 一节）。
4. **显示并进入事件循环**：`window.show()` 后 `sys.exit(app.exec())`，以 `app.exec()` 的退出码作为进程退出码。

**类与函数**：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| （无类定义） | — | 本文件不定义任何类，仅包含模块级入口代码块 `if __name__ == "__main__":`，内部流程见上文"功能"四步。 |

**接口**：

- **被哪些模块 import**：无。`main.py` 是顶层启动脚本，不被项目中任何模块导入；只由用户/快捷方式/开机自启项（注册表 Run 键，见 `main_window.set_start_on_boot`）直接执行。
- **对外提供**：无类、无信号、无公开方法。它 import 了 `main_window.MainWindow`，是整条启动链的起点。

**关键变量/常量**：

| 名称 | 类型 | 说明 |
| --- | --- | --- |
| `app` | `QApplication` | 模块级（`__main__` 块内）应用对象，整个程序唯一的 Qt 应用实例，`app.exec()` 启动主事件循环。 |
| `window` | `MainWindow` | 主窗口实例，来自 `main_window.py`，构造时完成全部初始化，随后 `show()` 显示。 |
| `Qt.ApplicationAttribute.AA_UseSoftwareOpenGL` | Qt 枚举常量 | 应用级属性，强制 Qt 使用软件 OpenGL 渲染（llvmpipe/opengl32sw），规避 NVIDIA 驱动崩溃；必须在 `QApplication` 构造前设置。 |

## `main_window.py`

**功能**：定义主窗口类 `MainWindow(QMainWindow, Ui_MCHelper)`，是整个应用的"壳"：负责工具 tab 的注册与加载顺序持久化、可拖拽 tab 栏、窗口尺寸自适配、系统托盘与最小化到托盘、菜单栏（设置/关于）、开机自启动注册表写入，以及退出前的逐工具配置保存。多继承 Qt Designer 生成的 `Ui_MCHelper`（`CodesUI.MCHelperMainWindow`），`setupUi(self)` 完成菜单栏、central widget、`tabWidget` 等控件的搭建。

**初始化顺序**（`__init__` 内，严格按源码顺序）：

1. `super().__init__()` + `self.setupUi(self)`：完成 Qt Designer UI 搭建（`tabWidget` 等在此创建）。
2. 初始化四个状态量：`is_system_tray = False`（是否最小化到托盘）、`is_start_on_boot = False`（是否开机自启动）、`is_quitting = False`（是否正在退出）、`_chrome_hint = None`（最近一次测得的合理窗口装饰开销缓存）。
3. `self._setup_draggable_tab_bar()`：把 `tabWidget` 的原生 TabBar 替换为支持拖拽重排的 `DraggableTabBar`（下文详述）。
4. `self.load_tools()`：按保存的顺序把所有工具实例化并加入 tab（无记录时用注册表默认顺序）。
5. 连接 `self.tabWidget.currentChanged → self.adapt_window_to_tool`：切换 tab 时窗口自适应当前工具的期望尺寸。
6. `QTimer.singleShot(0, lambda: self.adapt_window_to_tool(self.tabWidget.currentIndex()))`：**启动补正**。首个 `addTab` 会自动选中 index 0，但发生时 `currentChanged` 信号尚未连接，若不补正程序会以默认 800×600 打开；用 0ms 延迟把这次自适应排到事件循环启动后执行。
7. `self.create_menu()`：创建菜单栏并绑定信号。
8. 连接设置总线信号：`settings_bus.is_system_tray → self.system_tray_controller`、`settings_bus.is_start_on_boot → self.start_on_boot_controller`。`settings_bus` 是 `Utils/Settings/signals_Settings.py` 中定义的模块级单例 `SettingsSignals(QObject)`，含两个 `Signal(bool)` 信号，供设置页跨窗口广播配置变更。
9. `self.creat_tray_icon()`：创建系统托盘图标（注意：方法名是源码原样的 `creat_tray_icon`，少一个 e）。

**工具注册机制**（核心流程）：

- **注册表**：所有工具类集中放在 `Tools/__init__.py` 的 `TOOL_CLASSES` 列表中（当前 6 个：AutoBackUp、EnchantCalculator、StrongHoldFinder、SeedReverser、MapPreviewer、StructurePreviewer）。新增工具只需把类追加到该列表。
- **工具元信息协议**：工具类继承 `BaseToolWidget` 并实现 `@classmethod tool_name()` 返回工具显示名（Tab 标题）。关键点：`load_tools` 里**先用 classmethod 拿名字、再实例化**——`tool_name()` 调用不创建对象，`tool_widget = tool_cls(self)` 这一行才真正实例化，随后 `addTab(tool_widget, tool_name)` 加入页签。
- **顺序恢复**（`_order_tool_classes`）：读取 `tab_order.json`（工具名列表），按"保存的顺序里能对上注册表的名字优先、其余按注册表默认顺序追加"合成最终顺序。兼容规则（源码注释原文）：保存顺序包含全部工具 → 按保存顺序；新增了工具（保存记录里没有）→ 新工具按注册顺序追加在后面；保存记录里有已不存在的工具名 → 忽略（防止下次又存回去）；无记录/文件损坏/格式不合法（非字符串列表）→ 返回默认顺序 `list(TOOL_CLASSES)`。
- **配置路径回退**（`tab_order_config_path_static`）：优先 `QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)`；返回空（异常环境）则回退到本文件所在目录；目录不存在时 `os.makedirs(..., exist_ok=True)` 自动创建；最终文件名为 `tab_order.json`（与 `settings_config.json` 同目录）。提供 staticmethod 版本是为了"不实例化主窗口即可获取，供测试等外部代码使用"，实例方法 `_tab_order_config_path` 只是转发。
- **顺序保存**（`_save_tab_order`）：遍历 `tabWidget` 各页，按页部件的 `tool_name()` 取名写入 JSON（`ensure_ascii=False, indent=2`）。**刻意不用 `tabText`**：tabText 是展示文本，拖拽中途等场景下可能暂时为空，而 `tool_name()` 是工具注册名，会话内唯一且稳定；仅当页部件没有 `tool_name` 属性时才回退用 `tabText`。触发时机有两个：① 拖拽结束——`DraggableTabBar.orderChanged`（自定义信号，只在拖动结束后发射）连接到本方法；② 退出时 `save_all_tools_config` 末尾再存一次（双保险）。**不用 QTabBar 自带 `tabMoved`** 的原因（源码注释）：拖动中途每次让位（`moveTab`）都会发射它，中途顺序不是最终顺序。
- **可拖拽 TabBar 替换**（`_setup_draggable_tab_bar`）：`QTabWidget` 没有公开的 `setTabBar` 接口（PySide6 中是受保护槽，可直接调用），先 `DraggableTabBar(self.tabWidget)` 创建新 TabBar（继承时自动带上 QTabWidget 的父子关系与样式），再 `self.tabWidget.setTabBar(self.tab_bar)` 换掉原生 TabBar；原生 TabBar 被接管后即被 C++ 侧销毁，无需也不能再手动删除。随后连接 `self.tab_bar.orderChanged → self._save_tab_order`。

**窗口自适应流程**（`adapt_window_to_tool(index)`，tab 切换时触发）：

1. 前置拦截：`index < 0`、对应页部件为 `None`、部件未声明 `preferred_size`（或为空）、窗口处于最大化/最小化/全屏——均直接返回不干预。`preferred_size` 是 `BaseToolWidget` 的类属性 `tuple | None`，由各工具声明期望的内容区尺寸。
2. **装饰开销测算**：`chrome_w = self.width() - widget.width()`、`chrome_h` 同理，即菜单栏 + central widget 布局边距 + tab 栏 + tab 页边框的固定开销（不随窗口大小变化）。注意 `resize()` 设置的是客户区尺寸，不能用 `frameGeometry()`（含原生边框）。有效性校验：仅当差值 ≥ 0（窗口 ≥ 页面最小尺寸，页面能铺满窗口）时才更新缓存 `self._chrome_hint`；差值为负说明窗口被钳制得比页面最小尺寸还小（页面被托住），此时改用 `self._chrome_hint` 缓存值（无缓存则按 0 处理），避免把窗口 resize 到垃圾尺寸。
3. **尺寸适配**：目标客户区 = `preferred + chrome`；再按当前屏幕可用区域（`screen().availableGeometry()`，排除任务栏）钳制——用 `frameGeometry().width() - self.width()` 算出左右+上下原生边框（含标题栏）开销 `frame_w/frame_h`，`target = min(target, max(available - frame, 100))`，下限 100 防止可用区域异常小时得到负数/极小窗，保证整个窗口（含装饰）完整落在屏内；内容区被压缩后由各工具自身布局消化。
4. **位置适配**：`move()` 定位的是客户区左上角，先算边框相对客户区的偏移 `off_x/off_y`（`frameGeometry().left() - self.x()` 等）。若 frame 右/下边缘超出可用区域则向左/上移回；再检查左/上边缘（处理缩小后遗留的屏外位置或窗口比屏幕还大的极端情况），保证左上角至少在屏内。只拉回越界部分，不动用户本来就摆好的位置。

**关闭与退出流程**（`closeEvent(event)`）：

1. **逐工具关闭许可**：遍历所有 tab 页，部件若有可调用的 `can_close` 且返回 `False`（如 AutoBackUp 备份进行中），弹 `QMessageBox.warning`（"无法关闭：工具正在执行备份任务……"），`event.ignore()` 后直接 return，本次关闭被阻止。
2. 若 `is_quitting` 为 True（托盘菜单"关闭程序"已置位）**或** 未启用最小化到托盘（`is_system_tray == False`）：调用 `save_all_tools_config()` 保存全部工具配置，`event.accept()` 正常关闭。
3. 若托盘图标存在且可见：`self.hide()` 隐藏窗口到托盘，`event.ignore()`（程序继续在托盘运行）。
4. 托盘不可见（兜底）：保存配置后 `event.accept()`。

**托盘与退出**：`creat_tray_icon` 创建 `QSystemTrayIcon`，图标用当前样式的标准图标 `QStyle.SP_ComputerIcon`（注释建议正式版改用资源文件 `:/icons/app.ico`），tooltip 为 "MCHelper"；右键菜单两项——"显示窗口"（→ `show_window`）与"关闭程序"（→ `quit_app`）；`activated` 连接 `tray_activated`，仅处理左键单击（`QSystemTrayIcon.Trigger`）→ `show_window`。`show_window` 依次 `show()` + `raise_()`（提升到顶层）+ `activateWindow()`（取焦点）。`quit_app` 置 `is_quitting = True` → `save_all_tools_config()` → `QApplication.quit()` 彻底退出。

**配置保存**（`save_all_tools_config`）：遍历所有 tab 页，部件若有可调用的 `save_config` 则调用（逐个 try/except，失败仅打印 `保存工具 {tool_name} 配置失败` 不中断），最后调用 `_save_tab_order()` 同步保存 tab 顺序。工具侧是否实现 `save_config`/`can_close` 是可选协议，用 `hasattr + callable` 探测。

**菜单栏**（`create_menu`）：创建 `QMenu("菜单")`，按列表 `["设置", "关于"]` 逐项建 `QAction`，`action.setData(索引)`（设置=0、关于=1）后 `triggered` 统一连接 `menu_controller`，菜单加入 `self.menuBar()`。`menu_controller` 用 `self.sender()` 拿到触发的 action、`action.data()` 取回索引；当前只处理索引 0：`SettingsWindow(self)` 创建设置对话框（来自 `Tools/tool_Settings`）并以 `exec()` 模态打开。索引 1（关于）暂无处理分支。

**开机自启动**（`set_start_on_boot(enable: bool)`）：操作注册表 `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`，值名固定为 `"MCHelper"`。以 `KEY_SET_VALUE` 打开键后：`enable=True` 时取 `os.path.abspath(sys.argv[0])` 作为程序路径，若是 `.py` 则写 `"<sys.executable>" "<脚本路径>"`（python.exe 调用），否则（打包后的 .exe）直接写自身路径，`SetValueEx` 写入 `REG_SZ`；`enable=False` 时 `DeleteValue` 删除（值不存在则捕获 `FileNotFoundError` 提示）。成功返回 `True`，任何注册表异常打印 `✗ 操作注册表失败` 并返回 `False`。该方法由 `start_on_boot_controller` 在收到 `settings_bus.is_start_on_boot` 信号时调用（同时更新 `is_start_on_boot` 状态量并打印）；`system_tray_controller` 同理只更新 `is_system_tray` 并打印。

**类与函数**：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `MainWindow` | `class MainWindow(QMainWindow, Ui_MCHelper)` | 主窗口类，多继承 QMainWindow 与 Designer 生成的 UI 类；下表为其全部方法。 |
| `__init__` | `__init__(self)` | 按"UI 搭建 → 状态量 → 可拖拽 TabBar → 加载工具 → 连接自适应信号与 0ms 补正 → 菜单 → 设置总线信号 → 托盘"的顺序完成初始化（详细流程见上文"功能"节）。无参数，无返回值。 |
| `_setup_draggable_tab_bar` | `_setup_draggable_tab_bar(self)` | 创建 `DraggableTabBar(self.tabWidget)` 并经 `setTabBar` 替换原生 TabBar（原生件随即被 C++ 侧销毁）；把 `orderChanged` 连接到 `_save_tab_order` 实现拖拽后自动持久化。 |
| `tab_order_config_path_static` | `@staticmethod tab_order_config_path_static() -> str` | 返回 tab 顺序配置文件路径（`<AppConfigLocation 或脚本目录>/tab_order.json`，目录不存在自动创建）。静态版供测试等外部代码在未实例化主窗口时使用。 |
| `_tab_order_config_path` | `_tab_order_config_path(self) -> str` | 实例版配置路径，直接转发到 `tab_order_config_path_static()`，保证两处逻辑一致。 |
| `_load_tab_order` | `_load_tab_order(self) -> list \| None` | 读取 `tab_order.json` 并 `json.load`；仅当结果是"全为字符串的列表"时返回该列表；文件不存在、`OSError`/`ValueError`（含 JSON 损坏）或格式不合法时打印失败原因并返回 `None`（调用方据此回退默认顺序）。 |
| `_save_tab_order` | `_save_tab_order(self) -> None` | 遍历 `tabWidget` 各页，按 `widget.tool_name()`（缺该属性时回退 `tabText`）收集顺序并写 JSON（UTF-8、`ensure_ascii=False`、缩进 2）；写失败打印不抛出。由拖拽结束（orderChanged）与退出流程调用。 |
| `load_tools` | `load_tools(self) -> None` | 工具加载主流程：先 `_order_tool_classes()` 得到有序工具类列表；对每个类先调 classmethod `tool_name()` 拿 Tab 标题（不创建对象），再 `tool_cls(self)` 实例化（parent 为主窗口），最后 `addTab(tool_widget, tool_name)` 加入页签。 |
| `_order_tool_classes` | `_order_tool_classes(self) -> list` | 合成最终工具顺序：默认 `list(TOOL_CLASSES)`；有保存记录时按 `tool_name() → 类` 建映射，先返回记录中出现且仍存在的类，再把记录中没出现的新工具按注册顺序追加；记录里有已不存在的名字直接忽略；结果为空则兜底返回默认顺序（详细兼容规则见上文）。 |
| `adapt_window_to_tool` | `adapt_window_to_tool(self, index: int) -> None` | tab 切换时窗口自适应该工具 `preferred_size`：测算窗口装饰开销（含 `_chrome_hint` 负差值缓存兜底）→ 目标客户区 = 期望尺寸 + 开销 → 钳制到屏幕可用区域内（下限 100）→ `resize` → 位置越界检查与拉回。四种前置情况不干预（见上文流程 1）。参数 `index` 为当前 tab 索引。 |
| `closeEvent` | `closeEvent(self, event) -> None` | 窗口关闭事件处理：先逐工具询问 `can_close()`（备份中则警告并 `event.ignore()` 阻止）；再按 `is_quitting`/`is_system_tray`/托盘可见性三分支决定"保存并关闭 / 隐藏到托盘 / 保存并关闭"（详细分支见上文）。 |
| `save_all_tools_config` | `save_all_tools_config(self) -> None` | 逐 tab 调用部件的 `save_config()`（可选协议，hasattr 探测；单个失败打印不中断），最后 `_save_tab_order()` 再存一次 tab 顺序（与拖拽即时保存构成双保险）。 |
| `creat_tray_icon` | `creat_tray_icon(self) -> None` | 创建托盘图标：标准 `SP_ComputerIcon` 图标、tooltip "MCHelper"、右键菜单（显示窗口/关闭程序）、`activated → tray_activated`，最后 `show()` 显示。（方法名沿源码原样，`creat` 少一个 e。） |
| `tray_activated` | `tray_activated(self, reason) -> None` | 托盘激活回调：仅当 `reason == QSystemTrayIcon.Trigger`（左键单击）时调用 `show_window()`，其余激活方式忽略。 |
| `show_window` | `show_window(self) -> None` | `show()` 显示窗口 + `raise_()` 提升到顶层 + `activateWindow()` 激活取焦点，三连保证从托盘唤起时窗口前置可见。 |
| `quit_app` | `quit_app(self) -> None` | 彻底退出：置 `is_quitting = True` → `save_all_tools_config()` 保存全部配置 → `QApplication.quit()`。由托盘菜单"关闭程序"触发；置位后 `closeEvent` 走"正常关闭"分支。 |
| `create_menu` | `create_menu(self) -> None` | 建 `QMenu("菜单")`，为 `["设置", "关于"]` 逐项创建 `QAction` 并 `setData(索引)`，`triggered` 统一接 `menu_controller`，加入菜单栏。 |
| `menu_controller` | `menu_controller(self) -> None` | 菜单动作统一分发：`self.sender()` 取触发的 action，`action.data()` 取索引；索引 0 时 `SettingsWindow(self).exec()` 模态打开设置窗口；索引 1（关于）暂无分支。 |
| `system_tray_controller` | `system_tray_controller(self, statu) -> None` | 响应 `settings_bus.is_system_tray(bool)`：把参数写入 `self.is_system_tray` 并打印 `系统托盘{statu}`。该状态决定 `closeEvent` 是隐藏到托盘还是真关闭。 |
| `start_on_boot_controller` | `start_on_boot_controller(self, statu) -> None` | 响应 `settings_bus.is_start_on_boot(bool)`：写入 `self.is_start_on_boot`、调用 `set_start_on_boot(statu)` 落注册表、打印 `自启动{statu}`。 |
| `set_start_on_boot` | `set_start_on_boot(self, enable: bool) -> bool` | 写/删 HKCU Run 键实现开机自启（值名 "MCHelper"；.py 用 `python.exe 脚本` 命令行、.exe 直接路径；详见上文"开机自启动"）。返回 `True`/`False` 表示成败。 |

**接口**：

- **被哪些模块 import**：`main.py`（`from main_window import MainWindow`，程序入口创建唯一实例）。静态方法 `tab_order_config_path_static()` 按注释设计为"供测试等外部代码使用"。（待确认：是否有测试文件直接引用该方法，本次未全仓检索。）
- **对外提供**：
  - 类 `MainWindow`：唯一对外类型，提供完整主窗口能力；依赖的外部协议包括——工具类需提供 classmethod `tool_name()`（`Tools/TOOL_CLASSES` 注册表），工具实例可选提供 `preferred_size`（尺寸自适应）、`can_close()`（关闭许可）、`save_config()`（配置保存）。
  - 无自定义信号（信号出口在 `DraggableTabBar.orderChanged` 与 `settings_bus`，均为外部依赖对象）。
  - 公开静态方法 `tab_order_config_path_static() -> str`（配置路径，测试可用）。
- **依赖的外部组件**：`Tools.TOOL_CLASSES`（工具注册表）、`Tools.tool_Settings.SettingsWindow`（设置对话框）、`CodesUI.MCHelperMainWindow.Ui_MCHelper`（Designer UI）、`Utils.Settings.signals_Settings.settings_bus`（设置变更信号总线，`Signal(bool)` × 2）、`Utils.MainWindow.draggable_tab_bar.DraggableTabBar`（可拖拽 TabBar，拖动结束发射自定义 `orderChanged` 信号）、`winreg`（开机自启注册表）。

**关键变量/常量**：

| 名称 | 类型 | 说明 |
| --- | --- | --- |
| `self.is_system_tray` | `bool` | 是否启用"最小化到托盘"（初始 `False`），由 `settings_bus.is_system_tray` 信号驱动更新；决定 `closeEvent` 中关闭按钮是隐藏窗口还是真退出。 |
| `self.is_start_on_boot` | `bool` | 是否开机自启动（初始 `False`），由 `settings_bus.is_start_on_boot` 信号驱动；变更时同步写/删注册表 Run 项。 |
| `self.is_quitting` | `bool` | 是否正在彻底退出（初始 `False`）；`quit_app`（托盘"关闭程序"）置 `True`，使 `closeEvent` 绕过"隐藏到托盘"分支走正常关闭。 |
| `self._chrome_hint` | `tuple[int, int] \| None` | 最近一次测得的合理窗口装饰开销 (宽, 高) 缓存（初始 `None`）；客户区与页面尺寸差为负（窗口被钳得比页面最小尺寸还小）时用它兜底，避免把窗口 resize 到垃圾尺寸。 |
| `self.tab_bar` | `DraggableTabBar` | 替换后的可拖拽 TabBar 实例；`orderChanged` 信号连接到 `_save_tab_order` 实现拖拽后持久化。 |
| `self.tray_icon` | `QSystemTrayIcon` | 系统托盘图标（`creat_tray_icon` 创建）；`closeEvent` 据其 `isVisible()` 决定是否最小化到托盘。 |
| `self.tabWidget` | `QTabWidget` | 由 `setupUi` 生成的页签容器，是工具加载、顺序保存、自适应、托盘退出保存等所有遍历逻辑的数据源。 |
| `TOOL_CLASSES`（导入常量） | `list[type]` | 来自 `Tools/__init__.py` 的工具类注册表（当前 6 个工具类），`load_tools`/`_order_tool_classes` 的默认顺序来源；新增工具即追加到此列表。 |
| `settings_bus`（导入单例） | `SettingsSignals(QObject)` | 来自 `Utils/Settings/signals_Settings.py` 的模块级信号总线，含 `is_system_tray`、`is_start_on_boot` 两个 `Signal(bool)`；设置页发射、主窗口接收，实现跨窗口配置变更广播。 |
| `tab_order.json`（配置文件） | `list[str]`（JSON） | tab 顺序持久化文件，位于 `QStandardPaths.AppConfigLocation`（回退脚本目录）；内容为按显示顺序排列的工具注册名列表，损坏/缺失时回退注册表默认顺序。 |
| Run 键路径 `Software\Microsoft\Windows\CurrentVersion\Run`（常量） | `str` | `set_start_on_boot` 操作的 HKCU 注册表路径，值名 `"MCHelper"`，值为启动命令行字符串（`REG_SZ`）。 |

# 2. 公共模块（Utils/Public）

# Utils/Public 公共模块文档

> 本文覆盖 `Utils/Public/` 下被 2~4 个工具共用的 7 个公共模块。所有信息均来自源码精读与 grep 引用核对，不含臆测。
> 引用位置标注为 `文件:行号`。

---

## `Utils/Public/notification.py`

**功能**：桌面气泡通知控件。在主屏幕右下角（排除任务栏的 `availableGeometry()` 区域内）弹出深色半透明圆角气泡，无边框、置顶、不抢焦点；多条通知按创建顺序从下往上堆叠（间距 10px，最新的最靠下），每条显示 `duration` 毫秒后以 500ms 淡出动画（`windowOpacity` 1.0→0.0，`OutQuad` 先快后缓）销毁，并在销毁后把剩余通知重新堆叠补位。

实现原理：
1. 窗口属性：`FramelessWindowHint | Tool | WindowStaysOnTopHint` + `WA_TranslucentBackground`（圆角外无矩形底）+ `WA_ShowWithoutActivating`（显示不抢焦点）；
2. 内部用一个 `QFrame` 作深色容器（`rgba(40,40,40,220)`、8px 圆角），标题加粗白字、正文灰字自动换行，字号与内边距通过字符串替换注入 QSS，窗口尺寸随内容 `adjustSize()` 自适应；
3. 实例创建时注册进类级列表 `_instances`，`_adjust_positions()` 以最新通知为基准、按各通知自身高度依次向上偏移排布，并钳制在可用区域顶部内（通知过大也不越出屏幕上沿）；
4. 单次 `QTimer` 计时到点触发 `start_fade_out()`，动画结束回调 `_on_fade_finished()` 从 `_instances` 注销自己、关闭窗口并重排剩余通知。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `NotificationWidget` | `class NotificationWidget(QWidget)` | 通知控件本体；`_instances` 类级列表跟踪全部存活实例（[0] 最旧、[-1] 最新），用于堆叠排布。 |
| `__init__` | `(title, message, duration=3000, title_size=13, message_size=12, padding=(15,12,15,12), parent=None)` | 设置窗口属性 → 构建 QFrame 容器与两个 QLabel（标题/正文）→ 按内容自适应尺寸 → 定位右下角 → 注册实例并堆叠排布 → 启动单次 QTimer（`duration` 毫秒后触发 `start_fade_out`）。 |
| `_move_to_bottom_right` | `()` | 私有。取主屏 `availableGeometry()`，右/下各留 20px 边距定位；通知宽高超可用区时钳制，保证右/下边缘不出屏（顶部超出时回推到可见）。 |
| `_adjust_positions` | `()` | 私有。从最新（`reversed(_instances)`）开始，第 i 新的通知向上偏移 `i*(自身高度+10)`px；所有通知水平对齐取最旧通知的 x；堆叠超过可用区顶部时钳制到顶部。 |
| `start_fade_out` | `()` | 启动淡出：`QPropertyAnimation(self, b"windowOpacity")`，500ms，1.0→0.0，`OutQuad` 缓动，`finished` 接 `_on_fade_finished`。 |
| `_on_fade_finished` | `()` | 私有。从 `_instances` 移除自身并 `close()`；然后以剩余最新通知的 y 为基准重排（逻辑与 `_adjust_positions` 一致，含顶部钳制）。 |
| `Show` | `@staticmethod Show(title, message, duration=3000, title_size=13, message_size=12, padding=(15,12,15,12))` | 快捷入口：创建实例并 `show()`，返回实例引用（便于外部跟踪/主动关闭）。必须在主线程调用，子线程需经信号转发。 |

**接口**：被以下模块 import（`from Utils.Public.notification import NotificationWidget`）：
- `Tools/tool_AutoBackUp.py:13`（备份完成/部分完成、监测进程启动时弹出）；
- `Tools/tool_StrongHoldFinder.py:37`（要塞定位完成弹出，大字号）；
- `Tools/tool_SeedReverser.py:63`；
- `Tools/tool_MapPreviewer.py:65`。

对外只提供 `NotificationWidget` 类与静态方法 `Show()`。

**关键变量/常量**：

| 名称 | 含义 |
|---|---|
| `_instances`（类级） | 当前全部存活通知实例列表，创建顺序排列；驱动多通知堆叠排布与销毁后补位。 |
| `duration` 默认 3000 | 通知停留毫秒数，超时开始淡出。 |
| `title_size=13` / `message_size=12` | 标题/正文字号（px），注入 QSS。 |
| `padding=(15, 12, 15, 12)` | 内容内边距（左,上,右,下）。 |
| 布局常量 | 堆叠间距 10px；右下角边距 20px；淡出时长 500ms；标题与正文间距 4px。 |

---

## `Utils/Public/structure_icons.py`

**功能**：MapPreviewer 系工具的结构件图标解析：把「结构键 + 可选群系 id」映射为英文 Minecraft Wiki EnvSprite 环境精灵（16x16 PNG）的本地文件路径。图标于 2026-09 经浏览器通道批量下载转存，统一放在项目 `assets/Public/` 目录（而非打进资源文件），便于用户按喜好替换图片（多工具共用）。Wiki 原始 URL 模式为 `https://minecraft.wiki/images/EnvSprite_<name>.png`。

村庄图标按生成群系区分外观（对应 `structure_map._check_village` 的五变体判定）：Wiki 无独立「平原村庄」文件名，`plains-village` 是 `new-village` 的重定向，故平原映射到 `new-village`；村庄在草甸（MEADOW）上生成时判定层已归入平原，这里同样映射到平原村庄；雪原针叶林（SNOWY_TAIGA）外观同为雪原，作兜底补充。下界/末地扩展结构（要塞/堡垒遗迹/末地城）也给了精灵名，缺图标时调用方自动回退自绘红圈，不挡功能。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `sprite_key` | `(struct_key: str, biome: int \| None = None) -> str \| None` | 结构键 + 群系 id → EnvSprite 名（不含 `EnvSprite_` 前缀与 `.png` 后缀）。村庄按 `_VILLAGE_BIOME_SPRITE` 取变体，群系未知/不在表内时退回 `"new-village"`；其他结构查 `_STRUCT_SPRITE`，键未知返回 `None`。 |
| `icon_path` | `(struct_key: str, biome: int \| None = None) -> str \| None` | 先 `sprite_key` 取精灵名，再做安全校验（`os.path.basename(sp) == sp`，防路径注入），拼出 `ICON_DIR/EnvSprite_<sp>.png`；文件不存在（被用户删除/替换中）返回 `None`。调用方应回退自绘标记，不能假设返回值恒存在。 |
| `display_name` | `(name_cn: str, struct_key: str, biome: int \| None = None) -> str` | 悬停/标签显示名：村庄且群系可识别时返回 `"群系中文名 + 村庄"`（如"平原村庄"），其余结构原样返回 `name_cn`。 |

**接口**：被以下模块 import：
- `Tools/tool_MapPreviewer.py:66`（`as st_icons`）；
- `Tools/tool_SeedReverser.py:64`（`as struct_icons`）；
- `Tools/tool_StructurePreviewer.py:52`（`as struct_icons`）；
- `Utils/MapPreviewer/choose_structure.py:24`（`as st_icons`，结构选择网格的图标与显示名）。

对外提供三个解析函数与 `ICON_DIR` 常量。

**关键变量/常量**：

| 名称 | 含义 |
|---|---|
| `ICON_DIR` | `<项目根>/assets/Public`（由 `__file__` 向上三级推算），多工具共用图标目录。 |
| `PLAINS=1, DESERT=2, TAIGA=5, SNOWY_PLAINS=12, SNOWY_TAIGA=30, SAVANNA=35, MEADOW=177` | cubiomes `biomes.h` 群系 id 常量（与 structure_map 同源），仅为村庄变体映射引入所需几项，避免整套结构判定模块。 |
| `_STRUCT_SPRITE` | 22 项：结构键 → EnvSprite 名。注意 Wiki 上丛林神殿/沙漠神殿的精灵名带 `pyramid`（`jungle-pyramid`/`desert-pyramid`）；下界/末地扩展：`nether_fortress→fortress`、`bastion_remnant→bastion-remnant`、`end_city→end-city`。 |
| `_VILLAGE_BIOME_SPRITE` | 7 项：群系 id → 村庄变体精灵名（PLAINS/MEADOW→new-village、DESERT→desert-village、SAVANNA→savanna-village、TAIGA→taiga-village、SNOWY_PLAINS/SNOWY_TAIGA→snowy-village）。 |
| `_VILLAGE_BIOME_CN` | 7 项：群系 id → 村庄悬停用群系中文短名（MEADOW 归"平原"、SNOWY_TAIGA 归"雪原"），供 `display_name` 拼"群系名+村庄"。 |

---

## `Utils/Public/biome_names.py`

**功能**：群系名称映射表，最初为 SeedReverser 世界种子精化面板而建，后被多个工具共用。数据准则：id 以 cubiomes `biomes.h` 的 BiomeID 枚举为唯一权威（1.18~1.21+）；中文译名以 54 项权威对照表为准（与中文 Wiki 对齐，如 温水深海/积雪沙滩/积雪针叶林）；自然生成清单以 cubiomes `biomes.c` 的 `isOverworld(mc>=1.18)` 为准，并与 20 万点 BiomeSampler 采样实测（54 个 id）完全一致。

四个用途：
1. **UI 下拉/补全**：`BIOME_CHOICES`，仅收录 1.18+ 自然生成的 54 个主世界群系；
2. **名称解析**：`resolve_biome(label) -> biome_id | None`，支持中文 F3 名 / cubiomes 枚举名（下划线式或驼峰式）/ 下拉标签全文 / 1.18 改名前旧名，大小写与分隔符（空格/下划线/连字符）不敏感；
3. **观测列表显示**：`biome_label(id) -> 标签`（含下界/末地群系）；
4. **图标**：`icon_path(key) -> assets/Public/<key>.png`（中文 Wiki BiomeSprite 转存 PNG，仅下拉 54 项配图）。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_norm` | `(s: str) -> str` | 私有。名称归一化：小写并剔除空格/下划线/连字符，使 `Snowy Taiga`、`snowy_taiga`、`snowy-taiga` 等价。 |
| `resolve_biome` | `(label: str) -> int \| None` | 用户输入 → biome id。三级解析：① 与 `BIOME_CHOICES` 下拉标签全文精确匹配（"海洋 ocean"）；② 中文 F3 名查 `_F3_CN_TO_KEY`（权威对照 → 下拉标签前缀 → 旧译名，`setdefault` 合成、后者不覆盖前者）；③ 英文枚举名经 `_norm` 后查 `_KEY_TO_ID`。全部失败返回 `None`。 |
| `biome_label` | `(bid: int) -> str` | biome id → 显示标签。优先查 `_EXTRA_DIM_BIOMES`（下界/末地 10 项），再反查 `BIOME_CHOICES`（54 项下拉标签），再反查 `_BIOME_IDS`（返回第一个匹配的英文键），都没有返回 `"id=N"`。 |
| `icon_path` | `(key: str) -> str \| None` | 内部键 → 图标绝对路径 `ICON_DIR/<key>.png`；键含路径分隔符（basename 校验失败）或文件缺失返回 `None`。 |

**接口**：被以下模块 import：
- `Tools/tool_SeedReverser.py:68`（`BIOME_CHOICES`、`biome_label`、`icon_path`、`resolve_biome`）；
- `Tools/tool_MapPreviewer.py:70`（整模块 `biome_names`）；
- `Tools/tool_StructurePreviewer.py:57`（`biome_label`）；
- `Utils/MapPreviewer/biome_colors.py:152`（`BIOME_CHOICES`、`resolve_biome`，函数内延迟导入）。

**关键变量/常量**：

| 名称 | 含义 |
|---|---|
| `BIOME_CHOICES` | 54 项 `(显示标签, 内部键)` 列表 = 1.18+ 主世界自然生成全集；标签格式 `"中文 Wiki 译名 + F3 英文原名"`（如 `"平原 plains"`），注释标注对应 biome id。含 26.2 新增的 `sulfur_caves`（187，MCHelper 自定 id）。 |
| `_BIOME_IDS` | 内部键/历史别名 → biome id。主表 0~50 含大量 1.18 改名前旧名与旧驼峰名（如 `mountains→3`、`swampland→6`、`mesa→37`）；128+ 变种与 1.14+ 新增一并收录（`deep_warm_ocean→47` 已随 21w43a 移除、`desert_hills` 等在 1.18+ 不再生成，仅保留旧名解析兜底）。 |
| `CN_NAME_TO_KEY` | 54 项中文官方名 → 内部键（与下拉标签一一对应；新增/修正群系时需同步维护 `BIOME_CHOICES` 与本表）。 |
| `_LEGACY_CN_TO_KEY` | 7 项旧版译名兜底（"积雪的沙滩"、"疏林山地"、"蘑菇岛岸" 等），仅输入解析用，不覆盖权威对照。 |
| `_F3_CN_TO_KEY` | 三层汇总表：`CN_NAME_TO_KEY` → 下拉标签首段 → 旧译名，用 `setdefault` 合成保证优先级。 |
| `_KEY_TO_ID` | `_BIOME_IDS` 的 `_norm` 归一化版本（运行时生成）。 |
| `_EXTRA_DIM_BIOMES` | 下界 5 项 + 末地 5 项的显示标签（id 8/9/40~43/170~173），不进下拉，仅供 `biome_label` 展示 MapPreviewer / StructurePreviewer 的下界与末地标注。 |
| `ICON_DIR` | `<项目根>/assets/Public`，与 structure_icons 的图标目录一致。 |

---

## `Utils/Public/structure_params.py`

**功能**：结构参数总表，全项目结构计算的单一数据源。数据逐条核对自 cubiomes `finders.c` 的 `getStructureConfig()`（master 分支，salt / regionSize / chunkRange 与 `s_xxx` 结构常量完全一致）。供 SeedReverser（逆推）、MapPreviewer（地图标注枚举）、StructurePreviewer（结构预览）三个工具读取结构定位所需的全部静态参数。

只支持 1.18~1.21+ 参数线（用户明确指示）。`mansion`（林地府邸）参数保留供 MapPreviewer 地图标注使用，但 SeedReverser 逆推 UI 已下架该结构（锚点定位误差过大，无计算价值），`_VERSION_STRUCTS` 各版本均不收录。

**`STRUCT_PARAMS` 六元组各位置含义**（索引顺序即 `get_params` 解包顺序）：

| 位置 | 字段 | 含义 |
|---|---|---|
| `[0]` | `salt` | 结构盐。参与区域种子：`regionSeed = structureSeed + regX*341873128712 + regZ*132897987541 + salt`。非区域制结构（要塞/矿井）占 0。 |
| `[1]` | `region_size` | 区域边长（区块单位）：每个区域内至多尝试一次生成，区块偏移 `offX ∈ [0, region_size)`。 |
| `[2]` | `chunk_range` | 区块偏移上界（Java `spacing - separation`）：线性散布结构 `offX = nextInt(chunk_range)`。 |
| `[3]` | `scatter` | 散布方式：`"linear"`（线性，2 次 nextInt）或 `"triangle"`（三角，4 次 nextInt 取两次平均）。 |
| `[4]` | `min_ver` | 该结构可用的最低版本（主版本号 int：103=1.3、116=1.16、121=1.21 等），用于版本可用性过滤。 |
| `[5]` | `lift_mod` | 可参与低位 lifting 预筛的最大 2 幂模数（`chunk_range` 的最大 2 幂因子：r=24→8、r=20/12→4、r=26/22→2）。该模数 m 下「val mod m」精确等于「(state>>17) mod m」，只取决于结构种低 (17+log2 m) 位；0 = 不可预筛（三角散布 / 2 幂 r / 概率结构 / 奇数 r）。 |

`lift_mod=0` 的四类原因（源码注释逐条给出）：`pillager_outpost` 有 1/5 概率门；`monument` r=27 奇数且三角散布；`mansion` r=60 虽为 4 的倍数但三角散布两次 nextInt 相加后 `>>1` 的低位进位依赖高位，破坏低位同余；`ancient_city` r=16 是 2 的幂，`next(31)` 取的是状态高 31 位、偏移由高位决定，与低位枚举无关；`ruined_portal` r=25 为奇数，2^17 全枚举出 98303 个反例（预筛会漏真种子），只能作验证观测。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `get_params` | `(struct_key: str, version_key: str) -> dict` | 解包 `STRUCT_PARAMS[struct_key]` 六元组，返回 `{key, name, salt, region_size, chunk_range, scatter, min_ver, lift_mod, version}`；name 取 `STRUCT_NAMES`（缺省回退键名）。 |
| `available_structures` | `(version_key: str) -> tuple[str, ...]` | 指定版本可用（可逆推）的结构键元组：按 `_VERSION_STRUCTS[version_key]` 顺序（UI 易找程度），再过滤 `STRUCT_PARAMS[k][4] <= 版本号`（min_ver 过滤）。未知版本键回退 121。 |
| `get_default_tolerance` | `(struct_key: str) -> int` | 结构键 → 默认站位容差（区块，0~2）；未知键兜底 0。 |
| `is_reversible` | `(struct_key: str) -> bool` | 是否可参与低位预筛逆推：`linear` 且 `lift_mod >= 2`。与求解器 `_lift_split` 的分组语义严格一致；False = 仅验证观测（层 3 过滤假阳性，不参与层 1/2 预筛与进度条统计）。 |
| `struct_key_to_name` | `(struct_key: str) -> str` | 结构键 → 中文名（`STRUCT_NAMES` 查表，缺省原样返回）。 |

**接口**：被以下模块 import：
- `Tools/tool_SeedReverser.py:67`；
- `Tools/tool_MapPreviewer.py:70`（整模块）与 `:72`（`DIMENSION_NAMES`、`STRUCT_NAMES`）；
- `Tools/tool_StructurePreviewer.py:55`；
- `Utils/MapPreviewer/choose_structure.py:25`（`DIMENSION_NAMES`、`STRUCT_DIMENSION`、`STRUCT_NAMES`）；
- `Utils/SeedReverser/structure_math.py:65`（逆推求解读参数）；
- `Utils/Public/structure_map.py:51`（地图枚举读参数）。

**关键变量/常量**：

| 名称 | 含义 |
|---|---|
| `VERSION_KEYS` | `("26.2", "1.21.11", "1.21")`，与 UI versionCombo 对应，按新到旧排序。26.2 结构与 1.21 完全一致（数据包 101.2 仅新增硫磺洞穴群系），1.21.11 是 1.21.x 线修正版。 |
| `_VERSION_NUM` | 版本键 → 主版本号 int：`{"1.21": 121, "1.21.11": 1211, "26.2": 262}`，用于 min_ver 过滤。 |
| `_STRUCTS_121` / `_VERSION_STRUCTS` | 各版本可逆推结构元组（10 项：shipwreck、desert_pyramid、igloo、swamp_hut、jungle_temple、village、ocean_ruin、monument、trial_chambers、ruined_portal），三个版本共用同一元组。 |
| `STRUCT_NAMES` | 22 项结构键 → 中文名。除可逆推 10 项外，还收录 MapPreviewer 扩展：`stronghold` 要塞、`buried_treasure` 埋藏的宝藏、`mineshaft` 废弃矿井、`desert_well` 沙漠水井、`nether_fortress` 下界要塞、`bastion_remnant` 堡垒遗迹、`end_city` 末地城，以及不可逆推但可正向标注的 `pillager_outpost`、`mansion`、`ancient_city`、`trail_ruins`。 |
| `STRUCT_PARAMS` | 22 项：结构键 → 上述六元组（含义见表）。特殊条目：`stronghold`/`mineshaft` 非区域制（salt/region/chunk_range 占 0）；`buried_treasure` salt=10387320、region=1、概率 1% nextFloat；`desert_well` salt=40002、概率 0.001、基于 `getPopulationSeed + xNextIntJ(16)`；`nether_fortress` 与 `bastion_remnant` 共用 salt=30084232、r=27/23；`end_city` triangle 散布 + pos²≥1008² 距离门。 |
| `DEFAULT_TOLERANCES` | 各结构默认站位容差（区块，0~2），依据锚点可辨认程度：小型单模板结构（沉船/神殿/雪屋等）=0 保留全部信息量；大型/无中心/深埋结构（村庄/试炼密室/神殿类/下界末地扩展）=2 提高生存可用性；要塞=1、矿井=1（仅完整性，不进逆推 UI）。 |
| `STRUCT_DIMENSION` | 结构键 → 所在维度：仅 3 项（`nether_fortress`/`bastion_remnant`→"nether"、`end_city`→"end"），MapPreviewer 维度分组与标注路由用；未列出的键一律视为主世界。 |
| `DIMENSION_NAMES` | `{"overworld": "主世界", "nether": "下界", "end": "末地"}`，worldCombo 与选择窗分组标题用。 |

---

## `Utils/Public/biome_signature_colors.py`

**功能**：群系标志色表——下拉框选中某群系后，行编辑器内的群系名文字染成该群系的标志色。颜色抓取自中文 Minecraft Wiki（zh.minecraft.wiki）各群系页面信息框（2026-09-19 抓取，Java 版数值）。

取色规则：
- 陆地群系取「草地颜色」；
- 海洋/河流类群系（11 项）草地色无区分度，改取「水体颜色」（JE 值）；
- 沼泽 / 红树林沼泽草色按噪声分两档，取信息框主档（噪声值不小于 -0.1），两者同为 `#6A7039`；
- 下界群系草色在 Wiki 上为统一值 `#BFB755`、末地群系统一为 `#8EB971`，照录（供 MapPreviewer 下界/末地维度下拉）。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `color_for_label` | `(label: str) -> str \| None` | 下拉标签（`"中文 内部键"`）→ 标志色。取 `label.strip().rsplit(" ", 1)[-1]` 末段作为查表键（标签 = 中文 + 空格 + 英文键，两者均不含空格），兼容直接传内部键；空串/未知项（如「选择群系」占位、手输未匹配文本）返回 `None`，由调用方恢复默认文字色。 |

**接口**：被以下模块 import（`from Utils.Public.biome_signature_colors import color_for_label`）：
- `Tools/tool_SeedReverser.py:74`；
- `Tools/tool_MapPreviewer.py:71`。

**关键变量/常量**：

| 名称 | 含义 |
|---|---|
| `_WATER_KEY_COLORS` | 11 项海洋/河流类：键 = `BIOME_CHOICES` 内部键，值 = 水体颜色（JE）。如 ocean/deep_ocean/river → `#3F76E4`、warm_ocean → `#43D5EE`、frozen_ocean/deep_frozen_ocean/frozen_river → `#3938C9`。 |
| `BIOME_SIGNATURE_COLORS` | 全量标志色表（`#RRGGBB` 字符串）：用 `**_WATER_KEY_COLORS` 合并水体色后，追加主世界陆地 44 项（按平原类/干旱类/森林类/湿地岸滩类/山地类/洞穴类分组注释）+ 下界 5 项（统一 `#BFB755`）+ 末地 5 项（统一 `#8EB971`）。键 = `BIOME_CHOICES` / `_EXTRA_DIM_BIOMES` 的内部键；未收录键由 `color_for_label` 返回 `None`。 |

---

## `Utils/Public/stronghold_math.py`

**功能**：StrongHoldFinder 的纯计算模块（无任何 Qt/IO 依赖）：F3+C 命令解析 + 两条视线的水平求交点，即末影之眼三角定位法。

背景与数学原理：
- 末影之眼被抛出后朝最近的要塞方向飞行；玩家在两个不同位置分别把准星对准末影之眼飞走方向按 F3+C，会复制出 `/execute in minecraft:overworld run tp @s x y z yaw pitch` 形式的传送命令；
- 每条视线由「位置 + yaw」确定，参数方程 `(x, z) + t * (-sin(yaw), cos(yaw))`（t>0 为视线前方）；
- Minecraft 的 yaw 角度系与数学课本不同：0°=南(+Z)、90°=西(-X)、180°=北(-Z)、270°=东(+X)，因此水平面 (XZ) 上的视线方向向量为 `(-sin(yaw), cos(yaw))`；
- 两条视线的水平交点即要塞的水平位置。

**计算流程（`intersect_rays`）**：
1. 两 yaw 各经 `yaw_to_direction` 转单位方向向量 d1=(dx1,dz1)、d2=(dx2,dz2)；
2. 计算二维叉积 `cross = dx1*dz2 - dz1*dx2`（= sin(两视线夹角)）；`|cross| < 1e-6`（约 0.00006°）视为几乎平行，抛 `ValueError` 拦截「几乎原样复制两遍」的输入；
3. 两观测点水平间距 `hypot(x2-x1, z2-z1) < 0.5` 视为同一位置，无法三角定位，抛 `ValueError`；
4. 解 t1：由 `t1 * (d1×d2) = (P2-P1)×d2` 得 `t1 = (ex*dz2 - ez*dx2) / cross`（ex=x2-x1, ez=z2-z1）；
5. 回代求交点 `(ix, iz) = (x1 + t1*dx1, z1 + t1*dz1)`；
6. 交点在第二条视线上的有向参数 `t2 = (ix-x2)*dx2 + (iz-z2)*dz2`（单位方向向量点乘即距离）；
7. 返回 `{x, z, t1, t2, dist1, dist2}`：t1/t2 为有向参数（>0 在视线前方，<0 在背后，数值≈交点到该观测点的距离），dist1/dist2 = |t1|、|t2|。

**F3+C 解析流程（`_parse_f3c_numbers` → `parse_f3c_command*`）**：不依赖命令前缀完整格式（新旧版本前缀不同），而是用 `_NUMBER_RE` 抓取文本中全部带符号十进制数、取最后 5 个，按 F3+C 固定顺序解释为 x y z yaw pitch——因此同时兼容标准命令、旧版 /tp 命令与手打纯数字。数字不足 5 个或文本为空抛 `ValueError`（带示例提示）。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_parse_f3c_numbers` | `(text: str) -> tuple[float, float, float, float, float]` | 私有。抓取文本全部数字取最后 5 个 → (x, y, z, yaw, pitch)；空文本/数字不足 5 个抛 `ValueError`。 |
| `parse_f3c_command` | `(text: str) -> tuple[float, float, float]` | 解析出 (x, z, yaw)：水平坐标与水平视角（度，未规范化）。 |
| `parse_f3c_command_full` | `(text: str) -> tuple[float, float, float, float]` | 同上但额外保留 y，供生成传送命令时使用，返回 (x, y, z, yaw)。 |
| `looks_like_f3c` | `(text: str) -> bool` | 剪贴板预判门槛：① 以 `_F3C_PREFIX_RE` 前缀开头（`/execute in minecraft:overworld run tp @s`，允许省略开头斜杠与首尾空白）；② 前缀后至少 5 个数字；③ 文本长度 ≤200（F3+C 命令约 90 字符）。其他维度（the_nether/the_end）的 F3+C 不被识别——末影之眼在这些维度不朝要塞飞。 |
| `yaw_to_direction` | `(yaw: float) -> tuple[float, float]` | yaw → XZ 单位方向向量 (dx, dz) = (-sin(yaw), cos(yaw))。 |
| `normalize_yaw` | `(yaw: float) -> float` | yaw 规范到 [-180, 180)，仅用于展示（`math.fmod` 后按区间平移）。 |
| `yaw_to_compass` | `(yaw: float) -> str` | yaw → 八方位名：`round(规范化 yaw / 45)` 映射到 `_COMPASS` 索引（加 8 取模防负），返回 南/西南/西/西北/北/东北/东/东南 之一。 |
| `intersect_rays` | `(x1, z1, yaw1, x2, z2, yaw2) -> dict` | 两条视线求交（流程见上文**计算流程**），返回 `{x, z, t1, t2, dist1, dist2}`；平行或同位抛 `ValueError`。 |

**接口**：被以下模块 import：
- `Tools/tool_StrongHoldFinder.py:38`（`looks_like_f3c`、`parse_f3c_command`、`parse_f3c_command_full`、`intersect_rays`、`normalize_yaw`、`yaw_to_compass`——核心定位全流程）；
- `Tools/tool_SeedReverser.py:76`（`looks_like_f3c`、`parse_f3c_command`、`parse_f3c_command_full`——世界种子精化面板的 F3+C 观测录入复用同一解析）。

**关键变量/常量**：

| 名称 | 含义 |
|---|---|
| `_NUMBER_RE` | `[-+]?(?:\d+\.?\d*|\.\d+)`：匹配带可选正负号的十进制数（F3+C 不产生科学计数法，正则顺带兼容）。 |
| `_F3C_PREFIX_RE` | `^\s*/?execute in minecraft:overworld run tp @s\b`：F3+C 命令必然出现的完整前缀（定位场景维度恒为 overworld）。 |
| `_PARALLEL_CROSS_EPS = 1e-6` | 两视线单位向量叉积（= sin 夹角）小于该值视为平行，对应夹角约 0.00006°，只拦截「几乎原样复制两遍」的情况。 |
| `_SAME_POSITION_EPS = 0.5` | 两观测点水平间距小于该值（格）视为同一位置，无法三角定位。 |
| `_COMPASS` | 八方位元组 `("南","西南","西","西北","北","东北","东","东南")`，索引 = round(规范化 yaw/45) 映射 0~7。 |

---

## `Utils/Public/structure_map.py`

**功能**：MapPreviewer 的结构定位与群系校验核心——给定世界种子与视野（方块坐标矩形），枚举视野内「真实生成」的全部结构。结构位置计算复用 `Utils/SeedReverser/structure_math` 的 `get_structure_pos`（cubiomes 精确复刻，已与 SeedCrackerX 对拍）；群系校验按 cubiomes `finders.c` 的 `isViableStructurePos` 1.18+ 分支逐行移植（文件内注释标注 finders.c 源码行号）。仅支持 1.18~1.21 主世界结构 + 下界/末地扩展（用户明确指示的工具范围）。

与游戏一致的关键语义（模块 docstring 明示）：
- 1.18+ 所有结构校验都走 1:4 噪声格直接采样（scale=0/4，无 Voronoi 抖动），可用 `biome_noise.BiomeSampler` 直接采样；
- `getVariant` 采样点公式 `(chunkX*32 + 2*sv.x + sv.sx-1) / 2 >> 2` 中的 `/ 2` 是 **C 整数除法（向零截断）**，对负数与算术移位不同，必须用 `_c_div`；
- `chunkGenerateRnd` 需要 Java `Random.nextLong`（两次 next(32) 拼接，第二次须符号扩展），见 `_java_next_long`；
- 前哨站 `setAttemptSeed` 的异或值 < 2^21，不影响 48 位以上状态，故用 48 位结构种与用 64 位世界种子等价。

三大扩展（本文件内移植，非 structure_math 区域制）：
- **下界/末地**：下界要塞/堡垒遗迹/末地城为区域制（散布公式与主世界一致），但概率门/群系校验按 finders.c 的 `DIM_NETHER`/`DIM_END` 分支移植；群系采样用 `Utils/MapPreviewer/nether_end_sampler`（NetherSampler 逐点 / EndSampler chunk 级），主世界 BiomeSampler 不可混用；
- **特殊算法结构**：埋藏的宝藏/沙漠水井/废弃矿井为 `getStructurePos` 特殊分支与 `getMineshafts` 的逐行移植（含上游 rng.h 的 `xNextLongJ`/`xNextFloat`/`xNextIntJ` 语义，本地 cubiomes 裁剪未含 rng.h，故在 Xoroshiro 上自行实现）；
- **要塞**：`StrongholdIter` 环形序列（`initFirstStronghold`/`nextStronghold`）+ locateBiome 1.18+ 分支。窗口批量采样走 Python 带链逐点采样（MC-241546：`climateToBiome` 共享 dat 链，候选分歧时窗口边缘个别格的群系 id 与无链采样不同，对拍 probe 已复现，故 native sample_map 禁用）；1.18/1.19（btree19 = 1.19.2 线）的 locateBiome 消耗共享 rnds 流，必须按序全扫 128 窗、不可跳窗。

### 核心计算流程

#### ① `enumerate_structures` 主流程（区域制枚举：世界种子 → 区域盐值 → 区域种子 → 块坐标 → 边界判定）

1. `ws = seed & (2^64 - 1)`：世界种子归一为 64 位无符号（有符号 int64 输入均可）。
2. `struct_keys` 为 None 时取 `available_structures(version_key, dimension)`；非主世界时再按 `STRUCT_DIMENSION` 做维度防御过滤。
3. 采样器准备：下界 → `NetherSampler(ws)`；末地 → `EndSampler(ws)`；主世界 → `BiomeSampler(seed, version_key)`（下界/末地专用采样器惰性创建复用，主世界不建 NetherSampler/EndSampler，省开销）。
4. **特殊结构分流**（遍历 struct_keys）：
   - `stronghold` → `_enum_strongholds`（StrongholdIter 环形序列，不走区域制）；
   - `mineshaft` → `_enum_mineshafts`（getMineshafts 逐 chunk 概率枚举）；
   - `buried_treasure` / `desert_well` → `_enum_treasure_well`（逐 chunk 概率枚举，region=1）；
   - 其余进 `region_keys`，进入区域制循环。
5. **区域制循环**（每个结构键独立执行，进度回调按结构粒度）：
   a. 读参数：`rs = region_size * 16`（区域跨度，方块）；
   b. 计算覆盖视野的区域范围：`reg_x0 = min_bx // rs - 1` … `reg_z1 = max_bz // rs + 1`（多取一圈容错边缘）；
   c. `s48 = ws & (2^48 - 1)`（48 位结构种）；
   d. 逐区域 `(reg_z, reg_x)` 调 `get_structure_pos(key, s48, reg_x, reg_z, version_key)` 得锚点方块坐标 `(bx, bz)`。其内部 RNG 消耗顺序（structure_math/mc_random 已确认）：
      - **区域种子**：`v = structure_seed + regX*341873128712 + regZ*132897987541 + salt`（mod 2^64），再 `setSeed` 语义 `(v ^ 0x5DEECE66D) & (2^48-1)`——纯算术，不消耗随机数；
      - **linear 散布**：`struct_next_int(state, chunk_range)` × 2 → offX、offZ（cubiomes 内联 nextInt 语义，无拒绝采样）；
      - **triangle 散布**（monument/mansion/end_city）：`struct_next_int(state, r)` × 4 → `(a1+a2)>>1, (b1+b2)>>1`；
      - **块坐标**：`(regX * region_size + offX) << 4, (regZ * region_size + offZ) << 4`（结构西北角）。
   e. **边界判定**：锚点须在 `[min-96, max+96]` 视野外扩 96 方块内（容错大型结构包围盒），否则跳过；
   f. **群系校验**：`check_structure_at(...)`（内部 RNG 消耗见 ②），viable 才记录；
   g. 记录 `{struct, name, x, z, cx, cz, biome}`（x/z 锚点方块坐标，cx/cz 区块坐标，biome 判定采样点群系 id，未采样为 -1）。

#### ② `chunk_generate_rnd`（cubiomes `chunkGenerateRnd`，finders.h L390 复刻）

用途：取「该区块生成期随机流」的初始 48 位 LCG 状态（内部已 `setSeed(rnd, rnd)`），可直接供 `nextInt` 系列使用。变体判定（村庄/堡垒/jigsaw 结构）与前哨站选角都从它出发。流程：
1. `state = set_seed(ws)`（ws 必须是完整 64 位：乘法/异或依赖完整宽度）；
2. `a, state = _java_next_long(state)`——Java `Random.nextLong`：两次 `next(32)` 拼接 `((long)next(32) << 32) + next(32)`，**第二次必须符号扩展**（负 lo 使高 32 位 -1），共消耗 2 次 LCG 迭代；
3. `b, state = _java_next_long(state)`——再 2 次迭代；
4. `rnd = ((a * cx) ^ (b * cz) ^ ws) & (2^64-1)`（cx/cz 为区块坐标，64 位域乘法/异或）；
5. 返回 `set_seed(rnd)`（异或混淆后取 48 位状态）。

#### ③ 各 `_check_*` 结构判定函数的 RNG 消耗顺序

- `_check_feature`（shipwreck/desert_pyramid/igloo/swamp_hut/jungle_temple/ocean_ruin/trail_ruins/buried_treasure）：无 RNG；单点采样 `(chunkX*4+2, 319>>2, chunkZ*4+2)` ∈ `_FEATURE_WHITELIST[key]`（finders.c L1541-1558 的 L_feature）。
- `_check_mansion`：无 RNG；单点 `(chunkX*16+7, 319>>2) >> 2` ∈ {DARK_FOREST, DARK_FOREST_HILLS}（L1745-1756）。
- `_check_village`（L1613-1632）：按 PLAINS → DESERT → SAVANNA → TAIGA → SNOWY_PLAINS 顺序对 5 个变体逐一检查，命中即返回；每个变体消耗：`_village_variant` = `chunk_generate_rnd`（4 次 next(32)）+ `nextInt(4)`（rotation）+ `nextInt(表模数)`（t，如平原 204），随后查 `_VILLAGE_TABLES` 阈值尺寸表（不消耗 RNG），按 rotation 平移得 (vx, vz, vsx, vsz)；再经 `_variant_sample_point` 得噪声格（`_c_div` 截断除法），采样点群系 `== vbiome`、或（MEADOW 且变体为 PLAINS）即 viable。
- `_check_outpost`（L1634-1696）：三步：
  1. **概率门**：`s = world_seed ^ (chunkX>>4) ^ ((chunkZ>>4)<<4)`（setAttemptSeed，异或值 < 2^21 与 48 位语义等价）→ `set_seed(s)` → `next(31)`（1 次 LCG 迭代）→ `nextInt(5) == 0`，失败直接 False；
  2. **附近村庄检查**：10 区块范围内逐区域调 `get_structure_pos("village", ...)`（确定性计算，不消耗运行时 RNG），存在村庄锚点 → False（1.16.1+ 前哨站不与村庄同区域）；
  3. **角落采样**：`chunk_generate_rnd`（4 次 next(32)）+ `nextInt(4)` 选角 → `(chunkX*32±15)/2 >> 2`（C 截断除法）噪声格采样 ∈ `_OUTPOST_BIOMES`（12 种）。
- `_check_monument`（L1699-1731）：无 RNG。两阶段：① 中心单点 `(chunkX*16+8, 36>>2, chunkZ*16+8)` 须为 5 种深海之一；② `areBiomesViable(rad=29)`：先查 (x±29)>>2 方格四角（快速拒绝陆地/浅海），再全格遍历均须 ∈ `_MONUMENT_BIOMES`（12 种海洋/河流，y=(63-29)>>2=8）。
- `_check_jigsaw`（ancient_city / trial_chambers，L1770-1787）：消耗 = `_jigsaw_variant`（见下）+ 变体采样点 `biome_at(nx, y>>2, nz)`；ancient_city 须 `== DEEP_DARK`，trial_chambers 须 `!= DEEP_DARK`（非深暗之域的主世界群系）。
- `_check_desert_well`（L1560-1577）：无 RNG；锚点 `(bx>>2, 319>>2, bz>>2) == DESERT`。
- `ruined_portal`：恒 `(True, -1)`——finders.c L1208-1210 该结构 biome 判定恒 true（任意群系含地下），无额外 RNG 概率门。
- `stronghold` / `mineshaft`：恒 `(True, -1)`——getStructurePos/专用枚举已含概率门与环形序列；Mineshaft 的 isViableStructurePos 恒 viable（L1789-1790）。
- `_check_nether`（下界，L1449-1486）：① `nether_fortress`：先查堡垒概率门（`_bastion_probability`：`chunk_generate_rnd(bx>>4, bz>>4)` + `nextInt(5) >= 2`，4+1 次消耗）——门过则再做 `_bastion_variant`（再 `nextInt(4)`×2）+ 变体采样点群系 ∈ `_NETHER_BASTION_BIOMES`（4 种，不含玄武岩三角洲）→ 堡垒 viable 即要塞 **不** viable；门败/采样点不在白名单 → 要塞 viable（展示群系取 chunk 中心 `cx*4+2`）。② `bastion_remnant`：概率门失败 → False；门过 → `_bastion_variant`（`nextInt(4)` rotation + `nextInt(4)` start，查 `_BASTION_TABLES` 4 种起点尺寸）+ 采样点白名单。
- `_check_end`（末地城，L247-249 + L1488-1505）：无 RNG；距离门 `bx² + bz² >= 1008²`（方块坐标）→ chunk 级 `biome_at_chunk(bx>>4, bz>>4)`（scale=16）∈ {end_midlands, end_highlands}。

#### ④ 变体判定函数

- `_village_variant(world_seed, chunk_x, chunk_z, biome_id)`：getVariant(Village)（L2003-2117）。RNG：`chunk_generate_rnd` → `nextInt(4)`（rotation）→ `nextInt(_VILLAGE_TABLE_MOD[biome])`（t）。按 `_VILLAGE_TABLES[biome]` 阈值表（`(t上限, sx, sz)` 递增序列）取未旋转尺寸；rotation 1/2/3 分别作 (1-sz,0)/(1-sx,1-sz)/(0,1-sx) 平移并交换 sx/sz。群系不在 5 变体表返回 None（meadow 调用侧按 plains 传入）。
- `_bastion_variant(world_seed, chunk_x, chunk_z)`：getVariant(Bastion)（L2079-2106）。RNG：`chunk_generate_rnd` → `nextInt(4)`（rotation）→ `nextInt(4)`（start：0=air_base 46x46 / 1=hoglin_stable 30x48 / 2=treasure 38x38 / 3=bridge 16x32）。旋转平移与 Village 同式（1.18+ 无符号平移语义，无 1.16.1 的 start/rotation 交换）。
- `_jigsaw_variant(struct_key, world_seed, bx, bz)`：getVariant(Ancient City / Trial Chambers)（L2119-2141 / L2315-2328）。RNG 入口 `chunk_generate_rnd(bx>>4, bz>>4)`（bx/bz 为 getFeaturePos 返回的锚点，恒 16 的倍数）：
  - **ancient_city**：`nextInt(4)`（rotation）→ `nextInt(3)`（city_center_1..3，不影响包围盒，纯占位消耗）→ 用锚点坐标严格符号修入平移（`-(x>0)`/`+(x<0)` 等，尺寸 18x41 或 41x18）→ city_anchor (13, *, 20) 位移得 (vx, vz)；y = -27（供 `sampleY = y >> 2`）。
  - **trial_chambers**：`nextInt(21) - 40` 得 y（-40~-20）→ `nextInt(4)`（rotation）→ `nextInt(2)`（start 占位）→ 尺寸 19x19 按 rotation 平移。

#### ⑤ `StrongholdIter` 要塞环形序列（finders.c L834-936 移植）

1. **`__init__`（initFirstStronghold，L840-849）**：`s48 = ws & (2^48-1)` → `set_seed(s48)` → `next_double` 得 `angle = 2π*d1` → `next_double` 得 `dist = 128 + (d2-0.5)*80`；`nextapprox = (_c_round(cos(angle)*dist)*16+8, _c_round(sin(angle)*dist)*16+8)`；初始 `ringmax=3`（首环 3 个）。注意 `_c_round` 为 C `round()` 半值远离零语义（Python round 是银行家舍入）。
2. **`next()`（nextStronghold，L868-936）**，每调用产生一个环位：
   - 环位定位分版本：**1.19.3+ 快路径**（本工具版本键 26.2/1.21.11/1.21 恒走此路）——只消耗一次 `_java_next_long`（2 次 next(32)），`pos = approx` 不做群系采样（Java 1.19.3 起群系校验移到 piece 生成期，cubiomes 走 NULL 快路径）；**1.18/1.19 共享流线**——`_locate_biome` 全窗口扫描：以 approx 为中心取 112 块半径窗（噪声格 r=112>>2=28），`_StrongholdWinSampler.window_ids` 批量取 (2r+1)² 群系矩阵，水库采样（首个非排除格直接选中、之后每个候选格 `nextInt(found+1)==0` 才替换），消耗共享 `_rnds` 流，候选消耗依赖窗口内容故不可跳窗；
   - `pos = ((px & ~15) + 4, (pz & ~15) + 4)` 对齐 16 格；
   - 推进：`ringidx += 1`，`angle += 2π/ringmax`；环满时 `ringnum += 1`、`ringmax += 2*ringmax//(ringnum+1)`（上限 128-index）、`angle += next_double()*2π`；
   - 距离更新：`dist = 128 + 192*ringnum + (next_double()-0.5)*80`（1.9+ 公式，每步 1 次 nextDouble，环满时共 2 次）；
   - 新 `nextapprox` 同 init 公式；`index >= 128` 返回 False。
3. 排除集合 `_stronghold_valid_sets()`：isStrongholdBiome（L798-832）——1.18+ 采样器只产主世界 id，故取「排除集合」= 全部海洋系 + 河/滩/石岸 + 红树/深暗/苍白之园/硫磺洞穴；validB/validM 两集合同语义。

### 类与函数

| 名称 | 签名 | 说明 |
|---|---|---|
| `available_structures` | `(version_key: str, dimension: str = "overworld") -> tuple[str, ...]` | 某版本、某维度可标注的结构键元组：按 `_PREVIEW_ORDER`（21 种全覆盖）顺序，过滤 `STRUCT_PARAMS[k][4] <= vnum`（min_ver）且 `STRUCT_DIMENSION.get(k, "overworld") == dimension`。 |
| `_c_div` | `(v: int, d: int) -> int` | C 整数除法（向零截断）。Python `//` 向负无穷，负数商不同——getVariant 采样点公式对负坐标的正确性依赖此函数。 |
| `_java_next_long` | `(state: int) -> tuple[int, int]` | Java `Random.nextLong` 复刻：两次 next(32) 拼接 `((hi<<32) + lo_s) & MASK64`，lo 须带符号参与加法（负 lo 使高 32 位 -1）。返回 (long 值, 新状态)。 |
| `chunk_generate_rnd` | `(world_seed: int, chunk_x: int, chunk_z: int) -> int` | cubiomes `chunkGenerateRnd` 复刻（流程见上文 ②），返回可直接供 nextInt 用的 48 位 LCG 状态。 |
| `_village_variant` | `(world_seed, chunk_x, chunk_z, biome_id) -> tuple \| None` | getVariant(Village)；返回 (vx, vz, vsx, vsz)，群系不在 5 变体表返回 None（流程见上文 ④）。 |
| `_variant_sample_point` | `(chunk_x, chunk_z, vx, vz, vsx, vsz) -> tuple[int, int]` | getVariant 采样点公式（L1622-1623 / L1780-1781）：`sampleX = (chunkX*32 + 2*vx + vsx - 1) / 2 >> 2`，"/ 2" 用 `_c_div` 截断、">> 2" 算术移位（floor），返回噪声格 (x, z)。 |
| `_bastion_variant` | `(world_seed, chunk_x, chunk_z) -> tuple` | getVariant(Bastion)（流程见上文 ④）。 |
| `_bastion_probability` | `(ws64: int, bx: int, bz: int) -> bool` | 堡垒概率门（getStructurePos L281-289）：`chunk_generate_rnd(ws64, bx>>4, bz>>4)` → `nextInt(5) >= 2`。用完整 64 位世界种子（与 cubiomes 主流程一致；48 位截断值结果等价但保守取 64 位）。 |
| `_jigsaw_variant` | `(struct_key: str, world_seed: int, bx: int, bz: int) -> tuple` | getVariant(Ancient City / Trial Chambers)；返回 (vx, vz, vsx, vsz, y)（流程见上文 ④）。 |
| `_check_feature` | `(struct_key, sampler, chunk_x, chunk_z) -> tuple[bool, int]` | L_feature 单点群系校验（上文 ③），查 `_FEATURE_WHITELIST`。 |
| `_check_mansion` | `(sampler, chunk_x, chunk_z) -> tuple[bool, int]` | Mansion 单点校验（上文 ③）。 |
| `_check_village` | `(sampler, world_seed, chunk_x, chunk_z) -> tuple[bool, int]` | Village 5 变体逐一检查包围盒中心采样点（上文 ③），返回 (viable, 最后采样群系 id)。 |
| `_check_outpost` | `(sampler, world_seed, chunk_x, chunk_z, version_key) -> tuple[bool, int]` | Outpost 三步判定：概率门 → 附近村庄 → 角落采样（上文 ③）。 |
| `_check_monument` | `(sampler, chunk_x, chunk_z) -> tuple[bool, int]` | Monument 中心深海 + rad=29 方格全海洋（上文 ③），四角先查快速拒绝。 |
| `_check_jigsaw` | `(struct_key, sampler, world_seed, bx, bz) -> tuple[bool, int]` | Ancient City / Trial Chambers 变体采样点校验（上文 ③）。 |
| `_x_next_long_j` | `(xr: Xoroshiro) -> int` | rng.h `xNextLongJ`：两次 `next_long()` 取高 32 位，按 Java int 符号拼接（各先判 ≥2^31 减 2^32）。 |
| `_x_next_float` | `(xr: Xoroshiro) -> float` | rng.h `xNextFloat`：`next_long() >> 40`（高 24 位）* 2^-24，消耗整个 64 位。 |
| `_x_next_int_pow2` | `(xr: Xoroshiro, n_pow2: int) -> int` | rng.h `xNextIntJ` 的 2 幂特判分支（本工具只用 16）：`x = n * (next_long() >> 33)`，按带符号 int64 右移 31 位返回。 |
| `_c_round` | `(v: float) -> int` | C `round()`：半值远离零（Python round 是银行家舍入，负半值不同），要塞 dist 取整依赖。 |
| `get_population_seed` | `(world_seed: int, x: int, z: int) -> int` | finders.c `getPopulationSeed` 1.18+ 分支（L27-55）：`Xoroshiro.from_seed(ws)` → `a = _x_next_long_j \| 1` → `b = _x_next_long_j \| 1`（共 4 次 next_long）→ 返回 `(x*a + z*b) ^ ws`（64 位）。沙漠水井概率门的基础。 |
| `_check_desert_well` | `(sampler, bx, bz) -> tuple[bool, int]` | 沙漠水井锚点单点校验 == DESERT（上文 ③）。 |
| `_stronghold_valid_sets` | `() -> tuple[set, set]` | isStrongholdBiome 排除集合预计算（上文 ⑤ 第 3 点），(validB, validM) 同语义两份。 |
| `_check_nether` | `(struct_key, ws, bx, bz, sampler) -> tuple[bool, int]` | 下界要塞/堡垒遗迹判定（上文 ③；sampler 为 NetherSampler，ws 须完整 64 位）。 |
| `_check_end` | `(struct_key, bx, bz, sampler) -> tuple[bool, int]` | 末地城判定：距离门 + chunk 级群系（上文 ③；sampler 为 EndSampler）。 |
| `check_structure_at` | `(struct_key, world_seed, bx, bz, version_key, sampler, nether_end=None) -> tuple[bool, int]` | **总调度**：按 `STRUCT_DIMENSION` 路由到 `_check_nether`/`_check_end`（nether_end 参数 None 时惰性建对应采样器）；主世界再按结构键分派到 `_check_village`/`_check_outpost`/`_check_monument`/`_check_mansion`/`_check_jigsaw`/`_check_desert_well`/恒真分支（ruined_portal/stronghold/mineshaft）或兜底 `_check_feature`。返回 (viable, 判定采样点群系 id，-1=未采样)。 |
| `_enum_treasure_well` | `(key, ws, viewport, sampler, results, cancel=None) -> None` | 埋藏的宝藏/沙漠水井逐 chunk 枚举（region=1，每 chunk 至多一个；视野外扩 margin=96）：treasure——`v = cx*341873128712 + cz*132897987541 + ws + salt` → `set_seed(v)` → `next_float < 0.01` → 锚点 `(cx*16+9, cz*16+9)` → `_check_feature`（沙滩/积雪沙滩）；desert_well——`get_population_seed(ws, cx*16, cz*16)` → `Xoroshiro.from_seed(pop + 40002)` → `_x_next_float < 0.001` → 坐标 `cx*16 + _x_next_int_pow2(xr, 16)` ×2 → `_check_desert_well`。cancel 每外层行检查一次。 |
| `_enum_mineshafts` | `(ws, viewport, results, cancel=None) -> None` | 废弃矿井：getMineshafts（L332-386）1.13+ 分支。`set_seed(ws)` → `_java_next_long` a → `_java_next_long` b（4 次 next(32)）；逐 chunk：`aix = (cx*a) ^ ws` → `set_seed(aix ^ (cz*b))` → `next_double < 0.004` → 锦点 `(cx*16, cz*16)`。无群系校验。 |
| `_enum_strongholds` | `(ws, version_key, viewport, results, on_progress=None, cancel=None) -> None` | 要塞：StrongholdIter 全序扫 128 窗（共享流版本不可跳窗）。仅 1.18/1.19 建 `_StrongholdWinSampler`；提前终止：`reach = max(|视野端点|) + 96 + 112 + 64`，近似点超 reach 且 index>0 即 break（dist 单调递增）。pos 在视野外扩 96 内才记录；结束时 `on_progress(1, 1, "stronghold")`。 |
| `enumerate_structures` | `(seed, version_key, viewport, struct_keys=None, on_progress=None, cancel=None, dimension="overworld") -> list[dict]` | **对外主入口**，流程见上文 ①。返回 `{struct, name, x, z, cx, cz, biome}` 列表。 |
| `_StrongholdWinSampler` | `class`（`__init__(seed, version_key)` / `window_ids(cx, cz, radius) -> np.ndarray`） | 要塞 locateBiome 窗口批量采样器（性能层）。**必须 Python 带链逐点采样**（MC-241546 共享 dat 链语义，见上文功能段）；`window_ids` 返回 (2r+1, 2r+1) int32 群系矩阵，扫描顺序 = xp locateBiome（j=z 外层、i=x 内层），每窗口重置 dat 链。内部复用 `BiomeSampler.climate_point_xz` 与 `climate_to_biome_dat`。 |
| `StrongholdIter` | `class`（`__init__(world_seed, version_key, win_sampler=None)` / `_locate_biome(ax, az)` / `next() -> bool`） | cubiomes StrongholdIter 的 1.18~1.21 移植（上文 ⑤）。属性：`angle`、`dist`、`nextapprox`、`pos`、`index`（已产生数）、`ringnum`/`ringmax`/`ringidx`（环结构）、`_rnds`（共享 48 位流）。 |

**接口**：被以下模块 import：
- `Threads/task_MapPreviewer.py:45`（`available_structures`、`enumerate_structures`——后台结构枚举线程）；
- `Tools/tool_MapPreviewer.py:69`（`available_structures`）；
- `Tools/tool_StructurePreviewer.py:53`（`BiomeSampler`[本模块 re-export]、`check_structure_at`、`enumerate_structures`）；
- `Utils/StructurePreviewer/locator.py:15`（整模块——结构预览定位）；
- `Utils/StructurePreviewer/composition.py:46`、`stronghold_pieces.py:56`、`village_assembly.py:71`（`as sm`）、`mansion_pieces.py:57`、`end_city_pieces.py:56`（整模块 import，取群系常量与判定辅助做多件拼装）。

对外提供：结构枚举入口 `enumerate_structures`/`available_structures`、单点判定 `check_structure_at`、要塞迭代器 `StrongholdIter`、人口种子 `get_population_seed`、`chunk_generate_rnd`，以及 re-export 的 `BiomeSampler` 与全套群系 id 常量。

**关键变量/常量**：

| 名称 | 含义 |
|---|---|
| `_MASK48` / `_MASK64` | `(1<<48)-1` / `(1<<64)-1`：48 位结构种与 64 位世界种子的位宽掩码，贯穿全部种子运算。 |
| 群系 id 常量（`OCEAN`~`SULFUR_CAVES` 等 40+ 项） | cubiomes `biomes.h` 的 BiomeID（与 biome_colors.py 同源），供各白名单集合与判定函数使用；`SULFUR_CAVES=187` 为 26.2 群系，MCHelper 封闭系统自定 id。 |
| `_OCEANIC` / `_DEEP_OCEANIC` | isOceanic / isDeepOcean（biomes.c）：10 种海洋/河流群系、其中 5 种深海，组成 ocean_ruin/shipwreck 白名单与 monument 深海判定。 |
| `_MONUMENT_BIOMES` | finders.c `g_monument_biomes1`：areBiomesViable 的 12 种海洋/河流群系。 |
| `_FEATURE_WHITELIST` | isViableFeatureBiome 1.18+ 白名单（L1182-1234），10 个结构键 → 允许群系集合：desert_pyramid{沙漠,沙漠丘陵}、jungle_temple{丛林/竹丛林及其丘陵}、swamp_hut{沼泽}、igloo{雪原/积雪针叶林/积雪山坡}、ocean_ruin=_OCEANIC、shipwreck=_OCEANIC+两种沙滩、ancient_city{深暗之域}、trail_ruins{6 种}、mansion{黑森林/黑森林丘陵}、buried_treasure{沙滩/积雪沙滩}（L1236-1238）。 |
| `_OUTPOST_BIOMES` | 前哨站 1.18+ 白名单 12 种（L1252-1269）。 |
| `_PREVIEW_ORDER` | MapPreviewer 版本→结构映射（21 种全，按图上易找程度排序）。**不同于** SeedReverser 的观测用版本表：前哨站/废弃传送门虽不可逆推但可正向标注；下界要塞/堡垒遗迹/末地城仅对应维度可选。 |
| `_VERSION_NUM` | `{"1.21": 121, "1.21.11": 1211, "26.2": 262}`，min_ver 过滤用（与 structure_params 同款，本地独立副本）。 |
| `_NETHER_FORTRESS_BIOMES` / `_NETHER_BASTION_BIOMES` / `_END_CITY_BIOMES` | 下界/末地白名单（finders.c L1287-1299）：要塞可生成于下界全部 5 群系；堡垒 4 群系（不含玄武岩三角洲）；末地城仅 end_midlands/end_highlands。 |
| `_BASTION_TABLES` | 堡垒 getVariant 尺寸表（L2088-2094，未旋转 sx, sz）：air_base 46x46 / hoglin_stable 30x48 / treasure 38x38 / bridge 16x32。 |
| `_VILLAGE_TABLES` | 村庄变体尺寸表：5 群系 × 若干 `(t 阈值, sx, sz)` 档位（nextInt 的 t 落入哪一档取哪一尺寸；同群系出现两组阈值，如 PLAINS 200~204 为 abandoning 变体尺寸）。 |
| `_VILLAGE_TABLE_MOD` | 5 群系村庄 nextInt 模数：PLAINS 204 / DESERT 250 / SAVANNA 459 / TAIGA 100 / SNOWY_PLAINS 306。 |

---

## 引用关系总览

| 公共模块 | 引用方（grep 确认） |
|---|---|
| `notification.py` | tool_AutoBackUp、tool_StrongHoldFinder、tool_SeedReverser、tool_MapPreviewer |
| `structure_icons.py` | tool_MapPreviewer（st_icons）、tool_SeedReverser（struct_icons）、tool_StructurePreviewer（struct_icons）、Utils/MapPreviewer/choose_structure（st_icons） |
| `biome_names.py` | tool_SeedReverser、tool_MapPreviewer、tool_StructurePreviewer、Utils/MapPreviewer/biome_colors |
| `structure_params.py` | tool_SeedReverser、tool_MapPreviewer、tool_StructurePreviewer、Utils/MapPreviewer/choose_structure、Utils/SeedReverser/structure_math、Utils/Public/structure_map |
| `biome_signature_colors.py` | tool_SeedReverser、tool_MapPreviewer |
| `stronghold_math.py` | tool_StrongHoldFinder、tool_SeedReverser |
| `structure_map.py` | task_MapPreviewer、tool_MapPreviewer、tool_StructurePreviewer、Utils/StructurePreviewer/{locator, composition, stronghold_pieces, village_assembly, mansion_pieces, end_city_pieces} |

# 3. 工具控制层与后台线程（Tools / Threads）

# MCHelper 小型工具层与线程任务文档（03a）

> 覆盖文件：`Tools/tool_base.py`、`Tools/tool_AutoBackUp.py`、`Tools/tool_Settings.py`、`Tools/tool_StrongHoldFinder.py`、`Tools/tool_EnchantCaculator.py`、`Threads/task_AutoBackUp.py`、`Threads/task_StrongHoldFinder.py`、`Threads/task_WorldSeedRefine.py`
> 所有内容均来自源码精读，代码标识符保留英文。

---

## `Tools/tool_base.py`

**功能**：定义全部工具页的公共基类 `BaseToolWidget`，本身不含任何业务逻辑，只约定三件事：

1. 继承 `QWidget`，使每个工具都是可直接嵌入主窗口 `QTabWidget` 的页面控件；
2. 声明可选的跨模块通信信号 `request_status_message = Signal(str)`（用于工具向主窗口请求显示状态栏消息等场景；当前代码库内未见任何发射方，属预留接口）；
3. 约定子类的两个类级接口：
   - `tool_name()` 类方法：子类必须覆盖，返回显示在 Tab 标签上的工具名称；未覆盖时抛 `NotImplementedError`；
   - `preferred_size` 类属性：可选的 `(宽, 高)` 元组（单位像素），声明工具期望的内容区尺寸。主窗口在切换到该工具的 tab 时会把窗口调整到该尺寸（窗口装饰差值自动计算）；设为 `None` 表示不声明，主窗口切换到该工具时保持当前窗口大小不动。

此外主窗口在关闭与退出时通过鸭子协议调用工具的 `can_close()` / `save_config()` 方法（`main_window.py:228-259`），这两个方法不在基类中定义，由需要的工具自行实现（如 `AutoBackUpWidget.can_close`、`EnchantCalculatorWidget.save_config`）。

**类与函数**

| 名称 | 签名 | 说明 |
|---|---|---|
| `BaseToolWidget` | `class BaseToolWidget(QWidget)` | 所有工具页的基类，仅提供信号声明与两个类级接口约定，无 UI 构建 |
| `request_status_message` | `Signal(str)`（类属性） | 预留信号：工具请求主窗口显示状态栏消息；当前无发射方 |
| `preferred_size` | `tuple \| None = None`（类属性） | 工具期望的内容区尺寸 `(宽, 高)`；`None` 表示不声明，主窗口不调整窗口大小 |
| `__init__` | `__init__(self, parent=None)` | 仅调用 `super().__init__(parent)`，注释标明"工具特有的初始化"由子类完成 |
| `tool_name` | `@classmethod tool_name(cls) -> str` | 返回工具显示名称（Tab 标题）；基类直接 `raise NotImplementedError`，强制子类覆盖 |

**接口**

- 被谁 import：`Tools/__init__.py:1`（re-export 供外部使用），以及 6 个工具模块 `tool_AutoBackUp.py`、`tool_EnchantCaculator.py`、`tool_MapPreviewer.py`、`tool_StrongHoldFinder.py`、`tool_SeedReverser.py`、`tool_StructurePreviewer.py`。
- 继承关系：继承 `QWidget`；是全部工具 Widget 类的直接基类。
- 信号：定义 `request_status_message(str)`；不接收任何信号。

**关键变量/常量**

| 名称 | 类型/值 | 说明 |
|---|---|---|
| `request_status_message` | `Signal(str)` | 类级信号，工具 → 主窗口通信预留通道 |
| `preferred_size` | `tuple \| None`，默认 `None` | 类属性；各工具以 `(628, 475)` 等具体值覆盖 |

---

## `Tools/tool_AutoBackUp.py`

**功能**：自动备份工具的主界面与控制层（586 行），职责包括：源/目标目录管理、存档列表展示（含 MC 存档封面图标）、备份任务队列调度、备份进度呈现、游戏进程监测与退出自动备份、配置持久化。

**UI 构建流程**（`__init__` 按注释标号顺序执行）：

1. `super().__init__(parent)` 初始化 QWidget；
2. `setupUi(self)` 由编译生成的 `Ui_AutoBackUp` 创建全部控件与布局；
3. 给存档列表 `targetDirList` 挂 `RightIconDelegate(icon_size=32)` 委托——MC 存档文件夹（内存档根目录直接存在 `icon.png/jpg/jpeg/webp/bmp`）的封面图标固定显示在行最右侧；
4. 创建 300ms 单发防抖 `QTimer`（`_refresh_timer`）：源路径输入框 `textChanged` 每次只重启计时，用户停止输入 300ms 后才真正刷新列表（避免逐字符触发 `listdir` + 逐项解码存档图标造成卡顿）；
5. 进度条 `backUpProgress` 清零；
6. `connect_slots()` 连接全部信号槽；
7. 取 `QThreadPool.globalInstance()` 并 `setMaxThreadCount(4)`，限制备份并发上限；
8. 全部成员变量复位；
9. `read_config()` 加载持久化配置（目录、选中项、监测进程名等）；
10. 若配置中 `target_process` 非空，自动调用 `moniter_control()` 启动进程监测。

**信号连接**（`connect_slots`）：`chooseTargetDir`/`chooseDesDir` 点击 → 弹目录对话框；`targetDirPath.textChanged` → 防抖刷新；`startBackUp` 点击 → `do_back_up("手动")`；`monitorController` 点击 → `moniter_control` 切换监测；`isAutoBackUp.checkStateChanged` → `on_back_up_check_box_changed`；`processName.textChanged` → `on_process_name_text_changed`；跨模块信号 `backup_bus.task_started/task_progress/task_finished` → 三个主线程更新槽。

**备份任务生命周期（核心流程）**：`do_back_up(status)` 六步——

1. `get_back_up_list()`：从列表当前选中项构建 `{文件名: 绝对路径}` 写回 `back_up_list`；随后 `save_config()` 先持久化配置；
2. 重入保护：`is_backing_up` 为 True 时追加提示并返回（手动点击已被按钮禁用拦截，此处主要拦截"进程退出触发的自动备份"，防止计数被重置导致进度错乱）；
3. 校验：`back_up_list` 为空报错返回；`des_dir_path` 为空报错返回（提前拦截 `makedirs('')` 的 `FileNotFoundError`）；通过后 `os.makedirs(self.des_dir_path, exist_ok=True)`；
4. 阶段一（过滤有效文件，计算总大小）：遍历 `back_up_list`，路径不存在则警告跳过；文件夹用 `os.walk` 累计所有子文件大小、单文件直接 `os.path.getsize`，得到 `total_bytes` 与 `valid_paths`；全部无效则终止；
5. 阶段二（设定备份初始状态）：`finished_bytes/finished_tasks/failed_tasks` 归零、`total_tasks = len(valid_paths)`、`is_backing_up = True`、进度条归零、`startBackUp` 禁用、`_set_backup_controls_enabled(False)` 禁用路径编辑与列表选择（防止用户在备份中修改路径/选区与备份交错），信息框输出概览（触发方式 status + `format_bytes` 格式化总大小 + 任务数）；
6. 阶段三（提交任务到多线程池）：为每个 `valid_paths[idx]` 创建 `BackupTask(task_id=idx, file_path, dest_dir=self.des_dir_path)` 并 `self.thread_pool.start(task)`，由全局线程池（≤4 并发）调度执行；主线程随即返回，UI 靠 `backup_bus` 信号接收进度。

**backup_bus 信号通信**：`BackupTask` 在工作线程发射 `task_started(int, str)` / `task_progress(int, int)`（第二个 int 为本次压缩的增量字节数，非百分比）/ `task_finished(int, bool, str)`。主线程三个槽：`on_back_up_started` 向信息框追加"正在备份"日志；`on_back_up_progress` 累加 `finished_bytes`，按 `total_bytes` 换算百分比刷新进度条（`min(percent, 100)` 防多任务超 100%）；`on_back_up_finished` 累计 `finished_tasks` 与 `failed_tasks`、按成败追加日志，当 `finished_tasks == total_tasks` 时收尾——`is_backing_up = False`、恢复开始按钮与路径/列表控件、弹 `NotificationWidget.Show`（全部成功 / 有 N 个失败，3000ms）、进度条置 100。

**process_monitor 轮询**：监测器为 `Utils/AutoBackUp/process_monitor.py` 的 `ProcessMonitor`（`QObject` + `QTimer`，默认每 1000ms 触发 `_check`，内部用 `psutil.process_iter` 按进程名不区分大小写模糊匹配；PID 优先级更高但本工具只用进程名）。`start_monitoring()`：读取 `processName` 输入框（空则默认 `'java.exe'`）存入 `target_process`；旧 `monitor` 存在则先 `stop_monitoring()` + `deleteLater()`；新建 `ProcessMonitor(process_name=...)`，连接其 `started(name, pid)` / `stopped(name)` 信号，置 `is_monitoring = True` 后 `start_monitoring()`（内部先立即 `_check` 一次再启动定时器）。`stop_monitoring()`：停止并销毁 monitor、复位状态。`moniter_control()` 为切换开关，同时联动 `processName` 输入框的禁用/启用与按钮文本。槽 `on_process_started` 记录日志并弹通知；`on_process_stopped` 记录日志、按钮文本复位为"开始监测"，且当 `is_auto_back_up` 为 True 时调用 `do_back_up(status="自动")`——实现"游戏进程（默认 java.exe）退出即自动备份存档"。

**配置持久化**：配置文件 `backup_config.json`，路径由 `get_config_path()` 决定——`QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)`（通常 `~/.config/` 或 `%APPDATA%/`），获取失败回退到脚本所在目录，目录不存在自动创建。字段五个：`target_dir_path`（源目录）、`des_dir_path`（备份目标目录）、`back_up_list`（选中项字典）、`target_process`（监测进程名）、`is_auto_back_up`（缺省 True）。`read_config()` 恢复变量并回填 UI（含 `refresh_dir_list()` 触发列表刷新，`_do_refresh_dir_list` 末尾按 `back_up_list` 键集合用 `QItemSelectionModel.Select | Rows` 自动重选列表行）；`save_config()` 在每次 `do_back_up` 前写入（`ensure_ascii=False, indent=2`）。

**存档封面图标**：候选文件名元组 `_ICON_NAMES = ("icon.png", "icon.jpg", "icon.jpeg", "icon.webp", "icon.bmp")`；`_load_save_icon` 按候选顺序探测，命中且 `QPixmap` 非空则以 icon 文件绝对路径为键存入 `_icon_cache`（同一目录反复刷新不重复读盘解码），失败返回 `None`。`_add_list_items` 逐项构建 `QListWidgetItem`：text 保持原始文件夹名不变（它是 `saves_list`/`back_up_list` 的字典键，选中恢复逻辑依赖 text 匹配），图标通过 `RightIconDelegate.set_right_icon` 的自定义数据角色携带，不影响 text。目录无效（不存在/无权限）时 `_show_dir_error_item` 显示一行 `NoItemFlags` 的置灰提示项，不再静默空白。

**关闭保护协议**：`can_close()` 在备份进行中返回 False；主窗口 `closeEvent`（`main_window.py:228-238`）逐 tab 检查 `can_close`，为 False 时弹警告并 `event.ignore()`，避免留下不完整的 zip。

**类与函数**

| 名称 | 签名 | 说明 |
|---|---|---|
| `format_bytes` | `format_bytes(num_bytes: int) -> str`（模块级） | 字节数格式化为 1024 进制易读单位（B/KB/MB/GB/TB），保留 1 位小数，整数值省略 `.0`（如 1024 → "1 KB"） |
| `AutoBackUpWidget.__init__` | `__init__(self, parent=None)` | 按标号 1~9 顺序完成 UI 构建、委托挂载、防抖定时器、信号连接、线程池（setMaxThreadCount(4)）、成员复位、读配置、按需自动开启监测 |
| `connect_slots` | `connect_slots(self)` | 连接全部控件信号与 `backup_bus` 三条跨模块信号 |
| `tool_name` | `@classmethod tool_name(cls) -> str` | 返回 `"AutoBackUp"` 作为 Tab 标题 |
| `choose_target_dir` | `@Slot() choose_target_dir(self)` | `QFileDialog.getExistingDirectory` 选源目录，写入 `target_dir_path` 与 `targetDirPath` 文本框；取消（空串）不动作 |
| `choose_des_der` | `@Slot() choose_des_der(self)` | 同上，选备份目标目录，写入 `des_dir_path` 与 `targetDesPath` |
| `refresh_dir_list` | `@Slot() refresh_dir_list(self)` | 源路径文本变化时的防抖入口：仅 `_refresh_timer.start()`，到期才执行实际刷新 |
| `_do_refresh_dir_list` | `_do_refresh_dir_list(self)` | 实际刷新：清空列表与 `saves_list` → 校验 `os.path.isdir`（失败显示置灰错误项并返回）→ `os.listdir` 建 `{文件名: 绝对路径}` 映射 → `_add_list_items` 构建条目（含封面图标）→ 遍历列表按 `back_up_list` 键整行恢复选中 |
| `_show_dir_error_item` | `_show_dir_error_item(self, message: str)` | 向列表添加一行 `Qt.ItemFlag.NoItemFlags` 的不可选提示项 |
| `_load_save_icon` | `_load_save_icon(self, full_path: str)` | 按 `_ICON_NAMES` 顺序探测存档封面 icon，带 `_icon_cache` 缓存；命中返回 `QPixmap`，否则 `None` |
| `_add_list_items` | `_add_list_items(self, items)` | 逐项添加列表条目；仅文件夹才尝试加载封面图标（普通文件跳过）；text 保持原文件夹名 |
| `get_back_up_list` | `get_back_up_list(self)` | 清空 `back_up_list` 后按 `selectedItems()` 重建 `{选中文本: 绝对路径}` 映射 |
| `get_config_path` | `get_config_path(self) -> str` | 返回配置文件绝对路径（AppConfigLocation，失败回退脚本目录，自动建目录） |
| `read_config` | `read_config(self)` | 加载 JSON 配置到成员变量并回填 UI、触发列表刷新；文件不存在直接返回；异常打印不抛出 |
| `save_config` | `save_config(self)` | 先 `get_back_up_list()` 取最新选中项，再写入五字段 JSON（`ensure_ascii=False, indent=2`） |
| `do_back_up` | `@Slot() do_back_up(self, status)` | 备份主流程（见上文"备份任务生命周期"六步）；status 为 `"手动"`/`"自动"`，仅用于信息框文案 |
| `_set_backup_controls_enabled` | `_set_backup_controls_enabled(self, enabled: bool)` | 备份期间禁用/恢复源目录按钮、路径输入框（readOnly）、存档列表 |
| `can_close` | `can_close(self) -> bool` | 返回 `not self.is_backing_up`；主窗口关闭前询问用 |
| `on_back_up_started` | `@Slot() on_back_up_started(self, task_id, filename)` | 接收任务开始信号，信息框追加 `[任务{id}] 正在备份：{filename}` |
| `on_back_up_progress` | `@Slot() on_back_up_progress(self, task_id, chunk_bytes)` | 累加 `finished_bytes`，按总大小换算百分比（上限 100）刷新进度条 |
| `on_back_up_finished` | `@Slot() on_back_up_finished(self, task_id, success, message)` | 统计成败并记日志；全部完成时复位 `is_backing_up`、恢复控件、弹通知、进度条置 100 |
| `moniter_control` | `@Slot() moniter_control(self)` | 监测开关：未监测时改按钮文本为"停止监测"并 `start_monitoring()`、禁用进程名输入框；否则反向 |
| `start_monitoring` | `start_monitoring(self)` | 取进程名（空默认 `java.exe`）；旧 monitor 清理后新建 `ProcessMonitor`，连接 `started`/`stopped`，置位并启动 |
| `stop_monitoring` | `stop_monitoring(self)` | 停止并 `deleteLater()` monitor、置 None、`is_monitoring = False` |
| `on_process_started` | `on_process_started(self, name, pid)` | 进程启动处理：信息框记录 + `NotificationWidget.Show` 通知 |
| `on_process_stopped` | `on_process_stopped(self, name)` | 进程退出处理：记录日志、按钮复位；`is_auto_back_up` 为 True 时 `do_back_up(status="自动")` |
| `on_back_up_check_box_changed` | `on_back_up_check_box_changed(self)` | 读 `isAutoBackUp.checkState().name`，`"Checked"` → `is_auto_back_up = True`，否则 False |
| `on_process_name_text_changed` | `on_process_name_text_changed(self)` | 输入框文本同步到 `target_process` |

**接口**

- 继承：`BaseToolWidget` + `Ui_AutoBackUp`（`CodesUI.AutoBackUp` 编译生成的 UI 类）。
- 依赖 import：`BackupTask`（Threads）、`backup_bus`（Utils.AutoBackUp.signals_AutoBackUp）、`ProcessMonitor`（Utils.AutoBackUp.process_monitor）、`NotificationWidget`（Utils.Public.notification）、`RightIconDelegate`（Utils.AutoBackUp.right_icon_delegate）。
- 被谁 import：`Tools/__init__.py` 将其注册进 `TOOL_CLASSES`，由 `main_window.py` 加载为 tab 页。
- 信号接收：`backup_bus.task_started/task_progress/task_finished`；`monitor.started(str, int)` / `monitor.stopped(str)`。
- 信号发出：无自定义信号（基类 `request_status_message` 继承但未使用）。

**关键变量/常量**

| 名称 | 类型/值 | 说明 |
|---|---|---|
| `preferred_size` | `(628, 475)` | 类属性，UI 设计尺寸，主窗口切到本 tab 时自适应 |
| `_ICON_NAMES` | `("icon.png", "icon.jpg", "icon.jpeg", "icon.webp", "icon.bmp")` | 类常量，存档封面图标候选文件名 |
| `target_dir_path` / `des_dir_path` | `str`，默认 `''` | 类属性声明 + `__init__` 重赋实例属性：源/目标目录路径 |
| `saves_list` / `back_up_list` | `dict`，默认 `{}` | 类属性声明 + `__init__` 重赋实例属性：源目录全部条目映射 / 用户选中的备份项映射 |
| `target_process` | `str` | 监测的进程名（如 java.exe），触发自动备份的依据 |
| `total_bytes` / `finished_bytes` | `int` | 待备份总字节数 / 已完成累计字节数 |
| `total_tasks` / `failed_tasks` | `int` | 任务总数 / 失败数（`finished_tasks` 未在 `__init__` 初始化，仅在 `do_back_up` 阶段二赋值） |
| `is_backing_up` | `bool` | 备份进行中标志（重入保护 + 主窗口关闭保护） |
| `is_auto_back_up` | `bool`，默认 `True` | 进程退出时是否自动备份 |
| `monitor` / `is_monitoring` | `ProcessMonitor \| None` / `bool` | 进程监测器实例与运行标志 |
| `thread_pool` | `QThreadPool` | 全局线程池，最大并发 4 |
| `_refresh_timer` | `QTimer`（单发，300ms） | 路径输入防抖定时器 |
| `_icon_cache` | `dict` | `{icon 文件绝对路径: QPixmap}` 封面图标缓存 |
| `backup_config.json` | 配置文件 | 位于 AppConfigLocation（失败回退脚本目录），五个字段见上文 |

---

## `Tools/tool_Settings.py`

**功能**：设置对话框（79 行）。注意它**不继承** `BaseToolWidget`、不注册进工具 tab，而是 `QDialog` 模态对话框——由 `main_window.py` 的菜单控制器（`menu_controller`，index 0）以 `SettingsWindow(self); settings_win.exec()` 方式打开。

**实现原理**：`__init__` 中 `setupUi(self)` 后设置标题"设置"，初始化 `is_start_on_root`/`is_system_tray` 两个布尔成员，把复选框 `isStartOnRoot`/`isSystemTray` 的 `checkStateChanged` 信号分别连到 `start_on_root_statu`/`system_tray_statu`，再 `read_config()` 加载持久化配置，最后主动调用这两个状态槽一次——把配置加载后的勾选状态立即广播到 `settings_bus`，驱动主窗口生效。

**信号广播机制**：两个状态槽逻辑相同——读 `checkState().name`，等于 `"Checked"` 转布尔 True（否则 False），存入成员变量并 `settings_bus.is_start_on_boot.emit(bool)` / `settings_bus.is_system_tray.emit(bool)`。`settings_bus` 为 `Utils/Settings/signals_Settings.py` 定义的全局单例（`SettingsSignals(QObject)`，仅这两个 `Signal(bool)`）；`main_window.py:42-43` 连接这两个信号到 `system_tray_controller` / `start_on_boot_controller`，分别控制关闭行为（托盘最小化或退出）与开机自启（`set_start_on_boot` 写注册表）。

**配置持久化**：`get_config_path()` 与备份工具同模式——`QStandardPaths.AppConfigLocation`，失败回退脚本目录，自动建目录；文件名 `settings_config.json`，字段 `is_system_tray` / `is_start_on_root`。`closeEvent` 中先 `save_config()` 再 `event.accept()`，即每次关闭对话框都落盘。

备注（源码事实）：`read_config` 与 `save_config` 中缺省值写的是 `bool` 类型对象本身（`data.get("is_system_tray", bool)`、`getattr(self, "is_system_tray", bool)`），键缺失时将得到 `bool` 类而非布尔值；因 `save_config` 总会写入这两个键，正常流程不会触发该缺省分支。

**类与函数**

| 名称 | 签名 | 说明 |
|---|---|---|
| `SettingsWindow.__init__` | `__init__(self, parent=None)` | setupUi、设标题、成员初始化、连接两个复选框信号、读配置、主动广播一次当前状态 |
| `start_on_root_statu` | `start_on_root_statu(self)` | 复选框状态 → 布尔存 `is_start_on_root`，并 `settings_bus.is_start_on_boot.emit(bool)` |
| `system_tray_statu` | `system_tray_statu(self)` | 复选框状态 → 布尔存 `is_system_tray`，并 `settings_bus.is_system_tray.emit(bool)` |
| `get_config_path` | `get_config_path(self) -> str` | 返回 `settings_config.json` 绝对路径（AppConfigLocation，失败回退脚本目录，自动建目录） |
| `read_config` | `read_config(self)` | 文件不存在直接返回；读取两字段并 `setChecked` 回填 UI；异常打印不抛出 |
| `save_config` | `save_config(self)` | 写入 `{is_system_tray, is_start_on_root}` JSON（`ensure_ascii=False, indent=2`） |
| `closeEvent` | `closeEvent(self, event)` | 先 `save_config()` 再 `event.accept()` |

**接口**

- 被谁 import：仅 `main_window.py:5`（菜单打开设置）。
- 继承：`QDialog` + `Ui_Settings`（`CodesUI.Settings` 编译生成的 UI 类）。
- 信号：发出 `settings_bus.is_start_on_boot(bool)`、`settings_bus.is_system_tray(bool)`（接收方为 `main_window`）；不接收信号。

**关键变量/常量**

| 名称 | 类型/值 | 说明 |
|---|---|---|
| `is_start_on_root` | `bool`，初始 False | 开机自启选项（复选框 `isStartOnRoot` 对应状态） |
| `is_system_tray` | `bool`，初始 False | 系统托盘选项（复选框 `isSystemTray` 对应状态） |
| `settings_config.json` | 配置文件 | 位于 AppConfigLocation，字段 `is_system_tray` / `is_start_on_root` |

---

## `Tools/tool_StrongHoldFinder.py`

**功能**：要塞定位工具（307 行）——末影之眼三角定位法：玩家在两个不同位置，分别把准星对准末影之眼飞走的方向按 F3+C（复制出形如 `/execute in minecraft:overworld run tp @s x y z yaw pitch` 的命令），本工具通过剪贴板监听自动捕获两份观测数据，解析出"位置 + 视线朝向"，求两条视线在水平面上的交点即要塞水平位置，并给出下界交通坐标（主世界坐标 / 8）与可粘贴到聊天栏的 `/tp` 传送命令。

**UI 构建流程**（`__init__`）：`setupUi(self)` 后先向信息框 `informationBrowser` 预置四步使用说明；连接按钮 `doCaculate` → `_on_do_caculate_clicked`、`clearCoordinates` → `_on_clear_coordinates_clicked`；创建 `ClipboardListenerThread(self)` 并把其 `clipboard_changed` 信号连到 `_on_clipboard_changed` 后 `start()`（监听线程常驻——轮询序号开销可忽略，停/启反而引入竞态）；最后挂接应用级退出兜底 `QApplication.instance().aboutToQuit.connect(self._stop_clipboard_thread)`。模块头注释声明：自动监测仅在本页为 tab 栏最上层页时生效，主窗口最小化到托盘后仍继续生效（tab 停留在本页即可）。

**F3C 数据解析与自动填入流程**：

1. 后台线程检测到剪贴板序号变化，发 `clipboard_changed()`（无参），由主线程槽 `_on_clipboard_changed` 处理；
2. 门控 `_is_active_tab_page()`：沿 `parentWidget()` 父链向上找 `QTabWidget`——本页不在任何 tab 内（独立使用/测试）视为始终激活；在 tab 内则要求 `container.currentWidget() is self`。故意不看窗口可见性：最小化到托盘（hide）不改变 tab 当前页，隐藏后自动监测继续生效。非激活页收到信号直接忽略；
3. 读 `QApplication.clipboard().text()`，经 `looks_like_f3c` 预判（判据来自 `Utils/Public/stronghold_math.py`：以必现前缀 `/?execute in minecraft:overworld run tp @s` 开头、之后至少 5 个数字、长度 ≤200 字符；其他维度的 F3+C 不被识别）；
4. 与两个输入框现有文本去重（相同则忽略）；坐标一为空 → `_auto_fill_first(text)`；否则坐标二为空 → `_auto_fill_second(text)`；两框皆有内容时不自动覆盖，避免破坏用户已确认的观测数据；
5. `_auto_fill_first` 防抖：先 `parse_f3c_command(text)` 解析出 `(x, z, yaw)`（解析失败静默返回）；首次填入（无历史记录）直接通过；否则与上次自动填入比较——间隔不足 `_AUTO_FILL_COOLDOWN_S`(8 秒) 或 `math.hypot` 位置差不足 `_AUTO_FILL_MIN_DISTANCE`(10 格) 时忽略本次观测并在信息框提示（手动粘贴不受影响，点"清除"重置防抖状态）；通过则 `setText` 填入坐标一并记录 `_last_auto_fill_time` / `_last_auto_fill_pos`；
6. `_auto_fill_second`：填入坐标二后解析两点；若两观测点水平距离 `dist < _AUTO_CALC_MIN_DISTANCE`(30 格)，提示建议走远些（也可手动点"计算"）；达到 30 格则调用 `_compute_and_show()`，成功后弹 `NotificationWidget.Show`（标题"要塞定位完成"，内容含主世界坐标与下界坐标 /8 及"传送命令已复制到剪贴板"，显示 `_RESULT_NOTIFY_DURATION_MS` 6 秒，标题/正文字号与内边距均大于默认值以求醒目）。

**射线交汇计算流程**（`_compute_and_show`）：

1. 两个输入框去空白后非空校验，缺失则在信息框给出操作指引并返回 `None`；
2. 对两份文本各调 `parse_f3c_command_full(text)` 得 `(x, y, z, yaw)`。解析实现在 `Utils/Public/stronghold_math.py` 的 `_parse_f3c_numbers`：不依赖命令前缀完整格式（新旧版本前缀不同），用正则 `[-+]?(?:\d+\.?\d*|\.\d+)` 抓取文本中全部数字、取最后 5 个按 F3+C 固定顺序解释为 `x y z yaw pitch`——同时兼容标准命令、旧版 `/tp` 命令与手打纯数字；数字不足 5 个抛 `ValueError`；
3. 调 `intersect_rays(x1, z1, yaw1, x2, z2, yaw2)` 求交点：MC 角度系与数学课本不同（0°=南(+Z)、顺时针增大，90°=西），视线单位方向向量取 `(dx, dz) = (-sin(yaw), cos(yaw))`；解参数方程 `(x,z) + t·(dx,dz)`，对 `t1·(d1×d2) = (P2-P1)×d2`（二维叉积）先解 `t1` 再回代得交点 `(ix, iz)`，`t2` 由交点在第二条视线上的投影（单位向量点乘即距离）得出；返回 `dict{x, z, t1, t2, dist1, dist2}`。两视线叉积绝对值 `< 1e-6`（≈0.00006°，对应"几乎原样复制两遍"）判平行抛错；两观测点水平间距 `< 0.5` 格判同位置抛错；
4. 解析或求交抛 `ValueError` 时，信息框显示 `计算失败：{exc}` 并返回 `None`；
5. 成功：拼传送命令 `self._tp_command = f"/tp @s {result['x']:.1f} {max(y1, y2):.1f} {result['z']:.1f}"`（y 取两观测点较大值）并 `QApplication.clipboard().setText()` 自动复制；调 `_format_result` 生成结果文本写入信息框；返回结果 dict。

`_format_result`（静态方法）输出的内容包括：两观测点的 X/Y/Z 与视线朝向（`yaw_to_compass` 八方位名 + `normalize_yaw` 规范到 [-180,180) 的角度）、交点（要塞水平位置）、下界交通坐标（主世界坐标 / 8）、传送命令；随后追加质量告警——`result["t1"] < 0` 或 `t2 < 0` 表示交点位于该视线反方向（当时准星可能没对准末影之眼，建议重新观测）；最后附提示"末影之眼在距要塞约 20 格内会悬停下坠，近距离观测误差大；两次观测点相距越远、瞄准越准，交点越可靠"。

**退出兜底**（源码注释明确说明的动机）：Qt 只给顶层窗口发 `closeEvent`，不会传给作为子控件的工具页；托盘菜单"关闭程序"等路径也不会触发窗口 closeEvent；若监听线程在仍运行时被析构，程序会以 0xC0000409 崩溃退出。因此挂接应用级 `aboutToQuit` → `_stop_clipboard_thread()`（`requestInterruption()` + `quit()` + `wait(1000)`，重复调用无副作用）；`closeEvent` 再调一次作为双保险。

**类与函数**

| 名称 | 签名 | 说明 |
|---|---|---|
| `StrongHoldFinderWidget.__init__` | `__init__(self, parent=None)` | setupUi、预置使用说明、连接计算/清除按钮、创建并启动剪贴板监听线程、挂接 aboutToQuit 退出兜底 |
| `_stop_clipboard_thread` | `_stop_clipboard_thread(self) -> None` | 停止监听线程：requestInterruption + quit + wait(1000)；线程为 None 或重复调用无副作用 |
| `closeEvent` | `closeEvent(self, event) -> None` | 窗口关闭时再停一次线程（aboutToQuit 的双保险），随后调基类 closeEvent |
| `tool_name` | `@classmethod tool_name(cls) -> str` | 返回 `"StrongHoldFinder"` |
| `_is_active_tab_page` | `_is_active_tab_page(self) -> bool` | 沿父链找 QTabWidget 判断本页是否为当前激活页；不在 tab 内视为激活；不看窗口可见性（托盘隐藏不失效） |
| `_on_clear_coordinates_clicked` | `_on_clear_coordinates_clicked(self) -> None` | 清空两个坐标输入框与信息框，并重置自动填入防抖状态（`_last_auto_fill_time`/`_last_auto_fill_pos` 置 None） |
| `_on_clipboard_changed` | `_on_clipboard_changed(self) -> None` | 剪贴板变化主线程槽：激活页门控 → `looks_like_f3c` 预判 → 与输入框去重 → 按空框分派 `_auto_fill_first`/`_auto_fill_second` |
| `_auto_fill_first` | `_auto_fill_first(self, text: str) -> None` | 自动填入坐标一：解析 (x,z,yaw)，带 8 秒冷却与 10 格距离防抖，被拦时信息框提示；通过则填入并记录时间与位置 |
| `_auto_fill_second` | `_auto_fill_second(self, text: str) -> None` | 自动填入坐标二：两点距离 <30 格仅提示；≥30 格则 `_compute_and_show()` 成功后弹加大字号的定位完成通知 |
| `_on_do_caculate_clicked` | `_on_do_caculate_clicked(self) -> None` | 计算按钮槽：直接调 `_compute_and_show()` |
| `_compute_and_show` | `_compute_and_show(self) -> dict \| None` | 核心计算：两框非空校验 → `parse_f3c_command_full` ×2 → `intersect_rays` → 生成 `/tp @s x y z`（y 取两观测点较大值）复制到剪贴板 → `_format_result` 写信息框；成功返回结果 dict，失败返回 None |
| `_format_result` | `@staticmethod _format_result(result, x1, y1, z1, yaw1, x2, y2, z2, yaw2, tp_command="") -> str` | 把交点结果整理为展示文本：观测点与八方位朝向、交点、下界坐标（/8）、传送命令、t1/t2<0 的重新观测告警、近距离误差提示 |

**接口**

- 继承：`BaseToolWidget` + `Ui_strongHoldFinder`（`CodesUI.StrongHoldFinder` 编译生成的 UI 类）。
- 依赖 import：`ClipboardListenerThread`（Threads.task_StrongHoldFinder）；`Utils.Public.stronghold_math` 的 `intersect_rays`、`looks_like_f3c`、`normalize_yaw`、`parse_f3c_command`、`parse_f3c_command_full`、`yaw_to_compass`；`NotificationWidget`。
- 被谁 import：`Tools/__init__.py` 注册进 `TOOL_CLASSES`。
- 信号接收：`_clipboard_thread.clipboard_changed()`（无参）；信号发出：无自定义信号。

**关键变量/常量**

| 名称 | 类型/值 | 说明 |
|---|---|---|
| `preferred_size` | `(663, 373)` | 类属性，UI 设计尺寸 |
| `_AUTO_FILL_COOLDOWN_S` | `8.0` 秒 | 坐标一两次自动填入的最小间隔 |
| `_AUTO_FILL_MIN_DISTANCE` | `10.0` 格 | 坐标一自动填入与上次位置的最小距离（1 格 = 1 米） |
| `_AUTO_CALC_MIN_DISTANCE` | `30.0` 格 | 两观测点达到该距离时自动计算 |
| `_RESULT_NOTIFY_DURATION_MS` | `6000` 毫秒 | 自动计算通知显示时长 |
| `_NOTIFY_TITLE_SIZE` / `_NOTIFY_MESSAGE_SIZE` / `_NOTIFY_PADDING` | `16` / `14` / `(20, 16, 20, 16)` | 通知外观：定位结果需醒目，字号与内边距大于默认值 |
| `_last_auto_fill_time` | `float \| None` | 上次自动填入坐标一的时刻（`time.monotonic()`，None 表示无记录） |
| `_last_auto_fill_pos` | `tuple[float, float] \| None` | 上次自动填入坐标一的位置 `(x, z)` |
| `_tp_command` | `str` | 最近一次计算的传送命令（用于结果展示） |
| `_clipboard_thread` | `ClipboardListenerThread` | 常驻剪贴板监听线程（父对象为 self） |

---

## `Tools/tool_EnchantCaculator.py`

**功能**：附魔计算器（铁砧合并优化）的控制层（246 行）——负责 UI 组装、流程编排与会话持久化；附魔数据、冲突检测、优化算法与结果展示分别在 `Utils/EnchantCaculator` 的各子模块中（`DataManager` 数据单例、`ChooseItemsWindow` 物品选择窗、`CardListWidget` 卡片列表、`conflict_resolver` 冲突簇检测与决策弹窗、`AnvilOptimizer` 铁砧优化器、`AnvilStepsTree` 步骤树展示）。

**UI 构建流程**（`__init__`）：`setupUi(self)` 后依次：

1. `addItems` 按钮 → `do_choose_items`（打开物品选择窗）；
2. 把 UI 生成的原生 `chosenItemList`（`QListWidget`）**同父组件同网格位置替换**为增强型 `CardListWidget`（`self.gridLayout.replaceWidget(old_list, ...)` 后旧控件 `deleteLater()`，原布局不受影响）——增强点：横排卡片布局（构造内置）、Del 键删除、再次点击取消选中、拖动交换位置；
3. `clearItems` 按钮 → `do_clear_cards`（清空卡片 + 冲突决策清零 + 步骤图恢复占位）；
4. 结果区原生 `realSteps`（`QListWidget`）同法替换为步骤树控件 `AnvilStepsTree`；
5. `startCaculate` 按钮 → `do_start_calculate`（计算合并所有卡片的最少经验等级与最优合成步骤）；
6. `displayMode` 下拉框 `currentIndexChanged` → `_on_display_mode_changed`（树状图 / 步骤图两种展示模式，切换时用最近方案即时重渲染）；
7. 初始化成员：`selected_stuff`（选择窗回传数据）、`conflict_choices`（跨卡片冲突保留决策 `{簇序号: 保留的附魔ID}`，只影响最终合成物组成、不从卡片移除任何附魔，未保留的仍计费）、`_optimizer = AnvilOptimizer(DataManager())`（DataManager 为单例，构造开销极小）、`_last_plan`/`_last_dm`（最近一次计算成功的方案及其数据管理器，供展示模式切换重渲染）；
8. `chosenItemList.itemDoubleClicked` → `_edit_card_at`（双击卡片进入编辑模式）；
9. `_restore_session()` 启动时恢复上次会话的卡片（异常静默丢弃，不影响启动）。

**开始计算主流程**（`do_start_calculate`）：

1. `chosenItemList.all_card_data()` 收集全部卡片数据，为空则 `QMessageBox.information` 提示并返回；
2. 取 `DataManager()`，调 `_resolve_conflicts_for_calculate(cards, dm)` 做冲突决策——冲突统一在开始计算时处理（添加卡片时不再弹窗）：`find_conflict_clusters` 检测冲突簇 → `resolve_conflicts` 自动决策（附魔出现在全部非书卡片上则必然保留，如唯一剑上的锋利）→ 剩余待决策簇弹 `ConflictResolveDialog`（`defaults` 把上次 `conflict_choices` 按新旧簇序号映射预选；用户取消则返回 False，本次不计算）；无冲突时过期决策作废清空；
3. 决策转约束：`required = frozenset(self.conflict_choices.values())`（保留的附魔必须出现在最终合成物上）；
4. `self._optimizer.optimize(build_items_from_cards(cards), required_enchants=required)` 计算最优合并方案；抛 `AnvilError`（无法合成一件 / 约束无法满足）时 `QMessageBox.warning` 提示原因、结果区维持原状；
5. 成功：缓存 `_last_plan`/`_last_dm`，调 `realSteps.show_plan(plan, dm, mode="steps" if displayMode.currentIndex()==1 else "tree")` 按当前展示模式渲染步骤树。

**会话持久化**：会话文件 `enchant_session.json`（路径逻辑同前：AppConfigLocation，失败回退脚本目录，自动建目录）。`_save_session` 把 `all_card_data()` 写入 JSON（添加/编辑/清空卡片时调用）；`_restore_session` 启动时读取，逐项校验数据包结构（dict 且含 `item_name`、`enchants` 为 list）后 `add_card` 恢复，异常项跳过、文件缺失或损坏静默处理；`save_config()` 是主窗口退出协议（`save_all_tools_config`）的挂点，转调 `_save_session`。

**物品类型约束**（`allowed_item_types`）：铁砧不能合并不同类型物品——已存在非附魔书卡片时，选择窗只开放 `{"附魔书"} | 该类型`；无卡片或只有附魔书卡片时返回 `None`（不限制）；非书类型超过 1 种时返回空集（理论不可达，双保险）。双击编辑 `_edit_card_at` 时约束以"除本卡外的其它卡片"计算（本卡将被替换，不算既存类型），选择窗以 `prefill_data` 预填该卡数据，确认后 `replace_card` 原位替换、取消则不动。

**类与函数**

| 名称 | 签名 | 说明 |
|---|---|---|
| `EnchantCalculatorWidget.__init__` | `__init__(self, parent=None)` | setupUi + 五组信号连接 + 两次控件替换（CardListWidget / AnvilStepsTree）+ 成员初始化 + `_restore_session()` |
| `_session_path` | `_session_path(self) -> str` | 返回会话文件 `enchant_session.json` 绝对路径（AppConfigLocation，失败回退脚本目录） |
| `_restore_session` | `_restore_session(self)` | 启动时恢复卡片列表：逐项校验结构后 `add_card`；文件缺失/损坏/类型不符静默跳过 |
| `_save_session` | `_save_session(self)` | 把 `all_card_data()` 写入会话文件（`ensure_ascii=False, indent=2`），OSError 打印不抛出 |
| `save_config` | `save_config(self)` | 主窗口退出协议挂点，转调 `_save_session()` |
| `tool_name` | `@classmethod tool_name(cls) -> str` | 返回 `"EnchantCaculator"` |
| `do_choose_items` | `do_choose_items(self)` | 打开 `ChooseItemsWindow`（模态 exec，allowed 由 `allowed_item_types()` 决定）；确认后 `add_item_card` 添加卡片并 `_save_session`；未确认（`selected_data` 为 None）不动作 |
| `allowed_item_types` | `allowed_item_types(self) -> set \| None` | 计算当前允许的物品类型集合：有非书卡片 → `{"附魔书"} \| 该类型`；>1 种非书类型 → 空集；否则 None 不限 |
| `add_item_card` | `add_item_card(self, data: dict)` | 把选择窗打包数据 `{"item_name": str, "enchants": [{"id","name","level"}, ...]}` 生成为卡片加入列表 |
| `_edit_card_at` | `_edit_card_at(self, item)` | 双击卡片：取 `CARD_DATA_ROLE` 数据，以其余卡片计算类型约束，`prefill_data` 打开选择窗，确认后 `replace_card` 原位替换并保存会话 |
| `_resolve_conflicts_for_calculate` | `_resolve_conflicts_for_calculate(self, cards, dm) -> bool` | 冲突决策统一入口：检测簇 → 自动决策 → pending 弹窗（预选上次决策，取消返回 False）→ 更新 `self.conflict_choices`；无冲突时清空过期决策 |
| `_on_display_mode_changed` | `_on_display_mode_changed(self, index: int)` | 展示模式切换（0=树状图 / 1=步骤图）：`_last_plan` 为 None 不动结果区；否则 `show_plan` 用最近方案重渲染 |
| `do_clear_cards` | `do_clear_cards(self)` | 清空全部卡片、`conflict_choices` 清零、`_last_plan`/`_last_dm` 置 None、步骤图恢复占位、保存空会话 |
| `do_start_calculate` | `do_start_calculate(self)` | 开始计算主流程（见上文五步）：收集卡片 → 冲突决策 → 决策转 required 约束 → 优化 → 步骤树展示 |

**接口**

- 继承：`BaseToolWidget` + `Ui_EnchantCaculator`（`CodesUI.EnchantCaculator` 编译生成的 UI 类）。
- 依赖 import：`ChooseItemsWindow`、`CardListWidget`、`find_conflict_clusters`/`resolve_conflicts`/`ConflictResolveDialog`（conflict_resolver）、`DataManager`（enchant_data_manager）、`AnvilOptimizer`/`AnvilError`/`build_items_from_cards`（anvil_optimizer）、`AnvilStepsTree`（anvil_steps_tree）。
- 被谁 import：`Tools/__init__.py` 注册进 `TOOL_CLASSES`。
- 信号：不定义也不接收自定义信号（基类 `request_status_message` 未使用）；`save_config` 由主窗口退出流程调用。

**关键变量/常量**

| 名称 | 类型/值 | 说明 |
|---|---|---|
| `preferred_size` | `(634, 518)` | 类属性，UI 设计尺寸 |
| `selected_stuff` | `dict` | 最近一次选择窗确认后回传的物品数据 |
| `conflict_choices` | `dict`，`{簇序号: 保留的附魔ID}` | 跨卡片冲突保留决策；只影响最终合成物组成，未保留附魔仍计费；开始计算时重新检测并预选 |
| `_optimizer` | `AnvilOptimizer` | 铁砧优化器实例（`DataManager()` 单例注入） |
| `_last_plan` / `_last_dm` | 方案对象 / `DataManager` | 最近一次计算成功的方案及其数据管理器（displayMode 切换重渲染用） |
| `enchant_session.json` | 配置文件 | 位于 AppConfigLocation，内容为卡片列表 JSON，重启恢复用 |

---

## `Threads/task_AutoBackUp.py`

**功能**：备份任务的可运行对象（124 行）。`BackupTask` 继承 `QRunnable`，封装**单个**文件或文件夹压缩到目标 ZIP 的全部逻辑；自身不创建线程，由 `AutoBackUpWidget` 持有的全局 `QThreadPool`（最大并发 4）调度执行 `run()`。采用分块读取（8KB）避免大文件内存溢出，通过全局信号总线 `backup_bus` 向主线程汇报开始/进度/结果——工作线程不直接接触任何 UI。

**命名规则**：`__init__` 中预生成属性 `self.zip_name = 原文件名(不含扩展名)_YYMMDD_HHMMSS.zip`（时间戳 `datetime.now().strftime("%y%m%d_%H%M%S")`，如 `data_240808_153045.zip`）；`run()` 内再按源类型计算局部 `zip_name`——单文件取 `splitext` 去扩展名，文件夹直接用 `base_name`（文件夹名），并拼出 `dest_path = os.path.join(self.dest_dir, zip_name)`。

**run() 执行流程**：

1. `try` 块内先 `backup_bus.task_started.emit(self.task_id, os.path.basename(self.file_path))` 通知主界面任务开始；
2. 创建 `zipfile.ZipFile(dest_path, 'w', compression=zipfile.ZIP_DEFLATED)`：
   - **单文件**：记录 `total_size`（取了值但流程中未再使用，进度按增量汇报）、`open(源文件, 'rb')` 与 `zipf.open(条目名=basename, 'w')` 双上下文，循环 `src_file.read(8192)` 分块写入，每块 `backup_bus.task_progress.emit(self.task_id, len(chunk))`（增量字节数，非百分比）；
   - **文件夹**：`os.walk` 递归遍历全部子目录，每个文件 `arcname = os.path.relpath(full_path, start=root_dir)` 保留相对目录结构（如 `folder/subfolder/file.txt`）写入 ZIP，同样 8KB 分块 + 每块发增量进度；
3. 全部压缩完成：`backup_bus.task_finished.emit(self.task_id, True, f"{zip_name} 备份成功")`；
4. 异常处理：`except Exception` 捕获所有异常，`backup_bus.task_finished.emit(self.task_id, False, f"{zip_name} 备份失败: {str(e)}")`——失败信息也经完成信号回传，不在工作线程弹窗。

**类与函数**

| 名称 | 签名 | 说明 |
|---|---|---|
| `BackupTask.__init__` | `__init__(self, task_id: int, file_path: str, dest_dir: str)` | 保存任务 ID（用于主界面区分并发任务）、源路径（单文件直压 / 文件夹递归）、输出目录；预生成 `self.zip_name`（原名去扩展名_时间戳.zip） |
| `BackupTask.run` | `run(self)` | 压缩主逻辑：发 task_started → 按 basename/时间戳定 zip 名 → ZIP_DEFLATED 创建压缩包（单文件 8KB 分块 / 文件夹 os.walk 递归 + relpath 保结构 + 8KB 分块，每块发 task_progress 增量）→ 发 task_finished(成功)；任何异常发 task_finished(失败, 错误信息) |

**接口**

- 被谁 import：仅 `Tools/tool_AutoBackUp.py:15`（`do_back_up` 阶段三逐项创建并 `thread_pool.start(task)`）。
- 继承：`QRunnable`（PySide6.QtCore）。
- 信号：经模块级单例 `backup_bus`（`Utils/AutoBackUp/signals_AutoBackUp.py`，`BackupSignals(QObject)`：`task_started(int, str)`、`task_progress(int, int)` 增量、`task_finished(int, bool, str)`）发出三条信号；不接收信号。

**关键变量/常量**

| 名称 | 类型/值 | 说明 |
|---|---|---|
| `task_id` | `int` | 任务索引标识，对应 `valid_paths` 中的位置，主界面据此区分并发任务 |
| `file_path` | `str` | 源文件/文件夹绝对路径 |
| `dest_dir` | `str` | 目标 ZIP 存放目录 |
| `zip_name` | `str` | `__init__` 预生成的目标文件名属性（run 内另有同规则局部变量） |
| `8192` | 字节 | 分块读写缓冲大小（两处硬编码） |
| `zipfile.ZIP_DEFLATED` | 压缩算法 | ZIP 创建时使用的 deflate 压缩 |
| `"%y%m%d_%H%M%S"` | 时间戳格式 | 输出文件名时间戳（如 `240808_153045`） |

---

## `Threads/task_StrongHoldFinder.py`

**功能**：StrongHoldFinder 的剪贴板监听线程（71 行）。Qt 的 `QClipboard` 只允许在 GUI 线程使用，因此工作线程**只调用 Win32 序号查询**：通过 `ctypes.WinDLL("user32")` 拿到 `GetClipboardSequenceNumber`（`restype = ctypes.c_ulong`），该调用只读一个系统维护的 32 位序号——不打开剪贴板、不与其他程序争抢剪贴板所有权，一次系统调用 CPU 开销可忽略。序号相对上次发生变化即认为剪贴板内容更新，向主线程发 `clipboard_changed()` 信号；剪贴板的具体内容由主线程在槽中用 `QApplication.clipboard()` 读取（见 `tool_StrongHoldFinder` 的 `_on_clipboard_changed`）。

**轮询与去重策略**：`run()` 主循环以 `_POLL_INTERVAL_S = 0.2` 秒间隔轮询（约 200ms，对人手按 F3+C 的节奏足够灵敏）；`_last_seq is not None and seq != _last_seq` 时发信号——线程启动后第一次轮询只记录基准序号、不发信号，避免把程序启动前遗留在剪贴板里的旧内容当作"新变化"；若两次变化落在同一轮询间隔内，只对最新状态发一次信号（对人手操作节奏无影响）。

**平台兼容**：模块级常量 `_PLATFORM_SUPPORTED = sys.platform == "win32"`；仅 Windows 提供剪贴板序号接口，非 Windows 平台 `_get_clipboard_sequence = None`，`run()` 入口直接 `return`（线程立即退出），工具退回手动粘贴模式。

**生命周期**：常驻运行直到 `requestInterruption()`，停止延迟不超过约 2 个轮询周期；停止动作由工具侧的 `aboutToQuit` 兜底与 `closeEvent` 双保险触发（见 `tool_StrongHoldFinder` 文档）。

**类与函数**

| 名称 | 签名 | 说明 |
|---|---|---|
| `ClipboardListenerThread.__init__` | `__init__(self, parent=None)` | 仅初始化 `_last_seq = None`（None 表示尚未记录基准序号） |
| `ClipboardListenerThread.run` | `run(self)` | 轮询主循环：非 Windows 直接返回；否则循环——未请求中断时调 `_get_clipboard_sequence()` 取序号，与 `_last_seq` 不同且非首次则 `clipboard_changed.emit()`，更新 `_last_seq` 后 `time.sleep(0.2)` |

**接口**

- 被谁 import：仅 `Tools/tool_StrongHoldFinder.py:36`（`__init__` 中实例化并 `start()`）。
- 继承：`QThread`（PySide6.QtCore）。
- 信号：发出 `clipboard_changed()`（无参，槽在主线程执行）；不接收信号；取消采用 `QThread.requestInterruption()` 协作式中断而非自定义标志。

**关键变量/常量**

| 名称 | 类型/值 | 说明 |
|---|---|---|
| `_PLATFORM_SUPPORTED` | `bool`，`sys.platform == "win32"` | 平台开关；False 时线程空转退出、工具退回手动粘贴 |
| `_POLL_INTERVAL_S` | `0.2` 秒 | 轮询间隔（约 200ms） |
| `_user32` / `_get_clipboard_sequence` | `ctypes.WinDLL` / 函数指针 | user32 动态库与 `GetClipboardSequenceNumber`（restype `c_ulong`）；仅 win32 下创建 |
| `_last_seq` | `int \| None` | 实例属性，上次轮询到的剪贴板序号；None 表示尚未记录基准 |

---

## `Threads/task_WorldSeedRefine.py`

**功能**：世界种子精化的后台计算线程（131 行，SeedReverser 二期·路线 A）。把 `Utils/SeedReverser/world_seed_refine.refine_world_seeds` 的高位 16 bit 枚举放进工作线程执行——枚举总量为 **候选数 × 2^16**，native 引擎下完整枚举约 0.2 秒、多候选时更长，若在主线程直接计算会冻结界面。工作线程不做任何 UI 操作，只通过信号把进度/结果/错误回主线程。

**信号设计**（模块 docstring 明确给出两条客观理由）：

- 完成信号刻意命名为 `refine_finished` 而非 `finished`：`QThread` 自带 `finished` 信号（Qt 内部用它管理线程对象生命周期），自定义同名信号会遮蔽它，导致 `wait()`/退出清理等路径行为异常；
- `refine_finished` 参数用 `object` 而非 `dict`：`dict` 会被 PySide6 转 `QVariantMap`，其中世界种子值可能超出 int64（未转换的无符号位模式）而触发 shiboken 溢出钳制；`object` 直接透传 Python 对象；
- `progress` 用 `"qlonglong"` 类型：枚举总量 = 候选数 × 2^16，多候选时可能超出 Qt 默认 int 上限，必须 64 位。

**取消机制**：主线程调 `request_cancel()` 仅置 `_cancelled = True` 布尔标志（线程安全）；`run()` 把 `lambda: self._cancelled` 作为 `cancel` 回调传给枚举器，枚举器在候选间与高位步进间检查该标志，尽快退出；取消后发 `refine_finished({}, CANCELLED_SUMMARY)`（摘要标记 `"__cancelled__"`，区别于正常统计摘要）。

**run() 主流程**：`time.perf_counter()` 计时 → 调 `refine_world_seeds(self._candidates, self._biome_obs, self._version_key, on_progress=self._on_progress, cancel=lambda: self._cancelled)` → 异常分派：`ValueError`（观测点不足 / 无候选等预期错误）发 `error(str(exc))`；其它任何异常兜底发 `error(f"计算线程异常：{exc!r}")`（不能无声吞掉）→ 未取消则 `_format_summary(result.get("stages", {}), result.get("world_seeds", []), elapsed)` 生成统计摘要，发 `refine_finished(result, summary)`；已取消则发 `refine_finished({}, CANCELLED_SUMMARY)`。

**进度节流**：`_on_progress` 是枚举器的进度回调（工作线程内执行）。native 引擎自身已按 4096 迭代批量回调，此处再加一层时间节流——距上次发出不足 `_PROGRESS_INTERVAL_S`(0.1 秒) 则丢弃本次；`done >= total`（最后一步）时强制发出，保证收尾信号不丢。

**类与函数**

| 名称 | 签名 | 说明 |
|---|---|---|
| `WorldSeedRefineThread.__init__` | `__init__(self, candidates, biome_obs, version_key, parent=None)` | 列表化保存候选种子、群系观测点、版本键；`_cancelled = False`、`_last_emit = 0.0` |
| `request_cancel` | `request_cancel(self)` | 主线程调用的取消请求：仅置 `_cancelled = True` 布尔标志（线程安全） |
| `run` | `run(self)` | 精化主流程：计时 → `refine_world_seeds(on_progress, cancel)` → 预期 `ValueError` 与兜底异常发 `error` → 取消发 `refine_finished({}, "__cancelled__")` → 成功发 `refine_finished(result, summary)` |
| `_on_progress` | `_on_progress(self, done, total, msg)` | 枚举器进度回调：0.1 秒时间节流后转发为 `progress` 信号（`done >= total` 强制发出保证收尾） |
| `_format_summary` | `@staticmethod _format_summary(stages, world_seeds, elapsed) -> str` | 把统计整理成多行摘要：候选数 / 高位区间 / 枚举总量 / 实际枚举 / 引擎 / 耗时，末尾附命中种子列表（每行一个）或"未命中"提示 |

**接口**

- 被谁 import：仅 `Tools/tool_SeedReverser.py`（第 59-61 行 import，第 2120 行实例化：`WorldSeedRefineThread(candidates, biome_obs, "1.21", parent=widget)` 后连接三信号并 `start()`）。
- 继承：`QThread`（PySide6.QtCore）。
- 信号：发出 `progress("qlonglong", "qlonglong", str)`（done, total, msg）、`refine_finished(object, str)`（结果 dict + 统计摘要）、`error(str)`；不接收信号（取消通过 `request_cancel()` 方法调用而非信号）。

**关键变量/常量**

| 名称 | 类型/值 | 说明 |
|---|---|---|
| `CANCELLED_SUMMARY` | `"__cancelled__"` | 模块常量：取消结束时 `refine_finished` 的摘要标记，区别于正常统计摘要 |
| `_PROGRESS_INTERVAL_S` | `0.1` 秒 | 模块常量：progress 信号节流间隔 |
| `_candidates` / `_biome_obs` / `_version_key` | `list` / `list` / `str` | 实例状态：候选种子列表、群系观测点列表、游戏版本键 |
| `_cancelled` | `bool` | 取消标志（主线程写、工作线程读） |
| `_last_emit` | `float` | 上次 progress 发出时刻（`time.monotonic()`，仅工作线程内访问） |

---

# MapPreviewer 文档：工具控制层与渲染线程

> 覆盖文件：
> - `Tools\tool_MapPreviewer.py`（地图预览器控制层）
> - `Threads\task_MapPreviewer.py`（地图渲染线程）
>
> 本文档仅描述源码现状，所有信息均来自代码阅读，代码标识符保留英文。

---

## `Tools/tool_MapPreviewer.py`

**功能**：MapPreviewer（世界俯视群系图 + 21 种结构图标化标注）工具的 UI 控制层。继承 `BaseToolWidget` 并混入 Qt Designer 生成的 `CodesUI.MapPreviewer.Ui_mapPreviewer`，全部职责可归纳为四块：

1. **渲染编排**：把「版本 / 种子 / 半径 / 维度 / 结构勾选」打包为参数，交给后台线程 `Threads.task_MapPreviewer.MapPreviewerThread` 两阶段计算（地形采样 → 结构枚举），按 `progress` 更新进度条（百分比只进进度条，`labelInfo` 不显示数字），`render_finished` 后把结果 dict 应用到场景。按钮是单状态机：「生成地图」（从未生成）→「停止渲染」（计算中）→「更新结构」（已有地图后再点）；种子支持十进制（含负数）与 `0x` 十六进制，`_parse_seed` 做 int64 有符号范围校验。LOD 按视野预判：`radius >= 2048` 用 `cell`（4×4 方块合 1 像素快速档），否则 `block`（1 方块 = 1 像素精细档），下界/末地固定 `cell`（采样器数据本身 4 方块/像素）。

2. **无限地图渲染**：初始视野只是首屏渲染范围（±2048/±4096 方块），场景显式设 `sceneRect = ±_WORLD_LIMIT（±2^21 方块）`，拖动/缩放/定位后由 180ms 防抖 QTimer 触发 `_ensure_viewport_tiles` / `_ensure_structure_scan` 增量补渲染与补扫结构——瓦片按「距视口中心近优先」分批（单批 ≤ `_TILE_BATCH_MAX=8`）提交 `TileRenderThread`，`batch_done` 后零延迟续批直至视口补齐（`_MAX_FILL_ROUNDS=300` 兜底防互柜死循环）；瓦片缓存是加权 LRU（`_CACHE_WEIGHT_BUDGET=400`，block 瓦片权重 6、cell 权重 1），淘汰时跳过视口 ±2 瓦片格的受保护瓦片；补渲染统一沿用初始地图的 LOD 档位，不做缩放驱动的升/降级（保证视口瓦片档位一致、无混档接缝）。结构扫描把「视口扩 `_SCAN_MARGIN=128` 且超出已扫描覆盖矩形」的区域交给 `StructureScanThread`，结果并入 `_structs_seen` 去重后增量加标记（只增不删）。

3. **交互与可视化**：QGraphicsScene 场景坐标 = 世界方块坐标（1 场景单位 = 1 方块）。`eventFilter` 装在 `viewMap.viewport()` 上统一分发：滚轮锚点缩放（Ctrl+滚轮让给外层页面滚动，缩放比钳在 `[0.13, 4.0]`）、左键按住拖动（滚动条平移，Chrome 式）、MouseMove 悬停查询（`labelHover` 显示 X/Z 与群系中文名+id；初始矩阵范围外走 `_probe_biome` 单点采样探测，下界/末地用按 `(seed, dim)` 缓存的 `NetherSampler/EndSampler`，避免 MouseMove 高频重建 256 次洗牌的 Perlin 初始化）、点击结构标记复制 `/tp @s x ~ z` 命令。右键菜单提供区块网格（16 方块半透明网格，覆盖视口邻域跟随重建）、地形阴影（hillshade，仅落盘，重渲染后生效）、「填入坐标到定位栏」、「删除路径」、「适配视野」。结构标记用 Wiki EnvSprite 图标（村庄按生成群系区分变体），经 `_compose_plate_icon` 合成为「灰色底板 + 右下柔和暗影」的浮板图（仿 MC 物品展示），`ItemIgnoresTransformations` 保证不随地图缩放（JourneyMap 式恒定屏幕大小）；图标缺失回退红色圆圈。悬停 tooltip 由 MouseMove 主动接管（`_update_marker_tip` 用 data(2) 文本 + `QToolTip.showText`），因为内建 item tooltip 对 `ItemIgnoresTransformations` 项在视图变换下命中不可靠。

4. **定位系统**：坐标输入框（X/Z 分格，兼容一格填 "X, Z"）回车把视图中心移到该坐标；结构定位下拉与群系定位下拉（可输入匹配、选中即查找，手输时行编辑器按 `biome_signature_colors` 染群系标志色）分别启动 `StructureLocateThread` / `BiomeLocateThread` 扩窗查找「离输入坐标最近」的实例/出现位置，两者互斥（后定位者自动取消并移除前一定位）。定位成功画「定位链」：红点定位点（外环+内实心）→ 红色虚线连到实例 → 虚线中点上方距离文本（`≥100` 取整、否则一位小数）→ 两端坐标标签（抬升量按当前缩放把屏幕像素换算成场景单位，防被恒定屏幕大小的图标/红环压住）→ 群系定位时锇点叠加群系图标；视角自动 `fitInView` 适配两点包围盒（外扩 25%、最小视宽 384）。定位结构未被勾选时 `_ensure_locate_icon` 强制补显图标（撤下时同步还原去重表）。拖动/缩放后隐藏端点坐标标签，同种子/版本/维度重渲染会按保存的定位状态重画定位链。所有在途线程一律「request_cancel + 转入 retired 列表保引用 + epoch 丢弃迟到结果」，运行中 QThread 立即解引用会被析构导致 0xC0000409 崩溃（源码多处注释记录了这一教训）。

5. **会话持久化**：版本/种子/半径/维度/结构选择（按维度分桶）/网格与阴影开关/定位下拉选择实时落盘到用户配置目录 `map_previewer_session.json`（`QStandardPaths.AppConfigLocation`），重启自动恢复（恢复期间 `_session_ready=False` 抑制写入；恢复的下拉项 blockSignals 静默回设、不触发自动查找）。应用退出钩子 `aboutToQuit` 先 `_stop_thread`（全部线程 request_cancel + wait(5000)）再 `_persist`，`closeEvent` 双保险。本工具不调用 `setApplicationName`（会话目录由主进程应用名决定）。

**类与函数**：

模块级常量与函数之外，只有一个类 `MapPreviewerWidget`。方法按功能分组如下。

模块级函数：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_compose_plate_icon` | `_compose_plate_icon(src: QPixmap) -> QPixmap` | 把源图标合成为 36px 画布的浮板图：28px 灰色方板（`#949494`）居中，图标 `FastTransformation` 就近缩放到 24px 内缩其上（2px 边距，保留像素风），四周按 `_SHADOW_LAYERS` 四级错位矩形叠加右下偏移的柔和暗影（`#3A3A3A` 基色，由外向内 alpha 18/36/60/110，右下比左上延伸更远形成顶光投影），透明底合成。被结构标记与群系定位图标共用。 |

初始化与基类接口：

| 名称 | 签名 | 说明 |
|---|---|---|
| `MapPreviewerWidget` | `class MapPreviewerWidget(BaseToolWidget, Ui_mapPreviewer)` | 主控件类；类属性 `preferred_size = (1081, 801)` 声明默认窗口尺寸。 |
| `__init__` | `__init__(self, parent=None) -> None` | 依次：初始化约 40 个状态字段（五类线程的「在途引用 + retired 保引用列表 + epoch 序号」、瓦片缓存三表、定位激活状态、显示开关等）→ `_init_ui()` → `_init_signals()` → 连接 `QApplication.aboutToQuit`（先 `_stop_thread` 后 `_persist`，连接顺序即调用顺序）→ `_restore_session()` → 置 `_session_ready=True`。 |
| `tool_name` | `@classmethod tool_name(cls) -> str` | 实现基类接口，返回 `"MapPreviewer"`（工具注册名）。 |
| `_init_ui` | `_init_ui(self) -> None` | 创建 `QGraphicsScene` 并显式设全域 `sceneRect`（±`_WORLD_LIMIT`，无限地图的前提）；配置 `viewMap`（SmoothPixmapTransform、NoDrag、AnchorUnderMouse 缩放锚、鼠标跟踪、viewport 事件过滤器）；建 180ms 单发 QTimer `_schedule_timer`（瓦片补渲染）与 `_scan_timer`（结构扫描）；版本下拉清空后填 `structure_params.VERSION_KEYS`（收敛为 26.2/1.21.11/1.21），半径默认 2048，维度默认主世界；群系下拉设为可编辑 + 大小写不敏感 contains 过滤 completer；进度条 0~100 隐藏文本；最后 `_update_struct_menu()`。 |
| `_init_signals` | `_init_signals(self) -> None` | 连接按钮/输入：`btnRender.clicked` 与 `editSeed.returnPressed` → `_on_render_clicked`；`btnStructures` → 结构选择弹窗；半径/版本/维度 change → 持久化与切维处理；`xEdit/zEdit.returnPressed` → 坐标定位；结构/群系下拉 `currentIndexChanged` → 定位查找；群系 `lineEdit().textChanged` → `_update_biome_name_color`（手输不触发 currentIndexChanged 的互补路径）。 |

结构选择窗口与维度管理：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_on_version_changed` | `_on_version_changed(self, _) -> None` | 版本切换：可用结构集变化，`_update_struct_menu()` 清理失效选择并 `_persist()` 落盘。 |
| `_current_dimension` | `_current_dimension(self) -> str` | 把 `worldCombo` 索引经 `_DIM_COMBO_INDEX` 映射为维度键（0/1/2 → overworld/nether/end，越界回退 overworld）。 |
| `_on_dimension_changed` | `_on_dimension_changed(self, _) -> None` | 维度切换：若正在渲染先 `_cancel_render()` 并置 `_suppress_finished_label`（防旧线程迟到回调覆盖切换提示）；当前选择存入 `_selected_other[旧维度]`，换上新维度已保存的选择；`_update_struct_menu` → `_clear_map()` → `_persist()`。旧地图瓦片/标记/探测/线程语义全部跨维度错配，整体清空并提示重新生成。 |
| `_clear_map` | `_clear_map(self) -> None` | 取消瓦片/扫描/定位/群系线程，`_tile_epoch += 1` 作废迟到结果，`scene.clear()` 后复位瓦片三表、标记、悬停、扫描覆盖、结构去重与定位状态，进度条归零，`labelInfo` 提示「已切换到 X，请重新生成地图」，恢复空闲 UI。 |
| `_avail_keys` | `_avail_keys(self) -> tuple[str, ...]` | 调 `structure_map.available_structures(当前版本, dimension=当前维度)` 取可标注结构键。 |
| `_update_struct_menu` | `_update_struct_menu(self) -> None` | 选择集为 `None` 时以 `_COMMON_STRUCTS ∩ 可用集` 初始化；把选择收敛到当前可用集并存回维度桶；按勾选状态生成 `btnStructures` 的 ☑/☐ tooltip；级联重建结构定位下拉与群系定位下拉。 |
| `_on_struct_menu` | `_on_struct_menu(self) -> None` | 弹出 `ChooseStructureWindow`（图标网格勾选），Accepted 后 `get_selected()` 写回 `_selected`、刷新菜单并落盘。 |

渲染状态机与线程回调：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_on_render_clicked` | `_on_render_clicked(self) -> None` | 按钮单击：`_running` 为真则 `_cancel_render()`，否则 `_start_render()`。 |
| `_start_render` | `_start_render(self) -> None` | 先取消在途扫描/定位/群系线程；`_parse_seed` 解析种子（失败弹通知）；读半径（`_RADIUS_MAP`，缺省 2048）、排序后的结构键（允许为空 = 纯群系地图）、版本；按半径预判 LOD（≥2048 → cell）；创建 `MapPreviewerThread(seed, version, radius, keys, lod, hillshade, dimension)` 并连接 `progress/render_finished/error/finished→deleteLater`，`start()` 后置 `_running=True`、锁输入控件、按钮切「停止渲染」。 |
| `_cancel_render` | `_cancel_render(self) -> None` | 对 `_thread` 调 `request_cancel()`（仅置标志，线程安全），`labelInfo` 显示「停止中…」。 |
| `_set_running_ui` | `_set_running_ui(self, running: bool) -> None` | 状态机 UI：运行中按钮「停止渲染」；空闲时按 `_has_map` 显示「更新结构」或「生成地图」；运行中禁用版本/种子/半径/结构/维度控件。 |
| `_parse_seed` | `@staticmethod _parse_seed(text: str) -> int` | 解析种子：`0x/-0x` 前缀按 16 进制，否则 10 进制；空串与解析失败抛 `ValueError`（中文提示）；再校验落在 `[-2^63, 2^63)`。 |
| `_on_progress` | `_on_progress(self, done: int, total: int, msg: str) -> None` | 把 `(done, total)` 折算为百分比写入 `progressRender`；`total<=0` 归零。 |
| `_on_finished` | `_on_finished(self, result: dict, summary: str) -> None` | 复位 `_running` 并置 `_thread=None`（回收完全交给创建处连接的 `finished→deleteLater`，本回调到达时 `run()` 可能尚未返回，提前析构会 qFatal）；取消摘要（`CANCELLED_SUMMARY`）或空结果时按 `_suppress_finished_label` 决定显示「已停止」还是保留维度切换提示；否则 `_apply_result(result)`、`_has_map=True`、显示统计摘要、按维度弹完成通知（含结构数与采样/渲染/结构三段耗时）；`finally` 中 `_persist()`。 |
| `_on_error` | `_on_error(self, msg: str) -> None` | 复位运行态与 UI，进度条归零，`labelInfo` 显示「出错」，弹「地图渲染失败」通知。 |

定位输入与坐标定位：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_parse_coord_field` | `_parse_coord_field(self) -> tuple[int, int] \| None` | 读 X/Z 输入框：空格当 0；兼容一格填 "X, Z"（逗号/空格分隔且另一格为空）；`int(float(...))` 换算，非法返回 `None`。 |
| `_goto_coord` | `_goto_coord(self, coord) -> bool` | `viewMap.centerOn(x, z)` 平移视图中心（不改缩放），清零 `_fill_rounds` 并启动瓦片/扫描两个防抖定时器。 |
| `_on_locate_coord_clicked` | `_on_locate_coord_clicked(self) -> None` | X/Z 回车触发：解析失败弹「坐标无效」通知，否则 `_goto_coord`。 |
| `_fill_coord_field` | `_fill_coord_field(self, x: int, z: int) -> None` | 右键菜单「填入坐标到定位栏」：把右键点方块坐标写入 X/Z 分格（不触发跳转，可供结构/群系定位作起点）。 |

结构定位（下拉选中即查找）：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_update_locate_menu` | `_update_locate_menu(self) -> None` | 重建结构定位下拉：首项「选择结构」data=None + 当前版本+维度全部可用结构（`STRUCT_NAMES` 中文名）；blockSignals 静默并保留原选择。 |
| `_on_struct_choice_changed` | `_on_struct_choice_changed(self, _idx: int) -> None` | 落盘后取 `currentData`：None（回首项）= 取消在途线程、bump `_locate_epoch`、`_remove_locate()`；否则 `_start_struct_locate(key)`。 |
| `_start_struct_locate` | `_start_struct_locate(self, key: str) -> None` | 守卫链：渲染中 / 无地图（`_last is None`）/ 坐标非法分别弹通知；然后取消旧定位线程并 bump epoch、取消在途群系定位（互斥），创建 `StructureLocateThread(seed, version, key, tx, tz, dimension)`，`located` 回调按当前 epoch 闭包绑定，`finished` 回收 + deleteLater，启动后显示「结构定位中…」。 |
| `_on_locate_result` | `_on_locate_result(self, payload: dict, epoch: int) -> None` | epoch 不符（迟到）直接丢弃；空 `structures` 列表 = 未找到，按 `searched_side` 弹「已在 ±N 方块范围搜索」；命中则取 `target` 与实例 `(x, z)`、`dist`，先 `_remove_biome_locate(reset_combo=True)`（互斥清群系定位），再 `_draw_locate` 画链 + `_fit_locate_view` 适配视角，记录 `_locate_struct_key/_locate_point/_locate_inst/_locate_dist` 激活状态，`labelInfo` 显示实例名与距离，最后 `_ensure_locate_icon()` 强制补显未勾选结构的图标。 |
| `_on_locate_error` | `_on_locate_error(self, _msg: str) -> None` | 置空线程引用；非渲染中时 `labelInfo` 显示「结构定位失败（可重试）」。 |
| `_reap_locate_thread` | `_reap_locate_thread(self, th) -> None` | `finished` 回调：若还是当前线程则置 None，并从 retired 列表移除（RuntimeError 防御）。 |
| `_cancel_locate_thread` | `_cancel_locate_thread(self) -> None` | 放弃在途定位：置空引用，若在运行则 `request_cancel()` 并转入 `_locate_retired` 保引用（防析构 0xC0000409），迟到结果由 epoch 丢弃。 |

定位激活状态维护（强制图标 / 两态撤销）：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_ensure_locate_icon` | `_ensure_locate_icon(self) -> None` | 功能①：定位结构未被勾选时（初始渲染与增量扫描都不会为其建标记）用 `_add_marker(_locate_inst)` 单独补加图标；实例已在 `_structs_seen` 中则不重复添加并清空强制标记引用。 |
| `_clear_struct_activate` | `_clear_struct_activate(self) -> None` | 清结构定位激活状态：撤下 `_locate_forced_marker`（从场景与 `_markers` 移除，且仅当该实例来自强制补显才从 `_structs_seen` pop，避免增量扫描重复加图标），复位结构键与实例字段；不动定位链与共享定位点。 |
| `_remove_locate` | `_remove_locate(self) -> None` | 撤销结构定位：仅当结构定位激活时动作（防群系定位激活时误清），`_clear_struct_activate` + 清 `_locate_point/_locate_dist` + `_clear_locate_items()`。 |
| `_reset_locate_state` | `_reset_locate_state(self) -> None` | 换种子/版本/维度时整体复位结构+群系定位激活状态字段（场景项已随 `scene.clear()` 销毁，不动线程），并把结构/群系下拉静默回首项。 |

群系定位：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_update_biome_menu` | `_update_biome_menu(self) -> None` | 按维度重建群系定位下拉：主世界用 `biome_names.BIOME_CHOICES` 54 项（`resolve_biome` 解析 id，低版本不存在的 id 自然「未找到」）；下界/末地用线程模块的 `DIM_BIOME_TABLES` 各 5 项；首项「选择群系」data=None，重建时保留原选择。 |
| `_biome_key_by_id` | `_biome_key_by_id(self) -> dict` | 当前维度「群系 id → 图标内部键」映射：主世界取 `BIOME_CHOICES` 的 (label, key) 对；下界/末地取标签尾部单词作为内部键（图标文件缺失时 `_draw_locate` 自然回退菱形）。结果存入 `_biome_key_map`。 |
| `_biome_display` | `_biome_display(self, bid: int) -> str` | 群系显示名：从下拉标签取中文前缀（空格前段）；未知 id 回退 `biome_names.biome_label`。 |
| `_update_biome_name_color` | `_update_biome_name_color(self, *_args) -> None` | 行编辑器文字按 `color_for_label(currentText)` 染群系标志色（主世界 55 项 + 下界/末地 10 项）；首项或未匹配恢复默认样式。覆盖下拉选择、手输、静默回设等所有路径。 |
| `_on_biome_choice_changed` | `_on_biome_choice_changed(self, _idx: int) -> None` | 先刷新名称颜色；data=None（回首项）= 取消在途查找、bump `_biome_epoch`、`_remove_biome_locate()`；否则 `_start_biome_locate(bid)`。 |
| `_start_biome_locate` | `_start_biome_locate(self, bid: int) -> None` | 守卫链同结构定位（渲染中/无地图/坐标非法）；取消旧群系线程并 bump epoch，互斥取消在途结构定位并 bump `_locate_epoch`；创建 `BiomeLocateThread(seed, version, bid, tx, tz, dimension)`，`located` 按 epoch 绑定回调，`finished` 回收 + deleteLater，显示「群系定位中…」。 |
| `_on_biome_locate_result` | `_on_biome_locate_result(self, payload: dict, epoch: int) -> None` | epoch 丢弃；`payload["error"]` 时提示失败；空 `structures` = 未找到（提示搜索范围）；命中则 `_clear_struct_activate()`（互斥清结构激活状态、不动下拉）、`_draw_locate(..., icon_key=_biome_key_map.get(bid))`（锇点叠加群系图标）、`_fit_locate_view` 适配，记录 `_locate_point/_locate_dist/_locate_biome_id/_locate_biome_xy/_locate_biome_icon_key`，`labelInfo` 显示最近群系与距离。 |
| `_remove_biome_locate` | `_remove_biome_locate(self, reset_combo: bool = False) -> None` | 移除群系定位：未激活时不动作（防误清结构定位链）；`reset_combo=True` 时群系下拉回首项并连带 `_clear_struct_activate()`（结构定位抢占语义）；激活则清四个群系激活字段与定位链场景项。 |
| `_cancel_biome_thread` | `_cancel_biome_thread(self) -> None` | 放弃在途群系定位：bump epoch、`request_cancel()`、转入 `_biome_retired` 保引用。 |
| `_reap_biome_thread` | `_reap_biome_thread(self, th) -> None` | `finished` 回调：清当前引用、移出 retired（RuntimeError 防御）。 |

定位场景项（定位链绘制）：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_clear_locate_items` | `_clear_locate_items(self) -> None` | 移除定位点/虚线/距离与坐标标签/群系图标（换图、重渲染、新定位、删路径前）；RuntimeError 防御 `scene.clear()` 后的析构项；同时清空 `_coord_labels`。 |
| `_draw_locate` | `_draw_locate(self, tx: int, tz: int, x: int, z: int, dist: float, icon_key: str \| None = None) -> None` | 画完整定位链：0) `icon_key` 提供时加载群系图标（`biome_names.icon_path`），经 `_compose_plate_icon` 浮板合成，`ItemIgnoresTransformations` 居中锇在实例点，Z=10；图标缺失回退绿色菱形色块；1) 实例→定位点的红色虚线（Z=9）；2) 定位点：1.8 倍半径外环（半透明填充）+ 0.55 倍内实心红点（Z=10）；3) 虚线中点上方距离文本（`≥100` 取整否则一位小数，Z=11）；4) `_make_coord_label` 生成两端坐标标签。所有项 `setData(0, "locate")` 并入 `_locate_items`，随链一体销毁。 |
| `_style_loc_label` | `_style_loc_label(self, text: QGraphicsSimpleTextItem) -> None` | 定位链文本统一样式：`_LOC_TEXT_PT` 号加粗红字，`ItemIgnoresTransformations`（恒定屏幕大小）+ `ItemUsesExtendedStyleOption`。 |
| `_coord_lift` | `_coord_lift(self, at_target: bool) -> float` | 端点坐标标签的避让抬升量（场景单位）：取 `viewMap.transform().m11()`，把屏幕像素需求（`_COORD_LIFT_PX=24`，定位点端再加红环半径当量）换算成场景单位，并保留场景单位下限兜底（放大时红环/回退红圈随缩放变大）。 |
| `_make_coord_label` | `_make_coord_label(self, txt: str, ax: int, az: int, at_target: bool) -> QGraphicsSimpleTextItem` | 生成端点坐标标签：锚点上方水平居中、按 `_coord_lift` 抬升；`setData(1, (ax, az))` 记锚点坐标（供重排），手动 `addItem` 入场景。 |
| `_relayout_coord_labels` | `_relayout_coord_labels(self) -> None` | 视角适配改变缩放后重算两端标签抬升量（`_fit_locate_view` 调用）；定位链不在时静默。 |
| `_set_coord_labels_visible` | `_set_coord_labels_visible(self, visible: bool) -> None` | 拖动/缩放地图后隐藏、新定位/同世界重渲染恢复；仅作用于两个坐标标签（群系图标不在列内，拖动后保持可见）；RuntimeError 防御。 |
| `_fit_locate_view` | `_fit_locate_view(self, tx: int, tz: int, x: int, z: int) -> None` | 定位视角适配：两点包围盒（退化方向撑到 1 格）外扩 `_LOC_VIEW_PAD=0.25`，不足 `_LOC_VIEW_MIN_SPAN=384` 的方向以中心拉到最小视宽，`fitInView(KeepAspectRatio)` 后 `_clamp_zoom()`、重排坐标标签、清零续批轮次并启动瓦片/扫描防抖定时器。 |

结果应用与瓦片管理：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_apply_result` | `_apply_result(self, result: dict) -> None` | 渲染结果应用核心：由 rgb 构造 `QImage(Format_RGB888)`，按世界瓦片格（`_TILE_BLOCKS=1024`）对齐遍历「瓦片格 ∩ 地图范围」切片（512 半径等非对齐地图会产生部分瓦片），每片 `img.copy` → `QPixmap` → `addPixmap`，位置 = 交区左上方块坐标；`cell_px != 1` 时 `setScale(cell_px)` + `SmoothTransformation` 平滑放大；瓦片入 `_tiles/_tile_items/_tile_lod` 三表。随后：重建区块网格、`_render_markers` 建全部结构标记、`_scan_covered = _world_rect()` 作为增量扫描基线；同种子/版本/维度（`same_world`）时按保存的激活状态重画结构或群系定位链并恢复坐标标签可见，异世界则 `_reset_locate_state()`；最后 `_fit_view()` + `_clamp_zoom()` + 启动防抖定时器。`scene.clear()` 与 epoch bump 会一并作废旧标记与在途定位。 |
| `_world_rect` | `_world_rect(self) -> tuple[int, int, int, int]` | 当前地图实际内容的世界范围 `(bx0, bz0, bx1, bz1)`，左闭右开；`cell_px` 口径与 `_apply_result` 一致（非主世界固定 4）。 |
| `_visible_world_rect` | `_visible_world_rect(self) -> tuple[int, int, int, int]` | 视口映射到场景得到当前可见的世界方块矩形（右下 +1，同为左闭右开）。 |
| `_clamp_zoom` | `_clamp_zoom(self) -> None` | 把视口横向缩放比 `m11` 钳回 `[_ZOOM_MIN_SCALE, _ZOOM_MAX_SCALE]`（超界按比例 `scale` 补偿）。 |
| `_cancel_tile_thread` | `_cancel_tile_thread(self) -> None` | 放弃当前瓦片批：置空引用、`request_cancel()`、转入 `_tile_retired` 保引用；对已结束线程等价于纯回收。 |
| `_reap_tile_thread` | `_reap_tile_thread(self, th) -> None` | 瓦片线程 `finished` 回调：`deleteLater()` 延迟回收（事件循环执行时线程必已结束）并移出 retired。 |
| `_ensure_viewport_tiles` | `_ensure_viewport_tiles(self) -> None` | 视口补渲染调度（初始渲染完成、拖动/缩放/定位停顿 180ms 后触发）：`_last` 为空或渲染中返回；有在途批直接返回（`batch_done` 会自愈续批）；可见矩形钳到世界边界后换算瓦片格区间，收集不在 `_tiles` 的缺失瓦片，按「瓦片中心距视口中心」升序取前 `_TILE_BATCH_MAX=8` 为一批（每批 <1s 上屏，渐进铺满）；`_fill_rounds` 超过 `_MAX_FILL_ROUNDS=300` 停止；然后 `_cancel_tile_thread()` + bump `_tile_epoch`，创建 `TileRenderThread`（LOD 取 `_last` 档位，非主世界强制 cell；hillshade 取当前开关），连接 `tile_done/batch_done/error/finished` 并启动。 |
| `_on_tile_done` | `_on_tile_done(self, payload: dict, epoch: int) -> None` | 单瓦片完成：epoch 不符或无地图丢弃；rgb → `QImage(RGB888)` → `QPixmap`，替换场景旧项（`setScale` + Smooth 同初始切片）；LRU 记账：`_tiles.pop` 后重插队尾（最近使用），更新 `_tile_lod`，最后 `_evict_tiles()`。不在此重启调度（批次进行中 `_ensure_viewport_tiles` 有保护，收尾由 `batch_done` 统一续批）。 |
| `_evict_tiles` | `_evict_tiles(self) -> None` | 加权 LRU 淘汰：先算视口 ±2 瓦片格的受保护集合；总权重（block=6、cell=1）超 `_CACHE_WEIGHT_BUDGET=400` 时从 `_tiles` 最旧端找第一个无保护瓦片移除（含场景项 removeItem 与三表清理）；全部受保护则宁可超预算也不杀视口内瓦片。预算依据：极限缩小视口所需瓦片总量（1080p 约 63 格、2.5K 屏约 280 格），否则铺满过程新旧互柜永远补不齐。 |
| `_on_tile_batch_done` | `_on_tile_batch_done(self, epoch: int) -> None` | 整批完成：epoch 校验后 `_cancel_tile_thread()`（线程已结束仅回收引用）并重启 `_schedule_timer` 零延迟续批（渐进铺满自愈）。 |
| `_on_tile_error` | `_on_tile_error(self, msg: str) -> None` | 回收线程引用并弹「瓦片渲染失败」通知。 |
| `_rebuild_grid` | `_rebuild_grid(self) -> None` | 无限区块网格：移除旧项后，若 `_grid_on` 且有地图，在「可见范围 ±2 瓦片格」（钳到世界边界）内用 `QPainterPath` 画 16 方块间距的横竖线（`_CHUNK_GRID_COLOR` 半透明白，`QPen` 宽 0），Z=5。开关守卫放在本函数内兜住全部调用点（修复「取消勾选后缩放/拖动网格复活」的用户反馈 bug）。 |
| `_fit_view` | `_fit_view(self) -> None` | 首屏视图适配：无限地图下 sceneRect 会随瓦片铺设膨胀，不能再用 sceneRect，固定 `fitInView(self._fit_rect(), KeepAspectRatio)`。 |
| `_fit_rect` | `_fit_rect(self)` | 首屏适配目标 = `_world_rect()` 的 `QRectF`。 |

视图交互（eventFilter 分发 / 缩放 / 拖拽 / 悬停 / 点击复制）：

| 名称 | 签名 | 说明 |
|---|---|---|
| `eventFilter` | `eventFilter(self, obj, ev) -> bool` | 视口事件统一入口（viewport 会消费地图区域鼠标事件，控件层覆写收不到）：`Wheel` → `_on_wheel`（无地图放行）；`ContextMenu` → `_show_context_menu`；有地图时 `MouseButtonPress/MouseMove/MouseButtonRelease` 分别转 `_on_press/_on_move/_on_release`；其余走基类。 |
| `_show_context_menu` | `_show_context_menu(self, global_pos) -> None` | 右键菜单：「区块网格」「地形阴影」复选 + 分隔线；有地图加「填入坐标到定位栏」；定位链存在加「删除路径」；「适配视野」。执行对应动作：填坐标把右键点场景坐标（钳在 `_WORLD_LIMIT` 内）写入定位输入框。 |
| `_delete_locate_path` | `_delete_locate_path(self) -> None` | 右键「删除路径」= 手动撤销定位：按激活方（结构键或群系 id）取消在途线程、bump epoch、调对应 remove 方法并静默回设下拉回首项；无激活状态但场景项残留时仅清场景；`labelInfo` 提示「已删除定位路径」。 |
| `_set_struct_combo_index` | `_set_struct_combo_index(self, idx: int) -> None` | 结构下拉静默回设（blockSignals 防触发新一轮查找/撤销）。 |
| `_set_biome_combo_index` | `_set_biome_combo_index(self, idx: int) -> None` | 群系下拉静默回设，并刷新名称颜色。 |
| `_toggle_hillshade` | `_toggle_hillshade(self) -> None` | 翻转地形阴影开关并落盘；已有地图时弹「重新生成地图后生效」通知（不自动重渲染）。 |
| `_toggle_grid` | `_toggle_grid(self) -> None` | 翻转网格开关并落盘，`_rebuild_grid()`（守卫在内：开启重建/关闭移除）。 |
| `_on_wheel` | `_on_wheel(self, ev) -> bool` | 滚轮缩放：带 Ctrl 修饰返回 False（留给外层滚动页面）；否则按 `1.25/0.8` 缩放并钳制，实际缩放变化时收起标记提示、隐藏端点坐标标签（导航语义）、清零续批轮次、启动瓦片/扫描定时器并重建网格；恒返回 True。 |
| `_on_press` | `_on_press(self, ev) -> bool` | 左键按下：收起标记提示，记录 `_pan_start`，光标切 ClosedHand，返回 True；其他键放行。 |
| `_on_move` | `_on_move(self, ev) -> bool` | 拖拽中：增量滚动水平/垂直滚动条（Chrome 式跟随）、隐藏端点坐标标签、清零续批轮次、启动两个定时器、重建网格；非拖拽则 `_update_hover(pos)` 悬停查询。 |
| `_on_release` | `_on_release(self, ev) -> bool` | 结束拖拽（光标还原）；若本次按下未发生拖拽且是左键，则视为点击 → `_click_map(pos)` 复制。 |
| `_scene_block` | `_scene_block(self, view_pos) -> tuple[int, int] \| None` | 视图坐标 → 世界方块坐标（场景坐标即方块坐标，取整）。 |
| `_update_hover` | `_update_hover(self, pos) -> None` | 悬停查询：`biomes` 矩阵按噪声格索引（`方块 >> 2`，群系判定层与游戏 F3 一致）取 id，`labelHover` 显示 "X x Z z | 群系中文名 (id n)"；索引落在初始矩阵范围外（无限地图新区域）时改走 `_probe_biome` 单点探测，失败只显示坐标；范围内还调 `_update_marker_tip` 弹标记提示。 |
| `_dim_probe_sampler` | `_dim_probe_sampler(self, dim: str)` | 悬停探测用维度采样器，按 `(seed, dim)` 缓存实例（`_probe_samplers`）：nether → `NetherSampler`、end → `EndSampler`（函数内懒 import）；避免 MouseMove 高频重建 256 次洗牌的 Perlin 初始化。 |
| `_probe_biome` | `_probe_biome(self, bx: int, bz: int) -> int \| None` | 范围外悬停的单点群系探测：下界按噪声格 `biome_at(bx>>2, bz>>2)`；末地按 chunk 级 `biome_at_chunk(bx>>4, bz>>4)`（与地图渲染每像素=所在 chunk 群系一致）；主世界用 `sample_region(bx & ~3, bz & ~3, 4, 4, surface_mode=True)` 取 `[0,0]`（与渲染同语义）；任何异常返回 None（零 UI 阻塞风险）。 |
| `_marker_at` | `_marker_at(self, scene_pos)` | 标记命中判定：遍历 `_markers`，用 data(1) 存的锚点坐标算距离平方取最近者，距离 ≤ `_MARKER_HIT_R=14`（场景单位=方块）才命中；不依赖 item 几何（图标项与椭圆项 shape/rect 语义不同）；点击复制与悬停 tooltip 共用。 |
| `_update_marker_tip` | `_update_marker_tip(self, view_pos) -> None` | 主动悬停 tooltip：命中标记后若与 `_hover_tip_item` 相同且 `QToolTip` 可见则不重复刷（防闪烁），否则 `QToolTip.showText` 显示 data(2) 文本。 |
| `_clear_marker_tip` | `_clear_marker_tip(self) -> None` | 隐藏主动 tooltip（移出标记/无地图/拖拽/缩放时）。 |
| `_click_map` | `_click_map(self, pos) -> None` | 点击命中标记时把 data(0) 的 `/tp @s x ~ z` 写入剪贴板并弹「已复制」通知。 |

结构标记渲染与视野增量扫描：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_render_markers` | `_render_markers(self, structs: list) -> None` | 重建全部结构标记：收起提示、移除旧标记项（RuntimeError 防御）、清空 `_markers` 与 `_structs_seen`，逐个 `_add_marker`。初始渲染与按钮重渲染时调用。 |
| `_add_marker` | `_add_marker(self, st: dict) -> None` | 单个结构 → 标记项并入去重表：`st_icons.display_name` 生成显示名（村庄按群系取变体名）；`_structs_seen[(key, x, z)] = st`；tooltip = "显示名 (x, z)\n点击复制 /tp 命令"；`st_icons.icon_path(key, biome)` 命中且 QPixmap 有效时构建 `QGraphicsPixmapItem`（`_compose_plate_icon` 浮板合成、居中 offset、`ItemIgnoresTransformations` 恒定屏幕大小、Z=10），否则回退红色圆圈椭圆（半径 `_MARKER_R=10`）；data 约定：0=`/tp` 命令、1=锚点 `(x, z)`、2=tooltip 文本；裸构造项手动 `addItem` 入场景并入 `_markers`。 |
| `_ensure_structure_scan` | `_ensure_structure_scan(self) -> None` | 结构增量扫描调度（防抖后调用）：无地图/渲染中/在途扫描返回；无勾选结构返回；可见矩形扩 `_SCAN_MARGIN=128`（钳世界边界）且边长超 `_SCAN_MAX_SIDE=8192` 时以视口中心截断；与 `_scan_covered` 求交判断是否已覆盖，未覆盖才 bump `_scan_epoch` 并创建 `StructureScanThread(seed, version, view, keys, dimension)` 提交（信号按 epoch 绑定）。 |
| `_cancel_scan_thread` | `_cancel_scan_thread(self) -> None` | 放弃在途扫描：bump epoch（迟到结果丢弃）、`request_cancel()`、转入 `_scan_retired` 保引用。 |
| `_reap_scan_thread` | `_reap_scan_thread(self, th) -> None` | 扫描线程 `finished` 回调：`deleteLater()` 回收并移出 retired。 |
| `_on_scan_done` | `_on_scan_done(self, payload: dict, epoch: int) -> None` | 扫描完成：清当前引用；epoch 不符/无地图/渲染中丢弃；把 `view` 并入 `_scan_covered`（取并集）；新结构按 `(struct, x, z)` 去重后 `_add_marker`（只增不删：拖回旧区域标记仍在）；最后重启 `_scan_timer` 防抖自检一轮（拖动连续时的自愈）。 |
| `_on_scan_error` | `_on_scan_error(self, msg: str) -> None` | 扫描线程异常：已被取消的孤儿线程（`_scan_thread` 已为 None）静默；否则 print 日志并在非渲染中时提示「结构扫描失败（可点「更新结构」重试）」。 |

会话持久化与退出：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_session_path` | `_session_path(self) -> str` | 会话文件路径 = `QStandardPaths.writableLocation(AppConfigLocation) + "/" + _SESSION_FILE`，目录不存在则创建。 |
| `_persist` | `_persist(self, *_) -> None` | 实时落盘：`_session_ready` 之前不写；组装会话 dict（字段见下）以 UTF-8、`ensure_ascii=False`、indent=2 写 JSON；OSError 时 print 失败信息。可直连信号槽（`*_` 吞掉信号参数）。 |
| `_restore_session` | `_restore_session(self) -> None` | 恢复会话：文件不存在或非 dict 直接返回；逐字段类型校验后回设——版本/半径需在下拉中能找到；维度回设 `_active_dimension` 与 `worldCombo`；`selected` 过滤到当前可用集；`selected_other` 按维度恢复；当前维度选择覆盖同名桶；网格/阴影布尔；结构/群系下拉 `findData` 静默回设（`i > 0` 才回设，首项不触发自动查找）；群系回设放在菜单按恢复维度重建之后（跨维度 id 表不同），并刷新名称颜色。 |
| `save_config` | `save_config(self) -> None` | 主窗口退出协议（save_all_tools_config）入口，内部即 `_persist()`。 |
| `_stop_thread` | `_stop_thread(self) -> None` | 退出前停止全部线程：停两个定时器；汇集在途 + retired 五类线程引用并清空；逐个 `request_cancel() + wait(5000)` 确认结束再 `setParent(None)`；RuntimeError 防御性忽略（退出阶段 C++ 对象可能已析构）。运行中 QThread 退出阶段被析构会 0xC0000409。 |
| `closeEvent` | `closeEvent(self, event) -> None` | 窗口关闭即 `_stop_thread()`（aboutToQuit 的双保险），再走基类。 |

**接口**：

- **被哪些模块 import**：
  - `Tools/__init__.py`：`from .tool_MapPreviewer import MapPreviewerWidget`，注册进 `TOOL_CLASSES`（工具集合主入口）。
  - `Utils/MapPreviewer/choose_structure.py` 文档字符串注明其调用方为本文件（`ChooseStructureWindow` 以 `exec()` 弹出，`get_selected()` 回写选择集）。
- **接收的信号（连接的后台线程）**：
  - `MapPreviewerThread`：`progress` → `_on_progress`；`render_finished` → `_on_finished`；`error` → `_on_error`；`finished` → `deleteLater`。
  - `TileRenderThread`：`tile_done` → `_on_tile_done`（epoch 闭包）；`batch_done` → `_on_tile_batch_done`（epoch 闭包）；`error` → `_on_tile_error`；`finished` → `_reap_tile_thread` + `deleteLater`。
  - `StructureScanThread`：`structures_done` → `_on_scan_done`（epoch 闭包）；`error` → `_on_scan_error`；`finished` → `_reap_scan_thread` + `deleteLater`。
  - `StructureLocateThread`：`located` → `_on_locate_result`（epoch 闭包）；`error` → `_on_locate_error`；`finished` → `_reap_locate_thread` + `deleteLater`。
  - `BiomeLocateThread`：`located` → `_on_biome_locate_result`（epoch 闭包）；`finished` → `_reap_biome_thread` + `deleteLater`。
- **依赖的 Utils/内部模块**：
  - `Threads.task_MapPreviewer`：`MapPreviewerThread`、`TileRenderThread`、`StructureScanThread`、`StructureLocateThread`、`BiomeLocateThread`、`CANCELLED_SUMMARY`、`DIM_BIOME_TABLES`、`_TILE_BLOCKS`。
  - `Utils.Public.notification.NotificationWidget`（通知弹窗，样式常量与 SeedReverser 一致）。
  - `Utils.Public.structure_icons`（别名 `st_icons`：`icon_path` / `display_name`）。
  - `Utils.MapPreviewer.biome_colors.biome_cn_name`（悬停群系中文名）。
  - `Utils.MapPreviewer.choose_structure.ChooseStructureWindow`（结构选择弹窗）。
  - `Utils.Public.structure_map.available_structures`（版本+维度可用结构集）。
  - `Utils.Public.biome_names`（`BIOME_CHOICES` / `resolve_biome` / `biome_label` / `icon_path`）。
  - `Utils.Public.structure_params`（`VERSION_KEYS` / `DIMENSION_NAMES` / `STRUCT_NAMES`）。
  - `Utils.Public.biome_signature_colors.color_for_label`（群系下拉标志色）。
  - 函数内懒 import：`Utils.MapPreviewer.nether_end_sampler.NetherSampler / EndSampler`（`_dim_probe_sampler`）、`Utils.MapPreviewer.map_sampler.sample_region`（`_probe_biome`）。
  - `CodesUI.MapPreviewer.Ui_mapPreviewer`（Qt Designer 生成的 UI）、`.tool_base.BaseToolWidget`（工具基类）。
  - 标准库与 PySide6：`json`、`os`、`collections.OrderedDict`；QtGui（QBrush/QColor/QFont/QImage/QPainter/QPainterPath/QPen/QPixmap/QPolygonF）、QtCore（QEvent/QPointF/QRectF/QStandardPaths/Qt/QTimer）、QtWidgets（QApplication/QComboBox/QCompleter/QGraphicsItem/QGraphicsLineItem/QGraphicsPixmapItem/QGraphicsScene/QGraphicsSimpleTextItem/QGraphicsView/QMenu/QToolTip）。

**关键变量/常量**：

模块常量：

| 常量 | 值 | 说明 |
|---|---|---|
| `_SESSION_FILE` | `"map_previewer_session.json"` | 会话文件名（用户配置目录下）。 |
| `_MARKER_R` | `10.0` | 结构标记半径（场景像素=方块单位），图标缺失时的红圈回退用。 |
| `_MARK_ICON_SIZE` | `28` | 结构图标显示尺寸（屏幕像素），`ItemIgnoresTransformations` 下恒定，不随地图缩放。 |
| `_MARKER_HIT_R` | `14.0` | 标记命中半径（场景单位=方块），点击复制与悬停 tooltip 共用判定。 |
| `_SCAN_MARGIN` | `128` | 增量结构扫描视口扩边（结构锚点容错）。 |
| `_SCAN_MAX_SIDE` | `8192` | 单次扫描边长上限（= 最大半径 4096 地图边长，极端缩小时扫描量钳在与全图初始枚举同量级）。 |
| `_NOTIFY_DURATION_MS` / `_NOTIFY_TITLE_SIZE` / `_NOTIFY_MESSAGE_SIZE` / `_NOTIFY_PADDING` | `6000` / `16` / `14` / `(20, 16, 20, 16)` | 通知样式（与 SeedReverser 一致）。 |
| `_RADIUS_MAP` | `{"2048": 2048, "4096": 4096}` | 视野半径下拉文本 → 方块半径（512/1024 已移除）。 |
| `_ZOOM_MIN_SCALE` / `_ZOOM_MAX_SCALE` | `0.13` / `4.0` | 缩放钳制（视口缩放比 = 屏幕像素/方块）；最小取全图适配值略下，再小会让视口所需瓦片总量超出缓存预算导致重复渲染。 |
| `_CACHE_WEIGHT_BUDGET` / `_CACHE_W_BLOCK` | `400` / `6` | 瓦片缓存加权 LRU 预算与 block 瓦片权重（cell=1；约 78MB~200MB）。 |
| `_TILE_BATCH_MAX` | `8` | 单批瓦片数上限（每批 <1s 上屏，距视口中心近的优先）。 |
| `_MAX_FILL_ROUNDS` | `300` | 渐进铺满续批轮次上限（防极端视口/缓存互柜导致无限补渲染）。 |
| `_WORLD_LIMIT` | `1 << 21` | 可导航世界边界（±2^21 方块，与采样器安全范围一致）；必须显式设为 sceneRect，否则 QGraphicsScene 自动跟随瓦片包围盒会把视图钳死。 |
| `_COMMON_STRUCTS` | `("village", "desert_pyramid", "swamp_hut")` | 「常用」预设结构（首次无会话时的默认勾选）。 |
| `_DIM_COMBO_INDEX` | `{0: "overworld", 1: "nether", 2: "end"}` | 维度下拉索引 → 维度键。 |
| `_LOC_PIN_R` / `_LOC_PIN_COLOR` / `_LOC_LINE_COLOR` / `_LOC_LINE_WIDTH` / `_LOC_TEXT_COLOR` / `_LOC_TEXT_PT` | `6.0` / 红 `#FF4040` / `rgba(255,64,64,220)` / `2.0` / `#FF6060` / `10` | 定位点与虚线、距离文本样式（红色虚线 + 恒定屏幕大小文本）。 |
| `_LOC_VIEW_PAD` / `_LOC_VIEW_MIN_SPAN` | `0.25` / `384.0` | 定位视角适配：包围盒外扩比例与最小视宽（太近仍拉到可辨识视野）。 |
| `_COORD_LIFT_PX` | `24.0` | 端点坐标标签避让量（屏幕像素设计值，按当前缩放换算成场景单位）。 |
| `_MARK_PAD` / `_MARK_PIX_SIZE` / `_MARK_PLATE` / `_MARK_SHADOW` / `_SHADOW_LAYERS` | `4` / `36` / `#949494` / `#3A3A3A` / `((3,4,18),(2,4,36),(1,3,60),(1,2,110))` | 浮板图标合成参数（画布尺寸、底板灰、影基色、暗影四层：左上扩、右下扩、alpha）。 |
| `_CHUNK_GRID_SIZE` / `_CHUNK_GRID_COLOR` | `16` / `rgba(255,255,255,28)` | 区块网格间距（方块）与颜色。 |

实例状态（`__init__` 建立，按用途分组）：

| 变量 | 类型/初值 | 说明 |
|---|---|---|
| `_thread` / `_running` | `None` / `False` | 主渲染线程引用（None=空闲）与运行标志。 |
| `_scan_thread` / `_scan_retired` / `_scan_epoch` / `_scan_covered` | `None` / `[]` / `0` / `None` | 结构增量扫描：在途线程、已放弃但仍在跑的保引用列表、批序号（迟到结果丢弃）、已覆盖扫描的世界矩形 `(bx0,bz0,bx1,bz1)`。 |
| `_structs_seen` | `{}` | 已知结构去重表：`(struct, x, z) → 结果 dict`（初始 + 增量扫描合并）。 |
| `_has_map` | `False` | 是否已生成过地图（决定空闲按钮文案「生成地图/更新结构」）。 |
| `_tile_thread` / `_tile_retired` / `_tile_epoch` / `_fill_rounds` | `None` / `[]` / `0` / `0` | 瓦片增量渲染：在途线程、retired 保引用、批序号、渐进铺满续批轮次（交互触发清零）。 |
| `_tiles` / `_tile_items` / `_tile_lod` | `OrderedDict()` / `{}` / `{}` | 已渲染瓦片表（`(tx,tz) → QPixmap`，插入序即 LRU 序）、场景像素项表、每瓦片 LOD 档（"block"/"cell"），同键同步增删。 |
| `_last` | `None` | 最近一次渲染载荷 dict（悬停查询、重渲染 same_world 判断、瓦片坐标系与 LOD/维度口径均取自此）。 |
| `_grid_item` | `None` | 区块网格图形项（快速移除/重建）。 |
| `_markers` / `_hover_tip_item` | `[]` / `None` | 结构标记列表与当前主动 tooltip 指向的标记。 |
| `_selected` / `_selected_other` / `_active_dimension` | `None` / `{}` / `"overworld"` | 当前维度结构选择集（None=未初始化）、其他维度的选择桶（维度切换时互换）、当前维度键。 |
| `_probe_samplers` | `{}` | 悬停探测采样器缓存：`(seed, dim) → NetherSampler/EndSampler` 实例。 |
| `_suppress_finished_label` | `False` | 维度切换取消在途渲染后，迟到的「已停止」不覆盖切换提示。 |
| `_session_ready` | `False` | 会话恢复完成前抑制实时保存。 |
| `_grid_on` / `_hillshade_on` | `True` / `True` | 显示开关（右键菜单切换）；阴影切换后提示重渲染生效。 |
| `_locate_thread` / `_locate_retired` / `_locate_epoch` | `None` / `[]` / `0` | 结构定位：在途线程、retired、批序号。 |
| `_locate_items` / `_coord_labels` | `[]` / `[]` | 定位链场景项（定位点/虚线/距离/坐标标签/图标）与端点坐标标签两项（拖动后隐藏）。 |
| `_locate_struct_key` / `_locate_point` / `_locate_inst` / `_locate_dist` | `None` / `None` / `None` / `0.0` | 结构定位激活状态：结构键、定位点方块坐标、定位实例 dict（图标强制显示与「移除定位」用；换种子/版本/维度复位）、距离。 |
| `_biome_thread` / `_biome_retired` / `_biome_epoch` | `None` / `[]` / `0` | 群系定位：在途线程、retired、批序号。 |
| `_locate_biome_id` / `_locate_biome_xy` / `_locate_biome_dist` / `_locate_biome_icon_key` | `None` / `None` / `0.0` / `None` | 群系定位激活状态：群系 id、实例点方块坐标、距离、图标内部键（结构/群系定位互斥，后定位者移除前一定位）。 |
| `_biome_key_map` | `{}` | 群系 id → 图标内部键（下拉重建时更新）。 |
| `_locate_forced_marker` | `None` | 功能①强制图标（定位结构未被勾选时补显；移除定位时撤下并还原去重表）。 |
| `_pan_start` | `None` | 拖拽平移起点（视图坐标，Chrome 式拖动跟随）。 |
| `_schedule_timer` / `_scan_timer` | 180ms 单发 QTimer | 拖动/缩放后延迟调度瓦片补渲染 / 结构增量扫描（避免拖动中每像素重排）。 |
| `_scene` | `QGraphicsScene` | 场景：sceneRect 显式 ±`_WORLD_LIMIT`；场景坐标 = 世界方块坐标。 |

**会话 JSON 持久化字段**（`_persist` 写入 / `_restore_session` 恢复，文件 `map_previewer_session.json`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `version` | str | 版本下拉当前文本（恢复时需能在下拉中找到）。 |
| `seed_text` | str | 种子输入框原文（未解析，重启后仍可回车重渲染）。 |
| `radius` | str | 视野半径下拉文本（"2048"/"4096"）。 |
| `dimension` | str | 当前维度键（"overworld"/"nether"/"end"）。 |
| `selected` | list[str] | 当前维度勾选的结构键（排序后写入）。 |
| `selected_other` | dict[str, list[str]] | 其他维度的结构选择桶（键为维度键）。 |
| `grid` | bool | 区块网格开关。 |
| `hillshade` | bool | 地形阴影开关。 |
| `locate_struct` | str \| null | 结构定位下拉的当前结构键（恢复时静默回设，不触发自动查找；首项/None 不回设）。 |
| `locate_biome` | int \| null | 群系定位下拉的当前群系 id（同上；恢复放在菜单按维度重建之后）。 |

---

## `Threads\task_MapPreviewer.py`

**功能**：MapPreviewer 的全部后台计算线程，把地形采样、地图渲染、结构枚举、瓦片增量渲染与结构/群系定位放进工作线程；线程内不做任何 UI 操作，只通过 Qt 信号把进度/结果/错误回主线程。

**信号设计要点**（模块 docstring 明确说明）：
- 统一进度信号 `progress(qlonglong, qlonglong, str)`（done, total, 消息）。
- 完成信号刻意命名为 `render_finished` 而非 `finished`：QThread 自带 `finished` 信号（Qt 内部用它管理线程对象生命周期），自定义同名信号会遮蔽它。
- 载荷用 `object` 而非 `dict`：结果含 numpy 数组与无符号位模式种子，`QVariantMap` 转换可能触发 shiboken 溢出钳制。
- 错误信号 `error(str)`。

**取消机制**：主线程调 `request_cancel()` 仅置布尔标志（线程安全）；各线程在采样行间/渲染瓦片间/结构间/扩窗轮间检查，尽快退出；被取消的 `MapPreviewerThread` 最终发 `render_finished({}, CANCELLED_SUMMARY)`（`CANCELLED_SUMMARY = "__cancelled__"`，与正常统计摘要区分），瓦片线程被取消则不发 `batch_done`，扫描/定位线程被取消则静默不发结果——迟到的结果由控制层按 epoch 序号丢弃。

**进度节流**：native 采样引擎自身按 30ms 批量回调、纯 Python 路径按行回调，线程内再统一加 0.1s 时间节流（`_PROGRESS_INTERVAL_S`），`done >= total` 的最后一步强制发出保证收尾。

**类与函数**：

模块常量：

| 名称 | 值 | 说明 |
|---|---|---|
| `CANCELLED_SUMMARY` | `"__cancelled__"` | 取消结束时的 `render_finished` 摘要标记（区别于正常统计摘要）。 |
| `_PROGRESS_INTERVAL_S` | `0.1` | 进度信号时间节流间隔（秒）。 |
| `_TILE_BLOCKS` | `1024` | 瓦片边长（方块），仅控制增量渲染粒度（与结构枚举/进度条单位无耦合）。 |
| `_TILE_PAD_CELLS` | `2` | 瓦片扩边采样格数：hillshade 是 horn 3x3 梯度 + 3x3 平滑两层邻域，单瓦片边界线性外推只是近似；四边多采 pad 个噪声格（每边 pad*4 方块，总宽 +pad*8），渲染后裁掉边缘，跨瓦片阴影无缝；pad=2 时外圈 1 格 horn 外推不进入内区平滑窗口，内区与整图渲染 bit-exact，开销仅约 3%。 |
| `NETHER_BIOMES` | 5 项元组 | 下界群系 (标签, cubiomes biomes.h 枚举 id)：下界荒地 8、灵魂沙峡谷 170、绯红森林 171、诡异森林 172、玄武岩三角洲 173（与 `nether_end_sampler` 同源）。 |
| `END_BIOMES` | 5 项元组 | 末地群系 (标签, id)：末地 9、末地小型岛屿 40、末地中部高地 41、末地高地 42、末地荒地 43。 |
| `DIM_BIOME_TABLES` | `{"nether": NETHER_BIOMES, "end": END_BIOMES}` | 维度键 → 群系 (标签, id) 表（主世界由 UI 侧按 `biome_names.BIOME_CHOICES` 动态填充）。 |

`MapPreviewerThread(QThread)`——整幅地图渲染 + 结构枚举主线程：

| 名称 | 签名 | 说明 |
|---|---|---|
| （信号） | `progress = Signal("qlonglong", "qlonglong", str)`；`render_finished = Signal(object, str)`；`error = Signal(str)` | 统一进度 / 完整结果 dict + 统计摘要 / 错误消息。 |
| `__init__` | `__init__(self, seed: int, version_key: str, radius_blocks: int, struct_keys=None, parent=None, lod: str = "block", hillshade: bool = False, dimension: str = "overworld")` | 存参数；`struct_keys` 语义区分 `None`（未指定 = 全部可标注结构）与 `[]`（明确不标任何结构，纯群系地图），不可用 `or None` 混同；`lod` 非法回退 `"block"`；`dimension` 非法回退 `"overworld"`；非主世界强制 `lod="cell"`（数据固定 4 方块/像素）；初始化 `_cancelled=False` 与 `_last_emit=0.0`。 |
| `request_cancel` | `request_cancel(self)` | 置 `_cancelled = True`（主线程调用，线程安全）。 |
| `run` | `run(self)` | 入口：`try: self._run_impl()` 除兜底任何异常都 `error.emit(f"渲染线程异常：{exc!r}")`，不让异常无声吞掉。 |
| `_run_impl` | `_run_impl(self)` | 两阶段主流程（详见下方「重点流程」）。 |
| `_on_sample_progress` | `_on_sample_progress(self, done, total, msg)` | 采样进度回调（工作线程侧）：转 int/str 后转发 `_emit_progress`。 |
| `_emit_progress` | `_emit_progress(self, done, total, msg)` | 进度统一出口：`time.monotonic()` 距上次发出 ≥0.1s 或 `done >= total`（收尾）才 `progress.emit`，并更新 `_last_emit`。 |

`_run_impl` 重点流程（分块采样 → 渲染 → 结构枚举 → 结果组装）：

1. **阶段 1：地形采样**。主世界调 `Utils.MapPreviewer.map_sampler.sample_region(seed, version, 0, 0, size, size)`（`size = radius*2`），带四个开关：`want_depth=True`（水深渐变/恶地色带，零采样成本）、`want_temp_humid=True`（草色 tint，零采样成本）、`surface_mode=True`（表面层重判，消除高山内部切片误判溶洞）、`on_progress`/`cancel`（行级取消与进度）。下界/末地按维度选择 `sample_region_nether` / `sample_region_end`（`Utils.MapPreviewer.nether_end_sampler`）。计时得 `t_sample`；`_cancelled` 或 `map_res["cancelled"]` 时发 `({}, CANCELLED_SUMMARY)` 返回。
2. **阶段 1.5：地图渲染**。主世界按 LOD：`cell` → `render_cell_rgb(biomes, temp, humid, depth, hillshade)`（4x4 方块合 1 像素快速档）；`block` → `render_block_rgb(..., on_progress=on_render, hillshade, seed, origin_bx, origin_bz)`（1 方块 = 1 像素精细档，`on_render` 把渲染进度折算进采样进度段且不越界）。下界/末地跳过渲染，直接复用采样器输出的 `map_res["rgb"]`。结果回写 `map_res["rgb"]` 与 `map_res["lod"]`，计时得 `t_render`。
3. **阶段 2：结构枚举**。结构数基数取 `len(self._struct_keys or available_structures(...))`（`_struct_keys` 为 `[]` 时基数 1，保证进度总量不为 0）；调 `Utils.Public.structure_map.enumerate_structures(seed, version, (-radius, -radius, +radius, +radius), struct_keys, on_progress, cancel, dimension)`——21 种结构按维度正向定位 + cubiomes 位级群系校验（与 finders.c `isViableStructurePos` 位级一致），结构粒度回调进度（总量 = 采样行数 + 结构数，`on_struct` 把 `done_base + done / rows_total + total` 换算成统一进度），区域间/结构间可取消。计时得 `t_struct`；取消则发 CANCELLED_SUMMARY 返回。
4. **结果组装**：`result = dict(map_res)` 并补 `structures`（含 `x/z/struct/name/biome` 等键的结构列表）、`radius`、`seed`、`version`、`dimension`、`t_sample/t_render/t_struct`；summary 形如「完成：引擎 X｜采样 a s｜渲染 b s｜结构 c s｜标记 n 个」；`render_finished.emit(result, summary)`。

`StructureLocateThread(QThread)`——结构定位（扩窗搜索最近实例）：

| 名称 | 签名 | 说明 |
|---|---|---|
| （信号） | `located = Signal(object)`；`error = Signal(str)` | 载荷 dict：命中 `{struct, name, x, z, biome, target: (tx,tz), dist, searched_side}`；未找到 `{"structures": [], "target", "searched_side"}`。 |
| `_LOCATE_START_SIDE` / `_LOCATE_MAX_SIDE` | `512` / `8192` | 扩窗起始边长（覆盖末地城/要塞典型最小间距，村庄等密集结构首轮命中）与上限（与 `_SCAN_MAX_SIDE` 同源）。 |
| `__init__` | `__init__(self, seed, version_key, struct_key, tx, tz, parent=None, dimension="overworld")` | 存目标结构与目标点坐标，维度非法回退 overworld。 |
| `request_cancel` | `request_cancel(self)` | 置取消标志。 |
| `run` | `run(self)` | `_run_impl` 异常兜底 `error.emit`。 |
| `_run_impl` | `_run_impl(self)` | 指数扩窗：`side` 从 512 起，每轮以目标点为中心建 `(tx-half, tz-half, tx+half, tz+half)` 视窗调 `enumerate_structures`（仅该结构、可取消）；对结果按「距目标距离平方 → x → z」字典序稳定排序取最优；命中判据为圆形判据 `half*half >= d2`（最优实例距目标 ≤ 窗半径，此时窗外不可能有更近实例，必为最近），命中即填 `target/dist/searched_side` 后 break，否则 `side *= 2` 续扩；扩到 8192 仍无命中发空 `structures` 载荷；取消路径静默返回不发结果。 |

`StructureScanThread(QThread)`——视口驱动的结构增量扫描：

| 名称 | 签名 | 说明 |
|---|---|---|
| （信号） | `structures_done = Signal(object)`；`error = Signal(str)` | 载荷 `{"structures": [...], "view": (bx0,bz0,bx1,bz1)}`。 |
| `__init__` | `__init__(self, seed, version_key, view: tuple, struct_keys=None, parent=None, dimension="overworld")` | 主线程把可视方块矩形整批提交；`struct_keys` 同主线程语义（None=全部，[]=明确不标）。 |
| `request_cancel` | `request_cancel(self)` | 置取消标志（用户又拖走时主线程放弃本批）。 |
| `run` | `run(self)` | `_run_impl` 异常兜底 `error.emit`。 |
| `_run_impl` | `_run_impl(self)` | 一次提交一次结果、不做进度回报（21 种结构 × 若干区域的正向定位毫秒到亚秒级）：调 `enumerate_structures` 正向枚举该视野内真实生成的结构，`_cancelled` 时静默返回，否则 `structures_done.emit({"structures": ..., "view": ...})`。 |

`TileRenderThread(QThread)`——视口驱动的瓦片批量增量渲染：

| 名称 | 签名 | 说明 |
|---|---|---|
| （信号） | `tile_done = Signal(object)`；`batch_done = Signal()`；`error = Signal(str)` | 单瓦片载荷 `{tx, tz, rgb, origin_bx, origin_bz, engine, lod}`；整批完成（空占位，便于统一收尾续批）。 |
| `__init__` | `__init__(self, seed, version_key, tiles: list, parent=None, lod="block", hillshade=False, dimension="overworld")` | `tiles = [(tx, tz), ...]` 瓦片格坐标；非主世界强制 `lod="cell"`。 |
| `request_cancel` | `request_cancel(self)` | 置取消标志（新一批提交前由主线程调用）。 |
| `run` | `run(self)` | `_run_impl` 异常兜底 `error.emit`。 |
| `_run_impl` | `_run_impl(self)` | 逐瓦片循环（详见下方「重点流程」）；全部完成且未取消才 `batch_done.emit()`。 |

`_run_impl` 重点流程（逐瓦片：扩边采样 → 渲染 → 裁边 → 上屏）：

1. 瓦片 `(tx, tz)` 的世界左上角为 `(tx*_TILE_BLOCKS, tz*_TILE_BLOCKS)`；因 `sample_region` 中心对齐，采样中心取 `(obx + 512, obz + 512)`，采样边长 `_TILE_BLOCKS + pad*8`（pad=`_TILE_PAD_CELLS`=2，每边多出 pad*4 方块）；贴世界边界的方向自然少采，不足 pad 时 horn 用线性外推兜底，不报错。
2. 主世界走 `sample_region(want_depth=True, want_temp_humid=True, surface_mode=True, cancel=...)`（与主渲染同语义）；下界/末地走对应维度采样器。`_cancelled` 或 `res["cancelled"]` 即 break。
3. 渲染与裁边：下界/末地 rgb 单位即 4 方块/像素，直接裁 `[pad : pad + 256]` 像素；主世界 `cell` 档 `render_cell_rgb` 后裁 `[pad : pad + 256]` 噪声格；`block` 档 `render_block_rgb`（带 seed/origin）后裁 `[pad*4 : pad*4 + 1024]` 方块。裁剪视图非连续，`np.ascontiguousarray` 拷贝回补（QImage 要求 C 连续数组）。
4. `tile_done.emit` 载荷的 `origin_bx/origin_bz` 由采样返回值回补 `+ pad*4`，对齐到瓦片真实左上角（= `tx*_TILE_BLOCKS`）；每片立即发信号（不等整批），主线程可在 `tile_done` 里自行丢弃失效瓦片，线程不回溯。
5. 循环后 `if not self._cancelled: self.batch_done.emit()`——被取消的批次不发 batch_done（主线程 epoch 校验也会丢弃）。

`BiomeLocateThread(QThread)`——群系定位（扩窗搜索最近出现位置）：

| 名称 | 签名 | 说明 |
|---|---|---|
| （信号） | `located = Signal(object)` | 载荷命中 `{biome, name?, x, z, target: (tx,tz), dist, searched_side}`（x/z 为该像素左上角方块坐标即群系实例点）；未找到 `{biome, "structures": [], target, searched_side}`；线程异常也走 located（带 `error` 键），由主线程识别提示。 |
| `_LOCATE_START_SIDE` / `_LOCATE_MAX_SIDE` | `512` / `8192` | 与结构定位同源；蘑菇岛/冰刺之地等稀疏群系可能超出上限 → 未找到提示扩大定位搜索范围。 |
| `__init__` | `__init__(self, seed, version_key, biome_id, tx, tz, parent=None, dimension="overworld")` | 存目标群系 id 与目标点。 |
| `request_cancel` | `request_cancel(self)` | 置取消标志。 |
| `run` | `run(self)` | `_run_impl` 异常兜底：发带 `error` 键的 located 载荷（不发 error 信号，主线程按 payload["error"] 分支处理）。 |
| `_sample_window` | `_sample_window(self, view: tuple) -> dict` | 按维度采样 `view=(bx0,bz0,bx1,bz1)` 的群系矩阵：主世界 `sample_region(中心, w, h, surface_mode=True, cancel=...)`（同主渲染语义）；下界/末地用独立采样器；契约一致，biomes 均为 1 像素 = 4x4 方块。 |
| `_run_impl` | `_run_impl(self)` | 指数扩窗同结构定位：每轮采样窗内群系矩阵，`np.nonzero(mat == biome_id)` 找目标群系全部像素，按「像素左上角到窗中心的格距平方」`np.argmin` 取最近（目标点恒在窗中心；对角同一像素视为同一实例，格距平方直接比较不放大尺度）；格距² `<< 4` 换算块距²（1 像素 = 4x4 方块，`d2_blk = d2_n << 4`），实例方块坐标 = `origin + (像素索引 << 2)`；圆形判据 `half*half >= d2_blk` 命中即停窗，否则窗口翻倍；8192 仍未命中发空 `structures` 载荷；取消静默返回。 |

**接口**：

- **被哪些模块 import**：仅 `Tools/tool_MapPreviewer.py`（import `CANCELLED_SUMMARY`、`BiomeLocateThread`、`DIM_BIOME_TABLES`、`MapPreviewerThread`、`StructureLocateThread`、`StructureScanThread`、`TileRenderThread`、`_TILE_BLOCKS`）。
- **发出的信号汇总**：
  - `MapPreviewerThread`：`progress(qlonglong, qlonglong, str)`、`render_finished(object, str)`、`error(str)`（+ 继承的 QThread `finished`）。
  - `StructureLocateThread`：`located(object)`、`error(str)`。
  - `StructureScanThread`：`structures_done(object)`、`error(str)`。
  - `TileRenderThread`：`tile_done(object)`、`batch_done()`、`error(str)`。
  - `BiomeLocateThread`：`located(object)`（无 error 信号，异常经 located 载荷的 `error` 键传递）。
- **依赖的上游模块**：
  - `Utils.MapPreviewer.map_sampler.sample_region`（主世界地形采样：native 优先、纯 Python 兜底，行级进度与取消）。
  - `Utils.MapPreviewer.nether_end_sampler.sample_region_nether / sample_region_end`（下界/末地独立采样器，输出即 4 方块/像素 rgb）。
  - `Utils.MapPreviewer.block_colors.render_block_rgb / render_cell_rgb`（群系矩阵 → RGB，block 精细/cell 快速两档，支持 hillshade 与 temp/humid/depth）。
  - `Utils.Public.structure_map.available_structures / enumerate_structures`（21 种结构按维度正向定位 + cubiomes 位级群系校验）。
  - 第三方：`numpy`（矩阵运算与非零搜索）、`PySide6.QtCore.QThread / Signal`。

**关键变量/常量**（实例状态）：

| 类 | 变量 | 说明 |
|---|---|---|
| 各线程共有 | `_cancelled` / `_seed` / `_version_key` / `_dimension` | 取消标志（`request_cancel` 置位）与计算参数；`_dimension` 非法值一律回退 `"overworld"`。 |
| `MapPreviewerThread` | `_radius` / `_struct_keys` / `_lod` / `_hillshade` / `_last_emit` | 半径（方块）；结构键（None=全部 / []=不标）；渲染档位（非法回退 block，非主世界强制 cell）；阴影开关；上次 progress 发出时刻（仅工作线程访问，monotonic 秒）。 |
| `StructureLocateThread` | `_struct_key` / `_tx` / `_tz` | 目标结构键与目标点方块坐标（扩窗中心）。 |
| `StructureScanThread` | `_view` / `_struct_keys` | 待扫描方块矩形 `(bx0,bz0,bx1,bz1)`（int 元组）与结构键。 |
| `TileRenderThread` | `_tiles` / `_lod` / `_hillshade` | 待渲染瓦片格坐标列表与渲染参数；LOD 沿用主图初始档位（线程内同样强制非主世界 cell）。 |
| `BiomeLocateThread` | `_biome_id` / `_tx` / `_tz` | 目标群系 id 与目标点方块坐标（扩窗中心）。 |

---

### 附：控制层与线程的协作全景

```
用户输入（版本/种子/半径/维度/结构勾选）
        │  _start_render()
        ▼
MapPreviewerThread ──progress──▶ 进度条
   │  采样 sample_region / nether_end_sampler（分块、行级取消）
   │  渲染 render_block_rgb / render_cell_rgb
   │  结构枚举 enumerate_structures（位级群系校验）
   ▼ render_finished(result, summary)
_apply_result(): rgb → QImage → 按 1024 方块瓦片格切片入场景
   │                                   结构 → 标记（浮板图标/红圈回退）
   ▼
拖动/缩放/定位 ──180ms 防抖──▶ TileRenderThread（缺失瓦片分批补渲染，加权 LRU 缓存）
                └─防抖──▶ StructureScanThread（视口扩边增量扫结构，去重并标记）
结构定位下拉 ──▶ StructureLocateThread（512→8192 指数扩窗找最近实例）
群系定位下拉 ──▶ BiomeLocateThread（同样扩窗，矩阵找最近群系像素）
        │  located（epoch 校验）
        ▼
_draw_locate(): 定位点+红虚线+距离文本+端点坐标标签 → _fit_locate_view() 适配视角
```

---

# SeedReverser（种子逆推工具）文档

> 覆盖文件：
> - `Tools\tool_SeedReverser.py`（实际 2404 行，控制层/UI 层）
> - `Threads\task_SeedReverser.py`（246 行，后台计算线程）

---

## `Tools/tool_SeedReverser.py`

**功能**：SeedReverser（结构坐标逆推 48 位结构种 + 群系模式精化 64 位世界种子）的工具页控件，继承 `BaseToolWidget` 并挂接 Qt Designer 编译产物 `CodesUI.SeedReverser.Ui_seedReverser`。本文件是纯控制层：负责观测数据的采集/校验/编辑、信息量（信息熵）提示、后台线程调度（结构种逆推、候选批量验证、世界种子精化）、结果格式化展示、通知弹窗、快捷键与会话持久化；全部重计算逻辑都下沉到 `Utils\SeedReverser` 与 `Threads` 模块，本文件不做任何数学求解。

核心数据流（与文件头 docstring 的使用流程一致）：

1. **观察值录入**：用户选结构类型（`structTypeCombo`，按版本过滤并分「可逆推/仅验证」两组），粘贴或手输 X/Z（支持整段 F3+C 文本自动提取），`_on_add_clicked` 走 8 步校验：非空/整数（`_coerce_coord`）→ 结构键有效性 → 由 `seed_math.compute_region`/`compute_offset` 计算区域坐标与区域内区块偏移 → 同区域同类型查重 → 边界检查（`seed_math.is_near_boundary`，阈值 `_BORDER_THRESHOLD=2` 区块，只警告不拒绝）→ 以 `structure_params.get_default_tolerance` 的预设容差构造观测 dict 追加入 `_observations` 并写入 `structList` 行（容差列注入行内 `QComboBox`）→ 刷新信息量条并落盘 → 边界警告。
2. **信息熵提示**：`_update_info_bar` 只统计「可逆推」观测（`structure_params.is_reversible`，即 linear 且 lift_mod≥2；仅验证观测不约束低位预筛，计入会虚高），调用 `seed_math.calc_info_bits(obs_list)` 计算累计比特（容差把每维位置约束从 1 值放宽为 `min(2*tol+1, chunk_range)` 候选值并按窗口折减），钳到 [0,48] 后写入 `infoProgressBar`（颜色分段：`<18` 红 / `<27` 橙 / `<40` 黄 / `≥40` 绿），`seed_math.info_hint` 生成文字提示，并联动 `_update_buttons` 的按钮可用矩阵。实测发现 QProgressBar 对超上限的 setValue 会静默忽略且 value 停在 -1，因此必须先钳制。
3. **结构种逆推**：`_on_calc_clicked` 把 `_observations` 压缩为 `entries`（struct_key/reg_x/reg_z/off_x/off_z/tol）交给 `SeedReverserCalcThread` 后台执行三层漏斗求解（`Utils\SeedReverser\structure_math.solve_structure_seeds`，约 10 秒级）。进度经 `progress(qlonglong,qlonglong,str)` 信号回 `_on_calc_progress`（按钮文本同时承担「取消」入口与百分比，阶段名放 tooltip）；完成经 `calc_finished(list,str)` 回 `_on_calc_finished`：与 `CANCELLED_SUMMARY` 比对识别取消，保存 `_last_candidates`/`_result_version`，群系模式开启时自动把候选全量回填精化面板（`_auto_fill_candidates`），按 hex+十进制双格式列出候选并触发 `_start_auto_verification`；无候选时给出三大可能原因与建议（版本不匹配/多条坐标抄错/站位跨区域）。`error` 信号回 `_on_calc_error`（观测不足等 ValueError 场景 + 结构选择建议）。
4. **候选验证**：两层——① 计算完成后自动启动 `SeedReverserVerifyThread` 批量正向复算全部候选（`_on_verify_finished` 追加汇总与首个候选的 `verify_candidate_seed` 逐条比对明细）；② 「验证候选种子」按钮 `_on_verify_clicked` 弹 `QInputDialog` 供选择/手输任意 48 位种子，`_run_verification` 在主线程同步验证并把逐条明细追加到信息框（与层 3 同语义，逐观测用自己的行内容差）。
5. **群系模式（世界种子精化）**：勾选 `biomeModeCheckBox` 后 `_on_biome_mode_toggled` 显示 `refineGroupBox` 并隐藏右侧 3D 结构视口（二者互斥，信息框为 Expanding 自动补位）。群系观测录入 `_on_add_biome_obs`：X 框可粘整段 F3+C（`parse_f3c_command_full` 自动填 X/Y/Z）、X/Z 整数校验、Y 可选（填则按该高度群系判定，缺省按深层）、`resolve_biome` 解析中英文/F3 别名群系名、按 `(x>>2, z>>2, y>>2)` 噪声格去重（同格信息冗余直接拒绝）。精化候选来源：计算完成自动回填 / `_on_import_candidates` 手动导入 / 候选框手敲（hex/十进制混合，`_parse_candidate_text` 解析，0≤v<2^48 去重）。`_on_refine_clicked` 校验（候选非空 + 观测 ≥`_MIN_BIOME_OBS=7`）后启动 `WorldSeedRefineThread`（`Threads\task_WorldSeedRefine`）：对每个候选结构种枚举高 16 位（每候选验证 65536 个种子，native 引擎约 0.2 秒/候选），输出满足全部群系观测的 64 位世界种子。`_on_refine_finished` 分唯一解（自动复制剪贴板）/ 多解（需人工核对）/ 未命中（三大原因）三态渲染到 `worldSeedDetailBrowser` 并发通知。
6. **结果展示与辅助交互**：候选种子 hex+十进制双格式列出；`eventFilter` 拦截信息框双击，`_SEED_HEX_RE` 命中种子 hex 即复制到剪贴板并在 `infoHintLabel` 提示 4 秒；快捷键 Ctrl+Enter 计算、Esc 取消/清空输入、Enter 添加、Delete（列表焦点时）删行；两个列表各有右键菜单（删除/复制坐标/复制可粘回游戏聊天栏的传送命令）。

**群系/结构下拉的图标 delegate**（自研 QStyledItemDelegate 族）：

- `_NoEditDelegate`：基类。① 按列号集合屏蔽行内编辑器（`createEditor` 返回 None）；② 解决「编辑中重影」——行内编辑器多为半透明下拉，编辑期间视图重绘会让 item 文字透出，故用 `createEditor`/`destroyEditor`/`editor.destroyed` 三路跟踪正在编辑的 `QPersistentModelIndex`，`paint` 时该单元格只画背景不画文字。
- `BiomeComboDelegate`：群系图标委托。图标按「显示标签 → QIcon」字典查表（不依赖 model 的 DecorationRole，因此组合框下拉列表与补全浮层两个不同 model 的视图可共用同一 delegate）；`sizeHint` 为右侧 16px 图标预留宽度（combo 单列模型时加宽防长文字压图标）；`paint` 三步：完整矩形画背景（选中/悬停高亮满宽）→ 缩窄矩形画文字（右侧留图标位）→ 图标画在项右端。
- `StructRowDelegate`：structList 双击行内编辑——「类型」列构建动态 QComboBox（按当前版本枚举 `available_structures`，仅验证结构名后缀「（仅验证）」，value 存 struct_key 到 UserRole）、「X/Z」列 QLineEdit（带占位提示），`#`/区域/容差/状态列只读；`setEditorData`/`setModelData` 负责 UserRole 与显示文本的转换。提交校验统一由 `itemChanged` 处理器（`_on_struct_item_changed`）负责。
- `BiomeRowDelegate`：biomeObsList 行内编辑 + 第 4 列（群系列）行末图标。「群系」编辑器为可编辑 QComboBox + `QSortFilterProxyModel` 包含式过滤（自带补全是前缀式，对带空格英文标签不可用）+ `QCompleter(UnfilteredPopupCompletion)`，弹层复用主下拉的 `_biome_delegate`。

**会话持久化**：所有输入侧状态实时落盘到用户配置目录 `seed_reverser_session.json`（`QStandardPaths.AppConfigLocation`，取不到时回退模块所在目录）。`_save_session` 在每次数据变化点（添加/编辑/删除/容差改动/候选回填/模式切换/计算收尾）调用，`_session_ready` 标志在恢复完成前抑制写盘（防半恢复状态污染文件）；`_restore_session` 启动时恢复——顺序关键：先恢复版本（版本切换会刷新结构下拉，必须先于观测恢复），再逐条重建结构观测（`_rebuild_observation` 独立校验，坏条目跳过不阻断其余；兼容旧格式无逐条 `tol` 时继承旧全局 `tol`，非法值回退默认容差表）、恢复候选（int 且 0≤s<2^48 过滤）、`result_version`、群系观测（`biome_id` 0~255 范围校验）、候选框文本与群系模式开关，最后统一刷新三处 UI 状态。退出路径双保险：`QApplication.aboutToQuit` 连接 `_stop_calc_thread` 与 `_save_session`（连接顺序即调用顺序：先停线程再存盘），`closeEvent` 再兜底一次；`save_config` 实现主窗口退出协议 `save_all_tools_config`。停线程用 `request_cancel()+wait(5000)`，不用 `terminate`（强杀破坏 Qt 状态），并顺手停掉 3D 视口的变种轮播 QTimer——运行中的 QThread/QTimer 在退出阶段被析构会 0xC0000409 崩溃（PySide6 已知坑）。

**类与函数**：

模块级委托类（QStyledItemDelegate 族）：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `_NoEditDelegate.__init__` | `(readonly_columns=(), parent=None)` | 记录只读列集合，初始化 `_edit_index=None`（正在编辑的 QPersistentModelIndex 跟踪位）。 |
| `_NoEditDelegate.createEditor` | `(parent, option, index) -> editor\|None` | 只读列返回 None 屏蔽编辑；可编辑列创建编辑器后经 `_track_editor` 启动防重影跟踪。 |
| `_NoEditDelegate._track_editor` | `(editor, option, index) -> None` | 记录编辑中的 index，连接 `editor.destroyed` 兜底解除跟踪，并立即重绘该单元格清掉旧文字。 |
| `_NoEditDelegate.destroyEditor` | `(editor, index) -> editor` | 编辑器销毁时清 `_edit_index` 后转父类。 |
| `_NoEditDelegate._clear_edit_index` | `(*_args) -> None` | `destroyed` 信号槽（deleteLater 关闭路径兜底），解除编辑跟踪。 |
| `_NoEditDelegate._is_editing` | `(index) -> bool` | 判断某 index 是否正被行内编辑。 |
| `_NoEditDelegate._paint_item` | `(painter, option, index, with_text=True) -> None` | 统一单元格绘制入口：initStyleOption 后走 `CE_ItemViewItem`；`with_text=False` 时清空 text/icon（编辑中防重影）。 |
| `_NoEditDelegate.paint` | `(painter, option, index) -> None` | 编辑中不画文字，否则正常绘制。 |
| `BiomeComboDelegate.__init__` | `(icons: dict, parent=None, icon_column=None, readonly_columns=())` | 保存「显示标签→QIcon」表；`icon_column=None` 表示单列 combo 全列画图标，指定列号则仅该列画（多列树/表共用场景）。常量 `ICON_SIZE=16`、`ICON_PAD=6`。 |
| `BiomeComboDelegate.sizeHint` | `(option, index) -> QSize` | 为右侧图标预留空间：combo 模式加宽 `ICON_SIZE+2*ICON_PAD`，树/表模式只保行高 `max(h, ICON_SIZE+4)`；非图标列原样返回。 |
| `BiomeComboDelegate.paint` | `(painter, option, index) -> None` | 编辑中转基类防重影；无图标或非图标列转基类原生绘制；否则三步绘制：满宽背景 → 缩窄文字（右侧留位）→ 图标右端对齐绘制。 |
| `StructRowDelegate.__init__` | `(widget, parent=None)` | 持有主控件引用；只读列 `(0,4,5,6)`（#、区域、容差、状态——区域与状态是坐标派生值，容差由行内下拉承担）。 |
| `StructRowDelegate.createEditor` | `(parent, option, index) -> editor` | 列 1 构建 QComboBox：按当前版本枚举结构，仅验证结构标注后缀，经 `_add_struct_combo_item` 加项（带图标）；列 2/3 的 QLineEdit 设置「X（可粘 F3+C）」/「Z」占位符。 |
| `StructRowDelegate.setEditorData` | `(editor, index) -> None` | 类型列从 UserRole（struct_key）回显选中项；其余走默认。 |
| `StructRowDelegate.setModelData` | `(editor, model, index) -> None` | 类型列把选中项的 struct_key 写回 UserRole；其余走默认。 |
| `BiomeRowDelegate.__init__` | `(widget, parent=None)` | 继承 `BiomeComboDelegate`，图标表用 `widget._biome_icons`、图标列=4、只读列=(0,)。 |
| `BiomeRowDelegate.createEditor` | `(parent, option, index) -> editor` | 群系列（4）构建可编辑 QComboBox + `QStandardItemModel`（54 项标签）+ `QSortFilterProxyModel` 包含式过滤 + `QCompleter(UnfilteredPopupCompletion)`，弹层与补全浮层均复用 `widget._biome_delegate` 画图标；其余列走父类（文本编辑）。 |
| `BiomeRowDelegate.setEditorData` | `(editor, index) -> None` | 群系列把当前显示文本写入 lineEdit；其余走默认。 |

主控件 `SeedReverserWidget(BaseToolWidget, Ui_seedReverser)`，类属性 `preferred_size = (1170, 826)`。按功能分组：

初始化与基础：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `tool_name` | `@classmethod () -> str` | 返回 `"SeedReverser"`，主窗口按此注册/查找工具。 |
| `__init__` | `(parent=None) -> None` | 初始化全部实例状态（观测列表、三组线程与运行标志、`_session_ready` 等），依次 `_init_ui`/`_init_signals`/`_update_info_bar`，把 `_stop_calc_thread` 与 `_save_session` 挂到 `QApplication.aboutToQuit`（先停线程后存盘），最后 `_restore_session` 恢复会话并置 `_session_ready=True`。 |
| `_init_ui` | `() -> None` | 用 `Structure3DView` 替换 UI 占位 label（`render_error` 连 `_on_render_error`）；填充版本下拉（`VERSION_KEYS` 新到旧）；构建结构/群系两套 QIcon 表（复用 MapPreviewer 的 Wiki EnvSprite 资产 / `assets/SeedReverser/<键>.png`，缺图回退无图标）；设置两个列表的 7 列/5 列表头与列宽；信息量条 0~48 与 `%vbit / 48bit` 格式；构建群系名下拉的双语包含式补全（model+proxy+completer）与图标 delegate；行编辑器尾部 action 占位当前群系图标；精化面板默认隐藏、`pushButton` 改文案「粘贴F3+C」；写入精化面板常驻说明与信息框初始帮助。 |
| `_init_signals` | `() -> None` | 连接全部控件信号（版本/类型/模式切换、添加/粘贴/清空/计算/验证/清空全部、精化面板 7 个按钮与 3 个 returnPressed、候选框 editingFinished 落盘、列表右键菜单与 itemChanged）与快捷键（Ctrl+Return 计算、Esc 取消/清空、Delete 删行——WidgetShortcut 防误触）；给 `informationBrowser` 安装 eventFilter（双击种子 hex 复制）。 |
| `_add_struct_combo_item` | `(combo, text: str, key: str) -> None` | 给结构下拉加项（主下拉与行内编辑下拉共用）：查 `_struct_icons` 命中则 `addItem(icon, text, key)`，否则无图标回退。 |
| `_reload_struct_combo` | `() -> None` | 按当前版本重建结构下拉：先列可逆推结构（附 `calc_info_bits` 单个比特数），有仅验证结构时插入 `"─"*24` 分隔项（`userData=None`，`setFlags` 去掉 `ItemIsSelectable` 使其不可选中）再列仅验证项；`blockSignals` 包裹防触发切换，尽量恢复原选中项，收尾调 `_on_struct_type_changed`。 |

信息量条与按钮状态：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `_update_info_bar` | `() -> None` | 过滤出可逆推观测后调 `seed_math.calc_info_bits`（含逐条容差折减），钳到 [0, maximum] 再 setValue（QProgressBar 超上限 setValue 会静默忽略且停在 -1），按 `_INFO_BAR_SECTIONS`/`_INFO_BAR_COLOR_GOOD` 选色重写进度条样式表（控件级 background+border 声明才能让凹槽彻底隐形），`seed_math.info_hint` 更新提示文本，最后联动 `_update_buttons`。 |
| `_update_buttons` | `() -> None` | 按钮状态矩阵：计算/验证运行中——calcButton 变「取消验证/取消计算」且可点、其余输入类控件全部禁用；空闲——观测数 `<3` 时计算按钮禁用并提示「至少 3 个」，有结果时文案变「重新计算」并启用验证/清空按钮。 |

结构观测录入（观察值采集）：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `_on_paste_f3c` | `() -> None` | 读取剪贴板，`looks_like_f3c` 预判后 `parse_f3c_command` 解析，把 X/Z 填入输入框（群系面板另有独立实现）；格式不符时信息框提示并 `_flash_red` 抖红输入框。 |
| `_on_clear_input` | `() -> None` | 只清 X/Z 输入框并聚焦，不动已采集列表。 |
| `_on_add_clicked` | `() -> None` | 添加观测的 8 步主流程：非空+整数/F3+C 校验（`_coerce_coord`）→ 结构键检查（分隔线 `currentData` 为 None 时提示）→ `compute_region`/`compute_offset` 算区域与偏移 → 同区域同类型查重（拒绝并提示跨区域采集）→ `is_near_boundary` 边界检查（允许添加但状态列标「边界!」）→ 构造观测 dict（含 `tol=get_default_tolerance`、`params`）追加并 `_append_list_row` → 清输入、`_update_info_bar`、`_save_session` → 边界观测输出站位跨区块警告。 |
| `_coerce_coord` | `(raw_text: str, other_text: str, is_x: bool) -> tuple` | 输入规整：纯整数直接返回；整段 F3+C 文本则解析提取——X 框时返回 `(x, str(z))` 顺带回填 Z，Z 框时返回 `(z, other_text)`；解析失败返回 `(None, other_text)`。 |
| `_flash_red` | `(*edits) -> None` | 校验失败反馈：输入框套 2px 红边框样式，600ms 后 QTimer 恢复。 |

行内编辑与列表维护：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `_on_struct_item_changed` | `(item, column: int) -> None` | structList 行内编辑提交统一入口（程序化回写用 `blockSignals` 防递归）。类型列：新 key 换参数表，先用旧坐标重算区域再全表查重（冲突/版本不支持则回滚 UserRole 并提示），成功后更新 obs 的 key/name/params/区域/偏移，容差回落新类型默认值并 `_attach_tol_combo` 重建下拉，`_recalc_struct_obs` 重算状态列并回写图标/文本/颜色，最后 `_after_struct_edit`。X/Z 列：`_coerce_coord`（X 列可粘整段 F3+C 顺带改 Z）→ 重算区域/偏移 → 排除自身的同区域同类型查重 → 更新 obs 并回写行，非法输入经 `_rollback_struct_cell` 恢复。 |
| `_recalc_struct_obs` | `(obs: dict) -> str` | 用当前偏移重算 `near_boundary`，返回 `"边界!"/"OK"` 状态文本（区域/偏移已由调用方更新）。 |
| `_rollback_struct_cell` | `(item, obs, column, reason) -> None` | 非法输入回滚：`blockSignals` 包裹恢复旧显示文本，信息框输出「修改未生效 + 原因」。 |
| `_after_struct_edit` | `() -> None` | 合法提交公共收尾：清 `_last_candidates`/`_result_version`（旧结果失效），验证运行中则 `request_cancel`，刷新信息量条并落盘。 |
| `_append_list_row` | `(seq: int, obs: dict, status: str) -> None` | 把观测追加为 structList 一行：7 列文本（容差列留空）、类型列 UserRole 存 struct_key 并画结构图标（DecorationRole）、对齐与 `_STATUS_COLORS` 状态着色，`blockSignals` 包裹 addTopLevelItem，最后 `_attach_tol_combo` 注入容差下拉。 |
| `_attach_tol_combo` | `(item, obs: dict) -> None` | 给容差列 `setItemWidget` 注入 QComboBox（0=精确 / 1~2 区块，value 存 itemData），带完整容差说明 tooltip；`currentIndexChanged` 闭包回写 `obs["tol"]` 并刷新信息量条+落盘（容差直接影响信息量贡献）。 |
| `_renumber_rows` | `() -> None` | 删除观测后重排 # 列序号。 |
| `_delete_selected` | `() -> None` | 删除选中行：同步删 `_observations[idx]` 与列表项、重排序号、清旧结果（验证运行中取消）、刷新信息量条并落盘。 |
| `_on_list_context_menu` | `(pos) -> None` | 右键菜单三动作：删除此条（走 `_delete_selected`）/ 复制坐标（`"x, z"`）/ 复制 F3+C 格式（生成 `/execute in minecraft:overworld run tp @s X 100 Z 0 0` 传送命令，y=100 仅用于飞到结构上空）。 |
| `_resize_struct_columns` | `() -> None` | 列宽自适应：#/X/Z/区域/状态 ResizeToContents、类型列 Stretch、容差列 Interactive——因 ResizeToContents 感知不到 setItemWidget 注入的下拉框，故临时构建探针 QComboBox 按 sizeHint+8px 手动定宽。 |
| `_resize_biome_columns` | `() -> None` | biomeObsList 列宽：前 4 列 ResizeToContents，末列「群系」Stretch。 |

版本 / 模式切换 / 3D 预览：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `_on_version_changed` | `() -> None` | 刷新结构下拉（`_reload_struct_combo`），检查已采集观测在新版本下是否仍存在，不存在的结构名列表提示用户确认来源世界版本，最后落盘。 |
| `_on_struct_type_changed` | `(indirect) -> None` | 类型切换：按参数生成 tooltip（`scatter=="triangle"` 三角散布不可单独参与预筛 / `lift_mod==0` 仅验证 / 线性结构附单个比特数），从 `_ANCHOR_HINTS` 取锚点位置提示写入 tooltip 与 infoHintLabel（添加观测后会被信息量提示覆盖，符合「选结构时看一眼」时序），并刷新 3D 预览。 |
| `_update_anchor_preview` | `() -> None` | 结构切换 → 3D 视口更新：无选中则 `set_structure(None)`；key 未变直接返回（缓存 `_anchor_preview_key`），否则 `set_structure(key, name)`（模型走 build_model 缓存）。原平面示意图（structure_preview）已由 3D 视口取代，保留方法名与调用点减少外部引用破坏。 |
| `_on_render_error` | `(msg: str) -> None` | 3D 视口 `render_error` 信号槽：`informationBrowser.append` 追加「[3D 视口]」前缀错误（模型构建失败/上传失败/绘制异常统一链路）。 |
| `_on_biome_mode_toggled` | `(checked: bool) -> None` | 群系模式开关：显示/禁用切换 `refineGroupBox`，同时隐藏/恢复右侧 3D 视口（群系模式=纯群系观测，无结构预览；informationBrowser 垂直 Expanding 自动吃掉/归还空间实现「结果区自动加高」）；空闲提示 `_refine_idle_hint`，最后落盘。 |

计算（结构种逆推）：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `_on_calc_clicked` | `() -> None` | 计算按钮多态：计算运行中 → `request_cancel` 并显示「取消中…」禁用；验证运行中 → 取消验证；空闲 → 压缩 `entries`（struct_key/reg/off/tol）启动 `SeedReverserCalcThread`，连接 progress/calc_finished/error 与内置 finished（清引用防悬挂），置 `_calc_running` 刷按钮后 start。观测 `<3` 的入口是按钮禁用态的兜底防御。 |
| `_on_calc_progress` | `(done: int, total: int, stage: str) -> None` | 进度槽：按钮文本变「取消计算 N%」，tooltip 显示「阶段 stage: done/total（点击按钮取消）」。 |
| `_on_calc_finished` | `(candidates: list, summary: str) -> None` | 完成槽：`summary == CANCELLED_SUMMARY` 时输出「计算已取消」即返。成功路径：保存 `_last_candidates`/`_result_version`；群系模式开启且有候选时 `_auto_fill_candidates` 自动回填精化面板；用 Counter 汇总观测构成、`_tol_summary_line` 生成容差摘要，把候选逐个按 `0x...012X (十进制: n)` 格式列出并提示即将自动验证，触发 `_start_auto_verification` 与完成通知。无候选时输出错误页（版本不匹配/多条坐标抄错/站位跨区域三原因 + 建议）与失败通知，最后统一落盘。 |
| `_tol_summary_line` | `() -> str` | 容差摘要行：全部 0 →「精确模式」；否则按 Counter 列出「容差 t 区块 ×n」与「精确 ×n」，便于核对逐条容差设置。 |
| `_on_calc_error` | `(message: str) -> None` | 求解异常槽：恢复状态、输出「无法计算 + 原因 + 结构选择建议（沉船/沙漠神殿/雪屋等线性结构最适合逆推）」、发通知。 |
| `_on_thread_finished` | `() -> None` | QThread 内置 `finished`（线程对象真正结束）槽：非运行即清 `_calc_thread`/`_verify_thread` 引用防悬挂。 |

验证（手动 + 自动批量）：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `_on_verify_clicked` | `() -> None` | 手动验证入口：`QInputDialog.getItem`（可编辑下拉，选项为候选的 12 位 hex）选择/输入种子，`_parse_seed_text` 解析失败则追加格式错误提示，成功走 `_run_verification`。 |
| `_parse_seed_text` | `(text: str) -> int\|None` | 解析种子文本（0x 开头按 hex，否则十进制），范围校验 0 ~ 2^48-1，非法返回 None。 |
| `_run_verification` | `(seed: int) -> None` | 同步正向全量比对：`verify_candidate_seed(seed, self._observations, version)`（版本优先用 `_result_version`），把「验证结果」页与逐条比对明细追加到信息框（语义与层 3 一致，逐观测用自己的行内容差）。 |
| `_start_auto_verification` | `() -> None` | 计算完成后的自动批量验证：以 `[dict(o) for o in self._observations]` 快照与候选列表启动 `SeedReverserVerifyThread`，连接四个信号（含内置 finished 清引用），置 `_verify_running` 后 start。 |
| `_on_verify_progress` | `(done, total, stage) -> None` | 验证进度槽：按钮文本「取消验证 N%」+ tooltip。 |
| `_on_verify_finished` | `(passed: list, summary: str) -> None` | 批量验证完成槽：取消分支输出提示；成功分支追加「自动验证」页——`summary + 容差摘要`，通过时对首个候选再跑一次 `verify_candidate_seed` 展示逐条比对明细，无通过则提示检查观测坐标或版本。 |
| `_on_verify_error` | `(message: str) -> None` | 批量验证异常槽：输出失败原因，注明逆推结果仍有效可手动验证排查。 |

清空与帮助：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `_on_clear_all` | `() -> None` | 清空全部：QMessageBox 确认（默认 No）后清观测/候选/结果、取消运行中的验证、清列表与输入框、恢复信息框初始帮助文本，刷新信息量条/精化按钮并落盘。 |
| `_initial_help_text` | `() -> str` | 生成信息框初始使用说明（`__init__` 与清空共用）：6 步采集计算流程、站位容差说明（锚点在区块西北角、F3+C 得到的是玩家站位、建议容差 2 及信息量代价）、群系模式要点（候选全量导入不截断等）。 |

结果区交互与快捷键：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `eventFilter` | `(obj, event) -> bool` | 拦截 `informationBrowser` 双击：光标下整词被 `_SEED_HEX_RE` 完整匹配（`0x` + 1~16 位 hex）则复制到剪贴板，infoHintLabel 显示「已复制 …」4 秒后由 `_restore_info_hint` 恢复。 |
| `_restore_info_hint` | `() -> None` | 复制提示超时后按当前可逆推观测重新计算信息量并恢复 `info_hint` 文本（与信息条同口径）。 |
| `_on_escape` | `() -> None` | Esc 快捷键：计算/验证运行中请求取消；空闲时清空 X/Z 输入框并聚焦。 |

精化面板（世界种子精化）——辅助与候选导入：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `_y_tag_of` | `@staticmethod (obs_list) -> str` | 统计带 Y 观测点数，生成「（n 点带Y）」提示后缀（无则空串）。 |
| `_refine_idle_hint` | `() -> str` | 空闲提示：观测 `<7` 显示「n/7 点+Y标签」；达标显示「已就绪：n 点 × 候选数 × 2^16」。 |
| `_parse_candidate_text` | `@staticmethod (text: str) -> list[int]` | 解析候选种子文本：按空白/逗号/分号（含全角）切分，逐 token 按 0x 前缀定进制，非法静默跳过，范围 0≤v<2^48 且去重。 |
| `_count_refine_candidates` | `() -> int` | 当前候选框内有效候选数（解析失败静默忽略），驱动精化按钮状态。 |
| `_update_refine_buttons` | `() -> None` | 精化按钮状态矩阵（独立于结构逆推）：运行中按钮变「停止精化」、清除禁用、提示「精化中…」；空闲按「观测≥7 且候选>0」启用，infoLabel 依次显示观测不足/请先完成结构逆推或手输候选/就绪（含枚举总量 `n_cands * 65536`）。 |
| `_auto_fill_candidates` | `(candidates: list) -> None` | 结构逆推成功后自动把候选全量回填 candidateSeedEdit（逗号分隔、不截断——曾按 ≤16 截断导致真种子排在第 17+ 位时精化必然未命中，111 候选案例实证），刷新按钮状态并落盘。 |
| `_on_import_candidates` | `() -> None` | 「从计算结果导入」手动兜底：把 `_last_candidates` 全量写入候选框并落盘；无结果时 infoLabel 提示先运行结构逆推。 |

精化面板——群系观测录入与编辑：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `_on_add_biome_obs` | `() -> None` | 添加群系观测：X 框粘贴完整 F3+C 且 Z 为空时用 `parse_f3c_command_full` 自动填 X/Y/Z；X/Z 整数校验、Y 可选整数校验；`resolve_biome` 解析群系名（无法识别则提示中英文/F3 别名输入方式）；同噪声格去重（`x>>2, z>>2, (y>>2)` 三元组，同格信息冗余直接拒绝，带不同 Y 的同 (x,z) 点有效）；构造 `{"x","z","biome_id"[,"y"]}` 追加并 `_append_biome_row`，清输入、刷按钮、落盘。 |
| `_append_biome_row` | `(seq: int, obs: dict) -> None` | 群系观测追加为 biomeObsList 一行（5 列：#/X/Y/Z/群系全标签，Y 缺省显示「—」），设置对齐与可编辑标志，`blockSignals` 包裹防程序化触发 itemChanged。 |
| `_on_biome_item_changed` | `(item, column: int) -> None` | 行内编辑提交统一入口（blockSignals 防递归）。X/Z 列（1/3）：X 列可粘整段 F3+C（解析 float 后取 int），否则与另一列文本拼合取整；按噪声格三元组排除自身查重；回写 obs 的 x/z（y 按「本列输入是否含 Y」决定保留/移除）并 `_rewrite_biome_row` 规范化整行 + `_after_biome_edit`。Y 列（2）：空或「—」视作移除 y；换 Y 可能撞上同 (x,z) 噪声格另一条，冲突回滚。群系列（4）：`resolve_biome` 解析失败恢复原群系，成功更新 biome_id。 |
| `_rewrite_biome_row` | `(item, obs: dict) -> None` | 从 obs 规范化回写整行显示（Y 缺省「—」、群系用 `biome_label` 全标签），blockSignals 包裹。 |
| `_rollback_biome_cell` | `(item, obs, column, reason) -> None` | 非法输入回滚：恢复该列旧显示文本，refineInfoLabel 说明原因。 |
| `_after_biome_edit` | `() -> None` | 合法提交收尾：`_update_refine_buttons` + `_save_session`。 |
| `_on_paste_biome_f3c` | `() -> None` | 精化面板「粘贴F3+C」：剪贴板 `looks_like_f3c` 预判 + `parse_f3c_command_full` 解析后填 X/Y/Z 三个输入框；群系名无法从 F3+C 提取，光标定位群系下拉（`setCurrentIndex(-1)` 清选择）并提示手动选择后点「添加」。 |
| `_update_biome_accent` | `(*_args) -> None` | 群系选择/输入联动：以 `currentText()` 精确匹配标准标签——命中 `_biome_icons` 则行编辑器尾部 action 显示图标，并用 `color_for_label`（中文 Wiki 信息框草地/水体标志色）染文字色；任意其他文本/清空则移除图标恢复默认色。两种事件源（currentIndexChanged 与 textChanged 兜底）统一处理。 |
| `_on_clear_biome_obs` | `() -> None` | 清空群系观测列表与数据，刷新按钮并落盘。 |
| `_on_biome_obs_context_menu` | `(pos) -> None` | 右键菜单：删除此条（删数据+列表项+重排序号+刷按钮+落盘）/ 复制坐标（带 Y 与不带 Y 两种格式）。 |

精化面板——计算：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `_on_refine_clicked` | `() -> None` | 精化按钮多态：运行中 → `request_cancel` 并「停止中…」；空闲 → `_parse_candidate_text` 校验候选非空、观测 ≥7，组装观测列表（x/z/biome_id/y 可选）启动 `WorldSeedRefineThread(cands, obs, version)`，连接 progress/refine_finished/error/finished，置 `_refine_running` 后 start；详情区先显示「正在精化世界种子…」。 |
| `_on_refine_progress` | `(done, total, msg) -> None` | 精化进度槽：只驱动 `refineProgressBar` 百分比；按钮与 infoLabel 文案由状态切换统一管理。 |
| `_on_refine_finished` | `(result: dict, summary: str) -> None` | 完成槽：`summary == _REFINE_CANCELLED_SUMMARY`（来自 task_WorldSeedRefine）时输出取消态；否则三态渲染——无种子输出「未命中」页（观测抄错/候选不含真值/版本不符三原因 + 统计）；唯一解输出十进制种子 + 64 位 hex；多解输出候选列表并注明需人工核对。命中时全部种子复制到剪贴板、infoLabel 提示、发完成通知。 |
| `_on_refine_error` | `(message: str) -> None` | 精化异常槽：进度条归零、详情区输出「无法精化 + 原因」、发通知、刷按钮。 |
| `_on_refine_thread_finished` | `() -> None` | 线程内置 finished 槽：非运行即清 `_refine_thread` 引用。 |
| `_on_refine_clear` | `() -> None` | 清除精化：候选框清空 + `_on_clear_biome_obs` + 进度条归零 + 详情区恢复 `_REFINE_DETAIL_INITIAL` 说明文本，再次落盘（候选框文本变化）。 |

会话持久化与线程管理：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `_session_path` | `() -> str` | 会话文件路径：`QStandardPaths.AppConfigLocation` 下 `seed_reverser_session.json`（取不到回退模块所在目录），自动建目录。 |
| `_save_session` | `() -> None` | 实时落盘：`_session_ready` 未就绪时直接返回（防半恢复状态写盘）；序列化 `version/biome_mode/observations(逐条 10 字段)/candidates/result_version/biome_obs/candidate_text` 为 UTF-8 JSON（ensure_ascii=False, indent=2）；OSError 打印告警不抛。只存输入侧状态，输出文本由启动后的初始文本承担。 |
| `_restore_session` | `() -> None` | 启动恢复：文件缺失/非 dict/损坏（OSError/ValueError）静默跳过；顺序为版本（必须先于观测，版本切换会刷新结构下拉）→ 结构观测逐条 `_rebuild_observation`（坏条目跳过）→ 候选列表（int 且 [0,2^48) 过滤）→ result_version → 群系观测（biome_id 0~255）→ 候选框文本 → biome_mode → 统一刷新信息量条/精化按钮/按钮矩阵。 |
| `_rebuild_observation` | `(raw, version: str, legacy_tol: int = 0) -> dict\|None` | 从会话 dict 重建单条结构观测：`get_params` 校验 struct_key（参数表已移除该结构返回 None）；坐标/区域/偏移字段采集时已固化直接取整；容差取值链：新格式逐条 `tol` → 旧全局 `tol`（`legacy_tol`）→ `get_default_tolerance` 兜底，保证恢复后总带合法 tol；params 按保存时版本重算。 |
| `save_config` | `() -> None` | 主窗口退出协议（`save_all_tools_config`）实现：转调 `_save_session`。 |
| `_stop_calc_thread` | `() -> None` | 停止全部线程（aboutToQuit/closeEvent 双保险，重复调用无副作用）：先 `_anchor_view.stop_variant_timer()`（退出阶段运行中 QTimer 被析构会 0xC0000409），再对三条线程 `request_cancel()+wait(5000)`（结构逆推层间约 0.1~0.5 秒粒度、验证候选间微秒级、精化候选间与高位步进间检查；native 精化整轮不到 1 秒），RuntimeError（退出阶段 C++ 对象已析构）防御性忽略，不使用 terminate；最后清三个引用。 |
| `closeEvent` | `(event) -> None` | 窗口关闭兜底：调 `_stop_calc_thread` 后转父类（工具页是子控件平时收不到 closeEvent，主要靠 aboutToQuit）。 |

**接口**：

- 被谁 import：`Tools\__init__.py` 第 6 行 `from .tool_SeedReverser import SeedReverserWidget`，并注册进 `TOOL_CLASSES` 列表，主窗口靠该列表加载工具页（`tool_name()=="SeedReverser"`）。
- 发出的信号：无自定义信号；但会转发处理子对象信号——`Structure3DView.render_error(str)` → `_on_render_error`。
- 接收的信号（作为 Qt 槽）：
  - `SeedReverserCalcThread`：`progress("qlonglong","qlonglong",str)` → `_on_calc_progress`；`calc_finished(list,str)` → `_on_calc_finished`；`error(str)` → `_on_calc_error`；内置 `finished` → `_on_thread_finished`。
  - `SeedReverserVerifyThread`：同上三个信号 → `_on_verify_progress`/`_on_verify_finished`/`_on_verify_error`；内置 `finished` → `_on_thread_finished`。
  - `WorldSeedRefineThread`：`progress` → `_on_refine_progress`；`refine_finished(object,str)` → `_on_refine_finished`；`error(str)` → `_on_refine_error`；内置 `finished` → `_on_refine_thread_finished`。
- 依赖的模块：
  - `Tools.tool_base.BaseToolWidget`（基类，提供 `save_config` 退出协议等）。
  - `CodesUI.SeedReverser.Ui_seedReverser`（Designer 编译 UI）。
  - `Threads.task_SeedReverser`（`SeedReverserCalcThread`/`SeedReverserVerifyThread`/`CANCELLED_SUMMARY`）。
  - `Threads.task_WorldSeedRefine`（`WorldSeedRefineThread`/`CANCELLED_SUMMARY`，别名 `_REFINE_CANCELLED_SUMMARY`）。
  - `Utils.SeedReverser.seed_math`（`calc_info_bits`/`info_hint`/`compute_region`/`compute_offset`/`is_near_boundary`）。
  - `Utils.SeedReverser.structure_math.verify_candidate_seed`（正向全量比对）。
  - `Utils.SeedReverser.structure_3dview.Structure3DView`（锚点 3D 视口）与 `structure_preview`（导入保留，平面示意图已被 3D 视口取代）。
  - `Utils.Public.structure_params`（`VERSION_KEYS`/`STRUCT_NAMES`/`available_structures`/`get_params`/`get_default_tolerance`/`is_reversible`/`struct_key_to_name`）。
  - `Utils.Public.structure_icons`（结构 Wiki EnvSprite 图标路径）、`Utils.Public.biome_names`（`BIOME_CHOICES`/`biome_label`/`icon_path`/`resolve_biome`）、`Utils.Public.biome_signature_colors.color_for_label`（群系标志色）、`Utils.Public.notification.NotificationWidget`（右下角通知）。
  - `Utils.Public.stronghold_math`（`looks_like_f3c`/`parse_f3c_command`/`parse_f3c_command_full`，F3+C 文本解析）。
  - Qt：QtCore（QEvent/QPersistentModelIndex/QSortFilterProxyModel/QRect/QSize/QStandardPaths/Qt/QTimer）、QtGui（QBrush/QColor/QIcon/QKeySequence/QShortcut/QStandardItem/QStandardItemModel）、QtWidgets（QAbstractItemView/QApplication/QComboBox/QCompleter/QLineEdit/QHeaderView/QInputDialog/QMenu/QMessageBox/QStyledItemDelegate/QStyle/QStyleOptionViewItem/QTreeWidgetItem）。
  - 标准库：`json`（会话读写）、`os`、`re`（`_SEED_HEX_RE`）、`collections.Counter`（观测构成/容差计数）。

**关键变量/常量**：

模块常量：

| 常量 | 值 | 说明 |
| --- | --- | --- |
| `_MIN_OBSERVATIONS` | `3` | 计算所需最少观测数（solve 内部同样校验）。 |
| `_BORDER_THRESHOLD` | `2` | 离区域边界的警告阈值（区块）。 |
| `_SESSION_FILE` | `"seed_reverser_session.json"` | 会话文件名（配置目录下）。 |
| `_NOTIFY_DURATION_MS` / `_NOTIFY_TITLE_SIZE` / `_NOTIFY_MESSAGE_SIZE` / `_NOTIFY_PADDING` | `6000` / `16` / `14` / `(20,16,20,16)` | 完成类通知的展示参数（失败通知用另一组小字号）。 |
| `_INFO_BAR_SECTIONS` | `((18,"#E74C3C"),(27,"#E67E22"),(40,"#F1C40F"))` | 信息量条颜色分段（<18 红 / <27 橙 / <40 黄）。 |
| `_INFO_BAR_COLOR_GOOD` | `"#27AE60"` | 信息量 ≥40 比特的绿色。 |
| `_STATUS_COLORS` | `{"OK":(绿,None),"边界!":(橙,"#FEF9E7")}` | 状态列 (前景色, 背景色)，None 表示不设置。 |
| `_TOL_COL` / `_TOL_COMBO_MAX` | `5` / `2` | structList 容差列索引（0 起）与容差下拉上限（structure_math 上限 2）。 |
| `_SEED_HEX_RE` | `re.compile(r"0x[0-9A-Fa-f]{1,16}")` | 双击信息框复制种子 hex 的完整匹配正则。 |
| `_ANCHOR_HINTS` | dict（10 项） | 各结构锚点大致位置提示（依据 Minecraft Wiki：村庄无严格中心、单模板结构锚点为模板包围盒一角且向东南展开等），显示于信息量提示行与下拉 tooltip。 |
| `_MIN_BIOME_OBS` | `7` | 世界种子精化最少群系观测点数（refine_world_seeds 内部同样校验）。 |
| `_BIOME_MODE_HELP_TEXT` / `_REFINE_DETAIL_INITIAL` | 长文本 | 勾选群系模式写入说明区的完整使用说明 / 说明+「尚未精化」占位（精化结果会覆盖显示）。 |

主要实例状态（`SeedReverserWidget`）：

| 变量 | 类型/初值 | 说明 |
| --- | --- | --- |
| `_observations` | `list[dict]` | 结构观测列表，与 structList 行一一对应；每条含 `struct_key/name/x/z/reg_x/reg_z/off_x/off_z/near_boundary/tol/params`。 |
| `_calc_thread` / `_calc_running` | `QThread\|None` / `bool` | 结构种逆推线程与运行标志（None=空闲）。 |
| `_last_candidates` | `list[int]` | 最近一次计算的候选 48 位结构种（验证功能与精化导入的数据源）。 |
| `_result_version` | `str\|None` | 候选对应的版本键（手动验证优先用它，避免用户事后切换版本导致口径不一致）。 |
| `_verify_thread` / `_verify_running` | `QThread\|None` / `bool` | 自动批量验证线程与运行标志。 |
| `_biome_obs` | `list[dict]` | 群系观测列表（`x/z/biome_id`，可选 `y`），与 biomeObsList 行对应。 |
| `_refine_thread` / `_refine_running` | `QThread\|None` / `bool` | 世界种子精化线程与运行标志。 |
| `_session_ready` | `bool` | 会话恢复完成标志：False 期间抑制 `_save_session`（防半恢复状态写盘）。 |
| `_anchor_view` / `_anchor_preview_key` | `Structure3DView` / `str\|None` | 替换占位 label 的 3D 视口（保留 `anchorPreviewLabel` 同名属性引用不破外部引用）/ 当前预览的结构键缓存。 |
| `_struct_icons` | `dict[str, QIcon]` | 结构内部键 → QIcon（MapPreviewer 的 EnvSprite 资产，缺图跳过）。 |
| `_biome_icons` | `dict[str, QIcon]` | 群系显示标签 → QIcon（`assets/SeedReverser/<内部键>.png`）。 |
| `_biome_delegate` / `_obs_delegate` | `BiomeComboDelegate` / `BiomeRowDelegate` | 主下拉/补全浮层共用图标委托；群系观测列表的行内编辑+图标委托。 |
| `_biome_model` / `_biome_proxy` / `_biome_completer` | `QStandardItemModel` / `QSortFilterProxyModel` / `QCompleter` | 群系名下拉的双语包含式补全三件套（自带补全是前缀式，对带空格英文标签不可用）。 |
| `_biome_trailing_action` | `QAction` | 行编辑器 TrailingPosition 尾部 action：显示当前群系图标（与下拉项右侧图标视觉一致，浮层互斥联动）。 |

会话 JSON（`seed_reverser_session.json`）字段：

| 字段 | 说明 |
| --- | --- |
| `version` | 当前选中的版本键（如 `"1.21.11"`）。 |
| `biome_mode` | 群系模式勾选状态（bool）。 |
| `observations` | 结构观测数组，逐条存 `struct_key/name/x/z/reg_x/reg_z/off_x/off_z/near_boundary/tol` 十个字段（`params` 不存，恢复时按版本重算）。 |
| `candidates` | 最近候选 48 位结构种整数列表。 |
| `result_version` | 候选对应的版本键。 |
| `biome_obs` | 群系观测数组，逐条 `x/z/biome_id`（int）与可选 `y`。 |
| `candidate_text` | 精化面板候选框原始文本（hex/十进制混合字符串）。 |
| `tol`（旧版兼容） | 旧格式全局容差字段：新文件无逐条 tol 时统一继承（缺省 0），非法回退默认容差表。 |

---

## `Threads\task_SeedReverser.py`

**功能**：SeedReverser 的后台计算线程模块，把两类耗时任放入 QThread 执行，工作线程不做任何 UI 操作，只通过信号回传进度/结果/错误：

1. `SeedReverserCalcThread`——**48 位结构种逆推**。把三层漏斗求解 `Utils\SeedReverser\structure_math.solve_structure_seeds`（单次约 10 秒级，主线程直算会冻结界面）放进工作线程：构造时传入观测列表与版本键（可选全局容差 `tol` 兜底，UI 路径的 entries 逐条自带 `tol`），`run()` 中以 `on_progress`/`cancel` 回调与 `tol` 调用求解器。`cancel` 是个轮询取消标志的 lambda，主线程 `request_cancel()` 置位后求解器在层间边界尽快退出并发 `calc_finished([], CANCELLED_SUMMARY)`。容错机制：求解器抛 `ValueError`（观测不足/可 lifting 结构不足/容差计算量超限等预期错误）走 `error` 信号；首轮全量观测无候选时自动逐条剔除重试（最多 `_MAX_RETRY_SHOTS=8` 次，容错单条坐标抄错），命中后在 summary 前附「剔除第 N 条」提示。进度节流：层 3 是逐候选回调（候选可达数十万级），信号太密会淹没主线程事件循环，按 `_PROGRESS_INTERVAL_S=0.1` 秒时间间隔节流，每层最后一步（`done>=total`）强制发一次保证收尾。注意 progress 信号必须声明为 `"qlonglong"`：层 2 进度总量可达幸存低位数 × 高位块数 ≈ 十亿级，超出 Qt int（32 位，上限 2,147,483,647）会 OverflowError 且数值回绕成负数；槽参数带 Python 类型注解即可透明接收 64 位整数。
2. `SeedReverserVerifyThread`——**候选批量正向验证**。对全部候选逐个调用 `verify_candidate_seed`（与手动「验证候选种子」、求解器层 3 完全同一验证语义，含哨塔概率判定），通过者收集后一次性发出。语义说明：候选本就是层 3 严格筛过的种子，此线程是同一逻辑的批量复算，正常情况下全部通过（用于展示逐条比对明细与兜底确认），不做额外更强的过滤。取消在候选间检查（单候选微秒级，随时可停），进度同样 0.1 秒节流+收尾强制发。
3. 命名与取消约定：完成信号刻意叫 `calc_finished` 而非 `finished`——QThread 自带 `finished` 信号（Qt 内部用它管理线程对象生命周期），自定义同名信号会遮蔽它，导致 `wait()`/退出清理等路径行为异常。取消一律是主线程调用 `request_cancel()` 置布尔标志（仅置位，线程安全），从不强杀。

**类与函数**：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `SeedReverserCalcThread.__init__` | `(observations, version_key, parent=None, tol: int = 0)` | 拷贝观测列表与版本键；`tol` 为缺省容差，仅对无 `"tol"` 键的观测生效（obs 自带 tol 优先，本参数保留作兜底/兼容）；初始化 `_cancelled=False`、`_last_emit=0.0`（上次 progress 发出时刻，仅工作线程内访问）。 |
| `SeedReverserCalcThread.progress` | `Signal("qlonglong", "qlonglong", str)` | 进度信号 `(done, total, stage层名)`；必须 64 位整数（层 2 总量十亿级，32 位 Qt int 会溢出回绕）。 |
| `SeedReverserCalcThread.calc_finished` | `Signal(list, str)` | 完成信号 `(candidates 48 位结构种列表, summary 统计摘要)`；取消时列表为空且摘要为 `CANCELLED_SUMMARY`。 |
| `SeedReverserCalcThread.error` | `Signal(str)` | 错误信号（观测不足 / 输入矛盾 / 未预期异常）。 |
| `SeedReverserCalcThread.request_cancel` | `() -> None` | 主线程调用；仅置 `_cancelled=True` 布尔标志，线程安全。 |
| `SeedReverserCalcThread.run` | `() -> None` | 求解主流程：记录起始时刻后调 `solve_structure_seeds(observations, version_key, on_progress=self._on_progress, cancel=lambda: self._cancelled, tol=self._tol)`。`ValueError` → `error.emit` 返回（观测不足等预期错误）；其他异常 → `error.emit(f"计算线程异常：{exc!r}")` 兜底（任何异常不能无声吞掉）；`_cancelled` → `calc_finished([], CANCELLED_SUMMARY)`；空结果且未取消 → `_retry_without_single_obs` 自动剔除重试（返回 None 表示已发取消/错误信号）；成功 → `_format_summary` 生成统计摘要（命中剔除重试时提示文本前置），`calc_finished.emit(candidates, summary)`。 |
| `SeedReverserCalcThread._retry_without_single_obs` | `() -> tuple[result, note]` | 逐条剔除观测重试（最多 `min(观测数, 8)` 次）：每轮先查取消（取消即发信号并返回 `(None, "")`），构造排除第 skip 条的子集重新求解；`ValueError`（剔除后观测不足等）静默跳过换下一条；其他异常发 error 并返回 None；有候选即命中，生成提示 `"⚠ 提示：剔除第 {skip+1} 条观测后才有候选，该条坐标很可能抄错…"`（UI 端序号 = skip+1）返回；全部失败返回空结果 dict。 |
| `SeedReverserCalcThread._on_progress` | `(done, total, stage) -> None` | 求解器进度回调（工作线程内）：`time.monotonic` 距上次发出 ≥0.1 秒或 `done>=total`（收尾强制）时转发为 progress 信号。 |
| `SeedReverserCalcThread._format_summary` | `@staticmethod (stages, elapsed) -> str` | 求解统计转多行摘要：低位枚举位宽（low_bits）/ 层 1 幸存低位（layer1）/ 层 2 幸存候选（layer2）/ 层 3 精确验证（layer3）/ 耗时（秒，1 位小数）；stages 为空返回 `"耗时: --"`。 |
| `SeedReverserVerifyThread.__init__` | `(candidates, observations, version_key, parent=None)` | 拷贝候选列表、观测快照与版本键；初始化取消标志与节流时刻。 |
| `SeedReverserVerifyThread.progress` / `calc_finished` / `error` | 同上三个 Signal | 进度 `(已验证个数, 总数, 阶段名)`；完成 `(通过候选列表, 文本摘要)`，取消时空列表 + `CANCELLED_SUMMARY`；异常消息。 |
| `SeedReverserVerifyThread.request_cancel` | `() -> None` | 主线程调用置取消标志，线程安全。 |
| `SeedReverserVerifyThread.run` | `() -> None` | 逐候选正向验证：循环对每个 seed 调 `verify_candidate_seed(seed, observations, version_key)`，`ok` 即收集；每轮候选间检查 `_cancelled`（置位即发 `calc_finished([], CANCELLED_SUMMARY)` 返回）；进度按 0.1 秒节流、最后一个候选（`idx+1==total`）强制发 `(idx+1, total, "验证")`；异常兜底发 error；收尾 `calc_finished.emit(passed, f"共验证 {total} 个候选，通过 {len(passed)} 个")`。 |

**接口**：

- 被谁 import：仅 `Tools\tool_SeedReverser.py`（导入 `CANCELLED_SUMMARY`、`SeedReverserCalcThread`、`SeedReverserVerifyThread`）。
- 发出的信号：两个线程类各自发出 `progress("qlonglong","qlonglong",str)`、`calc_finished(list,str)`、`error(str)`；刻意不用 `finished` 作为自定义信号名（避免遮蔽 QThread 内置 finished）。进度/结果由 UI 层 `tool_SeedReverser.py` 的对应槽接收。
- 依赖的模块：`PySide6.QtCore`（`QThread`/`Signal`）、`time`（`perf_counter` 计时与 `monotonic` 节流）、`Utils\SeedReverser\structure_math`（`solve_structure_seeds` 三层漏斗求解器、`verify_candidate_seed` 正向全量比对——其 `on_progress(done,total,stage)` 与 `cancel()` 回调约定与本线程一致）。
- 与求解器的回调协议：`solve_structure_seeds` 通过 `on_progress` 回调上报各层进度（经 0.1 秒节流转发为信号）、通过 `cancel` 回调轮询取消标志（层间边界退出）、通过返回 dict 的 `candidates`/`stages` 键回传候选与统计、通过抛 `ValueError` 表达预期错误。

**关键变量/常量**：

模块常量：

| 常量 | 值 | 说明 |
| --- | --- | --- |
| `CANCELLED_SUMMARY` | `"__cancelled__"` | 取消结束时的 `calc_finished` 摘要标记（区别于正常统计摘要；UI 层据此分流取消分支）。 |
| `_PROGRESS_INTERVAL_S` | `0.1` | 进度信号节流间隔（秒），两线程共用；层 3/验证为逐候选回调，太密会淹没主线程事件循环。 |
| `_MAX_RETRY_SHOTS` | `8` | 空结果后逐条剔除单条观测重试的次数上限（每次另起一轮三层漏斗，上限过高拖慢失败反馈；正常前几次重试即可定位坏条目）。 |

实例状态（两个线程类同构）：

| 变量 | 说明 |
| --- | --- |
| `_observations` / `_candidates` | 输入数据拷贝（构造时 `list(...)` 浅拷贝，与 UI 侧后续修改隔离）。 |
| `_version_key` | 求解/验证所用版本键（决定结构参数表）。 |
| `_tol`（仅计算线程） | 缺省容差兜底值，仅对无 `"tol"` 键的观测生效。 |
| `_cancelled` | 取消标志（主线程 `request_cancel` 置位，工作线程经 `cancel` 回调轮询/候选间检查）。 |
| `_last_emit` | 上次 progress 发出时刻（`time.monotonic`，仅工作线程内访问，无锁）。 |

---

# 03d — StructurePreviewer 工具控制层文档

## `Tools/tool_StructurePreviewer.py`

**功能**：StructurePreviewer（结构预览器）工具页的控制层，按世界种子预览结构 3D 构造并预测箱子战利品。类 `StructurePreviewerWidget` 同时继承 `BaseToolWidget`（工具页基类，提供 Tab 标题 `tool_name()="StructurePreviewer"` 与首选窗口尺寸 `preferred_size=(1170, 826)`）和 Qt Designer 编译产物 `CodesUI.StructurePreviewer.Ui_structurePreviewer`，是 MCHelper 工具集合中的一页。当前源码共 1884 行。

整体数据流为一条「输入 → 枚举 → compose → 渲染 → 战利品 → 图标合成」的流水线：

1. **输入层**：世界种子（支持十进制、负数、`0x` 十六进制，校验 64 位有符号范围，`_parse_seed`）、版本键（`26.2`/`1.21.11`/`1.21`，来自 `structure_params.VERSION_KEYS`）、结构类型（12 种 `_STRUCT_KEYS`：igloo/shipwreck/ocean_ruin/stronghold/nether_fortress/bastion_remnant/end_city/trial_chambers/ancient_city/village/pillager_outpost/woodland_mansion）、锚点坐标 X/Z（手动输入或「粘贴F3+C」解析剪贴板）。「woodland_mansion」是 UI/展示/compose 用键，枚举与群系校验链路用 cubiomes 键 `mansion`，由 `_UI_TO_ENUM` 别名映射桥接。

2. **实例枚举（后台线程）**：单按钮两态的「附近的实例」态触发 `_on_locate_clicked`，创建 `_LocateThread`（QThread）在后台调用 `Utils/Public/structure_map.enumerate_structures`，以输入坐标（留空为原点）为中心 ±`_LOCATE_RADIUS`(2048) 方块视口，按结构所属维度（`structure_params.STRUCT_DIMENSION`，下界结构自动走 NetherSampler）逐区块枚举真实生成的结构实例（含群系校验，结果与游戏 `/locate` 一致），以 `progress`/`finished_ok`/`error` 信号回传主线程；结果按距中心距离平方排序填入左侧 `treeWidget`（结构/X/Z/群系四列），行 UserRole 存 `(x, z, 结构键)`，双击行加载实例，右键复制 F3+C 格式传送指令（`_tp_command` 生成 `/execute in <维度> run tp @s X 100 Z 0 0`）。

3. **compose（主线程同步）**：按钮「预览」态触发 `_on_preview_clicked`：先用 `check_structure_at` 对锚点做群系校验（主世界结构传入主线程新建的 `BiomeSampler`，下界/末地由校验函数内部惰性建采样器；校验失败仅提示「结构可能不存在，仅供 RNG 演示」，不阻断），再调用 `composition.compose(key, seed, bx, bz, biome_id, version_key)`——该函数逐行移植 cubiomes finders.c 的 `getVariant` + `getStructurePieces` RNG 消耗序列，产出 `Composition` 数据类（变种名/旋转/镜像/锚点/部件列表 `pieces`，其 `chests` property 汇总所有 `Chest{pos, loot_table, loot_seed, pos_model, pos3}`）。LootTableSeed 由 `loot_rng.get_population_seed` + salt 档推导（同区块流内 `nextLong` 消耗顺序即箱序），求值时用 `signed_seed` 转为 Java 有符号显示。

4. **3D 渲染（主线程）**：`composition.compose_display_model(comp)` 组装显示模型 dict（mesh/tex_keys/chest_blocks），注入 `Structure3DView`（`Utils/SeedReverser/structure_3dview.py` 的 QOpenGLWidget，在 `_init_ui` 中替换 `.ui` 的占位件）。本页视口默认**旁观者相机模式**（`set_spectator_mode(True)`，WASD+鼠标 FP 飞行，` 键呼出/锁定鼠标）；渲染体素里的全部容器方块经 `set_interact_chests` 注册为可交互箱（含 RNG 未预测的箱，如 bastion jigsaw 渲染箱多于预测箱），准星右键/E 发 `chest_open_requested` 信号回控制层弹战利品 GUI；点箱子列表行发 `set_chest_highlights` 琥珀描边。

5. **战利品计算（主线程同步）**：`loot_engine.era_for_version(version)` 得时代码 `era`；逐箱经 `_loot_table(table_name, era)`（带模块级 `_loot_cache`）取 `LootTable`，`loot_engine.generate_loot(table, chest.loot_seed)` 用标准 Java LCG（`loot_rng.JavaRandom`）按 Cubiomes-Loot 移植逻辑在 float32 域求值出 `ItemStack` 列表（附魔/炖菜效果按 RNG 顺序生成）；`_merge_stacks` 把同箱内物品/附魔/效果/药水完全相同的堆合并数量后填入 `chestList` 树（顶层行=箱：战利品表名 + LootTableSeed + 坐标；子行=物品：图标 + 中文名 x 数量，tooltip 为游戏风格富文本卡片）。

6. **物品图标合成**：子行与开箱槽位的图标来自 `assets/StructurePreviewer/items/<物品短名>.png`（16x16 原版纹理，1.21.11 客户端 jar 提取）；药水类物品走类型染色贴图 `<容器>_<药水短名>.png`（`_icon_key` 决定键，缺失回退基础短名）。附魔物品图标叠加游戏原版 `enchanted_glint.png` 流光：`CompositionMode_Plus` 加法混合两层反向滚动的光效纹理（不透明度 0.35），用物品不透明像素的 `QRegion` 剪裁防外溢；数量角标与开箱窗标题用游戏 ascii 字形 `font_ascii.json` 逐位画点（带 1px 右下阴影）。

**线程与主线程分工**（本模块并发模型的核心）：
- **后台线程只跑「附近实例枚举」**：`_LocateThread.run` 调用 `enumerate_structures`，其中含逐区块 RNG 计算与群系噪声采样（`BiomeSampler`/`NetherSampler` 初始化开销大），是唯一放入后台的重计算。线程持有 `_cancelled` 标志（`request_cancel`），枚举回调里转发进度；退出时 `aboutToQuit` 钩子 `_stop_locate_thread` 请求取消并 `wait(3000)` 同步收尾，防退出期 QThread 析构崩溃（0xC0000409）。
- **compose、compose_display_model、战利品求值均在主线程同步执行**（点击「预览」时），不做后台化——单次 compose/loot 求值耗时可控，换取实现简单与信号/槽零竞态；竞态防护改为「上下文签名」机制：枚举请求时记录 `_locate_sig`（种子/版本/结构/中心坐标五元组），完成回调 `_on_locate_ok` 时与当前 UI 比对，不一致则丢弃过期结果。
- **OpenGL 渲染**在 `Structure3DView` 自身（QOpenGLWidget 的 paintGL/GL 线程机制），控制层只通过 `set_model`/`set_chest_highlights`/`set_interact_chests` 等方法喂数据；流光动画由主线程 QTimer 驱动（`_GlintItemDelegate.FRAME_MS=50ms ≈20fps`，`_SlotWidget` 共享 `ChestLootDialog` 的定时器），每帧只推进位移相位并请求视口局部重绘，开销极低。

**loot 快照加载**（`Utils/StructurePreviewer/data/loot` 目录）：
- 控制层持 `_LOOT_DIR` 指向该目录，`_loot_table(table_name, era)` 调 `loot_engine.load_loot_snapshot(table_name, era, snapshot_dir=_LOOT_DIR)` 并按 `{era: {表名: LootTable}}` 缓存。
- 快照文件命名两种：无分档表为 `<表短名>.json`（如 `igloo_chest.json`、`bastion_bridge.json`、`intersection.json`、`end_city_treasure.json`）；分档表为 `<表短名>.<档>.json`，档位 ∈ {`1_20`, `1_21`, `1_21_11`}（如 `shipwreck_supply.1_21.json`、`woodland_mansion.1_20.json`、`ancient_city.1_21_11.json`）。选档由 `loot_engine._LOOT_TABLE_ERAS`（表名 → 双级 era 边界）决定：运行时 `era >= 边界1` 用 `1_21_11` 档，`>= 边界2` 用 `1_21` 档，否则用旧档（`1_20`）；分档快照按**档位自身**的 era 解析（版本自包含，对齐 C 烘焙表语义），未分档快照用运行时 era。
- 子表引用在**同目录**按 `<短名>.json` 解析一层（如 trial_chambers 的 `reward`/`reward_common`/`reward_rare`/`reward_unique`、`intersection`、`corridor`、`entrance` 等为独立快照文件）；缺失时报 unresolved（与 C 实现同语义）。试炼密室表 1.20.5 引入且各档内容一致（1.21+ 才有该结构），不参与分档。

**GUI 纹理**（均从 1.21.11 客户端 jar 提取的原图）：
- `slot.png`（`_SLOT_TEX`，18x18）：游戏容器单槽凹槽贴图——顶/左 `#373737` 内阴影 + 底/右 `#FFFFFF` 亮线 + `#8B8B8B` 内部，1x 直接绘制不缩放、scale 整数倍时与图标同步最近邻放大（按尺寸缓存 `_slot_tex_cache`）；`_SlotWidget` 用作槽底，文件缺失回退手绘三色凹槽。
- `generic_54.png`（`_PANEL_TEX`，256x256）：游戏大箱子 GUI 图集。`_load_panel_pixmap` 拼出单箱槽区面板：上段 `copy(0,0,176,71)`（17px 标题区 + 3 行箱槽 + 槽底白线）+ 下段 `copy(0,215,176,7)`（图集底部边框条）→ 176x78 画布，按 `GUI_SCALE=2` 最近邻放大后整窗拉伸（缓存 `_panel_cache`/`_panel_cache_scale`）；`ChestLootDialog` 的槽位网格坐标（x8 起、标题区 17px 下、步距 18）与该图集严格对齐；文件缺失回退纯色 `#C6C6C6` 面板。
- `font_ascii.json`（`_FONT_JSON`）：游戏 `ascii.png` 位图字形的预处理 JSON（由一次性脚本 `.temp/prep_pixel_font.py` 从 1.21.11 jar 的 default.json include 映射 + ascii.png 解析生成，零运行时解析），每字符含 `{x 内容起始列, w 内容宽, rows 8 行位图}`；`_draw_pixel_text` 用 `fillRect` 逐位画点（advance=内容宽+1、空格 advance=4、缺字形兜底 6），支持整体 1px 右下阴影层（阴影层先画、文字层后画，避免覆盖相邻字形）；用于 `_SlotWidget` 数量角标与 `ChestLootDialog` 标题条，JSON 缺失/损坏时回退系统粗体字体。
- 物品图标目录 `_ICON_DIR`（`assets/StructurePreviewer/items`）与流光纹理 `_GLINT_PATH`（`assets/Public/enchanted_glint.png`，128x128 原版 enchanted_glint_item，与 EnchantCaculator 共用）见常量表。

**会话持久化**：会话 JSON 为 `_SESSION_FILE`（`structure_previewer_session.json`），路径取 `QStandardPaths.AppConfigLocation`（取不到则回退工具文件所在目录），由 `_session_path` 拼出。字段共 4 个：`seed`（种子输入框原文）、`coord_x`、`coord_z`（坐标框原文，留空即空串）、`sensitivity`（镜头灵敏度滑条整数档 [1,30]）。写盘时机：退出钩子 `aboutToQuit` → `_save_session`，以及种子/坐标/版本/结构/灵敏度每次变化时（`_update_preview_button`/`_on_sensitivity_changed`/`_invalidate_context` 内联调用）；`_session_ready=False`（启动恢复完成前）抑制写盘防半恢复状态回写；读盘在 `_restore_session`（启动时），文件缺失/损坏/类型不符均静默跳过，`sensitivity` 越界不恢复。写盘失败仅打印不干扰交互（与 SeedReverser 会话同口径）。

**已知妥协**（源码头注释声明）：igloo 3D 模型不随 rotation/mirror 旋转（公式含隐藏 piece 内偏移，反解不唯一），仅模型角度保留妥协，RNG/坐标不受影响；shipwreck 全 20 个官方变种模板已就位。

---

### 类与函数

#### 模块级函数（翻译/缓存/渲染资源加载）

| 名称 | 签名 | 说明 |
|---|---|---|
| `_loot_table` | `(table_name: str, era: int) -> loot_engine.LootTable` | 按 era 取缓存的 LootTable：`_loot_cache.setdefault(era, {})` 查表，未命中走 `loot_engine.load_loot_snapshot(table_name, era, snapshot_dir=_LOOT_DIR)`；文件缺失异常上抛由调用方捕获显示。试炼密室表单文件不参与分档。 |
| `_tp_command` | `(x: int, z: int, struct_key: str) -> str` | 实例锚点 → 可粘回游戏聊天栏的传送指令（F3+C 同款 `/execute in minecraft:<维度> run tp @s X 100 Z 0 0`）。Y 固定 100（结构上空），视角归零；维度按 `structure_params.STRUCT_DIMENSION` 展开（tp 不跨维度生效，下界结构必须 execute in the_nether）。 |
| `_potion_display_name` | `(item_short: str, potion_id: str) -> str` | 药水类型 → 游戏同款中文名。剥 `minecraft:` 前缀后识别 `strong_`（强效）/`long_`（普通版同名）前缀，基名查 `_POTION_BASE_CN`（药水名而非效果 id，如 swiftness/healing），未知基名用效果名兜底 `<效果>药水`；按容器加前缀：`splash_potion`→喷溅型、`lingering_potion`→滞留型、`tipped_arrow`→药水箭/`<名>箭`。 |
| `_icon_key` | `(stack: loot_engine.ItemStack) -> str` | ItemStack → 图标键：取 `minecraft:` 后缀短名；药水类（`_POTION_ITEMS`）且带 potion 时构造染色贴图键 `<容器>_<药水短名>`，用 `_icon_key_cache` 缓存其存在性探测，贴图存在才用染色键，否则回退基础短名。 |
| `_item_label` | `(stack: loot_engine.ItemStack) -> str` | ItemStack → 「皮革帽子（保护III） x3」式列表显示文本。药水类优先用类型名（效果信息已含名内，时长不再附括号）；普通物品查 `_ITEM_CN`，附魔拼「中文名+罗马等级」顿号列表，效果（炖菜）附「效果名 N秒」（时长已乘 20 tick，除 20 还原秒）；末尾 `x数量`。 |
| `_rom` | `(n: int) -> str` | 附魔等级 → 罗马数字（查 `_ROMAN` 表 1~10），越界回退阿拉伯数字。 |
| `_item_tooltip_html` | `(stack: loot_engine.ItemStack) -> str` | ItemStack → 游戏 tooltip 风格富文本：嵌套表格实现边框（Qt 富文本不画 CSS border，外层 `#5000FF` 单元格 cellpadding=1 露 1px 作紫色描边，内层 `#100010` 近黑紫底）；首行物品名白字（含 xN），附魔每行灰字（`#AAAAAA`）+ 罗马等级，诅咒附魔红字（`#FF5555`），效果行灰字秒数。 |
| `_merge_stacks` | `(items: list[ItemStack]) -> list` | 同箱内完全相同物品合并数量：键为 `repr((item, tuple(enchantments), effect, potion))`（药水类型并入键），首次出现顺序保留（与 RNG 产出顺序一致），可合并不相邻重复堆；先克隆再累加，不修改调用方原对象（防上游共享引用的 count 被污染或重复计数）。 |
| `_load_item_pixmap` | `(key: str) -> tuple \| None` | 加载 16x16 物品纹理 `(QPixmap, 不透明区 QRegion\|None)`，`_item_pix_cache` 缓存（含 None 负缓存）；文件缺失/空图返回 None（行无图标）。QRegion 由 `createMaskFromColor(透明, MaskInColor)` 生成，供流光剪裁到物品不透明像素。 |
| `_load_item_scaled` | `(key: str, scale: int) -> tuple \| None` | 按 scale 返回预缩放 `(图标, 剪裁区)`：16x16 最近邻（FastTransformation 像素风不插值）放大到 `round(16*scale*0.8)`（`_ICON_SLOT_RATIO` 缩小 20%），剪裁区从缩放后图生成（随尺寸自动同步），`(key, scale)` 维度缓存于 `_item_scaled_cache`；QBitmap 必须先包 QRegion 再 translated（QBitmap 无 translated，直接传 QPainter.updateClipRegion 会崩）。 |
| `_load_glint_pixmap` | `(size: int) -> QPixmap \| None` | 加载并预缩放附魔光效纹理到 `size*2` 边长（KeepAspectRatioByExpanding 保证平铺无缝），`_glint_cache` 按尺寸缓存多规格共存；`_GLINT_OK=False` 时返回 None。 |
| `_load_panel_pixmap` | `(scale: int = 1) -> QPixmap \| None` | 加载 generic_54.png 并两段拼接 176x78 单箱面板（上段 71px + 下段 7px 边框条，1x 几何见常量表），按 scale 整数倍最近邻放大；全局缓存 `_panel_cache`/`_panel_cache_scale`（单规格，换 scale 重建）；文件缺失/空图返回 None（调用方回退纯色背景）。 |
| `_load_glyphs` | `() -> dict` | 懒加载字形 JSON（`_FONT_JSON`），`_glyph_cache` 全局单例；OSError/ValueError 时置 `{}`（调用方回退系统字体）。 |
| `_pixel_text_size` | `(text: str) -> tuple[int, int]` | 像素文字 1x 尺寸：逐字符累加 advance（内容宽+1、空格 4、缺字形 6），高恒 8 像素。 |
| `_draw_pixel_text` | `(p: QPainter, x: int, y: int, text: str, color: QColor, scale: int = 1, shadow: QColor \| None = None) -> None` | 用游戏字形画像素文字：按位图 rows 逐位 `fillRect` 画点（先收集全部点再分层画），shadow 先画偏移 (scale, scale) 的阴影层再画文字层；缺字形/空格按 advance 兜底推进。 |

#### 渲染视口 / 3D 绘制与物品绘制组件

| 名称 | 签名 | 说明 |
|---|---|---|
| `_GlintItemDelegate` | `class _GlintItemDelegate(QStyledItemDelegate)` | 战利品子行委托：行首绘制物品图标，附魔物品图标叠加动态流光。类常量：`ICON=16`（图标边长）、`PAD=4`（与文本间距）、`FRAME_MS=50`（流光帧间隔 ≈20fps）、`SCROLL=1`（两层每帧位移 px，反向）。 |
| `_GlintItemDelegate.__init__` | `(tree: QTreeWidget, parent=None)` | 持树引用与快/慢层相位 `_t_fast`/`_t_slow`；自建共享 QTimer（50ms）连 `_advance`，`_GLINT_OK` 时启动。 |
| `_GlintItemDelegate.stop` | `() -> None` | 停流光定时器（工具页退出钩子 `_stop_glint_delegate` 调用，防退出期重绘崩溃）。 |
| `_GlintItemDelegate._advance` | `() -> None` | 每帧推进两层位移（模 ICON 循环）并 `viewport().update()` 整视口重绘。 |
| `_GlintItemDelegate.paint` | `(painter, option, index) -> None` | 四段绘制：① 背景与选中态走原 `CE_ItemViewItem`（清空 text/icon 防重复画）；② 图标画行首（UserRole 存图标键，`_load_item_pixmap` 取图）；③ 附魔物品（`_ENCHANTED_ROLE`）在图标不透明区内 `CompositionMode_Plus` + 透明度 0.35 画两层反向滚动光效（2x2 平铺保证滚动无缝）；④ 文本从图标区右侧起绘，沿用行前景色（琥珀高亮）与 ElideRight 省略号。无图标键/图标缺失时整体回退原实现。 |
| `_SlotWidget` | `class _SlotWidget(QLabel)` | 游戏同款容器槽位（开箱 GUI 用）：类常量 `SLOT=18`（1x 槽距）、`GLINT_MS=50`。构造时按 `stack` 装载：`_icon_key`→`_load_item_scaled` 取缩放图标与剪裁区，`_ench`=有附魔，`_count`=数量，tooltip=游戏风格富文本；鼠标指针设手型；附魔且流光可用时连接外部 `glint_timer`（与同箱其他槽共享定时器）。 |
| `_SlotWidget._advance_glint` | `() -> None` | 推进两层流光相位（周期=图标跨度 `16*scale`，倍缩放无缝循环）并 `update()` 自绘。 |
| `_SlotWidget.paintEvent` | `(ev) -> None` | 四段绘制：① 槽底贴原版 slot.png（按尺寸缓存最近邻放大），缺失回退手绘三色凹槽（#8B8B8B 内部/#373737 顶左阴影/#FFFFFF 底右亮线）；② 图标缩小 20% 居中绘制（槽内 (s,s) 起算居中偏移）；③ 附魔流光 Plus 混合两层反向滚动，剪裁区平移到图标起点；④ 数量 >1 时右下角像素字体白字 + 1px 阴影 `#3F3F3F`（字形缺失回退系统粗体多向描边），右对齐 17px 线。 |

#### 开箱容器 GUI（游戏大箱子界面复刻）

| 名称 | 签名 | 说明 |
|---|---|---|
| `ChestLootDialog` | `class ChestLootDialog(QDialog)` | 箱子战利品 GUI：游戏大箱子同款 3x9 槽位布局 + 原版面板贴图。类常量 `GUI_SCALE=2`（整体缩放，1x=游戏原生 176x90 面板区）。 |
| `ChestLootDialog.__init__` | `(items: list, title: str, parent=None)` | 非模态（`setModal(False)`，show 而非 exec，防模态阻塞主窗事件循环造成卡死假象）；设置 tooltip 样式表 + 调色板（QToolTip/QTipLabel 底色 `#100010`、边框 0，去 Windows 白框，双保险只作用于本对话框）；`_glint_timer` 仅当 items 前 27 堆中有附魔物品才创建启动（关窗随对象销毁）；调 `_build_ui`。 |
| `ChestLootDialog._build_ui` | `(items: list) -> None` | 无边框窗（FramelessWindowHint）+ 真半透明（WA_TranslucentBackground，generic_54 四角斜切圆角透桌面，须 show 前设置）；窗体固定为面板尺寸；27 槽 3 行 x 9 列行优先摆放 `_SlotWidget`（物品按 generate_loot 产出顺序依次入槽，不合并——游戏实际入箱序），空槽补位到 27；边距对齐图集（左 8/上 17/右 6/下 7）；空箱显示「（空）」，超 27 堆防御性提示未显示数量。 |
| `ChestLootDialog.paintEvent` | `(ev) -> None` | 面板背景：两段拼接贴图整窗拉伸（缺失回退纯 `#C6C6C6`）；标题条：17px 标题区居中深灰（`#404040` + 1px 阴影 `#101010`）像素文字；超宽自适应——2x 放不下先降 1x 渲染，再放不下按「..」省略号截断（防 loot 表全路径切字成字形残缺）；字形缺失回退系统字体居中。 |
| `ChestLootDialog.changeEvent` | `(ev) -> None` | 失焦自动关：`ActivationChange` 事件且可见且失活即 close（悬浮面板行为）。背景：非模态无边框窗无关闭钮，焦点被锁定态视口/主窗/其它程序夺走后 Esc/E 会被吞，GUI 关不掉（实测死锁），失活即关兜底；close 走 finished 信号 → 控制层解锁链路。 |
| `ChestLootDialog.keyPressEvent` | `(ev) -> None` | E 键（非自动重复）关闭窗口（同游戏关闭容器界面）；Esc 默认 reject 同样隐藏；非模态用 close()（accept() 仅对 exec 事件循环有意义）。 |

#### 枚举线程（后台）

| 名称 | 签名 | 说明 |
|---|---|---|
| `_LocateThread` | `class _LocateThread(QThread)` | 附近实例枚举线程，复用 `enumerate_structures`，结构粒度进度。信号：`progress(int, int)`（done, total）、`finished_ok(list)`（实例字典列表）、`error(str)`。 |
| `_LocateThread.__init__` | `(seed: int, version_key: str, struct_key: str, center_x: int, center_z: int, parent=None)` | 保存种子/版本/结构键（此处已是 cubiomes 键）/中心坐标，`_cancelled=False`。 |
| `_LocateThread.request_cancel` | `() -> None` | 置取消标志（进度回调与完成前检查均短路），由退出钩子与新枚举前的防重入路径使用。 |
| `_LocateThread.run` | `() -> None` | 以中心 ±`_LOCATE_RADIUS` 构造视口四元组，调 `enumerate_structures(seed, version, viewport, [struct_key], on_progress=转发 progress, cancel=查标志, dimension=STRUCT_DIMENSION 查表)`——下界结构必须按维度枚举（缺省 overworld 会被维度防御过滤成空）；结果按距中心距离平方升序排序后发 `finished_ok`；取消则静默返回；异常且未取消时发 `error("实例枚举失败：…")`。 |

#### 主控件（控制层核心）

| 名称 | 签名 | 说明 |
|---|---|---|
| `StructurePreviewerWidget` | `class StructurePreviewerWidget(BaseToolWidget, Ui_structurePreviewer)` | 工具页主控件；`preferred_size=(1170, 826)`。 |
| `StructurePreviewerWidget.__init__` | `(parent=None)` | `setupUi` 后创建 `Structure3DView` 替换 `.ui` 占位件（`gridLayout.replaceWidget` + 隐藏占位），连接视口三信号并 `set_spectator_mode(True)`；初始化实例状态（`_model`/`_selected_chest=-1`/`_loaded_pos=None`/`_locate_sig`/`_session_ready=False`/`_locate_thread`/`_locate_result`/`_chest_dlg=None`/`_current_era=-1`）；调 `_init_ui`。 |
| `tool_name` | `@classmethod () -> str` | 返回 `"StructurePreviewer"`（Tab 标题，基类约定）。 |
| `_init_ui` | `() -> None` | 一次性装配：① `_fit_groupbox_layouts` 改装三个 GroupBox 布局；② 版本下拉填 `VERSION_KEYS`；③ 结构下拉按 `_STRUCT_KEYS`（经 `_UI_TO_ENUM` 查 cubiomes 名与 `structure_icons.icon_path` 图标，userData 存 UI 键）；④ 信息/提示文案（hintLabel 必须 setWordWrap，否则 minimumSizeHint 撑爆网格列）；⑤ 实例树 4 列表头 + 隔行变色，箱子树 1 列 + itemClicked + 自定义 `_GlintItemDelegate`（iconSize 16）；⑥ 进度条隐藏；⑦ 按钮两态信号（btnPreview/pasteBtn/坐标框 textChanged）、灵敏度滑条 [1,30] + 默认 5；⑧ 实例行双击/右键菜单；⑨ 结构/版本/种子变化连 `_invalidate_context`；⑩ aboutToQuit 三个退出钩子（停线程/停流光/存会话）；⑪ `_restore_session` 后置 `_session_ready=True`。 |
| `_session_path` | `() -> str` | 会话文件路径：`QStandardPaths.AppConfigLocation` 可写目录（空则工具文件目录），makedirs 后拼 `_SESSION_FILE`。 |
| `_save_session` | `() -> None` | 保存 seed/coord_x/coord_z/sensitivity 四字段 JSON（ensure_ascii=False, indent=2）；`_session_ready=False` 时直接返回；OSError 仅打印。 |
| `_restore_session` | `() -> None` | 启动恢复：文件缺失/损坏/非 dict 静默跳过；字段逐一类型校验后 setText/setValue（sensitivity 须在 [_SENS_MIN, _SENS_MAX] 内）。 |
| `_on_sensitivity_changed` | `(value: int) -> None` | 滑条变化：`value/100.0` 得度/像素，`_view.set_spectator_sensitivity` 应用视口，标签显示「镜头灵敏度 X.XX°/px」，并落盘会话。 |
| `_fit_tree_widget` | `@staticmethod (tree: QTreeWidget, content_cols: int = 0) -> None` | 树视图防溢出：ElideRight 省略 + 横向滚动条常隐 + 滚动按像素 + 末列 stretchLastSection + 最小列宽 32；content_cols>0 时前 N 列 ResizeToContents（实例树 结构/X/Z 列）；uniformRowHeights 加速大列表。 |
| `_fit_groupbox_layouts` | `() -> None` | `.ui` 编译产物中 infoLabel/treeWidget/chestList 是 setGeometry 绝对定位（GroupBox 缩放不跟随），本方法为 infoGroupBox/locateGroupBox/chestsGroupBox 各装 QVBoxLayout 让内容填满；infoLabel 另设 WordWrap + TextBrowserInteraction（可选中复制）。 |
| `_parse_seed` | `@staticmethod (text: str) -> int` | 解析种子：空报错；`0x`/`-0x` 前缀按十六进制，否则十进制；范围 [-2^63, 2^63) 否则报「超出 64 位有符号整数范围」；失败抛 ValueError 由调用方显示。 |
| `_parse_int` | `@staticmethod (text: str, what: str, default: int \| None = None) -> int` | 坐标解析：空且给 default 用 default（如枚举中心留空=0），否则报「请输入 X 坐标」；非整数报错。 |
| `_parse_f3c` | `@classmethod (text: str) -> tuple[int, int, str \| None]` | 解析 F3+C 剪贴板 → (X, Z, 维度\|None)。正则抓 `in <ns> run tp` 提取维度（the_nether/the_end 归一为 nether/end）；`_F3C_NUM_RE = -?\d+(?:\.\d+)?` 抓全部数字，少于 3 个报错；Y 与视角忽略，X/Z 用 `math.floor` 取整（对齐游戏）。兼容 `/execute in ... run tp @s X Y Z Yaw Pitch`、`/tp @s X Y Z`、纯坐标三种形式。 |
| `_current_struct_key` | `() -> str` | 结构下拉当前 userData（UI 键），兜底 `"igloo"`。 |
| `_on_paste_f3c` | `() -> None` | 读剪贴板 → `_parse_f3c` → 填 X/Z（textChanged 连锁复位按钮两态）；空剪贴板/解析失败/维度不匹配（F3+C 维度 ≠ 当前结构所属维度）分别在 infoLabel 提示，成功提示「已填入 (x, z)，点附近的实例查找」。 |
| `_is_loaded_current` | `() -> bool` | 按钮两态判据：`_loaded_pos` 非空且坐标框两框文本（strip 后）与之相等。 |
| `_update_preview_button` | `() -> None` | 坐标匹配已加载实例 → 按钮文字「预览」（tooltip：显示该坐标处结构与战利品预测），否则「附近的实例」（tooltip：以输入坐标为中心枚举）；随后落盘会话。 |
| `_context_signature` | `() -> tuple` | 当前搜索上下文签名：`(种子原文, 版本文本, 结构键, X 原文, Z 原文)`，供枚举结果竞态比对。 |
| `_invalidate_context` | `() -> None` | 结构/版本/种子变化：作废 `_loaded_pos`、清空实例树与 `_locate_result` 缓存、复位按钮、落盘——实例列表只对请求时上下文有效，旧行双击会预览出错误组合，必须清空。 |
| `_on_locate_clicked` | `() -> None` | 枚举入口（按钮「附近的实例」态）：线程进行中直接返回（防重入）；解析种子与中心坐标（留空 0,0）；记录 `_locate_sig` 竞态基线；按钮禁用 + 进度条忙碌态（setRange(0,0)）+ 清实例树；创建 `_LocateThread`（结构键经 `_UI_TO_ENUM` 换 cubiomes 键），连接 finished→deleteLater/`_on_locate_finished`、finished_ok/`_on_locate_ok`、error/`_on_locate_error`，start。 |
| `_stop_locate_thread` | `() -> None` | 退出钩子：丢引用 → `request_cancel` → `wait(3000)` 同步等线程收尾（finished→deleteLater 已在创建处连接，C++ 对象随事件循环回收，防退出期析构崩溃）。 |
| `_stop_glint_delegate` | `() -> None` | 退出钩子：`_glint_delegate.stop()` 停流光动画定时器。 |
| `_on_locate_finished` | `() -> None` | 线程结束统一收尾（正常/取消/异常均触发 finished）：丢线程引用、恢复按钮、隐藏进度条。 |
| `_on_locate_ok` | `(items: list) -> None` | 枚举结果回填：签名 ≠ 当前上下文 → 提示丢弃（竞态防护）；存 `_locate_result`、清树、空结果提示「附近 N 方块内未找到」；每行四列（结构名/X/Z/biome_label 群系中文名）+ 整行 tooltip + UserRole 存 `(x, z, struct)`（右键复制按行自带键展开维度，不依赖当下下拉状态）；成功提示找到 N 个实例。 |
| `_on_locate_error` | `(msg: str) -> None` | 枚举异常信息显示到 infoLabel。 |
| `_on_instance_activated` | `(item, _col) -> None` | 双击实例行：取 UserRole 坐标 → 写 `_loaded_pos`（按钮即变「预览」态）→ 填两坐标框 → 直接触发 `_on_preview_clicked` 加载预览。 |
| `_on_instance_context_menu` | `(pos) -> None` | 右键实例行：从行 UserRole 结构键查 `STRUCT_DIMENSION`/`DIMENSION_NAMES` 得维度中文名，弹单项菜单「复制TP指令（<维度>，F3+C 格式）」→ `_copy_instance_tp`。 |
| `_copy_instance_tp` | `(item) -> None` | 行传送指令写入剪贴板（`_tp_command`，菜单动作与离屏测试共用实现），infoLabel 提示 Y=100 上空自行调高。 |
| `_on_preview_clicked` | `() -> None` | 预览主流程（两态统一入口）：非「已加载当前坐标」态 → 转 `_on_locate_clicked`；否则解析种子/X/Z，依次：① 别名映射取枚举键；② 群系校验——主世界结构新建 `BiomeSampler`（下界/末地传 None 走 check_structure_at 内部惰性采样器），`check_structure_at` 得 (viable, biome)；③ `composition.compose(UI 键, seed, bx, bz, biome_id, version)` 得 comp（biome<0 传 -1）；④ `composition.compose_display_model(comp)` 得 model 注入视口（`set_model`），清箱子选中与高亮（`set_chest_highlights(None)`），`set_interact_chests(model["chest_blocks"])` 注册可交互箱；⑤ `loot_engine.era_for_version` 得 era，缓存 `_comp`/`_era` 供 3D 开箱按序取用，`_fill_chests` + `_fill_info`；异常统一显示「预览失败：…」。compose 与 loot 均在主线程同步执行。 |
| `_fill_info` | `(comp, viable: bool, biome: int, seed: int, version: str) -> None` | 结构信息区多行文本：结构名（查 cubiomes 键）+ 变种名（与键同名不重复展示）、锚点/旋转/镜像、群系（viable=False 加「未通过生成校验」警告）；按结构追加专属行——igloo 地下室（有则竖井段数）、shipwreck 搁浅、nether_fortress/end_city/trial_chambers/pillager_outpost 部件数（end_city 加含末地船、trial 加密室层 y）、bastion 起点类型（`_BASTION_START_CN`）、ancient_city 中心类型（`_ANCIENT_CITY_START_CN`）+ 底面 y、village 变体/僵尸标记/中心序号/地基 y、stronghold 部件数 + 传送门已填眼数（bin 计 1）/12、woodland_mansion 拼装旋转/房间件数/覆盖区块、ocean_ruin 水温/大型/簇件/部件数；末行箱子数。 |
| `_fill_chests` | `(comp, era: int, viable: bool, biome: int) -> None` | 箱子列表填充：无箱子改表头「（无箱子）」；逐箱顶层行 =「箱N（表名）@ (x, z)｜LootTableSeed: 有符号值」（`loot_rng.signed_seed`）；`_loot_table` + `generate_loot` 求值（异常时子行显示「战利品求值失败」）；`_merge_stacks` 合并后每堆一个子行（`_item_label` 文本 + `_item_tooltip_html` 富文本 tooltip + UserRole 图标键 + 有附魔置 `_ENCHANTED_ROLE`）；空箱显示「（空）」；最后 expandAll。 |
| `_on_chest_open_requested` | `(idx: int) -> None` | 视口准星态右键/E 开箱：idx 是交互箱全集（model["chest_blocks"]）下标，按模型坐标匹配 `_comp.chests` 中 `pos_model` 相等的预测 Chest（无预测数据 → `note_chest_gui_closed` 恢复鼠标 + 提示，不编造战利品）；用缓存 `_era` 重新 `generate_loot`（**不合并**，槽位摆放=游戏实际入箱序）；标题用剥 `chests/` 前缀的表短名 + 坐标（防像素字体 2x 面板 352px 装不下全路径被切）；非模态单实例：先换 `_chest_dlg` 引用再连 finished（防旧窗 finished 误撤新锁），关旧（close+deleteLater）、`show` 新窗、`set_spectator_input_locked(True)` 锁视口 FP 输入。 |
| `_on_spectator_close_request` | `() -> None` | 锁定态视口 Esc/E 转发：若开箱窗可见则 close。双保险兜底——正常路径靠弹窗失焦自关，焦点停在视口的平台边缘态由此兜底。 |
| `_on_chest_dlg_finished` | `() -> None` | 开箱窗 finished（E/Esc/失焦关闭）：`sender() is self._chest_dlg` 校验后 `set_spectator_input_locked(False)` 解锁视口——替换重开时旧窗 close 的 finished 同步到达，此时引用已指向新窗，不误撤新窗输入锁。 |
| `_on_chest_clicked` | `(item, _col) -> None` | 点箱子列表：子行归到其父顶层行，取顶层序号 `_selected_chest`，全部顶层行前景刷琥珀（`_HIGHLIGHT_AMBER`，其余复位默认），视口 `set_chest_highlights([model["chests"][idx]])` 琥珀描边该箱。 |
| `_on_render_error` | `(msg: str) -> None` | 视口 `render_error` 信号落地：显示到 infoLabel（如 GL 初始化/着色失败降级信息）。 |
| `keyPressEvent` | `(ev) -> None` | ` 键全局兜底：焦点不在 3D 视口时按 ` 且视口可见、处于旁观者模式、鼠标未锁定（未控制态）→ 焦点给视口并 `spectator_toggle_grab()` 开始控制视角（锁定态 ` 由视口自身处理呼出）。 |

---

### 接口

**被哪些模块 import**：
- `Tools/__init__.py`：`from .tool_StructurePreviewer import StructurePreviewerWidget`，并注册进 `TOOL_CLASSES` 工具表（主窗口按此工厂创建 Tab 页）。无其他模块直接 import 本文件。

**信号**：
- 本模块定义并发出（均在 `_LocateThread` 上，跨线程queued 到主线程）：
  - `progress(int, int)`——枚举进度 (done, total)，控制层未连接显示（进度条用忙碌态），保留给进度 UI；
  - `finished_ok(list)`——实例字典列表（元素含 struct/name/x/z/cx/cz/biome 键）；
  - `error(str)`——枚举失败消息。
- 本模块接收（连接到 `StructurePreviewerWidget` 的外部信号）：
  - `Structure3DView.render_error(str)` → `_on_render_error`（渲染失败提示）；
  - `Structure3DView.chest_open_requested(int)` → `_on_chest_open_requested`（准星开箱请求，参数为交互箱下标）；
  - `Structure3DView.spectator_close_request()` → `_on_spectator_close_request`（锁定态 Esc/E 兜底关窗）。
- 基类 `BaseToolWidget.request_status_message` 本工具未使用。

**依赖的 Utils 模块**：
- `Utils/Public/structure_map`——`BiomeSampler`（群系采样器，实际定义于 `Utils/SeedReverser/biome_noise.py`，经 structure_map 转出）、`check_structure_at`（锚点群系校验，返回 (viable, biome_id)，下界/末地维度自动惰性建 NetherSampler/EndSampler）、`enumerate_structures`（后台枚举，支持 viewport/struct_keys/on_progress/cancel/dimension 参数）。
- `Utils/Public/structure_params`——`VERSION_KEYS`（版本下拉）、`STRUCT_NAMES`（结构中文名）、`STRUCT_DIMENSION`（结构 → overworld/nether/end 维度路由，tp 指令/枚举维度/校验采样器选择三处使用）、`DIMENSION_NAMES`（维度中文名）。
- `Utils/Public/biome_names`——`biome_label(bid)`（群系 id → 中文名）。
- `Utils/Public/structure_icons`（as `struct_icons`）——`icon_path(enum_key)`（结构图标路径，复用 MapPreviewer 资产）。
- `Utils/SeedReverser/structure_3dview`——`Structure3DView`（OpenGL 3D 视口：set_model/set_chest_highlights/set_interact_chests/set_spectator_mode/set_spectator_sensitivity/set_spectator_input_locked/note_chest_gui_closed/is_spectator_mode/mouse_grabbed/spectator_toggle_grab）。
- `Utils/StructurePreviewer/composition`——`compose(struct_key, world_seed, block_x, block_z, biome_id, version_key)`（getVariant+getStructurePieces RNG 移植，12 结构各有 compose_xxx 分派）、`compose_display_model(comp)`（体素拼装显示模型：mesh/tex_keys/chest_blocks/chests 等键）。数据类 `Chest`（pos/loot_table/loot_seed/pos_model/pos3）、`Piece`、`Composition`（pieces + chests property）。
- `Utils/StructurePreviewer/loot_engine`——`load_loot_snapshot`（快照分档加载）、`era_for_version`（版本键 → era）、`generate_loot(table, seed)`（Java LCG 整表求值）、类型 `LootTable`/`ItemStack`。
- `Utils/StructurePreviewer/loot_rng`——`signed_seed`（无符号 64 位 → Java 有符号显示）。
- 其他：`Tools/tool_base.BaseToolWidget`（基类）、`CodesUI.StructurePreviewer.Ui_structurePreviewer`（Qt Designer UI）、标准库 `json/math/os/re`、PySide6 QtCore（QEvent/QRect/QSize/QStandardPaths/Qt/QThread/QTimer/Signal）、QtGui（QBrush/QColor/QFont/QIcon/QPainter/QPalette/QPen/QPixmap/QRegion）、QtWidgets（QApplication/QDialog/QGridLayout/QHeaderView/QLabel/QMenu/QStyle/QStyledItemDelegate/QTreeWidget/QTreeWidgetItem/QVBoxLayout）。

---

### 关键变量/常量

#### 资源路径与资源缓存常量

| 名称 | 值/类型 | 说明 |
|---|---|---|
| `_SESSION_FILE` | `str` = `"structure_previewer_session.json"` | 会话持久化文件名，落在 QStandardPaths AppConfigLocation 目录。 |
| `_SENS_MIN` / `_SENS_MAX` / `_SENS_DEFAULT` | `1` / `30` / `5` | 灵敏度滑条整数档范围与默认值；实际灵敏度 = 档位/100 度/像素（0.01~0.30）。 |
| `_STRUCT_KEYS` | `tuple[str, ...]`（12 项） | 本工具支持的结构键：igloo/shipwreck/ocean_ruin/stronghold/nether_fortress/bastion_remnant/end_city/trial_chambers/ancient_city/village/pillager_outpost/woodland_mansion；下界结构维度路由查 `structure_params.STRUCT_DIMENSION`。 |
| `_UI_TO_ENUM` | `{"woodland_mansion": "mansion"}` | UI 键 → cubiomes 键别名映射（枚举/校验/图标/显示名链路用），compose 仍用 UI 键。 |
| `_LOOT_DIR` | `str` 路径 | loot 快照目录 `<项目根>/Utils/StructurePreviewer/data/loot`，传给 `load_loot_snapshot`。 |
| `_ITEM_CN` | `dict[str, str]`（约 160 项） | 物品短名 → 中文 Wiki 名（六张表全集 + 试炼密室/要塞/林地府邸/远古城市/海底废墟/掠夺者前哨站/堡垒遗迹/村庄补全）。 |
| `_ENCH_CN` | `dict[str, str]`（44 项） | 附魔短名 → 中文名（loot_engine.ENCHANTMENT_ORDER 全集）。 |
| `_EFFECT_CN` | `dict[str, str]`（39 项） | 状态效果全名（minecraft:xxx）→ 中文名（1.21.11 原版 39 效果全集，loot 产出 id 均可命中）。 |
| `_ROMAN` | `tuple`（""~"X"） | 附魔等级罗马数字表（1~10 足够，越界回退阿拉伯）。 |
| `_HIGHLIGHT_AMBER` | `QColor(0xF1, 0xC4, 0x0F)` | 选中箱子行的前景琥珀色，与视口箱子描边同色。 |
| `_ICON_DIR` | `str` 路径 | 物品图标目录 `<项目根>/assets/StructurePreviewer/items`，16x16 原版纹理（1.21.11 jar 提取，方块物品/新版定义/重命名已折算为 `<短名>.png`）。 |
| `_GLINT_PATH` / `_GLINT_OK` | `str` 路径 / `bool` | 附魔光效纹理 `<项目根>/assets/Public/enchanted_glint.png`（原版 enchanted_glint_item，128x128，与 EnchantCaculator 共用）；`_GLINT_OK` 为启动时存在性探测，False 时全链路禁用流光。 |
| `_GUI_DIR` | `str` 路径 | 容器 GUI 贴图目录 `<项目根>/assets/StructurePreviewer/gui`（slot.png/generic_54.png/font_ascii.json 同目录）。 |
| `_SLOT_TEX` / `_PANEL_TEX` | `str` 路径 | 18x18 单槽凹槽贴图 / 256x256 大箱子 GUI 图集（细节见「GUI 纹理」节）。 |
| `_FONT_JSON` | `str` 路径 | 游戏字形数据 `_GUI_DIR/font_ascii.json`（预处理 JSON，零运行时解析）。 |
| `_item_pix_cache` | `dict[str, tuple \| None]` | 原始物品纹理缓存 {短名: (QPixmap, QRegion\|None)}，含 None 负缓存。 |
| `_item_scaled_cache` | `dict[tuple, tuple \| None]` | 缩放纹理缓存 {(短名, scale): (QPixmap, QRegion\|None)}。 |
| `_glint_cache` | `dict[int, QPixmap]` | 流光纹理按尺寸缓存（size → 2x size 贴图）。 |
| `_slot_tex_cache` | `dict[int, QPixmap]` | slot.png 按目标尺寸（18*scale）缓存。 |
| `_panel_cache` / `_panel_cache_scale` | `QPixmap \| None` / `int` | 单箱面板拼装结果全局缓存（单规格，scale 变化重建）。 |
| `_glyph_cache` | `dict \| None` | 字形 JSON 全局单例（None=未加载，{}=加载失败回退态）。 |
| `_icon_key_cache` | `dict[str, bool]` | 药水染色贴图存在性缓存 {候选键: bool}。 |
| `_loot_cache` | `dict[int, dict[str, LootTable]]` | loot 表缓存 {era: {表名: LootTable}}，随实例预览按需构建。 |

#### 面板几何与绘制参数

| 名称 | 值 | 说明 |
|---|---|---|
| `_PANEL_W` / `_PANEL_H` | `176` / `78` | 单箱面板 1x 几何（游戏 3 行容器标准上半部）。 |
| `_PANEL_TOP_H` | `71` | 上段高：标题区 + 3 行槽 + 槽底白线（generic_54 的 (0,0,176,71)）。 |
| `_PANEL_STRIP_Y` / `_PANEL_STRIP_H` | `215` / `7` | 下段取条：图集底部边框条 (0,215,176,7)（探针实测槽行 y=18/36/54 起、y214 白线、y219 #555555、y221 黑边）。 |
| `_ICON_SLOT_RATIO` | `0.8` | 槽内图标绘制比例（图标缩小 20%：边长 = round(16*scale*0.8)）。 |
| `_ENCHANTED_ROLE` | `Qt.ItemDataRole.UserRole + 1` | 战利品子行自定义角色：UserRole=图标键，UserRole+1=有附魔（流光开关）。 |
| `_CURSE_KEYS` | `frozenset({"vanishing_curse", "binding_curse"})` | 诅咒附魔短名（tooltip 中显示红色）。 |
| `_POTION_BASE_CN` | `dict[str, str]`（21 项） | 药水基名（potion id 短名，非效果 id——swiftness/healing 等与效果不同名）→ 中文名。 |
| `_POTION_ITEMS` | `frozenset`（4 项） | 药水/药水箭容器物品（potion/splash_potion/lingering_potion/tipped_arrow），图标走类型染色贴图。 |
| `_BASTION_START_CN` | `tuple`（4 项） | bastion start 变种索引 → 中文短名（堡垒主体/疣猪兽棚/宝藏房/桥，非官方命名）。 |
| `_ANCIENT_CITY_START_CN` | `tuple`（3 项） | ancient_city 中心变种索引 → 中文短名（中心喷泉型/大型中心型/回字环型，非官方命名）。 |
| `_LOCATE_RADIUS` | `2048` | 附近实例枚举半径（方块；单侧 ±2048 ≈ 128 区块半径视口）。 |
| `_F3C_NUM_RE` | 编译正则 `-?\d+(?:\.\d+)?` | F3+C 内容中的数字抓取（含负号与小数）。 |

#### StructurePreviewerWidget 实例状态

| 名称 | 类型/初值 | 说明 |
|---|---|---|
| `_view` | `Structure3DView` | 3D 视口实例（替换 .ui 占位件），旁观者相机模式。 |
| `_model` | `dict \| None` | 当前注入的显示模型（compose_display_model 输出），箱子行高亮取 `model["chests"]`。 |
| `_selected_chest` | `int`，`-1` | 当前选中箱子序号（0 起，-1 未选）。 |
| `_loaded_pos` | `tuple[str, str] \| None` | 已加载预览的实例坐标 (x_str, z_str)；按钮两态判据：坐标框内容与之相等 → 「预览」，否则「附近的实例」。 |
| `_locate_sig` | `tuple \| None` | 本次枚举请求的上下文签名（种子/版本/结构/中心坐标），完成回调时与当前 UI 比对丢弃过期结果。 |
| `_session_ready` | `bool`，`False` | 会话恢复完成前置 False 抑制写盘（防半恢复状态回写）。 |
| `_locate_thread` | `_LocateThread \| None` | 进行中的枚举线程引用（防重入 + 退出钩子收尾）。 |
| `_locate_result` | `list[dict]` | 最近一次枚举结果缓存。 |
| `_chest_dlg` | `ChestLootDialog \| None` | 开箱窗引用（非模态 show 持引用防 GC；重开先关旧）。 |
| `_current_era` | `int`，`-1` | 当前预览 era（loot 缓存键域；实际取用走 `_era`）。 |
| `_glint_delegate` | `_GlintItemDelegate` | 箱子列表自定义委托（图标 + 流光绘制）。 |
| `_comp` / `_era` | `Composition` / `int` | 预览成功后缓存的 compose 结果与 era，供 3D 开箱（准星右键/E）按模型坐标匹配预测箱并按序求值战利品。 |

# 4. 附魔计算器（Utils/EnchantCaculator）

# 附魔计算器模块文档（Utils/EnchantCaculator/）

> 本文档覆盖附魔计算器工具的全部 9 个源文件，依据源码逐行整理。模块整体数据流：
> `enchant_data_manager`（enchants.json 单例数据源）→ `choose_items`（物品+附魔选择对话框）→
> `card_list_widget`/`enchanted_item_card`（物品卡片展示）→ `conflict_resolver`（冲突决策）→
> `anvil_optimizer`（最优合并方案搜索，纯逻辑无 Qt）→ `anvil_steps_tree`（方案图形化渲染）。
> UI 层入口为 `Tools/tool_EnchantCaculator.py`（主界面）与 `CodesUI/ChooseEnchantedItems.py`（Designer 生成的选择窗 UI）。

---

## `Utils/EnchantCaculator/enchant_data_manager.py`

**功能**：附魔数据管理器，单例模式加载项目根目录 `data/enchants.json`，为附魔计算器提供统一的查询接口（附魔条目、按类别/物品筛选、经验消耗表、最大等级、互斥冲突列表）。数据文件中 `enchants` 数组的每条记录含 8 个字段：`id`（英文标识，如 `aqua_affinity`）、`name`（中文名）、`max_level`、`level_cost_from_items`（物品间合并的各等级经验消耗表）、`level_cost_from_book`（从附魔书合并的消耗表，同等级两表数值不同）、`applicable`（适用物品类型列表，所有附魔均含"附魔书"）、`category`（近战武器/工具/远程武器/防具/通用附魔/诅咒）、`conflicts`（互斥附魔 ID 列表）、`description`。

单例实现：重写 `__new__` 使所有 `DataManager()` 调用返回同一实例，`_initialized` 标志保证只在首次创建时读盘，后续调用直接复用内存数据。路径定位：当前文件位于 `Utils/EnchantCaculator/`，向上三级 `dirname` 回到项目根，拼出 `<根>/data/enchants.json`，并用 `os.makedirs(exist_ok=True)` 自动建目录。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `DataManager` | `class DataManager` | 单例数据管理器，全模块共享一个实例与一份数据 |
| `__new__` | `(cls) -> DataManager` | 首次调用创建实例并置 `_initialized=False`，之后返回同一实例 |
| `__init__` | `() -> None` | 仅首次初始化执行：置 `_initialized=True`、`data={"enchants": []}`，随即 `load_data()` 读盘 |
| `_get_data_path` | `() -> str` | 计算项目根下 `data/enchants.json` 绝对路径，顺带确保 `data` 目录存在 |
| `load_data` | `() -> None` | 文件不存在则先调 `_create_default_data` 建默认文件；然后 `json.load` 读入 `self.data`；`JSONDecodeError`/`IOError` 时打印原因并回退为空数据兜底，不崩溃 |
| `save_data` | `() -> None` | `json.dump` 写回文件，`ensure_ascii=False` 保中文、`indent=2` 美化；IO 异常仅打印不中断 |
| `get_all_enchants` | `() -> List[Dict]` | 返回全部附魔列表（分类 Tab 初始化时遍历筛选用） |
| `get_enchant_by_id` | `(enchant_id: str) -> Optional[Dict]` | 线性遍历按 `id` 查找，未找到返回 `None` |
| `get_enchants_by_category` | `(category: str) -> List[Dict]` | 返回 `category` 字段等于给定值的附魔列表 |
| `get_enchants_for_item` | `(item_type: str) -> List[Dict]` | 返回 `applicable` 列表包含该物品类型的全部附魔 |
| `get_level_cost` | `(enchant_id: str, level: int, is_from_book: bool) -> Optional[int]` | 按 `is_from_book` 选 book/items 消耗表，等级 1-based 直接索引（1 级=下标 0），越界返回 `None` |
| `get_max_level` | `(enchant_id: str) -> Optional[int]` | 返回附魔最大等级，不存在返回 `None` |
| `get_conflicts` | `(enchant_id: str) -> List[str]` | 返回互斥附魔 ID 列表的拷贝，无数据返回 `[]` |

**接口**：被 `Utils/EnchantCaculator/choose_items.py` 与 `Tools/tool_EnchantCaculator.py` 直接 import；`anvil_optimizer.AnvilMechanics` 与 `conflict_resolver` 虽不 import 本模块，但以鸭子类型持有 DataManager 实例（仅调用 `get_enchant_by_id`/`get_level_cost`/`get_conflicts` 三个查询方法）。

**关键变量/常量**：

| 名称 | 说明 |
|---|---|
| `_instance` | 类属性单例实例 |
| `_initialized` | 实例属性，防止重复读盘 |
| `self.data` | 内存中的完整 JSON 数据 `{"enchants": [...]}` |
| `enchants.json` 记录字段 | `id`/`name`/`max_level`/`level_cost_from_items`/`level_cost_from_book`/`applicable`/`category`/`conflicts`/`description` |

**已知缺陷**（如实记录，未改动代码）：`load_data` 在文件不存在时调用 `self._create_default_data(file_path)`，但该方法在类中（及全项目）并无定义；由于 `data/enchants.json` 实际存在，正常运行不会触发，但若数据文件缺失，此分支会抛出 `AttributeError` 而非按注释预期生成默认数据。

---

## `Utils/EnchantCaculator/anvil_optimizer.py`

**功能**：铁砧合成优化器，模拟 Java 版铁砧机制（纯逻辑、不依赖 Qt，便于单元测试），并搜索把多件物品（含附魔书）合并成一件、总经验花费最少的合并顺序。文件头注释逐条对照中文 Minecraft Wiki「铁砧机制」声明了计费依据，要点如下：

1. **单次合并总花费** = 目标 PWP + 牺牲 PWP + 合并魔咒花费（本工具假设物品满耐久、不重命名，故不含维修费/重命名费）。
2. **累积惩罚 PWP**（Prior Work Penalty）：物品每经历一次铁砧合并，惩罚在前值基础上 ×2+1，n 次后为 2^n−1；合并时玩家支付双方 PWP 之和，结果物品的 PWP 基于**两者中较高者**再算下一层（如 3 与 7 合并 → 结果 15）。
3. **合并魔咒花费**（Java 版按输出物品上该魔咒的最终等级计费）：对牺牲物品的每条魔咒——不适用于输出物品类型 → 直接忽略不计费；输出物品已有互斥魔咒（含目标原有或本次已转移的）→ 不转移，每有一个互斥魔咒 +1 级；否则计费 = 乘数表[输出最终等级]，牺牲是书用书乘数表，否则用物品乘数表。**即使牺牲等级低于目标、等级不上升，仍按输出最终等级计费**。
4. **等级合并规则**：目标无此魔咒 → 获得牺牲等级；牺牲更高 → 升至牺牲等级；相同 → +1；牺牲更低 → 目标等级不变；结果均不超过 `max_level`。
5. **合法性（方向敏感）**：牺牲（铁砧第二格）必须与目标（第一格）同类型（书+书视为同类型），或牺牲本身是附魔书；**附魔书做目标时只能吞另一本书**——把剑等非书物品"吸收"进书里是游戏中不存在的操作；不同类型非书物品无法合并。
6. **"过于昂贵"**：生存模式单次操作 >39 级（即 ≥40）铁砧拒绝执行，优化器在方案中把此类步骤序号记入 `too_expensive_steps` 供 UI 红色警示（计费仍按原值累计）。

**核心算法流程（`AnvilOptimizer`）**：

- **输入**：`items: list[AnvilItem]`（每件物品 = 类型名 + 魔咒 frozenset{(id, 等级)} + 初始 PWP，全部叶子 PWP=0，frozenset 保证状态可哈希）与 `required_enchants: frozenset`（用户在冲突对话框中选择的、最终合成物必须包含的附魔 ID 集）。
- **预处理（`optimize`）**：空列表抛 `AnvilError`；单件时检查是否已含全部保留附魔，满足则返回零步方案，否则抛错。合法性预检：收集全部非书物品的类型名，多于 1 种 → 铁砧不可能合成一件，直接抛 `AnvilError`。由此确定**终态类型约束** `required_type`：有非书物品则最终必须是该类型，全为书则必须是"附魔书"。
- **精确搜索（`_search_exact`，n ≤ 8 件时启用）**：在"剩余物品多重集合"状态空间上跑 **Dijkstra 最短路**：
  1. 状态表示：剩余物品列表；等价键 = `tuple(sorted(剩余物品, key=repr))`（同一多重集合的不同排列归并为同一键）。起始状态入堆：`(0, 0, next(counter), start_key, [], items)`，元组前两维分别是累计花费与步数，第三维是 `itertools.count()` 递增序号——保证 `heapq` 的元组比较在整数上终止，永不触及后面的 list。
  2. 每轮 `heappop` 取 (花费, 步数, 序号) 字典序最小的状态：**先保证总花费最小，花费相同时步骤数更少的优先**。若 `cost > best[key]`（该状态已以更低花费到达过）则丢弃；若只剩 1 件物品且通过 `_is_goal`（类型匹配 + 含全部 required_enchants）→ 命中目标，直接 `break`（Dijkstra 性质保证首个出堆的终态即全局最优）；只剩 1 件但不满足约束 → 死状态不再扩展。
  3. 扩展：枚举当前所有**有序对** `(i, j), i≠j`（有序是关键——剑+书与书+剑是两次不同操作），经 `can_merge` 过滤后逐一 `merge` 得 `(result, fee, detail)`；新状态 = 移除 i、j 两个物品 + 追加 result；`new_cost = cost + fee`，若优于 `best` 中该键的记录则更新并压堆。源码注释说明：曾考虑"保留附魔被互斥拦截后找不回"的可行性剪枝，为保守起见**不剪**，交由终态判定兜底（状态数有限，正确性优先）。
  4. 搜索耗尽仍无终态 → 抛 `AnvilError`，提示物品自带的互斥附魔无法移除、会把所选附魔拦在铁砧外。
  5. 复杂度：状态数与物品的合并划分结构同阶（Bell 数量级，n=8 时可控），每状态枚举 O(n²) 有序对，每次 `merge` 对牺牲魔咒排序后 O(E log E)。
- **贪心降级（`_search_greedy`，n > 8 件）**：每轮枚举全部合法有序对并逐一 `merge` 试算，按二元组 `rank = (是否拦截保留附魔, 本次花费)` 取最小者执行（源码中先看 `blocked_kept`：若本次计费明细中存在"required_enchants 中的 ID 且原因是互斥"则 rank 首位记 1 加大虚拟惩罚，实际花费不变）；无任何合法对 → 抛错；循环至剩一件。合法性（含"书不能吞非书"）由方向敏感的 `can_merge` 统一保证，输出类型 = 目标类型，终态自然满足 `required_type`。
- **费用计算公式汇总**：`总花费 = Σ各步 [ t.pwp + s.pwp + Σ魔咒费 ]`；魔咒费 = 0（不适用）/ 每个互斥 +1（不转移）/ `get_level_cost(id, final_lv, s 是书)`；`final_lv` 由等级合并规则得出；结果 PWP 用位运算技巧计算——`pwp = 2^n − 1` 的二进制恰为 n 个 1，故已完成操作次数 `n = pwp.bit_length()`，结果 PWP = `2^(max(双方 bit_length) + 1) − 1`。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_roman` | `(lv: int) -> str` | 等级转罗马数字（查 `_ROMAN` 表），超界回退阿拉伯数字 |
| `AnvilError` | `class AnvilError(Exception)` | 优化无法完成时抛出 |
| `AnvilItem` | `@dataclass(frozen=True) (name, enchants, pwp, label="")` | 铁砧世界中的不可变物品，作搜索状态节点 |
| `AnvilItem.make` | `(name, enchant_pairs, pwp=0, label="") -> AnvilItem` | 便捷构造：自动把魔咒对列表转 frozenset |
| `AnvilItem.enchant_map` | `() -> dict` | 魔咒集合转 `{id: 等级}` 字典 |
| `AnvilItem.has_enchant` | `(eid) -> bool` | 是否拥有某附魔（按 id 匹配，不看等级） |
| `AnvilItem.is_book` | `() -> bool` | `name == "附魔书"` |
| `AnvilItem.display_label` | `(data_manager=None) -> str` | 展示标签；`label` 为空时自动生成，有 DataManager 用中文名，否则用 ID，格式如 `剑（锋利V、抢夺III）` |
| `MergeStep` | `@dataclass (target, sacrifice, result, cost, detail={})` | 一次铁砧操作；`detail` 含 `pwp_cost`/`enchant_costs`/`ignored` 三段计费明细 |
| `AnvilPlan` | `@dataclass (steps, total_cost, final_item, too_expensive_steps=[])` | 完整合并方案；`too_expensive_steps` 为花费 ≥40 的步骤序号（1-based） |
| `AnvilMechanics` | `(data_manager)` | Java 版铁砧机制模拟，纯函数式 |
| `AnvilMechanics._enchant` | `(eid) -> Optional[dict]` | 转发 `dm.get_enchant_by_id` |
| `AnvilMechanics._name_of` | `(eid) -> str` | 附魔中文名，查无数据回退 ID 字符串 |
| `AnvilMechanics._applicable_to` | `(eid, item_name) -> bool` | 魔咒是否适用于某物品类型（数据中所有附魔的 applicable 均含"附魔书"，故书书互并时魔咒正常转移） |
| `AnvilMechanics._cost` | `(eid, final_level, from_book) -> int` | 按输出最终等级查乘数表计费，查无返回 0 |
| `AnvilMechanics.can_merge` | `(target, sacrifice) -> bool` | 方向敏感合法性：同类型（含书书）或牺牲是书 |
| `AnvilMechanics.merge` | `(target, sacrifice) -> (result, cost, detail)` | 核心合并模拟：初始化 `cost = 双方 PWP 之和`，输出魔咒从目标拷贝并实时更新（冲突检查基于它），遍历牺牲魔咒（sorted）按"不适用→忽略 / 互斥→每项+1级不转移 / 否则等级合并+按输出最终等级计费"三类处理；结果类型 = 目标类型；结果 PWP 按位长公式；同时生成人类可读的 `label` 与计费 `detail` |
| `AnvilOptimizer` | `(data_manager, max_items_for_exact=8)` | 优化器入口类，持有 `AnvilMechanics` 与精确搜索的物品数阈值 |
| `AnvilOptimizer.optimize` | `(items, required_enchants=frozenset()) -> AnvilPlan` | 入口：空/单件处理、非书类型一致性预检、确定 `required_type`，按件数分流精确/贪心 |
| `AnvilOptimizer._is_goal` | `(item, required_enchants, required_type) -> bool` | 终态判定：类型匹配且含全部保留附魔 |
| `AnvilOptimizer._search_exact` | `(items, required_enchants, required_type) -> AnvilPlan` | Dijkstra 精确搜索（流程见上） |
| `AnvilOptimizer._search_greedy` | `(items, required_enchants, required_type) -> AnvilPlan` | 贪心降级（流程见上） |
| `build_items_from_cards` | `(cards_data: list) -> list` | 面向 UI 的入口：把卡片数据包 `[{"item_name", "enchants": [{"id","name","level"}]}]` 转成初始 PWP=0 的 `AnvilItem` 列表并生成展示标签 |

**接口**：被 `Tools/tool_EnchantCaculator.py` import（`AnvilOptimizer`/`AnvilError`/`build_items_from_cards`，开始计算按钮的主链路）；被 `anvil_steps_tree.py` import（`AnvilPlan` 类型标注）。对外核心类型即三个 dataclass 与优化器。

**关键变量/常量**：

| 名称 | 说明 |
|---|---|
| `BOOK_ITEM = "附魔书"` | 附魔书的物品类型名（与数据 applicable、UI 下拉框一致） |
| `_ROMAN` | 罗马数字表 `["", "I", ..., "X"]` |
| `AnvilItem.enchants` | `frozenset{(id, 等级)}`，frozen 保证可哈希、可作状态键 |
| `MergeStep.detail` | `{"pwp_cost": 双方惩罚和, "enchant_costs": [(id, 输出等级, 费用, 原因)], "ignored": [(id, 原因)]}`，驱动步骤图悬停明细 |
| `best` 字典 | `_search_exact` 的等价状态→已知最小花费映射，兼做去重与剪枝 |

---

## `Utils/EnchantCaculator/anvil_steps_tree.py`

**功能**：把 `AnvilOptimizer` 输出的 `AnvilPlan` 渲染成图形化合成步骤图（`QGraphicsView` 场景），支持两种 `displayMode`：**树模式**（默认，自上而下——顶层为全部原始物品叶子框，向下每层是一次合并的产物框，最底部为最终合成物；方框内为物品图标，左子树=目标/第一格、右子树=牺牲/第二格，严格对应铁砧摆放）与**步骤图模式**（每步一行 `[目标框] + [牺牲框] = [产物框]`，行首行末标注步骤序号与花费）。通用交互：带附魔的方框叠加游戏附魔流光（紫色流光双层反向滚动，视图级 QTimer 统一驱动）；悬停方框/花费圆标弹出游戏 tooltip 风格提示（深紫背景+紫描边，物品名白色+附魔灰字罗马数字）；汇合线上挂圆形经验标记（数字=该步花费等级，≥40 变红）；最终框加粗描边，下方标注总花费与"过于昂贵"警告。

树构建的关键设计：`_find_producer` 按**对象身份**（`is`）而非值相等在步骤表中回溯某中间物品的产出步骤。原因：优化器构造步骤表时后一步的 target/sacrifice 就是前一步 result 的同一对象（引用传递，身份链完整）；若按值匹配，两条路径产出完全相同的中间物品（如两对相同附魔书分别合并）会重复展开同一产出者、丢失真正的原始物品叶子。布局采用两遍算法：`_set_rows` 自底向上算行号（叶子=0，合并=max(子行)+1），`_place_x` 中序遍历分配横向位置（叶子占固定槽位宽，合并节点居中于两子中心）。

流光实现细节（`_ItemBox.paint`）：光效纹理 96×96 预缩放为 2×2 平铺尺寸；**平铺间距必须等于纹理边长**——间距小于边长会使相邻瓦片在图标区内重叠，加法混合重复叠加形成周期性亮斑；由于 96px 纹理的平移量在 [−48,−1] 时单片即可完整覆盖 48×48 图标区，每层只需绘制一次，与卡片 `_GlintIcon` 的 2×2 循环平铺数学等价。光效经 `createMaskFromColor` 生成的剪辑区域限制在物品不透明像素内，`CompositionMode_Plus` 加法混合、`opacity 0.35`，只提亮不遮盖原色。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_glint_texture` | `() -> QPixmap` | 光效纹理懒加载 + 全场景共享单份 QPixmap；路径首用时解析（避免模块导入期路径依赖），文件缺失返回 null pixmap 由调用方按无光效处理 |
| `_Node` | `(kind, item=None, step=None, step_index=None)` | 合并树节点：`kind`="leaf"/"merge"；另有 `role`（"final"/"target"/"sacrifice"）、`left`/`right`、`row`、`cx`、`box` |
| `_find_producer` | `(steps, before, item) -> Optional[int]` | 在 `steps[0..before)` 中按 `result is item` 身份匹配找产出步骤序号 |
| `_build_tree` | `(steps) -> _Node` | 以最后一步为根递归建树；target/sacrifice 若是此前某步产物则继续展开为该步，否则为原始物品叶子；build/wrap 用包装函数互相递归 |
| `_set_rows` | `(node) -> int` | 自底向上行号：叶子 0，合并 = max(子行)+1 |
| `_place_x` | `(node, x_left) -> float` | 中序布置横向位置，返回子树占用宽度；合并节点 `cx` = 两子 `cx` 均值 |
| `_ItemBox` | `class _ItemBox(QGraphicsItem)` | 物品方框：白底黑描边 68×60，内含 48px 图标（`FastTransformation` 保像素锐利），缺图标回退灰色物品名文字；`role=="final"` 描边 3px 加粗 |
| `_ItemBox.advance_glint` | `() -> None` | 推进两层流光位移一帧（快层 +1、慢层 −1，均对 `_ICON` 取模）并 `update()` 重绘 |
| `_ItemBox.paint` | `(painter, option, widget=None)` | 画白底、描边、图标；有附魔时 `save`→`setClipRegion`（物品不透明区）→`CompositionMode_Plus`→`opacity 0.35`→两层各画一次光效→`restore` |
| `_ItemBox._tooltip_lines` | `() -> list[(text, color)]` | 首行物品名（白）+ 各附魔行"名称 罗马等级"（灰） |
| `_CostCircle` | `(step, step_no, too_expensive, view)` | 半径 12 的经验花费圆标：白底、≥40 用 `_WARN_COLOR` 红否则绿；数字为该步花费；悬停弹出"第 N 步·花费 X 级"+ 计费明细 |
| `_GameTooltip` | `(parent)` | 游戏 tooltip 风格悬浮框，挂在视图 viewport 上，`WA_TransparentForMouseEvents` 鼠标事件穿透 |
| `_GameTooltip.popup` | `(lines, cursor_local) -> None` | 按内容自适应宽高，显示在光标右下；越界自动翻转到左上，最后收边钳制在视口内 |
| `_GameTooltip.paintEvent` | `(event)` | 关抗锯齿（像素风格）：深紫背景→1px 内描边→2px 紫外描边→逐行绘制文本 |
| `AnvilStepsTree` | `class AnvilStepsTree(QGraphicsView)` | 步骤图主控件 |
| `AnvilStepsTree.__init__` | `(parent=None)` | 建场景、背景 `#ECECEC`、关抗锯齿、居中对齐；建 tooltip 与 50ms 流光定时器；初始 `clear_plan()` |
| `AnvilStepsTree.placeholder_text` / `is_placeholder` / `boxes` / `cost_circles` / `final_box` | — | 只读状态接口：占位文案、是否占位、当前全部方框列表、全部花费圆标列表、最终合成物方框（占位时 None），供测试与外部检查 |
| `AnvilStepsTree._advance_glint` / `_ensure_glint_timer` | `() -> None` | 定时器回调：无带附魔方框时自停省开销；渲染新方案后按需重启 |
| `AnvilStepsTree.clear_plan` | `() -> None` | 隐藏 tooltip、清场景与缓存，放一条斜体灰色占位文字 |
| `AnvilStepsTree.show_plan` | `(plan: AnvilPlan, data_manager=None, mode="tree")` | 主入口：清场景后按 mode 分流树/步骤模式；树模式无步骤（单物品）时只画一个 final 叶子框；末尾统一 `setSceneRect` 收边 |
| `AnvilStepsTree._show_plan_steps` | `(plan, too_exp)` | 步骤图模式：逐行布置目标/牺牲/产物三框 + 加粗大号 `+`/`=` 运算符 + `=` 号上方花费圆标 + 行末"第 N 步·花费 X 级（过于昂贵）"标签（昂贵时红字）；最后一步产物框 role="final" |
| `AnvilStepsTree._draw_node` | `(node, too_exp)` | 树模式递归绘制：先子后父（父框需引用子框），再画本框 |
| `AnvilStepsTree._draw_merge_links` | `(node, too_exp)` | 直角汇合连线（子框底边→上引至汇合横线 `lane_y=y-18`→横连→竖直下行入产物框顶），`zValue=0` 垫在框下；同点位挂花费圆标 |
| `AnvilStepsTree._draw_summary` | `(plan, cx, bottom_y)` | 树/步骤两模式共用：最终框下方居中"总花费 X 级"，有昂贵步骤时再叠一行红色警告 |
| `AnvilStepsTree._ench_name` | `(eid) -> str` | 附魔 ID → 中文名（查 DataManager），无则回退 ID |
| `AnvilStepsTree._step_detail_lines` | `(step) -> list` | 把 `MergeStep.detail` 转成 tooltip 明细行：累积惩罚、各魔咒"原因，+X 级"、忽略项 |
| `AnvilStepsTree.show_tooltip` / `hide_tooltip` | `(lines)` / `()` | 供场景内 item 调用：把全局光标位置映射到 viewport 局部坐标后弹/收悬浮框 |

**接口**：被 `Tools/tool_EnchantCaculator.py` import（`AnvilStepsTree`，主窗口右侧渲染区）。依赖 `anvil_optimizer.AnvilPlan` 与 `enchanted_item_card` 的 `int_to_roman`/`get_item_icon_path`/四个 tooltip 配色常量（保证方框与卡片、悬浮框视觉一致）。

**关键变量/常量**：

| 名称 | 说明 |
|---|---|
| `_GLINT_TEX_PATH` | 模块级光效纹理路径缓存（None=未解析） |
| `_BOX_W=68, _BOX_H=60, _ICON=48` | 方框与图标尺寸 |
| `_LEAF_GAP=18, _SIBLING_GAP=30, _ROW_H=88, _STEP_GAP=44, _MARGIN=16` | 树/步骤两模式的版面间距 |
| `_LINE_COLOR=#1A1A1A, _TEXT_COLOR=(70,70,70), _WARN_COLOR=(190,30,30), _COST_COLOR=(30,130,30)` | 连线描边 / 总花费文字 / 过于昂贵红 / 花费圆标绿 |
| `self._boxes / self._circles / self._placeholder_item / self._dm` | 视图维护的场景对象缓存与 DataManager 引用 |
| `_glint_timer` | 视图级 50ms QTimer：QGraphicsItem 非 QObject 不能自挂定时器，由视图统一推进全部带附魔方框 |

---

## `Utils/EnchantCaculator/card_list_widget.py`

**功能**：物品卡片列表控件（`QListWidget` 子类），横排流式展示已添加的物品卡片（`IconMode` + `LeftToRight` + 自动换行 + 间距 8），视口背景淡灰 `#ECECEC`。在 Qt 默认行为之上实现四类增强交互：Del/Backspace 删除选中卡片、再次点击已选中卡片取消选中、左键拖动卡片交换位置（自实现 `QDrag`，关闭 Qt 内部拖动）、外部按钮调用 `clear_cards()` 全清。三个信号把卡片集合变化上报给主窗口：`cardRemoved(list)`（被删卡片的附魔 ID 列表）、`cardReordered()`（拖动换位成功）、`cardsCleared(list)`（被清空卡片的附魔 ID 并集）。

**卡片控件管理策略**（本模块最重要的工程决策）：卡片数据（`{"item_name", "enchants"}`）完整存放在 `QListWidgetItem` 上（`CARD_DATA_ROLE`），任何结构变化（移动、替换、批量移除附魔）之后都**按数据重建全新卡片控件**，绝不尝试重绑旧控件。原因：`takeItem` 时视图会对该行 editor 触发 `closeEditor→deleteLater` 异步销毁，重绑旧控件与销毁时序冲突（不同事件路径表现不同，实测结论）。重建通过 `QTimer.singleShot(0, ...)` 推迟到事件循环下一拍执行，确保发生在旧控件销毁完成之后；重建后必须同步 `item.setSizeHint(card.sizeHint())`——编辑可能增删附魔行导致新卡片高度变化，沿用旧 sizeHint 会被视图按旧高度裁剪（附魔文字与底边框被切掉的根因）。

拖动判定只认自定义 MIME 类型 `_MIME_CARD`（`application/x-card-reorder`），该类型仅本控件 `_start_reorder_drag` 会携带，天然排除外部拖入（下方附魔列表拖的是 `text/plain`）；刻意不依赖 `event.source()`——手动构造的拖放事件 `source()` 为 None，依赖它会破坏可测试性。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `CardListWidget` | `class CardListWidget(QListWidget)` | 物品卡片列表主控件 |
| `__init__` | `(parent=None)` | 配置流式布局/间距/单选/无右键菜单；`setDragEnabled(False)`+`setAcceptDrops(True)` 为自实现拖动做准备；视口调色板 Base 色承淡灰背景 |
| `add_card` | `(data: dict) -> None` | 按 `ChooseItemsWindow.selected_data` 数据包新建 `EnchantedItemCard` 挂到条目，同时写入 `CARD_IDS_ROLE`（附魔 ID 列表）与 `CARD_DATA_ROLE` |
| `card_enchant_ids` | `(item) -> list` | 读取条目上的附魔 ID 列表 |
| `replace_card` | `(item, data: dict) -> None` | 编辑卡片确认后原位替换数据并延迟重建控件，条目行号不变 |
| `all_card_data` | `() -> list[dict]` | 汇总全部条目的数据包，供冲突检测与优化器输入 |
| `remove_enchants_everywhere` | `(removals: dict) -> None` | 按 `{物品名: [待移除附魔 ID]}` 批量过滤各卡片的附魔（同一物品多张卡都处理），有变化的数据走延迟重建 |
| `clear_cards` | `() -> None` | 收集全部附魔 ID→`clear()`→发 `cardsCleared`；空列表直接返回 |
| `keyPressEvent` | `(event)` | Del/Backspace 删除当前选中项并消费按键 |
| `_remove_item` | `(item)` | `takeItem` 后发 `cardRemoved` |
| `mousePressEvent` | `(event)` | 左键按下记录 `_pressed_item`/`_press_pos`/`_press_on_selected`，供"点击取消选中"与"启动拖动"共用 |
| `mouseMoveEvent` | `(event)` | 左键按住且曼哈顿位移 ≥ `DRAG_THRESHOLD`(8px) → 启动换位拖动 |
| `mouseReleaseEvent` | `(event)` | 未拖动且按在已选中卡上 → 取消选中；**取消必须在 `super().mouseReleaseEvent` 之后**——Qt 父类会按按下时的 pressedIndex 恢复选中，先取消会被覆盖 |
| `_start_reorder_drag` | `(item)` | 构造 QDrag：MIME 携带起始行号，拖动图标 = 卡片透明底实时快照，`exec_` 阻塞至松手 |
| `_transparent_snapshot` | `@staticmethod (widget) -> QPixmap` | 用 `QImage(Format_ARGB32_Premultiplied)` + `render(DrawChildren)` 渲染透明背景快照（`grab()` 会强制填不透明底，悬浮跟随生硬） |
| `dragEnterEvent` / `dragMoveEvent` | `(event)` | 仅接受带 `_MIME_CARD` 的拖动，MoveAction |
| `dropEvent` | `(event)` | 解析起始行号（`ValueError`/越界 ignore）；目标行 = 光标处项之前，光标在空白处 → 移到末尾；调用 `_move_item` |
| `_move_item` | `(from_row, to_row) -> bool` | 执行搬移：`to_row` 落在 `(from_row, from_row+1)` 视为落回原位不算移动；`takeItem` 后按 `to_row>from_row` 修正插入行；被移动行延迟重建控件，其余行不受影响；完成后选中该卡并发 `cardReordered` |
| `_rebuild_card_at_item` | `(item, data)` | 在仍存在的条目上新建卡片控件并更新 `sizeHint`（防裁剪）；条目已不存在则放弃 |

**接口**：被 `Tools/tool_EnchantCaculator.py` import（`CardListWidget`，主窗口物品卡片区）。依赖 `enchanted_item_card.EnchantedItemCard` 渲染单张卡片。

**关键变量/常量**：

| 名称 | 说明 |
|---|---|
| `_MIME_CARD = "application/x-card-reorder"` | 内部换位拖动 MIME，兼做外部拖入过滤器 |
| `CARD_IDS_ROLE = Qt.UserRole` | 条目上存附魔 ID 列表 |
| `CARD_DATA_ROLE = Qt.UserRole + 3` | 条目上存完整数据包 dict（+1/+2 留给条目其他用途） |
| `DRAG_THRESHOLD = 8` | 启动拖动的最小位移（px），量级对齐 `QApplication.startDragDistance` |
| `_pressed_item / _press_pos / _press_on_selected / _drag_active` | 鼠标按下状态组，取消选中与拖动判定共用 |

---

## `Utils/EnchantCaculator/enchanted_item_card.py`

**功能**：附魔物品卡片组件与其依赖工具：单张卡片 = 物品图标（上）+ 游戏 tooltip 风格附魔方框（下）。视觉完全参照 Minecraft 游戏内物品悬停提示框（深紫近黑背景 + 紫色双层描边 + 首行白色物品名 + 其余灰色附魔行罗马数字等级），并复刻了附魔物品的紫色流光动画。本模块同时是附魔计算器 UI 族的**视觉常量与工具函数源头**：tooltip 配色常量被 `anvil_steps_tree` 复用、`int_to_roman` 被 `anvil_steps_tree`/`conflict_resolver` 复用、`get_item_icon_path` 被 `anvil_steps_tree` 复用。

图标映射：物品中文名 → `assets/EnchantCaculator/` 下 PNG 文件名，全部取钻石质（盔甲/工具用钻石材质）；"锹"与"铲"同图标（下拉框物品名用"铲"，与数据 applicable 一致）；含"海龟"字样的物品名特判映射 `turtle_helmet`；找不到映射或文件不存在返回空串，卡片按无图标处理。流光图标 `_GlintIcon` 的实现要点：光效纹理 `assets/Public/enchanted_glint.png`（类级缓存共享）；预缩放到 2× 图标尺寸供平铺；构造时用 `createMaskFromColor(Qt.transparent, Qt.MaskInColor)` 生成位掩码再转 `QRegion`——透明像素在掩码中为白、物品像素为黑，而 `QRegion(位图)` 取黑色像素，恰好得到物品不透明区；绘制时 `CompositionMode_Plus` 加法混合 + 0.35 透明度，光效只提亮不遮盖物品原色；50ms 定时器推进两层反向位移（各 +1/−1 像素取模循环），2×2 平铺循环绘制保证任意位移下无空隙。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `int_to_roman` | `(level: int) -> str` | 1–10 查 `ROMAN_NUMERALS` 表转罗马数字；>10 回退阿拉伯数字；≤0 回退 "I" |
| `get_item_icon_path` | `(item_name: str) -> str` | 物品名映射图标绝对路径；含"海龟"特判；无映射/文件不存在返回 `""` |
| `_GlintIcon` | `class _GlintIcon(QWidget)` | 带流光动画的物品图标控件（仅"有附魔且物品纹理可用"时使用） |
| `_GlintIcon.__init__` | `(item_name, icon_size, parent=None)` | 加载物品纹理（FastTransformation 保像素锐利）与光效纹理（类级缓存）；预缩放 2x 平铺尺寸；预计算不透明区剪辑区域；`setFixedSize(icon_size, icon_size)`；有流光才启动 50ms QTimer |
| `_GlintIcon._advance` | `() -> None` | 每帧推进两层位移（`+SCROLL_FAST`/`−SCROLL_SLOW` 对 icon_size 取模）并 `update()` 仅重绘本控件 |
| `_GlintIcon.paintEvent` | `(event)` | 画物品纹理→`setClipRegion`（不透明区）→`CompositionMode_Plus`→`opacity 0.35`→两层各 2×2 平铺绘制（起点 `offset − size`，步进 `2*size`） |
| `EnchantedItemCard` | `class EnchantedItemCard(QWidget)` | 单个已添加物品的卡片容器 |
| `EnchantedItemCard.__init__` | `(item_name, enchants, parent=None)` | 垂直布局（边距 4、间距 2）：有附魔且图标可用 → `_GlintIcon`，否则 → `QLabel` 静态图标（同样 FastTransformation 缩放）；下挂 `_TooltipBox` |
| `_TooltipBox` | `class _TooltipBox(QWidget)` | 游戏 tooltip 风格方框，`paintEvent` 自绘 |
| `_TooltipBox.__init__` | `(item_name, enchants, parent=None)` | 用应用默认字体（9pt，避免写死字体名跨环境失效）逐行生成文本（物品名 + 每条附魔"名称 罗马等级"）；按最长行宽+16px、行高×行数+10px 定死尺寸 |
| `_TooltipBox.paintEvent` | `(event)` | 关抗锯齿：深紫背景→1px 内描边→2px 紫外描边→逐行文本（首行 `TOOLTIP_HEADER` 白，其余 `TOOLTIP_TEXT` 灰） |

**接口**：被 `card_list_widget.py`（`EnchantedItemCard`）、`anvil_steps_tree.py`（`int_to_roman`/`get_item_icon_path`/4 个配色常量）、`conflict_resolver.py`（`int_to_roman`）import。卡片数据结构约定为 `{"item_name": str, "enchants": [{"id", "name", "level"}]}`（由 `ChooseItemsWindow.on_confirm_clicked` 打包），贯穿卡片列表、优化器、步骤树全链路。

**关键变量/常量**：

| 名称 | 说明 |
|---|---|
| `TOOLTIP_BG_TOP / TOOLTIP_BG_BOTTOM` | `(16,0,16,240)` 背景深紫近黑 |
| `TOOLTIP_BORDER_OUTER_START / _END` | `(80,0,255,155)` / `(40,0,127,155)` 外描边紫渐变 |
| `TOOLTIP_BORDER_INNER_START / _END` | `(40,15,66,190)` / `(20,5,33,190)` 内描边渐变 |
| `TOOLTIP_TEXT = (164,166,166)` / `TOOLTIP_HEADER = 白` | 附魔灰白文本 / 物品名白字 |
| `ROMAN_NUMERALS` | `["", "I", ..., "X"]` 等级表 |
| `_GlintIcon.FRAME_MS=50 / SCROLL_FAST=1 / SCROLL_SLOW=1` | 动画帧间隔与双层每帧位移 |
| `_GlintIcon._glint_tex` | 类级光效纹理缓存，多卡片共享一份 QPixmap |
| `EnchantedItemCard.ICON_SIZE = 48` | 图标边长（16×16 纹理放大 3 倍） |
| 物品名→图标文件映射 | 附魔书→enchanted_book、剑→diamond_sword、斧→diamond_axe、矛→diamond_spear、镐→diamond_pickaxe、锹/铲→diamond_shovel、锄→diamond_hoe、弓→bow、弩→crossbow、三叉戟→trident、重锤→mace、头盔→diamond_helmet、胸甲→diamond_chestplate、护腿→diamond_leggings、靴子→diamond_boots、钓鱼竿→fishing_rod、"海龟"→turtle_helmet |

---

## `Utils/EnchantCaculator/choose_items.py`

**功能**：物品选择对话框（`QDialog` + Designer 生成的 `Ui_enchantedItems`），用户在此完成一次物品的配置：顶部下拉框选物品类型 → 中部 Tab 分类浏览该物品可用的附魔（可拖入已选列表、左键加级/右键减级）→ 上方已选列表（可拖入、Del/×删除）→ 确认打包数据。核心职责有三：**按物品类型动态过滤附魔 Tab**、**已选附魔的冲突实时置灰**、**确认时打包 `selected_data` 数据包**（该结构贯穿后续卡片/优化/渲染全链路）。

两个可选构造参数的时序设计：`allowed_item_names`（物品类型白名单，如已添加剑卡片后只允许"附魔书、剑"）必须在**信号连接之前**倒序从下拉框移除——倒序保证当前项 index 0 不受影响、不发 `currentIndexChanged` 信号，避免触发切换清空联动；`prefill_data`（编辑卡片时的预填数据包）则在**信号连接之后**执行：先 `findText`+`setCurrentIndex` 恢复物品类型（若触发 `on_item_type_changed` 清空联动也发生在预填拖入之前，不影响结果），再逐个调用 `on_enchant_dropped` 重新拖入已选附魔。

冲突置灰机制：`refresh_disabled_state` 收集已选附魔的所有冲突附魔并集（排除已在选中集合中的 ID，双保险），对下方每个分类列表的对应项移除 `ItemIsEnabled|ItemIsSelectable` 标志（Qt 自动置灰）并设 tooltip "与已选的「来源」冲突，移除后可选"；无冲突项则补回标准标志（含 `ItemIsDragEnabled|ItemIsUserCheckable`）并清 tooltip。拖入去重与等级合并：已存在同 ID 项时取两者较高等级更新显示，否则新增条目；等级以 `min(level, max_level)` 防溢出。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `ChooseItemsWindow` | `class ChooseItemsWindow(QDialog, Ui_enchantedItems)` | 物品选择对话框 |
| `__init__` | `(parent=None, allowed_item_names=None, prefill_data=None)` | 取 DataManager 单例、`setupUi`、白名单过滤、配置 `chosenEnchantmentList` 并连接其 `dropped`/`removed` 信号、初始化状态字典、`load_enchant_data`、连接三个按钮/下拉信号、可选预填、`selected_data=None` |
| `load_enchant_data` | `() -> None` | 全附魔按 `category` 分组存入 `category_enchants`；`enchant_levels` 中未记录的 ID 补默认等级 1；以"附魔书"为初始物品类型建 Tab |
| `update_tabs_and_lists` | `(item_type: str) -> None` | 按物品类型重建 Tab：先算兼容附魔 ID 集合（`get_enchants_for_item`）；记录当前 Tab 名 → `clear()` → 逐分类建 `EnchantListWidget`（无兼容附魔的分类整个跳过），条目带 `UserRole=id / +1=等级 / +2=最大等级` → 按名恢复选中 Tab → `refresh_disabled_state` |
| `on_enchant_level_changed` | `(enchant_id, new_level)` | 列表控件加/减级信号回调，同步进 `enchant_levels` 字典 |
| `_get_selected_enchant_ids` | `() -> set` | 从 `chosenEnchantmentList` 收集已选附魔 ID |
| `refresh_disabled_state` | `() -> None` | 冲突置灰/恢复（机制见上） |
| `on_item_type_changed` | `(item_type)` | 更新 `current_stuff`；复用 `on_clear_clicked` 清空已选（旧附魔可能不兼容新物品）；`update_tabs_and_lists` |
| `on_enchant_dropped` | `(enchant_id, level)` | 拖入处理：查数据→等级钳制→已存在则取较高等级否则新增→刷新置灰 |
| `on_enchant_removed` | `(enchant_id)` | 拖出/删除回调，仅刷新置灰恢复可选 |
| `on_clear_clicked` | `() -> None` | 循环 `takeItem(0)` 清空已选列表并刷新置灰；空列表直接返回 |
| `on_confirm_clicked` | `() -> None` | 遍历已选列表打包 `selected_data = {"item_name": 下拉框文本, "enchants": [{"id","name","level"}]}`（无 ID/数据缺失的异常项跳过），`accept()` 关闭对话框 |

**接口**：被 `Tools/tool_EnchantCaculator.py` import（`ChooseItemsWindow`，添加/编辑卡片时 `exec()` 弹出，返回后读 `selected_data`）。依赖 `enchant_data_manager.DataManager`、`enchant_list_widget.EnchantListWidget`、`CodesUI.ChooseEnchantedItems.Ui_enchantedItems`。

**关键变量/常量**：

| 名称 | 说明 |
|---|---|
| `self.current_stuff` | 当前物品类型名，初始 "附魔书" |
| `self.enchant_levels` | `{附魔 ID: 当前等级}` 全局记忆（跨 Tab/物品类型保留，默认 1） |
| `self.category_enchants` | `{分类名: [附魔 dict]}` 分组缓存 |
| `self.category_widgets` | `{分类名: EnchantListWidget}` 当前 Tab 控件表，置灰刷新时遍历 |
| `self.selected_data` | 确认后的输出数据包（None=未确认），调用方读取的唯一出口 |
| 条目角色 | `Qt.UserRole`=附魔 ID、`+1`=等级、`+2`=最大等级 |

---

## `Utils/EnchantCaculator/conflict_resolver.py`

**功能**：跨卡片附魔冲突检测与决策。背景：多件物品最终合成到一件时，互斥附魔（`conflicts` 列表）不能共存于最终合成物。处理分三层：① `find_conflict_clusters` 用**并查集**把"当前所有卡片上同时存在的互斥附魔"聚成簇（如锋利×亡灵杀手×节肢杀手三者两两互斥→一个簇；同一附魔出现在多张卡片不构成冲突，合成时正常合并等级，按 id 去重、等级取最高）；② `resolve_conflicts` 应用**自动决策规则**——出现在**全部非附魔书卡片**上的附魔必然保留：非书物品在所有合并中只能做铁砧第一格（书不能吞非书），其附魔必定传入最终合成物，且互斥附魔不可能同时存在于同一物品上把它拦掉；簇内恰有一个这样的附魔 → 整簇自动决策（其余成员注定被拦截计费），零个或多个 → 进 `pending` 待用户选择；③ `ConflictResolveDialog` 弹窗为每个 pending 簇提供单选。重要约定：**弹窗只记录决策，不从卡片移除任何附魔**——未保留的附魔仍留在卡片上并正常计入合成花费（互斥不转移时每次 +1 级），只是不会出现在最终合成物中；决策由调用方作为 `required_enchants` 约束传给优化器。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `find_conflict_clusters` | `(cards_data: list, data_manager) -> list` | 三步：汇总 `present`（同 id 合并：等级取最高、物品名去重收集）；并查集 `find` 带路径压缩，遍历每个存在附魔的 `conflicts`，对同时存在的互斥对方 `union`；按根收集簇，只留 ≥2 成员的簇。簇内按 id 排序、簇间按首 id 排序保证顺序稳定。返回成员 `[{"id","name","level"(最高),"items":[物品名]}]` |
| `resolve_conflicts` | `(clusters, cards_data) -> (auto, pending)` | 收集全部非书卡片附魔 ID 的交集 `common`（无非书卡片则全部簇进 pending）；逐簇统计成员中落在 `common` 里的 ID：恰 1 个 → `auto[簇序号] = 该 ID`；0 个（用户未把该附魔放上任何非书卡）或 >1 个（同一卡片自带两个互斥附魔，正常操作无法产生）→ 交回弹窗，由优化器对任一选择给出精确报错 |
| `ConflictResolveDialog` | `class ConflictResolveDialog(QDialog)` | 冲突选择对话框，每簇一个 `QGroupBox` 组框、组内每个成员一个 `QRadioButton`（文案 = "名称 罗马等级 —— 涉及物品列表"） |
| `ConflictResolveDialog.__init__` | `(clusters, parent=None, defaults=None)` | 顶部说明文字（未选中的附魔仍计费不从卡片移除）；`defaults={簇序号: 附魔ID}` 预选上次决策，无记录选第一个；底部"确定"（默认按钮，accept）/"暂不处理"（reject，保持现状冲突保留） |
| `ConflictResolveDialog.choices` | `() -> dict` | 遍历单选按钮返回 `{簇序号: 保留的附魔 ID}` |

**接口**：被 `Tools/tool_EnchantCaculator.py` import（`find_conflict_clusters`/`resolve_conflicts`/`ConflictResolveDialog`，"开始计算"前的冲突预处理链路）。依赖 `enchanted_item_card.int_to_roman`。

**关键变量/常量**：

| 名称 | 说明 |
|---|---|
| `parent` 字典 | 并查集父指针，键为附魔 ID |
| `present` 字典 | `{附魔 ID: {"id","name","level","items"}}` 当前存在附魔的汇总视图 |
| `self._radios` | `[[ (附魔 ID, QRadioButton), ... ], ...]` 按簇序号索引的单选组 |
| 簇成员结构 | `{"id","name","level","items"}`，level 为跨卡片最高等级 |

---

## `Utils/EnchantCaculator/drop_list_widget.py`

**功能**：已选附魔列表控件（`QListWidget` 子类）与配套的 × 删除图标委托。只接收外部拖入（自身项不可拖拽，右键菜单禁用防干扰拖放），拖入数据为下方 `EnchantListWidget` 发出的 `text/plain` 格式 `"附魔ID:等级"`，解析成功发 `dropped(enchant_id, level)` 信号——实际添加列表项（查重、等级取较高等）由 `ChooseItemsWindow.on_enchant_dropped` 完成，本控件只负责接收转发。删除有两种方式且共用同一 `_remove_item`：Del/Backspace 键、点击项右侧 × 图标（委托绘制 + 控件命中判定），均发 `removed(enchant_id)` 信号。

视觉与交互细节：`CloseButtonDelegate.paint` 先走标准绘制再在项右侧叠加 ×——默认灰色 ×，悬停行升级为红色圆底（`QColor(232,17,35)`，外扩 3px、开抗锯齿）+ 白色 ×；悬停行号由控件层 `mouseMoveEvent`/`leaveEvent` 通过 `set_hover_row` 同步，行号变化才 `viewport().update()` 重绘避免频繁刷新；× 命中判定带 ±6px 宽容度防误触难点。`mousePressEvent` 命中 × 时直接删除并 return，不再触发选中切换。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `CloseButtonDelegate` | `class CloseButtonDelegate(QStyledItemDelegate)` | 列表项右侧 × 删除图标的绘制委托 |
| `CloseButtonDelegate.set_hover_row` | `(row: int) -> bool` | 更新悬停行号，返回是否有变化 |
| `CloseButtonDelegate._icon_rect` | `(option: QStyleOptionViewItem) -> QRect` | 计算图标矩形：右侧留 `MARGIN=12`，`ICON_SIZE=10`，垂直居中 |
| `CloseButtonDelegate.paint` | `(painter, option, index)` | `super().paint` 标准内容 + 叠加 ×（悬停红圆白×/默认灰×） |
| `DropListWidget` | `class DropListWidget(QListWidget)` | 可拖入的已选附魔列表 |
| `__init__` | `(parent=None)` | `setAcceptDrops(True)`、显示放置指示线、禁右键菜单；挂载委托；`setMouseTracking(True)` 支持悬停高亮 |
| `dragEnterEvent` / `dragMoveEvent` | `(event)` | 接受带文本的拖拽（CopyAction），持续接受防止鼠标显示禁止符号；无文本 ignore |
| `dropEvent` | `(event)` | 取 `mimeData().text()` 按 `":"` 拆出附魔 ID 与等级（`ValueError` ignore），发 `dropped` 信号 |
| `_remove_item` | `(item)` | `takeItem` 后读 `Qt.UserRole` 发 `removed` 信号 |
| `keyPressEvent` | `(event)` | Del/Backspace 删除当前选中项并消费按键 |
| `mousePressEvent` | `(event)` | 左键命中 `_hit_close_icon` → 直接删除不触发选中；其余交父类 |
| `mouseMoveEvent` / `leaveEvent` | `(event)` | 无按键按下时更新悬停高亮行；离开控件清高亮 |
| `_hit_close_icon` | `(item, pos) -> bool` | 用 `visualItemRect` 构造选项取图标矩形，外扩 6px 判断包含 |
| `_update_hover_row` | `(pos)` | 行号变化才重绘 |

**接口**：被 Designer 生成文件 `CodesUI/ChooseEnchantedItems.py` import（`DropListWidget`，即 `chosenEnchantmentList` 的实际类型）；`ChooseEnchantedItems.ui` 中以 `<header>Utils.EnchantCaculator.drop_list_widget</header>` 声明提升控件。`dropped`/`removed` 两个信号是它与 `ChooseItemsWindow` 的全部通信通道。

**关键变量/常量**：

| 名称 | 说明 |
|---|---|
| `dropped = Signal(str, int)` | 拖入成功：(附魔 ID, 等级) |
| `removed = Signal(str)` | 键删/×删：(附魔 ID) |
| `CloseButtonDelegate.MARGIN = 12 / ICON_SIZE = 10` | × 图标与项右边缘距离、图标边长 |
| `self._close_delegate` | 委托实例，控件层读写其 `_hover_row` |
| MIME 约定 | `text/plain` 的 `"附魔ID:等级"`（与 `EnchantListWidget` 拖出格式对应） |

---

## `Utils/EnchantCaculator/enchant_list_widget.py`

**功能**：可点击增减等级、可拖拽的附魔列表控件（`QListWidget` 子类），用在选择对话框下方各分类 Tab 中。两类交互：**点击调级**——左键点击加一级（不超 `max_level`），右键点击减一级（不低于 1），条目文本同步刷新为 `"{附魔名} (等级 {n})"`（从现有文本按 `"("` 切分还原基础名），并发射 `levelChanged(enchant_id, new_level)`；**拖拽分发**——左键按住移动超过 `QApplication.startDragDistance` 即启动 `QDrag`，MIME 文本为 `"附魔ID:等级"`，CopyAction，由上方 `DropListWidget` 接收。禁用项（与已选附魔冲突、被 `refresh_disabled_state` 摘除 `ItemIsEnabled` 标志的）不可拖拽也不可点击调级。

两个防坑设计：① `mousePressEvent` 用 `itemAt(pos)` 记录 `_pressed_item` 而非 `currentItem()`——禁用项不会被选中，`currentItem` 会停留在旧项上，直接用会导致误拖/误改旧项；② 拖拽图标与热点的 devicePixelRatio 处理：pixmap 按屏幕缩放比提升实际像素（`setDevicePixelRatio(dpr)`，显示尺寸不变、高分屏不模糊），**所有绘制必须用逻辑矩形**（设置 dpr 后 painter 自动缩放，`pixmap.rect()` 是设备像素矩形不能用），热点必须用 `logical_center` 除回 dpr——否则 dpr>1 时图标偏离鼠标。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_is_item_disabled` | `(item) -> bool` | 判断条目无 `Qt.ItemIsEnabled` 标志（即被冲突置灰） |
| `EnchantListWidget` | `class EnchantListWidget(QListWidget)` | 主控件 |
| `__init__` | `(parent=None)` | `setDragEnabled(True)`、`setAcceptDrops(False)`（只出不进）、禁右键菜单、初始化按下状态 |
| `mousePressEvent` | `(event)` | 记录 `_pressed_item`（必须 `itemAt`，原因见上）与左键 `_drag_start_pos` |
| `mouseMoveEvent` | `(event)` | 左键按住且位移达标：`_pressed_item` 为空或禁用则放弃；否则构造 QDrag——`mime.setText(f"{enchant_id}:{level}")`、拖动图标 `_create_drag_pixmap(item.text())`、热点 `logical_center`、`exec_(Qt.CopyAction)` 阻塞 |
| `mouseReleaseEvent` | `(event)` | 左键未超拖动阈值 = 点击：非禁用且 `level < max_level` 时 +1，更新 `UserRole+1` 与文本并发 `levelChanged`；右键：非禁用且 `level > 1` 时 −1，同上 |
| `_create_drag_pixmap` | `(text) -> QPixmap` | 拖拽跟随图标：淡灰圆角背景（`QColor(230,230,230,235)`）+ 浅描边 + 黑色居中文本；按 `devicePixelRatioF` 提升实际分辨率，dpr 下用逻辑矩形绘制 |
| `logical_center` | `@staticmethod (pixmap) -> QPoint` | 返回 pixmap 的逻辑中心（宽高各除以 dpr 再取半），供 `QDrag.setHotSpot` 使用 |

**接口**：被 `Utils/EnchantCaculator/choose_items.py` import（`update_tabs_and_lists` 中为每个分类 Tab 创建实例）与 `CodesUI/ChooseEnchantedItems.py` import（UI 生成文件）；`ChooseEnchantedItems.ui` 中以 `<header>` 声明提升控件。对外的唯一信号 `levelChanged(str, int)` 连接到 `ChooseItemsWindow.on_enchant_level_changed`；拖拽 MIME 文本格式与 `DropListWidget.dropEvent` 的解析约定一一对应。

**关键变量/常量**：

| 名称 | 说明 |
|---|---|
| `levelChanged = Signal(str, int)` | 等级变化信号 (enchant_id, new_level) |
| `self._pressed_item` | 按下位置的实际条目（区别于 currentItem，防误改旧项） |
| `self._drag_start_pos` | 左键按下坐标，用于拖动阈值与"点击 vs 拖动"判定 |
| 条目角色 | `Qt.UserRole`=附魔 ID、`+1`=当前等级、`+2`=最大等级（由 `choose_items.update_tabs_and_lists` 写入） |
| MIME 约定 | `text/plain` 的 `"附魔ID:等级"` |

# 5. 备份组件与主窗口部件（AutoBackUp / Settings / MainWindow）

# MCHelper 模块文档：备份/设置信号、进程监测、图标委托与可拖拽 Tab 栏

> 本文档基于源码精读整理，覆盖以下 5 个文件：
> `Utils/AutoBackUp/signals_AutoBackUp.py`、`Utils/AutoBackUp/process_monitor.py`、`Utils/AutoBackUp/right_icon_delegate.py`、`Utils/Settings/signals_Settings.py`、`Utils/MainWindow/draggable_tab_bar.py`

---

## `Utils/AutoBackUp/signals_AutoBackUp.py`

**功能**：备份功能的跨线程信号总线。备份任务的压缩工作在 `QThreadPool` 工作线程（`Threads/task_AutoBackUp.py`）中执行，而 Qt 的 UI 更新只允许在主线程进行；本文件提供一个全局唯一的 `QObject` 信号载体，工作线程只管向它发射信号，主界面（`Tools/tool_AutoBackUp.py`）连接这些信号做日志、进度条与结果通知。PySide6 的信号是线程安全的队列连接载体，`emit` 从工作线程调用时会自动跨线程投递到接收者所在线程，从而实现"工作线程 → 主线程"的安全通信。文件极小（16 行），仅含一个信号类与一个模块级单例。

**类与函数**：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `BackupSignals` | `class BackupSignals(QObject)` | 备份信号总线类，继承 `QObject`，仅声明信号、不含任何逻辑。docstring 写明用途："全局信号总线，用于所有备份任务与主线程通信"。 |
| `BackupSignals.task_started` | `Signal(int, str)` | 任务开始信号，参数为 `(任务ID, 文件名)`。 |
| `BackupSignals.task_progress` | `Signal(int, int)` | 任务进度信号，参数为 `(任务ID, 已压缩字节数)`。**注意：第二个参数是增量字节数（每次新压缩了多少），不是累计百分比**，百分比换算由接收方负责。 |
| `BackupSignals.task_finished` | `Signal(int, bool, str)` | 任务完成信号，参数为 `(任务ID, 是否成功, 消息)`。 |

**接口**：
- 对外提供模块级全局单例 `backup_bus = BackupSignals()`（文件内注释"全局单例"），整个项目共用这一个实例。
- 被 `Threads/task_AutoBackUp.py` import（`from Utils.AutoBackUp.signals_AutoBackUp import backup_bus`）：工作线程依次发射 `task_started(self.task_id, filename)`、循环中按压缩块发射 `task_progress(self.task_id, len(chunk))`、结束发射 `task_finished(self.task_id, True/False, 消息)`。
- 被 `Tools/tool_AutoBackUp.py` import（同样导入 `backup_bus`）：在初始化中把三个信号分别连接到 `self.on_back_up_started`、`self.on_back_up_progress`、`self.on_back_up_finished`，完成 UI 反馈。

**关键变量/常量**：

| 名称 | 类型 | 说明 |
| --- | --- | --- |
| `backup_bus` | `BackupSignals` | 模块级全局单例（import 时即创建），任务线程与 UI 线程共同持有的通信枢纽。 |

---

## `Utils/AutoBackUp/process_monitor.py`

**功能**：进程监测器。用 `psutil` + `QTimer` 定时轮询的方式实时监测某个目标进程（按进程名或 PID 识别）是否在运行，状态发生变化时通过 Qt 信号向主界面汇报。核心机制是**轮询**：一个默认 1000ms 间隔的 `QTimer` 周期性触发 `_check()`，`_check()` 调 `_is_process_running()` 得到"当前是否在运行"，与内部缓存 `_is_running` 比较——只有发生**状态翻转**（停→跑 / 跑→停）才发射信号，状态不变时不发任何信号，避免刷屏。启动监测时会先立即执行一次 `_check()` 再启动定时器，这样目标进程若已在运行，监测开始的一瞬间就能收到 `started` 信号，不会漏报。

进程名匹配规则（`_is_process_running`）：① 若提供了 `pid`，直接 `psutil.pid_exists(pid)` 判断，无需遍历进程表，最精确也最快；② 否则用 `process_name` 匹配——把目标名转小写，`psutil.process_iter(['name'])` 遍历全系统进程，逐个比较 `proc.info['name'].lower() == name_lower`，即**全名相等、忽略大小写**（不是子串模糊匹配）；③ 两者都没提供返回 `False`。遍历过程中对单个进程抛出的 `psutil.NoSuchProcess`（进程恰好消失）与 `psutil.AccessDenied`（无权限查看）做 `continue` 跳过，不影响整体检查。按名字匹配每次都要遍历整个进程表，文件注释也指出频繁调用时可改用 PID 方式规避开销。

在项目中的实际用法（`Tools/tool_AutoBackUp.py`）：备份工具页让用户输入目标进程名（输入为空时默认监测 `java.exe`），点"开始监测"按钮后 `ProcessMonitor(process_name=process_name)` 实例化，把 `started`/`stopped` 连到 `on_process_started`/`on_process_stopped` 槽，再调 `start_monitoring()`；再点按钮则 `stop_monitoring()` + `deleteLater()` 销毁监测器。用于实现"监测到 MC 进程启动/退出时自动备份存档"类场景。

**类与函数**：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `ProcessMonitor` | `class ProcessMonitor(QObject)` | 进程监测器类。信号：`started(str, int)`——目标进程启动时发射，附进程名与 PID；`stopped(str)`——目标进程关闭时发射，附最后一次获取的进程名；`status_changed(bool)`——状态翻转时发射（True=启动/恢复，False=关闭），供主界面统一更新状态。 |
| `__init__` | `(self, process_name=None, pid=None, parent=None)` | 保存监测条件（`pid` 优先于 `process_name`），初始化状态缓存 `_is_running = False`，创建 `QTimer(self)` 并把 `timeout` 连到 `_check`，默认检查间隔 `_interval = 1000`（毫秒）。支持只给名字、只给 PID 或两者混用的三种构造方式。 |
| `set_interval` | `(self, ms: int)` | 修改检查间隔。若定时器正在运行，先 `stop()` 再以新间隔 `start()`，保证改动立即生效；值越小响应越快但 CPU 占用越高，注释建议不要低于 100ms。 |
| `start_monitoring` | `(self)` | 开始监测。若定时器未在运行：先立即执行一次 `_check()` 获取初始状态（避免漏掉"监测开始前就已运行"的进程，若已运行会当场发射 `started`），再 `self._timer.start(self._interval)` 进入周期轮询。 |
| `stop_monitoring` | `(self)` | 停止监测：停掉定时器即不再轮询；内部缓存的状态保持不变，彻底清理需另行 `deleteLater()`。 |
| `_check` | `(self)` | 轮询核心（由定时器触发）。流程：调用 `_is_process_running()` 得到当前状态 → 与缓存 `_is_running` 比较 → 不一致则更新缓存并按方向发射信号：变为运行时先 `_get_process_info()` 取 `(name, pid)` 发 `started`（取不到信息时走防御分支发 `(self.process_name or "Unknown", 0)`），再发 `status_changed(True)`；变为关闭则发 `stopped(self.process_name or "Unknown")` 与 `status_changed(False)`。状态无变化不发射。 |
| `_is_process_running` | `(self) -> bool` | 按上文匹配规则判断目标进程是否存在：PID 优先走 `psutil.pid_exists`；否则按进程名小写全等匹配遍历 `psutil.process_iter(['name'])`，单进程异常（`NoSuchProcess`/`AccessDenied`）跳过；无条件时返回 `False`。 |
| `_get_process_info` | `(self)` | 获取当前匹配进程的 `(进程名, PID)` 元组，找不到返回 `None`。有 `pid` 时直接 `psutil.Process(self.pid).name()`（进程不存在抛 `NoSuchProcess` 返回 `None`）；有名字时按与 `_is_process_running` 相同的忽略大小写规则遍历 `process_iter(['name', 'pid'])` 查找。供 `started` 信号与 `get_current_info()` 使用。 |
| `is_running` | `(self) -> bool` | 对外查询当前运行状态：直接调 `_is_process_running()` 实时检查，不依赖缓存，即使定时器停了也能得到正确结果。 |
| `get_current_info` | `(self)` | 对外查询当前匹配进程的详细信息 `(name, pid)`，与 `is_running()` 一样实时查询；区别在于它返回详细元组（可用于显示 "java.exe (PID: 1234)" 这类文本），找不到返回 `None`。 |

**接口**：
- 被 `Tools/tool_AutoBackUp.py` import（`from Utils.AutoBackUp.process_monitor import ProcessMonitor`）。工具页持有 `self.monitor` 实例与 `self.is_monitoring` 开关，`moniter_control` 按钮槽负责启停切换；`started` → `on_process_started`、`stopped` → `on_process_stopped`。
- 对外提供：类 `ProcessMonitor`（三个信号 `started(str, int)` / `stopped(str)` / `status_changed(bool)`），以及 `start_monitoring()` / `stop_monitoring()` / `set_interval(ms)` / `is_running()` / `get_current_info()` 五个公开方法。

**关键变量/常量**：

| 名称 | 类型 | 说明 |
| --- | --- | --- |
| `self.process_name` | `str \| None` | 目标进程名（如 `"java.exe"`），匹配时忽略大小写。 |
| `self.pid` | `int \| None` | 目标进程 PID，提供时优先于进程名（`psutil.pid_exists` 精确判断）。 |
| `self._is_running` | `bool` | 上次轮询缓存的运行状态，用于在 `_check()` 中检测状态翻转。 |
| `self._timer` | `QTimer` | 轮询定时器，`timeout` 连接 `_check`。 |
| `self._interval` | `int` | 检查间隔毫秒数，默认 `1000`。 |

---

## `Utils/AutoBackUp/right_icon_delegate.py`

**功能**：把列表项图标固定绘制在**行最右侧**的自定义委托（Delegate），服务于 AutoBackUp 存档列表。背景：`QListWidget` 默认的图标（`DecorationRole`）由风格绘制在文字左侧，无法满足"图标统一靠右"的需求。本委托的策略是**分工绘制**：背景、选中高亮和文字仍交给 Qt 默认风格按完整行宽绘制（文字按剩余宽度做尾部省略 `…`，给右侧图标让位），只有自定义数据角色 `ICON_ROLE` 里携带的 `QPixmap` 由委托自己画在行的右缘。用途：扫描存档目录时，若文件夹内含 `icon` 文件（即 MC 地图存档），就把世界封面图标画在该行最右侧，一眼区分哪些文件夹是可玩的世界存档。

`paint()` 的实现流程：① 无图标（`ICON_ROLE` 数据不是有效 `QPixmap`）时直接 `super().paint()` 完全走默认绘制；② 有图标时复制一份 `QStyleOptionViewItem` 并 `initStyleOption`，把 `textElideMode` 设为 `ElideRight`，用 `QFontMetrics.elidedText` 按"可用宽度 = 行宽 − 右留白 − 图标宽 − 文字图标间距"预先省略文本，再调 `option.widget.style()`（兜底 `QApplication.style()`）的 `drawControl(CE_ItemViewItem, ...)` 画完整行；③ 图标定位：槽宽 `slot = min(icon_size, 行宽 − ICON_RIGHT_MARGIN)`（行极窄时收缩到 0 防越界），水平贴右缘留白、垂直居中；非正方形源图按 `KeepAspectRatio` 等比缩放并在槽内居中（罕见情况的兜底，注释说明 MC 存档 `icon.png` 源图 64×64、按 2:1 整数缩小到 32 保持像素风清晰），最后 `drawPixmap` 绘制。`sizeHint()` 则把行高抬到至少 `icon_size + 4`，使无图标行与有图标行等高、列表视觉整齐。

**类与函数**：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `RightIconDelegate` | `class RightIconDelegate(QStyledItemDelegate)` | 列表项委托：背景/选中高亮/文字由默认风格绘制，图标固定画在行最右侧。构造时记录 `icon_size`（默认 `DEFAULT_ICON_SIZE=32`）。 |
| `__init__` | `(self, icon_size=DEFAULT_ICON_SIZE, parent=None)` | 保存图标显示尺寸 `self.icon_size`，其余交给父类。 |
| `set_right_icon` | `@staticmethod (item, pixmap)` | 为列表项挂上要显示在行右缘的图标：`pixmap` 是非空 `QPixmap` 时写入 `ICON_ROLE`，否则写 `None` 清除图标。做成静态方法是为了不持有委托实例也能设置数据。 |
| `paint` | `(self, painter, option, index)` | 绘制入口，流程见上文"功能"（无图标走默认；有图标则预省略文字 → 默认风格画整行 → 图标画右缘垂直居中，非正方形按比例缩放居中兜底）。 |
| `sizeHint` | `(self, option, index)` | 在默认尺寸基础上保证行高 ≥ `icon_size + 4`，让所有行（含无图标行）统一预留图标高度。 |

**接口**：
- 被 `Tools/tool_AutoBackUp.py` import（`from Utils.AutoBackUp.right_icon_delegate import RightIconDelegate`）：以 `RightIconDelegate(icon_size=32, parent=self.targetDirList)` 实例化并通过 `self.targetDirList.setItemDelegate(...)` 挂到存档目录列表上；扫描到含 `icon` 的文件夹时调 `set_right_icon(list_item, pixmap)` 给对应行挂世界封面图。
- 对外提供：类 `RightIconDelegate`、静态工具 `set_right_icon(item, pixmap)`，以及自定义数据角色常量 `ICON_ROLE`（外部一般不直接用，经 `set_right_icon` 间接读写）。

**关键变量/常量**：

| 名称 | 值 | 说明 |
| --- | --- | --- |
| `ICON_ROLE` | `Qt.ItemDataRole.UserRole + 1` | 自定义数据角色，存放要在行右缘显示的 `QPixmap`。 |
| `ICON_RIGHT_MARGIN` | `6` | 图标与行右缘的留白（px）。 |
| `ICON_TEXT_GAP` | `8` | 文字（省略号）与图标之间的最小间距（px）。 |
| `DEFAULT_ICON_SIZE` | `32` | 默认图标显示尺寸；MC 存档 `icon.png` 源图 64×64，2:1 整数缩小保持像素风清晰。 |

---

## `Utils/Settings/signals_Settings.py`

**功能**：设置模块的跨对象信号总线（与备份信号总线同一设计模式，但更精简，仅 8 行）。设置页（`Tools/tool_Settings.py`）修改"开机自启"与"最小化到系统托盘"两类开关后，不直接操作主窗口，而是向全局单例 `settings_bus` 发射对应的布尔信号；主窗口 `main_window.py` 在初始化时连接这两个信号到各自的控制器槽，完成设置项到主窗口行为的解耦传递。

**类与函数**：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `SettingsSignals` | `class SettingsSignals(QObject)` | 设置信号总线类，仅声明两个信号、无任何方法逻辑。 |
| `SettingsSignals.is_start_on_boot` | `Signal(bool)` | 开机自启开关变化信号，参数为开关状态（True=开启 / False=关闭）。 |
| `SettingsSignals.is_system_tray` | `Signal(bool)` | 系统托盘开关变化信号，参数为开关状态。 |

**接口**：
- 对外提供模块级全局单例 `settings_bus = SettingsSignals()`。
- 被 `Tools/tool_Settings.py` import（发射方）：勾选状态变化时 `settings_bus.is_start_on_boot.emit(statu_bool)` / `settings_bus.is_system_tray.emit(statu_bool)`。
- 被 `main_window.py` import（接收方）：`settings_bus.is_system_tray.connect(self.system_tray_controller)`、`settings_bus.is_start_on_boot.connect(self.start_on_boot_controller)`，分别控制托盘图标创建/移除与开机自启配置。

**关键变量/常量**：

| 名称 | 类型 | 说明 |
| --- | --- | --- |
| `settings_bus` | `SettingsSignals` | 模块级全局单例（import 时创建），设置页与主窗口共用的通信枢纽。 |

---

## `Utils/MainWindow/draggable_tab_bar.py`（重点）

**功能**：支持拖拽重排标签页的 `QTabBar` 替代品，交互对齐 Chrome / VS Code 的 tab 拖拽习惯。整体行为：按住某个 tab 拖动，一枚由「标签快照 + 页面缩略快照」上下拼合的浮动卡先从标签原位"磁吸"飞向鼠标（短距离过渡 + 淡入，不瞬移）；到位后浮动卡钉住鼠标跟随、页面像被拎起来一样移动，原标签在栏内隐藏留出空槽；光标越过相邻标签中点时该标签被"挤走"，从当前位平滑滑入被拖 tab 空出的槽位（约 90ms ease-out 滑动动画）；浮动卡是独立顶层窗口，拖出 tab 栏甚至主窗口边界都完整可见不裁剪；松手时真实 tab **立即**在最终槽位就位（顺序/持久化逻辑不受动画影响），浮动卡转为残影从松手位置磁吸飞回槽位并淡出，随后发射 `orderChanged`；只按一下没有拖动则保持 Qt 默认的点击切换行为。

实现原理的几个关键设计（均为源码注释明确说明）：

1. **不用 QDrag/MimeData**：tab 重排是控件内部操作，自管理拖动状态即可，避免与工具页内部的拖放（如附魔卡片拖拽）冲突。
2. **拖拽启动判定**：`mousePressEvent` 只记录按下点局部坐标与 `tabAt` 索引；`mouseMoveEvent` 中当左键仍按住、有按下索引、且位移的 `manhattanLength() >= QApplication.startDragDistance()` 时才 `_start_drag`——阈值取系统设置，与系统拖动手感一致；未达阈值松手则完全走父类逻辑（点击切换不受影响）。
3. **坐标体系统一**：所有拖动逻辑使用控件局部坐标（`QMouseEvent.position()`），需要全局定位时才 `mapToGlobal` 换算——offscreen 平台等场景合成事件的全局坐标不可靠，局部坐标让真实交互与 QTest 模拟走同一套坐标体系，行为完全一致。
4. **浮动层用独立顶层窗口**（`_TabDragOverlay`）而不是 `paintEvent` 画在 tab 栏上：画在栏上会被控件矩形裁剪（拖出即消失），顶层窗口无此限制；窗口 flags 组合 `Qt.FramelessWindowHint | WindowStaysOnTopHint | WindowTransparentForInput | Qt.Tool`，配 `WA_TranslucentBackground` 与 `WA_ShowWithoutActivating`——不吞鼠标事件（事件继续到达下方真实窗口，拖动状态仍由 `DraggableTabBar` 的鼠标事件驱动）、不被裁剪、显示时不抢主窗口焦点。页面缩略快照用 `QWidget.grab()` 直接抓取（对隐藏页也能渲染），**不切换当前页、不触发 `currentChanged`**，对主窗口的自适应逻辑零扰动。
5. **拖拽跟随动效（Chrome 式磁吸）**：`_start_drag` 时浮动卡先以 `opacity=0` 精确落在标签原位（`_lift_start_anchor = mapToGlobal(rect.topLeft())`），随后由 14ms 的 `_lift_timer` 驱动 `_update_lift` 逐帧推进：锚点从标签原位向"鼠标位置 − 按下偏移"做 ease-out（`1-(1-p)²`）插值（时长 110ms），前 30% 进度线性淡入；动画期间栏内标签仍在绘制，视觉上是"从标签上拎起"。若提起途中就拖得很快、光标越过相邻标签中点（`_lift_would_swap`），立即 `_finish_lift` 结算进入拖动态，避免"页面还没拎稳就换位"的错位感。`_finish_lift` 把锚点切回鼠标偏移定位（`move_to(global − _drag_offset)`）——两种定位共用"标签快照左上角"这一坐标基准，切换不跳变。提起动画由 QTimer 驱动而非仅依赖鼠标事件，鼠标静止时也逐帧推进。
6. **让位（磁吸/插入指示）**：判定规则是"光标越过相邻标签中点"而不是"光标进入别的标签矩形"——后者在拖到最右侧空白区时 `tabAt` 返回 −1，末尾让位会卡住；中点判定与 Chrome/VS Code 手感一致，且光标超出标签栏边缘也能正确停到末尾。`_update_drag` 用 `while moved` 循环连续检测，一次鼠标事件可跨多格让位（快速拖动场景），每让一位把缓存索引 `_drag_index_val` 同步到新位置。
7. **挤走动画＝绘制偏移方案**：`moveTab` 本身是瞬时重排；动画靠"绘制偏移"实现——`_do_swap` 在 `moveTab` **前**按 tab 文本记录各标签的 x 坐标，重排后布局立即处于最终状态，绘制时给被挤标签一个从旧位到新位的插值偏移（`_slide_offsets` 字典按 tab 文本登记 `(位移dx, 起始时间)`，`_slide_offset_for` 按时间算 ease-out 插值，`_slide_timer` 每 14ms 重绘，90ms 播完自动清理），视觉上即平滑滑动。**动画只影响绘制，布局与逻辑（索引/顺序/持久化）从让位那一刻起就是最终状态**。动画键用 tab 文本（会话内唯一）而非索引——`moveTab` 后索引会变、文本不变；源码注释还说明不用"清空/回填标签文字来反查被拖 tab"的原因：清空文字会让 tab 突然变窄、后续标签左移，既让预计算的拖放目标坐标失效，也可能在拖动中途让位时把空文本写进顺序配置。
8. **拖动期间自绘接管整条标签栏**：`paintEvent` 在拖动/动画期间整条重绘（先 `fillRect` 用 palette 窗口色填背景——`QTabBar` 本身透明、其后是 `QTabWidget` 窗格同色背景，再 `drawPrimitive(PE_FrameTabBarBase)` 画基线，然后逐标签用原生样式 `CE_TabBarTab` 在（可能平移过的）矩形上绘制，被拖标签在提起动画完成后跳过）——避免上一帧标签像素残留成拖影；标签外观走原生样式，与平时观感一致。`_slide_offset_for` 在 paint 路径中只读不清理（清理由 `_prune_slide_offsets` 统一做），防止 paint 中触发 `update()` 重入。
9. **drop 后的重排与持久化**：顺序重排其实已在让位过程中由 `moveTab` 逐步完成，松手时布局已是最终顺序；`_end_drag` 取最终槽位矩形（`_drag_index_val`，在清理状态前取）换算全局左上角作为残影目标点，用浮动卡的快照构造 `_TabDragGhost` 从松手位置飞回槽位（130ms，ease-out 位移 + 线性淡出，自驱动播完自毁），随后立即清空所有拖动状态、结算播了一半的挤走动画，最后发射 `orderChanged`。**外部必须连接 `orderChanged` 做持久化，而不是 QTabBar 自带的 `tabMoved`**——拖动中途每次让位（`moveTab`）都会发射 `tabMoved`，中途顺序不是最终顺序；`tabMoved` 留给 Qt 内部机制用。
10. **退出安全清理**：残影与浮动卡都是顶层窗口 + 内部运行中的 `QTimer`，程序退出阶段若未停止会被析构导致原生崩溃（注释称"与剪贴板线程同款根因"，即项目已知的 PySide6 退出析构崩溃）。因此 `__init__` 中把 `QApplication.aboutToQuit` 连接到 `_cleanup_fades_on_quit`：停滑动/提起计时器、删浮动卡、遍历 `_live_fades` 逐项停止并 `deleteLater`（逐项 `try/except RuntimeError` 兜底——若某残影已自行播完销毁而集合引用尚未同步，操作已析构的 C++ 对象会抛 `RuntimeError: Internal C++ object already deleted`）；正常路径由 `_ghost_finished` 回调在残影播完时**同步**从 `_live_fades` discard `(widget, timer)`，保证集合不含死引用。
11. **与主窗口的协作方式**（源码在 `main_window.py`）：主窗口 `_setup_draggable_tab_bar()` 创建 `DraggableTabBar(self.tabWidget)` 后直接调 `self.tabWidget.setTabBar(self.tab_bar)` 替换 QTabWidget 的原生 TabBar（PySide6 中 `setTabBar` 是受保护槽可直调；原生 TabBar 被 C++ 侧接管销毁，无需手动删除），随后 `self.tab_bar.orderChanged.connect(self._save_tab_order)`。`_save_tab_order` 按各页 `widget().tool_name()` 取工具注册名（而非 `tabText`——展示文本在拖拽中途等场景可能暂时为空，而 `tool_name()` 会话内唯一稳定）写入配置文件 `tab_order.json`（`QStandardPaths.AppConfigLocation` 目录）；启动时 `_load_tab_order` / `_order_tool_classes` 按保存顺序加载工具页。控件侧另提供 `current_order()` 返回当前 tab 文本顺序，仅供调试/测试（注释建议外部持久化用主窗口的 `_save_tab_order` 更稳健）。

**类与函数**：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `_TabDragOverlay` | `class _TabDragOverlay(QWidget)` | 拖动时的顶层浮动卡：标签快照 + 页面缩略快照拼合、跟随鼠标。顶层窗口 flags（Frameless + StaysOnTop + TransparentForInput + Tool）与半透明/不激活属性使其不被裁剪、不吞事件、不抢焦点。持有 `_pixmaps`（`[(pixmap, 相对卡片左上角的位置), ...]`）、`_content_origin`（内容包围盒原点在窗口内的位置）、`_drag_offset`（按下点相对标签快照左上角的偏移）。 |
| `_TabDragOverlay.__init__` | `(self)` | 设置窗口 flags 与 `WA_TranslucentBackground`、`WA_ShowWithoutActivating`，初始化三个内容字段为空。 |
| `_TabDragOverlay.set_content` | `(self, pixmaps: list)` | 设置拼合内容并按内容总包围盒调整窗口大小：取各项位置的最小 x/y 作内容原点（`_content_origin = (-min_x, -min_y)`），最大 x/y（按 `devicePixelRatio` 折算回逻辑像素）定尺寸；空列表时缩为 1×1。 |
| `_TabDragOverlay.set_drag_offset` | `(self, offset: QPoint)` | 记录按下时鼠标在标签内的相对偏移，供 `move_to` 跟随时保持相对位置。 |
| `_TabDragOverlay.move_to` | `(self, global_pos: QPoint)` | 按"鼠标全局位置"定位浮动卡：等价于 `move_to_anchor(global_pos - self._drag_offset)`。 |
| `_TabDragOverlay.move_to_anchor` | `(self, anchor_global: QPoint)` | 按"标签快照左上角应处的全局位置"定位（窗口 `move(anchor_global - _content_origin)`）；提起磁吸动画的插值基准就是该锚点。 |
| `_TabDragOverlay.paintEvent` | `(self, event)` | 遍历 `_pixmaps`，把每张图按 `_content_origin + pos` 直接绘制。 |
| `_TabDragGhost` | `class _TabDragGhost(QWidget)` | 松手时的磁吸残影：从松手位置飞回最终槽位并同步淡出。与 Overlay 同款外观与窗口 flags；动画自驱动（内部 14ms QTimer 逐帧插值位置与透明度，播完自毁），不拦事件、不抢焦点。 |
| `_TabDragGhost.__init__` | `(self, pixmaps, start_top_left_global, target_top_left_global, duration_ms, on_finished=None)` | 布局逻辑与 `set_content` 一致（算内容原点与包围盒）；起点 = 松手位置的标签快照左上角（`start - origin`），位移 `delta = target - start`；以 `time.monotonic()` 为动画基准，创建 14ms QTimer 连接 `_tick` 并启动；`on_finished` 缺省为空操作（宿主通常在构造后另行挂接）。 |
| `_TabDragGhost._tick` | `(self)` | 动画帧：按 `(now - t0)/duration` 算进度，位置做 ease-out（`1-(1-p)²`）插值、透明度做 `1-p` 线性淡出；进度到 1 时停表、调 `_on_finished`（通知宿主把自己从 `_live_fades` 移除）并 `deleteLater()` 自毁。 |
| `_TabDragGhost._on_finished` | `(self)` | 播完回调占位（默认无操作），宿主在构造后覆盖为 `_ghost_finished` 挂接。 |
| `_TabDragGhost.paintEvent` | `(self, event)` | 与 Overlay 相同：按 `_origin + pos` 绘制各张快照。 |
| `DraggableTabBar` | `class DraggableTabBar(QTabBar)` | 可拖拽重排 tab 的 QTabBar 本体。自定义信号 `orderChanged = Signal()`：拖动结束、外观恢复后发射，外部连接它保存最终顺序（`tabMoved` 因中途让位也会发射、顺序非最终，留给 Qt 内部机制用）。 |
| `DraggableTabBar.__init__` | `(self, parent=None)` | 初始化全部拖动状态：按下点/按下索引/拖动激活位、按下偏移 `_drag_offset`、被拖 tab 缓存索引 `_drag_index_val`、挤走动画表 `_slide_offsets`（键为 tab 文本）与 `_slide_timer`、提起磁吸状态（`_lift_start_anchor`/`_lift_t0`/`_lift_timer`）、浮动卡 `_overlay`、残影集合 `_live_fades`；定义 `_ghost_finished` 回调（同步 discard，防遍历到已析构 QTimer 抛 RuntimeError）；把 `QApplication.aboutToQuit` 连接到 `_cleanup_fades_on_quit`。 |
| `mousePressEvent` | `(self, event)` | 左键按下：记录局部坐标 `_press_pos`、`_press_index = tabAt(...)`，复位 `_drag_active`；随后交父类。非左键不记录。 |
| `mouseMoveEvent` | `(self, event)` | 拖拽启动判定与拖动分发：左键按住且有按下索引、未激活、位移 `manhattanLength() >= QApplication.startDragDistance()` 时调 `_start_drag` 进入拖动；拖动中按提起动画是否完成分流到 `_update_lift` / `_update_drag`，并 `return` 不交父类（避免触发 Qt 内部点击/移动逻辑）；非拖动状态照常交父类。 |
| `mouseReleaseEvent` | `(self, event)` | 松手：若曾进入拖动则 `_end_drag()` 后直接 `return`（tab 已在让位过程中到达最终位置，不再交父类）；否则交父类，保持 Qt 默认的点击切换。 |
| `_start_lift_timer` | `(self)` | 启动/复用提起动画驱动计时器（14ms 间隔，连 `_on_lift_tick`），保证鼠标静止时动画也逐帧推进。 |
| `_stop_lift_timer` | `(self)` | 停止提起动画计时器（可重复调用，幂等）。 |
| `_on_lift_tick` | `(self)` | 提起动画帧：拖动仍在进行且提起未完成时用 `_last_local_pos` 推进 `_update_lift`；条件不满足则停表。 |
| `_finish_lift` | `(self)` | 结束提起动画：浮动卡钉到鼠标（锚点 = `mapToGlobal(_last_local_pos) - _drag_offset`）、透明度置 1.0、清 `_lift_start_anchor`/`_lift_t0`、停提起计时器并重绘。提起动画只是过渡，锚点从"标签原位"切回"鼠标偏移定位"共用同一坐标基准，切换不跳变。 |
| `_update_lift` | `(self, local_pos: QPoint)` | 提起动画帧推进：记录 `_last_local_pos`；先查 `_lift_would_swap`，成立则 `_finish_lift()` + `_update_drag(...)` 立即结算进入拖动态（避免"页面还没拎稳就换位"的错位感）；否则按 `(now - _lift_t0)/_LIFT_DURATION` 计进度，锚点从标签原位向目标 ease-out 插值，前 30% 进度线性淡入；进度满则 `_finish_lift`。 |
| `_lift_would_swap` | `(self, local_pos: QPoint) -> bool` | 提起动画中的提前让位判定：光标 x 已越过自身中心且到达右邻标签中点（向右），或对称地向左越过左邻中点，即返回 True。 |
| `_prune_slide_offsets` | `(self)` | 清理已播完（超 90ms）的挤走动画偏移项，有清理则触发重绘；paint 路径不调它（防 `update()` 重入），统一由动画帧调用。 |
| `_slide_offset_for` | `(self, index: int) -> int` | 查询某 index 标签当前的动画偏移量：按 tab 文本取 `(dx, t0)`，按流逝时间算 ease-out 进度，返回 `dx * (1 - eased)`（动画中逐渐收敛到 0）；未在动画中返回 0。只读不清理。 |
| `_start_slide_timer` | `(self)` | 启动/复用挤走动画驱动计时器（14ms，连 `_on_slide_tick`）。 |
| `_on_slide_tick` | `(self)` | 挤走动画帧：`_prune_slide_offsets` 清过期项 + `update()` 重绘当前插值状态；`_slide_offsets` 为空（全部播完）则停表。 |
| `_settle_slides` | `(self)` | 立即结算所有挤走动画（松手时用）：清空 `_slide_offsets`、停 `_slide_timer`。 |
| `paintEvent` | `(self, event)` | 非拖动且无动画时直接走父类；否则整条自绘：填 palette 窗口色背景 → 画 `PE_FrameTabBarBase` 基线 → 逐标签 `_paint_tab_at`（被拖标签在提起动画完成后跳过、由浮动卡代表；动画中的标签按 `_slide_offset_for` 平移矩形绘制）。整条重绘避免上一帧像素残留拖影。 |
| `_paint_tab_at` | `(self, painter, index: int, rect: QRect)` | 用原生样式在指定矩形绘制某标签外观：`initStyleOption` 填 `QStyleOptionTab`、把 `opt.rect` 设为传入矩形（平移矩形即平移标签）、`drawControl(CE_TabBarTab)`。 |
| `_start_drag` | `(self, local_pos: QPoint)` | 进入拖动态：置位 `_drag_active`、缓存 `_drag_index_val = _press_index`；渲染标签快照（`_render_drag_label`），算按下偏移 `_drag_offset = local_pos - rect.topLeft()`；`tab_widget.widget(_press_index).grab()` 抓页面快照（对隐藏页也能渲染，不切当前页、不触发 currentChanged）；页面快照经 `_scale_page_pixmap` 缩放后与标签快照按 `_DRAG_GAP` 上下拼成 content；创建 `_TabDragOverlay` 填内容、设偏移；提起磁吸初始化——`_lift_start_anchor` = 标签原位全局坐标、透明度 0、`move_to_anchor` 落到原位后 `show()`，启动提起计时器；重绘。 |
| `_update_drag` | `(self, local_pos: QPoint)` | 拖动跟随（提起动画完成后）：`while moved` 循环反复检测让位——向右拖越过右邻中点则 `_do_swap(idx, idx+1)` 并把缓存索引同步为 idx+1（向左对称），循环支持一次事件跨多格；随后浮动卡 `move_to(mapToGlobal(local_pos))` 跟随鼠标并重绘。 |
| `_do_swap` | `(self, from_idx: int, to_idx: int)` | 让位核心：按 tab 文本记录让位前各标签 x 坐标 → `moveTab(from_idx, to_idx)` → 对每个非被拖标签计算新旧 x 差 `dx`，非 0 者登记到 `_slide_offsets[文本] = (dx, now)`（被拖标签由浮动卡代表不参与滑动）→ 有动画则启动滑动计时器。布局即刻为最终状态，动画仅是绘制偏移。 |
| `_end_drag` | `(self)` | 松手收尾：取最终槽位矩形（`_drag_index_val`，在清理状态前取，此时布局已是最终顺序）换算全局左上角作为残影目标；用浮动卡快照构造 `_TabDragGhost` 从当前位置飞回槽位并淡出（构造后挂 `_ghost_finished` 回调——注释说明不能写进构造参数，那时 `ghost` 变量还没赋值），`show()` 后登记进 `_live_fades`，原浮动卡立即 `deleteLater()`；清提起状态、停提起计时器、`_settle_slides()`、复位按下/拖动索引，重绘并发射 `orderChanged`。 |
| `_cleanup_fades_on_quit` | `(self)` | 程序退出清理：`_settle_slides`、停提起计时器并清提起状态、删浮动卡；遍历 `_live_fades` 逐项 `try: timer.stop() / widget.deleteLater() except RuntimeError: pass`（兜底已析构对象），最后清空集合。避免退出阶段析构运行中的顶层窗口与 QTimer 导致原生崩溃。 |
| `_tab_widget` | `(self)` | 返回所属 QTabWidget（即 `self.parentWidget()`），用于抓取页面快照。 |
| `_scale_page_pixmap` | `(self, page_pix)` | 页面快照缩放与卡片包装：按 `_DRAG_PAGE_SCALE(0.18)` 等比缩放，高度上限 260 再缩、宽度下限 160 放大、高度下限 100 再放大；输出按源 `devicePixelRatio` 的高分辨率透明 QPixmap，画深底 + 紫描边圆角卡（与标签快照同款配色），页面内容按卡内缩 4px 绘制（开启 `SmoothPixmapTransform`）；输入为 `None` 或空尺寸返回 `None`（无页面快照）。 |
| `current_order` | `(self) -> list` | 返回当前 tab 文本顺序列表（调试/测试辅助）；注释建议外部持久化用主窗口的 `_save_tab_order`（按 `widget().tool_name()` 取名更稳健）。 |
| `_render_drag_label` | `(self, text: str, rect: QRect) -> QPixmap` | 渲染标签快照：按 `devicePixelRatioF` 提升分辨率建透明 QPixmap；画略缩 1px 的深底 + 紫描边圆角矩形（避免贴边裁切描边），用控件当前字体居中绘制原文字，视觉与真实标签一致。 |

**接口**：
- 被 `main_window.py` import（`from Utils.MainWindow.draggable_tab_bar import DraggableTabBar`）。
- 对外提供：类 `DraggableTabBar` 与自定义信号 `orderChanged()`（无参数）。使用方式：`tab_bar = DraggableTabBar(tabWidget)` 后 `tabWidget.setTabBar(tab_bar)` 替换原生 TabBar；连接 `orderChanged` 做顺序持久化（主窗口 `_save_tab_order` 写 `tab_order.json`，按 `widget().tool_name()` 取名；启动时由 `_load_tab_order`/`_order_tool_classes` 恢复顺序）。`_TabDragOverlay`、`_TabDragGhost` 为模块私有辅助类，不对外。

**关键变量/常量**：

| 名称 | 值 | 说明 |
| --- | --- | --- |
| `_DRAG_BG` | `QColor(30, 27, 40, 235)` | 拖动快照深底色（与工具页像素风格一致）。 |
| `_DRAG_BORDER` | `QColor(120, 88, 200, 235)` | 拖动快照紫色描边。 |
| `_DRAG_TEXT` | `QColor(235, 235, 235)` | 标签快照文字颜色。 |
| `_DRAG_RADIUS` | `4` | 快照圆角（像素风不宜大圆角）。 |
| `_DRAG_GAP` | `4` | 标签快照与页面快照之间的间距（px）。 |
| `_DRAG_PAGE_SCALE` | `0.18` | 页面快照等比缩放系数。 |
| `_DRAG_MIN_PAGE_W` / `_DRAG_MIN_PAGE_H` | `160` / `100` | 页面快照最小宽/高（过小则文字不可辨认）。 |
| `_DRAG_MAX_PAGE_H` | `260` | 页面快照最大高度（避免竖屏工具页占满全屏）。 |
| `_SLIDE_DURATION` | `90.0` | 挤走（让位）滑动动画时长（ms）。 |
| `_SLIDE_INTERVAL` | `14` | 各动画的 QTimer 帧间隔（ms）。 |
| `_LIFT_DURATION` | `110.0` | 提起磁吸：浮动卡从标签原位飞向鼠标的时长（ms）。 |
| `_DROP_DURATION` | `130.0` | 放下磁吸：残影从松手位置飞回最终槽位的时长（ms）。 |
| `self._slide_offsets` | `dict[str, tuple[float, float]]` | 挤走动画表：键为 tab 文本（`moveTab` 后索引变、文本不变），值为 `(旧位→新位像素差 dx, 动画起始时间)`。 |
| `self._lift_start_anchor` | `QPoint \| None` | 提起动画的锚点（标签原位全局坐标）；`None` 表示不在提起动画中。 |
| `self._live_fades` | `set[(QWidget, QTimer)]` | 淡出/飞回中的残影及其计时器集合，退出时统一清理。 |

# 6. 地图预览器逻辑层（Utils/MapPreviewer）

# MapPreviewer 支撑模块文档（Utils/MapPreviewer）

本文档覆盖 MapPreviewer 的配色表、渲染器、采样器与原生扩展构建脚本共 6 个文件。
所有信息来自源码精读，行号以当前源码为准。群系 id 全部与 cubiomes `biomes.h` 的
`BiomeID` 枚举同源。

---

## `Utils/MapPreviewer/biome_colors.py`

**功能**：MapPreviewer 的群系配色静态表，负责两个方向的映射：群系 id → RGB 颜色
（地图上色）、群系 id → 中文群系名（悬停信息条/图例）。id 依据 cubiomes `biomes.h`
的 `BiomeID` 枚举（与 `Utils/Public/biome_names.py` 同源）；配色参考 Amidst/cubiomes
mapview 风格并按俯视观感微调。覆盖 1.18+ 主世界表层、下界五群系（1.16+）与末地五群系
的常见群系，未收录 id 兜底灰色，保证未知 id 不致渲染失败。

中文群系名采用「双源合并」策略：主世界 1.18+ 自然生成的 54 项以
`Utils/Public/biome_names.py` 的权威对照表为唯一数据源，在模块导入时由
`_build_biome_cn_names()` 动态生成，与 SeedReverser 的显示严格一致；其余 id
（1.18+ 不再自然生成的主世界变种、下界/末地群系）用本地兜底表 `_BASE_CN_NAMES`。
权威表导入失败时静默退化为仅用兜底表，悬停功能不致报错。

两个特殊设计点：
- 末地 `small_end_islands`(id=40) 的颜色刻意取近黑 (12,12,20) 作为「虚空底色」：
  chunk 级 25×25 邻域无小岛场时游戏语义即显示该群系（F3 在虚空处显示它），且
  4 方块/像素下小岛本身近乎不可见，画深色才能呈现「主岛 + 虚空 + 外岛」结构；
- `_BASE_CN_NAMES` 注释修正了 33/160 的译名混淆：id 33 是原始松木针叶林的丘陵变种，
  id 160 才是原始云杉针叶林本体。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_build_biome_cn_names` | `() -> dict[int, str]` | 合并兜底表与权威表：以 `_BASE_CN_NAMES` 为底，尝试 `from Utils.Public.biome_names import BIOME_CHOICES, resolve_biome`，对每个下拉项 `label` 经 `resolve_biome(label)` 解析出群系 id 后写入 `names[int(bid)] = label.split(" ")[0]`（取中文前缀，去掉 id 后缀）。任何异常（模块缺失等）均被 `except Exception: pass` 吞掉，仅用兜底表。 |
| `biome_color` | `(bid: int) -> tuple[int, int, int]` | 群系 id → (r, g, b)，查 `BIOME_COLORS`，未收录返回 `FALLBACK_COLOR` 灰色。被 map_sampler / nether_end_sampler 的 `_colors_for` 逐 id 构建查找表使用。 |
| `biome_cn_name` | `(bid: int) -> str` | 群系 id → 中文群系名（SeedReverser 权威名优先），查 `BIOME_CN_NAMES`，未知 id 返回 `f"id={bid}"`。供 `Tools/tool_MapPreviewer.py` 悬停信息条使用。 |

**接口**：
- `Utils/MapPreviewer/map_sampler.py`：`from Utils.MapPreviewer.biome_colors import biome_color`
- `Utils/MapPreviewer/nether_end_sampler.py`：同上，用于下界/末地 RGB 生成
- `Tools/tool_MapPreviewer.py`（第 67 行）：`import biome_cn_name`，悬停显示群系中文名
- 对外提供：`BIOME_COLORS`、`BIOME_CN_NAMES`、`FALLBACK_COLOR`、`biome_color()`、`biome_cn_name()`

**关键变量/常量**：

| 名称 | 类型/值 | 说明 |
|---|---|---|
| `BIOME_COLORS` | `dict[int, tuple[int, int, int]]` | 主配色表，共 84 项，按注释分组：海洋/河流 12 项（ocean/river/冻洋/深海/四种温水海水与深海变种）、平原/草原/沼泽 9 项、森林 14 项、针叶林/寒带 15 项、山地/裸岩/雪峰 12 项（含 1.18+ 新群系 meadow/grove/snowy_slopes/jagged_peaks/frozen_peaks/stony_peaks/deep_dark）、沙漠/恶地 6 项、岸线/杂项 6 项（beach/cherry_grove/pale_garden/dripstone_caves/lush_caves/sulfur_caves）、下界 5 项、末地 5 项。 |
| `FALLBACK_COLOR` | `(128, 128, 128)` | 未收录 id 的兜底灰。 |
| `_BASE_CN_NAMES` | `dict[int, str]` | 31 项本地中文兜底表：1.18+ 不再自然生成的主世界变种（雪山、繁茂丘陵等）、下界/末地群系；译名风格与 MapPreviewer 群系下拉（`task_MapPreviewer.DIM_BIOME_TABLES`）一致。 |
| `BIOME_CN_NAMES` | `dict[int, str]` | 模块导入时由 `_build_biome_cn_names()` 构建的最终合并表（兜底表 ∪ 权威 54 项）。 |

---

## `Utils/MapPreviewer/block_colors.py`

**功能**：游戏地图色板系俯视渲染器（1 方块 = 1 像素，可柔化）。输入为噪声格分辨率
（1 噪声格 = 4×4 方块）的群系/气候矩阵（即 `map_sampler.sample_region` 输出的
`biomes`/`temp`/`humid`/`depth`），输出 4 倍边长的 `uint8` RGB 矩阵。色彩骨架对齐
Minecraft 原版地图物品色板（Map item format 的 base color 表），再向参考风格
（低饱和灰调大地色、柔和沉稳）整体收敏。

**两类颜色入口（LOD 双档，共用同一套基色规则）**：
- `render_block_rgb`：精细档，1 像素 = 1 方块。噪声格级算基色 → `_up4` 4× 上采样到
  方块级 → 方块级遮罩（树冠/泥土斑点/水洼/冰裂/花色/石面草 patch 等）+ 全体伪随机
  颗粒扰动。为控内存按行分块渲染（单块约 200 万方块），支持进度回调与可选 hillshade
  地形阴影。
- `render_cell_rgb`：快速档，1 像素 = 4×4 方块。仅执行噪声格级基色计算 `_cell_base`
  （草色 tint/水深渐变/恶地色带/洞穴群系自绘），省去方块级遮罩、颗粒与 4× 上采样，
  色彩基调与精细档一致；输出 (nh, nw, 3)，柔化过渡由展示端以
  `SmoothTransformation` 平滑插值放大提供，渲染层保持逐格确定性、跨瓦片无缝。

**结构色（树冠/植被）的组织方式**：树冠色由三个 256 长 LUT 协同——
`_CANOPY_DENS`（树冠斑点密度，逐群系取值 0~0.62，樱花树林 0.55 最密）、
`_CANOPY_MULT`（相对色模式：树冠色 = 草 tint × `_CANOPY_MULT` × `_GRASS_MULT`，
如黑森林 (0.45,0.58,0.42) 压暗）、`_CANOPY_ABS` + `_CANOPY_ABS_M`（绝对色模式，
仅樱花树林 185 与苍白之园 186 使用固定色）。树冠斑点还需低频 patch 场 > 0.30 成簇，
并叠加伪高度立体感：簇高 `(patch-0.30)/0.50` 提亮 0.88~1.08、颗粒抖动 0.92~1.06，
再对簇的北缘（上邻非树冠）提亮 ×1.12、南缘压暗 ×0.86，形成疙状起伏而非平涂色点。
雪坡林地 grove(178) 的云杉冠斑用固定色 `_SNOW_TAIGA_CROWN`，同样带北亮南暗。

**水体色的组织方式**：三档低饱和柔和灰蓝锚点 `_WATER_SHALLOW`/`_WATER_BASE`/
`_WATER_DEEP`（非原版亮蓝，避免与暖色地貌对比过冲），由 `_norm_fields` 从 depth
矩阵整图一次算出归一化场 `water_u = clip(-depth/2400, 0, 1)`（depth 为负且越深越负，
近岸 0 亮 → 深海 1 暗，`_WATER_SPAN=2400` 固定物理映射、与视野内容无关）；深海群系
（24/47/48/49）再 +0.25 加深；河流(7)/暖水海洋(44) 因「河床深但水深浅」不走同一映射，
固定取 `0.12 + 0.18*water_u` 浅亮段；冻洋/冻河/深冻洋（10/11/50）画冰面 `_ICE_RGB`。
方块级另有低频 patch 水波明暗（幅度 ±0.035）与冰面裂纹（`_ICE_RGB*0.86`）。

其余规则：草色 = 温度×湿度双梯度四角锚点（`_grass_tint` 双线性）× 群系系数
`_GRASS_MULT`；热带草原类（35/36/163/164）固定原版草色 #BFB755 不随气候插值；
恶地按 depth 分档取 8 档陶瓦色带 `_TERRACOTTA`（原版地图 TERRACOTTA 系去饱和 12%，
谷底深棕→高原顶浅橙），方块级再加 ±0.3 档抖动与繁茂恶地顶部草 patch；山地石面按
`_GRASS_PATCH`/`_GRAVEL_PATCH` 概率混入草色/砾石；洞穴群系（174 溶洞/175 滴水石/
183 深暗之域/187 硫磺洞穴）自绘旧版观感，深暗之域有 `_SCULK_SPECK` 幽匿微光点；
全体方块级乘以 `(1+(n0-0.5)*0.045)` 颗粒扰动。可选 hillshade：`_hillshade_shade`
以 depth 为高程场按 GDAL/ArcGIS 标准 horn 公式（西北光源 315°、高度角 40°、
`_HS_ZSCALE=0.001`）计算 [0,1] 阴影场，四边线性外推 pad 消除瓦片接缝、3×3 均值平滑，
乘法混合 `(0.40+0.60*shade)` 压暗背光坡，水面（非冰）跳过（shade=1）。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_one_hot` | `(ids) -> np.ndarray` | 把群系 id 序列转为 256 长布尔查找表（越界 id 忽略），供向量化判断「该群系属于某组」。 |
| `_build_luts` | `() -> tuple` | 模块导入时构建 9 个 256 长 LUT 并返回：分类 `cat`、草色系数 `mult`、树冠密度 `dens`、树冠相对色 `cmult`、树冠绝对色 `cabs`、绝对色掩码 `abs_mask`、泥土斑点密度 `dirt`、石面草 patch 概率 `grass_patch`、砾石 patch 概率 `gravel_patch`。 |
| `_hash01` | `(bx, bz, seed, salt) -> np.ndarray` | 伪随机哈希：(方块/噪声格 x, z, 种子, salt) → [0,1)。u64 溢出回绕的 splitmix 风格混合（乘 0x9E37…/0xC2B2… 黄金比率、两次 `q ^= q>>33`），取低 24 位归一化。同参数结果可复现，是颗粒/斑点/花色的唯一随机源。 |
| `_up4` | `(a) -> np.ndarray` | 前两维逐 4 重复上采样：(nh, nw[, …]) → (nh*4, nw*4[, …])，把噪声格级颜色/掩码展开到方块级。 |
| `_expand_patch` | `(rc, bh, bw) -> np.ndarray` | 噪声格随机场 (nh+2, nw+2)（外圈 1 格 pad，索引 = 全局噪声格 − 块原点格 + 1）→ 方块级 (bh, bw) 双线性平滑场。方块 b 落在噪声格 b//4 内、格间位置 (b%4)/4 按整数格边界插值，产生 4~8 方块尺度的平滑斑块，供山地草/石混合、沙丘明暗、水面波纹使用；纯整数格映射，跨块无缝。 |
| `_norm_fixed` | `(dq, base, span, invert=False) -> np.ndarray` | depth 量化值 → [0,1] 固定物理映射（确定性、不依赖整图内容）：`u = clip((dq-base)/span)`，invert=True 时取 1−u。 |
| `_grass_tint` | `(tq, hq) -> np.ndarray` | 温度/湿度量化值（×10000）→ 草色 tint (…,3)：先映射到 [0,1]，再按行（温度冷→热）/列（湿度干→湿）对四角锚点 `_GRASS_TL/TR/BL/BR` 双线性插值。 |
| `_cell_base` | `(biomes, temp, humid, water_u, bad_u) -> tuple[np.ndarray, dict]` | 噪声格级基色层：(nh,nw) 分类/气候 → (nh,nw,3) float32 基色 + 状态字典（bid/cat/草 tint/各分类掩码/bad_idx 等）。精细档与快速档共用：草 tint × 群系系数 → 水深渐变/冰面 → 雪/沙/石固定色 → 恶地陶瓦色带 → 沼泽/蘑菇岛 → 热带草原固定色 → 洞穴群系自绘 → 未覆盖 id 兜底 `_FALLBACK_CELL`。 |
| `_render_chunk` | `(biomes, temp, humid, water_u, bad_u, seed, obx, obz) -> np.ndarray` | 渲染一个噪声格行块 → (nh*4, nw*4, 3) uint8。流程：`_cell_base` 基色 → 用全局方块坐标（obx/obz 已是方块坐标）生成 n0/n1/n2 三路哈希与低频 patch 场 → `_up4` 上采样 → 依次叠加：水波/沙丘明暗、泥土斑点、树冠斑点（含立体感与北亮南暗）、花色点缀、冰裂、石面草/砾石、雪面裸岩与蓝冰、恶地抖动与繁茂恶地顶部、沼泽水洼、雪坡云杉冠、溶洞苔藓/幽匿微光、菌丝斑点、全体颗粒扰动。 |
| `_norm_fields` | `(biomes, depth) -> tuple[np.ndarray \| None, np.ndarray \| None]` | 整图一次由 depth 计算水色/恶地归一化场：水面 `water_u = _norm_fixed(-dq, 0, 2400)`，恶地 `bad_u = _norm_fixed(dq, -500, 7000, invert=True)`（u→1 高原顶浅橙 / u→0 谷底深棕）；仅当对应群系存在时才计算，depth 为 None 时返回 (None, None)。分块渲染时各块只切片复用。 |
| `_liquid_mask` | `(biomes) -> np.ndarray` | 液态水掩码（`_WATER_IDS` 且非 `_FROZEN_WATER_IDS`），与 `_cell_base` 的 liquid 定义一致，供 hillshade 跳过水面。 |
| `_hillshade_shade` | `(depth, liquid) -> np.ndarray` | depth 高程场 → [0,1] 山体阴影场（噪声格分辨率）。horn 3×3 加权和求 dzdx/dzdy → slope/aspect → `cos(zen)·cos(slope)+sin(zen)·sin(slope)·cos(az−aspect)`，除以 `cos(zen)` 归一化（平坦=1）。pad 采用线性外推（局部坡面近似线性时与真实边界梯度一致，消除接缝；edge 复制会引入 Δ/2 误差），角点双向外推；3×3 均值平滑后水面置 1。 |
| `render_block_rgb` | `(biomes, temp, humid, depth, seed=0, origin_bx=0, origin_bz=0, on_progress=None, hillshade=False) -> np.ndarray` | 方块级渲染主入口（LOD 精细档）。temp/humid/depth 可为 None（退化为按群系 id 的简化配色）；seed/origin 进入哈希保证跨次渲染可复现；按行分块（chunk ≈ 2M 方块）调 `_render_chunk`，可选乘 hillshade 阴影场（`0.40+0.60*shade`），经 `on_progress(done_rows, total_rows)` 汇报进度。返回 (nh*4, nw*4, 3) uint8。 |
| `render_cell_rgb` | `(biomes, temp, humid, depth, hillshade=False) -> np.ndarray` | cell 级快速渲染（LOD 快速档，1 像素 = 4×4 方块）。与精细档共用 `_cell_base` 基色规则，仅省去方块级遮罩与 4× 上采样；hillshade 语义与精细档相同。返回 (nh, nw, 3) uint8，展示端再放大到方块尺度。 |

**接口**：
- `Threads/task_MapPreviewer.py`（第 43 行）：`from Utils.MapPreviewer.block_colors import (render_block_rgb, …)`——地形采样完成后调用本模块把群系/气候矩阵渲染成地图像素
- 对外提供：`render_block_rgb`、`render_cell_rgb` 两个入口；内部 LUT 与工具函数均以 `_` 前缀私有

**关键变量/常量**：

| 名称 | 类型/值 | 说明 |
|---|---|---|
| `CELL` | `4` | 每噪声格边长对应的方块/像素数。 |
| `_CAT_*`（8 个） | `0~7` | 群系分类：WATER/GRASS/SNOW/SAND/STONE/BADLAND/SWAMP/MUSHROOM，按 bid 0..255 建 `_CAT` LUT。 |
| `_TERRACOTTA` | `(8,3) float32` | 恶地陶瓦色带（高原顶→谷底 8 档），原版地图 TERRACOTTA 系去饱和 12%。 |
| `_GRASS_TL/TR/BL/BR` | 各 (3,) float32 | 草色双梯度四角锚点：行=温度（冷→热）、列=湿度（干→湿）；整体降饱和 +G 提权重。 |
| `_DIRT/_SNOW/_ICE/_SAND/_STONE/_GRAVEL/_MYCELIUM_RGB` 等 | (3,) float32 | 各类固定基色（地图 DIRT/SNOW/ICE/SAND/STONE/PURPLE base 柔化）；另有 `_SWAMP_GRASS`、`_SWAMP_WATER`、`_MANGROVE_GRASS`、`_BLUE_ICE_RGB`、`_WOODED_BAD_TOP`、`_MYCELIUM_SPECK`、`_CHERRY_CANOPY`、`_PALE_CANOPY`、`_SNOW_TAIGA_CROWN`。 |
| `_CAVE_*`、`_SCULK_SPECK` | (3,) float32 | 洞穴群系色：溶洞 (136,118,82)、苔藓 (100,138,70)、滴水石 (150,132,106)、深暗之域 (42,46,58)、硫磺洞穴 (168,138,60，与 biome_colors 同源)、幽匿微光 (96,150,170)。 |
| `_WATER_SHALLOW/BASE/DEEP` | (3,) float32 | 水色三档锚点：低饱和柔和灰蓝 (96,128,200)/(76,100,180)/(52,70,138)。 |
| `_FLOWER_COLORS` | (4,3) float32 | 花色点缀（繁花森林/草甸）：黄/红/白/粉紫。 |
| `_FALLBACK_CELL` | (3,) float32 | 未收录群系 id 兜底（平原草色 145,189,89）。 |
| `_WATER_IDS` 等 11 个分组 | int 元组 | 按 id 归组：液态水 (0,7,24,44,45,46,47,48,49)、冰面 (10,11,50)、深海 (24,47,48,49)、雪 (12,13,26,140,178,179,180,181)、沙 (2,130,16)、石 (3,20,25,131,182)、恶地 (37,38,39,165)、沼泽 (6,134,184)、蘑菇 (14,15)、云杉类针叶林、雪地针叶林。 |
| `_CAT`/`_GRASS_MULT`/`_CANOPY_DENS`/`_CANOPY_MULT`/`_CANOPY_ABS`/`_CANOPY_ABS_M`/`_DIRT_DENS`/`_GRASS_PATCH`/`_GRAVEL_PATCH` | 256 长或 (256,3) LUT | `_build_luts()` 的产物（模块级解包），全部按 bid 索引。 |
| `_WATER_SPAN`/`_BAD_BASE`/`_BAD_SPAN` | `2400.0 / -500.0 / 7000.0` | depth 参数（`np6[4]*10000`）的固定物理映射界限：水色 −depth 0→2400 亮→暗；恶地 −500→−7500 取反得谷底→高原顶条带。 |
| `_HS_AZ`/`_HS_ZEN`/`_HS_ZSCALE` | `rad(315°) / rad(50°) / 0.001` | hillshade 参数：光源罗盘方位 315°（西北）、天顶角（高度角 40°）、depth→高程缩放（典型梯度：平原 ~50/格、丘陵 ~400、山地 1000+）。 |

---

## `Utils/MapPreviewer/choose_structure.py`

**功能**：MapPreviewer 的「选择结构」图标网格对话框。UI 由用户在 Qt Designer 定义的
`ChooseStructureWin.ui`（编译为 `CodesUI/ChooseStructureWin.py` 的
`Ui_chooseStructureWin`：结构列表 `structureList` + 确认按钮 `confirmBtn`）提供，
本模块只做控制逻辑：

- `QListWidget` IconMode 网格视图展示当前版本可标注的结构，图标用 Wiki EnvSprite
  资产（`Utils/Public/structure_icons`，16×16 精灵以 `FastTransformation` 就近放大到
  36px 保持像素风），中文名（`STRUCT_NAMES`）显示在图标下方（IconMode 自带文字换行）；
- `MultiSelection` 模式：点击条目即在「选中/取消」间切换（高亮 = 在地图上标注该结构）。
  刻意不用 `ItemIsUserCheckable` 勾选框——点击勾选框会原生切换一次、`itemClicked`
  再切换一次，双重抵消产生歧义；
- 条目按维度分组（主世界/下界/末地），分组标题是禁用的 `QListWidgetItem`（无
  Selectable 标志，不可选不可点），主世界组不显示标题；组内保持 `avail_keys` 传入顺序
  （按图上易找程度排序）；
- 图标文件缺失或 QPixmap 为空时仍可正常选择（只少图标不挡功能）。

调用方 `Tools/tool_MapPreviewer.py` 以 `exec()` 弹出，确认（`confirmBtn` → `accept()`）
后经 `get_selected()` 取回选中集并写回自己的选择状态。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `ChooseStructureWindow` | `class ChooseStructureWindow(QDialog, Ui_chooseStructureWin)` | 结构选择对话框。构造时 `setupUi` 加载 Designer UI、设窗口标题，把 `structureList` 配置为 IconMode/Adjust/Static/MultiSelection、统一条目尺寸、间距 10、图标 36px 并应用 `_SELECT_QSS`；随后调 `_add_dimension_groups` 填充条目并按 `selected` 预选；`confirmBtn.clicked` 连接 `self.accept`。 |
| `ChooseStructureWindow.__init__` | `(parent=None, avail_keys=(), selected=None)` | `avail_keys` 为当前版本可标注的结构键序列（调用方已按版本过滤）；`selected` 为初始选中集合（None = 全不选）。 |
| `ChooseStructureWindow.get_selected` | `() -> set` | 确认后取回选中结构键集合：遍历 `structureList.selectedItems()`，取各条目 `Qt.ItemDataRole.UserRole` 数据（即结构键）。 |
| `_add_dimension_groups` | `(lst: QListWidget, avail_keys, selected: set) -> None` | 按维度分组填充：先以 `STRUCT_DIMENSION.get(key, "overworld")` 把 `avail_keys` 归入 overworld/nether/end 三组，再按固定顺序遍历，下界/末地组先插 `_add_group_header` 标题行；每个结构建 `QListWidgetItem(STRUCT_NAMES.get(key, key))`，UserRole 存结构键，flags 为 Enabled+Selectable，设 tooltip「点击选中/取消：选中后该结构将标注在地图上」，尝试加载图标（`st_icons.icon_path` → QPixmap 非空才 `scaled(36,36, IgnoreAspectRatio, FastTransformation)`），`key in selected` 则 `setSelected(True)`。 |
| `_add_group_header` | `(lst: QListWidget, title: str, count: int) -> None` | 插入禁用的分组标题行（如「下界 · 2 种」）：flags 仅 `ItemIsEnabled`（无 Selectable = 禁用），前景色 #5f6673、加粗、行高 26、水平垂直居中。 |

**接口**：
- `Tools/tool_MapPreviewer.py`（第 68 行）：`from Utils.MapPreviewer.choose_structure import ChooseStructureWindow`
- 依赖：`CodesUI.ChooseStructureWin.Ui_chooseStructureWin`（Designer UI）、
  `Utils.Public.structure_icons`（图标路径）、
  `Utils.Public.structure_params`（`DIMENSION_NAMES`/`STRUCT_DIMENSION`/`STRUCT_NAMES`）
- 对外提供：`ChooseStructureWindow` 类（其余两个函数为模块私有辅助）

**关键变量/常量**：

| 名称 | 类型/值 | 说明 |
|---|---|---|
| `_ICON_SIZE` | `36` | 网格图标显示尺寸（屏幕 px），16×16 精灵就近放大，像素风与地图标记一致。 |
| `_SELECT_QSS` | str（QSS 样式表） | 选中态样式：列表白底；选中项浅蓝底 #cfe4f7 + 深字 #1a1a1a + 蓝边框 #4a90d9；hover 非选中浅灰 #eef2f6。浅底下 hover/分组标题均保持可读。 |

---

## `Utils/MapPreviewer/map_sampler.py`

**功能**：MapPreviewer 的主世界俯视图采样器。把 `Utils/SeedReverser/biome_noise.py`
的 `BiomeSampler`（1.18+ 主世界群系逐点采样，与 cubiomes `biomenoise.c` 位级对拍）
扩展成矩形区域批量采样，产出 numpy `uint8` RGB 矩阵供 UI 层转 QImage 显示。

**引擎**：native 优先——优先调用 `Utils/MapPreviewer/_native/_map_sampler.pyd`
（C++ 多线程，管线与 `_biome_refine.cpp` 同源，已与纯 Python 路径逐点对拍）；
扩展缺失、导入失败或调用异常时自动降级纯 Python 逐点路径（结果位级一致，仅速度差异），
降级时向 stderr 打印一行诊断避免静默变慢无从排查。

**采样计算流程**：
1. **坐标约定**：方块坐标 (bx, bz) → 噪声格坐标 = 方块 `>> 2`（1:4），每个像素 =
   1 噪声格 = 4×4 方块。宽高先对齐 4 的倍数（下限 16），`nw = w>>2`、`nh = h>>2`；
   区域中心 (cx_blocks, cz_blocks) 换算左上角噪声格
   `origin_nx = (cx − w//2) >> 2`（中心对齐）。
2. **采样层**：固定 `DEFAULT_NY = 16`（噪声格 y），对应方块层 y≈64~79，即海平面
   地表层、与 F3 群系判定一致层（经用户真实数据校准）。cubiomes `getBiome` 的
   等价计算由 `BiomeSampler.climate_point_xz(x, z, ny)`（6 元组气候参数）+
   `climate_to_biome(np6, btree)`（btree 群系判定）完成；native 路径则由 pyd 内的
   C++ 实现执行同一条管线。
3. **native 路径**：按 `version_key` 经 `VERSION_TO_BTREE` 取 btree 名，
   `_ensure_native_btree` 将该版本 btree 数据（`steps` uint32 / `param` int64 /
   `nodes` uint64 / `order`）每版本仅首次推入 pyd（`set_btree`），随后调用
   `_native_ext.sample_map(seed, btree_name, origin_nx, origin_nz, nw, nh, ny, …)`，
   传入进度回调、取消函数与 `want_depth`/`want_temp_humid`/`surface_mode` 开关。
4. **纯 Python 路径（兜底）**：逐行逐点双重循环——`np6 = sampler.climate_point_xz(origin_nx+col, nz, ny)`
   → `biomes[row, col] = climate_to_biome(np6, btree)`（与 cubiomes 位级一致的逐点
   语义，不做数值向量化）；RGB 生成则用 numpy 向量化查表。每行结束回调
   `on_progress(done_rows, total, "python")`，每行前检查 `cancel()`，取消时尽快返回
   部分结果。
5. **surface_mode 表面层重判（默认 True，最高方块渲染）**：固定层 ny=16 会切入高山
   山体（`np6[4]` 即 depth 参数 > 0 表示采样层在真实地表之下），btree 最近邻会判到
   地下群系（174 滴水石/175 繁茂洞/183 深暗之域），俯视图上表现为「地表随处可见
   溶洞」。此时把第 5 个参数置 0（地表线 d=0）重新判定群系；`d <= 0`（水面/低地）
   不动 → 水色零回归。depth 矩阵仍记录原始 d，保证 hillshade/水深渐变不变。native
   路径同一语义由 C++ 侧实现。
6. **RGB 生成**：`_colors_for(biomes)` 将 int32 群系矩阵转为 uint8 RGB——逐通道构建
   256 项 LUT（`biome_color(bid)[ch]`，超范围 id 经 `np.clip` 走兜底灰），再以
   `lut[np.clip(biomes, 0, 255)]` 一次向量化取色。
7. **返回契约**：dict 载荷（线程与 UI 解耦）：`rgb`/`biomes`/`origin_bx`/`origin_bz`
   （= 噪声格原点 `<< 2` 回方块坐标）/`ny`/`surface_mode`/`engine`
   （"native" | "python"）/`elapsed`/`cancelled`/`rows_done`；可选 `depth`
   （气候第 5 参数量化值 depth×10000，值域约 [−12850, 6160]，海平面 ≈ −1585）、
   `temp`/`humid`（气候第 1/2 参数量化值）。depth/temp/humid 不额外增加采样成本。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_ensure_native_btree` | `(btree_name: str) -> None` | 把指定版本 btree 数据推入 native 扩展（每版本仅首次，用 `_NATIVE_BTREES` 集合去重）。从 `_load_btree` 读取后以 `np.ascontiguousarray` 规范 dtype/内存布局再 `set_btree`。 |
| `sample_region` | `(seed, version_key, cx_blocks, cz_blocks, width_blocks, height_blocks, ny=DEFAULT_NY, on_progress=None, cancel=None, want_depth=False, want_temp_humid=False, surface_mode=True) -> dict` | 主入口：采样以 (cx,cz) 为中心的矩形区域并返回 dict 载荷。seed 为有符号 int64（内部按无符号 64 位处理）；version_key 如 "26.2"/"1.21.11"/"1.21"。先做宽高对齐与原点换算，native 可用则走 `_native_ext.sample_map`（异常时打印诊断并落到纯 Python），否则逐行逐点 `climate_point_xz` + `climate_to_biome`（含 surface_mode 重判），最后统一 `_colors_for` 上色并组包（含 engine/elapsed/cancelled/rows_done 与可选 depth/temp/humid）。 |
| `_colors_for` | `(biomes: np.ndarray) -> np.ndarray` | int32 群系矩阵 → uint8 RGB 矩阵：逐通道建 256 项颜色 LUT 后 `lut[np.clip(biomes,0,255)]` 向量化查表；超范围 id 按兜底色处理。nether_end_sampler 里有同实现副本。 |

**接口**：
- `Threads/task_MapPreviewer.py`（第 40 行）：`from Utils.MapPreviewer.map_sampler import sample_region`
- `Tools/tool_MapPreviewer.py`（第 1971 行，函数内局部导入）：单点/区域探测
- 运行期依赖：`Utils/SeedReverser/biome_noise.py`（`BiomeSampler`/`climate_to_biome`/
  `VERSION_TO_BTREE`/`_load_btree`）、`Utils/MapPreviewer/biome_colors.biome_color`、
  可选 native 扩展 `Utils.MapPreviewer._native._map_sampler`（由 `build_map.py` 编译）
- 对外提供：`sample_region`（其余以 `_` 前缀私有）

**关键变量/常量**：

| 名称 | 类型/值 | 说明 |
|---|---|---|
| `_native_ext` | module \| None | 尝试导入 `_map_sampler` pyd；ImportError 及扩展自身导入期异常一律置 None 降级。 |
| `_NATIVE_BTREES` | `set[str]` | native 端已推入的 btree 版本名集合，避免每次调用重复推数据。 |
| `DEFAULT_NY` | `16` | 默认采样层（噪声格 y），≈ 方块层 64~79 的海平面地表层。 |

---

## `Utils/MapPreviewer/nether_end_sampler.py`

**功能**：下界/末地群系采样器（legacy Random 线）。与 `biome_noise.py` 的 Xoroshiro
线（1.18+ 主世界）不同，下界群系（1.16+）与末地群系（1.9+，本模块按 1.13+ 语义，
项目版本线 1.18~1.21）的噪声完全由 legacy Java `Random` 流驱动；本模块按 cubiomes
`biomenoise.c` / `noise.c` 逐行移植并用 numpy 向量化。除地图渲染外，还是下界/末地
结构校验的群系采样后端（`Utils/Public/structure_map.py` 复用单点采样）。

**下界采样计算流程**（biomenoise.c L164-212）：
- 播种 `setNetherSeed`：`setSeed(seed)` → `doublePerlinInit(temperature, omin=-7, len=2)`；
  `setSeed(seed + 1)` → `doublePerlinInit(humidity)`——两条独立流（`NetherSampler.__init__`）。
- `getNetherBiome`：y 强制 0（下界无垂直变化），temp/humid 各一次
  `sampleDoublePerlin`，坐标 = 噪声格 1:4，scale=4 无 Voronoi。
- 5 点最近邻（float 域，`_nether_nearest`）：nether_wastes(0,0)、soul_sand_valley(0,−0.5)、
  crimson_forest(0.4,0)、warped_forest(0,0.5，常数项 0.375²)、basalt_deltas(−0.5,0，
  常数项 0.175²)；C 中 temp/humidity 存为 float，距离在 float32 域计算，严格小于
  （`dsq < dmin`）→ 平局取先出现者，等价于 `np.argmin` 最小索引。
- `genNetherScaled` scale=4 直接逐格采样；cubiomes `mapNether3D` 的 `fillRad3D`
  是纯加速优化（noisedelta 保证半径内群系不变），逐点采样结果等价，故本模块直接
  整矩阵向量化采样。

**末地采样计算流程**（biomenoise.c L370-515）：
- 播种 `setEndSeed`：`setSeed(seed)` → `skipNextN(17292)` → `perlinInit`（单 Perlin，
  用于 simplex 2D 小岛高度场）。
- `mapEndBiome`（单位 = 16 方块 chunk，1.13+）：先建 hmap 尺寸 (w+26)×(h+26)
  （外圈 12 格 pad），元素 rx=x+i−12、rz=z+j−12；`rsq > 4096` 且
  `sampleSimplex2D(perlin, rx, rz) < −0.9` 的格子填小岛高度
  `v = ((|rx|·3439 + |rz|·147) % 13 + 9)²`——float32 乘法 + `(unsigned int)` 截断，
  uint16 域平方（≤441 无溢出）；其余 0。
- 主循环：`rsq ≤ 4096` → `the_end`（中心岛）；否则 hx/hz = 2h+1，1.13+ 若
  `(int32)(hx²+hz²) < 0`（即 `rsq & 0xFFFFFFFF ≥ 2³¹`）→ `end_barrens`；
  其余走 `getEndBiome`：h 初值 `|hx|,|hz| ≤ 15` → `64·(hx²+hz²)`，否则 14401；
  25×25 窗内 elev 非 0 时 `h = min(h, (ds[(hx<0)+i] + ds[(hz<0)+j])·elev)`
  （`_END_DS[26] = (25−2i)²`）；h<3600 → end_highlands；≤10000 → end_midlands；
  ≤14400 → end_barrens；else small_end_islands。批量向量化 `_end_get_biome_batch`
  按 64 个点分块 gather 25×25 窗，控制峰值内存。
- **坐标系映射与 scale 展开**：输入像素为 4 方块噪声格（与主世界 1 像素 = 4 方块
  观感一致）；`EndSampler.map_region` 把原点对齐到 chunk 边界（`& 3` 取 pad、`>> 2`
  得 chunk 坐标）先算 chunk 网格群系，再 `np.repeat` 4× 最近邻展开到像素级并裁剪
  （对应 cubiomes `mapEnd` 的 `(x+i)>>2` 展开）。区域入口 `_align_dims` 与
  map_sampler 相同约定：宽高对齐 4、中心换算左上角噪声格，返回 dict 中
  `origin_bx = origin_nx << 2` 回方块坐标；`ny` 恒 0、`surface_mode=False`、
  `engine="python"`。
- **RGB 生成规则**：`_colors_for` 与 map_sampler 完全同一查表实现（逐通道 256 项
  LUT + clip），下界/末地颜色来自 `biome_colors.BIOME_COLORS` 的对应条目
  （id 8/170~173 与 9/40~43）。

**位级细节（与 C 严格对应，均为可复现关键）**：
- `perlinInit`（noise.c L49-77）：a/b/c = `nextDouble·256`；256 次洗牌
  `j = nextInt(256−i) + i`（rng.h 完整版 nextInt，含拒绝采样，i=0 时 n=256 为
  2 幂走 pow2 分支）；`idx[256]=idx[0]`；预计算 `h2=(int)floor(b)`、
  `d2=b−floor(b)`、`t2=fade(d2)`。
- `octaveInit`（omin=−7, len=2）：end=−6 < 0 → `skipNextN(1572)`；persist=1/3、
  lacuna=2⁻⁶ 起，逐 octave persist×2、lacuna×0.5。
- `doublePerlinInit`：amplitude=(10/6)·len/(len+1)=10/9；octA、octB 在同一条流上
  顺序初始化。
- `samplePerlin` y=0 快速路径：d2==0 时用预计算常数；h1/h3 为 uint8 截断（C 中
  `(int)floor` 存入 uint8_t 即 mod 256），idx 索引链加法全部 `& 0xff` 回绕；
  `indexedLerp` 16 case 编码为 (16,3) 符号表 `_LERP_SIG` 点积；`lerp(t,a,b)=a+t·(b−a)`；
  `maintainPrecision` 为恒等函数。
- `sampleDoublePerlin`：f = 337/331，两套 octave 分别按 x 与 x·f 采样后求和 ×amplitude。
- 末地 hmap 的 float 单精度（float32 计算再截断）、`(int)rsq < 0` 的 32 位截断、
  窗起点 `(hz/2 − z)` 的 `/2` 为 C 向零截断除法（负 chunk 坐标时窗起点偏 +1，
  奇偶不对称，`_c_div2` 精确复刻）。

**结构校验支撑**：finders.c 的下界/末地结构群系校验（isViableStructurePos
L1449-1506）直接调用本模块单点采样——下界 `getBiomeAt(g, 4, sampleX, 0, sampleZ)`
（y 无效，对应 `NetherSampler.biome_at`）；末地 `getBiomeAt(g, 16, chunkX, 0, chunkZ)`
（chunk 级，对应 `EndSampler.biome_at_chunk`）。bastion 的 getVariant 采样点、
fortress = NOT bastion 等规则在 `structure_map.py` 侧实现（复用本模块采样器）。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_Rand` | `class _Rand`（`__slots__ = ("s",)`） | 单条 legacy Random 流封装：48 位状态 + 完整版取数接口。`__init__(seed64)` 经 `mc_random.set_seed` 洗种子；`next_int(n)`/`next_double()` 委托 `Utils.SeedReverser.mc_random`（next_int 已是 rng.h 完整版语义，含拒绝采样）。 |
| `_skip_next_n` | `(rnd: _Rand, n: int) -> None` | rng.h skipNextN：纯状态推进 n 次（无输出），`s = (s·0x5DEECE66D + 0xB) & (2⁴⁸−1)`。用于 octaveInit 的 1572 次与 setEndSeed 的 17292 次跳步。 |
| `_perlin_init` | `(rnd: _Rand) -> tuple` | perlinInit → (a, b, c, idx, d2, h2, t2)：三次 nextDouble×256 取 a/b/c，256 次完整版 nextInt 洗牌得 257 项排列表（idx[256]=idx[0]），预计算 b 的整数/小数/fade 量。每条流只初始化一次（毫秒级）。 |
| `_octave_pair` | `(rnd: _Rand) -> list` | octaveInit(omin=−7, len=2)：先 `skipNextN(6·262=1572)`，再顺序初始化 2 个 perlin，persist 1/3→2/3、lacuna 2⁻⁶→2⁻⁷，返回 [(perlin, amplitude, lacunarity) × 2]。 |
| `_double_perlin` | `(rnd: _Rand) -> tuple` | doublePerlinInit：amplitude = (10/6)·2/3 = 10/9；octA、octB 在同一条流上顺序 `_octave_pair`，返回 (amplitude, oct_a, oct_b)。 |
| `_sample_perlin_y0` | `(p, xs, zs) -> np.ndarray` | samplePerlin 的 y=0 快速路径（整段 numpy 向量化）：d1=xs+a、d3=zs+c 取整/小数，h1/h3 uint8 截断、idx 索引链 `& 0xff` 回绕；`ilerp` 闭包用 `_LERP_SIG[(g&15)]` 符号表点积算 8 角梯度（点积用小数部分 f1/f3），再按 t1/t2/t3 三轴 lerp 合并。是下界/末地全部噪声的最底层。 |
| `_sample_octaves` | `(octs, xs, zs) -> np.ndarray` | sampleOctave（y=0，maintainPrecision=恒等）：逐 octave 累加 `amp · _sample_perlin_y0(p, xs·lac, zs·lac)`。 |
| `_sample_double_perlin` | `(dp, xs, zs) -> np.ndarray` | sampleDoublePerlin：`(_sample_octaves(oct_a, xs, zs) + _sample_octaves(oct_b, xs·f, zs·f)) · amplitude`，f = 337/331。 |
| `_sample_simplex2d` | `(p, xs, ys) -> np.ndarray` | sampleSimplex2D 向量化（返回 ×70 后的值）：skew/unskew 定单元格 → 按x0>y0 选三角 → 3 顶点梯度 `grad`（simplexGrad 的 con=0.5−x²−y² 负值截 0、con⁴ 权重 × `_LERP_SIG[(gi%12)]` 符号表）求和。供末地小岛高度场用。 |
| `NetherSampler` | `class NetherSampler` | 下界群系采样器（1.16+）：`__init__(seed)` 建立 temperature（seed）与 humidity（seed+1）两条 doublePerlin 流。 |
| `NetherSampler.biome_matrix` | `(nx0, nz0, w, h) -> np.ndarray` | 噪声格矩形批量采样：xs/zs 由 arange + broadcast 构成整批坐标，ravel 后一次性算 temp/humid 双场，`_nether_nearest` 判群系后 reshape (h, w)（行 = z 方向）。 |
| `NetherSampler.biome_at` | `(nx, nz) -> int` | 单点采样（噪声格坐标；结构校验用）：坐标包成 1 元素数组走同一管线，返回 int 群系 id。 |
| `_nether_nearest` | `(temp, humid) -> np.ndarray` | 5 点最近邻：temp/humid 转 float32 升维，对各候选点算 `dx²+dy²+常数项`，`np.argmin`（平局取最小索引 = C 的严格小于语义）取 `_NETHER_IDS`。 |
| `_c_div2` | `(v: np.ndarray) -> np.ndarray` | C 整数除法 v/2（向零截断）：`v≥0 ? v>>1 : −((−v)>>1)`，负奇数与算术移位不同（−5/2 = −2）。 |
| `EndSampler` | `class EndSampler` | 末地群系采样器（1.13+ 语义）：`__init__(seed)` 执行 setSeed → skipNextN(17292) → perlinInit 得单 Perlin。 |
| `EndSampler.biome_matrix_chunk` | `(x, z, w, h) -> np.ndarray` | mapEndBiome 的向量化实现（输入输出均为 chunk 单位）：先算 (h+26)×(w+26) hmap（rsq>4096 且 simplex<−0.9 填 float32 截断的小岛高度 v²，其余 0）；再对主区域 broadcast hx0/hz0，三分支掩码——rsq≤4096 → THE_END、(2h+1)² 32 位符号位为负 → END_BARRENS、其余收集坐标交 `_end_get_biome_batch`。 |
| `EndSampler.biome_at_chunk` | `(cx, cz) -> int` | 单 chunk 采样（结构校验用，getBiomeAt scale=16 语义）：对 (cx, cz, 1, 1) 调 `biome_matrix_chunk` 取 [0,0]。 |
| `EndSampler.map_region` | `(origin_nx, origin_nz, nw, nh) -> np.ndarray` | scale=4 像素展开（mapEnd L490-515）：原点对齐 chunk 边界（pad = origin & 3），算覆盖的 chunk 网格群系后 `np.repeat` 4×4 最近邻展开并裁剪出 (nh, nw)——像素 i 的群系 = chunk ((origin_nx+i)>>2, (origin_nz+j)>>2)。 |
| `_end_get_biome_batch` | `(out, hmap, hw, x, z, hx0, hz0, rows_t, cols_t) -> np.ndarray` | getEndBiome 批量向量化（按 64 个点分块控制峰值内存）：h 初值 `|hx1|≤15 且 |hz1|≤15 → 64·(hx1²+hz1²)` 否则 14401；窗起点 `_c_div2(hz1)−z`/`_c_div2(hx1)−x`（C 截断除法）；gather 25×25 窗 elev，`u = (ds[(hx1<0)+i] + ds[(hz1<0)+j])·elev`（elev=0 的格子置 2³⁰ 不参与），`h = min(h0, u.min)` 后按 <3600/≤10000/≤14400/else 分档写回。 |
| `_colors_for` | `(biomes: np.ndarray) -> np.ndarray` | int32 群系矩阵 → uint8 RGB（与 map_sampler 同一查表实现）。 |
| `_align_dims` | `(cx_blocks, cz_blocks, width_blocks, height_blocks) -> tuple` | 宽高对齐 4 的倍数（下限 16）+ 中心换算左上角噪声格，与 map_sampler 相同约定；返回 (w, h, nw, nh, origin_nx, origin_nz)。 |
| `sample_region_nether` | `(seed, cx_blocks, cz_blocks, width_blocks, height_blocks, on_progress=None, cancel=None) -> dict` | 下界矩形区域采样（1 像素 = 1 噪声格 = 4 方块，scale=4 无 Voronoi）：每 64 行一批调 `NetherSampler.biome_matrix`，批前查 cancel、批后回调 on_progress(…, "nether")；返回 dict 契约与 map_sampler.sample_region 一致（无 depth/temp/humid；ny=0、surface_mode=False、engine="python"）。 |
| `sample_region_end` | `(seed, cx_blocks, cz_blocks, width_blocks, height_blocks, on_progress=None, cancel=None) -> dict` | 末地矩形区域采样（1 像素 = 4 方块；chunk 级计算 + 最近邻展开）：每 64 行一批调 `EndSampler.map_region`，回调标签 "end"；返回契约同上。 |

**接口**：
- `Threads/task_MapPreviewer.py`（第 41 行）：`from Utils.MapPreviewer.nether_end_sampler import (…)`——下界/末地地图渲染
- `Tools/tool_MapPreviewer.py`（第 1945-1949 行，函数内局部导入）：悬停单点群系探测（`biome_at`/`biome_at_chunk`）
- `Utils/Public/structure_map.py`（第 55 行）：`from Utils.MapPreviewer.nether_end_sampler import (…)`——下界/末地结构的群系校验（bastion/fortress/末地结构等）
- 依赖：`Utils.SeedReverser.mc_random`（legacy Random 语义）、
  `Utils.MapPreviewer.biome_colors.biome_color`
- 对外提供：`NetherSampler`、`EndSampler`、`sample_region_nether`、`sample_region_end`
  及 10 个群系 id 常量；采样器类与其余函数供内部/structure_map 复用

**关键变量/常量**：

| 名称 | 类型/值 | 说明 |
|---|---|---|
| `_MASK48` / `_MASK64` | `2⁴⁸−1` / `2⁶⁴−1` | legacy Random 状态掩码 / 种子无符号化掩码。 |
| 群系 id 常量（10 个） | int | `NETHER_WASTES=8`、`SOUL_SAND_VALLEY=170`、`CRIMSON_FOREST=171`、`WARPED_FOREST=172`、`BASALT_DELTAS=173`；`THE_END=9`、`SMALL_END_ISLANDS=40`、`END_MIDLANDS=41`、`END_HIGHLANDS=42`、`END_BARRENS=43`。 |
| `_NETHER_PTS` | `(5,3) float32` | 下界 5 点最近邻表（getNetherBiome L177-183）：[dx, dy, 常数项]；warped_forest 常数 0.375²、basalt_deltas 常数 0.175²。 |
| `_NETHER_IDS` | `(5,) int32` | 与 `_NETHER_PTS` 行一一对应的群系 id。 |
| `_END_DS` | `(26,) int32` | getEndBiome 距离表 `ds[26] = (25−2i)²`（625…1…625）。 |
| `_LERP_SIG` | `(16,3) float64` | indexedLerp 16 case 的 (sa, sb, sc) 符号表（noise.c L27-42），perlin 与 simplex 共用。 |
| `_SKEW` / `_UNSKEW` | float | simplex 2D 歪斜/反歪斜常数：0.5·(√3−1) 与 (3−√3)/6。 |

---

## `Utils/MapPreviewer/_native/build_map.py`

**功能**：MapPreviewer 地图采样原生扩展的构建脚本：调用 MSVC `cl.exe` 把同目录的
`_map_sampler.cpp`（C++ 多线程采样管线，与 `_biome_refine.cpp` 同源）编译为
`_map_sampler.pyd`。产物被 `map_sampler.py` 尝试导入作为加速引擎；缺失或加载失败时
`map_sampler.py` 自动降级纯 Python 路径，因此本脚本是可选的性能组件维护入口。

用法（项目根目录或任意目录）：
`python Utils/MapPreviewer/_native/build_map.py`
环境要求：MSVC（cl.exe）在 PATH 中（建议在 "x64 Native Tools Command Prompt for VS"
里运行，或自行设置 INCLUDE/LIB 后直调）；venv 已安装 pybind11。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `main` | `() -> int` | 构建主流程：① 检查 `_map_sampler.cpp` 存在，缺失打印并返回 2；② 拼接 cl 命令行（FLAGS + 源文件 + `/Fe:` 输出 pyd + `/Fo:` 目标 obj + LINK），`subprocess.run(cwd=NATIVE_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace")` 执行；③ 把 stdout+stderr 写入日志 `_build_map_log.txt`；④ returncode==0 且 `.pyd` 存在 → 返回 0，返回 0 但无 `.pyd` → 返回 2，失败 → 透传 returncode。 |

**接口**：
- 独立脚本，无模块被它 import 之外的反向依赖；不被任何业务代码 import
- 产物 `_map_sampler.pyd` 被 `Utils/MapPreviewer/map_sampler.py` 导入（可选）
- 依赖 `pybind11`（`get_include()` 提供头文件路径）、`sysconfig`/`sys` 提供 Python
  头文件与导入库路径

**关键变量/常量**：

| 名称 | 类型/值 | 说明 |
|---|---|---|
| `NATIVE_DIR` | str | 本脚本所在目录（`os.path.dirname(os.path.abspath(__file__))`），同时是编译工作目录。 |
| `CPP` / `PYD` / `LOG` | str | 源文件 `_map_sampler.cpp`、产物 `_map_sampler.pyd`、编译日志 `_build_map_log.txt` 的绝对路径。 |
| `PY_INCLUDE` | str | `sysconfig.get_paths()["include"]`：Python 头文件目录。 |
| `PY_LIBS` | str | `sys.base_prefix + "\\libs"`：Python 导入库（python313.lib）目录。 |
| `PB_INCLUDE` | str | `pybind11.get_include()`：pybind11 头文件目录。 |
| `FLAGS` | list[str] | 编译开关：`/nologo /std:c++20 /utf-8 /O2 /EHsc /MD /LD` + 两个 `/I` 头文件路径。`/MD` 与官方 Python 发行版运行时一致（vcruntime 由 python313.dll 提供）；`/LD` 产出动态链接库；`/utf-8` 保证源码中文注释正确编码。 |
| `LINK` | list[str] | 链接开关：`/link /LIBPATH:{PY_LIBS} python313.lib`，显式链接 Python 3.13 导入库。 |

# 7. 种子逆推核心库（Utils/SeedReverser · 算法）

# 07 · SeedReverser 种子逆推核心模块文档

> 覆盖范围：`Utils/SeedReverser` 包内 6 个算法/数据模块，以及 `_native/` 下 2 个 pybind11 构建脚本。
> 依据：全部内容逐行取自源码精读，不含臆测；代码标识符保留英文。
> 实际行数（撰写时）：mc_random.py 304 / mc_rng.py 189 / seed_math.py 172 / structure_math.py 714 / biome_noise.py 973 / world_seed_refine.py 270 / build_biome.py 68 / build_native.py 69。

## 0. 总览：两条 RNG 语义线与逆推数据流

SeedReverser（结构种子逆推器）的数据流：

```
玩家观测（结构方块坐标）
   │  seed_math.compute_region / compute_offset
   ▼
(reg_x, reg_z, off_x, off_z) 观测列表
   │  structure_math.solve_structure_seeds —— 三层漏斗（mc_random 提供 LCG 原语）
   ▼
48 位结构种候选（= 64 位世界种子的低 48 位）
   │  world_seed_refine.refine_world_seeds —— 枚举高 16 位
   │  biome_noise.BiomeSampler 逐候选采样群系做二次校验
   ▼
完整 64 位世界种子
```

两条 RNG 语义线**严禁混用**（mc_random.py 模块 docstring 明示）：

1. **结构区块定位线**（mc_random.py）：对应 cubiomes finders.h 内联版 getFeaturePos / getLargeStructurePos，无拒绝采样。这是 SeedReverser 逆推与 StructurePreviewer 正向定位共用的线。
2. **拼装/布局线**（mc_rng.py）：对应 1.21.1 官方混淆字节码考证的 jigsaw 拼装机制（LegacyRandomSource / setLargeFeatureSeed / Mth.getSeed / Rotation 洗牌 / RuleProcessor 逐方块降解）。

生产加速：`_native/_solver_native.pyd`（逆推层 2 的 C++ 多线程扩展）与 `_native/_biome_refine.pyd`（世界种子精化扩展）；任一扩展缺失或运行期异常，Python 层自动降级到 numpy 档，再降级到纯 Python 档，功能不受影响。

---

## `Utils/SeedReverser/mc_random.py`（304 行）

**功能**：Java `java.util.Random` 的精确复刻（Minecraft 结构生成使用的 48 位 LCG），同时复刻 cubiomes 中与结构生成相关的接口。是整个 SeedReverser 与 StructurePreviewer 的最低层 RNG 原语库，只含函数、无类。

两条语义线（与 cubiomes 源码严格对应）：

1. **结构区块定位**（finders.h 内联版）：
   - 区域种子：`regionSeed = (structureSeed + regX*341873128712 + regZ*132897987541 + salt) mod 2^64`
   - 初始状态：`state = setSeed(regionSeed) = (regionSeed ^ 0x5DEECE66D) mod 2^48`
   - 每取一个偏移消耗一步 LCG：`state = LCG(state)`（即 `(state * 0x5DEECE66D + 0xB) & (2^48-1)`），随后 `val = (state >> 17) % r`——**无拒绝采样**；`r` 为 2 的幂时等价于 `val = (r * (state >> 17)) >> 31`。
   - 关键数学性质（逆推的理论基础）：`r` 整除 `2^k` 时，`val mod 2^k` 精确等于 `(state >> 17) mod 2^k`，只取决于状态低 (17+k) 位。
2. **概率判定**（cubiomes rng.h 完整版 nextInt，含拒绝采样）：掠夺者前哨站的 1/5 生成判定用 `nextInt(5)`（cubiomes finders.c 的 Outpost 分支显式调用 rng.h 的 nextInt 而非内联版）。

实现约定：

- 状态一律保存为 0 ~ 2^48-1 的整数；移位用 `>>`（Python 对非负整数即逻辑右移，与目标位区间内的 C 算术右移等价）；拒绝采样的溢出判断按 Java int（有符号 32 位）语义用掩码转写。
- **RNG 消耗粒度（标量版）**：`struct_next_int` 每次调用先推进一步 LCG 再取值（1 步）；`next_int` 在 2 的幂时 1 步出结果，否则每轮拒绝采样各消耗 1 步直到命中；`next_float` 消耗一次 `next(24)`（1 步）；`next_double` 消耗 `next(26) + next(27)`（2 步）；`set_seed` / `region_seed` 只做状态初始化，不消耗任何 RNG 步。
- **向量化版本（`vec_*`）与标量版的关系**：`vec_*` 是同名标量函数的 numpy uint64 数组批量版，逐元素语义完全一致，专为逆推层 1 / 层 2 的批量计算服务；向量化只覆盖**无拒绝采样**语义（层 2 只验证线性结构偏移，走无拒绝语义；前哨站概率只在层 3 标量验证，因此 `next_int` 没有向量化版本）。uint64 乘法/加法按 2^64 自然回绕，`& M48` 后与 C 的 48 位截断一致；**低 L 位输入时输出的低 L 位同样正确**（乘法低位只依赖乘数低位），这是层 1「低位局部性」成立的实现前提。numpy 未安装时向量化函数经 `_require_numpy` 抛 `ImportError`；标量路径始终可用。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `set_seed` | `(value: int) -> int` | Java `Random.setSeed`：`(value ^ 0x5DEECE66D) & (2^48-1)`；任意 64 位整数输入自动回绕到低 48 位 |
| `next_state` | `(state: int) -> int` | LCG 前进一步：`s' = (s * 0x5DEECE66D + 0xB) mod 2^48`，仅返回新状态 |
| `next_bits` | `(state: int, bits: int) -> int` | Java `Random.next(bits)`：先推进一步，返回新状态的高 bits 位 `s' >> (48 - bits)`（无符号；结构场景只用 17/31 位宽，另供 next(24)/26/27） |
| `next_int` | `(state: int, n: int) -> tuple[int, int]` | 完整版 `nextInt(bound)`（rng.h 语义，含拒绝采样）：2 的幂特判走 `(n * (s' >> 17)) >> 31`（1 步）；否则 `bits = s' >> 17`、`val = bits % n`，若 `((bits - val + n-1) & 0xFFFFFFFF) >= 0x80000000`（Java int 溢出变负）则再消耗一步重试，直至返回 `(val, s')`。仅供前哨站 1/5 判定等概率场景，结构定位勿用 |
| `struct_next_int` | `(state: int, r: int) -> tuple[int, int]` | 结构区块定位专用 nextInt（finders.h `getFeatureChunkInRegion` 内联版，**无拒绝采样**）：推进一步后，`r` 非 2 幂取 `(s' >> 17) % r`；`r` 为 2 幂取 `(r * (s' >> 17)) >> 31`。offX/offZ 各消耗一次调用 |
| `next_float` | `(state: int) -> tuple[float, int]` | `nextFloat = next(24) / 2^24`，消耗 1 步。用途：埋藏的宝藏 1% 生成判定（finders.c Treasure 分支 `nextFloat < 0.01`） |
| `next_double` | `(state: int) -> tuple[float, int]` | `nextDouble = ((next(26) << 27) + next(27)) / 2^53`，消耗 2 步。用途：废弃矿井 1.13+ 0.4% 生成判定（finders.c `nextDouble < 0.004`） |
| `region_seed` | `(structure_seed: int, reg_x: int, reg_z: int, salt: int) -> int` | cubiomes `getRegionSeed`：`(structure_seed + regX*341873128712 + regZ*132897987541 + salt) & (2^64-1)` 后 `^ 0x5DEECE66D` 取低 48 位；返回「setSeed 之后、第一次取偏移之前」的 48 位初始状态 |
| `_require_numpy` | `() -> module` | 私有：numpy 未安装时抛 `ImportError`（提示在 MCHelper 的 venv 中 `pip install numpy`），否则返回 numpy 模块。所有 `vec_*` 函数的入口守卫 |
| `_vec_uint64_consts` | `() -> tuple` | 私有：返回 uint64 形式的 `(K, B, M48)` 常量三元组，供向量化运算复用 |
| `vec_step` | `(states: ndarray) -> ndarray` | 数组版 `next_state`：`(states * K + B) & M48`；uint64 乘加按 2^64 回绕；低位输入时低位输出正确（层 1 低位封闭性的实现基础） |
| `vec_region_seed` | `(structure_seeds: ndarray, reg_x: int, reg_z: int, salt: int) -> ndarray` | 数组版 `region_seed`：`reg_x/reg_z` 可为负，`regX*系数` 可能超 int64，故系数先各自 `& (2^64-1)` 折算，全程 uint64 运算（加法按 2^64 自然回绕，与 C 一致），最后 `^ K` 取低 48 位 |
| `vec_struct_next_int` | `(states: ndarray, r: int) -> tuple[ndarray, ndarray]` | 数组版 `struct_next_int`（无拒绝采样）：`vec_step` 一步后取 `>> 17`，2 幂走 `(bits * r) >> 31`；返回 `(val 数组, 新状态数组)` |
| `vec_state_lows` | `(structure_seed_lows: ndarray, L: int, reg_x: int, reg_z: int, salt: int) -> ndarray` | 层 1 专用「低位 region_seed」：由结构种低 L 位直接推 setSeed 后状态低 L 位。原理：regionSeed 的加法进位只向上传播、异或按位运算，低 L 位封闭，故状态低 L 位只依赖结构种低 L 位；实现为三个系数与 salt 都先 `& (2^L-1)`，加法后 `^ (K & (2^L-1))` 再掩码 |

**接口**：

- 包内：`Utils/SeedReverser/structure_math.py` 全量使用（正向 `region_seed`/`struct_next_int`，逆推 `vec_state_lows`/`vec_step`/`vec_region_seed`/`vec_struct_next_int`，概率判定 `set_seed`/`next_state`/`next_int`，以及 `_HAVE_NUMPY`/`_np` 标志）。
- 跨域复用：
  - `Utils/Public/structure_map.py`（公共种子地图模块）：正向画结构位置；
  - `Utils/MapPreviewer/nether_end_sampler.py`（MapPreviewer 下界/末地群系采样）；
  - `Utils/StructurePreviewer/` 的 `composition.py` / `mansion_pieces.py` / `stronghold_pieces.py` / `end_city_pieces.py`：结构 3D 预览的正向拼装复用同一条 LCG 语义。
- 对外提供：结构线 LCG 的全部标量与向量化原语；SeedReverser 三层漏斗、StructurePreviewer 正向模拟、公共地图共用的最低层。

**关键变量/常量**：

| 名称 | 值 | 语义 |
|---|---|---|
| `_MULTIPLIER` | `0x5DEECE66D` | LCG 乘子 a（= 十进制 25214903917，Java Random / cubiomes rng.h 同源） |
| `_ADDEND` | `0xB` | LCG 增量 b（= 11） |
| `_MASK48` | `(1 << 48) - 1` | 48 位状态掩码 |
| `_MASK64` | `(1 << 64) - 1` | 64 位回绕掩码（regionSeed 加法运算用） |
| `_REG_X_COEF` | `341873128712` | regionSeed 公式中 regX 的系数（cubiomes getRegionSeed） |
| `_REG_Z_COEF` | `132897987541` | regionSeed 公式中 regZ 的系数 |
| `_HAVE_NUMPY` / `_np` | `True/False` / 模块引用 | 导入期探测的 numpy 可用性标志与模块引用，包内其他模块（如 structure_math 层 1/层 2 选档）直接读取 |

---

## `Utils/SeedReverser/mc_rng.py`（189 行）

**功能**：Python 复刻 Minecraft 1.21 jigsaw 拼装随机机制（基于 1.21.1 官方混淆字节码考证）。与 mc_random 的分工：mc_random 服务「结构区块定位线」，本模块服务「拼装/布局线」。混淆名 → 原名对应（docstring 考证表）：`dyz`=LegacyRandomSource（48 位 LCG）、`dyn`=BitRandomSource（nextInt/nextLong/nextFloat 默认实现）、`dzx`=WorldgenRandom（setLargeFeatureSeed）、`ad`=Util（shuffle/getRandom）、`dmm`=Rotation（getShuffled）、`ayo`=Mth（getSeed(BlockPos)）、`enm`=RuleProcessor（逐方块降解，每方块按坐标重播种、规则间共享随机流）、`ekv$b`=JigsawPlacement$Placer（tryPlacingChildren）。所有乘加运算按 Java long（mod 2^64）/int（mod 2^32）回绕语义模拟。

核心流程（按 RNG 消耗粒度）：

1. **`set_large_feature_seed`**（dzx.c(J,II)，GenerationContext 布局随机源播种）：
   `setSeed(levelSeed)` → `nextLong()` 两次得 l1、l2（**1.21.1 无 `|1`**，dzx.c 字节码实证）→ `setSeed((chunkX*l1) ^ (chunkZ*l2) ^ levelSeed)`（全部按 Java long 回绕；chunkX/chunkZ 先按 Java int 截断再参与 64 位乘法）。消耗 2 次 nextLong（各 2 步 LCG，共 4 步）后重播种。字节码 L130-156 无 `lor`、用 `lxor` 组合；调用点 ejr$a.a 压栈 `dcd.e`(=x, 低 32 位) → 第一个 int、`dcd.f`(=z) → 第二个。同参数的 dzx.a(JII) 才有 `|1 + ladd`（散点结构概率用），勿混。本式与 cubiomes `chunkGenerateRnd` 恒等——**结构布局流与 getVariant 变种流是同一条流**（对拍脚本 cross_check_rng_streams.py 6/6 全一致验证）。
2. **`mth_get_seed`**（ayo.b(III)，逐方块降解种子）：`l = (x * 3129871 /*imul，32 位回绕*/) ^ (z * 116129781) ^ y` → `l = l * l * 42317861 + l * 11`（Java long 回绕）→ `return l >> 16`（**算术右移**，有符号）。
3. **`LegacyRandomSource.next_int(bound)`**（dyn.a(I)）：先取 `next(31)`（1 步）；bound 为 2 的幂直接 `(bound * r) >> 31`（bound*r < 2^62 无回绕问题）；否则拒绝采样 `val = r % bound`，若 `r - val + (bound-1) > 0x7FFFFFFF`（Java int 溢出变负）则再取 next(31) 重试。
4. **`shuffle_list`**（ad.c，Fisher-Yates）：`i` 从 size 递减到 2，`j = nextInt(i)`，交换 `i-1` 与 `j`；每次交换消耗一次 nextInt（1 步起）。
5. **`rotation_shuffled` / `rotation_get_random`**（dmm）：`tryPlacingChildren` 对**每个候选元素**调用一次 rotation_shuffled（洗 4 元素旋转表）；拼装**起点**调用一次 rotation_get_random（随机取一个旋转）。
6. **`DegradationRandom`**（enm.a，RuleProcessor.processBlock 的逐方块随机源）：对每个方块 `setSeed(Mth.getSeed(pos))` 重播种，然后把同一条流依次传给各条规则评估；**输入谓词短路不匹配时不消耗随机数**。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `java_int` | `(v: int) -> int` | Python 整数 → Java int（有符号 32 位）：`& 0xFFFFFFFF` 后 ≥2^31 时减 2^32 |
| `java_long` | `(v: int) -> int` | Python 整数 → Java long（有符号 64 位） |
| `_u` | `(v: int) -> int` | 有符号/任意整数 → 64 位无符号表示（StructurePreviewer 多个拼装模块直接 import） |
| `LegacyRandomSource` | `class` | dyz：Java 48 位 LCG（`__slots__ = ("state",)`）。`set_seed`：`(seed ^ MULT) & MASK_48`；`next_bits(bits)`：推进一步返回新状态高 bits 位；`next_int_bits(bits)`：next(bits) 的 Java int 版；`next_long`：h=next(32)、l=next(32)（各自按 Java int 有符号化），`((long)h << 32) + (long)l`（消耗 4 步）；`next_int(bound)`：见上；`next_float`：`next(24) * 2^-24`；`next_boolean`：`next(1) != 0` |
| `shuffle_list` | `(rng: LegacyRandomSource, items: Sequence[T]) -> List[T]` | ad.c Fisher-Yates：i 从 size 递减到 2，j=nextInt(i)，交换 i-1 与 j |
| `get_random_of` | `(rng, items) -> T` | ad.a：`items[nextInt(len(items))]` |
| `rotation_shuffled` | `(rng) -> List[str]` | dmm.b(ayw)：ROTATIONS 表洗牌（tryPlacingChildren 每候选一次） |
| `rotation_get_random` | `(rng) -> str` | dmm.a(ayw)：ROTATIONS 表随机取一（拼装起点一次） |
| `set_large_feature_seed` | `(rng, level_seed: int, chunk_x: int, chunk_z: int) -> None` | dzx.c(J,II) 布局流播种（流程见上） |
| `mth_get_seed` | `(x: int, y: int, z: int) -> int` | ayo.b(III) 逐方块降解种子（流程见上） |
| `DegradationRandom` | `class` | enm.a 逐方块随机源：`reseed_for(x, y, z)` 用 mth_get_seed 重播种内部 rng；`next_float()` 透传 |
| `make_layout_rng` | `(level_seed, chunk_x, chunk_z) -> LegacyRandomSource` | ejr$a.a(J, dcd) 等价物：`new WorldgenRandom(new LegacyRandomSource(0))` + set_large_feature_seed，一步得到布局随机源 |

**接口**：

- 包内：`Utils/SeedReverser/jigsaw_assembly.py`（堡垒遗迹 jigsaw 拼装）import `LegacyRandomSource` / `make_layout_rng` / `mth_get_seed` / `rotation_get_random` / `rotation_shuffled` / `shuffle_list`。
- 跨域复用（StructurePreviewer）：`village_assembly.py` / `ancient_city_assembly.py` / `outpost_assembly.py` / `trial_assembly.py` 直接 import 常量 `MASK_48` / `MASK_64` / `MULT` / `ADD` 与 `_u` 等，在同一条 LCG 语义上做正向拼装。
- 对外提供：1.21 拼装随机机制的完整 Python 复刻（布局播种、旋转洗牌、逐方块降解流），供 jigsaw 拼装类工具正向重放。

**关键变量/常量**：

| 名称 | 值 | 语义 |
|---|---|---|
| `MULT` | `25214903917` | LCG 乘子（= 0x5DEECE66D，与 mc_random._MULTIPLIER 同值不同表示） |
| `ADD` | `11` | LCG 增量 |
| `MASK_48` | `(1 << 48) - 1` | 48 位状态掩码 |
| `MASK_32` | `0xFFFFFFFF` | 32 位掩码（java_int 用） |
| `MASK_64` | `0xFFFFFFFFFFFFFFFF` | 64 位掩码（java_long/_u 用） |
| `ROTATIONS` | `("NONE", "CLOCKWISE_90", "CLOCKWISE_180", "COUNTERCLOCKWISE_90")` | dmm 旋转枚举顺序（索引 0~3），洗牌/随机选取的目标表 |

---

## `Utils/SeedReverser/seed_math.py`（172 行）

**功能**：SeedReverser 的辅助纯函数集：信息量估算 + 区域/偏移换算。模块不含任何 UI 与线程逻辑，全部为确定性纯函数。docstring 给出数学背景：区域种子 `s0 = (structureSeed + regX*341873128712 + regZ*132897987541 + salt) mod 2^64` → `st = (s0 ^ 0x5DEECE66D) mod 2^48` → `st1 = LCG(st)` 得 offX、`st2 = LCG(st1)` 得 offZ；观测换算链为 `cx = x >> 4`、`reg = floor(cx / region_size)`、`off = cx - reg * region_size`。

各函数要点：

- `calc_info_bits(observations)`：累计约束比特数。基础量：线性散布结构 offX/offZ 各贡献 `log2(chunk_range)`（合计约 9.17 比特）；三角散布（monument 等，4 次 nextInt 取平均）按 1 维计约 `log2(chunk_range)`。条目支持**双形态**：观测 dict（含 `"params"` 与可选 `"tol"`，UI 的 obs 结构，tol 缺省按 0 精确处理）或 params 本体（dict / 带 `chunk_range` 与 `scatter` 属性的对象，等效 tol=0，向后兼容）。容差折减：tol 把每维位置约束从 1 个值放宽为 `min(2*tol+1, chunk_range)` 个候选值（与求解器层 2 范围校验 `_estimate_tolerance_work` 的通过率同口径），该维信息量 = `log2(r) - log2(有效窗口)`；tol 钳制 0~2（与 structure_math._obs_tol、UI 行内下拉同域）；window=r 时该维归零。
- `info_hint(bits)`：按累计比特数返回 UI 信息量条右侧提示文案：<9「至少需要 3 个结构才能计算」、<18「再找 2~3 个结构」、<27「可以尝试计算，再找 1~2 个更准」、<40「信息量充足，可以计算」、否则「信息量非常充足，直接计算即可」。
- `compute_region(block_x, block_z, region_size)`：`(block_x >> 4) // region_size`——Python `//` 即数学地板除，负数坐标正确。
- `compute_offset(block_x, block_z, reg_x, reg_z, region_size)`：`offX = cx - regX * region_size`，保证 `0 <= off < region_size`。
- `is_near_boundary(off_x, off_z, region_size, threshold=2)`：`off < threshold` 或 `off > region_size - 1 - threshold`（任一维）视为靠近区域边界，供 UI 提醒观测质量。
- `region_seed_value(structure_seed, reg_x, reg_z, salt)`：返回 **setSeed 之前**的 64 位原始 regionSeed（mod 2^64 回绕）。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `calc_info_bits` | `(observations) -> float` | 累计信息量（比特）：每观测 `dims * log2(chunk_range / window)`；linear dims=2、triangle dims=1；tol 折减与钳制见上 |
| `info_hint` | `(bits: float) -> str` | 按比特数分档返回提示文案 |
| `compute_region` | `(block_x, block_z, region_size) -> tuple[int, int]` | 方块坐标 → 区域坐标（先 `>> 4` 转区块，再地板除） |
| `compute_offset` | `(block_x, block_z, reg_x, reg_z, region_size) -> tuple[int, int]` | 方块坐标 + 区域坐标 → 区域内区块偏移 (offX, offZ) |
| `is_near_boundary` | `(off_x, off_z, region_size, threshold=2) -> bool` | 偏移是否离区域边界过近（任一维） |
| `region_seed_value` | `(structure_seed, reg_x, reg_z, salt) -> int` | setSeed 之前的 64 位原始 regionSeed |

**接口**：

- 包内：`Utils/SeedReverser/structure_math.py` 顶部 `from . import seed_math`（当前正文无 `seed_math.` 调用点，属预留/历史导入）。
- UI 直用：`Tools/tool_SeedReverser.py` 大量调用（`calc_info_bits`/`info_hint` 驱动信息量条；`compute_region`/`compute_offset` 在观测录入与 F3+C 粘贴解析中换算；`is_near_boundary` 生成边界警告并写入 `obs["near_boundary"]`）。
- 对外提供：观测 → 区域/偏移换算与信息量估算的唯一来源。

**关键变量/常量**：

| 名称 | 值 | 语义 |
|---|---|---|
| `_REG_X_COEF` | `341873128712` | regionSeed 的 regX 系数（与 mc_random 重复定义，本模块自用于 region_seed_value） |
| `_REG_Z_COEF` | `132897987541` | regionSeed 的 regZ 系数（同上） |

---

## `Utils/SeedReverser/structure_math.py`（714 行）

**功能**：SeedReverser 的结构正向复刻与逆推求解（cubiomes 权威算法 + SeedCrackerX TimeMachine lifting 思路，三层漏斗）。本文件是整个逆推器的核心。

### 正向复刻（finders.h 内联版语义）

- **线性散布结构**（沉船/沙漠神殿/雪屋/女巫小屋/丛林神庙/村庄/海底废墟/远古城市/试炼密室）：`regionSeed = (structureSeed + regX*341873128712 + regZ*132897987541 + salt) mod 2^64` → `st = setSeed(regionSeed)` → offX = 第 1 次 struct_next_int（**消耗 LCG 第 1 步**），offZ = 第 2 次（**消耗第 2 步**）→ 结构方块坐标 = `((regX*regionSize + offX) << 4, (regZ*regionSize + offZ) << 4)`（西北角）。
- **三角散布**（海底神殿 monument / 林地府邸 mansion）：4 次 struct_next_int，offX = `(a1 + a2) >> 1`、offZ = `(b1 + b2) >> 1`（共消耗 4 步）。mansion 仅 MapPreviewer 标注用，SeedReverser UI 已下架（但参数仍可传入，MapPreviewer 共用参数表）。
- **前哨站**：坐标同线性 + `setAttemptSeed` 概率判定 `nextInt(5) == 0`（setAttemptSeed 作用在**结构种子**上、非区域种子——finders.c Outpost 分支语义）。

### 逆推数学基础

regionSeed 的加法/异或/截断在低 L 位封闭，LCG 乘加亦然，故「结构种低 L 位相同 ⟹ 全部状态低 L 位相同」。而偏移 `val = (st >> 17) % r` 在 r 是 2^k 的倍数时满足 `val mod 2^k = (st >> 17) mod 2^k`，只取决于状态低 (17+k) 位。每个结构用自己的 `lift_mod` 参与预筛：r=24 的结构（沙漠神殿/雪屋/女巫小屋/丛林神庙）可用 mod8（低 20 位）；r=20/12 用 mod4（低 19 位）；r=26/22 用 mod2（低 18 位）。

### solve_structure_seeds 三层漏斗流程

1. **入口校验**：观测 ≥3 个；全局 tol ∈ [0, 2]。`_lift_split` 把观测分组：可 lifting（scatter=="linear" 且 lift_mod>=2，按 lift_mod **降序**——mod4 排前面，压缩比高）与不可 lifting（monument/mansion 三角、ancient_city 的 2 幂 r、outpost 概率，**只参与层 3 精确验证**）；每个 entry 归一化进 salt/chunk_range/region_size/scatter/lift_mod/tol。可 lifting 观测 < 4 个（`_MIN_LIFT_OBS`）抛 ValueError（提示废弃传送门、海底神殿、林地府邸、远古城市、前哨站只能作验证观测）。
2. **位宽**：`low_bits = max(18, max(17 + log2(lift_mod_i)))`（mod8→20、mod4→19、mod2→18）。
3. **容差守卫**（任一 lifting 观测 tol>0 时）：`_estimate_tolerance_work` 估算——层 1 每维通过率 = `min(2tol+1, mod)/mod`（mod ≤ 2tol+1 时该观测在层 1 完全失效，如村庄/试炼 mod2 在 tol≥1 时）、层 2 每维通过率 = `min(2tol+1, r)/r`；验证次数 ≈ `2^48 × ∏(min(2tol_i+1, mod_i)/mod_i)²`、候选数 ≈ `2^48 × ∏(min(2tol_i+1, r_i)/r_i)²`。验证次数超 `_TOLERANCE_MAX_VERIFIES`（1200 s × 5e8 次/秒）或候选数超 100 万则提前报错并指引补充小型结构观测（或改用精确模式 + /locate）。
4. **层 1（低 L 位枚举 + mod 预筛）**：枚举 0..2^low_bits-1 全部低位。numpy 路径 `_layer1_lowbits_np` 逐观测过滤：`state_low = vec_state_lows(lows, L, regX, regZ, salt)` → `st1 = vec_step(state_low)`（**LCG 第 1 步，仅低 L 位参与**）→ `st2 = vec_step(st1)`（**第 2 步**）→ `ox = (st1 >> 17) & (mod-1)`、`oz = (st2 >> 17) & (mod-1)`（mod 为 2 幂，% 等价于位与），与观测 `offX % mod` / `offZ % mod` 比较，保留同时满足两条件的行（幸存 ≈ `2^L / ∏mod_i²`）。tol>0 时改为**集合成员**判断 `{(off±d) % mod | d=-tol..tol}`（mod < 2tol+1 时集合会绕区域回卷引入弱化——方向不变、绝不含漏真种子；mod=2 在 tol≥1 时退化为无预筛）。无 numpy 时走 `_layer1_lowbits_py` 纯 Python 逐低位标量同语义（用完整 struct_next_int 后 `& (mod-1)`）。
5. **层 2（高位枚举 + 完整偏移验证）**：对每个幸存低位，枚举高 (48−low_bits) 位，按 `_LIFT_BLOCK = 2^22`（约 4M）组块向量化：`seeds = (upper << low_bits) | lower`；随后**逐观测压缩**：`st = vec_region_seed(alive, regX, regZ, salt)` → `ox, st = vec_struct_next_int(st, r)`（**消耗该观测 RNG 第 1 步**）→ 筛 `ox == off_x`（tol>0 时 int64 距离 `|ox - off_x| <= tol`，不跨区域绕回——锚点跨区域时该观测本就不可靠，UI 另行警告）→ 对幸存者再 `oz = vec_struct_next_int(st[keep], r)`（**消耗第 2 步**，只对 offX 幸存者计算，省约 45%）→ 筛 oz；每个观测后种子数 ÷ r²，第二观测后通常只剩个位数。三档实现按可用性自动选择：① native（默认，C++ 多线程 `_solver_native.layer2_full`，直接传 dict 观测列表，语义与 numpy 档一致，数十倍加速）；② numpy；③ 纯 Python（`_layer2_py` 标量逐种子，极慢仅兜底）。native 运行期异常（扩展损毁/回调异常）自动回落下一档；取消时返回已完成部分的候选。
6. **层 3（精确正向复算）**：`_layer3_verify` 对层 2 候选逐一调用 `_verify_observation` 复算**全部**观测（含三角/概率/2 幂结构）：正向 `get_structure_pos` → 与期望区块（obs 的 `block_cx/block_cz`，缺失则 `reg*region_size + off` 推算）比对；tol>0 按**切比雪夫距离** `max(|dx|, |dz|) <= tol` 放宽（玩家站位语义）；`pillager_outpost` 位置吻合后还须通过 `outpost_probability` 判定。

### verify_candidate_seed 反向验证流程

UI「验证候选种子」的唯一语义来源，与手动验证按钮、层 3 复算同源。对单个候选 48 位结构种：

1. **观察值准备**：逐观测取 per-obs 容差（`_obs_tol`：obs["tol"] 优先，缺省用参数 tol；非法值回退并钳制 0~2）。
2. **正向重放 RNG**：`get_structure_pos(struct_key, seed, reg_x, reg_z, version_key)` —— 从 structure_params 取 salt/region_size/chunk_range/scatter → `region_seed` 初始化状态 → 按散布类型重放（线性 2 步 / 三角 4 步）→ 生成方块坐标。
3. **观测区块**：obs 带 `"x"/"z"`（F3+C 原始站位）时 `obs >> 4` 得区块；否则取期望区块 `reg*region_size + off`。
4. **偏移/区块比对**：精确模式要求生成区块与观测区块相等；tol>0 按切比雪夫距离 ≤ tol 放宽。
5. **前哨站概率**：位置吻合后调用 `outpost_probability`——其内部流程：`cx, cz = 生成区块` → `s = (structure_seed ^ (cx >> 4) ^ ((cz >> 4) << 4)) & (2^64-1)`（setAttemptSeed，作用在结构种子上）→ `set_seed(s)` → `next_state` 一次（next(s, 31)，**消耗 1 步**）→ `next_int(state, 5)`（2 非幂，拒绝采样每轮 1 步）→ 判定 `val == 0`。
6. **输出**：逐条比对文本行（观测编号/名称/观测区块/生成区块/✓ 吻合 或 ✗ 不符（未通过 1/5 生成概率判定））+ 汇总行；返回 `(ok: bool, lines: list[str])`。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `get_structure_pos` | `(struct_key, structure_seed, reg_x, reg_z, version_key="1.21") -> tuple[int, int]` | 正向：由结构种与区域坐标算结构方块坐标（西北角）。取参数表 → region_seed → 按 scatter 分派线性/三角偏移 → `((regX*regionSize+offX) << 4, ...)` |
| `_next_offsets_linear` | `(state: int, r: int) -> tuple[int, int]` | 线性散布：2 次 `struct_next_int` → (offX, offZ)（无拒绝采样，2 步） |
| `_next_offsets_triangle` | `(state: int, r: int) -> tuple[int, int]` | 三角散布：4 次 `struct_next_int`，两次平均（monument 观测用 / mansion 仅 MapPreviewer 标注用，4 步） |
| `get_structure_chunk` | `(struct_key, structure_seed, reg_x, reg_z, version_key) -> tuple[int, int]` | 结构区块坐标（get_structure_pos 结果 `>> 4`） |
| `outpost_probability` | `(structure_seed, reg_x, reg_z, version_key) -> bool` | 前哨站 1/5 概率判定（流程见 verify_candidate_seed 第 5 步） |
| `_obs_tol` | `(ob: dict, default_tol: int = 0) -> int` | 私有：读 per-obs 容差（ob["tol"] 优先），非法/越界回退并钳制 0~2 |
| `_estimate_tolerance_work` | `(lift_obs) -> tuple[float, float]` | 私有：估算容差求解的层 2 验证次数与候选数期望（守卫用，公式见上） |
| `_lift_split` | `(observations, version_key, default_tol=0) -> (lift_obs, other_obs)` | 私有：观测分组（linear 且 lift_mod>=2 为可 lifting），entry 归一化参数与 tol，lift_mod 降序 |
| `_layer1_lowbits_np` | `(lift_obs, low_bits, on_progress=None) -> ndarray` | 层 1 numpy 档：枚举低位 + 各观测 lift_mod 预筛（流程见上），返回幸存低位 uint64 升序数组 |
| `_layer1_lowbits_py` | `(lift_obs, low_bits, on_progress=None) -> list[int]` | 层 1 纯 Python 兜底：逐低位标量验证，语义与 numpy 档一致 |
| `_layer2_np` | `(lift_obs, lows_arr, low_bits, on_progress=None, cancel=None) -> list[int]` | 层 2 numpy 档：组块（4M）向量化 + 压缩索引 + 完整偏移验证（流程见上） |
| `_layer2_py` | `(lift_obs, lower_list, low_bits, on_progress=None, cancel=None) -> list[int]` | 层 2 纯 Python 兜底：逐种子标量验证（每 100 万步报一次进度） |
| `_layer2_native` | `(lift_obs, lower_list, low_bits, on_progress=None, cancel=None) -> list[int]` | 层 2 C++ 档：把 dict 观测列表与低位列表交给 `_solver_native.layer2_full`（计算期零 Python 交互）；扩展缺失抛 RuntimeError 由调用方降级；on_progress/cancel 在 monitor 线程被调用、不得接触 Qt |
| `_layer3_verify` | `(candidates, observations, version_key, on_progress=None, default_tol=0) -> list[int]` | 层 3：候选逐一 `all(_verify_observation(...))` 复算全部观测 |
| `_verify_observation` | `(seed, o: dict, version_key, tol=0) -> bool` | 单观测正向验证：期望区块 vs 生成区块（tol 用切比雪夫距离）；outpost 附加概率判定 |
| `verify_candidate_seed` | `(seed, observations, version_key, tol=0) -> tuple[bool, list[str]]` | 单候选全量比对（UI 验证唯一语义来源，流程见上） |
| `solve_structure_seeds` | `(observations, version_key="1.21", on_progress=None, cancel=None, tol=0) -> dict` | 三层漏斗主入口；返回 `{"candidates": [...], "stages": {"layer1","layer2","layer3","low_bits"}, "cancelled": bool}`；观测不足/可 lifting 不足/容差超限抛 ValueError |

**接口**：

- 线程/UI：`Threads/task_SeedReverser.py` import `solve_structure_seeds` + `verify_candidate_seed`（后台计算线程）；`Tools/tool_SeedReverser.py` import `verify_candidate_seed`（验证按钮）。
- 跨域复用：`Utils/Public/structure_map.py`（公共种子地图模块）import `get_structure_pos` 正向定位结构。
- 包内依赖：`mc_random`（LCG 原语与 numpy 标志）、`Utils.Public.structure_params`（salt/region_size/chunk_range/scatter/lift_mod 参数表，与 MapPreviewer 共用）；顶部 `from . import seed_math` 当前无调用点（预留导入）。
- 对外提供：正向坐标计算（含前哨站概率）、三层漏斗逆推、单种子验证三组能力。

**关键变量/常量**：

| 名称 | 值 | 语义 |
|---|---|---|
| `_STRUCT_BITS` | `48` | 结构种位宽 |
| `_MIN_LOW_BITS` | `18` | 层 1 枚举位宽下限（mod8 需 17+3=20 位、mod4 需 19、mod2 需 18；solve 内按观测实际模数取 max） |
| `_MIN_LIFT_OBS` | `4` | 最少可 lifting 观测数（4 个 mod4 观测后层 1 幸存 ≈ 2^(20-16)=16） |
| `_LIFT_BLOCK` | `1 << 22` | 层 2 组块大小（约 4M 候选/块，控制内存 < 百 MB） |
| `_TOLERANCE_TIME_LIMIT_S` | `1200` | 容差模式守卫耗时上限（秒；2026-09-09 应用户要求由 10 分钟放宽至 20 分钟，覆盖 8×mod8 tol=2 端到端约 5 分钟场景） |
| `_NATIVE_VERIFY_RATE` | `5e8` | native 层 2 实测吞吐（次验证/秒，2026-09 校准） |
| `_TOLERANCE_MAX_VERIFIES` | `1200 × 5e8` | 验证次数上限（= 6e11；可拦住 mod2 混合的天级场景） |
| `_TOLERANCE_MAX_CANDIDATES` | `1_000_000` | 候选数可用性上限（百万级无法人工核对） |
| `_MAX_TOLERANCE` | `2` | 站位容差上限（区块）；容差每 +1 信息量指数级下降，3 已普遍超守卫且村庄/试炼类完全失效 |
| `_native_ext` | `_solver_native` 模块或 `None` | C++ 层 2 扩展引用；导入期 ImportError 及扩展自身异常一律降级为 None |

---

## `Utils/SeedReverser/biome_noise.py`（973 行）

**功能**：1.18+ 群系噪声生成器（纯 Python 位级实现，参数逐项对齐 cubiomes 源码）。用途：世界种子精化（SeedReverser 二期）——给定 48 位结构种候选与若干群系观测点，供 world_seed_refine 枚举高 16 位时逐种子采样群系做判定。纯 Python 版本用于正确性基准与回归测试；生产枚举走 `_native` C 扩展（`_biome_refine`），本模块在纯 Python 下亦完整可用。

实现范围（仅本文件用到的子集，全部逐行核对自 cubiomes）：rng.h L185-248 Xoroshiro128+ / SplitMix64（xSetSeed）；noise.c L79-107 xPerlinInit（3 次 xNextDouble + Fisher-Yates 256）、L391-446 xOctaveInit（参数级状态 + md5("octave_-N")）、L538-572 xDoublePerlinInit / sampleDoublePerlin（337/331）；biomenoise.c L844-907 六个气候参数的 MD5 种子常量与八度参数、L946-1133 depth 样条（initBiomeNoise 系列构建函数）、L1141-1191 sampleBiomeNoise（shift 采样 + np 量化）、L1369-1484 climateToBiome（btree 最近邻 R 树搜索）；tables/btree*.h 群系树数据表。

浮点精度约定（与 cubiomes bit 级一致的必要约定）：气候参数噪声在原实现中于 float(32 位) 下累加，本文件在对应位置用 `np.float32` 截断模拟，其余运算用 float64；样条构建/求值全程 float32（depth 的常量运算是 double）；np 量化 `(int64)(10000.0F * v)` 先 float32 乘法再向零截断。

### btree_tables.npz 与版本键查询

- `btree_tables.npz`（与本模块同目录）：数据由 extract 脚本从 cubiomes `tables/` 生成，npz 键为 `{name}_order`（R 树分支因子）/ `{name}_steps` / `{name}_param` / `{name}_nodes`。
- `_load_btree(name)`：惰性加载并缓存进模块级 `_BTREES` dict（进程内每版本只读一次 npz）。`BTree` 对象含 `name/order/steps(uint32)/param(int64，每节点参数盒 lo/hi)/nodes(uint64，节点编码)/len`。
- `VERSION_TO_BTREE`（版本键 → btree 表名）：`"1.21"` → `btree21wd`；`"1.21.11"` → `btree21wd`（1.21.x 线共用 21wd 群系树，1.21.11 为 MapPreviewer 坐标地图版本键）；`"26.2"` → `btree262`（26.2 混沌更新：仅新增硫磺洞穴群系，其余继承 21wd）。npz 内 btree18/19/20 数据保留供 native 槽表加载，Python 层不再引用。
- `get_btree(version_key)`：先做版本校验（不支持的版本抛 ValueError 并列出支持版本），再 `_load_btree`。

### 气候参数 → 群系 id 映射链（BiomeSampler 一次采样全流程，含每步 RNG 消耗）

1. **参数级种子**：`Xoroshiro.from_seed(seed)`（xSetSeed：`l = value ^ 0x6A09E667F3BCC909`、`h = l + 0x9E3779B97F4A7C15`，然后 lo/hi 两侧各自 `^>>30 → *0xBF58476D1CE4E5B9 → ^>>27 → *0x94D049BB133111EB → ^>>31`）→ `next_long()` 两次消耗 2 个输出得 `(xlo, xhi)`（等价 setBiomeSeed 的参数级种子）。
2. **六个气候噪声对象**：对 SHIFT/TEMPERATURE/HUMIDITY/CONTINENTALNESS/EROSION/WEIRDNESS（索引 0~5，`NP_MAX=6`）逐个 `Xoroshiro(xlo ^ md5_lo, xhi ^ md5_hi)`（md5 常量取 `_CLIMATE_SMALL`/`_CLIMATE_LARGE` 表）→ `x_double_perlin_init`：两组 `x_octave_init`；每组 `x_octave_init` 先**消耗 2 次 next_long** 得参数级状态 `(xlo', xhi')`，再对幅值非零的每个八度用 `MD5_OCTAVE_N[12 + omin + i]`（md5("octave_-N") 常量表，omin ∈ -12..0）异或派生独立 Xoroshiro，逐个 `x_perlin_init`——**每个 Perlin 消耗 3 次 next_double（各 1 个 next_long 输出）+ 256 次 next_int(256-i) 洗牌**（Fisher-Yates 填 257 字节置换表，idx[256]=idx[0]）。large 变体仅 T/H/C/E 四参数有独立 MD5 常量与八度参数（`_CLIMATE_LARGE`），SHIFT 与 WEIRDNESS 固定（biomenoise.c L854-899）；`large=True` 当前直接抛 ValueError（large biomes 暂不支持）。
3. **sampleBiomeNoise（`climate_point_xz(x, z, ny)`）**：shift 扰动 `px = x + sample_double_perlin(shift, x, 0.0, z) * 4.0`、`pz = z + sample_double_perlin(shift, z, x, 0.0) * 4.0`——**第二次 shift 调用传参 (z, x, 0)**，即 y=x、z=0（biomenoise.c L1156-1157 语义）；随后 C/E/W 在 `(px, 0.0, pz)` 采样（气候采样恒 y=0，samplePerlin 走 yamp=0 路径：d2==0 时用初始化时预存的 h2/d2/t2）；depth：`ridge = -3.0 * (|(|w| - 0.6666667)| - 0.33333334)`（fabsf/减法/乘法全程 float32），`off = get_spline(主样条, (c, e, ridge, w)) + 0.015`（0.015F 先提升为 double），`d = 1.0 - ny*4/128.0 - 83.0/160.0 + off`；T/H 采样；最后每参数 `quant(v) = int(np.float32(10000.0F * v))` 得 6 元组 `(t, h, c, e, d, w)` 的 int64 量化 np 值。`climate_point(x, y, z)` 是其别名封装（ny 即 y）。
4. **depth 样条**：`_build_splines` 照抄 initBiomeNoise 与四个构建函数（`create_spline_38219` / `create_flat_offset_spline` / `create_land_spline` / `_get_offset_value`），节点表示 `("fix", val)`（常量叶）或 `(typ, [(loc, val, der), ...])`（分段表，typ ∈ 大陆性/侵蚀/山脊/奇异性），全程 float32；结果缓存在模块级 `_SPLINE_ROOT`（首次调用构建，之后复用）。`get_spline` 递归求值：中间运算 float32，最终插值 `r = lerp(k, n, o) + k*(1-k)*lerp(k, p, q)` 为 double 函数（rng.h lerp 是 double，C 编译器把参数提升为 double），但 `k*(1.0F-k)` 是 float 域乘法。
5. **climateToBiome（btree 最近邻搜索）**：`climate_to_biome(np6, btree)` → `_resulting_node(np6, bt, 0, 0, 2^64-1, 0)` 从根递归——`_get_np_dist` 按节点 64 位编码的低 48 位取 6 个参数盒索引（每参数 8 位，`param[pidx]` 为 (lo, hi)），计算参数盒到 np6 的平方距离（uint64 算术不溢出，盒外取轴向距离、盒内为 0）；`_resulting_node` 沿 `steps[depth]` 步进遍历 `order` 个子节点，维护当前最优 (leaf, ds)；返回最近叶节点，`(nodes[idx] >> 48) & 0xFF` 即群系 id。另有 `climate_to_biome_dat(np6, bt, dat)`：MC-241546 的 dat 共享路径——以上一次搜索的终点节点作为 alt 初始值并以该节点距离初始化 ds（剪枝下界），跨格链式传递，供 structure_map 大图采样加速。
6. **顶层查询**：`BiomeSampler.biome_at(x, y, z)` = `climate_to_biome(climate_point(x, y, z))`，输入 1:4 噪声格坐标，返回群系 id。

### 逆函数（测试/考证用）

- `splitmix64` / `splitmix64_inverse`：SplitMix64 正向与逆向（完全可逆；`_mul_inv` 用 Newton-Raphson 迭代求模 2^64 乘法逆元）。
- `x_set_seed` / `x_set_seed_inverse`：xSetSeed 逆向——由最终 (lo, hi) 恢复世界种子；lo/hi 侧各自逆序撤 `^>>31`、乘 B、`^>>27`、乘 A、`^>>30`，`hi -= lo` 撤 `h = l + XL`，`lo ^ XH` 即原种子；`^>>k` 的逆是多项式迭代 `_xor_shift_inv`（`x = y ^ (y>>k) ^ (y>>2k) ^ ...`），单次异或不够。

### 群系 id / 名称表

- `BIOME_ID`：1.18+ 主世界 1:4 可出现集合（ocean=0、plains=1、……、pale_garden=186）；26.2 `sulfur_caves=187` 为 MCHelper 封闭系统自定编码（官方 187 被其他 id 占用，btree262 叶编码与此表自洽）；`gravelly_mountains` 与 `windswept_gravelly_hills` 同为 131。
- `BIOME_NAME_ZH`：中文显示名；`_F3_ALIASES`：F3 调试屏旧名归一（如 snowy_tundra/ice_plains→snowy_plains、mesa→badlands、jungle_edge→sparse_jungle）；`_ZH_ALIASES`：中文俗称（雪原/平顶山/滴水石/苍园等）。
- `biome_key_to_id`（英文键含别名）、`biome_display_name`（键/id → 中文显示名）、`resolve_biome_input`（用户输入解析链：纯数字 id → 中文精确 → 中文名反查 → 英文键/别名 → 子串模糊匹配）、`block_to_noise(v)`（方块 → 噪声格，`>> 2`）。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `BTree` | `class(name, order, steps, param, nodes)` | 一个版本的群系树（最近邻搜索数据），`__slots__` 五字段，数组统一转 numpy dtype |
| `_load_btree` | `(name: str) -> BTree` | 从 npz 惰性加载一个 btree 并缓存（`_BTREES`） |
| `get_btree` | `(version_key: str) -> BTree` | 版本键校验 + 取 btree（不支持抛 ValueError） |
| `_rotl64` / `_rotr64` | `(x: int, k: int) -> int` | 64 位循环左移/右移 |
| `_mul_inv` | `(a: int) -> int` | 模 2^64 乘法逆元（Newton-Raphson，6 轮收敛） |
| `splitmix64` / `splitmix64_inverse` | `(x: int) -> int` | SplitMix64 正向/逆向（xSetSeed 内部管线等价物） |
| `x_set_seed` | `(value: int) -> tuple[int, int]` | rng.h xSetSeed：世界种子 → Xoroshiro 初始状态 (lo, hi) |
| `_xor_shift_inv` | `(y: int, k: int) -> int` | 逆 `x ^= x >> k` 的多项式迭代 |
| `x_set_seed_inverse` / `x_set_seed_inverse_world` | `((lo, hi)) -> int` | xSetSeed 逆向：由最终状态恢复世界种子（后者为元组入参的等价封装，供测试） |
| `Xoroshiro` | `class(lo, hi)` | 可变状态 Xoroshiro128+。`from_seed`（经 x_set_seed）；`next_long`：`n = rotl64((l+h)&M64, 17) + l`，状态更新 `h ^= l; lo = rotl64(l,49) ^ h ^ ((h<<21)&M64); hi = rotl64(h,28)`；`next_int(n)`：32 位乘法高位 + Lemon 风格拒绝采样（threshold = `((~n+1)&0xFFFFFFFF) % n`，`(r & 0xFFFFFFFF) < threshold` 则重取）；`next_double`：`(next_long() >> 11) * 2^-53` |
| `x_next_double` / `x_next_long_state` | 模块级函数 | nextDouble 的模块级封装 / 无状态版 xNextLong（返回 (输出, 新 lo, 新 hi)） |
| `Perlin` | `class` | 单个 Perlin 八度（257 字节置换表 d + 预计算 a/b/c 偏移与 h2/d2/t2） |
| `x_perlin_init` | `(xr: Xoroshiro) -> Perlin` | 3 次 next_double 偏移 + Fisher-Yates 256 次洗牌（消耗 256 次 next_int） |
| `_indexed_lerp` | `(idx, a, b, c) -> float` | noise.c indexedLerp（16 项梯度点积表） |
| `sample_perlin` | `(p, d1, d2, d3) -> float` | noise.c samplePerlin（yamp=0 路径）；三轴 smoothstep（t = d³(d(6d−15)+10)）+ 8 角梯度三次插值 |
| `OctaveNoise` / `x_octave_init` | `(xr, amplitudes, omin) -> OctaveNoise` | 消耗 2 次 next_long 得参数级状态；幅值非零八度各用 md5("octave_-N") 异或派生 Xoroshiro 建 Perlin，附 (amplitude, lacunarity) |
| `sample_octave` | `(octn, x, y, z) -> float` | 逐八度 `amp * sample_perlin(p, x*lac, y*lac, z*lac)` 累加（maintainPrecision 为恒等） |
| `DoublePerlin` / `x_double_perlin_init` / `sample_double_perlin` | — | 两组八度 + 幅值归一（AMP_INI[有效长度]）；采样 `v = octA(x,y,z) + octB(x*f, y*f, z*f)`，f = 337/331，全程 double |
| `_f32` / `_get_offset_value` | — | float32 截断助手 / biomenoise.c getOffsetValue 复刻 |
| `_build_splines` / `_spline_root` | `() -> spline` | 照抄 initBiomeNoise 构建大陆性主样条（含嵌套 land/flat/ridges 样条）；模块级惰性缓存 |
| `_lerp_f32` / `get_spline` | `(sp, vals) -> np.float32` | biomenoise.c getSpline：递归多维样条求值（精度规则见上） |
| `BiomeSampler` | `class(seed, version_key="1.21", large=False)` | 单个世界种子的 1.18+ 主世界群系采样器（等价 setBiomeSeed + 采样）。`__init__` 建参数级种子与 6 个 DoublePerlin；`climate_point(x,y,z)` / `climate_point_xz(x,z,ny)` 采样 6 参数 np 量化值；`biome_at(x,y,z)` 返回群系 id |
| `_get_np_dist` | `(np6, bt, idx) -> int` | 节点 idx 参数盒到 np6 的平方距离（uint64） |
| `_resulting_node` | `(np6, bt, idx, alt, ds, depth) -> int` | btree 递归最近邻搜索（steps 步进 + order 分支遍历） |
| `climate_to_biome` | `(np6, bt: BTree) -> int` | climateToBiome（dat=NULL 路径）：根起搜索，`(nodes[idx] >> 48) & 0xFF` 为群系 id |
| `climate_to_biome_dat` | `(np6, bt, dat) -> tuple[int, int]` | MC-241546 dat 共享路径：alt/ds 链式传递，返回 (idx, 新 dat) |
| `biome_key_to_id` / `biome_display_name` / `resolve_biome_input` | `(str|id) -> id|str` | 群系键/显示名/用户输入 ↔ id（含别名与模糊匹配） |
| `block_to_noise` | `(v: int) -> int` | 方块坐标 → 噪声格坐标（1:4，`>> 2`） |

**接口**：

- 包内：`Utils/SeedReverser/world_seed_refine.py` import `BiomeSampler` / `block_to_noise` / `VERSION_TO_BTREE` / `get_btree` / `_load_btree`。
- 跨域复用：
  - `Utils/MapPreviewer/map_sampler.py`（MapPreviewer 主世界群系地图渲染）import `BiomeSampler` / `climate_to_biome` / `VERSION_TO_BTREE` / `_load_btree`——逐格采样画图；
  - `Utils/Public/structure_map.py`（公共种子地图模块）import `BiomeSampler` / `Xoroshiro` / `climate_to_biome_dat`（dat 路径用于大图连续采样提速）。
- 对外提供：世界种子 → 任意 1:4 噪声格群系 id 的完整查询链（含输入归一化、中文名、F3 别名），以及 SplitMix64/xSetSeed 的正逆函数（考证与回归测试用）。

**关键变量/常量**：

| 名称 | 值/形态 | 语义 |
|---|---|---|
| `VERSION_TO_BTREE` | dict | 版本键 → btree 表名（1.21/1.21.11→btree21wd，26.2→btree262） |
| `_BTREE_FILE` | 路径 | `btree_tables.npz` 绝对路径（与本模块同目录） |
| `_BTREES` | dict | 模块级 btree 缓存（每版本仅加载一次 npz） |
| `_M64` | `(1 << 64) - 1` | 64 位掩码 |
| `_XL` | `0x9E3779B97F4A7C15` | 黄金比率 gamma（SplitMix64 步进；含断言核对） |
| `_XH` | `0x6A09E667F3BCC909` | md5 待定常量（xSetSeed 初值异或） |
| `_MUL_A` / `_MUL_B` | `0xBF58476D1CE4E5B9` / `0x94D049BB133111EB` | SplitMix64/xSetSeed 的两次混合乘子 |
| `MD5_OCTAVE_N` | 13 元常量元组 | md5("octave_-12") … md5("octave_0") 的 (lo, hi) 对（noise.c L394-415） |
| `LACUNA_INI` / `PERSIST_INI` / `AMP_INI` | 常量元组 | 八度 lacunarity（2^omin 起）/ persistence（(2^len−1)/2^len 型）/ 修零后归一化幅值 |
| `NP_TEMPERATURE`…`NP_MAX` | 0…6 | 气候参数索引（SHIFT=4 不是真气候参数，用于局部扰动） |
| `_CLIMATE_SMALL` / `_CLIMATE_LARGE` | dict | 各参数的 ((md5_lo, md5_hi), amplitudes, omin)；large 变体仅 T/H/C/E |
| `_SP_CONTINENTALNESS`… | 0…3 | 样条参数索引（大陆性/侵蚀/山脊/奇异性） |
| `_SPLINE_ROOT` | 模块级缓存 | depth 主样条（首次调用构建） |
| `BIOME_ID` / `BIOME_NAME_ZH` / `_F3_ALIASES` / `_ZH_ALIASES` | dict | 群系 id 表 / 中文名 / F3 旧名归一 / 中文俗称 |

---

## `Utils/SeedReverser/world_seed_refine.py`（270 行）

**功能**：世界种子精化（SeedReverser 二期·路线 A）。一期 `solve_structure_seeds` 输出的候选是 64 位世界种子的**低 48 位**（结构种）；本模块用群系观测点**枚举高 16 位**恢复完整世界种子：`worldSeed = (high16 << 48) | s48`，high16 ∈ [0, 2^16)。判定方法（群系二次校验）：每个高位候选与 s48 拼出 64 位种子，用 `biome_noise.BiomeSampler`（已与 cubiomes 45/45 对拍通过）在**全部**群系观测点采样，全部一致才通过。

流程（`refine_world_seeds`）：

1. **入口校验**：候选非空；观测点 ≥ `MIN_OBS = 7`（依据：主世界 1:4 噪声格上不同群系组合数有限（约 2^14），观测点少于 7 个时判别力上限（2^-7 相对 2^16 枚举空间）不足以保证唯一解；仅做下限校验，不强推观测点多样性）。
2. **候选归一化**：`int(c) & mask48` 截断到 48 位（结构种语义）并去重保序。
3. **观测点预处理**：`nx = block_to_noise(x)`、`nz = block_to_noise(z)`（方块坐标 `>> 2` 换算，与游戏 F3 群系判定一致）；`y` 可选（方块 Y `>> 2`；带 y 可区分地表与洞穴群系——繁茂/溶洞等在深层大面积判定，不带 y 会误判），缺省 `ny = 0`（深层噪声层，旧行为）。
4. **版本校验**：`get_btree(version_key)` 先行（不支持的版本抛友好 ValueError）；`btree_name = VERSION_TO_BTREE[version_key]`。
5. **native 路径（默认）**：`_ensure_native_btree` 把该版本 btree 数据推入 C++ 扩展（`set_btree(btree_name, steps(uint32), param(int64), nodes(uint64), order)`，每版本仅首次，`_NATIVE_BTREES` 集合去重）→ `_biome_refine.refine_full(cands, obs_dicts, btree_name, high_span, on_progress, check_cancel)` 多线程枚举（obs_dict 形如 `{nx, nz, y, biome_id}`）；C++ 端以无符号位模式返回 uint64 数组，统一 `_to_signed64` 转有符号 int64（`(high<<48)|s48` 可能 ≥ 2^63，避免下游 Qt 信号与 UI 显示把大种子钳成 -1；与游戏 /seed、F3 显示一致）。C++ 端取消标志不回传，取消后复查 `cancel()` 状态。**任何异常**（未知 btree/数据异常等）打印一行诊断到 stderr 后降级纯 Python（原先静默吞掉会让「极慢」无从排查）。
6. **纯 Python 路径**：对每个候选 s48，枚举 `high ∈ [0, high_span)`：`seed = (high << 48) | s48`（≥2^63 时减 2^64 转有符号，同 native）→ 每个高位候选**新建一个 `BiomeSampler(seed, version_key)`**（每候选重跑 xSetSeed + 2 次 next_long + 6 个气候 DoublePerlin 派生——枚举成本主要在噪声采样而非 LCG）→ `all(sampler.biome_at(nx, ny, nz) == bid for ...)` → 命中即收集。
7. **进度与取消**：进度回调节流为每 64 个高位步一次（`_PROGRESS_MASK = 0x3F`），另有开始、候选切换（「候选 {s48} 完成」）与结束时的即时回调；取消检查在候选间与高位步进间两处。回调异常一律吞掉（不中断计算）。
8. **返回**：`{"world_seeds": [...], "stages": {"candidates", "high_span", "enum_total", "enum_done", "hits", "elapsed", "engine"("native"|"python")}, "cancelled": bool}`；取消时 enum_done < enum_total。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_to_signed64` | `(x: int) -> int` | 无符号 64 位种子值 → 有符号 int64（≥2^63 映射为负；对外统一表示） |
| `_ensure_native_btree` | `(btree_name: str) -> None` | 把指定版本 btree（steps/param/nodes/order，均 ascontiguousarray）推入 native 扩展，每版本仅首次 |
| `_refine_native` | `(cands, obs_list, btree_name, on_progress, cancel, high_span) -> list[int]` | native 路径：组装 obs_dicts → `_biome_refine.refine_full` → 结果统一转有符号；扩展缺失抛 RuntimeError 由调用方降级 |
| `_check_cancel` | `(cancel) -> bool` | cancel 为可调用对象时执行并转 bool；None/不可调用返回 False |
| `refine_world_seeds` | `(candidates, biome_obs, version_key="1.21", on_progress=None, cancel=None, high_limit=None) -> dict` | 主入口：48 位候选 + 群系观测 → 枚举高 16 位 → 全部通过观测验证的 64 位世界种子（流程见上）；`high_limit` 供调试/快速验证只枚举部分高位 |

**接口**：

- `Threads/task_WorldSeedRefine.py` import `refine_world_seeds`（后台计算线程）。
- 对外提供：结构种候选 + 群系观测点 → 完整 64 位世界种子的二期精化入口（SeedReverser 一期与二期的衔接层）。

**关键变量/常量**：

| 名称 | 值 | 语义 |
|---|---|---|
| `_native_ext` | `_biome_refine` 模块或 `None` | C++ 精化扩展引用；导入期 ImportError 及扩展自身异常一律降级 |
| `_NATIVE_BTREES` | `set[str]` | 已推入 native 的 btree 版本名集合（避免每次调用重复推数据） |
| `MIN_OBS` | `7` | 群系观测点数量下限（判别力论证见上） |
| `_PROGRESS_MASK` | `0x3F` | 进度回调节流掩码（每 64 个高位步触发一次） |
| `_U64_MASK` / `_S63_SIGN` | `(1<<64)-1` / `1<<63` | 有符号/无符号 64 位转换助手 |

---

## `Utils/SeedReverser/_native/build_biome.py`（68 行，简要）

**功能**：构建 SeedReverser 二期世界种子精化扩展：用 MSVC `cl.exe` 直接编译同目录 `_biome_refine.cpp` → `_biome_refine.pyd`（pybind11 扩展，不依赖 setuptools）。产物缺失或加载失败时 `world_seed_refine.py` 自动降级纯 Python 路径。

**要点**：编译参数 `/nologo /std:c++20 /utf-8 /O2 /EHsc /MD /LD`，include 路径为 pybind11 与 Python 头文件（`sysconfig.get_paths()["include"]`）；链接 `/LIBPATH:{sys.base_prefix}/libs python313.lib`（注释说明：sysconfig 的 nt 方案无 "libs" 键，python313.lib 位于安装根的 libs/ 下；`/MD` 与官方 Python 发行版运行时一致，vcruntime 由 python313.dll 提供）。编译输出（stdout+stderr）写入 `_build_biome_log.txt`。退出码：0 成功（且 .pyd 存在）、2 源文件缺失或「编译器返回 0 但未找到 .pyd」、其余为编译器返回码。环境要求：cl.exe 在 PATH（建议 "x64 Native Tools Command Prompt for VS"）、venv 已装 pybind11。

**类与函数**：仅 `main() -> int`（组装 cl 命令行 → subprocess 执行 → 写日志 → 校验产物）。

## `Utils/SeedReverser/_native/build_native.py`（69 行，简要）

**功能**：构建 SeedReverser 的 C++ 层 2 扩展：编译同目录 `_solver_native.cpp` → `_solver_native.pyd`（structure_math 层 2 的多线程批量验证扩展）。构建失败时 `structure_math.py` 自动降级 numpy 路径，不影响工具可用性。

**要点**：与 build_biome.py 结构完全相同（同样的 FLAGS/LINK/日志 `_build_log.txt`/退出码约定/环境要求），仅目标源文件与产物不同。两脚本均可在项目根目录或任意目录运行：`python Utils/SeedReverser/_native/build_native.py`、`python Utils/SeedReverser/_native/build_biome.py`。

**类与函数**：仅 `main() -> int`。

# 8. 结构模型与渲染（Utils/SeedReverser · 引擎）

# 结构引擎模块文档（08a）：structure_models + jigsaw_assembly

> 依据源码精读整理，覆盖 MCHelper 中结构体素建模与 jigsaw 拼装两大引擎。
> 生成日期：2026-09-23。所有信息均来自源码，未做臆测；行号以当前文件为准。

---

## `Utils/SeedReverser/structure_models.py`

实际 3305 行。无自定义类，全部以模块级函数 + 常量表组织。

**功能**：SeedReverser 结构 3D 模型构建层——把各类结构键（structure key）统一转换为体素字典 `{(x,y,z): mat}`，再网格化为 GPU 可直接上传的绘制数据。坐标约定：x 西→东、z 北→南、y 向上，`(0,0,0)` = 结构包围盒西北角底部 = cubiomes 生成锚点。体素值有两种形态：纯字符串 `mat`（整格方块）；`(mat, shape)` 二元组（带形状码的非完整方块：半砖/楼梯/门/活板门/栅栏/墙/玻璃板/铁栏杆/链/火把/箱子/床等，shape 语义由 `block_shapes`（别名 `bs`）按 palette Properties 驱动）。实现原理按结构键来源分四条管线：

1. **NBT 模板解析（8 键）**：`parse_nbt` 为纯 Python 自实现的 NBT 解析器（gzip 解压 + 13 种标签递归解析，compound 用 dict、list 用 `(elem_type, [values])` 元组表示）。`_voxels_from_template_file` 读取 `assets/SeedReverser/templates/*.nbt`（文件名 `__` = 原路径分隔符），先解析 palette 条目（`Name` + `Properties`），每个条目经 `_map_block`（查 `_MAT_MAP`，slab 的 `type=top/double` 按 `mode="full"` 去 `halfheight:` 前缀）与 `bs.shape_from_props`（Properties → 形状码）生成 `mats[state]` 映射表；旧式 `halfheight:` 前缀材质若无 properties 形状则归一化为 `SHAPE_SLAB_BOT`（top 半砖按官方几何画上半砖，修复旧逻辑误画整块）。再遍历 `blocks` 列表（`pos` 为 TAG_List 元组 `(9,[x,y,z])`、`state` 为 palette 索引），None 跳过、索引越界回退 `UNKNOWN_MAT`。兼容单 palette（`root["palette"]`）与多 palette 随机变体（`root["palettes"]`，取第一个变体，如沉船）。
2. **蓝图挤出（1 键：jungle_temple）**：`_voxels_from_blueprint` 取 `structure_blueprints.blueprint(key)` 的 `top`（base36 高度图）+ `tcol`（最高层调色板字符）+ `palette`（人话名），每格从 y=1..h 向上挤出柱体；人话名经 `_norm_block_name`（去 `entitysprite:` 前缀、去 `-rotNNN` 后缀）归一化后直接作为纹理键，并用 `TEX_DIR` 下 PNG 是否存在校验（缺失回退 `UNKNOWN_MAT`）；调色板名含 slab/stairs 打 `halfheight:` 前缀、carpet 走 `SHAPE_CARPET`。jungle_temple 随后追加确定性后处理：`_mossify_jungle`（圆石 50% 换苔石，随机源 `_rng(key)` = `random.Random("mchelper:{key}")` 可复现）与 `_carve_jungle_temple`（南面正中 2 宽 2 高门洞 y1..2、x7..8、z9..12 穿透三层外墙，雕刻在苔化之后保证门洞边缘材质分布一致）。
3. **程序化合成（5 键）**：`_PROC_BUILDERS` 分发表按原版形体规则合成——monument（58x58 基座 + 23 根 2x2 错列巨柱 y-8..-1 + 中央主体 23x22 + 前部高塔含南面 3x3 主入口与 penthouse 海晶灯顶 + 东西两翼及翼顶小塔 + 金块藏宝室示意）、swamp_hut（4 根橡木桩架空的 5x6 云杉板小屋 + 南门前平台 + 炼药锅/工作台）、village（中央水井：圆石框+砾石示意水+四角原木柱+石砖檐口顶盖；四角复用真实模板 `village__plains__houses__plains_medium_house_1.nbt` 平移拼入，整体 54x40）、trial_chambers（40x40x20 全封闭凝灰岩砖箱体 + 中央决斗室 + 三层柱廊 + 外墙铜格栅饰带 + 四角氧化铜方柱）、desert_pyramid（wiki 逐层蓝图数据驱动：`_DESERT_LAYERS` 存层号 -14..10 共 22 层 21x21 字符画，`_DESERT_CHAR_MAT` 字符→纹理键；羊毛字符按 wiki 生成规则替换——W=塌顶 25 块按 `(x*7+z*13)%3` 确定性 33% 砂岩/67% 沙、G=沙/砂岩互斥对不建、R=暗室埋沙 83 块→sand；含地下暗室 TNT9/箱4/压力板1）。
4. **WorldEdit .schem（Sponge Schematic v2/v3，3 键）**：`_voxels_from_schem_file` 兼容 v2 平铺字段与 v3 `root["Schematic"]["Blocks"]` 收纳布局；方块数据为 YZX 顺序 varint palette 索引（`_read_schem_varint`：1..3 字节小端 7 位组，最大 21 位，-1 按 21 位补码解出 `0x1FFFFF` 自然查表跳过）；palette 名 `minecraft:xxx[k=v,...]` 由 `_schem_base_and_type` 拆基名与 props；`_MAT_MAP=None` 与 `_SCHEM_ENV_FILTER` 命名方块不保留也不参与包围盒；最后把保留体素的最小角平移到 `(0,0,0)`（框选"宁大勿小"混入的纯空边经重定基剔除）。文件存在时优先于程序化结果，缺失回退。

**build_mesh 网格化流程**：把体素字典转为 `{"verts", "idx", "slots", "slot_mat", "quad_slot", "water_off", "water_count", "chunks", "occl"}`。要点：
- **形状感知面剔除**：面剔除采用"共面 + 投影覆盖"精确判据（`_rect` 投影 + `_covered` 覆盖判定，容差 1e-9）——只有本 AABB 贴格界、且邻居在同格界处有贴界面完全遮盖本面投影时才剔（修复半砖/楼梯下方看穿）；同方块内其他 AABB 同侧同平面完全覆盖时剔小面（内容相等者除外，避免完全重合面互剔全光）；透明材质 `_TRANSPARENT_MATS` 异材不剔（透过水/玻璃/冰可见）；ladder 作为邻居时不剔所贴墙面（否则梯子看似悬空）。
- **性能优化**：体素值级缓存（`_mat_shape` 归一化、基础 AABB、邻居贴界面矩形，键均为可哈希体素值）；整格实心体素若六邻全为整格实心非透明则整体跳过（bastion 实测 ~60% 命中，面迭代 -60%）；post/pane/wall 连通臂随邻居变化逐位现算（`_boxes_with_arms` 用 `bs.connect_kind`/`bs.connect_arms`）。
- **特殊形状路径**：plant（SHAPE_PLANT）走 `_PLANT_QUADS` 对角 X 四 quad 专用路径（绕序 CCW 正面、法线 (0,0,±1)、UV 世界平铺）；活塞头轴盒端面官方无 faces → `_SKIP_FACE` 哨兵完全不 emit。
- **面级纹理分流**：每面经 `_face_mat`（→ 尾部委托 `_decor_face_mat`）返回 `(纹理键, rect)`：箱子（单箱朝向面基键 / 大箱左右半按 `big_end=((typ=="left")==(f in("n","e")))` 取半窗合成图）、barrel（顶/底专用图）、`col:<axis>`（`_COL_ENDS` 轴端面，原木年轮/玄武岩顶）、`fc:<f>[:lit]`（`_FC_FACES` 炉族前脸/亮前脸/竖直前脸）、`_FULL_FACES` 整格分面（草方块/书架/耕地等独立顶底图）、crafting table 特例（无朝向属性，north/west 固定前脸）、bell/composter 按盒特征（box 参数）区分柱/梁/钟体与壁/底板；装饰族（torch 三级台阶段、lantern 顶盖/主体、erod 底座/杆、brewing 三分窗、bed 枕带分区窗含 e/w swap、dhead 龙首 5 面、wsign 板盒正面窗、pist/pisth、candle、flowerpot、sculk、repeater/comparator、lamp、rswire）全部按官方模型 JSON uv 像素窗换算（`_RU`/`_RS`：up 面 v=(1-b,1-d)、down/侧面 v=(1-d,1-b)，u=(a,c)，像素/16 归一化）。
- **输出组织**：同材质面聚合为绘制槽（slots = `(idx_start, idx_count)` 区间 + `slot_mat`），未知材质单独成槽（视口回退灰色）；水槽不注册常规槽、索引强制垫到尾部（`water_off/water_count`，视口半透明第二遍绘制；字母序下 water 插中部会让 quad_slot 物理对位错位，如 trial 的 water<white bed）；quad 按 16³ chunk 分桶重排（排序键 = chunk 首现序：`np.unique` + `np.argsort(first)` + `np.searchsorted` 稳定排序，chunk 序号与遮挡域共用一套物理序）；每 chunk AABB 由 quad 4 角顶点推出（必须取齐 4 角，两角会退化成一条线导致视锥剔除误删整 chunk）；每 quad 所在方块坐标（法线轴取朝面一侧 ceil-1/floor、其余轴 4 角 min floor，保证分桶与遮挡域体素格划分一致）；`quad_slot` 供烘焙，索引按总量选 uint16/uint32。
- **build_occlusion**：逐 16³ section 可见性矩阵，移植自 1.21.11 反编译源码（VisGraph.resolve + SectionCompiler.compile 同款，MC 洞穴剔除构建期算法）：opaque 格标阻挡 → 从 6 个外表面边缘空格 flood fill → 每空域记录接触到的外表面方向 → 6×6 bool 矩阵（36 位 int，`face_from*6+face_to` 位，同空域接触的两面互相可见）；特例 opaque<256 全 true、≥4096 全 false；方向用原版 `Direction.values()` 序 (0=-Y,1=+Y,2=-Z,3=+Z,4=-X,5=+X)；输出附 `chunk_at`（section 键 → chunks 列表下标，键用"面所属格"而非 AABB min，避免跨层平面 quad 抢注键导致室内成片缺渲染）。

**缓存机制**：两层。① `build_model` 层：模块级单条缓存 `_CACHE = {"key": None, "model": None}` + `threading.Lock`（`_CACHE_LOCK`），键 `(key, variant)`，切换零成本复用，返回 `{"key","variant","voxels","size","mesh","tex_keys"}`；② jigsaw_assembly 侧模板/池缓存独立（见下节）。另 `pool_max_yspan` 等在各自对象上缓存。

**_MAT_MAP 材质键映射组织**：键 = `minecraft:` 方块名，值 = 纹理文件键（`assets/SeedReverser/textures/block/<键>.png`）、`halfheight:` 前缀（半高块）或 `None`（非实体/透明直接跳过）；未收录回退 `UNKNOWN_MAT`（视口中性灰）。按方块族组织（含 2026-09 多轮材质适配注释）：
- **石材**：stone/bedrock/deepslate 系；黑石/玄武岩系（bastion 主体，basalt 端面经 `_COL_ENDS`、轴向经 `col:<axis>` 几何/分面联动）；深板岩砖/瓦及其裂纹/錾制变体（古城）；凝灰岩系（试炼密室，三轮补映射由 `_map_block` hook 实证 481 格回退 UNKNOWN_MAT 后补齐）；安山岩/闪长岩/花岗岩（未磨制映射到磨制纹理）。
- **石材楼梯/台阶/墙**：楼梯与台阶统一 `halfheight:<族基键>`（半高复用整块纹理，与 polished blackstone 系同式）；墙映射回族基键整块。
- **土/砂**：dirt/coarse_dirt/podzol/grass_block/dirt_path/farmland/gravel（含 suspicious_*）/sand 系（红沙映射 sand）/sandstone 四态。
- **木质**：八木系 planks/log（stripped_wood 映射 log）/stairs/slab/fence/trapdoor/door（门基键 = 下半块纹理 `xxx door bottom`，上半块由 `_mat_shape` 按 `door:u:` 形状码换 `xxx door top`——行 279 注释提及的 `_DOOR_PART_TEX` 实际不存在，为注释遗留）；bookshelf/lectern/loom 等映射橡木板。
- **功能方块**：chest/trapped_chest/ender_chest/barrel/熔炉族（furnace/blast_furnace/smoker/dispenser/dropper→dispenser 纹理）/crafting_table/brewing_stand/cauldron 四态/tnt；**结构方块族（jigsaw/jigsaw_block/structure_block）= None 剔除**（世界生成时消耗不落地的占位标记，用户需求删除所有模型中的结构方块）。
- **灯具/红石**：torch/wall_torch/soul 系/lantern/sea lantern/redstone_torch/repeater/comparator/lever/redstone lamp/redstone wire（自制染色十字图，世界平铺 UV 命中线带）。
- **海底神殿**：prismarine 三态统一、湿海绵→sea lantern（无海绵纹理取最近似发光块）、magma。
- **染色/装饰**：陶瓦/釉面陶瓦→同色羊毛、羊毛/地毯同色同键、床 16 色、横幅（gray/white/brown→ominous wall banner；magenta→magenta_wool 末地城纯色布）、盆栽→potted cactus 合成图近似。
- **铜系（试炼密室）**：copper/oxidized/chiseled/grate/bulb/door/trapdoor 全量真实纹理，waxed_* 共用未涂蜡纹理。
- **古城专区**：幽匿系（sculk/sculk_catalyst/sculk_sensor 真实纹理）、cobbled deepslate 半高族、iron trapdoor/note block/snow（雪层半高近似）/campfire（熄灭原木半高，lit 两态不区分）/skeleton_skull（骨块半高近似，无独立 block 纹理）/soul_fire（透明十字火焰）。
- **村庄专区**：金合欢系全量（planks/log/stairs/slab/fence/fence_gate/pressure_plate/door/sapling，栅栏块模型 = planks 纹理）、作物（wheat/carrots/potatoes/beetroots 静态兑底 + `crop_stage_mat` 动态 age 接管）、工作方块（cartography/fletching/smithing/stonecutter，side 基键 + `_FULL_FACES` 顶面）、植物花草（poppy/dandelion/oxeye daisy/short_grass/tall grass/fern/dead bush 十字）、bell（floor/ceiling 真模型分面）、melon/pumpkin/clay/cactus/玻璃板染色系。
- **末地城**：end_stone_bricks/purpur 系（purpur_stairs/slab → halfheight:purpur_block）、end_rod（官方模型底座 2/16 + 立杆，`bar:y` 近似）。
- **非实体/透明**：air 三态/light/barrier/structure_void/moving_piston、水保留材质键（视口半透明）、lava 不透明绘制（与水同格时在 build_mesh 让位于水）、树叶带透明孔 discard 镂空、部分细杆/按钮/铁轨/蘑菇杆 None。

**TEMPLATE_DIR/TEX_DIR/SCHEM_FILES 资源定位**：`_ROOT` = `Utils/SeedReverser/` 上两级 = 项目根；`TEMPLATE_DIR` = `assets/SeedReverser/templates`；`TEX_DIR` = `assets/SeedReverser/textures/block`；`SCHEM_DIR` = `assets/SeedReverser/schematics`（`SCHEM_FILES` 3 键 village/monument/trial_chambers）。

### 类与函数

| 名称 | 签名 | 说明 |
|---|---|---|
| `parse_nbt` | `parse_nbt(data: bytes) -> dict` | 解析 gzip 压缩的结构模板 NBT，返回 root compound（dict）。校验根为 TAG_Compound、跳过根名后交 `_read_payload`；未知标签抛 ValueError。 |
| `_read_payload` | `_read_payload(data: bytes, pos: int, tag: int)` | NBT 载荷递归解析：数值型 struct 大端解包；BYTEARR/STRING 带长度前缀；LIST 返回 `(elem_type, [values])`（空列表 elem_type=TAG_END）；COMPOUND 循环读 `(type, name, payload)` 直至 TAG_END；INTARR/LONGARR 一次性 unpack。 |
| `_palette_entry_name` | `_palette_entry_name(entry) -> str` | palette 条目（dict，值为裸类型）→ `Name` 方块名；非 dict/非 str 返回空串。 |
| `_palette_entry_half` | `_palette_entry_half(entry) -> str` | palette 条目的 slab `type` 属性：`'bottom'/'top'/'double'/''`。 |
| `_palette_entry_props` | `_palette_entry_props(entry) -> dict` | palette 条目的 `Properties` dict（无则空 dict）。 |
| `_voxels_from_template_file` | `_voxels_from_template_file(path: str) -> dict` | 单模板 NBT → 体素 dict。流程：parse_nbt → 取 palette（兼容 palettes 多变体取第一变体）→ 逐条目 `_map_block` + `bs.shape_from_props` 生成 mats 表（halfheight: 前缀归一化为形状码，无形状旧前缀按 `SHAPE_SLAB_BOT`）→ 遍历 blocks 按 state 取材质写入 `vox[(x,y,z)]`（None 跳过、越界回退 UNKNOWN_MAT）。 |
| `crop_stage_mat` | `crop_stage_mat(name: str, props: dict \| None) -> str \| None` | 作物方块 → 按 `age` 属性的动态纹理键（非作物返回 None）。`_CROP_STAGES` 定义各作物的阶段纹理前缀与 age 折叠表（carrots/potatoes 四纹理对 age 0..7 折叠；beetroots 一对一）；age 缺省 0、越界钳制；调用方优先于 `_map_block` 静态映射。 |
| `_map_block` | `_map_block(name: str, mode: str) -> str \| None` | NBT 方块名 → 材质键。`_MAT_MAP` 查表（缺省 UNKNOWN_MAT）；`mode="full"`（top/double 台阶）去 `halfheight:` 前缀按整块，`mode="half"` 保持原样。 |
| `_schem_base_and_type` | `_schem_base_and_type(name: str) -> tuple` | Sponge palette 名 `"minecraft:xxx[k=v,...]"` → (基名, props dict)。 |
| `_read_schem_varint` | `_read_schem_varint(data: bytes, pos: int) -> tuple` | Sponge BlockData varint：1..3 字节小端 7 位组（最大 21 位）；-1 按 21 位补码解出 0x1FFFFF，不可能是合法 palette 索引，查表自然跳过；截断抛 ValueError。 |
| `_voxels_from_schem_file` | `_voxels_from_schem_file(path: str) -> dict` | Sponge Schematic → 体素 dict。v2/v3 双兼容取 BlockData/Palette；按 YZX 序解 varint 索引写入体素；环境过滤 + None 跳过；末尾把最小角平移为 (0,0,0)（重定基到结构本体包围盒西北角 = cubiomes 锚点）。 |
| `_norm_block_name` | `_norm_block_name(name: str) -> str` | Wiki 人话名 → 纹理键：strip/lower、去 `entitysprite:` 前缀、去 `-rotNNN` 旋转后缀（与 structure_preview._norm_block 一致）。 |
| `_voxels_from_blueprint` | `_voxels_from_blueprint(key: str) -> dict` | 蓝图 top+tcol → 体素：每格按 top 字符（base36）从 y=1..h 挤出柱；tcol 字符查 palette 得人话名 → 纹理键（TEX_DIR 存在性校验）；slab/stairs 加 halfheight: 前缀、carpet 打 SHAPE_CARPET。 |
| `build_voxels` | `build_voxels(key: str, variant: int \| None = None) -> dict` | 统一入口：结构键 → 体素 dict。分发顺序：VARIANT_KEYS（variant=None 用 TEMPLATE_FILES 多文件拼接 / variant=i 用 VARIANT_FILES[i] 单独建模轮播）→ TEMPLATE_FILES（igloo 特例：三段 NBT 各自从 y=0 起，top/middle/bottom 顺序垂直向下堆叠 `dy -= h`，top 在地表地下室在下方负高度）→ EXTRUDE_KEYS（jungle_temple 附带苔化+雕刻）→ SCHEM_FILES（文件存在优先）→ PROCEDURAL_KEYS（`_PROC_BUILDERS`）→ 未知键抛 ValueError。 |
| `_rng` | `_rng(key: str) -> random.Random` | 结构键派生的确定性随机源（`random.Random(f"mchelper:{key}")`），同键结果可复现跨会话稳定。 |
| `_mossify_jungle` | `_mossify_jungle(vox: dict) -> None` | 丛林神庙：圆石按 50% 概率换苔石（原版均匀混合）。 |
| `_carve_jungle_temple` | `_carve_jungle_temple(vox: dict) -> None` | 丛林神庙：南面正中 2 宽 2 高门洞（y1..2、x7..8、z9..12）穿透三层外墙，y0 保留作门槛。 |
| `_voxels_desert_pyramid` | `_voxels_desert_pyramid() -> dict` | 沙漠神殿：wiki 逐层蓝图数据驱动重建（`_DESERT_LAYERS` 22 层 21x21 字符画）。G/空格跳过；W 塌顶 25 块确定性伪随机（`(x*7+z*13)%3==0` → sandstone 否则 sand）；R 埋沙→sand；其余查 `_DESERT_CHAR_MAT`；包围盒重定基后 21x21x25，含地下暗室与南门走廊。 |
| `_voxels_swamp_hut` | `_voxels_swamp_hut() -> dict` | 女巫小屋：内部 `box` 辅助函数填充——4 根橡木桩 y0..2 架空、云杉板地板 y3/墙 y4..5（北窗/南门洞 pop 出）、平顶 y6 满铺含四向出檐（出檐即包围盒）、炼药锅+工作台陈设。 |
| `_voxels_village` | `_voxels_village() -> dict` | 村庄：中央水井（圆石框 y0 + 中心砾石示意水 + 四角原木柱 y1..3 + 石砖檐口顶盖 y4/y5）+ 四角 4 栋 `plains_medium_house_1` 真实模板体素平移拼入（offsets (0,0)/(41,0)/(0,29)/(41,29)），整体 54x40。 |
| `_voxels_trial_chambers` | `_voxels_trial_chambers() -> dict` | 试炼密室：10 步流程——40x40x20 实心箱体 → 环状走廊空腔 → 决斗室内腔 → 三层楼板（y1 氧化铜走道 / y7/y13 凝灰岩砖）→ 决斗室磨制凝灰岩地面 → 四棵铜柱 → 顶嵌 3x3 铜灯 → 外墙铜格栅饰带 y9..10 → 四角 2x2 氧化铜方柱 → 走廊四边中点地嵌铜灯。 |
| `_voxels_monument` | `_voxels_monument() -> dict` | 海底神殿：23 根 2x2 巨柱错列网格（y-8..-1）→ 58x58 基座 y0 → 中央主体 23x22（x17..39,z18..39）挖殿堂空腔 → 前部高塔（x24..34,y1..21）挖入口大厅、南面 3x3 主入口、金块藏宝室 4x2x4、penthouse 空腔 + 海晶灯顶 → 东西两翼（高 8）挖大房间 + 翼顶 5x5 小塔。 |
| `model_size` | `model_size(vox: dict) -> tuple` | 体素 dict → 包围盒尺寸 (W, D, H)（x/z/y 方向跨度）；空模型 (0,0,0)。 |
| `build_model` | `build_model(key: str, variant: int \| None = None) -> dict` | 构建并返回模型 dict（`(key, variant)` 单条缓存 + 线程锁）：`build_voxels` → `build_mesh` → `tex_keys`（`_mat_shape` 取纹理位排序去重）。返回 `{"key","variant","voxels","size","mesh","tex_keys"}`。 |
| `tex_keys_used` | `tex_keys_used(model: dict) -> list` | 模型用到的纹理键（`halfheight:` 前缀去前缀），排序返回。 |
| `_mat_shape` | `_mat_shape(v) -> tuple` | 体素值 → (基纹理键, 形状码\|None)：元组直取（门上半 `door:u:*` 且基键以 `" door bottom"` 结尾时换 `" door top"`）；旧 `halfheight:` 前缀字符串 → (去前缀, SHAPE_SLAB_BOT)；非字符串 → UNKNOWN_MAT。 |
| `_face_mat` | `_face_mat(mat: str, shape: str \| None, normal: tuple, box: tuple \| None = None) -> tuple` | 按面分流纹理，返回 (纹理键, rect)。rect = 图归一化窗 `(u0,v0,u1,v1[,swap])`（官方 JSON uv 像素按 FaceInfo 顶点配对换算），None = 基键全图。依次处理 chest/barrel/col/fc 形状族、bell/composter（按 box 特征）、crafting table 特例、`_FULL_FACES` 分面，装饰族委托 `_decor_face_mat`。 |
| `_RU` / `_RS` | `_RU(a,b,c,d)` / `_RS(a,b,c,d)` | 官方模型 JSON 像素窗 → 归一化窗换算：up 面 `v=(1-b,1-d)`；side/down 面 `v=(1-d,1-b)`；u=(a,c)；除以 16。 |
| `_decor_face_mat` | `_decor_face_mat(mat, kind, rest, normal, box) -> tuple` | 装饰方块（新形状码族）按面分流：rswire（世界平铺自动命中）、repeater/comparator（底板 smooth stone / 火把柱 redstone torch off）、sculk（底座/触须）、lamp（lit 两态）、pist（platform/bottom/side）、brewing（底板三分窗+杆）、flowerpot（壁侧横带+内底 dirt）、candle、torch（立式 + 墙上斜杆三级台阶段按段等分杆身带）、lantern（顶盖/主体盒）、erod（底座/杆盒）、dhead（龙首 5 面）、bed（顶面枕带/毯区分区窗，e/w 走 swap）、wsign（板盒正面窗）、pisth（平台/轴盒；轴端面返回 `_SKIP_FACE` 不生成）、lectern。 |
| `_rect` | `_rect(b: tuple, axis: int) -> tuple` | AABB 在 axis 法向平面上的投影矩形（x 面投影 (z,y)、y 面 (x,z)、z 面 (x,y)）。 |
| `_covered` | `_covered(inner: tuple, outer: tuple) -> bool` | 投影矩形 inner 是否被 outer 完全覆盖（容差 1e-9）。 |
| `_boxes_with_arms` | `_boxes_with_arms(vox: dict, pos: tuple, shape) -> list` | 某位置形状的完整 AABB 列表：post/pane/wall 按四向邻居 `bs.connect_kind` + `bs.connect_arms` 补连通臂；自身面生成与邻居贴界面矩形共用，保证接缝判定对称。 |
| `build_occlusion` | `build_occlusion(vox: dict) -> dict` | 逐 16³ section 可见性矩阵（1.21.11 反编译 VisGraph/SectionCompiler 移植）。输出 `{"sections": {(sx,sy,sz)->matrix}, "bounds": (...)}`，matrix 为 36 位 int（`face_from*6+face_to` 位，1=可见）；opaque<256 全 true、全实心全 false；从 6 外表面边缘空格 flood fill，空域接触方向对双向置位。 |
| `build_mesh` | `build_mesh(vox: dict) -> dict` | 体素 → 绘制网格（流程见上文"功能"）。返回 verts（8 列 x,y,z,u,v,nx,ny,nz）、idx、slots/slot_mat、quad_slot、water_off/water_count、chunks（含 AABB）、occl（含 chunk_at）。 |
| `_box_face` | `_box_face(b: tuple, normal: tuple) -> tuple` | AABB 上法线为 normal 侧的面四角（世界相对本地坐标，绕序与 `_FACES` 角点布局同构 = 面法线朝外）。 |
| `_emit_quad` | `_emit_quad(arr, idx, x, y, z, quad, normal, rect=None) -> None` | 四角 quad + 法线入槽 + 双三角索引。rect=None：UV 世界平铺（顶面 u=x,v=z；x 面 u=z,v=y；z 面 u=x,v=y）；非 None：窗内按面内归一化坐标线性插值（窗可反向；swap=True 轴交换，床顶 e/w 用）。 |

### 接口

- **同包内**：`Utils/SeedReverser/jigsaw_assembly.py` 只 import `parse_nbt`（模板 NBT 解析复用）。
- **同包内**：`Utils/SeedReverser/structure_3dview.py`（3D 视口）以 `import structure_models as sm` 使用 `sm.TEX_DIR`、`sm.build_model(key, variant)`、`sm.VARIANT_FILES`（变种轮播数）、`sm.ANCHOR_CENTER_KEYS` / `sm.ANCHOR_OFFSETS`（红线锚点/区块网格平移）。
- **跨域复用**：`Utils/StructurePreviewer/end_city_pieces.py` 局部 import `structure_models`，使用 `TEMPLATE_DIR`（拼 `endcity__{name}.nbt` 路径）与 `parse_nbt`（自解析末地城模板 palette/blocks）。
- **对 `block_shapes`（bs）与 `structure_blueprints`（sb）的依赖方向**：本模块是消费方（`shape_from_props`/`shape_boxes`/`connect_kind`/`connect_arms`/`SHAPE_*` 常量与 `sb.blueprint`）。
- **对外提供**：结构键 → 体素/网格/尺寸/纹理键的完整建模管线；体素坐标即 cubiomes 锚点坐标系，供 SeedReverser 生成逻辑与 StructurePreviewer 显示层共享。

### 关键变量/常量

| 名称 | 值/形态 | 说明 |
|---|---|---|
| `_ROOT` / `TEMPLATE_DIR` / `TEX_DIR` / `SCHEM_DIR` | 路径 str | 项目根 / `assets/SeedReverser/templates` / `assets/SeedReverser/textures/block` / `assets/SeedReverser/schematics`。 |
| `TEMPLATE_FILES` | dict[str, list[str]] | 8 键 NBT 模板映射（多文件拼接语义）：igloo 三段、pillager_outpost、ruined_portal、shipwreck、ocean_ruin、ocean_ruin_cold、ancient_city（city_center_1）、trail_ruins。 |
| `VARIANT_FILES` | dict[str, list[str]] | 变种模板（每项 = 单独模型，3D 视口轮播，与多文件拼接语义不同）：ocean_ruin 24+、ocean_ruin_cold 4、ruined_portal 13、shipwreck 20 官方变种（顺序与 composition._SW_INFO 的 sw_typ 索引一一对应，beached 按抽取索引取搁浅合法变种；首项 with_mast = 默认模板）。 |
| `VARIANT_KEYS` | frozenset | `frozenset(VARIANT_FILES)`。 |
| `ANCHOR_CENTER_KEYS` | frozenset | `{"monument"}`：锚点画在结构中心（wiki：1.13+ 神殿"生成在区块角上"即结构中心，正中央 4 方块分属 4 区块）；其余结构锚点为包围盒西北角。 |
| `ANCHOR_OFFSETS` | dict[str, tuple] | 非中心锚点结构的锚点偏移（模型局部坐标）：village (29.0, 53.0)（井柱簇形心）、trial_chambers (9.0, 35.4)；视口红线/区块网格按此平移。 |
| `EXTRUDE_KEYS` | set | `{"jungle_temple"}`：蓝图挤出键。 |
| `PROCEDURAL_KEYS` | set | 5 个程序化合成键。 |
| `SCHEM_FILES` | dict[str, str] | village/monument/trial_chambers → `.schem` 文件名（存在优先、缺失回退程序化）。 |
| `_SCHEM_ENV_FILTER` | frozenset | 环境方块过滤清单，当前空集（仅丢弃 `_MAT_MAP=None` 方块），待用户确认后填入。 |
| `UNKNOWN_MAT` | `"__unknown__"` | 未映射方块回退材质（视口渲染灰色）。 |
| `_MAT_MAP` | dict[str, str\|None] | 核心材质映射大表（约 400 条），组织方式见上文"功能"。 |
| `_E16` | 1/16 | 像素步长（`_decor_face_mat` 盒身份判别用）。 |
| `_B36` | base36 字符表 | 蓝图 top 高度字符解码辅助。 |
| `_TAG_*` | 13 个 int | NBT 13 种标签类型常量（END/BYTE/SHORT/INT/LONG/FLOAT/DOUBLE/BYTEARR/STRING/LIST/COMPOUND/INTARR/LONGARR）。 |
| `_CROP_STAGES` | dict | 作物 → (纹理前缀, age 折叠表)：wheat 8 档一对一；carrots/potatoes (0,0,1,1,2,2,2,3)；beetroots (0,1,2,3)。 |
| `_DESERT_LAYERS` | dict[int, tuple[str,...]] | 沙漠神殿 wiki 逐层蓝图（层号 -14..10，21 行/层，由 desert_layers_out.txt 自动生成，方块计数与 wiki Materials 表全对账）。 |
| `_DESERT_CHAR_MAT` | dict[str, str] | 蓝图字符 → 纹理键（S/C/H/O/B/d/T/E/P/t/l；羊毛 W/G/R 不在表内，按 wiki 生成规则在构建函数处理）。 |
| `_PROC_BUILDERS` | dict[str, callable] | 程序化合成分发表：monument/swamp_hut/trial_chambers/village/desert_pyramid。 |
| `_CACHE_LOCK` / `_CACHE` | Lock / dict | build_model 的模块级单条缓存（键 (key, variant)）与线程锁。 |
| `_TRANSPARENT_MATS` | frozenset | `{"water","glass","ice","ladder"}`：面剔除透明感知（异材不剔；ladder 不剔所贴墙面）。 |
| `_HP` / `_HALF` | `"halfheight:"` / 0.5 | 旧前缀归一化 / 半层边界（AABB 贴边占用判定）。 |
| `_FULL_FACES` | dict[str, tuple] | 整格分面表：基键 → (顶, 底, 侧)，None = 沿用基键（grass block/podzol/bookshelf/farmland/target/end portal frame/cactus/melon/工作台系列/trial spawner）。 |
| `_COL_ENDS` | dict[str, str] | 轴心方块端面表：基键 → 端面纹理（oak/spruce/dark oak/acacia/mangrove log 及 stripped、basalt、polished basalt、quartz pillar、deepslate）。 |
| `_FC_FACES` | dict[str, tuple] | 炉族前脸表：基键 → (顶, 前脸, 亮前脸, 竖直前脸)（furnace/blast furnace/smoker/dispenser/vault/ominous vault）。 |
| `_FACE_N` | dict[str, tuple] | 朝向字符 → 法线（n/s/e/w），箱子/炉族/龙首朝向面判定。 |
| `_LANTERN_R` / `_EROD_R` / `_BREW_R` / `_FPOT_S` | dict / tuple | 灯笼/末地烛/酿造台/花盆的 rect 窗表（`_RU`/`_RS` 换算的官方 uv 像素窗）。 |
| `_BED_HEAD_R` / `_BED_FOOT_R` / `_BED_MATS` | dict / tuple / frozenset | 床顶面枕带分区窗（s/n/e/w，e/w 带 swap）、毯区窗、全 16 色床白名单。 |
| `_DHEAD_FACES` | dict[str, str] | 龙首 5 面纹理键（face/top/side/west/bot，`make_decor_tex` 按框 UV 区合成）。 |
| `_SKIP_FACE` | `"__skip__"` | 面跳过哨兵：官方模型该面无 faces，完全不 emit（区别于 (None, None) 回退基键）。 |
| `_FACES` / `_NEIGHBOR_DIRS` / `_PLANT_QUADS` | 常量表 | 六向面（法线+4 顶点 CCW）、六邻方向、植物对角 X 四 quad 表。 |

> 备注：`__all__` 导出列表中包含 `voxels_from_template`，但模块中并无该名字的定义（历史遗留），实际模板解析函数为私有 `_voxels_from_template_file`；`build_occlusion`/`build_mesh` 未列入 `__all__` 但属公开可用 API。

---

## `Utils/SeedReverser/jigsaw_assembly.py`

1083 行。堡垒遗迹 jigsaw 拼装引擎 v2——逐字节码复刻 1.21.1 原版生成算法（字节码定案依据：工作空间 `.temp/jigsaw_classes/*.txt`；对应反编译符号：ejk.a 起点入口、ekv.a 18 参外层大盒 / 13 参驱动、ekv$b.a tryPlacingChildren、dka.a 连接判定、elb/jm 结构池、enm/eni 降解处理器；eju/eku 记账仅为游戏内部用途未实现）。

**功能**：

1. **TemplateModel 与模板解析**：`TemplateModel`（dataclass）持模板 key、size_x/y/z 与 `markers: List[JigsawMarker]`。`_parse_template(key, path)`（纯解析无缓存，供 `load_template` 与 4 个 StructurePreviewer 组装模块共用）流程：`parse_nbt` 读 NBT → `root["size"]`（TAG_Int_List 元组 `(9,[x,y,z])`）取尺寸 → 扫 palette 找 `minecraft:jigsaw` 条目的 `orientation` 属性（`parse_orientation`：`'north_up' -> ('north','up')`）→ 遍历 `blocks` 取 jigsaw 方块，从方块 NBT 读 `joint/name/target/pool/placement_priority`（缺省 `minecraft:empty` / 0），产出 `JigsawMarker` 列表。`load_template` 加模块级 `_TEMPLATE_CACHE`。
2. **template_pool JSON 解析**：`PoolElement`（single/legacy 候选：location 剥命名空间、projection、element_type、weight、processors 处理器 id）与 `ListPoolElementSpec`（list_pool_element 候选：getShuffledJigsawBlocks 委托 elements[0]、place 依序放置全部子元素、bbox = 子元素盒 encapsulating；location = elements[0] 模板 key、sub_locations = 全部子模板 key、sub_processors = 各子处理器 id，outpost overgrown 带 `minecraft:outpost_rot`）。`StructureTemplatePool` 持 pool_id/elements/fallback 与 `start_variant`（1.21.11 起始池 WeightedList 语义占位：None = 旧式展开列表抽取，("list", items) = 预展开抽索引）。`load_pool` 读 `assets/SeedReverser/bastion/template_pool/<id>.json`（`"minecraft:empty"` 无 JSON 文件，返回注册过的空池）；`parse_pool_dict` 从已解析 dict 构建内嵌池数据（trial 用），两者同走 `_POOL_CACHE`；`list_element_hook` 参数允许调用方把 list_pool_element 原始 dict 转为引擎可放置候选。trial 池的 feature_pool_element/empty_pool_element 无 location：location 存空串，Placer 按 element_type 过滤（feature → continue、empty → break 终止候选），与 fgs$b 语义一致。`_proc_id`：processors 字符串剥命名空间、dict/缺失 = None（内联 dict 处理器链村庄全为空 dict 同 None）。`expanded_pool` = elb.b shuffle 前 weight 展开列表（JSON 顺序）；`pool_max_yspan` = elb.getMaxSize（非 empty 候选模板 Rotation.NONE 下 y 跨度最大值，缓存于池对象）。
3. **拼装主循环（start piece → 扩展队列 → 连接匹配）**：`assemble_jigsaw` 通用入口（fgs.a + ekv$b 1.21 语义，bastion/trial/ancient_city/outpost/village 共用）：`make_layout_rng(level_seed, chunk_x, chunk_z)` 建流 →（可选 `skip_y_bound`：start_height 采样补位，trial 的 uniform(-40,-20) 在 rotation 之前消耗 nextInt(21)，调用方已用同一条流采出 y，重建流后须先丢弃等量消耗，否则 rotation/start_pool 全部错位；bastion start_height 是 constant 33 零消耗传 None）→ `rotation_get_random`（nextInt(4)）→ 起点池 weight 展开 + `next_int(len)` 抽起点件（fgw.a/ekv.b 同式 nextInt(totalWeight)；cubiomes 跳过这步仅因两起点件尺寸相同，RNG 消耗实际存在）→（可选 `start_jigsaw_name`：fgs.a L105-214 起点重定位，ancient_city 专用——起点模板全部 jigsaw 标记洗牌（M>1 时 M-1 次主流消耗）+ name 匹配（如 minecraft:city_anchor），`templatePosition = pos - R(local)` 使 anchor 标记世界坐标恰好落在 pos，dy 公式的 k 同步改用 templatePosition.y；找不到匹配标记抛 ValueError 同游戏"整体放弃生成"）→ 起始件 dy：`start_y_is_offset=True`（bastion）`dy = k-(minY+1)`（groundLevelDelta=1），False（trial）`dy = k-minY` → 建起点 `JigsawPiece(depth=0)` → 外层大盒 `outer = BBox(中心±max_dist, y ∈ [max(start_y-maxDist, -64+pad_bottom), min(start_y+maxDist+1, 320-pad_top)])` → `Domain(outer)` 挖掉起点盒得 freeSpace → `_Placer.run`。`_Placer.try_placing_children`（ekv$b L244-416 逐行转写）：父标记循环（`_parent_markers_shuffled`：世界坐标标记 shuffle + selection_priority 降序稳定排序）→ 域选择（父标记 targetPos ∈ 父 box → `private_domain = Domain(piece.box)` 懒初始化且**整棵子树共享**；否则用入队携带的 carried_domain）→ 候选池（depth != max_depth 时主池 weight 展开 shuffle + fallback 池 shuffle 拼接；每标记都消耗，bastion 全 0 优先级 → FIFO）→ 候选循环（empty_pool_element → break 终止；feature_pool_element → 仅消耗 rotation_shuffled 后 continue；single/list → rotation_shuffled 取旋转）→ 旋转循环（`_child_markers_shuffled`：markers_at(rot) + shuffle + selection_priority 排序；候选盒 yspan；expansion hack 且 yspan≤16 时 free_y_span 取子标记所引池含 fallback 的 `pool_max_yspan` 最大值，盒顶扩展 `max(free_y_span+1, yspan)`）→ 子标记循环（`_connects` 连接判定 → anchor = targetPos − rot(子标记局部位) → y 定位：rigid-rigid 时 `anchor_y = parent_min_y + rel_y`（与 anchor.y 代数恒等，dy=0），否则 `terrain_height(pw.x, pw.z) − mark_local_y`（缺省 `_flat_terrain_height` 返回海平面 63，按 (x,z) 缓存）→ `domain.rejects(child_box)` 碰撞判定（child 收缩 0.25 后露出域外 = 不完整在 bounds 内或与任一 hole 共享整数格；整数栅格上 deflate(0.25) 退化为无格重叠判定，贴面合法）→ 通过则 `domain.subtract(child_box)` 挖除 → 建 `JigsawPiece` 入 pieces → depth+1 ≤ max_depth 入队（优先级 = 父标记 placement_priority）→ break（label129 continue，同一候选一个子标记只放一次）。
4. **rot_piece_pos 旋转公式**（dmm.a(int,int,int)，体素/局部坐标旋转，Y 不变）：`CLOCKWISE_90 → (size_z-1-z, y, x)`；`CLOCKWISE_180 → (size_x-1-x, y, size_z-1-z)`；`COUNTERCLOCKWISE_90 → (z, y, size_x-1-x)`；NONE 原样。配套 `rot_rotate_dir`（方向向量水平旋转，竖直不变）与 `rot_size`（90 度旋转交换 x/z 尺寸）。`TemplateModel.markers_at(rot)` 用这三者把局部 pos/front/top 变换到旋转后坐标，`get_bounding_box(piece_pos, rot)` 按 `rot_size` 建盒。
5. **bastion/通用引擎与各结构组装模块的复用关系**：本模块是"通用拼装引擎 + bastion 特化"双重角色——`assemble_bastion` 只是 `assemble_jigsaw` 的 bastion 默认参数快捷入口（max_depth=6、start_y=33 offset 语义、max_dist=80、pad 0）；`assemble_jigsaw` 通过 `load_pool_fn`/`load_template_fn` 注入结构专属加载器（资产根绑定 + 各自缓存），通过 `skip_y_bound`/`start_jigsaw_name`/`expansion_hack`/`terrain_height_fn` 适配各结构差异。Utils/StructurePreviewer 下各组装模块复用：**trial_assembly.py**（注入绑定 trial 资产根的加载器、`skip_y_bound` 补位 start_height、内嵌池数据走 `parse_pool_dict`）、**ancient_city_assembly.py**（`start_jigsaw_name="minecraft:city_anchor"` 起点重定位 + list_element_hook）、**outpost_assembly.py**（list_pool_element 候选，overgrown 子元素 outpost_rot 降解）、**village_assembly.py**（processors 处理器 id 传渲染层分发降解）；四者均直接调用 `JA._parse_template` 解析自家 NBT 模板。渲染层 `composition.py` 使用 `assemble_bastion`、`rot_piece_pos`（多处局部 import）与 `apply_degradation`。
6. **bastion 降解处理器**（enm RuleProcessor + eni 规则，bastion_generic_degradation）：`apply_degradation(state_name, x, y, z)` 每方块独立 `LegacyRandomSource(Mth.getSeed(x,y,z))`——`mth_get_seed` 逐符号内联（x*3129871 imul 32 位回绕 + 符号扩展、z 项乘 116129781 在 64 位图案进行、`l = l*l*42317861 + l*11 mod 2^64`、`seed = l >> 16` 算术右移），规则按序共用该流、state.is(block) 短路（不匹配的规则不消耗随机数）；`_BASTION_RULES` 5 条（polished_blackstone_bricks 0.3→cracked、blackstone 1e-4→air、gold_block 0.3→cracked、gilded_blackstone 0.5→blackstone、blackstone 0.01→gilded），按 block 预分组 `_DEGRADABLE_ITEMS`（**必须列表保序**——blackstone 有两条规则共用同一条随机流直到首次命中，dict 单值覆盖会改变 RNG 消耗次数，对拍实证）；不可降解方块 frozenset 快速路径直接返回；可降解方块内联 48 位 LCG（`state*25214903917+11 mod 2^48`，`next(24)*2^-24 = next_float` 同式，数学恒等），免 4.4 万次对象创建。

### 类与函数

| 名称 | 签名 | 说明 |
|---|---|---|
| `_tpl_path` | `_tpl_path(key: str) -> Path` | 资源 key → 模板 NBT 路径：`'bastion/units/air_base'` → `templates/units/air_base.nbt`（资产目录已以 bastion 为根，剥 bastion/ 前缀；trial 等注入自己的加载器不走本函数）。 |
| `_pool_path` | `_pool_path(pool_id: str) -> Path` | 池 id → `template_pool/<完整id>.json` 路径（保留完整 key）。 |
| `rot_rotate_dir` | `rot_rotate_dir(rot: str, d: str) -> str` | dmm.a(ji)：方向向量水平旋转（竖直方向不变）；CW90/CW180/CCW90 按向量变换反查方向名。 |
| `rot_piece_pos` | `rot_piece_pos(rot: str, pos: Tuple[int,int,int], size_x: int, size_z: int) -> Tuple[int,int,int]` | dmm.a(int,int,int)：体素/局部坐标旋转（Y 不变），公式见上文"功能"4；非法 rot 抛 ValueError。 |
| `rot_size` | `rot_size(rot, size_x, size_y, size_z) -> Tuple[int,int,int]` | 90 度旋转交换 x/z 尺寸，其余原样。 |
| `BBox` | `BBox(x0,y0,z0,x1,y1,z1)` | 整方块闭区间包围盒，`__slots__`。`from_pos_size` 类方法按 pos+size 建；`moved` 平移；`contains` 点包含。 |
| `_contains` | `_contains(child: BBox, region: BBox) -> bool` | child 完整落在 region 边界盒内（整数格闭区间）。 |
| `_encapsulate` | `_encapsulate(boxes: List[BBox]) -> BBox` | BoundingBox.encapsulatingBoxes：多盒最小包围盒。 |
| `_flat_terrain_height` | `_flat_terrain_height(x: int, z: int) -> int` | terrain_matching getFirstFreeHeight 的缺省近似：返回海平面 63（无高度图注入时）。 |
| `_share_cell` | `_share_cell(a: BBox, b: BBox) -> bool` | 两盒是否共享至少一个整数格（贴面相邻 = False）。 |
| `Domain` | `Domain(bounds: BBox)` | freeSpace 允许域（VoxelShape AABB 近似）：`bounds` 域边界盒 + `holes` 已挖除盒列表。`subtract(box)` 挖除；`rejects(child)` = child 不完整在 bounds 内或与任一 hole 共享整数格（exs.c deflate(0.25) ONLY_SECOND 在整数栅格上的等价退化，贴面合法）。 |
| `JigsawMarker` | `JigsawMarker(local_pos, front, top, joint, name, target, pool, placement_priority)` | dataclass：jigsaw 方块标记；local_pos 为（旋转后）世界或局部坐标，joint 为 NBT joint（bastion 全显式）。 |
| `TemplateModel` | `TemplateModel(key, size_x, size_y, size_z, markers=[])` | dataclass：模板模型。`markers_at(rot)`：getJigsawBlocks 的标记部分（局部 pos/front/top 经 rot 变换）；`get_bounding_box(piece_pos, rot)`：rot_size + BBox.from_pos_size。 |
| `parse_orientation` | `parse_orientation(ori: str) -> Tuple[str, str]` | `'north_up' -> ('north','up')`。 |
| `_parse_template` | `_parse_template(key: str, path: Path) -> TemplateModel` | 模板 NBT 解析（load_template 与 trial/ancient_city/outpost/village 组装模块共用，纯解析无缓存）：size → palette 中 jigsaw 方块 orientation 表 → blocks 遍历收集标记（joint/name/target/pool/placement_priority）。 |
| `load_template` | `load_template(key: str) -> TemplateModel` | `_TEMPLATE_CACHE` 缓存加载 bastion 模板。 |
| `PoolElement` | `PoolElement(location, projection, element_type, weight, processors=None)` | dataclass：single/legacy 池候选；processors 为池 JSON 处理器 id（bastion/trial 全无，village 逐元素引用，经 JigsawPiece.processor 传渲染层）。 |
| `ListPoolElementSpec` | `ListPoolElementSpec(location, projection, weight, sub_locations=[], sub_processors=[])` | dataclass：list_pool_element 候选——标记源 = elements[0]、放置源 = 全部子模板、bbox = 子元素盒 encapsulating；outpost overgrown 子元素带 outpost_rot。 |
| `StructureTemplatePool` | `StructureTemplatePool(pool_id, elements, fallback, start_variant=None)` | dataclass：结构池；start_variant 为 1.21.11 起始池 WeightedList 语义占位。 |
| `_pool_from_json` | `_pool_from_json(pool_id, data, list_element_hook=None) -> StructureTemplatePool` | 池 JSON dict → StructureTemplatePool：elements 逐项转 PoolElement（list_pool_element 且有 hook 时交 hook），location 剥 `minecraft:` 前缀；fallback 同剥。 |
| `load_pool` | `load_pool(pool_id: str) -> StructureTemplatePool` | `_POOL_CACHE` 缓存加载 bastion 池 JSON；`"empty"` 返回注册过的空池（0 元素无 fallback，无文件）。 |
| `parse_pool_dict` | `parse_pool_dict(pool_id, data, list_element_hook=None) -> StructureTemplatePool` | 从已解析池 dict 构建池（trial 内嵌池数据用），语义与 load_pool 的 JSON 解析段一致，同走 `_POOL_CACHE`；trial 的 feature/empty 元素 location 存空串由 Placer 过滤。 |
| `_proc_id` | `_proc_id(proc) -> Optional[str]` | 池元素 processors 字段 → 处理器 id：字符串剥命名空间；dict/缺失 = None。 |
| `expanded_pool` | `expanded_pool(pool) -> List` | elb.b shuffle 前的 weight 展开列表（JSON 顺序，每元素重复 weight 次）。 |
| `pool_max_yspan` | `pool_max_yspan(pool, load_template_fn=None) -> int` | elb.getMaxSize：非 empty 候选模板 Rotation.NONE 下 y 跨度最大值（含 list 候选 sub_locations），结果缓存于池对象 `_max_yspan`。 |
| `_strip` | `_strip(rid: Optional[str]) -> Optional[str]` | 资源 id 剥命名空间前缀。 |
| `JigsawPiece` | `JigsawPiece(template, rot, piece_pos, box, depth, projection="rigid", sub_templates=None, sub_processors=None, processor=None)` | dataclass：已放置件。`world_markers()`：markers_at(rot) 后平移 piece_pos 得世界坐标标记（懒缓存 `_world_markers`）。 |
| `AssemblyResult` | `AssemblyResult(pieces, start_index, rng_calls)` | dataclass：拼装结果。start_index = start pool 真实选取索引（trial 起点池 end_1/end_2 等权，写死 0 会拼错几何，seed=42 对拍实证）；rng_calls = RNG 消耗日志。 |
| `PriorityWorkQueue` | `PriorityWorkQueue()` | ayz 优先队列（bastion 全 0 → FIFO；通用语义按 (priority, 插入序)）：`append(piece, domain, priority)`、`pop_front()`（线性扫描取最小元组）。 |
| `_default_joint` | `_default_joint(front: str) -> str` | dka 私有 a(ji)：joint 缺省规则——front 竖直（up/down）→ aligned，水平 → rollable。 |
| `_connects` | `_connects(parent: JigsawMarker, child: JigsawMarker) -> bool` | dka.a 连接判定：父 front == opposite(子 front) 且（父 joint == rollable 或 父 top == 子 top）且 父 target == 子 name（均剥命名空间）。 |
| `_Placer` | `_Placer(rng, rng_log, max_depth=6, load_pool_fn=None, load_template_fn=None, expansion_hack=False, terrain_height_fn=None)` | ekv$b Placer。核心方法：`_child_markers_shuffled`（标记 shuffle + selection_priority 降序稳定排序）、`_parent_markers_shuffled`（getShuffledJigsawBlocks：世界坐标标记 shuffle + 排序，每次 tryPlacingChildren 都消耗）、`_candidate_boxes`（候选在 rot 下的 (模板key, box) 列表；list 候选 = 子盒 encapsulating）、`try_placing_children`（主循环，见上文"功能"3）、`run(start, outer)`（起点入队后循环出队扩展直到队列空）。 |
| `assemble_bastion` | `assemble_bastion(level_seed: int, chunk_x: int, chunk_z: int, start_pool_id="bastion/starts") -> AssemblyResult` | bastion 快捷入口：以 bastion 常量（depth 6 / start_y 33 offset / max_dist 80 / pad 0）调用 assemble_jigsaw。 |
| `assemble_jigsaw` | `assemble_jigsaw(level_seed, chunk_x, chunk_z, *, start_pool_id, max_depth, start_y, start_y_is_offset, max_dist, pad_bottom=0, pad_top=0, skip_y_bound=None, load_pool_fn=None, load_template_fn=None, expansion_hack=False, terrain_height_fn=None, start_jigsaw_name=None) -> AssemblyResult` | 通用 jigsaw 拼装入口（fgs.a + ekv$b，流程见上文"功能"3）。返回 pieces + start_index + rng_calls。 |
| `apply_degradation` | `apply_degradation(state_name: str, x: int, y: int, z: int) -> str` | bastion_generic_degradation 单方块降解（eni/enm 字节码语义），流程与性能要点见上文"功能"6；不可降解直接返回，可降解内联 LCG 按序评估规则至首次命中。 |

### 接口

**依赖**（本模块 import）：
- `.mc_rng`：`LegacyRandomSource`、`make_layout_rng`、`mth_get_seed`、`rotation_get_random`、`rotation_shuffled`、`shuffle_list`（RNG 全部消耗时序与原版一致）。
- `.structure_models`：`parse_nbt`（模板 NBT 解析复用）。

**被 import**（对外提供）：
- `Utils/StructurePreviewer/trial_assembly.py`：`JA.assemble_jigsaw`（skip_y_bound 补位）、`JA.parse_pool_dict`（内嵌池数据）、`JA._parse_template`（自家模板解析）、`JA.TemplateModel` / `StructureTemplatePool` / `AssemblyResult`。
- `Utils/StructurePreviewer/ancient_city_assembly.py`：`JA.assemble_jigsaw`（`start_jigsaw_name` 起点重定位）、`JA.parse_pool_dict` + list_element_hook、`JA._parse_template`、`JA.ListPoolElementSpec` / `TemplateModel` 等。
- `Utils/StructurePreviewer/outpost_assembly.py`：`JA.assemble_jigsaw`、`JA.parse_pool_dict` + list_element_hook（overgrown outpost_rot）、`JA._parse_template`、`JA.ListPoolElementSpec` 等。
- `Utils/StructurePreviewer/village_assembly.py`：`JA.assemble_jigsaw`（processors 链路）、`JA.parse_pool_dict`、`JA._parse_template`、`JA.TemplateModel` 等。
- `Utils/StructurePreviewer/composition.py`（渲染合成层）：`assemble_bastion`、`apply_degradation`、`rot_piece_pos`（12 处局部 import，各 jigsaw 结构体素摆放旋转）。
- 同包 `structure_models.py` 与本模块无反向依赖（仅单向 `parse_nbt`）。

**对外提供**：`assemble_bastion`（bastion 一键拼装）、`assemble_jigsaw`（通用引擎，trial/ancient_city/outpost/village 共用）、`TemplateModel`/`_parse_template`/`load_template`（模板模型与解析）、`StructureTemplatePool`/`PoolElement`/`ListPoolElementSpec`/`load_pool`/`parse_pool_dict`/`expanded_pool`/`pool_max_yspan`（结构池层）、`rot_piece_pos`/`rot_rotate_dir`/`rot_size`（旋转三件套）、`BBox`/`Domain`/`PriorityWorkQueue`/`_Placer`（拼装原语）、`apply_degradation`（bastion 降解）、`JigsawPiece`/`AssemblyResult`（结果类型）。

### 关键变量/常量

| 名称 | 值 | 说明 |
|---|---|---|
| `BASTION_MAX_DEPTH` | 6 | 结构 JSON `size=6`：最大扩展深度（depth == max_depth 时主池不再 shuffle）。 |
| `BASTION_MAX_DIST` | 80 | `max_distance`：外层大盒半径。 |
| `BASTION_START_Y` | 33 | `start_height absolute=33`（constant，零 RNG 消耗）。 |
| `BASTION_PAD_BOTTOM` / `BASTION_PAD_TOP` | 0 / 0 | 大盒 y 向 padding。 |
| `BEARDIZER_MIN_Y` / `BEARDIZER_MAX_Y` | -64 / 320 | 大盒 y 上下硬界（beardifier 范围）。 |
| `PROJ_ROOT` / `ASSET_DIR` | Path | 项目根 / `assets/SeedReverser/bastion`（bastion 资产根：templates/ 与 template_pool/ 的基目录）。 |
| `DIR_VECTORS` / `_DIRS` / `OPPOSITE` | dict | 六方向名→向量 / 向量→名 / 相对方向表。 |
| `_TEMPLATE_CACHE` / `_POOL_CACHE` | dict | 模板与结构池的模块级缓存（key→对象）。 |
| `_BASTION_RULES` | tuple | 5 条降解规则 `(block, probability, output)`，JSON 顺序保序。 |
| `_DEGRADABLE_BLOCKS` | frozenset | 可被降解规则命中的输入方块集合（快速路径：不在集合内直接返回原样免建 RNG）。 |
| `_LCG_MULT` / `_LCG_ADD` / `_LCG_MASK48` / `_INV_2POW24` | 25214903917 / 11 / 2^48-1 / 2^-24 | 内联 48 位 LCG 常量（与 mc_rng.MULT/ADD/MASK_48 同源），免逐方块对象创建。 |
| `_DEGRADABLE_ITEMS` | dict[str, tuple] | 规则按 block 预分组（保序、同 block 多条规则共用同一随机流直到首次命中；dict 单值覆盖会改变 RNG 消耗次数——对拍实证，必须用列表）。 |

> 备注：`start_variant` 字段当前为 1.21.11 起始池 WeightedList 语义占位（None = 旧式展开抽取）；`_pool_from_json` 与 `parse_pool_dict` 的元素解析段为同一段逻辑的两份实现（后者支持内嵌 dict 数据源）。

---

# 08b 结构视图层：形状几何 / 蓝图数据 / 3D 视口 / 2D 预览

> 覆盖文件：`Utils/SeedReverser/block_shapes.py`、`structure_blueprints.py`、`structure_3dview.py`、`structure_preview.py`
> 信息全部来自源码精读与 grep 交叉核实；代码标识符保留英文。

---

## `Utils/SeedReverser/block_shapes.py`

**功能**：非完整方块形状几何库，StructurePreviewer 与 SeedReverser 共用。依据 MC 官方块状态 properties（`facing`/`half`/`type`/`open` 等）生成"形状码"字符串，再把形状码解析为 16 分格 AABB 近似几何（`_E = 1/16` 栅格），供 `structure_models.build_mesh` 网格化与连通性分析使用。纯视觉近似，以"观察定位场景够用"为度，尺寸尽量对齐官方 jar 内 `models/block/*.json` 元素。

- **体素值约定**（`build_mesh` 侧）：值为 `(tex, shape)` 二元组——`tex` 纹理键、`shape=None` 整格 / `str` 形状码；纯字符串值为老格式整格（程序化示意体/蓝图挤出）；`"halfheight:"` 前缀（蓝图侧遗留）= 底半砖。
- **形状码语法**：`kind:seg1:seg2...`。例如 `half:t:a`（顶半砖）、`stairs:s:b`（踏步贴南的下半楼梯）、`door:l:c:s:left`（下半/关/朝南/左铰链）、`trapdoor:n:c:b`（关/底半/背北）、`chest:n:single`、`rswire:s:-:u:-`（红石线四向连接段）、`fc:n:lit`（炉族带点亮前脸）、`pist:n:s:x`（粘性活塞已伸出）等。完整常量见下表。
- **朝向约定**：形状码尾段用官方 facing 缩写 `n/s/e/w`（NBT 里是全称，由 `_FACING_ABBR` 换算）；`u/d` 表示竖直朝向（竖直发射器、活塞等）。"踏步贴该侧"、"面板背靠反侧墙"（`wall_panel_edge` = facing 反侧）等语义在各常量注释中逐一注明。
- **连通体系**：`post`（栅栏 4/16 细柱）/`pane`（玻璃板中央 2/16 竖板）/`wall`（墙 8/16 柱）三类参与邻居连通，横臂由 `connect_arms` 依邻居类别自动补出（栅栏双横轨 2/16 截面 y 6..9/12..15、墙臂 6/16 宽高 14/16、面板臂中央全高板）；`col`/`fc` 几何整格也参与连通；半砖/楼梯/薄片类不连。

**类与函数**（无类，全部为模块级函数；几何私有函数按族合并列表）：

| 名称 | 签名 | 说明 |
|---|---|---|
| `shape_from_props` | `(name: str, props: dict) -> str \| None` | 官方方块名（`minecraft:xxx`）+ properties → 形状码。无形状语义返回 `None`（调用方按整格处理）。按后缀/名单逐族判定：植物类→`plant`；`*_slab`（double 返回 None 整格）；`*_stairs`（half=top 换 `:t`）；`*_trapdoor`；`bell`（attachment=ceiling→`bell:ceiling`）；`composter`；`*_door`；`chest`/`trapped_chest`/`ender_chest`/`barrel`（type=left/right/single）；火把族（带 facing→墙上火把）；`lantern`（hanging→`lantern:h`）；炉族/发射器/vault→`fc:<f>[:lit]`（u/d 保竖直）；`*_log`/basalt/quartz_pillar→`col:<axis>`（`*_wood` 六面同纹不进）；栅栏/墙/压力板/地毯；`*_bed`→`bed:head\|foot:<f>`；`chain`→`bar:<axis>`；`end_rod`；`ladder`/`tripwire_hook`/`*_wall_banner`→`panel:<贴边>`；`*_wall_sign`→`wsign:<att>`；落地 `*_sign`/`*_banner`→`cross`；`*_button`；`lever`；`redstone_wire`（none/side/up→`-/s/u` 四段）；`repeater`/`comparator`；`sculk_sensor`；`piston`/`sticky_piston`→`pist:<f>[:s][:x]`（extended 加 `:x`）；`redstone_lamp`→`lamp:0|1`；`tripwire`→`bar:x\|z`；`cauldron` 族；`*_bars`/`glass_pane`→`pane`；蜡烛；`brewing_stand`；`potted_*`→`flowerpot`；龙首（wall 变体→`dhead:<f>:w`，站立 rot 0/4/8/12→四向）；`piston_head(_short)`→`pisth:<f>[:s]`；`lectern` |
| `shape_from_palette` | `(name: str, props: dict \| None) -> str \| None` | jigsaw/模板 palette 条目 → 形状码（组装层加载器专用）。一律转调 `shape_from_props`（props 缺失按空 dict）——无 Properties ≠ 无形状：火把/灯笼/地毯/花盆等无属性方块靠内建默认定型；旧加载点 `if props else None` 会把它们错当整格（落地火把变整块）。返回 None 时下游 `halfheight:` fallback 兜底 |
| `shape_mirror` | `(shape: str \| None, mirror: str) -> str \| None` | 形状码按放置镜像换向。`FRONT_BACK`（x=-x）下 e↔w、`LEFT_RIGHT`（z=-z）下 n↔s，u/d 透传。按 `_MIRROR_KIND_FACE` 找 kind 的朝向段下标（`bed`=1、`door`=2、其余 0）；`rswire` 特殊处理四向段交换（段序 n,s,e,w）。调用方须在 `shape_rotation` 之前调用（StructureTemplate.transform 先镜像后旋转） |
| `shape_rotation` | `(shape: str \| None, rot: int) -> str \| None` | 形状码按放置旋转 rot（0..3）换向。`_ROT_FACE[rot&3]` 查映射（rot1 = n→e，与 cubiomes 放置旋转 R 的 `(x,z)->(-z,x)` 一致）。door 保铰链/开门状态（纯旋转手性不变）；`bar` 奇数旋转 x/z 轴互换；`col` 轴向无旋转语义；`fc`/`repeater`/`comparator`/`pist`/`pisth` 竖直朝向（u/d）不随 R 旋转；`rswire` 四向段按 rot 轮换；stairs/chest/trapdoor/panel/button/lever/torch/dhead 换尾段朝向；half/post/pane 等不变 |
| `shape_boxes` | `(shape: str \| None) -> tuple` | 形状码 → AABB 元组（本地方块坐标，y 向上），`lru_cache(maxsize=512)`；None=整格；`col`/`fc`/`lamp` 整格（分面专用码）；`plant` 空 AABB（非实体，不参与面剔除/遮挡）；未知码兜底整格。核心分发器：按 kind 调下方几何函数 |
| `connect_kind` | `(v) -> str \| None` | 体素值 → 连通类别：`'full'`/`'post'`/`'pane'`/`'wall'`/None 不连。纯字符串 = full（`halfheight:` 前缀除外）；二元组看 shape 首段，`col`/`fc` 视作 full |
| `connect_arms` | `(kind: str, nbs) -> tuple` | kind + 四向邻居类别 nbs（顺序 n,s,e,w）→ 臂 AABB 元组。pane 臂全高 2/16 板、wall 臂 6/16 宽高 14/16、post 臂双横轨 y 12..15/6..9；臂沿连接方向触格边，邻居为同类或 `full` 才补 |
| `panel_shape` | `(att: str) -> str` | 贴边方向 → `panel:<att>` 形状码（梯子/拌线钩/墙横幅共用） |
| `wall_panel_edge` | `(facing: str) -> str` | 墙上挂件的贴边方向 = facing 反侧（`_OPPOSITE` 查表，缺省 "n"） |
| 几何私有族 | `_slab(vh, blank)`、`_stairs(quad, half)`、`_door(part, open_, facing, hinge)`、`_trapdoor(facing, open_, half)`、`_bar(axis)`、`_barrel()`、`_cauldron()`、`_composter()`、`_brewing()`、`_flowerpot()`、`_candle()`、`_lantern(hang)`、`_end_rod(facing)`、`_dragon_head(wall, facing)`、`_wall_sign(att)`、`_piston_head(facing)`、`_lectern()`、`_chest(typ, facing)`、`_bell(att)`、`_torch(kind, facing)` | 每函数返回该形状的 AABB 元组，尺寸取自官方模型：半砖半格（blank m/s/e/w 缺角版保留扩展）；楼梯 = 底层全宽半格 + 踏步半格，half=t 为整体 y 镜像（侧置楼梯踏步落底半格不越界，旧版 +0.5 会插进上方格）；门 3/16 厚板贴 facing 侧框边、开门转 90° 贴铰链侧（每半块门板占满全高，half 只影响纹理选择）；活板门关=水平薄板置于半区、开=竖薄板贴 facing 反侧格缘；钟 = floor 双柱+横梁 / ceiling 吊杆 + 三段阶梯钟体（颈/肩/口），facing 无静态几何影响；箱子单箱 14³ 居中、大箱左右半 15/16 宽接缝贴格界（left 占 facing 逆时针 90° 格，`_CHEST_LEFT_OF` 查表）；桶 13/16 高 14x14 柱；锅/堆肥桶四壁+底杯状；酿造台中央杆+三底板（官方四元素原样）；花盆四壁+内底；蜡烛 2x6x2 主柱；灯笼主体+顶盖（悬挂 +1px）；末地烛底座+立杆按 facing 旋转（水平时底座贴反侧壁）；龙首 12³ 单盒（落地贴底居中 / 墙挂抬 0.25 外凸 0.25）；墙告示牌 1.0×8/16×2/16 板 y6..14；活塞头平台 16x16x4 + 突轴 4x4x12（越界 4px 与本体凹口咬合）；讲台底座+立柱+水平顶板近似斜置 |
| 红石族私有 | `_rot_y(box, f)`、`_redstone_wire(rest)`、`_diode(f, comparator)`、`_sculk_sensor()`、`_piston_base(f)` | `_rot_y` = facing=n 基准 AABB 按 blockstate y 旋转（e=90/s=180/w=270 坐标变换）；红石线 = 4px 宽辐射臂贴地 1/64 厚片 + up 全高贴边竖片 + 孤点中心板；中继器/比较器 = 平滑石底板 2/16 + 火把柱（比较器背面双火把+输出端小火把）；幽匿感测体 = 8/16 底座 + 四角直立薄板近似官方 45° 斜片；extended 活塞本体 = facing 端缩进 4px 露杆室（u/d 沿 y 缩进） |

**接口**（grep 核实）：被 7 个文件 import，跨 SeedReverser 与 StructurePreviewer 两个工具复用：
- `Utils/SeedReverser/structure_models.py:41`（`as bs`）——`build_mesh` 网格化、`_mat_shape` 释义的核心依赖；
- `Utils/StructurePreviewer/composition.py:47`（顶层 `as bs`）+ 10 处函数内延迟导入（`as _bs`）；
- `Utils/StructurePreviewer/stronghold_pieces.py:729`、`mansion_pieces.py:58`、`end_city_pieces.py:486,562`、`fortress_pieces.py:49`——各结构件解析时生成形状码。
- 对外提供：形状码常量、`shape_from_props`/`shape_from_palette`（NBT→形状码）、`shape_mirror`/`shape_rotation`（放置变换）、`shape_boxes`（形状码→AABB）、`connect_kind`/`connect_arms`（连通性）、`panel_shape`/`wall_panel_edge`（贴边挂件）。

**关键变量/常量**：

| 名称 | 值/形态 | 说明 |
|---|---|---|
| `_E` | `0.0625` | 1/16 格栅格单位 |
| `_HALF` | `0.5` | 半层边界 |
| `SHAPE_SLAB_TOP/BOT` | `"half:t:a"` / `"half:b:a"` | 半砖（blank 段 m/s/e/w 缺角版保留扩展，模板内只有完整半砖） |
| `SHAPE_STAIRS` | `{"s","n","e","w"}` → `"stairs:<q>:b"` | 楼梯四向（half 由 `shape_from_props` 换 `:t`） |
| `SHAPE_DOOR_LC/UC` | `"door:l:c:s:left"` / `"door:u:c:s:left"` | 门下半/上半（关/朝南/左铰链基准码） |
| `SHAPE_TRAPDOOR_CB/CT` | `"trapdoor:n:c:b"` / `"trapdoor:n:c:t"` | 活板门关/底半、关/顶半 |
| `SHAPE_FENCE_POST` / `SHAPE_WALL` | `"post"` / `"wall"` | 栅栏 4/16 柱 / 墙 8/16 柱（臂由 `connect_arms` 补） |
| `SHAPE_BAR_X/Y/Z` | `"bar:x"` / `"bar:y"` / `"bar:z"` | 横杆（y = 链；绊线复用 x/z） |
| `SHAPE_PANE` | `"pane"` | 玻璃板/铁栏杆中央竖板（连通臂自动补） |
| `SHAPE_TORCH_V` / `SHAPE_TORCH_H` | `"torch:v"` / `"torch:h"` | 立式火把 / 悬挂灯笼（历史命名，H 槽现指居中小块） |
| `SHAPE_CHEST_N` | `"chest:n:single"` | 箱子基准码（完整码 `chest:<f>:<single\|left\|right>`，两段旧码兼容） |
| `SHAPE_BARREL` / `SHAPE_BED` | `"barrel"` / `"bed"` | 桶 / 整床（分半床为 `bed:head\|foot:<f>`） |
| `SHAPE_LAYER` / `SHAPE_PLATE` / `SHAPE_CARPET` | `"layer"` / `"plate"` / `"carpet"` | 整格截层 13/16 / 压力板 2/16 / 地毯 1/16 |
| `SHAPE_CAULDRON` / `SHAPE_COMPOSTER` | `"cauldron"` / `"composter"` | 锅形杯状（四壁+底） |
| `SHAPE_BUTTON` / `SHAPE_LEVER` | `"button:n"` / `"lever:up"` | 按钮/拉杆基准码 |
| `SHAPE_BELL_FLOOR` | `"bell:floor"` | 落地钟（ceiling 变体码 `"bell:ceiling"` 内联） |
| `SHAPE_CROSS` / `SHAPE_PLANT` | `"cross"` / `"plant"` | 落地告示牌十字板 / 真·对角 X 植物（quad 专用路径，AABB 空） |
| `SHAPE_COL_Y` | `"col:y"` | 轴心方块（整格几何 + 轴向分面纹理） |
| `SHAPE_FC_N` | `"fc:n"` | 炉族前脸码（`fc:<f>[:lit]`，dispenser/vault 同族） |
| `SHAPE_BREWING` / `SHAPE_FLOWERPOT` / `SHAPE_CANDLE` / `SHAPE_LANTERN` | `"brewing"` / `"flowerpot"` / `"candle"` / `"lantern"` | 酿造台 / 花盆 / 蜡烛 / 灯笼（悬挂=`"lantern:h"`） |
| `SHAPE_END_ROD` / `SHAPE_DRAGON_HEAD` | `"erod:y"` / `"dhead:n"` | 末地烛 / 龙首（墙挂 `:w` 后缀） |
| `SHAPE_BED_HEAD` / `SHAPE_BED_FOOT` | `"bed:head"` / `"bed:foot"` | 分半床（完整码带 facing 尾段） |
| `SHAPE_WALL_SIGN` | `"wsign:n"` | 墙挂告示牌（att 段 = 贴边边） |
| `SHAPE_PISTON_HEAD` | `"pisth:n"` | 活塞头（sticky 加 `:s`） |
| `SHAPE_LECTERN` / `SHAPE_RSWIRE` | `"lectern"` / `"rswire:-:-:-:-"` | 讲台 / 红石线（四向段 `-`/`s`/`u`） |
| `_FACING_ABBR` | dict | `north/south/east/west` → `n/s/e/w` |
| `_CHEST_LEFT_OF` | `{"n":"w","e":"n","s":"e","w":"s"}` | 大箱 left 半所在方向（facing 逆时针 90°） |
| `_MIRROR_KIND_FACE` | dict | kind → 朝向字母在码中的下标（`bed`=1、`door`=2、多数=0；不在表 = 无朝向语义） |
| `_ROT_FACE` | 4 元组 dict | 旋转 0..3 的 facing 映射（rot1: n→e/s→w/e→s/w→n，与 cubiomes 放置旋转一致） |
| `_OPPOSITE` | `{"n":"s","s":"n","e":"w","w":"e"}` | 面板贴边反侧表 |
| `_DUST_T` | `0.25/16` | 红石尘面片官方厚度（1/64 格），`_sculk_sensor` 复用 |

---

## `Utils/SeedReverser/structure_blueprints.py`

**功能**：SeedReverser 结构锚点示意图的**纯数据模块**（无渲染逻辑）。数据来源为 Minecraft Wiki 各结构 /Structure 子页的 layered blueprint 字符画，经 `.temp/gen_blueprint_data.py` 一次性解析投影生成；其中 `desert_pyramid`（3D 雕刻入口）与 `swamp_hut`（3D 改程序化架空小屋）为手改维护，与 `structure_models` 程序化合成保持一致。数据是"该形态主蓝图"的精确投影：同一结构存在多形态变体时（沉船/海底废墟/废弃传送门）仅代表一种典型形态，锚点角一致。

每份蓝图 dict 的字段约定：
- `W/D/H`：包围盒尺寸（列/深/高）；`y0/y1`：相对生成点的 Y 范围；
- `top`：俯视高度图，D 行 × W 列，base36 单字符 = 相对最高层数，`.`=空气；网格北朝上（-Z 向上）、西朝左（-X 向左），左上角 (0,0) = 结构包围盒西北角 = cubiomes 生成锚点；
- `tcol`：与 top 同形状的最高层方块调色板字符（`.`=空）；
- `side`：南立面剪影，H 行 × W 列，`1`=有方块，行序 y 高→低；
- `palette`：字符 → 方块英文名（渲染配色查 `BLOCK_COLORS`；允许 `EntitySprite:` 前缀与 `-rotNNN` 旋转后缀，如 igloo 的 `"Z": "EntitySprite:Villager"`、jungle_temple 的 `"E": "Chest-rot270"`）。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `has_blueprint` | `(key: str) -> bool` | 该结构是否有精确蓝图数据（False 时渲染兜底示意框） |
| `blueprint` | `(key: str)` | 返回蓝图 dict 或 None（拼装结构返回 None） |
| `fallback_size` | `(key: str)` | 兜底示意外框尺寸 `(W, D, H)` 或 None |

**接口**（grep 核实）：被 2 个文件 import：
- `Utils/SeedReverser/structure_models.py:42`（`as sb`）——程序化合成层读取蓝图做衔接/校验；
- `Utils/SeedReverser/structure_preview.py:27`（`as sb`）——2D 俯视图渲染的数据源。
- 对外提供：`BLUEPRINTS`/`FALLBACK_SIZES`/`BLOCK_COLORS` 三张表与上述三个查询函数。

**关键变量/常量**：

| 名称 | 值/形态 | 说明 |
|---|---|---|
| `FALLBACK_SIZES` | dict，5 键 | 无整体蓝图的拼装结构示意外框 `(W,D,H)`：`ancient_city`(80,80,12)、`monument`(58,58,30)、`trail_ruins`(30,30,8)、`trial_chambers`(40,40,20)、`village`(54,40,8)；与 `structure_models` 程序化合成包围盒一致 |
| `BLUEPRINTS` | dict，9 键 | 有精确蓝图的结构：`desert_pyramid`(21×22×25, Y-14~10)、`jungle_temple`(16×13×14)、`swamp_hut`(7×8×7)、`igloo`(7×11×28, Y-23~4)、`pillager_outpost`(25×16×21)、`ruined_portal`(10×7×9)、`shipwreck`(18×45×21)、`ocean_ruin`(22×17×10)、`ocean_ruin_cold`(16×17×7) |
| `BLOCK_COLORS` | dict，约 90 键 | 渲染专用方块配色（近似原版材质主色调）：`"NEUTRAL": "#9AA0A6"` 为未收录回退灰；键为归一化方块名（小写 + 去 `EntitySprite:` 前缀 + 去 `-rotNNN` 后缀），如 `"sandstone": "#D8CB9A"`、`"tnt": "#D8491F"`、`"redstone dust": "#A8170A"`；由生成脚本按 Wiki 调色板全集写死 |

---

## `Utils/SeedReverser/structure_3dview.py`（重点）

**功能**：SeedReverser 结构 3D 交互视口（`QOpenGLWidget` + 原生 OpenGL，GLSL 120），替换原平面示意图 label。同一份组件被两个工具共用：SeedReverser 用**环绕模式**看结构锚点，StructurePreviewer 额外开启**旁观者 FP 飞行模式**与开箱交互。

### 坐标与数据约定
- 体素 `(x,y,z)` 直接作世界坐标：x 西→东、z 北→南、y 向上；`(0,0,0)` = 包围盒西北角底部 = cubiomes 生成锚点（monument 特例：锚点 = 结构中心）。y-up 右手系，`QMatrix4x4.perspective`。
- 模型来自 `structure_models.build_model(key, variant)`（共享顶点网格 dict，含 `mesh/voxels/size/chests` 等），或由 `set_model` 低层注入（StructurePreviewer 的 `composition` 组装 `compose_display_model + build_mesh` 产物，可带 `anchor_local=(ax,az)` 与 `chunk_origin=(gx0,gz0)` 覆盖字段）。`mesh` 关键字段：`verts`（8 列 float：pos3+uv2+normal3）、`slots`（材质槽计数表）、`slot_mat`（槽→材质键）、`idx`（numpy uint16/uint32 索引，水索引在尾部）、`quad_slot`（quad→槽号表）、`chunks`（16³ chunk 重排 `[(idx_off, idx_count, AABB min3, max3)...]`）、`occl`（逐 section 可见性矩阵：`bounds/sections/chunk_at`）、`water_off/water_count`。

### 渲染管线（paintGL 全流程）
1. **视口与清屏**：`glViewport(width*dpr, height*dpr)`，`glClear(0x4100)`（COLOR|DEPTH），清屏色 `#2B2F36`。
2. **每帧重设 GL 状态**：`GL_DEPTH_TEST(0x0B71)`/`GL_BLEND(0x0BE2)`/`GL_CULL_FACE(0x0BC5)` + `glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)`。必须每帧重开：帧末 QPainter overlay 会弄脏全局状态（QPainter 内部关闭深度测试），不重设会出现"后画几何按画序覆盖先画"的建筑透视错误。
3. **惰性上传**：`_needs_upload` 且 `_render_failed` 为假时在 GL 上下文内调 `_upload_model()`；异常走 `_handle_render_failure`（停渲染 + 复位按钮 + 发 `render_error` 信号；强制 `glDepthMask(1)` 防水阶段失败后深度写入永久关闭；`_render_failed` 拦后续帧重试防刷屏，切结构/变种时重置）。
4. **矩阵**：`proj.perspective(_SP_FOV=85°, aspect, 0.5, 4000.0)`；`view.lookAt`——旁观模式 `eye → eye+dir`（up=(0,1,0)），环绕模式 `eye_pos() → center+pan`。
5. **模型主体** `_draw_model_body(mvp, occl_cells)`：
   - 图集槽原点已烘焙进顶点属性 `aTile`（上传期 `_bake_tile_origin` 一次性 numpy 向量化），运行时无逐槽 uniform；`uModel`（恒单位阵）/`uLightDir` 状态驻留（initializeGL 写一次）。
   - **chunk 视锥剔除**：`mesh["chunks"]` 每帧做 6 平面 p-vertex 判定（平面 = MVP 行向量组合：`row_i±row_3`），全部 chunk 一次性 numpy 向量化（每帧 6×N 次点积）；视锥外 chunk 整段不提交——FS 有 alpha discard（树叶/玻璃）early-z 不可用，被剔 chunk 同时省顶点与填充。**可见连续 chunk 合并成一段 draw**（`np.diff` 找段边界，draw call 数 = 可见段数而非 chunk 数）。
   - **旁观模式遮挡剔除** `occl_cells`：`_occl_cells_for_eye()` 移植自 1.21.11 反编译源码 `SectionOcclusionGraph.runUpdates`（MC 洞穴剔除运行期同款）——眼在实心整格（`_occl_opaque`，整格且非 `sm._TRANSPARENT_MATS`）返回 None = 全渲染（游戏 `isSolidRender` 时 smartCull=false 同款）；眼在空气格从眼 section 做 section 级 BFS：种子无条件可见且 6 向传播（源码 initializeQueue 无 sourceDirection 跳过 facesCanSeeEachother 检查），后续传播到方向 e 要求存在来向 d 使当前 section 矩阵 `facesCanSeeEachother(d.opposite, e)`（bit = `OPP[d] + 6*e`，门窗空域自然连通）；界外 section 视作未加载阻断（否则沿界外空 section "高速路"绕过实心 section，密封房间剔除失效——视线管探针实证）；结果按眼 section 缓存。与视锥结果取交集（`np.isin`；满集跳过、空集全剔）。近→远排序绘制经真窗口 A/B 实测无收益甚至略亏，不采用。
   - draw 经 **ctypes 原生 `glDrawElements`**（见下节兼容性）：`0x0004`（GL_TRIANGLES）+ `self._idx_type` + `c_void_p` 字节偏移。
   - 无 chunk 数据（旧 mesh/低层注入）回退单次全量 draw（水区间在索引尾部被排除）。
6. **线框层** `_draw_guide_lines(mvp)`（不受渲染开关影响，锚点/区块是逆推核心信息）：`_plain` 简写着色器（aPos+uMVP+uColor）画三组线——①区块黄框（`GL_LINES` 1.5px，y=min_y-0.02 贴地微降防 z-fighting；只画结构足迹覆盖的区块格，每格输出 16×16 矩形四边，`_seen` 键去重共享边；网格相位 gx0/gz0 由锚点口径 mod 16 决定：monument 取 `(w/2,d/2) mod 16`、ANCHOR_OFFSETS 键取偏移 mod 16、注入模型用 `chunk_origin`、其余 (0,0)，世界对齐语义 = 锚点 ≡ 所在区块西北角）；②锚点无限红线（2.0px，`ext = max(w,d,h)*8+64` 上下延伸 + 地面十字 1×1 标精确点；位置口径：`sm.ANCHOR_CENTER_KEYS`(monument)→结构中心、`sm.ANCHOR_OFFSETS`(village 水井/trial_chambers 入口两水池)→偏移、注入模型 `anchor_local`、缺省 (0,0)）；③箱子高亮琥珀描边（`set_chest_highlights` 注入的 12 棱包围盒，跨度 1.1 = 体素外扩 0.05 防 z-fighting，惰性上传 `_chest_vbo`）。
7. **水第二遍** `_draw_water(mvp)`：`_FS_WATER` 同图集采样输出 alpha 0.62；`glDepthMask(0)` 深度只读 + 关 `GL_CULL_FACE` 双面绘制（防水下/斜视水侧被背向剔除误裁）；在网格线之后绘制（水面混合叠在线上，与游戏内俯视观感一致）；索引区间 `[water_off, water_off+water_count)`。
8. **2D overlay**（QOpenGLWidget 仅允许在 paintGL 内开 QPainter，覆写 paintEvent 画属未定义行为会随机 0xC0000409）：QPainter 画开箱准星、左上图例（"红线 = 锚点（结构中心/西北角）"、"黄框 = 覆盖区块 (16×16)"）、底部操作提示（按模式/准星/锁定/调速残显态切换文案；变种键显示 `变种 k/n`）、右上 FPS（帧间 `perf_counter` 滚动均值 0.5s 刷一次防闪烁；低于 `_FPS_BAD_TH=30` 显红 `_FPS_BAD` 否则暗绿 `_FPS_OK`）。文字/准星硬边无抗锯齿（像素风对齐 + 省全窗口 AA pass 开销）。
9. **连续渲染自驱动**：旁观模式且 tick/pin 定时器活跃时 `QTimer.singleShot(0, self.update)` 让出事件循环再调度下一帧——帧率 = min(GPU 能力, 合成节奏)，摆脱定时器精度钳制；paintGL 内直接 `update()` 实测会把 tick 从 248Hz 挤到 139Hz。静止/非交互态条件不满足自然停转，不空烧 GPU。

### 纹理图集 `_build_atlas()`
纹理目录 `TEX_DIR`（= `sm.TEX_DIR` = `assets/SeedReverser/textures/block`）全部 png 按**文件名排序**拼入 16 列 × 32 行 = 512 槽 RGBA 图集（`_ATLAS_COLS=16, _ATLAS_ROWS=32, _ATLAS_TEX=16`，1:1 不缩放；非 16×16 源 `scaled` 兜底）；槽 0 固定未知材质灰 `#9AA0A6`；槽位超限抛 ValueError 提示扩 `_ATLAS_ROWS`（注释实证：原 16×16=256 槽被 tuff bricks 槽 267 击穿，越界采样回绕导致 trial 外壳渲染成暖褐）。返回 `(QImage, {纹理键: 槽索引})`；`QOpenGLTexture` 用 Nearest 过滤 + ClampToEdge（像素风）。

### 顶点烘焙 `_bake_tile_origin(verts, slots, slot_mat, atlas_slots, idx, quad_slot)`
8 列顶点 → 10 列（尾部追加图集槽原点 `aTile` 二分格 uv）：主路径按 `quad_slot` 每 quad 4 顶点同 tile 查表；`halfheight:` 前缀材质与基材质共纹理（半高变体）；越界/无归属顶点 tile 兜底 (0,0)（灰）；`idx` 仅用于尾段水区间——按索引位置（主体 6/quad 之后）取引用值把水顶点 tile 覆盖为 `water` 槽原点；兼容路径（`quad_slot` 缺省的旧 mesh/低层注入）按"非空槽顺序填满"推归属；空 verts 返回 (0,10) 数组。

### 着色器（GLSL 120）
- `_VS`：attribute `aPos/aUV/aNor/aTile`（显式 `bindAttributeLocation` 绑 0/1/2/3——不绑则驱动分配顺序不保证，环境变化会让 `_upload_model` 硬编码 index 3 错位），varying `vUV/vNor/vTile`；`vNor = mat3(uModel) * aNor`。
- `_FS`：`fract(vUV)` 世界坐标平铺 → 半像素 clamp（pad = 0.5/16 防渗色）→ `vTile + (tileUV.x*SLOT_W, (1-tileUV.y)*SLOT_H)` 映射槽内采样；`tex.a < 0.5` discard（树叶/玻璃镂空）；光照 = `max(dot(N, L), 0)` 方向光 + 环境项 0.42（`col = tex.rgb * (0.42 + 0.58*diff)`）。`SLOT_W=0.0625`/`SLOT_H=0.03125` 硬编码进 shader 不走 uniform——PySide6 6.11 `setUniformValue(int, float)` 重载歧义会把小数截断成 int 写入（`.temp/result_probe_uni.out` 实证 T_wh 全黑）。
- `_FS_WATER`：同 `_FS` 但固定输出 `alpha=0.62`。
- `_plain`：线框用 `aPos + uMVP + uColor` 最简着色器。

### ctypes 调用点与软件 OpenGL 兼容说明
- **原生 glDrawElements**：PySide6 6.11 的 `QOpenGLFunctions.glDrawElements` 包装在 "IBO + c_void_p 偏移" 形态下静默不画（llvmpipe 上 A/B 实证：包装器 0%，原生指针 10.33%；纯 int 形态又被 ValueError 拒收）。`initializeGL` 里 `context().getProcAddress(b"glDrawElements")` + `ctypes.CFUNCTYPE(None, c_uint, c_int, c_uint, c_void_p)` 解析原生函数指针存 `self._native_glDrawElements`；绘制期偏移经 `_VOIDP(int_off)` 包成 `c_void_p`。
- **GLSL 120 桌面版约束**：`#version` 必须是源码首行（前导空行报错）；桌面 GLSL 不支持 ES 专用 `precision` 语句（NVIDIA 宽松能过，Mesa/llvmpipe 直接拒编）——shader 里不得出现。
- **uniform 绑定**：PySide6 6.11 实测名字形态仅 `str` + 矩阵/向量/QColor/int 可用，`str/bytes + float` 均无匹配重载；`location + 任意类型` 全可用 → 统一 `uniformLocation(n)` 缓存到 `self._u/_wu/_pu` 后走 location。
- **vsync**：构造时 `format().swapInterval() != _VSYNC(0)` 则 `setFormat` 解除垂直同步（须 expose 前），帧率不随刷新率封顶。
- **缓冲重建**：每次 `_upload_model` 销毁重建全部 VAO/VBO/IBO——同一 buffer 重复 allocate/重指定属性指针在 NVIDIA 驱动下触发 0xC0000409（事件日志定位）。
- **顶点直传**：numpy `tobytes()` 一次成型直传（旧路径 `struct.pack` 逐元素 12 万顶点要 20+ms）；索引 dtype 决定 GL 类型（uint16→`0x1403`/uint32→`0x1405`），list 兜底按值域选型打包；属性指针 stride 40 字节：aPos(off 0, 3f)/aUV(off 12, 2f)/aNor(off 20, 3f)/aTile(off 32, 2f)，用 `setAttributeBuffer`（`glVertexAttribPointer` 的 PySide6 绑定不接受裸 int 偏移）。
- **定时器精度**：旁观者 pin/tick 定时器用 `Qt.TimerType.PreciseTimer`——Windows 默认 CoarseTimer 的 2ms 实际被系统定时器分辨率拖到 ~8ms（实测 126Hz），高刷屏下帧率被隐形钳半。
- **退出期析构**：PySide6 退出期 QTimer/顶层窗口析构会 0xC0000409 → `app.aboutToQuit` 连接 `_stop_spin_timers`，`stop_variant_timer()` 公开入口一并停轮播/空闲/旁观者 tick/心跳/钉扎。

### 相机与交互
**环绕模式**（SeedReverser 默认）：
- 右键拖拽环绕：`_orbit(dx*0.4, dy*0.4)`，yaw 取模 360°、pitch 限位 5°~85°；右键按下切换到 `_orbit_cursor()` 旋转光标。
- 滚轮缩放：`dist *= 0.87**steps`，限位 `[radius*0.6, radius*6.0]`；左键拖拽平移 `_pan_screen`（像素→世界，按当前距离与 45° 视野估算，沿视线 right/up 基）；双击 `_reset_camera_for_model` 复位。
- 相机自适应：`_reset_camera_for_model` 按包围盒设 `center=(w/2, h*0.38, d/2)`、`radius=max(w,d,h)*0.72+2`、初始 yaw=225°/pitch=35°；变种轮播切换用 `_adapt_camera_for_model` 保持用户方位只适配中心/半径。
- **旋转光标** `_orbit_cursor`：56px 位图（`_CURSOR_PIX`），北/西双箭臂（`_CURSOR_N_ARM/_CURSOR_W_ARM`，臂长 16px 共点于位图中心=热点）+ N/W 字母线段（箭尖前方，识别哪支臂指北/西），按 `_screen_angle()`（世界北向 `(0,0,-1)` 投影到视线 right/up 基的 `atan2(sx,sy)`，0°=屏幕正上顺时针）整体旋转；白色主线 + DestinationOver 深色描边（3.5px）浅深底都可读；角度缓存 `_cursor_angle` 供投影退化分支复用。替代已删的地面罗盘层。
- **变种轮播**：`set_structure` 对 `sm.VARIANT_FILES` 键（海底废墟/废弃传送门）启动 `_variant_timer`（2500ms）轮播官方模板变种；拖动/缩放期间 `_pause_rotation` 停轮播并续期单发 `_idle_timer`（4000ms 后 `_resume_rotation` 恢复）；`hideEvent` 停、`showEvent` 恢复。

**旁观者模式**（StructurePreviewer 用 `set_spectator_mode(True)`，与环绕模式并存、状态各自保留）：
- 进入：`_spectator_enter` → `_spectator_reposition`——眼睛悬于模型水平中点正上方俯视（pitch=-89.9° 规避 lookAt 与 up 共线退化；高度分档：水平跨度 ≥ `_SP_START_SPAN=40` 的大型结构取最高点+10，否则 +5），速度 `radius*1.2` 限位 [1,120] 格/秒；不自动锁鼠标，待点击视口或按 ` 才开始控制。
- **鼠标锁定（FPS 相机标准做法）**：`_spectator_grab_mouse` → `QCursor.setPos` 钉回视口正中心 + BlankCursor + 启动 `_sp_pin` 钉扎定时器（`_SP_LOGIC_HZ=500Hz` PreciseTimer）；`_spectator_pin_tick` 直读全局光标相对位移转视角（yaw += dx*sens、pitch -= dy*sens 限 ±89.9°）后立即钉回中心——与 mouseMove 事件流解耦（Windows 事件合并/延迟会导致回中滞后），光标物理上出不了窗口。` / Esc 呼出鼠标。
- **FP 飞行**：`_spectator_tick` 按键集推进——WASD/方向键 = 水平四向（无视 pitch，MC 玩家习惯；fw = `(-cos yaw, 0, -sin yaw)`，rt = `(sin yaw, 0, -cos yaw)`），Space/Shift = 世界升降；位移 = 速度 × interval/1000（高刷 tick 更频每步更短，手感不随刷新率变）；无键自动停 tick 只留心跳。滚轮调速（`_SP_WHEEL_STEP=1.1` 倍率/格，限 [1,120]），调速提示残显 1400ms（`_sp_speed_until_ms`）。
- **心跳**：`_sp_idle`（120ms）检查光标出窗（`underMouse` 失败即释放锁定）/全松停 tick；`focusOutEvent` 失焦立刻松全部键 + 释放鼠标。
- **开箱交互**：`set_interact_chests` 注入可交互箱子坐标（模型坐标，与 `set_chest_highlights` 同源独立存储）；`_spectator_update_crosshair` 在飞行/转视角后重判——准星射线与箱子 `[c,c+1)^3` AABB 做 slab 法三轴区间求交，沿视线取最近者，进入距离 ≤ `_SP_CHEST_DIST=4.0`（约 60° 视线锥语义靠 t 区间收敛实现），命中索引变化才重绘；准星绘制 `_draw_crosshair` 用 `fillRect` 双层（黑描边 3px + 白芯 1px，臂长 L=7 空隙 G=2）——不用 Difference 合成模式（GL 引擎上支持随驱动/帧缓冲格式有差异）也不用 drawLine（1px/3px FlatCap 端点光栅化有歧义，实测臂端缺 1px）。命中态右键或 E 开箱：发 `chest_open_requested(idx)`、呼出鼠标，若原本锁定则记 `_sp_resume_grab`，GUI 关闭后 `note_chest_gui_closed` 恢复锁定继续飞行。
- **输入总闸**：`set_spectator_input_locked(True)`（开箱 GUI 显示期间）清按键集、停飞行 tick、呼出鼠标，其后键盘/鼠标/滚轮全部吞掉；锁定期 Esc/E 经 `spectator_close_request` 信号转发关弹窗（非模态弹窗失焦后焦点不在弹窗，不转发则 GUI 关不掉）。与 `set_spectator_mode` 正交。（注：源码类体内连续定义了两次 `set_spectator_input_locked`/`spectator_input_locked`，内容一致，后者生效。）

**信号**：`render_error(str)`（构建/上传/绘制任一环节异常，tool 层连接后写信息框；视口同步停渲染并复位按钮）、`chest_open_requested(int)`（准星态开箱，参数 = model["chests"] 索引）、`spectator_close_request()`（锁定态 Esc/E 关箱 GUI）。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `Structure3DView` | `(parent=None)` | 唯一类，继承 `QOpenGLWidget`。构造：vsync 格式、渲染开关按钮（右上角 76×24 "渲染模型"/"停止渲染"，默认不渲染，出错自动复位）、相机状态（yaw=225/pitch=35/dist=None 自适应/pan/center/radius）、GL 资源占位、水第二遍字段、chunk/occl 数据、箱子高亮与交互坐标、FPS 统计、变种/空闲定时器、旁观者全套状态与三个定时器（pin/tick/idle） |
| 公开接口 | `set_structure(key, name="")` | 切换结构：`sm.build_model(key)` 构建失败则停渲染 + 发 render_error；`_load_model` 装填，变种键启动轮播 |
| | `set_model(model)` | 低层注入入口（StructurePreviewer 用）：外建完整模型 dict 直接进视口，`_key` 置 None 退出结构键模式（不轮播、锚点/区块线按注入字段或西北角默认口径） |
| | `stop_variant_timer()` | 停全部定时器（应用退出钩子，防退出期析构崩溃） |
| | `set_chest_highlights(positions)` | 箱子高亮描边：每箱 12 棱包围盒顶点（外扩 0.05），惰性上传 |
| | `set_interact_chests(positions)` | 注入可交互箱子坐标并重判准星 |
| | `crosshair_active()` / `note_chest_gui_closed()` | 准星命中查询 / GUI 关闭后按需恢复鼠标锁定 |
| | `set_spectator_mode(on)` / `is_spectator_mode()` / `mouse_grabbed()` | 切换/查询旁观者模式与锁定态 |
| | `spectator_toggle_grab()` / `spectator_sensitivity()` / `set_spectator_sensitivity(deg)` / `fov_deg()` | ` 键公开入口；灵敏度读写（限 [0.01,0.30] 度/像素）；FOV 恒 85 |
| | `set_render_enabled(on)` | 渲染开关（按钮点击与外部控制共用） |
| | `set_spectator_input_locked(on)` / `spectator_input_locked()` | 旁观者输入总闸（见上文） |
| 模型装填 | `_load_model(model, key, variant_n)` | set_structure/set_model 公共段：复位轮播/失败标记/箱子数据、启动轮播、相机复位、旁观者 reposition、标记 `_needs_upload` |
| 相机 | `_reset_camera_for_model` / `_adapt_camera_for_model` | 全复位 / 变种轮播保持方位只适配中心半径 |
| 交互 | `_orbit(dx,dy)` / `_pan_screen(d)` / `_eye_pos()` | 环绕旋转 / 平移 / 相机眼位（dist 缺省 radius*2.2） |
| | `_screen_angle()` / `_orbit_cursor()` | 北向屏幕投影角 / 旋转光标位图生成 |
| | `mouseDoubleClickEvent` / `mousePressEvent` / `mouseReleaseEvent` / `mouseMoveEvent` / `wheelEvent` | 双击复位（旁观者吞掉）；sp 分支：锁定态吞、准星态右键开箱、未控制态点击即锁定；orbit 分支：右键设旋转光标、move 驱动 orbit/pan 并 `_pause_rotation`；滚轮两分支分别调速/缩放 |
| | `keyPressEvent` / `keyReleaseEvent` / `focusOutEvent` | sp 模式键处理（键集合存 int，PySide6 枚举 hash 与 int 不同必须双侧统一 int；` ` / Esc / E / 移动键分流，自动重复与锁定期分流）；失焦松键 |
| 旁观者 | `_spectator_enter/exit/reposition` | 进入复位眼睛到模型前缘 / 退出停定时器清元键还原相机 / 按体素范围重置眼睛姿态与速度 |
| | `_spectator_grab_mouse` / `_spectator_release_mouse` / `_spectator_recenter` / `_spectator_pin_tick` / `_spectator_toggle_grab` | 锁定（回中+隐藏+启动钉扎）/ 呼出 / 钉回中心（可重置基准）/ 直读光标位移转视角后钉回 / 切换 |
| | `_spectator_tick` / `_spectator_idle_check` / `_sp_dir` / `_sp_start_loop` | FP 飞行积分 / 低频心跳兜底 / 视线向量 / 有键启动 tick+心跳 |
| | `_spectator_update_crosshair` / `_draw_crosshair(p)` | slab 法准星命中重判 / 屏幕中心十字绘制（fillRect 双层） |
| | `_spectator_apply_refresh_rate` | 记录所在屏刷新率（仅诊断展示，不再节流定时器） |
| 轮播 | `_pause_rotation` / `_resume_rotation` / `_cycle_variant` / `_stop_spin_timers` | 交互暂停 + 4s 单发恢复 / 到点切下一变种（保持方位适配） / 停定时器 |
| GL | `initializeGL` | 取 `context().functions()`；ctypes 解析原生 glDrawElements；编译 `_VS+_FS`/`_VS+_FS_WATER`/`_plain` 三套 shader（显式绑属性 0..3）；建 VAO/VBO/IBO/锚点/区块 VBO；`_build_atlas` 上传图集；缓存 uniform 定位；设静态状态与静态 uniform（uModel 单位阵、uLightDir=(-0.45,0.85,0.28)、清屏色） |
| | `_upload_model` | 材质槽→图集槽号表；水区间参数；`_bake_tile_origin` 顶点 8→10 列烘焙；chunk/occl 数据注入（含 `_occl_opaque` 由 `sm._mat_shape` + `sm._TRANSPARENT_MATS` 判定）；销毁重建缓冲；numpy tobytes 直传 VBO/IBO（dtype 定 GL 类型）；设属性指针；计算锚点/区块线几何并上传两个线框 VBO |
| | `_occl_cells_for_eye` | MC 洞穴剔除 BFS 移植（详见渲染管线第 5 步），返回允许 chunk 序号集或 None |
| | `_draw_model_body(mvp, occl_cells)` / `_draw_guide_lines(mvp)` / `_draw_water(mvp)` | 见渲染管线第 5/6/7 步 |
| | `_handle_render_failure(msg)` / `paintGL` | 错误统一处理 / 渲染主循环（详见渲染管线） |
| | `resizeEvent` / `showEvent` / `hideEvent` / `event` | 按钮重定位 / 恢复轮播 + 刷新率记录 / 停轮播 + 旁观者还原鼠标 / ScreenChangeInternal 记录刷新率 |
| 模块级 | `_build_atlas()` / `_bake_tile_origin(...)` / `_VOIDP(off)` / `_seq_len(seq)` | 图集拼装 / 顶点烘焙 / ctypes 偏移包装 / numpy 安全 len |

**接口**（grep 核实）：被 2 个工具模块 import：
- `Tools/tool_SeedReverser.py:65`（批量 import）→ line 436 实例化 `self._anchor_view = structure_3dview.Structure3DView()`，连接 `render_error`（line 439），`set_structure(key, name)`（line 1262/1269），退出时 `stop_variant_timer()`（line 2386）——SeedReverser 主界面的锚点 3D 视口（环绕模式）；
- `Tools/tool_StructurePreviewer.py:56` → line 1100 实例化 `self._view`，连接三个信号（1102-1105），`set_spectator_mode(True)`（1107）、`set_spectator_sensitivity`（1296）、`set_model`（1637）、`set_chest_highlights`（1640/1866）、`set_interact_chests`（1645）、`note_chest_gui_closed`（1799）、`set_spectator_input_locked`（1831/1848）、`is_spectator_mode`/`spectator_toggle_grab`（1875/1880）——StructurePreviewer 的 FP 飞行 + 开箱场景。
- 另 `Utils/StructurePreviewer/composition.py:2806` docstring 说明其输出格式即 `structure_3dview.set_model` 格式（数据契约，非代码 import）。
- 对外提供：`Structure3DView` 类（上述全部公开方法与信号）、模块级 `_build_atlas`/`_bake_tile_origin`、`TEX_DIR`（转出 `sm.TEX_DIR`）。

**关键变量/常量**：

| 名称 | 值 | 说明 |
|---|---|---|
| `TEX_DIR` | `sm.TEX_DIR` | 方块纹理目录（`assets/SeedReverser/textures/block`），`_build_atlas` 扫描源 |
| `_ATLAS_COLS` / `_ATLAS_ROWS` / `_ATLAS_TEX` | 16 / 32 / 16 | 图集 16×32=512 槽（原 256 槽被 272 张纹理击穿后扩容，注释留有越界回绕实证）；每纹理边长 |
| `_VS` / `_FS` / `_FS_WATER` | GLSL 120 源码 | 顶点 / 主体片元（discard+光照）/ 水片元（alpha 0.62）；SLOT_W/H 硬编码 |
| `_ANCHOR_RED` / `_CHUNK_YELLOW` / `_CHEST_AMBER` | `#E5484D` / `(255,214,0)` / `#F1C40F` | 锚点红线 / 区块黄框 / 箱子高亮描边 |
| `_FPS_OK` / `_FPS_BAD` / `_FPS_BAD_TH` | 暗绿 / 红 / 30.0 | FPS 显示配色与掉帧预警阈值 |
| `_SP_FLY_MIN` / `_SP_FLY_MAX` | 1.0 / 120.0 | 飞行速度限位（格/秒） |
| `_SP_MOUSE_SPEED` / `_SP_MOUSE_MIN` / `_SP_MOUSE_MAX` | 0.05 / 0.01 / 0.30 | 鼠标转视角灵敏度（度/像素）默认与限位 |
| `_SP_PITCH_MAX` | 89.9 | FP 俯仰限位（不翻转） |
| `_SP_IDLE_MS` / `_SP_WHEEL_STEP` / `_SP_FLASH_MS` | 120 / 1.1 / 1400 | 心跳间隔 / 滚轮每格速度倍率 / 调速提示残显 |
| `_SP_FOV` | 85.0 | 视场角（orbit 与 FP 共用） |
| `_VSYNC` | 0 | swapInterval：解除垂直同步 |
| `_SP_LOGIC_HZ` | 500.0 | 逻辑 tick 频率（位移积分/渲染调度），交互帧率上限 ≈ min(此值, GPU 能力) |
| `_SP_HZ_MIN` / `_SP_HZ_MAX` | 60.0 / 240.0 | 屏幕刷新率读取兜底/钳制（仅诊断展示） |
| `_SP_START_SPAN` / `_SP_START_LARGE` / `_SP_START_SMALL` | 40.0 / 10.0 / 5.0 | 旁观者初始眼高分档（大型/小型结构） |
| `_SP_CHEST_DIST` | 4.0 | 开箱准星判定距离（格） |
| `_VARIANT_MS` / `_INTERACT_RESUME_MS` | 2500 / 4000 | 变种轮播间隔 / 交互停手后恢复轮播等待 |
| `_CURSOR_PIX` / `_CURSOR_N_ARM` / `_CURSOR_W_ARM` / `_CURSOR_N_LETTER` / `_CURSOR_W_LETTER` | 56 / 线段元组 | 旋转光标位图边长与北/西箭臂、N/W 字母线段几何 |
| `render_error` / `chest_open_requested` / `spectator_close_request` | Signal | 类信号（str / int / 无参） |
| `_SP_K_*` | 类属性 int | 键位常量（W/A/S/D/方向键/Space/Shift/QuoteLeft/AsciiTilde/Esc/E），统一 int 化规避 PySide6 枚举 hash 问题 |
| 实例字段 | `_chunks/_occl/_occl_opaque/_occl_cache_*` | chunk 剔除数据 / 逐 section 可见性矩阵 / 阻挡格集合 / 眼 section BFS 缓存 |

---

## `Utils/SeedReverser/structure_preview.py`

**功能**：SeedReverser 结构锚点示意图的 **QPainter 2D 渲染器**（Wiki 渲染图 + 真实方块纹理俯视图）。布局（用户定稿）：顶部标题（结构名 + W×D×H 与 Y 范围）；左侧 Wiki 信息框等轴测渲染图（`assets/SeedReverser/previews/<key>.png`）；右侧俯视图（上=北、左=西），每个非空格按最高层方块贴真实纹理（`assets/SeedReverser/textures/block/<方块名>.png`，自客户端 jar 提取；纹理缺失回退 `BLOCK_COLORS` 色块）；锚点 = 俯视图左上角 (0,0) 红框 + 描边文字"锚点(0,0)"（锚点恒等于结构包围盒西北角 = cubiomes 生成锚点）。无渲染图的蓝图（ocean_ruin warm/cold 等）俯视图占满整幅；拼装结构（无整体蓝图）有渲染图则铺满 + "内部布局随机拼装"说明，否则虚线外框示意。数据来自 `structure_blueprints`。
> 注：SeedReverser 主界面已由 `structure_3dview` 3D 视口取代此平面示意图（tool_SeedReverser.py:1257 注释），但模块仍被 import 保留；`structure_models.py:1046` 的 wiki 人话名→纹理键函数与 `_norm_block` 保持同一归一化规则。

**绘制流程**：
1. `render(key, name, width, height, dpr)` 入口：宽或高 < 40 返回空 QPixmap；建 `QPixmap(width*dpr, height*dpr)` 并 `setDevicePixelRatio(dpr)`（高分屏物理像素渲染），透明填充；开 QPainter（Antialiasing/TextAntialiasing/SmoothPixmapTransform 三 hint）。
2. `sb.blueprint(key)` 有数据 → `_render_blueprint`：内容区留 margin/标题区/说明区，有渲染图则左半 `_draw_preview`（等比缩放居中 + "Wiki 渲染图"叠底说明）、右半 `_draw_top_view`；无渲染图俯视占满；最后 `_draw_title` 画标题 `"{name}  W×D×H（Y y0~y1）"`。
3. `_draw_top_view`：cell = `max(2, min(rect宽//W, rect高//D, 24))`；先画主题色外框；逐格遍历 `tcol`（`.` 跳过）：每种调色板字符的纹理**只缩放一次**（`_tex_pixmap` 取 16×16 原图 → `scaled(cell*dpr)` 平滑缩放 + `setDevicePixelRatio(dpr)` 物理像素对齐），有纹理 `drawPixmap`，缺失回退 `_block_color` 色块 `drawRect`；下方 `_draw_caption`"俯视（上=北，左=西）"；`_draw_anchor_mark` 画锚点红框（cell+1 外扩 0.5px）+ 右侧描边文字。
4. `sb.blueprint(key)` 为 None → `sb.fallback_size(key)` 取尺寸走 `_render_fallback`：有渲染图铺满 + 叠底说明"Wiki 渲染图（内部布局随机拼装）"；否则按 `min(area宽/W, area高/D, 3.0)` 比例画虚线外框 + 中线淡虚线 + 居中文字"内部布局随机拼装（示意）" + 左上角锚点角标（7×7 红框 + 描边文字）+ 底部说明 + 标题"约 W×D×H（示意）"。尺寸都缺失则返回空 QPixmap。
5. 辅助绘制：`_draw_title`（13px 加粗居中）/`_draw_caption`（10px 区域下方居中小字，`over=True` 叠图时加主题 Window 底衬）/`_draw_outlined_text`（QPainterPath 文字 + 3px `_ANCHOR_OUTLINE` 深色描边，叠地图上仍可读）。

**类与函数**（无类，全部模块级）：

| 名称 | 签名 | 说明 |
|---|---|---|
| `render` | `(key, name, width, height, dpr=1.0) -> QPixmap` | 唯一公开入口：渲染整幅示意图（见上流程）；尺寸过小或无数据返回空 QPixmap |
| `_theme_color` | `(alpha=255) -> QColor` | 应用主题 WindowText 色（无 QApplication 时回退中性灰） |
| `_norm_block` | `(name: str) -> str` | Wiki 方块名 → 纹理文件键：strip+lower → 去 `entitysprite:` 前缀 → 去 `-rotNNN` 旋转后缀（rpartition 校验尾段全数字） |
| `_block_color` | `(bp, ch) -> QColor` | 纹理缺失时的回退色：palette 查名 → `_norm_block` → `BLOCK_COLORS`，未收录回退 NEUTRAL |
| `_preview_pixmap` | `(key) -> QPixmap \| None` | 结构键 → Wiki 渲染图（`_PREV_CACHE` 单条缓存；原图超 `_PREV_WORK_MAX=1024` 边长先一次性 Smooth 降采样为工作副本，避免大图反复缩放；缺失/解码失败返 None 且不缓存） |
| `_tex_pixmap` | `(name) -> QPixmap \| None` | 归一化名 → 16×16 纹理 QPixmap（`_TEX_CACHE` 全量缓存，缺失项也缓存 None 避免重复探测） |
| `_pt` | `(x, y) -> QPointF` | 坐标便捷构造 |
| `_draw_title` / `_draw_caption` / `_draw_outlined_text` / `_draw_anchor_mark` | `(p, ...)` | 标题 / 小字说明（可叠图带底衬）/ 描边文字 / 锚点红框+文字 |
| `_draw_preview` | `(p, key, rect) -> bool` | rect 内等比缩放绘制渲染图（`_PREV_SCALED` 单条缓存，key+宽高命中即复用，避免窗口拖拽反复平滑缩放）；居中；无图/极端小尺寸返回 False |
| `_draw_top_view` | `(p, bp, rect, dpr)` | 纹理俯视图（见绘制流程第 3 步） |
| `_render_blueprint` | `(p, key, bp, rect, name, dpr)` | 精确蓝图模式整幅布局（见第 2 步） |
| `_render_fallback` | `(p, key, rect, name, size)` | 拼装结构兜底（见第 4 步） |

**接口**（grep 核实）：
- import 方：`Tools/tool_SeedReverser.py:66`（`from Utils.SeedReverser import (seed_math, structure_3dview, structure_preview)`）——仅保留 import，主界面平面示意图已被 3D 视口取代（tool 内无调用点，注释 line 1257 说明）；无其他模块 import。
- 被依赖方：自身 import `structure_blueprints as sb`（蓝图与配色数据源）。
- 对外提供：`render()` 整幅渲染入口与资产路径常量。

**关键变量/常量**：

| 名称 | 值 | 说明 |
|---|---|---|
| `PREVIEW_DIR` | `<项目根>/assets/SeedReverser/previews` | Wiki 渲染图目录（`<key>.png`） |
| `TEX_DIR` | `<项目根>/assets/SeedReverser/textures/block` | 方块纹理目录（模块内自定义，与 `structure_models.TEX_DIR` 同路径） |
| `_ANCHOR` / `_ANCHOR_OUTLINE` | `#E5484D` / `#1B1E22` | 锚点标记红（主题无关强调色）/ 文字描边（深浅底均可辨） |
| `_PREV_CACHE` | `{"key","pm"}` | 渲染图单条缓存（原图解码开销高，切换结构只保留当前一份） |
| `_PREV_SCALED` | `{"key","w","h","pm"}` | 渲染图缩放缓存（单条，防 resize 反复缩放） |
| `_TEX_CACHE` | dict | 方块纹理全量缓存（16×16 小图；缺失项缓存 None） |
| `_PREV_WORK_MAX` | 1024 | 工作副本最大边长（原图超限先一次降采样） |

# 9. 结构预览器逻辑层（Utils/StructurePreviewer）

# StructurePreviewer 组装层文档 09a：composition.py

## `Utils/StructurePreviewer/composition.py`

**功能**：结构预览器的组装中枢（结构构造组合层）。输入「世界种子 + 结构锚点方块坐标（+ 锚点群系 id + 版本键）」，输出两样东西：

1. `Composition`（`compose()`）——一次结构的完整构造组合：模板变种（variant）、放置旋转（rotation/mirror）、部件（Piece）布局、每个箱子的世界坐标 + 战利品表 + 无符号 64 位 `LootTableSeed`；
2. 3D 视口显示模型（`compose_display_model()`）——`structure_3dview.set_model` 格式的体素模型 dict（`voxels/size/mesh/tex_keys/chests/chest_blocks/anchor/anchor_y/...`）。

覆盖 12 个结构键：`igloo`（雪屋）、`shipwreck`（沉船）、`nether_fortress`（下界要塞）、`bastion_remnant`（堡垒遗迹）、`end_city`（末地城）、`trial_chambers`（试炼密室，1.21+）、`pillager_outpost`（掠夺者前哨站）、`stronghold`（要塞）、`woodland_mansion`（林地府邸）、`ocean_ruin`（海底废墟/水下遗迹）、`ancient_city`（远古城市）、`village`（村庄）。

实现原理——按结构类型分三种范式：

- **公式直算**（igloo / shipwreck）：把 xpple/cubiomes fork（commit 5815e4f）`finders.c` 的 `getVariant` / `getStructurePieces` 公式逐行转写。RNG 流 = `structure_map.chunk_generate_rnd(world_seed, cx, cz)` 产出的区块流（1.18+ 为 Xoroshiro128++），变种选择、部件锚点、箱子坐标全部由 `mc_random.next_int / next_double / next_float / next_bits` 按固定顺序消耗；`LootTableSeed` 由 `loot_rng` 的 population 装饰流（`get_population_seed + decorator + 10000*step`）推导。
- **程序化逐 piece 拼装**（nether_fortress）：xp fork `features/fortress.c` 的 `getFortressPieces` 全套转写——起始件 + 碰撞检测（AABB 闭区间比较）+ 权重选型 + 队列随机取出循环；显示层再由 `fortress_pieces.build_fortress_voxels` 按 `NetherFortressPieces.java postProcess` 逐方块展开。
- **jigsaw 拼装委派**（bastion / end_city / trial_chambers / pillager_outpost / ancient_city / village / stronghold / woodland_mansion）：piece 树生成委派给兄弟模块（`jigsaw_assembly.assemble_bastion`、`end_city_pieces.build_end_city`、`trial_assembly.assemble_trial_chambers`、`outpost_assembly.assemble_outpost`、`ancient_city_assembly.assemble_ancient_city`、`village_assembly.assemble_village`、`stronghold_pieces`、`mansion_pieces.assemble_mansion`，各自与游戏同 RNG 流并对拍过）；本层负责：起点变量流的消耗口径（rotation/start/start_y 的 nextInt 顺序，与 `structure_map` 的变种流同序）、模板 NBT 容器扫描（chest/barrel/DATA 标记，带 LootTable 字段才进预测、才消耗流）、按「piece 序 × 块内 (Y,X,Z)」分区块连抽装饰流 `next_long()` 生成每箱 `LootTableSeed`、以及 `EndPiece/jp` → `Piece/Chest` 的数据结构转换。

显示模型约定：体素 dict `{(x, y, z): 材质键}`，x 东 / y 上 / z 南；材质键为小写字符串（完整方块）或 `(材质名, 形状码)` 元组（楼梯/台阶等非完整方块）。模型坐标 = 世界坐标 − anchor − start_off（jigsaw 类再减 y 基准面：64 / start_y / 90）。箱子标注（`chests` 高亮 + 回填 `Chest.pos_model`）分三种匹配：fortress 用全局 1:1 贪心近邻（切比雪夫 ≤8，xp 公式坐标与 Java 布局有已知偏差）；bastion/trial/ancient_city/village/stronghold/outpost/mansion/ocean_ruin 走 `pos3` 三维 exact 匹配（RNG 预测与拼装几何同源）；igloo/shipwreck/end_city 走通用 xz 匹配模板内 chest 体素（取其实际 y）。

版本约束：仅支持 mc ≥ 1.18（Xoroshiro128++ 流）；项目版本线收敛到 1.21 / 1.21.11，全部 salt 落 `loot_rng._SALT_1194` 档。考证基准：xp fork `finders.c`（含 `getStructurePieces` Igloo L3021-3343、Shipwreck、Fortress L3351-3396、Bastion L3397-3505）与各 Java 类（`NetherFortressPieces` / `OceanRuinPieces` / `StrongholdPieces` / `MansionGrid` / `StructureTemplate.transform`）逐行对齐；RNG 消耗序列逐行照抄，函数内注释标注对应 C 源码位置。

**主流程**：

- `compose()`（L2415）：`struct_key` 字符串分派到 12 个 `compose_*` 函数（if 链），未支持键抛 `ValueError`。`biome_id` 仅 shipwreck（搁浅判定）与 village（变体判定）/ocean_ruin（冷暖水判定）需要，缺省 -1。
- `compose_display_model()`（L2805）：按 `comp.struct_key` 分派体素生成（igloo 拼模板 + shipwreck 模板旋转 / fortress·bastion·trial·outpost·stronghold·mansion·ocean_ruin·ancient_city·village 的 `_*_voxels` 转写 / end_city 的 `end_city_pieces.end_city_voxels`）→ min_x/min_z 归一化到非负象限并补偿 `start_off` → 计算 `size/min_y` → 箱子标注匹配（分结构三路）→ 确定 `anchor_y`（igloo/ocean_ruin=90，shipwreck 及 nether 类=64，trial/ancient_city/village=`extra["start_y"]`）→ `chest_blocks`（渲染体素中全部容器方块，3D 开箱准星交互全集）→ `tex_keys` → `structure_models.build_mesh` → 返回模型 dict（含 `anchor_local=-start_off` 与 `chunk_origin=anchor_local % 16`，供注入模式的区块黄框相位对齐）。

---

**类与函数**

### 数据结构（dataclass）

| 名称 | 签名 | 说明 |
|---|---|---|
| `Chest`（L74） | `Chest(pos: tuple[int, int], loot_table: str, loot_seed: int, pos_model: tuple[int,int,int] \| None = None, pos3: tuple[int,int,int] \| None = None)` | 一个箱子。`pos` 为世界 (x, z)（getStructurePieces 公式值，RNG 用此坐标）；`loot_seed` 为无符号 64 位 LootTableSeed（显示用 `loot_rng.signed_seed` 转有符号）；`pos_model` 由 `compose_display_model` 回填（模型内三维坐标）；`pos3` 为世界 (x, y, z)，bastion 等全箱子预测填充——同 (x,z) 不同 y 的叠柱箱匹配需要 y |
| `Piece`（L92） | `Piece(name: str, pos: tuple[int,int,int], chests: list[Chest] = [], type/rot/depth/bb/chest_count/self_seed 默认 None)` | 一个结构部件（对应 finders.c 的 Piece）。`pos` 为世界锚点 (x, y, z)；`type/rot/depth/bb/chest_count/self_seed` 仅下界结构（fortress）填充：rot（起始件即结构 rotation）、bb 为 (bb0, bb1) 闭区间包围盒（bb1=Java maxX 语义的含端点最大角，NeStart 的 18 实占 19 格）、chest_count 为拐角件 `nextInt(3)==0` 的带箱标记、self_seed 为 FORTRESS_END 捕获的 32 位 RNG 输出（`BridgeEndFiller` 重建随机填桥用） |
| `Composition`（L113） | `Composition(struct_key: str, variant_name: str, rotation: int, mirror: bool, anchor: tuple[int, int], pieces: list[Piece], extra: dict = {})` | 一次 compose 的完整结果。`mirror` 仅 igloo 使用（cubiomes 用 mirror 编码 180°）；`extra` 为各结构私有信息（basement/size/sw_typ/start_y/portal_eyes 等）。属性 `chests`（L123）＝各 piece 箱子按序展平 |

### igloo（雪屋）

| 名称 | 签名 | 说明 |
|---|---|---|
| `compose_igloo`（L143） | `compose_igloo(world_seed: int, block_x: int, block_z: int, version_key: str = "1.21") -> Composition` | 雪屋全量组合（变种 + 部件布局 + 地下室箱子 LootTableSeed）。核心流程见下 |

`compose_igloo` 流程（RNG 消耗顺序，全部照抄 finders.c）：
① `min_bx/min_bz = block & ~15`；② `chunk_generate_rnd(seed, x>>4, z>>4)` 建流；③ `rot_raw = nextInt(4)`（经 `_IGLOO_ORIENT` 映射为 rotation∈{0,1} + mirror）；④ `basement = nextDouble() < 0.5`（有无地下室）；⑤ `size = nextInt(8) + 4`（竖井 middle 段数）。部件布局：top 在 `(min_bx, 90, min_bz)`；有地下室时 middle i=1..size 在 `(min_bx+2, 90-3i, min_bz+4)`，bottom 在 `(min_bx, 90-3-3size, min_bz-2)`；bottom 箱子偏移按 `(rotation<<1)|mirror` 查 `_IGLOO_CHEST_SUB`，LootTableSeed 走 `loot_seed_for_chest(..., "igloo", skips=1)`（流中先 skip 1 个 nextLong——placeInWorld 写入的种子未被使用）。`extra = {basement, size, rotation_raw}`。

### shipwreck（沉船）

| 名称 | 签名 | 说明 |
|---|---|---|
| `compose_shipwreck`（L272） | `compose_shipwreck(world_seed: int, block_x: int, block_z: int, biome_id: int, version_key: str = "1.21") -> Composition` | 沉船全量组合。流程见下 |
| `_shipwreck_loot_seeds`（L332） | `_shipwreck_loot_seeds(world_seed: int, chest_world, is_beached: bool, salt_key: str, version_key: str = "1.21") -> list[int]` | finders.c L3210-3339 六分支照抄：按「箱子是否同区块」分组抽 LootTableSeed——同区块组共享一条流（skip 箱数后按序各取 1 个 nextLong），异区块箱各自独立流（skip1 取1）。`_flow(cx,cz)`：population 种子（箱子所在区块角）+ decorator + 10000*step 建流，搁浅时先 `next_int(3)`（updateHeight 消耗） |

`compose_shipwreck` 流程：① `is_beached = biome_id not in OCEANIC_BIOMES`；② `chunk_generate_rnd` 建流；③ `rotation = nextInt(4)`（NONE/CW90/CW180/CCW90）；④ 搁浅时 `start = nextInt(11)` → `sw_typ = _SW_BEACHED_TYPES[start]`（salt 键 `shipwreck_beached`），否则 `start = nextInt(20)` → `sw_typ = start`（salt 键 `shipwreck`）；⑤ 从 `_SW_INFO[sw_typ]` 取模板名/尺寸/箱数/表/箱相对坐标；⑥ piece pos = `(min_bx + _SW_START_POS[rotation][0], 64, min_bz + _SW_START_POS[rotation][1])`；⑦ 各箱世界坐标按 rotation 变换（rot0 `(pos+rel)`、rot1 `(pos_x−cz, pos_z+cx)`、rot2 取反、rot3 交换取反）；⑧ `_shipwreck_loot_seeds` 出全部种子。`extra = {beached, start, sw_typ}`。

### nether_fortress（下界要塞）

| 名称 | 签名 | 说明 |
|---|---|---|
| `_FortressEnv`（L468，class） | `_FortressEnv(state: int)`，`__slots__ = ("state","accepted","queue","ntyp","typlast")` | getFortressPieces 生成环境（对应 FortressPieceEnv）：accepted=已接受 piece（碰撞检测全集）、queue=待处理 FIFO 队列（对应 C 的 list->next 链）、ntyp=各类型已接受计数（15 项）、typlast=最近接受的非 END 类型 |
| `_fortress_piece_aabb`（L486） | `_fortress_piece_aabb(pos: tuple[int,int,int], typ: int, facing: int) -> tuple[tuple, tuple]` | addFortressPiece 包围盒（xp features/fortress.c L42-65）：按 `_FORTRESS_INFO` 的 off/size 与 facing（0北/1东/2南/3西）算 (bb0, bb1)，bb1 为含端点最大角（闭区间语义，与 C 逐行一致） |
| `_fortress_add`（L521） | `_fortress_add(env, typ: int, x, y, z, depth: int, facing: int, pending: bool) -> dict \| None` | xp fork addFortressPiece（L39-107）逐行照抄：先 AABB 碰撞检测（与 accepted 全集比较，命中返回 None 且**不消耗 RNG**）；拐角件（CORRIDOR_TURN_*）碰撞通过后真实消耗 `nextInt(3)` → chest_count（v==0 有箱）；FORTRESS_END 用 `mc_random.next_bits(state, 32)` 捕获 32 位输出作 self_seed（流演进等价 skipNextN(rng,1)）；pending=True 才入 accepted/queue 并更新 ntyp/typlast。与主 fork 的差异：主 fork 用 skip 列近似拐角箱判定，对拍以 xp fork 为准 |
| `_fortress_extend`（L563） | `_fortress_extend(env, p: dict, offh: int, offv: int, turn: int, corridor: int) -> None` | extendFortress（L110-175）逐行照抄：按 turn（0 前进 / −1 左 / +1 右）和 facing 算新锚点；距起始件锚点 x 或 z 超 112 → 加 FORTRESS_END（pending=False，消耗 RNG 但不入队）；走廊/桥候选类型区间 `[typ0, typ1)`（corridor 时 CORRIDOR_STRAIGHT..CORRIDOR_NETHER_WART，桥时 BRIDGE_STRAIGHT..BRIDGE_CORRIDOR_ENTRANCE），排除达 max 上限者后累计权重；`valid==0 or weight_tot<=0 or depth>30` → END（pending=True）；否则最多 5 轮 `nextInt(weight_tot)` 选型（与 typlast 相同且不可 repeat 则 break 重抽），`_fortress_add` 成功即返回，5 轮全败 → END |
| `_fortress_extend_piece`（L631） | `_fortress_extend_piece(env, p: dict) -> None` | extendFortressPiece（L177-213）逐行照抄：按 piece 类型调 `_fortress_extend` 的组合（如 BRIDGE_CROSSING/START 三向扩展、CORRIDOR_CROSSING 三向、T_CROSSING 先各消耗 `nextInt(8)` 决定走廊/桥、NETHER_WART 上下两层）；FORTRESS_END 无分支、处理时不消耗 RNG |
| `compose_nether_fortress`（L674） | `compose_nether_fortress(world_seed: int, block_x: int, block_z: int, version_key: str = "1.21") -> Composition` | 要塞全量组合。流程见下 |

`compose_nether_fortress` 流程（RNG 消耗顺序）：① `cx, cz = block_x>>4, block_z>>4`，`chunk_generate_rnd(seed, cx, cz)` 建流；② 起始件（C L241-260）：pos `(cx*16+2, 64, cz*16+2)`、bb 18×9×18，`rot = nextInt(4)`；③ 主循环 `while queue`：`idx = nextInt(len(queue))` 随机取出一件（对应 Java `queue.remove(randomIndex)`）、`_fortress_extend_piece` 扩展；防御上限 `_FORTRESS_MAX_STEPS=100000`；④ 箱子（xp finders.c L3351-3396）：仅拐角件且 chest_count 的有箱，表 `chests/nether_bridge`，坐标 = `(pos.x−1+dx, pos.z−1+dz)`（`_FORTRESS_CHEST_OFF` 按 rot 取），每箱独立区块流 `loot_seed_for_chest(..., "nether_fortress", 0, version_key)`（skip 0，C 注释假设无两 piece 箱同区块）。`extra = {n_pieces, n_chests}`；`rotation` = 起始件 rot。

### bastion_remnant（堡垒遗迹）

| 名称 | 签名 | 说明 |
|---|---|---|
| `compose_bastion_remnant`（L774） | `compose_bastion_remnant(world_seed: int, block_x: int, block_z: int, version_key: str = "1.21") -> Composition` | 堡垒全量组合（全箱子战利品预测）。流程见下 |
| `_piece_chests_world`（L862） | `_piece_chests_world(piece) -> list[tuple[tuple[int,int,int], str]]` | jigsaw piece 内全部 chest 方块 → 世界坐标：`_template_chests`（NBT 直扫缓存）取局部坐标 + 表名，`jigsaw_assembly.rot_piece_pos` 旋转（与渲染体素同一变换）+ piece_pos 平移，按世界 (Y,X,Z) 升序返回 |
| `_template_chests`（L888） | `_template_chests(key: str) -> tuple` | bastion 模板 NBT 内全部 `minecraft:chest`（jigsaw/spawner 非 RandomizableContainer 不消耗流）→ `((局部 (x,y,z), "minecraft:chests/…"), ...)`；loot 表取方块 nbt.LootTable（37/37 全有）；结果入 `_BASTION_CHESTS_CACHE` |

`compose_bastion_remnant` 流程（RNG 消耗顺序）：① `chunk_generate_rnd` 建流；② `rotation = nextInt(4)`、`start = nextInt(4)`（getVariant Bastion 1.18+ 先 rotation 后 start，与 `structure_map._bastion_variant` 同流）；③ `variant_name = _BASTION_START_AIR_BASE[start]`（拼装起始 air_base 占位件名，本身无箱子）；④ 调 `jigsaw_assembly.assemble_bastion(world_seed, min_bx>>4, min_bz>>4)` 真实 jigsaw 拼装（与游戏同 RNG 流，reg3 对拍 6/6）；⑤ 逐 piece `_piece_chests_world` 收集全箱记录并按所在区块分组（记录序 = piece 序）；⑥ 每区块一条装饰流 `XoroshiroJava(get_population_seed(world_seed, pcx*16, pcz*16) + decorator(0) + 10000*step(4))`，块内按放置序连抽 `next_long()`（每箱恰好一次；盒外方块被跳过不消耗）；⑦ 每箱填 `pos3`（叠柱箱 y 区分）。`extra = {start, world_seed, xp_variant, xp_rot, n_pieces, n_chests}`——xp_variant/xp_rot 保持 xp 公式流口径（UI 起点类型显示与回归对照），`_BASTION_STARTS` 固定偏移表仅作 test_nether_compose 对拍对照（hoglin_stable/bridge 两型跨区块已弃用）。

### end_city（末地城）

| 名称 | 签名 | 说明 |
|---|---|---|
| `compose_end_city`（L942） | `compose_end_city(world_seed: int, block_x: int, block_z: int, version_key: str = "1.21") -> Composition` | 末地城全量组合。piece 树与箱子/loot 流全部在 `end_city_pieces.build_end_city`（cubiomes finders.c L2336-2595 + xp fork End_City 分支转写），本层仅做 EndPiece → Piece/Chest 转换：piece y 为相对高度（首件 y=0），显示基准面 anchor_y 取 64；`extra = {ship, n_pieces, n_chests, world_seed}`（ship=有无末地船）。显示走 `_ecp.end_city_voxels(comp.pieces, comp.anchor)`，RNG 箱子公式坐标与拼装 chest 体素严格重合（模板 NBT 实锚点 (1,y,1)+无修正旋转 R，43/43 实测命中），走通用 exact 匹配 |

### trial_chambers（试炼密室，1.21+）

| 名称 | 签名 | 说明 |
|---|---|---|
| `compose_trial_chambers`（L976） | `compose_trial_chambers(world_seed: int, block_x: int, block_z: int, version_key: str = "1.21") -> Composition` | 试炼密室全量组合（jigsaw 拼装 + 全容器预测）。流程见下 |
| `_piece_containers_world`（L1048） | `_piece_containers_world(piece) -> list` | trial piece 内带 LootTable 的容器 → 世界坐标：`_trial_template_containers` 缓存扫描 + `rot_piece_pos` 变换，按世界 (Y,X,Z) 升序 |
| `_trial_template_containers`（L1074） | `_trial_template_containers(key: str) -> tuple` | trial 模板 NBT 直扫：容器 = `minecraft:chest`/`minecraft:barrel`（`_TRIAL_CONTAINER_MATS`，均 RandomizableContainer 同 postProcess 写种子路径），**仅 NBT 带 LootTable 字段的入列表**（30 chest + 3 barrel 中仅 14 个有字段；19 个无字段 chest 游戏内为空箱不消耗流；2 个 vault 走交互系统不进预测）；路径经 `trial_assembly.ASSET_DIR` |

`compose_trial_chambers` 流程（RNG 消耗顺序）：① `chunk_generate_rnd` 建流；② `y_raw = nextInt(21)` → `start_y = y_raw − 40`（start_height uniform）；③ `rotation = nextInt(4)`；④ start 消耗在 `assemble_trial_chambers` 引擎内（`nextInt(2)`，chamber/end 池 end_1/end_2 等权；alias 流独立重建不耗主流）；⑤ 容器收集按 piece 序分区块；⑥ 每区块装饰流 = `population + decorator(4) + 10000*step(3)`（salt `trial_chambers=(3,4)`），块内按放置序连抽 nextLong。`extra = {start, world_seed, start_y, n_pieces, n_chests}`；variant_name = `"trial_chambers/" + 起点模板 key`。

### pillager_outpost（掠夺者前哨站）

| 名称 | 签名 | 说明 |
|---|---|---|
| `compose_pillager_outpost`（L1135） | `compose_pillager_outpost(world_seed: int, block_x: int, block_z: int, version_key: str = "1.21") -> Composition` | 前哨站全量组合（1.21.11 语义）。流程见下 |
| `_outpost_piece_containers_world`（L1205） | `_outpost_piece_containers_world(piece) -> list[tuple[tuple[int,int,int], str, int]]` | piece 箱子（DATA 标记语义）→ (世界 (x,y,z), 表, 子模板序)：单模板 piece 走防御式 chest 扫描；list piece（towers）按 watchtower + overgrown 子模板依序展开（DATA 标记 Chest* 在 watchtower @(9,14,10)），overgrown 箱子先过 `outpost_assembly.apply_outpost_rot`（95% 蚀掉→不写不消耗，保留则记录）；排序键 = (子模板序, Y, X, Z)（Java 依序两次 placeInWorld） |
| `_outpost_template_containers`（L1239） | `_outpost_template_containers(key: str) -> tuple` | 前哨站模板 NBT：watchtower 系无真实 chest 方块，由 DATA 标记 jigsaw（name 以 `Chest` 开头且 `final_state == "minecraft:chest"`）按标记位产出箱子记录（表取 nbt.LootTable，缺省 `minecraft:chests/pillager_outpost`）；普通模板防御式扫 nbt.LootTable 的 chest |

`compose_pillager_outpost` 流程（RNG 消耗顺序）：① `chunk_generate_rnd` 建流；② `rotation = nextInt(4)`（start pool 单元素 base_plate 的 `nextInt(1)` 在拼装引擎内消耗；start_height absolute(0) 零消耗；起点底面 = 地表平坦基准 63）；③ `assemble_outpost` 拼装；④ 容器收集按 (子模板序 × 块内 (Y,X,Z)) 分区块；⑤ 每区块装饰流 salt `pillager_outpost=(4,9)` 连抽 nextLong；⑥ 同 `pos3` 后写覆盖（overgrown 箱保留时替换 watchtower 箱方块，**两条记录都真实消耗装饰流**，去重仅作用于呈现层，不影响消耗序与后续种子偏移），以 `chests_by_pos` dict 实现。`extra = {start: 0, world_seed, n_pieces, n_chests}`。

### 显示辅助（跨结构共用）

| 名称 | 签名 | 说明 |
|---|---|---|
| `_is_chest_value`（L1315） | `_is_chest_value(v) -> bool` | 体素值是否容器方块（`chest/trapped_chest/barrel`，`_CHEST_MATS`）；兼容纯字符串与 `(纹理, 形状)` 元组 |
| `_igloo_model_parts`（L1325） | `_igloo_model_parts(comp: Composition) -> list[tuple[str, int, int, int]]` | 雪屋显示部件清单 [(模板文件名, dx, dy, dz)]：锚点偏移照抄 finders.c（top (0,0,0) / middle i (+2,−3i,+4) / bottom (0,−3−3size,−2)），无地下室仅 top；模板名取 `structure_models.TEMPLATE_FILES["igloo"]` |
| `_rotate_voxels`（L1343） | `_rotate_voxels(voxels: dict, rotation: int, nominal: tuple[int, int] \| None = None) -> tuple[dict, tuple[int, int]]` | 体素按 cubiomes 放置旋转精确变换：R_raw（rot0 (x,z) / rot1 (−z,x) / rot2 (−x,−z) / rot3 (z,−x)，与箱子世界坐标公式同向）；非完整方块元组同步 `block_shapes.shape_rotation` 旋转形状码朝向；返回 (旋转后体素, (平移x, 平移z))，平移 = min 使体素回非负象限，调用方用 startPos + shift 得模型锚点偏移。`nominal=(sx,sz)` 名义包围盒：shift 按完整格点解析式算（rot1 (−(sz−1),0) / rot2 (−(sx−1),−(sz−1)) / rot3 (0,−(sx−1))），用于 degraded 沉船（边缘方块被风化缺失，按实际体素算会把模型错位、区块网格相位偏移） |

### stronghold（要塞）

| 名称 | 签名 | 说明 |
|---|---|---|
| `compose_stronghold`（L1393） | `compose_stronghold(world_seed: int, block_x: int, block_z: int, version_key: str = "1.21") -> Composition` | 要塞全量组合：拼装/loot 流照抄 xp fork features/stronghold.c（`stronghold_pieces.compose_stronghold_pieces`，对拍 probe_sh 8 案例 checks=4206 FAILS=0）；本层逐 piece 转 Piece/Chest，表名按 C loot_tables.c 分档经 `sp.loot_table_for_version`（crossing 恒 1_13、library/corridor 按版本）；anchor = 全 piece bb 的 min(x,z)；箱子 seed `& loot_rng._M64` 归无符号；`extra = {world_seed, chunk, n_pieces, n_chests, portal_eyes}`（portal_eyes 取 SH_PORTAL_ROOM 件的末影之眼数） |
| `_stronghold_voxels`（L1438） | `_stronghold_voxels(comp: Composition) -> tuple[dict, set]` | 要塞显示：重跑 `sp.assemble_stronghold(..., sink_y=True)`（确定性 RNG，结果一致）→ `sp.build_stronghold_voxels(raw, comp.anchor)` 逐 piece postProcess 转写；模型 (x,z)=世界−anchor、y=世界−64（沉降后可为负，display 统一平移）；返回 RNG 箱子 (x,z) 集合供 exact 匹配（RNG 箱子与几何同源：同 piece 序 + 同 rot_pos 变换） |

### woodland_mansion（林地府邸）

| 名称 | 签名 | 说明 |
|---|---|---|
| `compose_mansion`（L1463） | `compose_mansion(world_seed: int, block_x: int, block_z: int, version_key: str = "1.21") -> Composition` | 府邸全量组合：拼装/装饰线全在 `mansion_pieces.assemble_mansion`（MansionGrid + createMansion 转写，对拍 6 案例 ALL PASS）；anchor = 全 piece pos 的 min(x,z)；单一 Piece("woodland_mansion") 承载全部箱子（pos3 填充，seed `& _M64`）；rotation = `mp._ROT_NAMES.index(rot_name)`；loot salt 用 (4,5) 档；`extra = {world_seed, chunk, rot_name, n_pieces, n_chests}` |
| `_mansion_voxels`（L1498） | `_mansion_voxels(comp: Composition) -> tuple[dict, set]` | 府邸显示：重跑 assemble_mansion，逐 piece `mp._load_template` 加载体素（air/structure_void/structure_block 不入），`mp.transform_pos(mirror, rot)` 变换（**镜像先、旋转后**）+ `shape_mirror` + `shape_rotation` 同步形状码；halfheight: 前缀剥除、无形状时补 `_bs.SHAPE_SLAB_BOT`；随机箱（DATA 标记不产出 NBT 方块）按容器记录补写 `"chest"` 体素；y 基准 64；箱子标注走 pos3 exact（chest_offs 仅为接口形状） |

### ocean_ruin（海底废墟）

| 名称 | 签名 | 说明 |
|---|---|---|
| `_ocean_rot_xz`（L1607） | `_ocean_rot_xz(x: int, z: int, rot: int) -> tuple[int, int]` | Java `StructureTemplate.transform`（mirror=NONE、pivot=0）x/z 分量：((x,z), (−z,x), (−x,−z), (z,−x))[rot&3]，与 `_rotate_voxels` 的 R_raw 同向 |
| `_mth_next_int`（L1613） | `_mth_next_int(state: int, lo: int, hi: int) -> tuple[int, int]` | Java `Mth.nextInt(random, min, max)`：min≥max 返回 min 不消耗；否则 `next_int(state, hi−lo+1) + lo` |
| `_ocean_piece_bbox`（L1621） | `_ocean_piece_bbox(p: dict) -> tuple[int, int, int, int]` | piece 世界平面 bbox（getBoundingBox 语义）：对角 = transform(size−1, rot)（big 模板 16×16、small 6×7），fromCorners 取 min/max，x/z 闭区间 |
| `_ocean_piece_in_chunk`（L1632） | `_ocean_piece_in_chunk(p: dict, pcx: int, pcz: int) -> bool` | piece bbox 与区块 [16cx, 16cx+15]² 相交判定（BoundingBox.intersects 同义；postProcess 触发条件） |
| `compose_ocean_ruin`（L1640） | `compose_ocean_ruin(world_seed: int, block_x: int, block_z: int, biome_id: int = -1, version_key: str = "1.21") -> Composition` | 海底废墟全量组合。流程见下 |
| `_ocean_ruin_voxels`（L1811） | `_ocean_ruin_voxels(comp: Composition) -> tuple[dict, set]` | 显示：逐 piece `_load_template_voxels(f"underwater_ruin__{短名}.nbt")`，`_ocean_rot_xz` 旋转（形状码同步 shape_rotation）+ pos 平移，遍历顺序 = pieces 序（后写覆盖先写，cold 三件套同位叠放：mossy 完整覆盖上层、brick/cracked 露出空位）；**未转写 BlockRotProcessor 风化**（integrity 判定流依赖运行时海床沉降 y，平坦预览不可精确复现，cold big 显示为三层并集示意）；DATA 标记箱子补写 chest 体素；y 基准 90 |

`compose_ocean_ruin` 流程（RNG 消耗顺序，OceanRuinPieces.java 逐行照抄）：① `temp = "warm" if biome_id in _OCEAN_WARM_BIOMES else "cold"`（未知 -1 按 cold），salt 键 `ocean_ruin_warm/cold`；② `chunk_generate_rnd` 建流，`rotation = nextInt(4)`；③ `nextFloat()` ≤0.3 → large（主件模板选择在 `_add_piece` 内：warm 大型 `nextInt(4)` 取 big_warm_{4+idx}、小型 `nextInt(8)` 取 warm_{1+idx}；cold 大型 `nextInt(4)` 从 `_OCEAN_BIG_COLD_IDX=(1,2,3,8)` 取 n、小型 `nextInt(8)` 取 1..8，然后 brick/cracked/mossy 三件套连放——**不再消耗 RNG**）；④ large 时 `nextFloat()` ≤0.9 → cluster（&&短路，small 不消耗）；⑤ cluster 时 addClusterRuins：主盒 = anchor 到 transform((15,0,15),rot) 对角盒；8 个候选位各消耗 2 次 `Mth.nextInt`（`_OCEAN_ALLPOS_RULES`），`Mth.nextInt(4,8)` 定数量，每轮 `nextInt(len(cands))` 取点 + `nextInt(4)` 朝向，候选盒（cpos+transform((5,0,6),crot)）与主盒**相交也照常消耗**、只是不放 piece（不相交才 `_add_piece` 小型件）；⑥ 箱子记录：模板无真实容器方块，全部由 "chest" DATA 标记运行时放置，坐标查 `_OCEAN_CHEST_MARKERS`（48 模板扫描实证，每模板 0/1 个，mossy_1 无）经 `_ocean_rot_xz` 变换；⑦ LootTableSeed：按箱子所在区块分组，组内按 `pieces_raw` 序（piece 相交本区块才 postProcess 消耗）抽 `population + decorator + 10000*step` 流的 nextLong；⑧ 生效箱过滤：cold 三件套同位叠放 → 同 pos3 多条记录全消耗（幽灵消耗）但方块后写覆盖，只保留 pi 最大者。`extra = {temp, large, cluster, world_seed, n_pieces, n_cluster, n_chests}`。

### ancient_city（远古城市）

| 名称 | 签名 | 说明 |
|---|---|---|
| `compose_ancient_city`（L1856） | `compose_ancient_city(world_seed: int, block_x: int, block_z: int, version_key: str = "1.21") -> Composition` | 远古城市全量组合。流程见下 |
| `_piece_ac_containers_world`（L1924） | `_piece_ac_containers_world(piece) -> list` | AC piece 内带 LootTable 的 chest（全结构无 barrel，ice_box 也是 chest）→ 世界坐标：list piece（ice_box_1 单子件 / camp 三子件）逐子模板展开，排序键 = (子序, Y, X, Z)；list 子模板无处理器降解（chest 不在 #ancient_city_replaceable，永不蚀空） |
| `_ac_template_containers`（L1957） | `_ac_template_containers(key: str) -> tuple` | AC 模板 NBT：`minecraft:chest`/`trapped_chest` 且 nbt.LootTable 有值才入列（15 chest 中 14 个有字段：13 chests/ancient_city + 1 ancient_city_ice_box；city_center_2 的 1 个无字段=游戏内空箱不消耗流）；key 保留 `ancient_city/` 前缀，路径经 `ancient_city_assembly.ASSET_DIR` |
| `_ancient_city_raw_blocks`（L2008） | `_ancient_city_raw_blocks(key: str) -> dict` | AC 模板 NBT → `{(x,y,z): (方块名, 形状码)}` 原始体素（`_AC_RAW_CACHE` 缓存）；Properties 经 `block_shapes.shape_from_palette` 转形状码供旋转同步 |
| `_ancient_city_jigsaw_voxels`（L2054） | `_ancient_city_jigsaw_voxels(comp: Composition) -> tuple[dict, set]` | AC 显示：重跑 `assemble_ancient_city`（与游戏同 RNG 流，含起点模板 jigsaw 标记洗牌 4 次 + city_anchor 重定位），逐 piece 逐子模板渲染：跳过 `minecraft:jigsaw` 占位，`rot_piece_pos` 旋转 + piece_pos 平移，逐方块 `aca.apply_ancient_city_degradation(nm, wx, wy, wz, variant)`（block_rot 0.95 + rule 链，每方块独立 Mth.getSeed 随机源，variant 按模板 key 定案，None=蚀空跳过），材质 `_map_block`；模型 y 基准 = `extra["start_y"]`（起点件底面） |

`compose_ancient_city` 流程（RNG 消耗顺序）：① `chunk_generate_rnd` 建流；② y = −27（start_height absolute **零消耗**）；③ `rotation = nextInt(4)`（`structure_map._jigsaw_variant` 同序；其内部 nextInt(3) 为包围盒推算消耗不影响 rotation 值）；④ start `nextInt(3)` 在 `assemble_ancient_city` 引擎内消耗（city_center 池三件等权）；⑤ 容器收集按 piece 序分区块；⑥ 每区块装饰流 salt `ancient_city=(7,0)`（decorator 0、step 7）连抽 nextLong。`extra = {start, world_seed, start_y（起点件底面 world y）, n_pieces, n_chests}`。

### village（村庄）

| 名称 | 签名 | 说明 |
|---|---|---|
| `_rotate_props`（L2131） | `_rotate_props(name: str, props: dict, rot_idx: int) -> dict` | 模板 palette props 按放置旋转世界化（处理器在世界坐标作用，blockstate_match 匹配的是旋转后 props）：facing 循环 n→e→s→w（`_FACE_CYCLE`）、axis 奇数 rot 互换 x↔z、水平连接布尔（north/east/south/west，pane/fence/stairs 边）环转 rot_idx 位、rotation 0..15 环值 +4/格；其余属性透传 |
| `_village_raw_blocks`（L2163） | `_village_raw_blocks(key: str) -> dict` | 村庄模板 NBT → `{(x,y,z): (name, props_dict)}` 原始体素（`_VILLAGE_RAW_CACHE` 缓存）；跳过 `minecraft:jigsaw` 占位；props 原样保留（zombie 处理器需完整连接态比较） |
| `_village_template_containers`（L2207） | `_village_template_containers(key: str) -> tuple` | 村庄模板 NBT 内带 LootTable 字段的容器：chest/trapped_chest/barrel 同扫（RandomizableContainer 同路）；无字段（村庄空桶等装饰容器）不入列不消耗流（483 模板实证：62 chest 全带字段、18 barrel 全无字段） |
| `compose_village`（L2259） | `compose_village(world_seed: int, block_x: int, block_z: int, biome_id: int = -1, version_key: str = "1.21") -> Composition` | 村庄全量组合。流程见下 |
| `_village_piece_containers_world`（L2326） | `_village_piece_containers_world(piece) -> list` | 村庄 piece 容器 → 世界坐标：全部池元素为 single/legacy（无 list）、无处理器蚀箱（chest 不在村庄处理器规则输入集），`rot_piece_pos` 变换后按 (Y,X,Z) 排序 |
| `_village_jigsaw_voxels`（L2346） | `_village_jigsaw_voxels(comp: Composition) -> tuple[dict, set]` | 村庄显示：重跑 `assemble_village`（与游戏同 RNG 流），逐 piece 加载 `_village_raw_blocks`，props 先 `_rotate_props` 世界化，逐方块 `va.apply_processor(pid, nm, wprops, wx, wy, wz)`（mossify/farm/street/zombie RuleProcessor，每方块独立 Mth.getSeed 流；None=蚀空跳过）；处理器换方块时按新名重求形状，作物优先 `crop_stage_mat` 动态 age 贴图，非作物回退 `_map_block`；y 基准 = `extra["start_y"]` |

`compose_village` 流程（RNG 消耗顺序）：① `variant = village_assembly.variant_from_biome(biome_id)`（变体由锚点群系决定，meadow 按 plains）；② `chunk_generate_rnd` 建流；③ `rotation = nextInt(4)`；④ start pick（`nextInt(总权重)`，plains 204：4 普通×50 + 4 僵尸×1；僵尸起点 street 标记指向 `<variant>/zombie/streets` 池→完整僵尸链）在 `assemble_village` 引擎内消耗（size=6 / max_dist=80 / start_y=地表平坦基准 63 / expansion_hack=true）；⑤ 容器收集分区块；⑥ 每区块装饰流 salt `village_{variant}`（step 4、decorator 22..26 按变体）连抽 nextLong。`extra = {variant, zombie, start, world_seed, start_y, n_pieces, n_chests}`；variant_name = `"village/{variant}"` + 僵尸起点加 `"/zombie"`。

### 公共入口与显示模型

| 名称 | 签名 | 说明 |
|---|---|---|
| `compose`（L2415） | `compose(struct_key: str, world_seed: int, block_x: int, block_z: int, biome_id: int = -1, version_key: str = "1.21") -> Composition` | 总分派入口：12 个结构键 if 链转发对应 `compose_*`（biome_id 仅 shipwreck/village/ocean_ruin 消费），未支持键抛 `ValueError("composition 未支持的结构键：…")` |
| `_load_template_voxels`（L2457） | `@lru_cache(maxsize=32) _load_template_voxels(fname: str) -> dict` | `structure_models._voxels_from_template_file(TEMPLATE_DIR/fname)` 的 lru 缓存（igloo/shipwreck 显示模板 NBT → 体素 dict）；大视野批量 compose_display_model 时同一模板只解析一次，返回值只读遍历/复制不改内部态 |
| `_fortress_solid_voxels`（L2466） | `_fortress_solid_voxels(comp: Composition) -> tuple[dict, set]` | fortress 显示：`fortress_pieces.build_fortress_voxels(comp)`（按 NetherFortressPieces.java postProcess 逐段转写，坐标映射/朝向变换/箱刷怪笼岩浆等特殊块字节码级核对，遍历顺序 = accepted 序 = postProcess 序）；chest_offs = 有箱拐角件的 (x,z) 集合，供 display 抬高/近邻兜底（xp 箱子坐标与 Java 布局有已知偏差达 7 格） |
| `_trial_raw_blocks`（L2498） | `_trial_raw_blocks(key: str) -> dict` | trial 模板 NBT → 原始体素 dict（`_TRIAL_RAW_CACHE` 缓存；key 剥 `trial_chambers/` 前缀映射 assets/SeedReverser/trial_chambers/templates/） |
| `_bastion_raw_blocks`（L2545） | `_bastion_raw_blocks(key: str) -> dict` | bastion 模板 NBT → 原始体素 dict（`_BASTION_RAW_CACHE` 缓存；降解须在材质映射前按世界坐标判定，故绕过 `_MAT_MAP` 直取 NBT Name） |
| `_bastion_jigsaw_voxels`（L2592） | `_bastion_jigsaw_voxels(comp: Composition) -> tuple[dict, set]` | bastion 显示：重跑 `assemble_bastion`（已对拍 6/6），逐 piece `_bastion_raw_blocks` + `rot_piece_pos` 旋转平移 + `jigsaw_assembly.apply_degradation`（bastion_generic_degradation，每方块独立 Mth.getSeed 随机源）；材质 `_map_block`（黑石系→stone 系风格化）；y 基准 64；箱子标注 (x,z) 并入集合由 display 抬到所在柱顶层 |
| `_trial_jigsaw_voxels`（L2647） | `_trial_jigsaw_voxels(comp: Composition) -> tuple[dict, set]` | trial 显示：重跑 `assemble_trial_chambers`（含 pool_aliases 解析与铜灯降解），逐方块 `ta.apply_trial_degradation`（仅 waxed_copper_bulb 消耗方块随机流，其它零消耗）；材质 `_map_block`（凝灰岩系/铜灯系/vault→stone 已核）；y 基准 = `extra["start_y"]` |
| `_outpost_raw_blocks`（L2703） | `_outpost_raw_blocks(key: str) -> dict` | 前哨站模板 NBT → 原始体素 dict（`_OUTPOST_RAW_CACHE` 缓存） |
| `_outpost_jigsaw_voxels`（L2747） | `_outpost_jigsaw_voxels(comp: Composition) -> tuple[dict, set]` | 前哨站显示：重跑 `assemble_outpost`，逐 piece 展开子模板（list piece = watchtower + overgrown 依序放置，后写覆盖先写）；`minecraft:jigsaw` DATA 标记不渲染占位方块；overgrown 子元素逐方块 `apply_outpost_rot`（95% 蚀空）；箱子体素由容器记录补写（DATA 标记不产出 NBT 方块），旗帜按游戏语义渲染为白色旗帜；y 基准 64（起点底面 63 → 模型 y 从 1 起） |
| `compose_display_model`（L2805） | `compose_display_model(comp: Composition) -> dict` | Composition → 3D 视口显示模型。流程见下 |

`compose_display_model` 流程：① 按 struct_key 生成体素 + start_off（igloo 拼 `_igloo_model_parts` 模板；shipwreck 按 `extra["sw_typ"]` 加载 `shipwreck__<名>.nbt` 后 `_rotate_voxels`（nominal 名义尺寸）+ `_SW_START_POS`；其余各走 `_*_voxels`；end_city 走 `end_city_pieces.end_city_voxels`）；② 体素 min_x/min_z < 0 时整体平移回非负并把平移量补偿进 start_off，算 `size=(宽, y 跨度, 深)` 与 `min_y`；③ 箱子标注匹配并回填 `Chest.pos_model`：nether_fortress 用全局 1:1 贪心分配（全部 (箱子, chest 体素) 对按切比雪夫距离排序、≤8、近距离优先互斥认领）；bastion(基准 64)/trial(基准 start_y)/ancient_city(start_y)/village(start_y)/stronghold(64)/pillager_outpost(64)/woodland_mansion(64)/ocean_ruin(90) 走 `pos3` 三维 exact 匹配；其余（igloo/shipwreck/end_city）走通用路径：mx/mz = pos − anchor − start_off，my 查 `chest_voxel_y[(mx,mz)]`，igloo 单箱无歧义直接用模板内 chest 块（模型未旋转的已知妥协），匹配不到落基准面（igloo 为 −3−3×size，其余 0），nether 键且 (x,z) 在 chest_offs 内时抬到所在柱顶层（bastion 示意体恒走此路的旧口径已由 jigsaw 拼装取代）；④ `anchor_y`：igloo/ocean_ruin=90、shipwreck=64、trial/ancient_city/village=`extra["start_y"]`、其余=64；⑤ `chest_blocks` = 渲染体素中全部容器方块（3D 开箱准星交互全集，bastion 渲染箱可能多于预测箱、未预测的开箱走提示）；⑥ `tex_keys` = 材质基名集合；`mesh = structure_models.build_mesh(voxels)`；⑦ 返回 dict：`{key, variant, voxels, size, min_y, mesh, tex_keys, chests, chest_blocks, anchor, anchor_off(start_off), anchor_y, anchor_local(=−start_off), chunk_origin(=anchor_local % 16), comp}`。

---

**接口**

被以下模块 import：

- `Tools/tool_StructurePreviewer.py`（L58 `from Utils.StructurePreviewer import composition, loot_engine, loot_rng`）：GUI 预览按钮链路 L1632 `composition.compose(...)` → L1636 `composition.compose_display_model(comp)` → `self._view.set_model(model)`，消费 `model["chest_blocks"]` 作开箱准星交互全集、`comp.chests` 弹战利品 GUI、`comp.variant_name/anchor/rotation/mirror` 填信息面板；另在注释/映射中引用 `composition._BASTION_STARTS` 顺序。
- `Utils/StructurePreviewer/locator.py`（L16 `from . import composition, loot_rng`）：`detail()` 调 `composition.compose(struct_key, seed & ((1<<64)-1), ...)`、`locate_with_details()` 调 `composition.compose_display_model(comp)`；类型注解用 `composition.Composition`。
- 其余文件（`stronghold_pieces.py` / `mansion_pieces.py` / `end_city_pieces.py` / `fortress_pieces.py` / `outpost_assembly.py` / `loot_rng.py` / `structure_models.py` / `jigsaw_assembly.py`）仅在模块注释中描述与 composition 的口径约定（如 fortress 的 bb 闭区间语义、bastion 显示基准面），无 import 依赖。

依赖以下模块：

| 模块 | 使用的成员 | 用途 |
|---|---|---|
| `Utils.Public.structure_map` | `chunk_generate_rnd` | 结构区块 RNG 起始流（全部 compose 的第一发消耗） |
| `Utils.SeedReverser.mc_random` | `next_int` / `next_double` / `next_float` / `next_bits` | Xoroshiro128++ 流原语（`(value, state)` 二元组显式传态） |
| `Utils.SeedReverser.structure_models` | `parse_nbt`、`TEMPLATE_DIR`、`TEMPLATE_FILES`、`TEX_DIR`、`_palette_entry_name`、`_palette_entry_props`、`_map_block`、`crop_stage_mat`、`_voxels_from_template_file`、`build_mesh` | 模板 NBT 解析、调色板属性、方块→材质键映射、作物动态贴图、显示模板加载、网格构建 |
| `Utils.SeedReverser.block_shapes`（`bs`） | `shape_rotation` / `shape_mirror` / `shape_from_palette` / `SHAPE_SLAB_BOT` | 非完整方块形状码的旋转/镜像换向与 palette 属性→形状码转换 |
| `Utils.StructurePreviewer.loot_rng` | `loot_seed_for_chest`（igloo skips=1 / fortress skips=0）、`salt_configs_for_version`、`get_population_seed`、`XoroshiroJava`、`_M64` | LootTableSeed 推导（population 装饰流）、版本 salt 表（`_SALT_1194` 档）、64 位无符号归一 |
| `Utils.SeedReverser.jigsaw_assembly`（懒加载） | `assemble_bastion`、`rot_piece_pos`、`apply_degradation` | bastion 拼装引擎、piece 局部旋转（渲染与容器共用同一变换）、bastion 降解 |
| `Utils.StructurePreviewer.end_city_pieces`（懒加载） | `build_end_city`、`end_city_voxels` | 末地城 piece 树与显示体素 |
| `Utils.StructurePreviewer.trial_assembly`（懒加载） | `assemble_trial_chambers`、`apply_trial_degradation`、`ASSET_DIR`、`_split_key` | 试炼密室拼装、铜灯降解、模板资产路径 |
| `Utils.StructurePreviewer.outpost_assembly`（懒加载） | `assemble_outpost`、`apply_outpost_rot`、`ASSET_DIR`、`_split_key` | 前哨站拼装、outpost_rot 腐蚀判定、模板资产路径 |
| `Utils.StructurePreviewer.ancient_city_assembly`（懒加载） | `assemble_ancient_city`、`apply_ancient_city_degradation`、`degradation_variant`、`ASSET_DIR` | 远古城市拼装（含 city_anchor 重定位）、降解链 |
| `Utils.StructurePreviewer.village_assembly`（懒加载） | `variant_from_biome`、`assemble_village`、`apply_processor`、`ASSET_DIR` | 村庄五变体拼装、mossify/farm/street/zombie RuleProcessor |
| `Utils.StructurePreviewer.stronghold_pieces`（懒加载） | `compose_stronghold_pieces`、`assemble_stronghold`、`build_stronghold_voxels`、`loot_table_for_version`、`SH_NAMES`、`SH_PORTAL_ROOM` | 要塞拼装/几何转写/表名分档 |
| `Utils.StructurePreviewer.mansion_pieces`（懒加载） | `assemble_mansion`、`_load_template`、`transform_pos`、`_ROT_NAMES` | 府邸拼装、模板体素、位置变换 |
| `Utils.StructurePreviewer.fortress_pieces`（懒加载） | `build_fortress_voxels` | 要塞显示层逐方块展开 |
| `Utils.SeedReverser.structure_models` 的 `TEX_DIR`（bastion 模板路径拼接） | `os.path.join(TEX_DIR, "..", "..", "bastion", "templates", …)` | bastion 模板 NBT 定位（`_template_chests` / `_bastion_raw_blocks`） |

标准库依赖：`os`、`dataclasses`（`dataclass`/`field`）、`functools.lru_cache`、`pathlib.Path`、`__future__.annotations`。

---

**关键变量/常量**

体素值约定：

| 变量/约定 | 说明 |
|---|---|
| 体素 dict | `{(x, y, z): 材质键}`；x 东 / y 上 / z 南；模型坐标 = 世界 − anchor − start_off（jigsaw 类再减 y 基准面） |
| 材质键取值 | 纯字符串（完整方块，如 `"stone"`、`"chest"`）或 `(材质名, 形状码)` 元组（楼梯/台阶等非完整方块，形状码来自 `block_shapes`） |
| `halfheight:` 前缀 | `_map_block` 返回的半高材质前缀，渲染前剥除；无形状码时补 `bs.SHAPE_SLAB_BOT`（底半格） |
| `Chest.pos` / `pos3` / `pos_model` | 世界 (x,z)（RNG 口径）/ 世界 (x,y,z)（叠柱箱区分）/ 模型内 (x,y,z)（compose_display_model 回填） |
| `Piece.bb` | `(bb0, bb1)`，bb1 = 含端点最大角（Java maxX 语义，闭区间 [bb0, bb1]） |
| anchor_y | igloo/ocean_ruin=90；shipwreck 与 nether/府邸/要塞/前哨站=64；trial/ancient_city/village=`extra["start_y"]`（起点件底面世界 y） |

材质常量：

| 常量 | 值 | 说明 |
|---|---|---|
| `_CHEST_MATS`（L1312） | `{"chest", "trapped_chest", "barrel"}` | 视口认得的容器方块材质键（小写），`chest_blocks` 交互全集与箱子 y 匹配的判定集合 |
| `_NETHER_KEYS`（L1322） | `{"nether_fortress", "bastion_remnant"}` | 下界结构键（显示模型箱子标注 y 抬升到所在柱顶层逻辑用） |
| `_ROT_IDX`（L2494） | `{"NONE":0, "CLOCKWISE_90":1, "CLOCKWISE_180":2, "COUNTERCLOCKWISE_90":3}` | jigsaw 旋转名 → `block_shapes.shape_rotation` 的 0-3 索引（与 cubiomes rot 换向表同序） |
| `_IGLOO_LOOT_TABLE`（L140） | `"chests/igloo_chest"` | 雪屋 bottom 箱战利品表 |
| `_FORTRESS_LOOT_TABLE`（L456） | `"chests/nether_bridge"` | 要塞拐角箱战利品表 |
| `_OCEAN_LOOT_BIG` / `_OCEAN_LOOT_SMALL`（L1603-1604） | `"chests/underwater_ruin_big"` / `"chests/underwater_ruin_small"` | 海底废墟大/小件箱战利品表（按件 isLarge 定） |

RNG 与结构信息表：

| 常量 | 说明 |
|---|---|
| `OCEANIC_BIOMES`（L56） | cubiomes 海洋群系 id 集（10 个），沉船搁浅（beached）判定：锚点群系不在集内 = beached |
| `_IGLOO_ORIENT`（L134） | `nextInt(4)` 四初值 → (rotation, mirror)：t0 (0,F) / t1 (1,F) / t2 (0,T) / t3 (1,T) |
| `_IGLOO_CHEST_SUB`（L138） | bottom 箱偏移按 `(rotation<<1)|mirror` 查表：0b00 (7,4) / 0b01 (3,2) / 0b10 (4,5) / 0b11 (6,1)（世界 = min+8−值） |
| `_SW_INFO`（L196） | 20 个沉船变种表 `(名称, sx, sy, sz, 箱数, loot 表元组, 箱相对坐标)`，索引 10-19 为 degraded 变种（与 structure_models 的抽取索引一一对应） |
| `_SW_BEACHED_TYPES`（L265） | 搁浅时 `nextInt(11)` → sw_typ 映射 `(0,4,5,6,7,8,9,10,17,18,19)` |
| `_SW_START_POS`（L269） | 变种 pivot (4,15) 按 rotation 的 pos 相对偏移：rot0 (0,0) / rot1 (19,11) / rot2 (8,30) / rot3 (−11,19) |
| 下界要塞 15 个 piece 类型号（L427-431） | `_FORTRESS_START`…`_FORTRESS_END` = range(15)，= xp feat_fortress.h 枚举序（extendFortress 的 typ0/typ1 区间依赖此序，不可改动） |
| `_FORTRESS_INFO`（L438） | 15 项 `((off_x,off_y,off_z), (size_x,size_y,size_z), repeatable, weight, max, 名称)`（NeStart/NeBS/NeBCr/NeRC/NeSR/NeMT/NeCE/NeSC/NeSCSC/NeSCRT/NeSCLT/NeCCS/NeCTB/NeCSR/NeBEF） |
| `_FORTRESS_CHEST_OFF`（L459） | 拐角箱偏移（以 pos−1 为基按 rot 4 向）：LEFT `((3,3),(−3,3),(−3,−3),(3,−3))`；RIGHT `((1,3),(−3,1),(−1,−3),(3,−1))` |
| `_FORTRESS_MAX_STEPS`（L465） | 100000：主循环防御上限（真实 piece 数在数百级，防实现 bug 死循环） |
| `_BASTION_STARTS`（L754） | xp 近似起始件表（件名/箱偏移×4rot/箱2/loot salt 键）——仅 test_nether_compose 回归对照用（hoglin_stable/bridge 跨区块已弃用） |
| `_BASTION_START_AIR_BASE`（L847） | start 池 air_base 占位件名 4 项（`bastion/units/air_base`、`bastion/hoglin_stable/air_base`、`bastion/treasure/big_air_full`、`bastion/bridge/starting_pieces/entrance_base`），作 variant_name |
| `_BASTION_START_XP`（L854） | xp 近似起始具体件名（原 _BASTION_STARTS name 列，extra["xp_variant"] 回归对照） |
| `_OCEAN_COLD_BIOMES` / `_OCEAN_WARM_BIOMES`（L1558-1559） | 冷水 6 群系 {0,10,24,46,49,50} / 暖水 3 群系 {44,45,48}（biome tag 1.21.11 jar 实证），定 temp 与 salt 键 |
| `_OCEAN_BIG_COLD_IDX`（L1562） | cold 大型三表索引 (1,2,3,8)（BIG_RUINS_BRICK/CRACKED/MOSSY 各 4 元素） |
| `_OCEAN_ALLPOS_RULES`（L1567） | allPositions 的 8 候选偏移规则（OceanRuinPieces.java L181-188：offset = base + Mth.nextInt(lo,hi)，相对主盒 min 角） |
| `_OCEAN_CHEST_MARKERS`（L1580） | 47 个模板短名 → chest DATA 标记局部坐标（48 模板扫描实证，每模板 0/1 个，mossy_1 无 chest） |
| `_FACE_CYCLE`（L2128） | `("n","e","s","w")`：facing 属性旋转环（Block.rotate 语义） |
| loot salt 键 | `shipwreck`（step 17）/ `shipwreck_beached`（18）/ `bastion_remnant` / `trial_chambers`=(3,4) / `pillager_outpost`=(4,9) / `ancient_city`=(7,0) / `village_{variant}`=(4,22..26) / `ocean_ruin_warm|cold`——均经 `loot_rng.salt_configs_for_version(version_key)` 取 (step, decorator)，全部落 `_SALT_1194` 档 |

缓存字典（模板 NBT 扫描结果，进程内 memoization）：

| 缓存 | 键 | 值 | 使用方 |
|---|---|---|---|
| `_load_template_voxels`（lru_cache 32，L2456） | 模板文件名 | 体素 dict | igloo/shipwreck 显示 |
| `_BASTION_CHESTS_CACHE`（L885） | bastion 模板 key | `((局部 pos, loot 表), …)` | `_template_chests` → `_piece_chests_world` |
| `_BASTION_RAW_CACHE`（L2490） | bastion 模板 key | 原始方块名体素 dict | `_bastion_raw_blocks` → `_bastion_jigsaw_voxels` |
| `_TRIAL_RAW_CACHE`（L971） / `_TRIAL_CONTAINERS_CACHE`（L972） | trial 模板 key | 原始体素 dict / 容器记录 tuple | trial 显示 / 容器预测 |
| `_OUTPOST_RAW_CACHE`（L1131） / `_OUTPOST_CONTAINERS_CACHE`（L1132） | outpost 模板 key | 同上 | outpost 显示 / 容器预测 |
| `_AC_RAW_CACHE`（L1853） / `_AC_CONTAINERS_CACHE`（L1954） | AC 模板 key（带 `ancient_city/` 前缀） | 同上 | AC 显示 / 容器预测 |
| `_VILLAGE_RAW_CACHE`（L2122） / `_VILLAGE_CONTAINERS_CACHE`（L2123） | village 模板 key（带 `village/` 前缀） | 原始 (name, props) 体素 dict / 容器记录 tuple | village 显示 / 容器预测 |

模块级已知妥协（源码 docstring 声明）：igloo 显示模型不随 rotation/mirror 旋转（cubiomes 公式含隐藏的 piece 内偏移，反解不唯一；RNG/世界坐标不受影响）；bastion 已从足迹示意体升级为逐 seed 真实 jigsaw 拼装；fortress 箱子标注近邻兜底（xp 与 Java 坐标已知偏差）；ocean_ruin 冷水三件套显示为三层并集示意（风化流依赖运行时海床沉降，不可平坦复现）。

---

# 09b 战利品 RNG 与结构件模块文档

本文档覆盖 `Utils/StructurePreviewer` 下战利品随机数原语、战利品表求值引擎与四套结构件生成模块。所有信息均来自源码逐行精读，行号引用为源文件内行号。

---

## `Utils/StructurePreviewer/loot_rng.py`

**功能**：StructurePreviewer 的战利品随机数（RNG）原语层，为整条"世界种子 → 结构锚点 → 箱子坐标 + LootTableSeed → 战利品求值"数据流提供两套互相独立的 64 位/48 位随机数实现与 LootTableSeed 派生公式。

职责分三块：

1. **Xoroshiro128++ 的 Java 包装（`XoroshiroJava`）**：对应 cubiomes `rng.h` 中 `RandomSource.type = XOROSHIRO_J` 分支。用于 mc >= 1.18 的 per-chunk 装饰流（population seed 派生、各结构箱子 LootTableSeed 推导）。核心方法与 Java 语义一一对应：`next_long` = xNextLongJ（两次 xNextLong 的高 32 位各按带符号 int32 拼接）；`next_int` = xNextIntJ（`xNextLong >> 33` 的模除拒绝采样，2 的幂走特判）；`next_float` = `(xNextLong >> 40) * 2^-24`；`next_double` = xNextDoubleJ（高 26/27 位拼接）；`skip_n` 为逐次推进原始输出（数量级小，无需矩阵跳转）。
2. **java.util.Random 精确复刻（`JavaRandom`）**：48 位 LCG，对应 `rng.h` JAVA_RANDOM 分支（`RandomSource.create(lootSeed)` = LegacyRandomSource）。专用于 1.18+ 的**箱子战利品求值**（`loot_engine.generate_loot`），与 LootTableSeed 推导用的 Xoroshiro 分属两条 RNG 线，不可混用。`_next(bits)` 推进一次 LCG 并返回高 bits 位（仅 bits=32 时按 int32 强转可能为负，bits<=31 恒非负）；`next_int(n)` 与 Java 完全一致（2 幂特判 + 拒绝采样，判定位用 uint32 截断 + int32 符号检查）。
3. **LootTableSeed 派生公式**（考证自 xpple/cubiomes fork `finders.c` 的 `getStructurePieces`/`getStructureSaltConfig`，mc >= 1.18，Xoroshiro128++）：① `population_seed = getPopulationSeed(world_seed, chest_chunk_x, chest_chunk_z)`——世界种子建 Xoroshiro 流连抽两个 `next_long` 作 a/b（各 `|1`），`(x*a + z*b) ^ world_seed`（x/z 为区块世界坐标）；② `state = population_seed + decorator_index + 10000 * generation_step`（各结构的 `(step, index)` 见 `_SALT_1194` 表）；③ 按箱子放置顺序在该流中依次 `next_long` 取 LootTableSeed（同区块多箱共用一条流按顺序取；隔区块的箱子从各自区块流取）。

版本口径：盐表按版本分档，版本线收敛后（26.2 / 1.21.11 / 1.21 三键）仅剩 `_SALT_1194` 档（1.19.4+ 语义），原 `_SALT_118` 档随旧版本下线删除。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_rotl` | `(_rotl(v: int, k: int) -> int)` | 64 位循环左移，Xoroshiro128++ 状态更新的基础操作。 |
| `_mix_stafford13` | `(_mix_stafford13(v: int) -> int)` | Stafford 13 混合函数（`xSetSeed` 拆 lo/hi 时对两半各做一次：异或移位 × 两次大数乘法）。 |
| `x_set_seed` | `(value: int) -> tuple[int, int]` | `rng.h xSetSeed`：64 位种子 → `(lo, hi)` 初始状态。注意 `h = (value ^ XH) + XL` 必须用未混合的 l（与 SeedReverser/biome_noise.py 同口径）。 |
| `XoroshiroJava` | 类（`__slots__ = ("lo","hi")`） | Xoroshiro128++ 的 Java 包装，见上文功能说明；构造时调用 `x_set_seed` 初始化双字状态。 |
| `XoroshiroJava._next_raw` | `() -> int` | 推进一次 Xoroshiro128++ 状态并返回 64 位原始输出（`rotl(l+h,17)+l` 输出 + 双字更新）。 |
| `XoroshiroJava.next_long` | `() -> int` | xNextLongJ：取两次 raw 的高 32 位，各按 int32 符号扩展后 `((a_s << 32) + b_s) & M64` 拼接（等价 Java `((long)next(32)<<32) + (int)next(32)`）。消耗 2 次 raw。 |
| `XoroshiroJava.next_int` | `(n: int) -> int` | xNextIntJ：n 为 2 的幂时 `n*(raw>>33)` 取高 31 位；否则 `raw>>33 % n` 拒绝采样（`bits-val+m` 按 uint32 截断后检查 int32 符号决定重抽）。每次尝试消耗 1 次 raw。 |
| `XoroshiroJava.next_int_between` | `(min_v: int, max_v: int) -> int` | xNextIntBetween：`nextInt(max-min+1) + min`。 |
| `XoroshiroJava.next_float` | `() -> float` | xNextFloat：`(raw >> 40) * 5.960464477539063e-08`（2^-24）。消耗 1 次 raw。 |
| `XoroshiroJava.next_double` | `() -> float` | xNextDoubleJ：两次 raw，`((a>>38)<<27) + (b>>37)` 乘 2^-53。 |
| `XoroshiroJava.skip_n` | `(count: int) -> None` | 推进 count 次 raw 输出（等价跳过 count 个 nextLongJ 的前 count 个 raw；注意与 JavaRandom 的 skip 语义差异见下）。 |
| `JavaRandom` | 类（`__slots__ = ("_state",)`） | java.util.Random 精确复刻（48 位 LCG），见上文功能说明；构造时 `(seed & M64 ^ 0x5DEECE66D) & (2^48-1)`。 |
| `JavaRandom._next` | `(bits: int) -> int` | LCG 推进一次（`state*0x5DEECE66D+0xB mod 2^48`），返回高 bits 位；bits=32 时按 int32 强转可能为负，bits<=31 恒非负。 |
| `JavaRandom.next_long` | `() -> int` | 两次 `_next(32)`，高 32 位符号扩展 + 低 32 位无符号相加（与 Java 一致）。消耗 2 次 next(32)。 |
| `JavaRandom.next_int` | `(n: int) -> int` | 2 幂特判 `n*_next(31) >> 31`；否则 `_next(31) % n` 拒绝采样（与 Java 完全一致）。 |
| `JavaRandom.next_int_between` | `(min_v: int, max_v: int) -> int` | `nextInt(max-min+1) + min`。 |
| `JavaRandom.next_float` | `() -> float` | `_next(24) / 2^24`。 |
| `JavaRandom.next_double` | `() -> float` | `((_next(26)<<27) + _next(27))`，超过 2^53 时减去（模拟 int64 有符号），除以 2^53。 |
| `JavaRandom.skip_n` | `(count: int) -> None` | 推进 count 次 LCG 状态（等价 count 次 next(1) 的状态步进；小数量直接迭代，与矩阵跳进等价）。 |
| `get_population_seed` | `(world_seed: int, block_x: int, block_z: int) -> int` | finders.c `getPopulationSeed`（mc>=1.18 分支）：世界种子建 Xoroshiro 流，`a = next_long()|1`、`b = next_long()|1`，返回 `((block_x*a + block_z*b) & M64) ^ world_seed`。参数为方块坐标（调用处传区块角或箱子方块坐标）。 |
| `salt_configs_for_version` | `(version_key: str) -> dict[str, tuple[int, int]]` | 版本键 → salt 表；版本线收敛后恒返回 `_SALT_1194`（保留参数维持既有调用签名）。 |
| `loot_seed_for_chest` | `(world_seed, chest_x, chest_z, salt_key, skips=0, version_key="1.21") -> int` | 求单个箱子的 LootTableSeed：`chest_x/z & ~15` 取区块角（兼容 igloo 传 minBlock 与 outpost 传 chestPosX 两种 C 口径），`pop = get_population_seed(...)`，`XoroshiroJava(pop + decorator + 10000*step)`，先消耗 `skips` 次 `next_long`（同流中排在前面的箱子/消耗；beached 沉船的 `nextInt(3)` 前置消耗不含在内）再取一个 `next_long`。 |
| `signed_seed` | `(value: int) -> int` | 无符号 64 位 → Java long（有符号），用于 UI 显示/输入。 |

**接口**：被 `loot_engine`（`loot_rng.JavaRandom`）、`stronghold_pieces`（`XoroshiroJava`、`get_population_seed`、`_M64`）、`mansion_pieces` / `end_city_pieces` / `fortress_pieces`（模块级导入；fortress 的 `JavaRandom` 用于 BridgeEndFiller 的 selfRandom）、`composition.py`（`loot_seed_for_chest`、`salt_configs_for_version`、`get_population_seed`、`XoroshiroJava`、`_M64`）导入。对外提供：两条 RNG 线（XoroshiroJava / JavaRandom）、population seed 与 LootTableSeed 派生公式、结构 salt 表、无符号↔有符号转换工具。

**关键变量/常量**：

| 名称 | 值/含义 |
|---|---|
| `_M64` | `(1<<64)-1`，64 位掩码。 |
| `_XL` / `_XH` | `0x9E3779B97F4A7C15` / `0x6A09E667F3BCC909`，`xSetSeed` 的黄金比例常量。 |
| `_MUL_A` / `_MUL_B` | Stafford 13 混合乘子 `0xBF58476D1CE4E5B9` / `0x94D049BB133111EB`。 |
| `_JR_MUL` / `_JR_ADD` / `_JR_MASK` | Java LCG 常量 `0x5DEECE66D` / `0xB` / `2^48-1`。 |
| `_MASK32` | `0xFFFFFFFF`，拒绝采样判定位的 uint32 截断。 |
| `_SALT_1194` | 结构键 → `(generation_step, decorator_index)` 字典：igloo (4,3)、shipwreck (4,17)、shipwreck_beached (4,18)、desert_pyramid (4,1)、jungle_pyramid (4,4)、pillager_outpost (4,9)、ruined_portal 系列 (4,10~16)、buried_treasure (3,0)、nether_fortress (7,1)、bastion_remnant (4,0)、end_city (4,2)、trial_chambers (3,4)、ancient_city (7,0)、stronghold (4,19)、mansion (4,5)、village_* (4,21~25)、ocean_ruin_cold/warm (4,7)/(4,8)。数值经 cl_salts_1_21_5.txt 与 xp fork 三方交叉验证。 |
| `SALT_CONFIGS` | 等于 `_SALT_1194`（对外别名）。 |

---

## `Utils/StructurePreviewer/loot_engine.py`

**功能**：战利品求值引擎，Cubiomes-Loot（xpple/cubiomes fork 5815e4f）的 Python 移植，对应 C 三件套：`loot_table_parser.c`（JSON → pool/entry/function 对象，即本文件 `load_loot_table` 一段）、`loot_table_context.c`（求值主循环，即 `LootTable.generate`）、`loot_functions.c`（各 LootFunction 的 RNG 消耗与附魔算法，即 `LootFunction.apply`）。求值入口 `generate_loot` 对"每个箱子开箱前的槽位物品列表"给出与游戏逐字节一致的确定性结果。

### 战利品表求值计算流程（核心）

**RNG 线选择**：`generate_loot(table, seed)` 用箱子的 LootTableSeed 创建 `loot_rng.JavaRandom`（标准 48 位 Java LCG，C 侧 `RandomSource.create(lootSeed)` = LegacyRandomSource）；LootTableSeed 的**推导**才用 Xoroshiro（见 loot_rng），两条线不可混用。

**五层结构 表→pool→entry→expand→roll 的每层 RNG 消耗与条件判定**：

1. **表层**：`LootTable.generate(rng, out)` 按 `pools` 列表顺序逐池调 `_generate_pool`，同一 RNG 流贯穿整表（池间不重播种）。
2. **池条件层**（每池第一步）：依序检查 `pool.conditions`，当前仅支持 `minecraft:random_chance`（解析期遇其它条件直接抛 `ValueError`；chance 在加载时已转 float32 存入）。每条条件消耗 `rng.next_float()` 一次并判定 `next_float() < chance`；**任一失败整池跳过**（后续 rolls 与 entries 均不再执行也不再消耗）。
3. **rolls 层**：数字型 rolls（`"rolls": 3`）为常量，**不消耗 RNG**；对象型 rolls（`{"min": a, "max": b}`）恒走 uniform `rng.nextInt(max-min+1) + min`——**即使 min==max 也消耗 `nextInt(1)`**。这是与 `set_count` 的关键区别：`set_count` 的 min==max 在解析期分流为 `set_count_constant`（不消耗），而 rolls 对象恒消耗，两者不可混淆。
4. **entry 抽取层**（每 roll 一步）：`len(pool.entries) > 1` 时消耗 `rng.nextInt(pool.total_weight)` 得权重值 w，查 `pool.precomputed`（解析期按 weight 展开的条目下标数组，对应 C 的 `precomputed_loot`）得被选 entry；`len(entries) <= 1` 时 **w=0，不消耗 nextInt**。
5. **expand（子表内联展开）**：被选 entry 若为子表条目（`minecraft:loot_table`），直接对 `subtables[idx]` 递归调 `generate(rng, out)`——子表**共享同一 RNG 流**，不重播种（C 同样只支持一层子表，`load_loot_table` 的 `resolve` 解析子表时传 `resolve=None` 拒绝嵌套）。
6. **roll 落地与函数层**：entry 无 item（空条目，C 的 entry id -1）则跳过；否则新建 `ItemStack(item=...)`，依序执行 entry.functions 中每个 `LootFunction.apply(rng, stack)`，最后 `out.append(stack)`。各函数的 RNG 消耗见下表。

**LootFunction 的 RNG 消耗**（顺序与 C 完全一致）：

| kind | RNG 消耗 | 说明 |
|---|---|---|
| `set_count_constant` | 无 | min==max 在解析期分流，直接赋 count。 |
| `set_count_uniform` | `nextInt(hi-lo+1)+lo` | count 对象型。 |
| `set_effect`（set_stew_effect） | `nextInt(len(entries))` + `nextIntBetween(dmin, dmax)` | 选效果与时长；非瞬时效果（`_INSTANT_EFFECTS` 之外）时长 ×20。 |
| `set_potion` | 无 | 药水 id 写入 `stack.potion`；单效果药水（查 `POTIONS`）同时写 `stack.effect`。 |
| `skip_n` / `skip_one` | 推进 n 次 raw | `absSkipN` 跳过的是 n 个**原始输出**（`skip_n`），不是 n 个 nextLongJ。set_damage / set_ominous_bottle_amplifier 解析为 `skip_one`。 |
| `no_op` | 无 | exploration_map / set_name / set_components 等一律空操作。 |
| `enchant_randomly_one` | `nextInt(1)` + `nextInt(max_level)+1` | 单附魔变体：**恒消耗** nextInt(1) 再掷等级（max_level==1 时也消耗）。 |
| `enchant_randomly` | `nextInt(len(pairs))`（+ `nextInt(max_level)+1` 仅当 max_level>1） | 列表变体：选附魔，仅 max_level>1 时再掷等级。pairs 在解析期按版本烘焙。 |
| `enchant_with_levels` | 见下 | 附魔台式随机附魔，算法最复杂。 |

**enchant_with_levels 详细流程**（`_apply_enchant_with_levels`，全程对齐 C `loot_functions.c`）：

1. 有效等级：`level = min_level`；若 `min != max` 则 `level += nextInt(max-min+1)`；再 `delta = enchantability // 4 + 1`，`level += 1 + nextInt(delta) + nextInt(delta)`。
2. 放大器：`amplifier = (nextFloat + nextFloat - 1.0) * 0.15`，**所有浮点均为 float32 域**（用 `np.float32` 显式模拟）；等级修正 `val = float32(level) + float32(level)*amp`，`level = floor(float32(val + 0.5f))`（f+0.5F 同样在 float32 域相加后再 floor）。
3. 取 `vectors[level+1]` 预计算向量（解析期 `_make_enchant_with_levels` 对 `level ∈ 0..2*max_level-1` 各建一次 `(vecSize, totalWeight, triples)`；`_build_level_vector` 对每个适用附魔只取其**最高有效等级**一条三元组 `(ench, ench_level, weight)`）；Python 侧钳制到末尾向量防御越界（真实参数下不可达）。
4. 首附魔：`_choose_enchantment` 消耗 `nextInt(total_weight)`，累计权重扫描（w 减到负即选中）。
5. 循环加魔：`while nextInt(50) <= level`——`_remove_incompatible` 剔除与已选附魔互斥的候选（`_INCOMPATIBLE` 集合），重算 total_weight，再 `_choose_enchantment`（每次消耗 `nextInt(total_weight)`），`level //= 2`；候选空则终止。结果写入 `stack.enchantments`。

**条件与"幸运"**：引擎的条件体系仅实现池级 `minecraft:random_chance`（entry 级条件在 C 中同样未实现）；全模块不含 luck 上下文参数（Cubiomes-Loot 同样不实现玩家幸运对抽取的影响），"幸运"仅以 luck_of_the_sea 附魔、luck 药水（`POTIONS` 表）与加权抽取权重的形式出现。

**快照加载（版本分档）**：同一张战利品表在不同版本间内容会变，引擎用本地快照文件解决（目录 `data/loot/`，命名 `<table>.<1_20|1_21|1_21_11>.json`，未分档的表用无后缀快照）。`load_loot_snapshot(table_name, era)` 的选档规则：`_LOOT_TABLE_ERAS` 记录每张分档表的 `(边界1, 边界2, 旧档后缀)`——`era >= 边界1` 用 `1_21_11` 档，`>= 边界2` 用 `1_21` 档，否则旧档；分档快照用**快照档位自己的 era** 解析（`_SNAPSHOT_ERAS`：`1_20`→E_1_14、`1_21`→E_1_21、`1_21_11`→E_1_21_11，对齐 C 烘焙表 version 烧死语义），运行时 era 只决定选哪一档；未分档快照保持运行时 era。解析时同目录存在子表快照则自动作一层子表 resolve（如 trial_chambers/reward 引用 reward_common/rare/unique）。

**era（版本时代）**：`era_for_version` 把版本键映射为序数（未知键回退 E_1_21）；era 影响 `get_applicable_enchantments` 的 ORDER 表选择（V1_13 / V1_14 / V1_21 / V1_21_11 四档遍历序）与 `enchant_randomly` 无 options 字段时 1.21.9+ 默认改走 tag 的分界（E_1_21_9）。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `era_for_version` | `(version_key: str) -> int` | 版本键 → era 序数；未知键回退 E_1_21（收敛后最小合法档）。 |
| `get_max_level` | `(ench: int \| str) -> int` | 查 `_MAX_LEVEL` 静态表（按 `ENCHANTMENT_ORDER` 枚举序索引），支持附魔名或 id。 |
| `_get_weight` | `(ench: int) -> int` | 附魔抽取权重（C get_weight）：protection/sharpness/efficiency/power/piercing=10，fire_protection 等 11 个=5，thorns/binding_curse 等 7 个=1，其余默认 2。 |
| `_init_incompatible` | `() -> None` | 惰性构建互斥表 `_INCOMPATIBLE`：对角线恒互斥 + 四组保护互斥、三组锋利互斥、fortune/luck_of_the_sea/looting×silk_touch、depth_strider×frost_walker、mending×infinity、riptide×channeling/loyalty、piercing×multishot、density×breach。 |
| `get_item_type` | `(item_name: str) -> int` | C get_item_type：按后缀子串匹配映射到 `IT_*`（**匹配顺序不能乱**：`_pickaxe` 必须先于 `_axe`，否则 iron_pickaxe 误判为 AXE）；fishing_rod/crossbow/trident/bow/book/mace 等整名匹配；其余 IT_NO_ITEM。 |
| `get_enchantment_from_name` | `(ench: str) -> int` | 附魔全名 → 枚举 id（顺序/子串匹配照抄 C：`"sweeping" in ench` → sweeping_edge、`"binding"/"vanishing"` 同理）；未识别返回 0（NO_ENCHANTMENT）。 |
| `is_treasure_enchantment` | `(ench: int) -> bool` | 宝藏附魔判定：mending/binding_curse/vanishing_curse/frost_walker/soul_speed/swift_sneak/wind_burst。 |
| `is_applicable` | `(ench: int, item: int, use_overrides: bool) -> bool` | 附魔-物品适用性（C is_applicable）：BOOK 是通配符；vanishing/unbreaking/mending 通用；thorns 在 use_overrides 时扩展到腿/靴/盔；sharpness/smite/bane 在 use_overrides 时扩展到斧；其余按类别（盔甲/工具/弓弩/钓竿/三叉戟/锤/矛）判定。 |
| `test_effective_level` | `(ench: int, i: int, n: int) -> bool` | 检查附魔等级 i 在有效等级 n 下是否可用，逐附魔照抄 C 的区间公式（如 protection：`1+(i-1)*11 <= n <= 1+(i-1)*11+11`）；未知 id 抛 ValueError。 |
| `get_enchantability` | `(item_name: str) -> int` | 查 `_ENCHANTABILITY` 表（皮革15/铁9/金25/钻10 × 四件套，工具同族，fishing_rod/bow/book=1），缺省 1。 |
| `_order_for_era` | `(era: int) -> tuple[int, ...]` | era → 可抽取附魔遍历序（V1_13/V1_14/V1_21/V1_21_11 四张预编译 id 元组）。 |
| `get_applicable_enchantments` | `(item, era, use_overrides) -> list[int]` | 按版本 ORDER 表过滤适用附魔（C get_applicable_enchantments）。 |
| `get_non_treasure` / `get_on_random_loot` | `(era, item, use_overrides) -> list[int]` | 1.21+ tag 展开：non_treasure tag 成员（1.21.11 追加 lunge）；on_random_loot = non_treasure + binding/vanishing/frost_walker/mending 尾部。 |
| `_is_tag_match` | `(tag: str, name: str) -> bool` | tag 名匹配（剥 `#` 前缀后全等）。 |
| `_build_level_vector` | `(level: int, applicable: list[int]) -> tuple[int, int, list]` | 构建某有效等级下的附魔候选向量 `(vecSize, totalWeight, [(ench, ench_level, weight)])`；每个附魔只取其最高有效等级一条（等级从 MAX_LEVEL 向下试探 `test_effective_level`）。 |
| `_choose_enchantment` | `(rng, triples, total_weight) -> int` | C choose_enchantment：消耗 `nextInt(total_weight)` 后累计权重扫描（w 减到负即选中），兜底返回末项。 |
| `_remove_incompatible` | `(triples, index) -> list` | C remove_incompatible_enchantments：剔除与选中附魔互斥的候选三元组。 |
| `ItemStack` | dataclass | 求值产物：`item`（minecraft:xxx 全名）、`count`、`enchantments`（`[(附魔规范短名, 等级)]` 按获得顺序）、`effect`（`(效果全名, 时长)` 或 None）、`potion`（药水类型全名，供 UI 按类型显示/染色）。 |
| `LootFunction` | 类（`__slots__=("kind","params")`） | C LootFunction 类化；kind 为上表字符串，params 为解析期烘焙的参数（版本相关列表如 pairs/vectors 在解析期定死）。`apply` 按 kind 分发，RNG 消耗顺序与 C 一致。 |
| `LootFunction.apply` | `(rng: JavaRandom, is_: ItemStack) -> None` | 上表 10 种 kind 的求值主体（除 enchant_with_levels 外全部内联于此）。 |
| `LootFunction._apply_enchant_with_levels` | `(rng, is_) -> None` | enchant_with_levels 五步算法，见上文"详细流程"。 |
| `_Entry` | 类 | C LootPool entry 的合并表示：`item`（全名）、`subtable`（在 `LootTable.subtables` 中的下标）、`functions`；item 与 subtable 均空 = 空条目。 |
| `_Pool` | 类 | 池结构：`min_rolls/max_rolls`、`uniform_rolls`（False=数字不消耗 / True=对象恒消耗）、`conditions`（float32 化的 random_chance 概率）、`entries`、`total_weight`、`precomputed`（按权重展开的下标数组）。 |
| `LootTable` | dataclass | `pools` + `subtables`（子表列表，内联展开用）。 |
| `LootTable.generate` | `(rng, out) -> None` | 求值入口：按池顺序逐池 `_generate_pool`。 |
| `LootTable._generate_pool` | `(pool, rng, out) -> None` | 池求值三层：条件 → rolls → 逐 roll 加权抽取/子表展开/函数执行，见上文"求值计算流程"第 2~6 步。 |
| `_ench_pairs` | `(ids: list) -> list` | 附魔 id 列表 → `[(规范短名, max_level)]`。 |
| `_enchant_randomly_full` | `(item_type, era, is_treasure) -> LootFunction` | 全表 enchant_randomly：ORDER 表（use_overrides=True）过滤，非 treasure 时再滤宝藏附魔。 |
| `_enchant_randomly_tag` | `(tag, item_type, era) -> LootFunction \| None` | tag 版 enchant_randomly：on_random_loot / non_treasure / in_enchanting_table 三种；不匹配或空 → None（调用方回退全表）。 |
| `_parse_enchant_randomly` | `(fd, item_name, era) -> LootFunction` | 解析 minecraft:enchant_randomly：options 缺失时 1.21.9+ 默认走 `#minecraft:in_enchanting_table` tag（失败回退全表），旧版直接全表；options 为字符串 → tag/单附魔（未识别名回退全表）；单元素列表 → one 变体；多元素列表 → pairs。`treasure` 默认 False。 |
| `_make_enchant_with_levels` | `(item_name, min_l, max_l, applicable) -> LootFunction` | 预计算 `vectors[level+1]`（level 覆盖 0..2*max_level-1，下标 0 占位 None），params 含 enchantability/min/max/vectors。 |
| `_parse_enchant_with_levels` | `(fd, item_name, era) -> LootFunction` | 解析 minecraft:enchant_with_levels：levels 为 dict/数字；**treasure 默认 True**；options 为 `#` 开头 tag 时走 tag 路径（use_overrides=False），否则全表路径（同样 use_overrides=False），非 treasure 滤宝藏附魔。 |
| `_parse_set_count` | `(fd: dict) -> LootFunction` | count 为 dict → uniform；数字/等值 → constant（min==max 不消耗 RNG，在解析期分流）。 |
| `_parse_set_effect` | `(fd: dict) -> LootFunction` | set_stew_effect → `[(效果全名, dmin, dmax)]`（C 仅接受 minecraft:uniform 时长）。 |
| `_parse_functions` | `(entry_data, item_name, era) -> list` | 解析 entry 的 functions/modifier（旧字段名）列表，单对象也合法：set_count/enchant_with_levels/enchant_randomly/set_stew_effect/set_potion 走专用解析；set_damage 与 set_ominous_bottle_amplifier → skip_one；其余（exploration_map/set_name/set_components…）→ no_op。 |
| `load_loot_table` | `(data, era: int, resolve=None) -> LootTable` | 解析战利品表（dict/JSON 字符串/bytes）：逐池解析 rolls（对象一律 uniform_rolls=True）、conditions（仅 random_chance，chance 先转 float32）、entries（loot_table 型 → `ensure_subtable` 经 resolve 解析一层子表，子表解析时 resolve=None 拒绝嵌套；物品型 → item + functions）、`precomputed` 按 weight 展开条目下标。 |
| `load_loot_table_file` | `(path: str, era: int, resolve=None) -> LootTable` | 读文件后转调 `load_loot_table`。 |
| `load_loot_snapshot` | `(table_name: str, era: int, snapshot_dir=None) -> LootTable` | 按 (表名, era) 选版本档快照并加载，见上文"快照加载"；`table_name` 允许带 `chests/` 前缀（取末段）；内嵌 `_resolve` 闭包按同目录快照文件名解析一层子表（缺失报 unresolved，C 同语义）。 |
| `generate_loot` | `(table: LootTable, seed: int) -> list` | 对整张表求值：`JavaRandom(seed)`（接受有符号/无符号 int64）→ `table.generate`，返回 `list[ItemStack]`。 |

**接口**：`Tools/tool_StructurePreviewer.py` 是主要消费方——`load_loot_snapshot`（按版本缓存战利品表）、`generate_loot`（对每个箱子按 `chest.loot_seed` 求值物品列表）、`era_for_version`、`ItemStack`（tooltip/图标/合并堆叠）、`ENCHANTMENT_ORDER` 等；`composition.py` 不直接导入本模块，但箱子记录的 `loot_table` 命名（带档后缀）与本模块 `load_loot_snapshot` 的快照命名规范对接。`__all__` 导出核心 API。内部依赖 `loot_rng`（JavaRandom/浮点常量）与 numpy（float32 模拟）。

**关键变量/常量**：

| 名称 | 值/含义 |
|---|---|
| `E_1_13`~`E_26_2` | era 常量 0~5（E_1_14 覆盖 1.14~1.20 的 ORDER_V1_14 区间、E_1_21=1.21~1.21.8、E_1_21_9=enchant_randomly 默认改走 tag 的分界、E_1_21_11=+lunge）。 |
| `_ERA_BY_VERSION` | `{"1.21": E_1_21, "1.21.11": E_1_21_11, "26.2": E_26_2}`。 |
| `ENCHANTMENT_ORDER` | 44 个附魔规范短名元组，**顺序必须与 C 的 enum Enchantment 一致**（QUICK_CHARGE 在 MULTISHOT 之前；末位 lunge 为 1.21.11+）。 |
| `_MAX_LEVEL` | 44 项最高等级表（armor 4/3/1…、swords 5/2/3…、lunge=3），按枚举序索引。 |
| `_WEIGHT_OVERRIDE` | 附魔权重覆盖表（10/5/1 三档，见 `_get_weight`）。 |
| `_INCOMPATIBLE` | 附魔互斥对集合（`_init_incompatible` 惰性构建）。 |
| `IT_*` | 物品类型枚举 0~16（NO_ITEM/盔甲四件/工具四件/FISHING_ROD/BOW/CROSSBOW/TRIDENT/MACE/BOOK/SPEAR）。 |
| `_INSTANT_EFFECTS` | 瞬时效果集合（instant_health/instant_damage/saturation），set_effect 时长不 ×20。 |
| `POTIONS` | 药水名 → (效果数, [(效果全名, 基础时长)])，43 种（含 turtle_master 双效果）；求值只使用单效果药水。 |
| `_ENCHANTABILITY` | 物品附魔容忍度表。 |
| `_ORDER_V1_13/14/21/21_11` | 四档附魔遍历序（含 id 预编译版 `_ORDER_*_IDS`）。 |
| `_NON_TREASURE_PRE_1_21_11` / `_NON_TREASURE_1_21_11` | 1.21+ non_treasure tag 成员（后者 +lunge）。 |
| `_ON_RANDOM_LOOT_TAIL` | on_random_loot tag 尾部四附魔 (binding, vanishing, frost_walker, mending)。 |
| `_SNAPSHOT_DIR` | 快照目录 `<本文件目录>/data/loot`。 |
| `_LOOT_TABLE_ERAS` | 分档表 → (边界1, 边界2, 旧档后缀)：shipwreck_supply/map/treasure 与 woodland_mansion、underwater_ruin_big/small、ancient_city 均为 `(E_1_21_11, E_1_21, "1_20")`；pillager_outpost 为 `(E_1_21_9, E_1_21, "1_20")`。附注每个分档的考证依据（1.21 档取 1.21.1 官方 jar 原生表等）。 |
| `_SNAPSHOT_ERAS` | 档后缀 → 解析 era：`1_20`→E_1_14、`1_21`→E_1_21、`1_21_11`→E_1_21_11。 |
| `__all__` | 导出 ItemStack/LootFunction/LootTable、三个 load_*、generate_loot、era_for_version、附魔查询函数族与 era 常量。 |

---

## `Utils/StructurePreviewer/stronghold_pieces.py`

**功能**：要塞（Stronghold）三合一模块——① 拼装引擎（`assemble_stronghold`，复现 Java `StrongholdStructure.java` 的重试循环 + `StrongholdPieces` 队列扩展算法，基准为 xpple fork `features/stronghold.c`）；② 战利品流模拟（`simulate_loot_stream`，照抄 xp `features/stronghold.c getStrongholdLoot`）；③ 几何转写（`build_stronghold_voxels`，把每个 piece 的 postProcess 逐段转写为模型体素，基准 `StrongholdPieces.java L232-1226`）。

### 递归/队列组装流程与 RNG 消耗顺序

**拼装 RNG**：LegacyRandom（java.util.Random 48 位 LCG），复用 `structure_map.chunk_generate_rnd`（= `setLargeFeatureSeed`）+ `Utils.SeedReverser.mc_random` 函数式 API（`next_int(state, n)` / `next_state(state)` 返回新状态）。

1. **重试循环**（Java `StrongholdStructure.java L24-45`）：`do { ... } while (portalRoomPiece == null)`——每次 attempt 独立播种 `chunk_generate_rnd(world_seed + attempt - 1, cx, cz)`（对应 `rng.setLargeFeatureSeed(seed + attempt++, cx, cz)`）；先建起始件：`facing = nextInt(4)`（消耗 1 次），StartPiece 类型为 StairsDown（`add=1` 即 isSource）、entry_door 恒 OPENING（零消耗）、bb 由 pos 按朝向扩展 5×11×5 足印；随后立即 `_extend_piece` 扩展一次（起始件**不入队**，且因 `add != 0` 在扩展时把 `imposed_piece` 强制设为 FiveCrossing）；然后进入主循环。
2. **主循环**（Java L37-41 = xp L431-443）：`while queue and not gen_stopped`——`idx = nextInt(len(queue))`（每轮消耗 1 次）从队列**随机移除**一个待扩展件并 `_extend_piece` 扩展。接受成功的件同时进入 `env.list`（pieces，接受序）与 `env.queue`（待扩展，Java pendingChildren）；FillerCorridor 也入队（pop 时零消耗）。
3. **单件扩展 `_extend`**：深度 > 50 或超出起始件 112 格半径或 `gen_stopped` 直接返回；若 `imposed_piece` 非空则先强制加该件；否则最多 5 次尝试——每次 `sel = nextInt(total_weight)`，按类型序扫描（跳过已除名 `deltyp` 位）累减权重选出类型，判定 `(max_count != 0 and count >= max_count) or depth < min_depth or typ == typlast` 则** break 本轮失败重试**；`_add_piece` 拒绝（碰撞等）则继续扫描后续类型（同一 sel，xp 原样）；接受后 `ntyp[typ] += 1`、`typlast = typ`，若满额则 `total_weight -= weight`、置 `deltyp` 位并调 `_update_generation_status`；5 次全败则兜底 `_add_piece(FILLER_CORRIDOR)`。
4. **`_add_piece`（xp addStrongholdPiece）**：构造期 RNG **仅在接受成功路径消耗**——Library 先试 11 高（minY>10 且无碰撞直接接受）否则降 6 高（高度选择零消耗），FillerCorridor 走专用收缩规则（z 从 2 收缩到 1 找不重叠最短段，接受条件 `b0.y > 1`），其余公共路径「minY>10 且有碰撞才拒绝」（按定案照抄 xp 的已知分叉）；接受后按类型消耗构造 RNG：Straight = `nextInt(5)`（entryDoor）+ 两次 `next_state`（leftChild/rightChild，`(st>>47)==0` 置位）；PrisonHall/LeftTurn/RightTurn/StraightStairsDown/StairsDown/ChestCorridor/Library = `nextInt(5)`；RoomCrossing = `nextInt(5)` + `nextInt(5)`（rc_type，bit0 = type==2 有箱变体）；FiveCrossing = `nextInt(5)` + 三次 `next_state`（leftLow/leftHigh/rightLow）+ `nextInt(3)`（rightHigh，>0 置位）；PortalRoom 零消耗只置 `env.portal = True`；FillerCorridor 零消耗。piece 计入 list/queue，`len(list) >= nmax(512)` 时置 `gen_stopped`。
5. **`_update_generation_status`**：只要还存在未除名的受限 piece（`ntyp < weight`）就不停机；7 个受限 piece 全部满额除名后置位（xp generationStopped 语义，主循环条件与 `_extend` 开头都检查它）。
6. **`_extend_piece`**（xp extendStrongholdPiece）按类型生成子件（forward/left/right 偏移表）：Straight → forward(1,1) + left/right（按 add bit）；PrisonHall/ChestCorridor/StraightStairsDown → forward；LeftTurn/RightTurn → 按 rot 决定左/右；RoomCrossing → forward(4,1)+left(1,4)+right(1,4)；StairsDown → 起始件先 imposed FiveCrossing 再 forward；FiveCrossing → forward(5,1) + 左 n/n2 + 右 n/n2（按 add 四 bit，rot∈{3,0} 时 n/n2 镜像为 5/3）；Library/PortalRoom/FillerCorridor 无子件。
7. **Y 沉降 `_apply_sink`**（Java 1.21 `moveBelowSeaLevel`，xp 默认不做）：在拼装终态流上消耗 `nextInt(53-k)`（k = 合并盒高度 - 64 + 1，k<53 才消耗），全体 piece 按 `dy = k - max_y` 平移；不影响 loot 流（loot 逐区块独立，且沉降只做全体平移，isTall 等高度差不变）。

**loot 流**（`simulate_loot_stream`）：逐区块独立 Xoroshiro 流——对合并盒覆盖的每个区块角 `(cx, cz)`，`rng = XoroshiroJava(get_population_seed(seed, cx, cz) + decorator + 10000*step)`（stronghold salt = (4,19)），按 **piece 列表顺序**对与该区块 xz 相交的 piece 依次走 postProcess 消耗：

| piece 类型 | RNG 消耗 |
|---|---|
| STRAIGHT | `generateBox` 壳层体素 nextFloat（仅世界坐标落在本区块的壳层格）+ 4 次无条件 nextFloat（火把 0.1F 概率 ×4） |
| PRISON_HALL | box skip + `skip_n(12)` |
| LEFT/RIGHT_TURN | box skip |
| ROOM_CROSSING | box skip；若 add bit0（有箱变体）且箱世界坐标（局部 (3,8)，y=bb0.y+4）落在本区块 → `next_long()` = corridor 箱种子 |
| STRAIGHT_STAIRS_DOWN / STAIRS_DOWN | box skip |
| FIVE_CROSSING | box skip + `skip_n(109)` |
| CHEST_CORRIDOR | box skip；箱（局部 (3,3)，y=bb0.y+2）落在本区块 → `next_long()` |
| LIBRARY | box skip（高度按 is_tall = y 跨度>6 取 11/6）+ `skip_n(520)`（generateMaybeBox 4×10×13）+ 箱1（局部 (3,5)，y+3）与 tall 箱2（局部 (12,1)，y+8）各在落区块时 `next_long()` |
| PORTAL_ROOM | `skip_n(760)`（the famous 760 skips）+ 12 个眼框逐个 `next_float() > 0.9`（约 10% 有眼，框格世界坐标落在本区块才置位 bit） |
| FILLER_CORRIDOR | 无消耗 |

箱子坐标与 `next_long` 消耗仅在箱子方块落在本区块时发生；眼睛 bit 按坐标落区置位（`eyes` 为 12 位掩码，非 portal_room 恒 0）。

**几何转写**：`_CtxS`（继承 fortress 的 `_Ctx`）提供 `place/box/air_box` 基础 + 楼梯/墙上火把/立式火把/panel/按钮/门/箱子/`sel_box`（SMOOTH_STONE_SELECTOR 盒：hollow=True 仅边界写石砖内部不动，hollow=False 边界石砖内部显式挖空）。`_door_type` 按 entryDoor 构造值转写五种门（0/1=OPENING 3×3 挖空、2=木门、3=铁栏杆 GRATES、4=铁门+双按钮）。概率填充不做（cobweb 恒不放、Straight 火把恒放，RNG 已由 loot 流 skip 处理，几何层零 RNG）。`_reattach_wall_decor` 对 torch/panel/button 做物理约束贴附校正（方向链逐环模拟与游戏实测不符，改为从 4 个水平邻格选实心格改贴附方向）。模型坐标：`(x,z) = 世界 - anchor`、`y = 世界 - 64`（沉降后 y 可为负）；AIR = 体素 pop；后写胜出。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `loot_table_for_version` | `(table: str, version_key: str) -> str` | 表名 → 带档后缀表名（C loot_tables.c 分档）：crossing 恒原名（1_13 单文件档）、library → `.1_20`、corridor → 版本 `1.21.9/1.21.11/26.*` 为 `.1_21_9` 否则 `.1_20`。供 composition 层把档后缀写入 Chest.loot_table 使快照层选对档。 |
| `stronghold_salt` | `(version_key="1.21") -> tuple[int, int]` | 返回 `(4, 19)`（finders.c L357-361，1.19.4+ 档）。 |
| `orient_box` | `(pos, offset, size, facing) -> (b0, b1)` | xp orientBox：piece 局部 offset/size 按朝向 0~3（N/E/S/W）生成世界 AABB（bb1 为含端点最大角，Java maxX 语义）。 |
| `boxes_intersect` | `(a0, a1, b0, b1) -> bool` | xp hasIntersection：两闭区间 AABB 三轴相交判定。 |
| `rot_pos` | `(bb0, bb1, lx, lz, rot) -> (x, z)` | xp rotPos：piece 局部 (x,z) → 世界 (x,z)（四旋转换算）。 |
| `_SHEnv` | 类 | 拼装环境：`state`（RNG 状态）、`list`（已接受 pieces）、`queue`（待扩展）、`portal`、`imposed_piece`、`typlast`、`ntyp[11]`、`deltyp`、`total_weight`（初值 145）、`gen_stopped`、`nmax`（默认 512，与 xp 探针同）。 |
| `_has_collision` | `(env, b0, b1)` | 返回第一个与给定 AABB 相交的已接受 piece（Java findCollisionPiece）。 |
| `_add_piece` | `(env, typ, x, y, z, depth, facing) -> bool` | xp addStrongholdPiece：接受判定（Library/FillerCorridor 特殊路径 + 公共路径）→ piece dict 构造 → 构造期 RNG（见上文第 4 步）→ 入 list/queue → nmax 上限置 gen_stopped。 |
| `_update_generation_status` | `(env) -> None` | xp updateGenerationStatus：受限 piece 全部满额除名后置 `gen_stopped`。 |
| `_extend` | `(env, piece, x, y, z, facing) -> None` | xp extendStronghold：深度/半径/停机检查 → imposed 强制件 → 5 次权重抽选 → 兜底 FillerCorridor，见上文第 3 步。 |
| `_child_forward` / `_child_left` / `_child_right` | `(env, piece, off...) -> None` | xp generateSmallDoorChildForward/Left/Right：按 piece 朝向把相对偏移换算为 `_extend` 的世界坐标与新朝向。 |
| `_extend_piece` | `(env, piece) -> None` | xp extendStrongholdPiece：按 12 种类型分发子件生成（偏移与 add bit 组合，见上文第 6 步）。 |
| `_apply_sink` | `(pieces, state) -> int` | Java moveBelowSeaLevel：`k = 高度 - 64 + 1`，k<53 时消耗 `nextInt(53-k)`，全体 y 平移 dy；返回消耗后的流状态。 |
| `assemble_stronghold` | `(world_seed, chunk_x, chunk_z, sink_y=True) -> list[dict]` | getStrongholdPieces 全流程（含重试循环与可选 Y 沉降），见上文组装流程；返回 piece dict 列表（bb0/bb1 闭区间）。 |
| `_generate_box_skip` | `(piece_bb0, piece_bb1, piece_rot, cx, cz, x0..z1, rng) -> None` | xp generateBox 的 RNG 侧：三重循环体素，仅世界坐标落在本区块且位于盒壳层的格消耗 `next_float()`（对应 Java SmoothStoneSelector 的区块外短路）。 |
| `simulate_loot_stream` | `(world_seed, pieces, version_key="1.21") -> None` | getStrongholdLoot 的 loot/眼睛段：逐区块建流、按 piece 序消耗（见上文 loot 流表格），就地填 `piece["chests"]`（`{"x","y","z","table","seed"}`）与 `piece["eyes"]`。 |
| `compose_stronghold_pieces` | `(world_seed, chunk_x, chunk_z, version_key="1.21") -> list[dict]` | 组装入口：`assemble_stronghold(sink_y=True)` + `simulate_loot_stream`；返回含 type/name/pos/rot/depth/bb0/bb1/add/entry_door/rc_type/chests/eyes 的 piece dict 列表。 |
| `_CtxS` | 类（继承 `fortress_pieces._Ctx`） | 要塞 postProcess 上下文：`wx_dir`（局部水平朝向→世界朝向）、`stairs`、`torch_wall`（方向链字节码定案，贴附墙取世界 FACING 反侧）、`torch_post`、`panel`、`button`、`door`（恒关闭+铰链左）、`chest`、`sel_box`（hollow 双模式石砖盒）。 |
| `_door_type` | `(c, typ, x, y, z) -> None` | StrongholdPiece.a()：entryDoor 构造值 0/1/2/3/4 → OPENING/WOOD_DOOR/GRATES/IRON_DOOR 五种门几何。 |
| `_piece_chest_corridor` | `(c, ed) -> None` | ChestCorridor.postProcess：hollow 盒 + 双门 + 石砖台 + 台阶 + 箱（局部 (3,2,3)）。 |
| `_piece_filler_corridor` | `(c, steps) -> None` | FillerCorridor.postProcess：steps 从 bb 跨度现算（N/S→zSpan、E/W→xSpan），逐列画壳体并挖空走廊。 |
| `_piece_five_crossing` | `(c, ed, add) -> None` | FiveCrossing.postProcess：hollow 大盒 + 四向门洞（按 add bit）+ 石砖薄盒/单柱/台阶 + 火把。 |
| `_piece_left_turn` / `_piece_right_turn` | `(c, ed) -> None` | LeftTurn/RightTurn.postProcess：hollow 小盒 + 门 + 按朝向挖一个侧出口（朝向条件互为镜像）。 |
| `_piece_library` | `(c, ed, is_tall) -> None` | Library.postProcess：hollow 大盒 + 门 + 侧壁书架/木柱（(z-1)%4==0 处木板+火把）+ 中层书架三组；tall 时加夹层木板、四段栏杆臂、梯子（FACING=SOUTH）、中央柱栏杆与 6 个立式火把；箱1 (3,3,5)，tall 箱2 (12,8,1)。 |
| `_piece_portal_room` | `(c, ed, eyes) -> None` | PortalRoom.postProcess：实心盒（内部挖空）+ 恒 GRATES 门 + y6 回廊 + y1 平台与岩浆 + 铁栏杆窗 + 三级石砖楼梯 + 12 个末地传送门框架（按 `eyes` bit 有眼→`end portal frame eye` / 无眼→side）+ 全眼时 3×3 传送门方块 + 蠹虫刷怪笼 (5,3,6)。 |
| `_piece_prison_hall` | `(c, ed) -> None` | PrisonHall.postProcess：hollow 盒 + 门 + 中央四柱 + 牢房铁栏杆 + 两扇铁门（FACING=WEST）。 |
| `_piece_room_crossing` | `(c, ed, rc_type) -> None` | RoomCrossing.postProcess 三变体：rc_type 0 火把柱（石砖柱+四面墙上火把+台阶环）、1 水池（石砖框+中心水柱）、2 阁楼（圆石圈+四角柱+火把+木板层+梯子+箱 (3,4,8)）。 |
| `_piece_stairs_down` | `(c, ed) -> None` | StairsDown.postProcess（StartPiece 同布局）：hollow 竖井盒 + 双门 + 石砖/台阶交错的下沉阶梯。 |
| `_piece_straight` | `(c, ed, add) -> None` | Straight.postProcess：hollow 走廊盒 + 双门 + 4 个墙上火把（几何恒放）+ 左右出口（按 add bit）。 |
| `_piece_straight_stairs_down` | `(c, ed) -> None` | StraightStairsDown.postProcess：hollow 长井盒 + 双门 + 6 级圆石楼梯（FACING=SOUTH）+ 垫层石砖。 |
| `_reattach_wall_decor` | `(vox: dict) -> list` | 贴边装饰（torch/panel/button）物理约束校正：贴附侧邻格为空时从 4 个水平邻格选实心格改方向（单实心直接取、多实心取环向最近、全空保留视为真悬空）；返回 `[(pos, 旧shape, 新shape)]`。 |
| `build_stronghold_voxels` | `(pieces: list[dict], anchor) -> dict` | 入口：按 accepted 顺序逐 piece 分发 12 种布局函数（FillerCorridor 的 steps 由 bb 跨度按朝向现算；Library 的 is_tall 由 bb y 跨度>6 现算；PortalRoom 用 eyes bit），输出模型体素 dict `{(x,y,z): 材质或(材质,形状码)}`（不含箱子标注，compose_display_model 负责）。 |

**接口**：被 `composition.py` 导入使用——`compose_stronghold_pieces`（拼装+loot，L1408）、`assemble_stronghold` + `build_stronghold_voxels`（重算体素，L1448-1450）、`SH_NAMES` / `loot_table_for_version`（箱子表名分档）、`SH_PORTAL_ROOM`（眼睛掩码透出）。本模块自身导入：`structure_map`（chunk_generate_rnd）、`mc_random`（函数式 LCG）、`loot_rng`（XoroshiroJava/get_population_seed/_M64）、`fortress_pieces`（`_Ctx`/`_PieceBB`/`_WX_STAIRS`，材质与上下文复用）、`block_shapes`。对外还提供 piece 类型枚举与几何辅助（orient_box 等）供测试复用。

**关键变量/常量**：

| 名称 | 值/含义 |
|---|---|
| `SH_STRAIGHT`~`SH_PIECE_COUNT` | piece 类型枚举 0~11（xp stronghold.h 顺序）：直廊/牢房厅/左转/右转/房间十字/直下楼梯/下楼梯/五路口/箱子走廊/图书馆/传送门房/填充走廊。 |
| `SH_NAMES` | 12 个短名（"SHS"/"SHPH"/"SHLT"/"SHRT"/"SHRC"/"SHSSD"/"SHSD"/"SH5C"/"SHCC"/"SHLi"/"SHPR"/"SHFC"）。 |
| `SH_INFO` | 每类型 (offset, size, weight, maxPlaceCount, minDepth) 表（xp stronghold_info L25-42）；FILLER_CORRIDOR 为 (-1,-1,-1) 不参选。 |
| `SH_TOTAL_WEIGHT` | 145（全部 weight 之和，StrongholdPieces.a() 重置后的初值）。 |
| `EYE_POSITIONS` | 传送门房 12 个眼框局部 (x,z)（y 恒 3），序与 Java $$19[0..11] 一致。 |
| `LOOT_CORRIDOR` / `LOOT_CROSSING` / `LOOT_LIBRARY` | 三张战利品表键（chests/stronghold_corridor / crossing / library）。 |
| `_SALT_STRONGHOLD_1194` | `(4, 19)`。 |
| `SB`/`SB_STAIRS`/`SB_SLAB`/`COBBLE`/`PLANKS`/`BOOKSHELF_M`/`BARS_M`/`FENCE_M`/`LADDER_M`/`LAVA_M`/`WATER_M`/`SPAWNER_M`/`TORCH_M`/`FRAME_M`/`FRAME_EYE_M`/`PORTAL_M`/`BUTTON_M`/`CHEST_M`/`OAK_DOOR_M`/`IRON_DOOR_M` | 材质键（对应 assets/SeedReverser/textures/block/<键>.png）；缺失纹理替代定案：END_PORTAL_FRAME→end_stone_bricks 系、END_PORTAL→obsidian、STONE_BUTTON→stone、INFESTED_STONE_BRICKS→stone bricks。 |
| `_OPP` | 水平方向反侧映射（n↔s、e↔w）。 |
| `_SLAB` / `_BARS` / `_FENCE` | 常用 (材质, 形状码) 二元组（石砖台阶/铁栏杆 pane/橡木栅栏 post）。 |

---

## `Utils/StructurePreviewer/mansion_pieces.py`

**功能**：林地府邸（woodland_mansion）生成，移植自官方映射反编译源（1.21.11 jar + SpecialSource + Vineflower 的 `WoodlandMansionPieces.java` 1229 行 + `WoodlandMansionStructure.java`）。模块把"结构拼装（模板级）+ 装饰（箱子 LootTableSeed）"两条**独立 RNG 线**完整复现，并加载 73 个模板 NBT 供后续体素渲染。

### 两条 RNG 线与组装流程

**结构线（模板拼装，LegacyRandomSource = 48 位 LCG）**：

1. 播种：`LegacyRandom.from_large_feature(world_seed, chunk_x, chunk_z)` = `structure_map.chunk_generate_rnd`（= `setLargeFeatureSeed`：`l1=nextLong(); l2=nextLong(); rnd = chunkX*l1 ^ chunkZ*l2 ^ seed`）。
2. `assemble_mansion` 第一步：`rot = _ROT_NAMES[rng.next_int(4)]`（Rotation.getRandom，消耗 1 次）；锚点 `pos = (chunk_x*16+7, 64, chunk_z*16+7)`（findGenerationPoint 的 `chunkBlock(7,7)`；游戏为 5×5 区块最低表面且 Y<60 拒绝生成，本模块 Y 固定 64，不复刻地形查询）。
3. `MansionGrid(rng)`（11×11 三层网格，RNG 消耗序与 Java 逐行一致）：构造期固定布局（入口房 2×2、西邻 2 格、东侧封死、南北走廊、四段 `recursiveCorridor` 朝西延伸、`cleanEdges` 收敛循环）——其中 `_recursive_corridor` 每层最多 8 次尝试，每次消耗 `nextInt(4)` 选方向（from2DDataValue 序 0=S 1=W 2=N 3=E），且**短路求值**：`nd != EAST` 时不消耗 `nextBoolean`；随后 `_identify_rooms` 对一/二层各跑一遍——先把房间格 `util_shuffle` 随机打乱（每个房间格消耗一次 `nextInt(i)`），再逐格识别 1×1/1×2/2×2 房（每房恒消耗两次 `nextBoolean` 定门位，失败时按 edgesTo 换角重试但不追加消耗）；`_setup_third_floor` 从二层带门 1×2 房候选中 `nextInt(len)` 选一个作楼梯间、`nextInt(len)` 选开放方向，三层递归走廊（depth 4）+ cleanEdges，最后三层再 `_identify_rooms`。
4. `_create_mansion(pos, rot, grid, rng)`（MansionPiecePlacer.createMansion）：① entrance 墙件（pos+W*9）后 pos 前移 S*16；② 两轮 `_traverse_outer_walls`（wall_flat 与 wall_window 两套 PlacementData，沿 baseGrid 外圈顺时针放 wall/wall_corner 件，双套方向状态：局部 gdir 走绝对方向、pd.rot 只由 traverse_turn/inner_turn 演化）；③ 三层墙件循环（找第三层首个 house 格，y 升 x 降）；④ 两轮 `_create_roof`（roof/roof_front/small_wall/small_wall_corner/roof_corner/roof_inner_corner，纯几何零 RNG）；⑤ 三层主循环：走廊格放 `corridor_floor` 与四向地毯（零 RNG），房间格先由**相邻走廊决定 door_dir**（`door_dir = dirs[rng.next_int(len(dirs))]`，仅当有相邻走廊才消耗；无则 `_ROOM_ORIGIN_FLAG` → "UP"），再放内墙/门（indoors_wall_N/indoors_door_N），最后按房间类型分发：1×1 → `_add_room_1x1`（恒耗 `get1x1`；门向非 E/N/W/S 即 UP/None 再耗 `get1x1Secret`）；1×2 → `_add_room_1x2`（十四分支按 door×side 组合放模板，恒耗一次 `get1x2Side/Front/Secret`，其中二层 `get1x2Secret` 是 `nextInt(1)+1`——nextInt(1) 也消耗一次流）；2×2 → `_add_room_2x2`（八分支，恒耗 `get2x2`）或 door=="UP" 时 `_add_room_2x2_secret`（`get2x2Secret` 零消耗）。
5. 模板名生成器 `_FirstFloor`/`_SecondFloor`（ThirdFloor 空继承二层的类）：如 `"1x1_a" + str(nextInt(5)+1)`、`"1x2_c_stairs"`（stairs 判定本身不耗流）等，每个模板名消耗一次 `nextInt(n)`。

**装饰线（箱子 LootTableSeed，Xoroshiro per-chunk）**：`_decor_loot` 复现 `ChunkGenerator.applyBiomeDecoration` + `StructureStart.placeInChunk` 语义——mansion 在 SURFACE_STRUCTURES（step=4）内注册序 5，salt 偏移 = `5 + 10000*4 = 40005`；对府邸合并盒覆盖的每个区块：`pop = get_population_seed(seed, 区块角)`，`rng = XoroshiroJava(pop + 40005)`；按 **pieces 列表序**遍历 bb 与区块 writable box（xz=16×16，y=[0,319] 恒内）相交的 piece，再按模板 `chest_markers` 顺序（= `filterBlocks` 的 buildInfoList 重排序：有 NBT 组按 (y,x,z) 升序）处理 `Chest*` DATA 标记——先 mirror→rot 变换到世界坐标，`filterBlocks` 区块 xz 裁剪、`createChest` 的 `isInside` 检查后消耗一次 `next_long()` = LootTableSeed，每箱恰一次（73 模板共 10 个 Chest* 标记）。模板自带容器（固定 Items NBT、无 LootTable，如 1x2_a9 的 42 个装饰箱）不耗流、开箱不 roll 表。

**模板加载**：`_load_template` 解析 `assets/SeedReverser/woodland_mansion/<模板名>.nbt`（缓存），产出 `{"size", "blocks", "chest_markers"}`；blocks 为显示体素（air/cave_air/structure_void 与 structure_block 不入），chest_markers 为 `(x,y,z,metadata)` 按 (y,x,z) 升序。`_piece_bb` 按模板尺寸 + mirror/rot + pos 算闭区间世界 AABB。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_rot_add` | `(rot: str, delta: str) -> str` | Rotation.getRotated：旋转叠加（模 4 加法，`_ROT_NAMES` 序）。 |
| `_rotate_dir` | `(rot: str, d: str) -> str` | Rotation.rotate：水平方向按放置旋转（CW90/180/CCW90/恒等）。 |
| `_rel2` / `_rel3` | `(pos, d, n=1) -> tuple` | BlockPos.relative：水平方向 / 含 UP 的三维位移。 |
| `transform_pos` | `(p, mirror, rot) -> tuple` | StructureTemplate.transform（pivot=0）：mirror 先、rot 后（LEFT_RIGHT: z=-z；FRONT_BACK: x=-x；CW90: (-z,y,x) 等）。 |
| `blockpos_rotate` | `(p, rot) -> tuple` | BlockPos.rotate（无镜像纯旋转）。 |
| `zero_pos_with_transform` | `(pos, mirror, rot, sx, sz) -> tuple` | StructureTemplate.getZeroPositionWithTransform：模板原点经镜像/旋转后的落点修正（用于房间模板定位偏移）。 |
| `LegacyRandom` | 类 | 结构线 RNG 函数式封装：`from_large_feature`（类方法，播种）、`next_int`（含拒绝采样的完整 Java 语义）、`next_boolean`（next(1)!=0）、`state` 属性。 |
| `util_shuffle` | `(lst, rng) -> None` | Util.shuffle：`for i = size; i > 1; i--: j = nextInt(i); swap(i-1, j)`。 |
| `SimpleGrid` | 类 | width×height int 网格（越界读返回 valueIfOutside）：`set`/`set_rect`（含端点、越界自动跳过）/`get`/`setif`（条件写）/`edges_to`（四正邻任一等于 v）。 |
| `_is_house` | `(grid, x, y) -> bool` | MansionGrid.isHouse：格值 ∈ {1,2,3,4}（走廊/房间/起始房/测试房）。 |
| `MansionGrid` | 类 | 11×11 三层网格生成器（RNG 消耗序与 Java 逐行一致），见上文第 3 步。 |
| `MansionGrid.is_room_id` | `(x, y, floor, rid) -> bool` | isRoomId：查 floorRooms[floor] 的 id 位（`$$0` 参数未用，反编译伪影）。 |
| `MansionGrid.get1x2RoomDirection` | `(grid, x, y, floor, rid) -> str \| None` | Plane.HORIZONTAL 序找同 id 邻格方向，找不到返回 None（Java @Nullable）。 |
| `MansionGrid._recursive_corridor` | `(grid, x, y, d, depth) -> None` | 递归走廊：置走廊格 → 最多 8 次随机方向试探（`nextInt(4)` + 短路 `nextBoolean`，仅当新方向非反向且两格外仍空才递归）→ 后处理：顺/逆时针邻格与两倍邻域置房间格（零 RNG）。 |
| `MansionGrid._clean_edges` | `(grid) -> bool` | cleanEdges 收敛步：孤立 CLEAR 格四邻 house 数 ≥3 或（=2 且对角 house ≤1）时转 ROOM；返回是否有变更（外层 while 收敛）。 |
| `MansionGrid._identify_rooms` | `(grid, rooms) -> None` | 房间识别：房间格坐标 `util_shuffle` 后逐格扩张成 1×1/1×2/2×2（东南/西南/西北 2×2 与东/南/西/北 1×2 优先级判定），每房两次 `nextBoolean` 定门位（不靠走廊时按 edgesTo 换角最多四轮，仍失败则 door_flag=0），写入带 `_ROOM_ORIGIN_FLAG/_ROOM_DOOR_FLAG/kind/id` 的格值，id 从 10 起。 |
| `MansionGrid._setup_third_floor` | `() -> None` | 三层布局：二层带门 1×2 房候选中选楼梯间（`nextInt(len)` ×2），按 baseGrid 房区拷贝到三层，三层递归走廊 + cleanEdges；无候选/无开放方向时整层 BLOCKED（后者回滚 stairs 旗标）。 |
| `_FirstFloor` / `_SecondFloor` | 类（全静态方法） | 楼层模板名生成器：`get1x1`/`get1x1Secret`/`get1x2Side`/`get1x2Front`/`get1x2Secret`/`get2x2`/`get2x2Secret`；二层差异：1x2Side/Front 带 stairs 分支（`1x2_c_stairs`/`1x2_d_stairs`）、get1x2Secret 为 `nextInt(1)+1`（消耗流）、get2x2Secret 恒 `"2x2_s1"` 零消耗。`_FLOOR_COLLECTIONS = (_FirstFloor, _SecondFloor, _SecondFloor)`。 |
| `template_path` | `(name: str) -> Path` | 模板 NBT 文件路径（`assets/SeedReverser/woodland_mansion/<名>.nbt`）。 |
| `_load_template` | `(name: str) -> dict` | 模板 NBT → `{"size","blocks","chest_markers"}`（`_TPL_CACHE` 缓存）；chest_markers 排序键 (y,x,z) 对齐 buildInfoList 比较器，**直接影响装饰线 nextLong 分配**；见上文"模板加载"。 |
| `_piece_bb` | `(size, mirror, rot, pos) -> tuple` | TemplateStructurePiece 构造 bb：transform(0) 与 transform(size-1) 取 min/max + move(pos)，六元组闭区间。 |
| `_PlacementData` | 类 | 放置游标：pos/rot/wall（wall 为墙件模板名）。 |
| `_add_piece` | `(pieces, name, pos, rot, mirror="NONE") -> None` | 向 pieces 列表追加 `{name, pos, rot, mirror}`。 |
| `_traverse_wall_piece` | `(pieces, d) -> None` | traverseWallPiece：add(wall, pos+E*7)；pos += S*8（游标沿墙推进一格）。 |
| `_traverse_turn` | `(pieces, d) -> None` | traverseTurn：外角处理——pos+=S*(-1) → wall_corner → pos+=S*(-7)+W*(-6) → rot=CW90。 |
| `_traverse_inner_turn` | `(pieces, d) -> None` | traverseInnerTurn：内角处理——pos+=S*6+E*8 → rot=CCW90（不放件）。 |
| `_traverse_outer_walls` | `(pieces, pd, g, d0, x, y, tx, ty) -> None` | traverseOuterWalls 逐行转写：沿网格边线走，外角（前方非 house）→ turn+放墙、内角（前与左前都 house）→ inner turn、直行 → 放墙；终止条件 = 回到起点坐标且 gdir 回到初始快照。 |
| `_create_roof` | `(pieces, base, rot, g, lower, start_x, start_y) -> None` | createRoof：对上层露出格放 `roof`（UP+3）+ 四向 `roof_front`；lower 非 None 时对上下都有房的格放 `small_wall`/`small_wall_corner`；最后补 `roof_corner`/`roof_inner_corner`。 |
| `_add_room_1x1` | `(pieces, p1, rot, door_dir, coll, rng) -> None` | addRoom1x1：恒耗 `get1x1`；门向非 E/N/W/S（UP/null，秘密房）再耗 `get1x1Secret`；按门向旋转模板并用 `zero_pos_with_transform` 算落点。 |
| `_add_room_1x2` | `(pieces, p1, rot, side, door, coll, stairs, rng) -> None` | addRoom1x2 十四分支（door∈{E,W,S,N,UP} × side 邻向组合），每分支一次位移/旋转/镜像 + 一次模板名消耗。 |
| `_add_room_2x2` | `(pieces, p1, rot, side, door, coll, rng) -> None` | addRoom2x2 八分支：算 dx/dz/r2/mirror 后 `get2x2` 落模板。 |
| `_add_room_2x2_secret` | `(pieces, p1, rot, coll, rng) -> None` | addRoom2x2Secret：`get2x2Secret`（零消耗）落 p1+E*1。 |
| `_create_mansion` | `(pos, rot, grid, rng) -> list` | MansionPiecePlacer.createMansion：墙/屋顶/三层走廊地毯与房间模板拼装全流程（见上文第 4 步），返回 `[{name, pos, rot, mirror}]`（pieces 列表序 = 装饰线处理序）。 |
| `_bb_intersects` | `(a, b) -> bool` | BoundingBox.intersects：两六元组闭区间三维重叠。 |
| `_bb_contains` | `(bb, p) -> bool` | BoundingBox.isInside：闭区间含点。 |
| `_decor_loot` | `(world_seed, pieces) -> list` | 装饰线箱子种子：逐区块建 Xoroshiro 流（pop+40005）、按 pieces 序 postProcess、Chest* 标记经 filterBlocks/isInside 后 `next_long()` = LootTableSeed；返回 `[{pos, loot_table, loot_seed, piece, marker}]`。 |
| `assemble_mansion` | `(world_seed, chunk_x, chunk_z) -> tuple[list, list, str]` | 对外入口：结构线（rot → MansionGrid → createMansion）+ 装饰线（_decor_loot）；返回 `(pieces, chests, rot_name)`。 |

**接口**：被 `composition.py` 导入——`assemble_mansion`（L1476 组装、L1515 重算体素）、`_ROT_NAMES`（rot 名→序号）、`_load_template` + `transform_pos`（composition 侧自行铺模板体素，L1520-1524）。本模块自身导入：`structure_map`（chunk_generate_rnd）、`block_shapes`（shape_from_palette）、`mc_random`（_MASK48、next_int/next_state）、`structure_models`（parse_nbt、_palette_entry_name/_palette_entry_props）、`loot_rng`（get_population_seed、XoroshiroJava、_M64）。对外提供方向/旋转变换工具（transform_pos 等）与模板缓存。

**关键变量/常量**：

| 名称 | 值/含义 |
|---|---|
| `_DIR_2D` | `("S","W","N","E")`——from2DDataValue 序（Direction BY_2D_DATA），recursiveCorridor 的 nextInt(4) 结果映射。 |
| `_HORIZONTAL` | `("N","E","S","W")`——Plane.HORIZONTAL 迭代序。 |
| `_STEP2` / `_STEP3` | 方向 → 单位位移映射（三维版含 UP）。 |
| `_CLOCKWISE` / `_COUNTER_CW` / `_OPPOSITE` | 方向旋转映射（N→E→S→W 等）。 |
| `_ROT_NAMES` / `_ROT_IDX` / `_MIRRORS` | `("NONE","CLOCKWISE_90","CLOCKWISE_180","COUNTERCLOCKWISE_90")`（Rotation.values() 序）与镜像枚举。 |
| `_CLEAR/_CORRIDOR/_ROOM/_START_ROOM/_TEST_ROOM/_BLOCKED` | SimpleGrid 格值 0~5。 |
| `_ROOM_1X1/_ROOM_1X2/_ROOM_2X2` | 房间类型位（65536/131072/262144）。 |
| `_ROOM_ORIGIN_FLAG/_ROOM_DOOR_FLAG/_ROOM_STAIRS_FLAG/_ROOM_CORRIDOR_FLAG` | 房间附加旗标（1048576/2097152/4194304/8388608）：门位格/门旗标/楼梯间/走廊侧房间。 |
| `_ROOM_TYPE_MASK` / `_ROOM_ID_MASK` | 983040 / 65535，格值拆位用。 |
| `_ASSET_DIR` | 模板资产目录（73 个 1.21.11 原版 jar 的 woodland_mansion NBT）。 |
| `_TPL_CACHE` / `_TPL_CACHE` 键 | 模板解析缓存（name → dict）。 |
| `_MANSION_LOOT_TABLE` | `"chests/woodland_mansion"`（唯一随机箱表）。 |
| `_MANSION_STEP` / `_MANSION_DECORATOR` / `_MANSION_SALT_OFFSET` | `4` / `5` / `40005`（SURFACE_STRUCTURES + 注册序 5）。 |

---

## `Utils/StructurePreviewer/end_city_pieces.py`

**功能**：末地城（End City）逐 piece 精确生成。RNG 权威基准为 cubiomes `finders.c getEndCityPieces`（L2336-2595）逐行转写，拼装 RNG 为 48 位 LCG（`structure_map.chunk_generate_rnd` + `mc_random` 函数式 API），loot 流为 Xoroshiro per-chunk。产出 `EndCityResult`（piece 树 + 箱子种子），并提供两套体素拼装（原始方块名版供对拍、材质映射版供显示）。

### 递归/队列组装流程与 RNG 消耗顺序

1. **入口 `build_end_city`**：`min_bx/z = block & ~15` 取区块角；`rng = chunk_generate_rnd(world_seed, min_bx>>4, min_bz>>4)`；`rot = nextInt(4)`（消耗 1 次，起始件朝向）；`ship = [0]`（单元素列表模拟 C 指针共享，genBridge 置位须穿透局部 env）；首件链：BASE_FLOOR（区块中心 `(min_bx+8, 0, min_bz+8)`）→ SECOND_FLOOR_1 (-1,0,-1) → THIRD_FLOOR_1 (-1,4,-1) → THIRD_ROOF (-1,8,-1)；然后 `_gen_recursively(_gen_tower, base, depth=1)`；`_assign_chests` 填箱子；返回 `EndCityResult(anchor, rot, pieces, ship, rng_state)`。
2. **`_gen_recursively`（genPiecesRecusively）**——批生成与弃置机制：`depth > 8` 直接返回 0；建局部 env（rng 从外层当前状态起、ship 指针共享、y 值拷贝）；调生成器填局部 pieces（**成败都把局部 rng 回写外层，即 RNG 消耗保留**）；成功后 `gendepth = next(rng, 32)`（**按 Java int 有符号解析，可为负**——无符号值会破坏 depth>8 判断）；对局部每个 piece 与主列表全体做 AABB 闭区间相交检查：与 `current.depth` **不同**的相交 piece → 整批弃置（返回 0）；同 depth 相交放行；通过后整批加入主列表并写 `depth = gendepth`。
3. **四个递归生成器**（每个都是"先 addPiece 后递归"的深度优先树）：
   - `_gen_tower`：`x = nextInt(2)+3`、`z = nextInt(2)+3`；TOWER_BASE (x,-3,z) → TOWER_PIECE (0,7,0)；`t = nextInt(3)`（t==0 记 floor）、`floorcnt = nextInt(3)+1`；循环加 TOWER_PIECE (0,4,0)，层间消耗 `next(1)` 决定 floor 更新；若有 floor：四方向各消耗 `next(1)`，命中则 BRIDGE_END + `_gen_recursively(_gen_bridge, depth+1)`；若无 floor 且 `depth != 7`：`_gen_recursively(_gen_fat_tower, depth+1)`；收尾 TOWER_TOP (-1,4,-1)。
   - `_gen_bridge`：`floorcnt = nextInt(4)+1`；BRIDGE_PIECE (0,0,-4)（depth=-1）；循环 floorcnt 次：`next(1)` 命中 → BRIDGE_PIECE（y 归零）；否则再 `next(1)` 分 BRIDGE_STEEP_STAIRS (0,y,-4) / BRIDGE_GENTLE_STAIRS (0,y,-8)，楼梯后 y=4；**END_SHIP 短路**：`ship[0]` 已置位时不消耗 `nextInt(10-depth)`，否则该掷命中 0 才生成船（`xs=nextInt(8)`、`zs=nextInt(10)`，END_SHIP 落 (xs-8, y, zs-70) 并置 `ship[0]=1`）；不生成船则 `env.y = y+1`、`_gen_recursively(_gen_house_tower, depth+1)`（失败返回 0 令整批弃置）；收尾反向 BRIDGE_END (4, y, 0)，depth=-1。
   - `_gen_house_tower`：`depth > 8` 返回 0；BASE_FLOOR (-3, env.y, -11)；`size = nextInt(3)`：0 → 仅 BASE_ROOF；1 → +SECOND_FLOOR_2+SECOND_ROOF；2 → +SECOND_FLOOR_2+THIRD_FLOOR_2+THIRD_ROOF；收尾 `_gen_recursively(_gen_tower, depth+1)`。
   - `_gen_fat_tower`：FAT_TOWER_BASE (-3,4,-3) → FAT_TOWER_MIDDLE (0,4,0)；`while j < 2`：`t = nextInt(3)`，t==0 break；否则再加 FAT_TOWER_MIDDLE (0,8,0) 并四方向各消耗 `next(1)` 生成 BRIDGE_END + `_gen_recursively(_gen_bridge)`；收尾 FAT_TOWER_TOP (-2,8,-2)。
4. **`_add_piece`（addEndCityPiece）**：查 `_PIECE_INFO[typ]` 名义尺寸，AABB 按 rot 扩展（rot0: bb1.x+=sx / bb1.z+=sz，其余 rot 同族变换）；prev 非空时相对偏移按 `prev.rot` 变换（0:+px,+pz / 1:-pz,+px / 2:-px,-pz / 3:+pz,-px）后平移 pos 与 AABB；piece 追加进 `env.pieces`。
5. **箱子与 LootTableSeed（`_assign_chests`，xp finders.c End_City 分支）**：有箱 piece 仅三种——FAT_TOWER_TOP（局部偏移 (3,11)/(5,13) 两箱）、END_SHIP（(5,7)/(7,7) 两箱）、THIRD_FLOOR_2（(6,2) 一箱）；箱子世界坐标 = `(pos-1) + R(偏移)`（R 为无修正旋转 `_rot_xz`，已对模板 NBT 箱子坐标四旋转逐一吻合验证）；流分组：单箱独立流 skip1 取1；同 piece 双箱**同区块** → 同流 skip2 取2，**跨区块** → 各自流 skip1 取1（skip 的 nextLong = placeInWorld 写入的未使用 LootTableSeed；模板 NBT 中箱子上方 DATA 结构方块实锤"固定 1 消耗 + 每箱 1 消耗"）；salt 档 `end_city = (4, 2)`（1.19.4+）；每箱记录 `(世界x, 世界z, "chests/end_city_treasure", loot_seed)`。
6. **几何口径**：piece 锚点 = 模板局部 (1, y, 1) 格（模板原点 = piece_pos - (1,0,1)）；方块世界坐标 = piece_pos - (1,0,1) + R(local)；fat_tower_top 的 AABB 用名义 16×5×16（渲染用真实模板 17×6×17 含悬挑），ship 同理（名义 12×23×28，模板 13×24×29）。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_next` | `(state: int, bits: int) -> tuple[int, int]` | C next(rng, bits)：推进一次 LCG 取高 bits 位；bits=32 时按 Java int 转有符号（批次深度用，可为负）。 |
| `_add_piece` | `(env, prev, rot, px, py, pz, typ) -> EndPiece` | addEndCityPiece：名义尺寸 AABB + 相对偏移按 prev.rot 变换，piece 追加进 env.pieces（见上文第 4 步）。 |
| `_gen_recursively` | `(gen, env, current, depth) -> int` | genPiecesRecusively：局部 env 批生成、批深度 next(32) 有符号、AABB 相交检查（异 depth 相交整批弃置、RNG 消耗保留），见上文第 2 步。 |
| `_gen_tower` | `(env, current, depth) -> int` | 细塔生成器：底座/塔身/tower_top 与四向桥接或转 fat_tower（见上文第 3 步）。 |
| `_gen_bridge` | `(env, current, depth) -> int` | 桥生成器：桥段/楼梯序列 + END_SHIP 短路 + house_tower 递归（见上文第 3 步）。 |
| `_gen_house_tower` | `(env, current, depth) -> int` | 小屋塔生成器：base_floor + 一/二/三层屋顶三变体 + 转回 tower。 |
| `_gen_fat_tower` | `(env, current, depth) -> int` | 粗塔生成器：底座/两层中段 + 四向桥接（`_FAT_BINFO` 偏移表）+ tower_top。 |
| `_rot_xz` | `(rot, x, z) -> tuple[int, int]` | 无修正旋转 R：0 恒等 / 1 (x,z)→(-z,x) / 2 (-x,-z) / 3 (z,-x)。 |
| `_assign_chests` | `(pieces, world_seed, version_key) -> None` | 按 xp End_City 分支逐 piece 填箱子坐标与 LootTableSeed（流分组规则见上文第 5 步）。 |
| `build_end_city` | `(world_seed, block_x, block_z, version_key="1.21") -> EndCityResult` | 公共入口：getEndCityPieces 全流程 + 箱子分配（见上文第 1 步）；block 坐标内部 &~15 取区块角。 |
| `_raw_template` | `(name: str) -> dict` | 模板 NBT（`templates/endcity__<name>.nbt`）→ 原始方块名体素 dict（`_RAW_CACHE` 缓存；palette 经 `shape_from_palette`，air 保留在原始 dict 中待材质映射阶段剔除）。 |
| `_rot_xz3` | `(rot, x, y, z) -> tuple` | 无修正旋转 R 的三维版（y 不变）。 |
| `end_city_raw_voxels` | `(pieces, anchor) -> dict` | piece 列表 + anchor → 原始方块名拼装体素（模型口径 `(x,z)=世界-anchor、y=世界-64`；**对拍测试用**）。 |
| `end_city_voxels` | `(pieces, anchor) -> dict` | 拼装显示体素：逐 piece 加载模板、材质映射 `structure_models._map_block`（air/structure_block 映射 None 自动剔除；`halfheight:` 前缀转半砖形状码）、形状码随 piece 旋转同步（`shape_rotation` 与 R 同族）；覆盖顺序 = pieces 列表顺序（与 Java postProcess 同序，后写覆盖先写）。 |
| `EndPiece` | dataclass | 单 piece：`name/type/rot/pos/bb0/bb1/depth/chests`（pos 为世界锚点，首件绝对坐标、其余链式累积；bb1 为含端点最大角；chests 由 `_assign_chests` 填充）。 |
| `EndCityResult` | dataclass | build_end_city 完整结果：`anchor`（区块角）、`rotation`、`pieces`、`ship`（本城是否生成 End Ship）、`rng_state`（piece 流最终 48 位状态，备用）。 |
| `_Env` | 类 | PieceEnv：`pieces` 列表 + `rng` 状态（不可变整数，赋值回写推进）+ `ship`（单元素列表模拟 C 指针共享）+ `y`（值拷贝：genBridge 写、genHouseTower 读，批被弃置时外层 y 不回传）。 |

**接口**：被 `composition.py` 导入——`build_end_city`（L952，EndPiece → Piece/Chest 数据结构转换前的一手数据）、`end_city_voxels`（L2863 显示模型）；`end_city_raw_voxels` 供对拍测试使用。本模块自身导入：`structure_map`（chunk_generate_rnd）、`mc_random`（next_int/next_state）、`loot_rng`（salt_configs_for_version、get_population_seed、XoroshiroJava）。对外还提供 20 个 piece 类型常量与 `PIECE_NAMES` 名称表。

**关键变量/常量**：

| 名称 | 值/含义 |
|---|---|
| `BASE_FLOOR`~`TOWER_TOP` | 20 个 piece 类型常量（range(20)，**索引即类型号、顺序不可动**，对应 addEndCityPiece 的 info[]）。 |
| `_PIECE_INFO` | (名称, sx, sy, sz) 名义尺寸表（finders.c L2338-2359）；`tower_floor` 标注 unused（Java 亦未生成）。 |
| `PIECE_NAMES` | 名称元组（`_PIECE_INFO` 首列）。 |
| `_TOWER_BINFO` | genTower 四向桥接表 `(rot偏移, px, py, pz)`：((0,1,-1,0),(1,6,-1,1),(3,0,-1,5),(2,5,-1,6))。 |
| `_FAT_BINFO` | genFatTower 四向桥接表：((0,4,-1,0),(1,12,-1,4),(3,0,-1,8),(2,8,-1,12))。 |
| `_LOOT_TABLE` | `"chests/end_city_treasure"`（全部箱子同表）。 |
| `_RAW_CACHE` | 模板原始体素缓存（name → dict）。 |

---

## `Utils/StructurePreviewer/fortress_pieces.py`

**功能**：下界要塞（Nether Fortress）**逐方块布局转写层**——把 `composition.compose_nether_fortress` 生成的 piece 序列（树拼装在 composition 层，本模块不做）按官方 `NetherFortressPieces.java`（26.1 官方未混淆源码）的 postProcess 逐段转写为模型体素 dict `{(x,y,z): 值}`。

坐标与朝向语义（StructurePiece.java 字节码级定案）：`getWorldX/Y/Z` 的 facing 0..3 = C 口径 `Plane.HORIZONTAL` 随机序 {N,E,S,W}——0 NORTH: `x=minX+x, z=maxZ-z`；1 EAST: `x=minX+z, z=minZ+x`；2 SOUTH: `x=minX+x, z=minZ+z`；3 WEST: `x=maxX-z, z=minZ+x`；y = bb.minY + y。方向性方块（楼梯 FACING）经 placeBlock 内 mirror/rotate 的净效果即 `_WX_STAIRS` 映射表（0 恒等、1 CW90、2 LEFT_RIGHT 镜像、3 镜像+CW90）。

已知妥协（源码注释声明、用户已认可）：无地形（fillColumnDown 全部跳过）；箱子朝向固定局部 north（真实游戏按周边固体邻居 reorient，LootTableSeed 口径不变）；spawner/lava 恒放置（真实游戏受 chunkBB.isInside 限制）；y 基准恒 64（不模拟 moveInsideHeights 平移）；AIR = generateBox 显式挖空（体素 pop），postProcess 按 accepted 顺序执行、后写胜出。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_PieceBB` | 类 | piece 世界包围盒（Java BoundingBox 语义，min/max 含端点）：由 composition 的 `(bb0, bb1)` 换算；`world_xy(x, z, facing)` 为 getWorldX/getWorldZ 联合映射（字节码定案表，见上文四朝向公式）。 |
| `_Ctx` | 类 | 单 piece 的 postProcess 上下文：`place`（局部坐标→世界写入，方向性状态在 `stairs` 中变换）、`stairs`（局部 FACING → 世界 FACING 的楼梯材质+形状码）、`fence`（generateBox 栅栏，统一 post 形状码、状态无关，连臂由渲染层按邻居自动处理）、`box`（generateBox 全格写）、`air_box`（generateBox(...,AIR) 显式挖空=体素 pop）。 |
| `_piece_start_bridge_crossing` | `(c: _Ctx) -> None` | BridgeCrossing.postProcess（StartPiece/NeStart 同布局）：十字桥面 + 挑空走廊 + 支撑柱，四臂对称。 |
| `_piece_bridge_straight` | `(c: _Ctx) -> None` | BridgeStraight.postProcess：直廊桥 + 两侧四组栅栏（nseFence/nswFence）。 |
| `_piece_room_crossing` | `(c: _Ctx) -> None` | RoomCrossing.postProcess：7×7 房间 + 四向门洞 + 檐口栅栏。 |
| `_piece_stairs_room` | `(c: _Ctx) -> None` | StairsRoom.postProcess：高竖井 + 螺旋上升的石砖台阶（逐级 box 抬升）。 |
| `_piece_monster_throne` | `(c: _Ctx) -> None` | MonsterThrone.postProcess（烈焰人刷怪笼王座）：阶梯状王座 + 环形栅栏（含端头单臂 post）+ spawner 局部 (3,5,5)。 |
| `_piece_castle_enterance`→`_piece_castle_entrance` | `(c: _Ctx) -> None` | CastleEntrance.postProcess：大城堡门 + 顶檐栅栏列 + 中央岩浆井（(6,5,6) lava，底下挖空通道）。 |
| `_piece_castle_small_corridor` | `(c: _Ctx) -> None` | CastleSmallCorridorPiece.postProcess：5×5 小走廊（无箱）。 |
| `_piece_corridor_turn` | `(c: _Ctx, chest: bool) -> None` | CastleSmallCorridorRightTurnPiece.postProcess：右拐走廊，`chest` 为真时局部 (1,2,3) 放箱（isNeedingChest 来自 composition 的 chest_count）。 |
| `_piece_corridor_turn_left` | `(c: _Ctx, chest: bool) -> None` | CastleSmallCorridorLeftTurnPiece.postProcess：左拐镜像版，箱在局部 (3,2,3)。 |
| `_piece_corridor_stairs` | `(c: _Ctx) -> None` | CastleCorridorStairsPiece.postProcess：10 级下行走廊（floor/roof 逐级演算，奇偶步放栅栏），楼梯局部 FACING=SOUTH 经 `_Ctx.stairs` 变换。 |
| `_piece_t_balcony` | `(c: _Ctx) -> None` | CastleCorridorTBalconyPiece.postProcess：T 形阳台 + 底部通道洞 + 三面栅栏。 |
| `_piece_corridor_crossing` | `(c: _Ctx) -> None` | CastleSmallCorridorCrossingPiece.postProcess：十字小走廊。 |
| `_piece_stalk_room` | `(c: _Ctx) -> None` | CastleStalkRoom.postProcess：大厅 + 中央七级螺旋楼梯（FACING=NORTH）+ 平台边缘楼梯（W/E）+ 两块地狱疣田（soul sand 床 + SHAPE_CROSS 地狱疣）。 |
| `_piece_bridge_end_filler` | `(c: _Ctx, self_seed: int) -> None` | BridgeEndFiller.postProcess：**本模块唯一的独立 RNG 消耗点**——`selfRandom = RandomSource.createThreadLocalInstance((long)selfSeed)`（LegacyRandomSource），用 `loot_rng.JavaRandom` 复刻；selfSeed 为无符号 32 位捕获（mc_random.next_bits），Java 存储为有符号 int32，先转回有符号再播种；随后消耗 `nextInt(8)`×10（两组 y=3/4 的桥面延伸）、`nextInt(8)`×2（檐口）、`nextInt(5)`×5（中段）、`nextInt(3)`×10（底层），逐列画不对称的下界砖残段。 |
| `build_fortress_voxels` | `(comp) -> dict` | 入口：遍历 `comp.pieces`（accepted 顺序 = Java postProcess 顺序，后写胜出），把 piece AABB 平移到模型系（- anchor，y-64），按 `_DISPATCH`/专用分支逐类型执行布局转写；`p.bb is None` 或 type=14 缺 self_seed 的 piece 跳过；返回值不含箱子标注逻辑（compose_display_model 负责）。 |

**接口**：被两方导入——`composition.py`（L2477-2478：`build_fortress_voxels` 生成显示体素）；`stronghold_pieces.py`（L730-731：复用 `_Ctx` 作 `_CtxS` 基类、`_PieceBB` 与 `_WX_STAIRS` 朝向映射表）。本模块自身导入：`block_shapes`（SHAPE_STAIRS/SHAPE_FENCE_POST/SHAPE_CHEST_N/SHAPE_CROSS）、`loot_rng`（JavaRandom，仅 BridgeEndFiller 用）。对外提供 `_DISPATCH`（类型号→布局函数）与 `_WX_STAIRS`。

**关键变量/常量**：

| 名称 | 值/含义 |
|---|---|
| `NB` / `LAVA` / `SOUL_SAND` / `SPAWNER` / `CHEST_MAT` | 材质键：nether bricks / lava / soul sand / spawner / chest（`CHEST_MAT` 需含 "chest"，供分面纹理判定）。 |
| `_FENCE` | `(NB, bs.SHAPE_FENCE_POST)`，栅栏统一输出 post 形状码（connect_arms 自动连臂，不区分 nsew 状态）。 |
| `_WART` | `("nether wart", bs.SHAPE_CROSS)`，地狱疣作物。 |
| `_WX_STAIRS` | 楼梯局部朝向→世界朝向映射表（索引 = piece facing 0..3）：0 恒等、1 CW90（n→e/s→w/e→s/w→n）、2 LEFT_RIGHT 镜像（n/s 不变、e↔w）、3 镜像+CW90（n→e/s→w/e→n/w→s）。被 stronghold_pieces 复用。 |
| `_DISPATCH` | 类型号 → 布局函数：0/2 → start_bridge_crossing（NeStart/NeBCr 同布局）、1 → bridge_straight、3 → room_crossing、4 → stairs_room、5 → monster_throne、6 → castle_entrance、7 → castle_small_corridor、8 → corridor_crossing、12 → t_balcony、13 → stalk_room；9/10（左右拐角，需 chest 标志）与 14（需 selfSeed）单独分发。 |

---

## 附：模块间数据流总览

```
世界种子
  ├─ loot_rng.get_population_seed / _SALT_1194 / loot_seed_for_chest
  │     └─ 各 *_pieces 的 loot 段：XoroshiroJava(pop + decorator + 10000*step) → next_long = LootTableSeed
  ├─ structure_map.chunk_generate_rnd（LegacyRandom 拼装流）
  │     ├─ stronghold_pieces.assemble_stronghold（队列扩展 + 重试循环）
  │     ├─ mansion_pieces.LegacyRandom → MansionGrid → _create_mansion
  │     └─ end_city_pieces.build_end_city（递归批生成）
  ├─ composition.py：Piece/Chest 数据结构（含 end_city/fortress 等其余结构）
  └─ loot_engine.generate_loot(JavaRandom(LootTableSeed), load_loot_snapshot(...))
        └─ ItemStack 列表（tool_StructurePreviewer.py 显示开箱结果）
```

其中体素渲染：`build_stronghold_voxels`（要塞，self-contained）、`end_city_voxels`（末地城，self-contained）、`build_fortress_voxels`（下界要塞，输入为 composition 的 piece 序列）、林地府邸由 composition 用 `mansion_pieces._load_template` + `transform_pos` 自行铺模板体素。

---

# 09c — StructurePreviewer 拼装层与定位层（village / outpost / trial / ancient_city / locator / 包说明）

> 依据源码精读整理（源码版本对应 MC Java 1.21 / 1.21.11 jar 资产口径）。
> 四个 `*_assembly` 模块均为「薄适配层」：结构专属常量 + 资产根绑定（`load_template` / `load_pool`）+ 拼装入口（委托 `Utils/SeedReverser/jigsaw_assembly.py` 通用引擎，下称 **JA**）+ 渲染期单方块处理器（降解 / RuleProcessor）。
> `jigsaw_assembly.assemble_jigsaw` 的通用主流为：重建布局 RNG（`make_layout_rng(level_seed, chunk_x, chunk_z)`）→（可选 `skip_y_bound` 补位）→ `rotation = nextInt(4)` → 起点池 pick `nextInt(总权重)` →（`start_jigsaw_name` 时起点标记洗牌 + anchor 重定位）→ `dy = k - (box.minY + groundLevelDelta)` → 外层大盒（xz = 中心±maxDist 含端 +1）→ `_Placer` 逐 jigsaw 标记扩展（连接判定 / 域扣除 / 候选 shuffle）。四个模块通过关键字参数把结构 JSON 定案注入该引擎。

---

## `Utils/StructurePreviewer/village_assembly.py`

**功能**：村庄（village）拼装模块，复用 JA 通用引擎，覆盖 desert / plains / savanna / snowy / taiga 五个变体及僵尸村庄起点链。

- **结构定义定案**（1.21.11 jar 提取 `data/minecraft/worldgen/structure/village_<biome>.json` ×5 与 `structure_set/villages.json`）：五变体结构键 `village_desert / village_plains / village_savanna / village_snowy / village_taiga` 共用 placement（`salt=10387312, spacing=34, separation=8`，与 `structure_params.STRUCT_PARAMS["village"]` 一致，锚点相同，具体生成哪个变体由锚点群系决定）；`type=jigsaw`，`start_pool=village/<biome>/town_centers`、`size=6`、`max_distance_from_center=80`、`start_height=absolute(0)`、`project_start_to_heightmap=WORLD_SURFACE_WG`（起点底面 = 地表，引擎参数 `start_y_is_offset=True`，与 outpost 同式）、`terrain_adaptation=beard_thin`（仅地形贴合，预览不建模）、`use_expansion_hack=true`（引擎 `expansion_hack=True`，子件盒顶部按池 maxSize 扩展）。
- **起点池与僵尸链**：以 plains 为例，起点池 8 元素 = 4 个普通中心 ×weight50 + 4 个僵尸中心 ×weight1（总权重 204）；僵尸中心的 street 标记指向 `village/<biome>/zombie/streets` 池，从而展开完整僵尸村庄链（1.21.x 僵尸村庄回归为起点池元素，无独立结构定义）。起点 pick 尺寸表与 `structure_map._VILLAGE_TABLES/_VILLAGE_TABLE_MOD` 逐项吻合（cubiomes `getVariant` 的 village 表即由此池推导）。
- **池元素类型**：`legacy_single`(592) / `empty`(22) / `feature`(35)，全部池无 `list_pool_element`。legacy 的 `getBoundingBox` = 全模板盒（与 JA `TemplateModel` 同口径）；feature（村民/猫/铁傀儡/动物等地物）由引擎按 `fgs$b` 语义跳过；empty 作为终止候选。
- **资产加载流程**：资产根 `assets/SeedReverser/village/`（下含 `templates/`、`template_pool/`、`processors/`）。`load_template(key)` 的 key **保留** `village/` 前缀（即相对路径层级 `templates/village/plains/houses/….nbt`），独立缓存 `_TEMPLATE_CACHE`，缺失模板返回零尺寸空模板（与 ancient_city 同款防御语义，解析本体复用 `JA._parse_template`）；`load_pool(pool_id)` 剥命名空间后**剥除** `village/` 层（池资产目录以 jar 剥除 `template_pool/village/` 后为根，无 `village/` 层），`minecraft:empty` 为注册过的空池（无 JSON）经 `JA.parse_pool_dict("empty", {})` 构造，独立缓存 `_POOL_CACHE`。
- **拼装入口与 RNG 消耗**：`assemble_village(level_seed, chunk_x, chunk_z, variant="plains", surface_y=None)` 实现 `fhp.a + fgs.a` 的 1.21 语义。`surface_y` 为锚点区块中心地表高度（WORLD_SURFACE_WG），预览无地形数据缺省 63（海平面平坦基准，闭包 `terrain_height_fn` 恒返回该值），整体 y 平移不影响拼装拓扑与 RNG 消耗；随后委托 `JA.assemble_jigsaw`，注入 `start_pool_id=f"village/{variant}/town_centers"`、`max_depth=6`、`start_y=surface_y`、`start_y_is_offset=True`（dy = start_y-(minY+groundLevelDelta=1)）、`max_dist=80`、`pad_bottom=0/pad_top=0`、`expansion_hack=True`、两个加载器闭包。主流消耗：`rotation nextInt(4)` → 起点 pick `nextInt(204)`（plains）→ 起点标记洗牌 → 展开池。
- **处理器子系统**（`apply_processor`，16 种 RuleProcessor 入库 `assets/.../village/processors/`）：数据驱动引擎，JSON 解析为 5 类 rule 元组（`rb`/`b`/`bs`/`rbs`/`tag`）+ location 谓词。每方块独立 `LegacyRandomSource(Mth.getSeed(x,y,z))`（内联 LCG，与 bastion `apply_degradation` 同式），规则链按 JSON 序共用一条流；input 谓词短路——不匹配的规则不消耗随机数，`random_block[_state]_match` 匹配才消耗 `next(24)*2^-24`；不在规则输入集的方块走零消耗快速路径。location_predicate 除 `always_true` 外（村庄仅 `block_match water`）在平坦预览无世界上下文恒 False → 规则不命中（水面街道变化属预览已知妥协）。命中返回 `output_state` 的 (Name+Properties)；输出 `minecraft:air` 返回 `None`（不放置）。`zombie_*` 处理器的 `tag_match(#minecraft:doors)` → air、`blockstate_match`（glass_pane 连接态 → 棕色玻璃板）均已支持。处理器逐方块独立流**不消耗布局/装饰 RNG**，LootTableSeed 不受影响。
- **与 composition.py 的协作分工**：`composition.compose_village` 先用 `va.variant_from_biome` 定变体、`structure_map.chunk_generate_rnd` 起点流采 rotation，再调 `va.assemble_village` 得 `AssemblyResult`；容器口径（62 chest 全带 LootTable、18 barrel 空桶不消耗流）由 composition 用 `va.ASSET_DIR` 直读模板 NBT 收集，LootTableSeed 走每区块 population 流（salt=(4, 22..26) 按变体）；体素渲染 `_village_jigsaw_voxels` 再次调 `va.assemble_village` 复现同一 piece 序列，并逐方块调 `va.apply_processor` 完成 mossify/farm/street/zombie 处理器降解。即：**本模块负责「拼出什么 + 每个方块变不变」，composition 负责「箱子在哪 + LootTableSeed + 展示模型」**。

**类与函数**（模块无类，纯函数组织）：

| 名称 | 签名 | 说明 |
|---|---|---|
| `variant_from_biome` | `(biome_id: int) -> str` | 锚点群系 id → 村庄变体（与 `structure_map._check_village` 同口径：`MEADOW` 按 plains）；五变体逐一比对 `structure_map` 的群系常量，未知群系回退 plains（演示模式）。 |
| `_strip_ns` | `(rid: str) -> str` | 剥除资源 id 的 `minecraft:` 命名空间前缀。 |
| `load_template` | `(key: str) -> JA.TemplateModel` | key 保留 `village/` 前缀映射到 `templates/village/….nbt`；带缓存；缺失模板返回零尺寸空 `TemplateModel`（防御语义，非异常）。解析委托 `JA._parse_template`。 |
| `load_pool` | `(pool_id: str) -> JA.StructureTemplatePool` | 剥命名空间并剥 `village/` 层后读 `template_pool/<….>.json`，经 `JA.parse_pool_dict` 构造池；`'empty'` 特判为注册空池（无 JSON）；带缓存。 |
| `assemble_village` | `(level_seed: int, chunk_x: int, chunk_z: int, variant: str = "plains", surface_y: Optional[int] = None) -> JA.AssemblyResult` | 拼装入口（`fhp.a + fgs.a` 1.21 语义）。缺省 `surface_y=63` 构造平坦地形高度闭包后全参数委托 `JA.assemble_jigsaw`（详见上「拼装入口与 RNG 消耗」）。 |
| `_load_proc` | `(pid: str) -> Optional[Tuple[tuple, frozenset]]` | 处理器 id → `(rules, input_blocks)`；`'empty'` 与解析失败均缓存为 `None`。把 JSON 规则编译为 5 类元组：`("rb", block, prob, loc, out_name, out_props)`、`("b", block, loc, …)`、`("bs", name, props, loc, …)`、`("rbs", name, props, prob, loc, …)`、`("tag", members, loc, …)`；`tag.endswith("doors")` 成员集取 `_DOORS`，其余 tag 为空集。 |
| `apply_processor` | `(pid: Optional[str], name: str, props: Optional[dict], x: int, y: int, z: int) -> Optional[Tuple[str, dict]]` | 单方块处理器（village RuleProcessor 语义）。返回落地 `(name, props)`，`None` = air 不放置。内联 LCG 每方块建流、规则链共用；输入集外零消耗快速路径；random 规则命中判据 `(state>>24)*2^-24 < prob`；location 谓词非 `always` 时平坦预览恒跳过；输出 air 返回 `None`。 |

**接口**：被 `Utils/StructurePreviewer/composition.py` 以 `from Utils.StructurePreviewer import village_assembly as va` 延迟导入 4 处（`compose_village`、`_village_jigsaw_voxels`、模板原始方块/容器读取两处直用 `va.ASSET_DIR`）。对外提供：`load_template` / `load_pool` / `assemble_village` / `apply_processor` / `variant_from_biome` / `VARIANTS` / `ASSET_DIR`。本模块又导入 `Utils.SeedReverser.jigsaw_assembly`（JA）与 `Utils.SeedReverser.mc_rng`（`MASK_48/MASK_64/MULT/ADD/mth_get_seed`），并函数内导入 `Utils.Public.structure_map`（群系常量）。

**关键变量/常量**：

| 名称 | 值 | 说明 |
|---|---|---|
| `PROJ_ROOT` | `Path(__file__).resolve().parents[2]` | 项目根，用于定位 assets。 |
| `ASSET_DIR` | `PROJ_ROOT / "assets" / "SeedReverser" / "village"` | 村庄资产根（templates / template_pool / processors 三层）。 |
| `VILLAGE_MAX_DEPTH` | `6` | `village_*.json` 的 `"size": 6`（jigsaw 展开深度）。 |
| `VILLAGE_MAX_DIST` | `80` | `max_distance_from_center`（外层大盒半径）。 |
| `_VILLAGE_TERRAIN_Y` | `63` | WORLD_SURFACE_WG 平坦基准（预览缺省地表高度，outpost 同式）。 |
| `VARIANTS` | `("desert", "plains", "savanna", "snowy", "taiga")` | 五个村庄变体键。 |
| `_PROC_DIR` | `ASSET_DIR / "processors"` | 16 种 RuleProcessor JSON 所在目录。 |
| `_INV_2POW24` | `1.0 / (1 << 24)` | `next(24)` 定点数 → float 的乘法逆（`nextFloat` 判据用）。 |
| `_DOORS` | 22 种门的 `frozenset` | `#minecraft:doors` 展开全集（1.21.11 jar tags/block/doors.json + wooden_doors 展开，含全部木质/铜质/下界/绯红/诡异门与 iron_door）。 |
| `_TEMPLATE_CACHE` / `_POOL_CACHE` | `Dict[str, …]` | 模板/池独立缓存（key 保留结构前缀层级）。 |
| `_PROC_CACHE` | `Dict[str, Optional[Tuple[tuple, frozenset]]]` | 处理器编译结果缓存（含负缓存 `None`）。 |

---

## `Utils/StructurePreviewer/outpost_assembly.py`

**功能**：掠夺者前哨站（pillager_outpost）拼装模块，复用 JA 通用引擎。反编译定案依据为 1.21.11 NeoForge（`.temp/mansion/decomp/...`）。

- **复用 JA 的注入方式**：`JigsawStructure`（fgs）`start_height absolute(0)` 零消耗；`project_start_to_heightmap=WORLD_SURFACE_WG` → 起点底面 = 地表（L100-102：`move(0, (start_y(0)+getFirstFreeHeight(中心)) - (minY+groundLevelDelta=1))`，引擎以 `start_y=surface_y, start_y_is_offset=True` 等价复算）；`use_expansion_hack=true` → `expansion_hack=True`（`$$37` 扩展语义，1.21.11 L315-342/L368-371；bastion/trial 为 False 不受影响）。
- **list_pool_element 支持**：`towers` 池唯一元素是 `list_pool_element`，经 `_list_element_hook` 转成 JA 的 `ListPoolElementSpec`——`location = elements[0]`（watchtower，标记/连接语义委托源），`sub_locations` = 全部子模板，`sub_processors` = 各子元素处理器 id（`None` = 无）；place 时依序放置全部子元素（watchtower 无处理器 + watchtower_overgrown 带 `minecraft:outpost_rot`）。
- **outpost_rot 降解**：`BlockRotProcessor.java L50` 语义——逐方块 `LegacyRandomSource(Mth.getSeed(worldX,worldY,worldZ)).nextFloat() > 0.05` → 删除该方块（即 5% 保留 / 95% 蚀），所有方块参与判定、无 rottable 集合限制；位置派生独立流，**不消耗布局/装饰 RNG**。
- **箱子口径**：watchtower NBT 无 chest 方块，由 DATA 标记（`ChestNorth` 等）经 `handleDataMarker` 放置，`createChest` 消耗装饰流 `nextLong()` 作 LootTableSeed（mansion 同范式，由 composition 层复刻，本模块不管箱子）。
- **资产加载流程**：资产根 `assets/SeedReverser/pillager_outpost/`；key 一律**剥除** `pillager_outpost/` 前缀（`_split_key`），`load_template` → `templates/<key>.nbt`（无缺失防御，缺失会抛文件读取错误；带缓存），`load_pool` → `template_pool/<key>.json`（`minecraft:empty` 特判为注册空池；`towers` 的 list 元素经 `_list_element_hook` 转引擎候选表示）。
- **拼装入口与 RNG 消耗**：`assemble_outpost(level_seed, chunk_x, chunk_z, surface_y=None)`——`surface_y` 缺省 63（`_OUTPOST_TERRAIN_Y` 海平面平坦基准；游戏走 `getFirstFreeHeight` 真实高度图，整座结构 y 平移不影响拼装拓扑与 RNG 消耗；`terrain_height_fn` 闭包同时供 feature_plates 的 terrain_matching 子件 `getFirstFreeHeight` 近似，不消耗 RNG）；委托 `JA.assemble_jigsaw`，注入 `start_pool_id="pillager_outpost/base_plates"`、`max_depth=7`（`pillager_outpost.json "size": 7`）、`start_y=surface_y`、`start_y_is_offset=True`、`max_dist=80`、`pad_bottom=0/pad_top=0`、`expansion_hack=True`。主流消耗与村庄同式：rotation `nextInt(4)` → start pick → 起点标记洗牌 → 展开池。
- **与 composition.py 的协作分工**：`composition.compose_outpost`（1165 行）调 `oa.assemble_outpost` 得 piece 序列；体素渲染层（2764 行）再次拼装并逐子元素判 `sub_processors == "outpost_rot"` 时调 `oa.apply_outpost_rot` 决定方块去留；composition 另用 `oa.ASSET_DIR + oa._split_key` 直读模板 NBT 做 DATA 标记箱子收集与 LootTableSeed 预测（`createChest` 装饰流语义）。

**类与函数**（模块无类）：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_strip_ns` | `(rid: str) -> str` | 剥资源 id 命名空间前缀。 |
| `_split_key` | `(key: str) -> List[str]` | key 按 `/` 切分并剥首段 `pillager_outpost/`，得资产相对路径段。 |
| `load_template` | `(key: str) -> JA.TemplateModel` | `'pillager_outpost/watchtower'` → `templates/watchtower.nbt`；缓存后委托 `JA._parse_template` 解析。 |
| `_list_element_hook` | `(el: dict) -> JA.ListPoolElementSpec` | `towers` 池 `list_pool_element` → 引擎候选：`location` 取 `elements[0]`（标记委托源），`projection`/`weight=1` 沿用，`sub_locations`/`sub_processors` 逐子元素展开（processors 非字符串记 `None`）。 |
| `load_pool` | `(pool_id: str) -> JA.StructureTemplatePool` | 剥前缀读池 JSON，传 `list_element_hook=_list_element_hook` 给 `JA.parse_pool_dict`；`'empty'` 特判空池；带缓存。 |
| `assemble_outpost` | `(level_seed: int, chunk_x: int, chunk_z: int, surface_y: Optional[int] = None) -> JA.AssemblyResult` | 拼装入口（`fgs.a` use_expansion_hack 语义）。缺省 63 构造平坦 `terrain_height_fn` 后委托 `JA.assemble_jigsaw`（参数见上）。起点投影注释定案：`$$30 = start_y(0) + surface(中心)`，引擎 `start_y_is_offset=True` 分支按 `dy = surface-(minY+1)` 复算，与字节码恒等。 |
| `apply_outpost_rot` | `(state_name: str, x: int, y: int, z: int) -> Optional[str]` | 单方块 5% 保留判定（内联 LCG，语义 = `BlockRotProcessor.a`）。`nextFloat() = next(24)*2^-24 = ((state*MULT+ADD)>>24)*2^-24` 与 `LegacyRandomSource` 数学恒等；`> 0.05` 返回 `None`（蚀），否则原样返回（保留）。 |

**接口**：被 `Utils/StructurePreviewer/composition.py` 以 `import outpost_assembly as oa` 延迟导入 5 处（拼装 ×2：`compose_outpost` 与体素层；`apply_outpost_rot` ×2；`ASSET_DIR/_split_key` 直读 NBT ×1）。对外提供：`load_template` / `load_pool` / `assemble_outpost` / `apply_outpost_rot` / `ASSET_DIR`。依赖 JA 与 `Utils.SeedReverser.mc_rng`（`MASK_48/MASK_64/MULT/ADD/_u/mth_get_seed`）。

**关键变量/常量**：

| 名称 | 值 | 说明 |
|---|---|---|
| `PROJ_ROOT` / `ASSET_DIR` | 项目根 / `assets/SeedReverser/pillager_outpost` | 资产根（templates / template_pool）。 |
| `START_POOL_ID` | `"pillager_outpost/base_plates"` | 起点池 id。 |
| `OUTPOST_MAX_DEPTH` | `7` | `pillager_outpost.json "size": 7`。 |
| `OUTPOST_MAX_DIST` | `80` | `max_distance_from_center`。 |
| `OUTPOST_START_Y` | `0` | `start_height absolute(0)`（地表注入前的常量记录）。 |
| `_OUTPOST_TERRAIN_Y` | `63` | features 池 terrain_matching 子件 y 基准的平坦近似（getFirstFreeHeight 无真实高度图时用；渲染可接受）。 |
| `_INV_2POW24` / `_LCG_MULT` / `_LCG_ADD` | `2^-24` / `MULT` / `ADD` | `apply_outpost_rot` 内联 LCG 所需常量（`nextFloat` 定点判据与乘加系数）。 |
| `_TEMPLATE_CACHE` / `_POOL_CACHE` | `Dict[str, …]` | 模板/池独立缓存。 |

---

## `Utils/StructurePreviewer/trial_assembly.py`

**功能**：试炼密室（trial_chambers，1.21+）拼装模块，复用 JA 通用引擎。字节码定案依据为 1.21.11 Fabric（工作空间 `%TEMP%\ekv_probe\*.txt`；类名映射 `fhp=JigsawStructure / fhc=PoolAliasLookup / fha 家族=PoolAliasBinding / fgs=JigsawPlacement / eur=LegacyRandomSource / bgj.b(III)=Mth.getSeed(III)`）。本模块独有两块引擎外逻辑：**pool_aliases 解析**与 **start_height 采样补位**。

- **`fhp.a` 拼装总入口顺序**（L160-208）：① `y = start_height` 采样（`uniform(-40,-20)` 即 `nextInt(21)-40`，位于 alias 与主流**之前**）→ ② `pos = (chunkX*16, y, chunkZ*16)` → ③ `fhc.create(aliases, pos, worldSeed)`（alias 专用流，不耗主流）→ ④ `fgs.a(...)` 主流（rotation → start pool）。
- **pool_aliases 机制**（`fhc.create` + `fha` 家族的 Python 复刻）：alias 流构造为 `factorySeed = (worldSeed ^ 0x5DEECE66D) & (2^48-1)`（`eur.e()` forkPositional 取当前 state 作 factorySeed）→ `rng = LegacyRandomSource(Mth.getSeed(x,y,z) ^ factorySeed)`（`eur$a.a(III)` 的 `lxor` 定案）；随后 3 个 binding 按 JSON 顺序 resolve：`direct`（fgz）零 RNG 直接映射；`random`（fhe）一次 `nextInt(总权重)` 前缀和选 target（`cbn.a` WeightedList 语义）；`random_group`（fhd）一次 `nextInt(总权重)` 选组、组内 binding 按序递归 resolve。trial 实际消耗序列：`random_group nextInt(3)` → `random(melee) nextInt(3)` → `random(small_melee) nextInt(4)`。
- **主流与 y 语义**：`fgs.a` 与 bastion 同引擎——rotation `nextInt(4)` → start pick；`dy = k - box.minY`（无投影、groundLevelDelta=0，起点件本地 minY=0 → dy=0），故 `start_y_is_offset=False`；`dimension_padding=10` 仅检查起始件（y∈[-40,-20] 恒过 -64+10）不进大盒 → `pad_bottom=0/pad_top=0`；外层大盒 xz = 起点中心±116（含端+1），y = [max(k-116,-64), min(k+117,320))。start_height 的 `nextInt(21)` 由调用方（`structure_map._jigsaw_variant`，y→rotation→start 顺序，可交叉验证）从 chunkGenerateRnd 同条流采出；本模块 `assemble_trial_chambers` 重建主流后以 **`skip_y_bound=21` 补位**（拒绝采样确定性相同 → 消耗次数逐位一致）再接 rotation/start pool。
- **资产加载流程**：资产口径 = 1.21 官方 jar（`assets/SeedReverser/trial_chambers/`：`trial_chambers.json` 结构定义 45 池 / 170 模板）；池/模板 key 均**剥除** `trial_chambers/` 前缀（`trial_chambers/chamber/end` → `template_pool/chamber/end.json`）；`load_template` 带缓存委托 `JA._parse_template`；`_load_pool_resolved` 是池加载核心（`'empty'` 特判——`minecraft:empty` 为注册空池、`entrance_cap` 的 fallback，空池 shuffle 零消耗与游戏一致），`load_pool` = 不做 alias 的直载（start_pool 等恒等映射场景）。结构定义 JSON 由 `_struct_def()` 惰性加载缓存，供 alias 解析读 `pool_aliases` 字段。
- **拼装入口与 RNG 消耗**：`assemble_trial_chambers(level_seed, chunk_x, chunk_z, y)`——先 `pos = (chunk_x*16, y, chunk_z*16)`、`resolve_aliases_cached` 取别名表；再以闭包 `load_pool_fn` 注入 JA：Placer 传入的 pool_id 先过 `alias.get(pool_id, pool_id)` 映射再加载（Direct/Random/RandomGroup 已在 resolve 阶段定案）；最后委托 `JA.assemble_jigsaw`，注入 `start_pool_id="trial_chambers/chamber/end"`、`max_depth=20`（`"size": 20`）、`start_y=y`、`start_y_is_offset=False`、`max_dist=116`、`pad_bottom=0/pad_top=0`、`skip_y_bound=21`。
- **铜灯降解**：`apply_trial_degradation` 实现 `trial_chambers_copper_bulb_degradation`（enm+eni 字节码语义；两版 JSON——1.21 / 1.21.11——逐字节比对一致）：仅 `waxed_copper_bulb` 参与判定，三条规则按序共用同一条每方块独立 `LegacyRandomSource(Mth.getSeed(x,y,z))` 流（`random_block_match = nextFloat() < prob`，首条命中即返回），概率 0.1 → `waxed_oxidized_copper_bulb`、0.33333334 → `waxed_weathered_copper_bulb`、0.5 → `waxed_exposed_copper_bulb`，至多消耗 3 次 nextFloat；输出态 Properties 恒 `lit=true/powered=false`（材质仅按方块名映射，引擎不需要输出 props）；不可降解方块直接原样返回。`protected_blocks` 处理器无 RNG，渲染可忽略。
- **与 composition.py 的协作分工**：`composition.compose_trial_chambers`（1012 行）调 `ta.assemble_trial_chambers` 得 piece 序列与 RNG 日志；体素层（2666 行）再次拼装并逐方块调 `ta.apply_trial_degradation`；composition 另用 `ta.ASSET_DIR + ta._split_key` 直读模板 NBT 做箱子（含 LootTable）收集。落点层的 y 采样在 `structure_map._jigsaw_variant` 完成（同条 chunkGenerateRnd 流），与本模块 skip_y_bound 补位构成「同消耗、可交叉验证」的分工。

**类与函数**（模块无类）：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_strip_ns` | `(rid: str) -> str` | 剥资源 id 命名空间前缀。 |
| `_split_key` | `(key: str) -> List[str]` | key 按 `/` 切分并剥首段 `trial_chambers/`，得资产相对路径段。 |
| `load_template` | `(key: str) -> JA.TemplateModel` | `'trial_chambers/hallway/straight'` → `templates/hallway/straight.nbt`；缓存 + `JA._parse_template`。 |
| `_load_pool_resolved` | `(resolved_id: str) -> JA.StructureTemplatePool` | 加载 **alias 解析后**的池 id（无 alias 语境走 `load_pool`）；`'empty'` 特判注册空池（无 JSON，空池 shuffle 零消耗）；缓存后 `JA.parse_pool_dict`。 |
| `load_pool` | `(pool_id: str) -> JA.StructureTemplatePool` | 不做 alias 的直载入口：`_load_pool_resolved(_strip_ns(pool_id))`。 |
| `_struct_def` | `() -> dict` | 惰性读取并缓存 `trial_chambers.json` 结构定义（内嵌解析，供 pool_aliases 用）。 |
| `_weighted_pick` | `(rng: LegacyRandomSource, weighted: List[Tuple[int, object]]) -> object` | `cbn.a`（WeightedList.getRandom）复刻：`nextInt(总权重)` → 前缀和取元素；末位兜底（浮点边界，理论不可达）。 |
| `_resolve_binding` | `(binding: dict, alias_map: Dict[str, str], rng: LegacyRandomSource) -> None` | 单 binding 解析：`direct` 零消耗直映射；`random` 一次 `nextInt(总权重)` 按 (weight, 序) 前缀和选 target；`random_group` 一次 `nextInt(总权重)` 选组后组内按序递归；未知类型抛 `ValueError`。 |
| `resolve_aliases` | `(level_seed: int, pos: Tuple[int, int, int]) -> Dict[str, str]` | `fhc.create` 复刻：`factorySeed = (_u(level_seed) ^ MULT) & MASK_48` → `rng = LegacyRandomSource(mth_get_seed(x,y,z) ^ factory_seed)` → 按 JSON 序 resolve 全部 binding，返回 `{alias_key(剥ns): target_key(剥ns)}`。 |
| `resolve_aliases_cached` | `(level_seed: int, pos: Tuple[int, int, int]) -> Dict[str, str]` | `(seed, x, y, z)` 四元组键的别名表缓存包装。 |
| `assemble_trial_chambers` | `(level_seed: int, chunk_x: int, chunk_z: int, y: int) -> JA.AssemblyResult` | 拼装入口（`fhp.a + fgs.a` 1.21 语义）。`y` 必须由调用方从 chunkGenerateRnd 同条流采出；本函数先取别名表、再以 alias 闭包注入 `load_pool_fn`，委托 `JA.assemble_jigsaw`（参数见上，含 `skip_y_bound=21` 补位）。 |
| `apply_trial_degradation` | `(state_name: str, x: int, y: int, z: int) -> str` | 单方块铜灯降解（内联 LCG，语义 = `enm.a + eni.a`，bastion 同式）。仅 `minecraft:waxed_copper_bulb` 建流，3 条规则共用流至多 3 次 nextFloat，未命中返回原 state。 |

**接口**：被 `Utils/StructurePreviewer/composition.py` 以 `import trial_assembly as ta` 延迟导入 4 处（拼装 ×2、`apply_trial_degradation` ×1、`ASSET_DIR/_split_key` 直读 NBT ×2）。对外提供：`resolve_aliases` / `resolve_aliases_cached` / `load_template` / `load_pool` / `assemble_trial_chambers` / `apply_trial_degradation` / `ASSET_DIR`。依赖 JA 与 `Utils.SeedReverser.mc_rng`（`MASK_48/MASK_64/MULT/ADD/LegacyRandomSource/_u/mth_get_seed`）；y 采样与 `Utils/Public/structure_map.py` 的 `_jigsaw_variant` 形成跨层协作。

**关键变量/常量**：

| 名称 | 值 | 说明 |
|---|---|---|
| `PROJ_ROOT` / `ASSET_DIR` | 项目根 / `assets/SeedReverser/trial_chambers` | 资产根（45 池 / 170 模板 / 结构定义 JSON）。 |
| `START_POOL_ID` | `"trial_chambers/chamber/end"` | 起点池 id。 |
| `TRIAL_MAX_DEPTH` | `20` | `trial_chambers.json "size": 20`。 |
| `TRIAL_MAX_DIST` | `116` | `max_distance_from_center`。 |
| `TRIAL_START_MIN_Y` / `TRIAL_START_SPAN` | `-40` / `21` | `start_height uniform(-40,-20)` → `nextInt(21)-40`；span 同时用作 `skip_y_bound` 补位次数。 |
| `_STRUCT_DEF_PATH` / `_STRUCT_DEF_CACHE` | 路径 / `Optional[dict]` | 结构定义 JSON 位置与惰性缓存。 |
| `_ALIAS_CACHE` | `Dict[Tuple[int,int,int,int], Dict[str,str]]` | `(seed,x,y,z)` → 别名表缓存。 |
| `_TRIAL_BULB_RULES` | `((0.1, waxed_oxidized…), (0.33333334, waxed_weathered…), (0.5, waxed_exposed…))` | 铜灯降解三规则（按 JSON 序共用流）。 |
| `_INV_2POW24` | `1/(1<<24)` | `nextFloat` 定点判据乘法逆。 |
| `_TEMPLATE_CACHE` / `_POOL_CACHE` | `Dict[str, …]` | 模板/池独立缓存（key 剥 `trial_chambers/` 前缀）。 |

---

## `Utils/StructurePreviewer/ancient_city_assembly.py`

**功能**：远古城市（ancient_city，1.19+）拼装模块，复用 JA 通用引擎。字节码定案依据为 1.21.11 Fabric（`.temp/ancient_city/*.txt + ekv_probe/`）。本模块的引擎外增量是 **start_jigsaw_name 起点重定位**与**三档降解处理器**。

- **结构定义定案**（`ancient_city.json`，1.21.11 jar 提取）：`start_pool=minecraft:ancient_city/city_center`（3 元素等权：`city_center_1/2/3`）、`start_jigsaw_name=minecraft:city_anchor`（起点重定位，新语义）、`size=7`、`max_distance_from_center=116`、`start_height=absolute(-27)`（零消耗）、`terrain_adaptation=beard_box`（仅 Beardifier 地形贴合，不参与布局，预览不实现）、`step=underground_decoration`、`use_expansion_hack=false`、无 `pool_aliases` 字段（`fhc.create` 得空别名、不耗主流）、无 `project_start_to_heightmap`（`Optional.empty` → k = templatePosition.y）。
- **起点重定位**（`fgs.a` L84-247 字节码定案，JA 的 `start_jigsaw_name` 参数）：主流 rotation `nextInt(4)` → start pick `nextInt(3)`（weight 展开）→ `findStartJigsawBlock`：起点模板 `getShuffledJigsawBlocks` 洗牌全部 jigsaw 标记（每个 city_center 模板 5 个标记 → `Util.shuffle` 消耗 4 次主流 nextInt，`probe_anchors_out.txt` 实证）→ 找 `name == minecraft:city_anchor` 的标记 → `templatePosition = pos - (anchorWorld - pos) = pos - R(local)`（anchor 局部 (13,24,20)，两次 `is.b(Vec3i)` 减法定案），使 anchor 标记世界坐标恰落在 pos；`dy = k - (box.minY + groundLevelDelta)`，k = templatePosition.y，`groundLevelDelta` 恒 1（`fgw.h()` 基类 `iconst_1` 实证，四个子类均不覆写）→ `start_y_is_offset=True`（与 bastion 同式）。
- **资产加载流程**：资产根 `assets/SeedReverser/ancient_city/`；与 village/outpost/trial 不同，本模块 key **不剥结构前缀**（资产目录保留 `ancient_city/` 层级，key 剥 `minecraft:` 命名空间后即相对路径）。`load_template` 缺失模板 = 空模板（`fjr.a(amo)=getOrCreate` 字节码实证：缓存 miss 时 new 空模板入缓存不抛异常）——1.21.11 jar 的 `walls/no_corners` 池引用了不存在的 `intact_horizontal_wall_stairs_5`（vanilla 数据缺陷），该候选照常消耗 rotation_shuffled（3 次）但无 jigsaw 标记永远放不下，与游戏行为一致。`load_pool` 对 structures 池的 `list_pool_element`（`ice_box_1` 单子件、processors 为空 dict = 无处理器，冰箱不风化；`camp_1/2/3` 三子件连放）经 `_list_element_hook` 转 `ListPoolElementSpec`（outpost 同范式）；`minecraft:empty` 特判注册空池（终止候选放置，空池 shuffle 零消耗）；sculk 池为 `feature_pool_element`（sculk_patch 地物）+ empty，引擎按 `fgs$b` 语义跳过（trial 先例）。
- **拼装入口与 RNG 消耗**：`assemble_ancient_city(level_seed, chunk_x, chunk_z)` 无需 surface/y 采样，直接委托 `JA.assemble_jigsaw`：`start_pool_id="ancient_city/city_center"`、`max_depth=7`、`start_y=-27`、`start_y_is_offset=True`、`max_dist=116`、`pad_bottom=0/pad_top=0`（dimension_padding：JSON 无该字段）、`load_pool_fn/load_template_fn` 绑定本模块加载器、`start_jigsaw_name="minecraft:city_anchor"`。主流消耗序列：rotation `nextInt(4)` → start pick `nextInt(3)` → 起点标记洗牌 4 次 → anchor 重定位 → `dy = k-(minY+1)`。
- **降解处理器**（`enm` RuleProcessor + `BlockRotProcessor` 字节码语义，两处理器各自独立 `RandomSource.create(Mth.getSeed(pos))` 逐方块流、互不影响）：按池 JSON 的 processors 字段分三档 variant——起点池 `city_center` 三件 = `start`（`ancient_city_start_degradation`，3 规则）；`walls` 与 `walls/no_corners` 池 = `walls`（`ancient_city_walls_degradation`，block_rot 0.95 + 4 规则）；其余（`city_center/walls`、`structures`、`city/entrance`）= `generic`（block_rot 0.95 + 3 规则）。`block_rot` 仅 `#ancient_city_replaceable`（jar 提取 12 个方块）参与判定，`nextFloat(pos流) <= 0.95` 保留 / 超过蚀空（outpost_rot 同式、integrity 0.95 保留方向一致）；rule 链为 `random_block_match` 短路（跨 block 不匹配不消耗，与 bastion `_DEGRADABLE_ITEMS` 同型），规则：`deepslate_bricks 0.3→cracked_deepslate_bricks`、`deepslate_tiles 0.3→cracked_deepslate_tiles`、（walls 加）`deepslate_tile_slab 0.3→air`、`soul_lantern 0.05→air`。处理器数组序 = JSON 序：block_rot（generic/walls 前置）→ rule 链 → protected_blocks（无 RNG，渲染忽略）。返回 `None` = 蚀空不渲染。
- **容器口径**（`probe_containers_out.txt / probe_tables_out.txt`，58 模板实证，LootTableSeed 由 composition 层执行）：15 个 `minecraft:chest`（无 barrel；ice_box 也是 chest）——14 个 NBT 带 LootTable（13 张 `chests/ancient_city` + 1 张 `chests/ancient_city_ice_box`）进预测列表；`city_center_2` 的 1 个无字段（游戏内空箱，`RandomizableContainer` 只认 NBT 字段，不写 LootTableSeed 不消耗流）。LootTableSeed 每区块 population 流 = `get_population_seed + 0 + 10000*7`（salt=(7,0)，`cl_salts_1_21_5.txt L33`），同区块按放置序（piece 序 × 块内 (Y,X,Z)）连抽 `nextLong`。
- **结构集**：`structure_set/ancient_cities.json` salt=20083232、spacing=24、separation=8，与 `structure_params.STRUCT_PARAMS["ancient_city"]` 一致（落点层无需改动，本模块不管落点）。
- **与 composition.py 的协作分工**：`composition.compose_ancient_city`（1887 行）调 `aca.assemble_ancient_city` 得 piece 序列；体素层（2074 行）再次拼装，对每个 piece 的子模板用 `aca.degradation_variant` 定档、逐方块调 `aca.apply_ancient_city_degradation`；composition 另用 `aca.ASSET_DIR` 直读模板 NBT（1965/2020 行）做容器/原始方块收集与 LootTableSeed 预测。

**类与函数**（模块无类）：

| 名称 | 签名 | 说明 |
|---|---|---|
| `_strip_ns` | `(rid: str) -> str` | 剥资源 id 命名空间前缀。 |
| `load_template` | `(key: str) -> JA.TemplateModel` | key 剥命名空间后即相对路径（保留 `ancient_city/` 层）；缺失模板返回零尺寸空模型（getOrCreate 语义），带缓存；解析委托 `JA._parse_template`。 |
| `_list_element_hook` | `(el: dict) -> JA.ListPoolElementSpec` | structures 池 `list_pool_element` → 引擎候选（outpost 同范式）：`location=elements[0]`、`sub_locations` 全子模板、`sub_processors` 各子元素处理器 id（processors 为空 dict 时记 `None` = 无处理器）。 |
| `load_pool` | `(pool_id: str) -> JA.StructureTemplatePool` | `'ancient_city/city_center'` → `template_pool/ancient_city/city_center.json`；`'empty'` 特判空池；带 `list_element_hook`。 |
| `assemble_ancient_city` | `(level_seed: int, chunk_x: int, chunk_z: int) -> JA.AssemblyResult` | 拼装入口（`fhp.a + fgs.a` 1.21 语义）。全参数委托 `JA.assemble_jigsaw`，含 `start_jigsaw_name=minecraft:city_anchor` 起点重定位（详见上）。y 无采样（absolute -27 零消耗，`skip_y_bound=None`）。 |
| `degradation_variant` | `(key: str) -> str` | 模板 key → 处理器档位（start/generic/walls）。按 8 个池 JSON 的 processors 字段定案：key ∈ `_START_TEMPLATES` → start；`ancient_city/walls/` 前缀 → walls；其余 → generic（注意 `city_center/walls` 子目录虽名含 walls 但绑 generic，不能按目录名粗分）。 |
| `_rot_rot` | `(x: int, y: int, z: int) -> bool` | block_rot integrity=0.95 单判定（内联 LCG）：`nextFloat() <= 0.95` → True 保留，超过 → False 蚀空（outpost_rot 同式）。 |
| `_apply_rules` | `(state_name: str, x: int, y: int, z: int, rules) -> str` | rule 链单方块（eni/enm 语义：每方块独立流，random_block_match 短路——不匹配的规则不消耗，首条命中即返回）。先做输入集四方块快速路径（集合外零消耗直接返回）。 |
| `apply_ancient_city_degradation` | `(state_name: str, x: int, y: int, z: int, variant: str = "generic") -> Optional[str]` | 处理器链单方块总入口：variant ≠ start 时先跑 block_rot 前置（仅 `_REPLACEABLE` 参与，蚀空返回 `None`），再跑 `_apply_rules`；两处理器各自独立建流互不影响。 |

**接口**：被 `Utils/StructurePreviewer/composition.py` 以 `import ancient_city_assembly as aca` 延迟导入 6 处（拼装 ×2、`degradation_variant` ×1、`apply_ancient_city_degradation` ×1、`ASSET_DIR` 直读 NBT ×2）。对外提供：`load_template` / `load_pool` / `assemble_ancient_city` / `degradation_variant` / `apply_ancient_city_degradation` / `ASSET_DIR`。依赖 JA 与 `Utils.SeedReverser.mc_rng`（`MASK_48/MASK_64/MULT/ADD/mth_get_seed`）。

**关键变量/常量**：

| 名称 | 值 | 说明 |
|---|---|---|
| `PROJ_ROOT` / `ASSET_DIR` | 项目根 / `assets/SeedReverser/ancient_city` | 资产根（目录保留 `ancient_city/` 前缀层级）。 |
| `START_POOL_ID` | `"ancient_city/city_center"` | 起点池 id。 |
| `ANCIENT_CITY_MAX_DEPTH` | `7` | `ancient_city.json "size": 7`。 |
| `ANCIENT_CITY_MAX_DIST` | `116` | `max_distance_from_center`。 |
| `ANCIENT_CITY_START_Y` | `-27` | `start_height absolute(-27)`（零消耗）。 |
| `ANCIENT_CITY_ANCHOR_NAME` | `"minecraft:city_anchor"` | 起点重定位标记名（新语义）。 |
| `_START_TEMPLATES` | 3 个模板 key 元组 | 起点池三元素（city_center 池 JSON 序，weight 全 1），同时是 `degradation_variant` 的 start 档判据。 |
| `_REPLACEABLE` | 12 方块 `frozenset` | `#minecraft:ancient_city_replaceable`（deepslate 系 11 种 + gray_wool），block_rot 判定集合。 |
| `_RULES_START` | 3 规则元组 | start/generic 档 rule 链（bricks 0.3→cracked、tiles 0.3→cracked、soul_lantern 0.05→air）。 |
| `_RULES_WALLS` | 4 规则元组 | walls 档 rule 链（在 start 基础上增加 `deepslate_tile_slab 0.3→air`，JSON 序）。 |
| `_RULES_BY_VARIANT` | `{"start": …, "generic": …, "walls": …}` | 档位 → rule 链映射（start 与 generic 同链）。 |
| `_INV_2POW24` | `1/(1<<24)` | `nextFloat` 定点判据乘法逆。 |
| `_TEMPLATE_CACHE` / `_POOL_CACHE` | `Dict[str, …]` | 模板/池独立缓存。 |

---

## `Utils/StructurePreviewer/locator.py`

**功能**：StructurePreviewer 的**结构定位层**。职责是把「落点枚举」与「构造组合/3D 模型」两段既有能力粘合成 UI 可直接消费的一条流水线：基于 `Utils.Public.structure_map.enumerate_structures` 复用既有锚点枚举与群系校验（与 MapPreviewer 的 GUI 验收口径一致），限定 `igloo / shipwreck` 两个结构键，并对每个锚点求完整构造组合。UI 主流程（btnPreview）：① `locator.locate()` 得到视野内锚点列表（含 biome id）→ ② `composition.compose()` 填充变种/部件/箱子/LootTableSeed → ③ `composition.compose_display_model()` 出 3D 视口模型。注意：本模块是四个 `*_assembly` 之外的定位门面，服务于 igloo/shipwreck 这类非 jigsaw 结构的既有 composition 路径；village/outpost/trial/ancient_city 的 jigsaw 拼装不经过本模块。

**类与函数**（模块无类）：

| 名称 | 签名 | 说明 |
|---|---|---|
| `locate` | `(seed: int, version_key: str, viewport: tuple[int, int, int, int], struct_keys=SUPPORTED) -> list[dict]` | 视野内结构实例列表（结构粒度，不含构造细节），直接转发 `structure_map.enumerate_structures`（`struct_keys` 转元组防可变默认参）；返回项 `{struct, name, x, z, cx, cz, biome}`。 |
| `detail` | `(seed: int, version_key: str, struct_key: str, anchor: tuple[int, int], biome_id: int) -> composition.Composition` | 单锚点 → 完整构造组合（变种/部件/箱子/LootTableSeed）；种子先 `& ((1<<64)-1)` 归一到无符号域再交给 `composition.compose`。 |
| `locate_with_details` | `(seed: int, version_key: str, viewport: tuple[int, int, int, int], struct_keys=SUPPORTED) -> list[dict]` | `locate` + 对每项追加 `comp`（`detail` 结果）与 `model`（`composition.compose_display_model(comp)`，含 voxels/chests/anchor/anchor_off），供 UI 直接消费；原命中字段浅拷贝保留。 |
| `format_seed_signed` | `(seed: int) -> int` | 无符号 → Java 有符号显示（纯转发 `loot_rng.signed_seed`）。 |

**接口**：当前源码树内无其他模块 import locator（仅自身与 `__pycache__` 编译产物命中），是按 docstring 定义的 UI 门面层（btnPreview 流程入口）。对外提供：`SUPPORTED`、`locate`、`detail`、`locate_with_details`、`format_seed_signed`。依赖 `Utils.Public.structure_map`（枚举/群系校验）、同包 `composition`（`compose` / `compose_display_model` / `Composition`）、同包 `loot_rng`（`signed_seed`）。

**关键变量/常量**：

| 名称 | 值 | 说明 |
|---|---|---|
| `SUPPORTED` | `("igloo", "shipwreck")` | 本定位层支持的结构键，也是 `locate*` 的默认 `struct_keys`。 |

---

## `Utils/StructurePreviewer/__init__.py`

**功能**：包标识文件，内容为空（0 行、无任何语句与导出）。作用仅为把 `Utils/StructurePreviewer` 标记为 Python 包，使 `from Utils.StructurePreviewer import composition, loot_engine, loot_rng`（`Tools/tool_StructurePreviewer.py`）及包内相对导入（如 `locator.py` 的 `from . import composition, loot_rng`）成立；不聚合子模块命名空间、不定义 `__all__`、无副作用代码，导入成本为零。

**类与函数**：

| 名称 | 签名 | 说明 |
|---|---|---|
| （无） | — | 文件为空，无类、函数或常量定义。 |

**接口**：无对外符号；仅作为包边界存在。包内实际对外入口由各子模块自持：拼装层（`village_assembly` / `outpost_assembly` / `trial_assembly` / `ancient_city_assembly`）、组合层（`composition`）、定位层（`locator`）、战利品层（`loot_rng` / `loot_engine`）等。

**关键变量/常量**：

| 名称 | 值 | 说明 |
|---|---|---|
| （无） | — | 空文件，无任何变量或常量。 |

# 10. 界面骨架层（CodesUI）

# CodesUI 模块文档

`CodesUI/` 是 Qt Designer 的 `.ui` 文件经 PySide6 uic（Qt User Interface Compiler 6.11.1）编译生成的界面代码目录。每个文件提供一个 `Ui_xxx` 类，包含 `setupUi`（构建控件树与布局）与 `retranslateUi`（设置文本）两个方法。业务层不采用组合模式（`self.ui.xxx`），而是多继承 mixin 模式：`class XxxWidget(BaseToolWidget, Ui_xxx)` 后调用 `self.setupUi(self)`，所有控件对象名直接成为业务类的属性（如 `self.comboVersion`）。本目录所有文件均为生成产物，头部注释声明"重新编译 UI 文件后改动将丢失"。

---

## `CodesUI/__init__.py`

**功能**：空文件，仅将 `CodesUI` 标记为 Python 包，使 `from CodesUI.xxx import Ui_xxx` 形式的导入生效。

**类与函数**：无。

**关键控件**：无。

---

## `CodesUI/AutoBackUp.py`

**功能**：自动备份工具（`Tools/tool_AutoBackUp.py` 的 `AutoBackUpWidget`）的界面骨架。顶层 `QWidget`（628×475），内部一个 `layoutWidget` 承载 `gridLayout`（列拉伸 1:4:1），自上而下分为四区：

- 存档目录区：`label`（"存档目录"）+ 路径输入框 + "浏览文件夹"按钮；
- 中部多选区：`targetDirList`（多选列表）与左右两个垂直弹簧；
- 备份目录区：`label_2`（"备份目录"）+ 路径输入框 + "浏览文件夹"按钮；
- 监测/执行区：`label_3`（"监测进程名"）+ 进程名输入框 + 监测开关按钮 + "自动备份"复选框；
- 底部执行区："开始备份"按钮 + 进度条 + 信息输出框（跨 4 列）。

**类与函数**：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `Ui_AutoBackUp` | `class Ui_AutoBackUp(object)` | 自动备份窗口的 UI 描述类 |
| `setupUi` | `setupUi(self, AutoBackUp)` | 创建控件与 `gridLayout`，设置列拉伸后调用 `retranslateUi` |
| `retranslateUi` | `retranslateUi(self, AutoBackUp)` | 设置窗口与各控件中文文本 |

**关键控件**（均被 `tool_AutoBackUp.py` 引用）：

| 对象名 | 控件类型 | 用途 |
| --- | --- | --- |
| `targetDirPath` | `QLineEdit` | 输入要备份的存档目录路径（带清除按钮） |
| `chooseTargetDir` | `QPushButton` | "浏览文件夹"：选择存档目录 |
| `targetDirList` | `QListWidget` | 存档目录下的存档/世界列表，多选模式、不可编辑 |
| `targetDesPath` | `QLineEdit` | 输入备份目标目录路径（带清除按钮） |
| `chooseDesDir` | `QPushButton` | "浏览文件夹"：选择备份目标目录 |
| `processName` | `QLineEdit` | 监测的进程名输入框，占位文本 `java.exe` |
| `monitorController` | `QPushButton` | 启动/停止监测进程的开关按钮 |
| `isAutoBackUp` | `QCheckBox` | "自动备份"开关 |
| `startBackUp` | `QPushButton` | "开始备份"按钮 |
| `backUpProgress` | `QProgressBar` | 备份进度条 |
| `informationBrowser` | `QTextBrowser` | 备份/监测日志输出区 |

未列出的 `label`/`label_2`/`label_3`/`verticalSpacer*` 为纯标签与弹簧，业务代码未引用。

---

## `CodesUI/ChooseEnchantedItems.py`

**功能**：附魔计算器的"选择物品与附魔"对话框（由 `Utils/EnchantCaculator/choose_items.py` 的 `ChooseItemsWindow` 驱动）。顶层 `QWidget`（585×417），`layoutWidget` + `gridLayout` 三段式：左上为物品类型下拉框、右上为已选附魔列表（支持拖放）、下部为按分类分页的附魔候选 `QTabWidget`，最底行为"确认/清空"按钮。

特殊点：本文件是 CodesUI 中唯一引入项目自定义控件的生成文件——`chosenEnchantmentList` 用 `Utils.EnchantCaculator.drop_list_widget.DropListWidget`（接受拖放），7 个分类页各放一个 `Utils.EnchantCaculator.enchant_list_widget.EnchantListWidget`。`choose_items.py` 运行时会 `allEnchantmentTab.clear()` 后按当前物品类型动态重建分类页，.ui 中预置的 7 页仅为设计时占位。

**类与函数**：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `Ui_enchantedItems` | `class Ui_enchantedItems(object)` | 选择附魔物品对话框的 UI 描述类 |
| `setupUi` | `setupUi(self, enchantedItems)` | 创建物品下拉框（16 个预置项）、拖放列表、7 页附魔 `QTabWidget` 与按钮，默认显示第 0 页 |
| `retranslateUi` | `retranslateUi(self, enchantedItems)` | 设置物品项（附魔书/剑/斧/矛/镐/铲/锄/弓/弩/三叉戟/重锤/头盔/胸甲/护腿/靴子/钓鱼竿）、7 个页签文本（近战武器/工具/远程武器/防具/三叉戟/通用附魔/诅咒）及按钮文本 |

**关键控件**（均被 `Utils/EnchantCaculator/choose_items.py` 引用）：

| 对象名 | 控件类型 | 用途 |
| --- | --- | --- |
| `itemsList` | `QComboBox` | 选择物品类型（附魔书、剑、斧、矛、镐、铲、锄、弓、弩、三叉戟、重锤、头盔、胸甲、护腿、靴子、钓鱼竿，共 16 项） |
| `chosenEnchantmentList` | `DropListWidget`（自定义） | 已选附魔列表，接受从分类页拖入附魔 |
| `allEnchantmentTab` | `QTabWidget` | 附魔候选分类页容器（运行时动态重建） |
| `confirmItem` | `QPushButton` | "确认"按钮，打包所选数据并关闭 |
| `clearEnchantList` | `QPushButton` | "清空"按钮，清空已选附魔 |

`meleeEnchantmentList`/`toolEnchantmentList`/`rangedEnchantmentList`/`armorEnchantmentList`/`tridentEnchantmentList`/`commonEnchantmentList`/`curseEnchantmentList` 及对应 tab 对象在运行时被 `clear()` 重建，业务代码不直接引用这些对象名。

---

## `CodesUI/ChooseStructureWin.py`

**功能**：地图预览器的"选择显示的结构"对话框（由 `Utils/MapPreviewer/choose_structure.py` 驱动）。顶层 `QWidget`（690×568），全窗口绝对定位（无布局管理器）：一个几乎铺满窗口的结构列表 + 底部居中的确认按钮。

**类与函数**：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `Ui_chooseStructureWin` | `class Ui_chooseStructureWin(object)` | 结构选择窗口的 UI 描述类 |
| `setupUi` | `setupUi(self, chooseStructureWin)` | `setGeometry` 摆放列表（0,0,691,531）与确认按钮（300,540,83,26） |
| `retranslateUi` | `retranslateUi(self, chooseStructureWin)` | 设置确认按钮文本"确认" |

**关键控件**（均被 `Utils/MapPreviewer/choose_structure.py` 引用）：

| 对象名 | 控件类型 | 用途 |
| --- | --- | --- |
| `structureList` | `QListWidget` | 可渲染的结构类型列表，供用户勾选显示哪些结构 |
| `confirmBtn` | `QPushButton` | "确认"按钮，保存选择并关闭窗口 |

---

## `CodesUI/EnchantCaculator.py`

**功能**：附魔计算器主界面（`Tools/tool_EnchantCaculator.py` 的 `EnchantCalculatorWidget`）。顶层 `QWidget`（634×518），`layoutWidget` + `gridLayout` 三段式：上部为已选物品列表（跨 4 列），中部为操作行（添加物品/清空物品/开始计算/展示模式下拉框），下部为计算结果区（跨 4 列）。

特殊点：`chosenItemList` 与 `realSteps` 在 .ui 中是原生 `QListWidget` 占位；`tool_EnchantCaculator.py` 运行时通过 `self.gridLayout.replaceWidget(...)` 将二者原位替换为 `CardListWidget`（卡片列表，支持拖动交换、Del 删除）与 `AnvilStepsTree`（铁砧合成步骤树），布局位置不变。

**类与函数**：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `Ui_EnchantCaculator` | `class Ui_EnchantCaculator(object)` | 附魔计算器主界面的 UI 描述类 |
| `setupUi` | `setupUi(self, EnchantCaculator)` | 创建两个列表占位、四个操作控件并装入 `gridLayout` |
| `retranslateUi` | `retranslateUi(self, EnchantCaculator)` | 设置按钮文本（添加物品/清空物品/开始计算）与展示模式项（树状图/步骤图） |

**关键控件**（`gridLayout`、`chosenItemList`、`realSteps`、`addItems`、`clearItems`、`startCaculate`、`displayMode` 均被 `tool_EnchantCaculator.py` 引用）：

| 对象名 | 控件类型 | 用途 |
| --- | --- | --- |
| `chosenItemList` | `QListWidget`（运行时替换为 `CardListWidget`） | 已选物品卡片列表，每张卡片是一次物品+附魔选择；双击卡片可重新编辑 |
| `realSteps` | `QListWidget`（运行时替换为 `AnvilStepsTree`） | 铁砧合成最优方案展示区（树状图/步骤图两种模式） |
| `addItems` | `QPushButton` | "添加物品"：打开选择物品对话框 |
| `clearItems` | `QPushButton` | "清空物品"：清空全部卡片并复位结果区 |
| `startCaculate` | `QPushButton` | "开始计算"：冲突决策后调用铁砧优化器求解最少经验方案 |
| `displayMode` | `QComboBox` | 结果展示模式切换（0=树状图，1=步骤图） |
| `gridLayout` | `QGridLayout` | 主布局；业务代码用 `replaceWidget` 原位替换两个列表控件 |

---

## `CodesUI/MapPreviewer.py`

**功能**：地图预览器主界面（`Tools/tool_MapPreviewer.py` 的 `MapPreviewerWidget`）。顶层 `QWidget`（1081×801），`layoutWidget` + `gridLayout`（9 列）四段式：顶部参数区（版本/种子/视野半径/两个动作按钮）、定位区（X/Z 坐标 + 结构定位 + 群系定位 + 维度下拉框）、主体地图画布 `viewMap`（`QGraphicsView`，跨 9 列）、底部状态区（进度条 + 悬停提示 + 状态文本）。

注意：`comboVersion` 的 4 个预置项（1.21/1.20/1.19/1.18）为设计时占位，`tool_MapPreviewer.py` 运行时清空后重建为实际支持的版本档位（26.2/1.21.11/1.21）。

**类与函数**：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `Ui_mapPreviewer` | `class Ui_mapPreviewer(object)` | 地图预览器主界面的 UI 描述类 |
| `setupUi` | `setupUi(self, mapPreviewer)` | 创建参数区、定位区、`QGraphicsView` 画布与状态区控件 |
| `retranslateUi` | `retranslateUi(self, mapPreviewer)` | 设置版本项（1.21/1.20/1.19/1.18）、半径项（2048/4096）、维度项（主世界/下界/末地）及各标签按钮文本 |

**关键控件**（均被 `tool_MapPreviewer.py` 引用）：

| 对象名 | 控件类型 | 用途 |
| --- | --- | --- |
| `comboVersion` | `QComboBox` | 游戏版本选择（预置项运行时被清空重建） |
| `editSeed` | `QLineEdit` | 输入世界种子 |
| `comboRadius` | `QComboBox` | 视野半径选择（2048/4096） |
| `btnStructures` | `QPushButton` | "选择显示的结构"：弹出 `chooseStructureWin` 对话框 |
| `btnRender` | `QPushButton` | "生成地图"：按当前参数渲染地图画布 |
| `xEdit` | `QLineEdit` | 定位中心 X 坐标 |
| `zEdit` | `QLineEdit` | 定位中心 Z 坐标 |
| `worldCombo` | `QComboBox` | 维度选择（主世界/下界/末地） |
| `structureLocateList` | `QComboBox` | 结构定位：选择要定位的结构类型 |
| `biomeLocateList` | `QComboBox` | 群系定位：选择要定位的群系 |
| `viewMap` | `QGraphicsView` | 地图画布，渲染结果与悬停交互的主体 |
| `progressRender` | `QProgressBar` | 地图渲染进度条 |
| `labelHover` | `QLabel` | 底部悬停信息栏（"悬停地图查看坐标与群系"） |
| `labelInfo` | `QLabel` | 底部状态栏（初始"就绪"） |

`labelVersion`/`labelSeed`/`labelRadius`/`locateLabel`/`structureLocateLabel`/`biomeLocateLabel` 为纯标签，业务代码未引用。

---

## `CodesUI/MCHelperMainWindow.py`

**功能**：MCHelper 主窗口骨架（`main_window.py` 的 `QMainWindow` 子类 `Ui_MCHelper`，800×600）。结构为标准 QMainWindow 三件套：中央区 `centralwidget`（内含 `horizontalLayout` + 一个圆角页签 `QTabWidget`）、菜单栏 `menubar`（含一个无标题 `QMenu` 和一个"设置" `QAction`）、状态栏 `statusbar`。`tabWidget` 初始 `currentIndex(-1)`，启动时无页签。

业务使用方式：`main_window.py` 仅实际使用 `tabWidget`——动态 `addTab` 各工具 widget、把 `currentChanged` 连到 `adapt_window_to_tool` 做窗口尺寸自适应、并用自定义 `DraggableTabBar` 替换页签栏实现拖拽排序。.ui 中的 `menu`/`action` 未被使用，菜单栏由 `create_menu()` 自建 `QMenu("菜单")`（设置/关于两项）经 `self.menuBar()` 挂载。

**类与函数**：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `Ui_MCHelper` | `class Ui_MCHelper(object)` | 主窗口的 UI 描述类 |
| `setupUi` | `setupUi(self, MCHelper)` | 创建中央 widget + `tabWidget`、菜单栏（menu/action）与状态栏 |
| `retranslateUi` | `retranslateUi(self, MCHelper)` | 设置窗口标题 `MainWindow` 与 `action` 文本"设置"（menu 标题为空） |

**关键控件**：

| 对象名 | 控件类型 | 用途 |
| --- | --- | --- |
| `tabWidget` | `QTabWidget` | 工具页签容器，Rounded 圆角页签；`main_window.py` 动态填充各工具页并接管其页签栏（拖拽排序、窗口自适应） |

`action`/`centralwidget`/`horizontalLayout`/`menubar`/`menu`/`statusbar` 仅由 `setupUi` 创建，业务代码未直接引用（菜单栏经 `QMainWindow.menuBar()` 方法自建菜单）。

---

## `CodesUI/SeedReverser.py`

**功能**：种子逆推器主界面（`Tools/tool_SeedReverser.py` 的 `SeedReverserWidget`）。顶层 `QWidget`（1170×826），`layoutWidget` 承载 10 列 `gridLayout`，分上下两大区块：

- **上半部（结构观测与种子计算）**：顶部参数行（目标版本 `versionCombo`、群系模式复选框）；结构类型行（`structTypeLabel` + `structTypeCombo` + X/Z 坐标输入框）；主体 `structList`（结构观测记录树，跨 3 行 9 列）；右侧竖排操作列（添加 / 粘贴F3+C / 清除）；进度信息行（"信息量" + `infoProgressBar` + `infoHintLabel`）；动作行（计算 / 验证候选种子 / 清空全部 + `anchorPreviewLabel` 锚点预览）；`informationBrowser` 结果输出。
- **下半部 `refineGroupBox`（"世界种子精化（群系验证）"）**：候选种子行（`candidateSeedEdit` + "从计算结果导入" + X/Y/Z 坐标 + 可编辑群系名下拉框 + 添加 + 粘贴F3+C）；`biomeObsList`（群系观测记录树）；精化控制行（开始精化 / 清除精化 / 进度条 / 提示标签 / 清空列表）；`worldSeedDetailBrowser`（世界种子详情输出）。

**类与函数**：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `Ui_seedReverser` | `class Ui_seedReverser(object)` | 种子逆推器主界面的 UI 描述类 |
| `setupUi` | `setupUi(self, seedReverser)` | 创建上半部观测/计算控件与下半部 `refineGroupBox` 精化控件并装入两级 `QGridLayout` |
| `retranslateUi` | `retranslateUi(self, seedReverser)` | 设置各标签、按钮、占位文本（X/Y/Z、群系名、结构种候选等）与 GroupBox 标题 |

**关键控件**（除注明外均被 `tool_SeedReverser.py` 引用）：

| 对象名 | 控件类型 | 用途 |
| --- | --- | --- |
| `versionCombo` | `QComboBox` | 选择目标游戏版本 |
| `biomeModeCheckBox` | `QCheckBox` | "群系模式"开关：切换观测类型（结构坐标 ↔ 群系） |
| `structTypeCombo` | `QComboBox` | 选择要逆推的结构类型 |
| `coordXEdit` / `coordZEdit` | `QLineEdit` | 输入结构观测点 X/Z 坐标 |
| `structList` | `QTreeWidget` | 结构观测记录列表（核心数据源） |
| `addButton` | `QPushButton` | "添加"：把当前输入的观测点加入 `structList` |
| `pasteF3CButton` | `QPushButton` | "粘贴F3+C"：解析剪贴板中的 F3+C 调试坐标 |
| `clearInputButton` | `QPushButton` | "清除"：移除选中的观测记录 |
| `clearAllButton` | `QPushButton` | "清空全部"：清空全部观测记录 |
| `calcButton` | `QPushButton` | "计算"：由观测记录逆推候选结构种子 |
| `verifyButton` | `QPushButton` | "验证候选种子"：校验候选种子的正确性 |
| `infoProgressBar` | `QProgressBar` | 信息量/计算进度指示 |
| `infoHintLabel` | `QLabel` | 信息量提示文本 |
| `anchorPreviewLabel` | `QLabel` | 锚点预览标签 |
| `informationBrowser` | `QTextBrowser` | 计算结果与日志输出区 |
| `refineGroupBox` | `QGroupBox` | "世界种子精化（群系验证）"容器 |
| `candidateSeedEdit` | `QLineEdit` | 待精化的结构种候选值 |
| `candidateFromCalcBtn` | `QPushButton` | "从计算结果导入"：把计算阶段的候选填入精化区 |
| `biomeXEdit` / `biomeYEdit` / `biomeZEdit` | `QLineEdit` | 群系观测点 X/Y/Z 坐标 |
| `biomeNameCombo` | `QComboBox`（可编辑） | 输入/选择观测到的群系名 |
| `addBiomeObsBtn` | `QPushButton` | "添加"：把群系观测加入 `biomeObsList` |
| `pushButton` | `QPushButton` | 精化区内的"粘贴F3+C"按钮（对象名为生成器默认名） |
| `biomeObsList` | `QTreeWidget` | 群系观测记录列表 |
| `refineButton` | `QPushButton` | "开始精化"：用群系观测从结构种推出世界种子 |
| `refineClearBtn` | `QPushButton` | "清除精化"：复位精化流程 |
| `clearBiomeBtn` | `QPushButton` | "清空列表"：清空群系观测记录 |
| `refineProgressBar` | `QProgressBar` | 精化进度条 |
| `refineInfoLabel` | `QLabel` | 精化状态/提示文本 |
| `worldSeedDetailBrowser` | `QTextBrowser` | 世界种子详情输出区 |

`structTypeLabel`/`versionLabel`/`infoLabel` 为纯标签，业务代码未引用。

---

## `CodesUI/Settings.py`

**功能**：设置对话框（`Tools/tool_Settings.py` 的 `SettingsWindow`，继承 `QDialog`）。顶层 `QWidget`（229×120），`layoutWidget` + `gridLayout`，仅两个纵向排列的复选框，分别对应"开机自启动"与"关闭时最小化到托盘"两项应用设置。

**类与函数**：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `Ui_Settings` | `class Ui_Settings(object)` | 设置对话框的 UI 描述类 |
| `setupUi` | `setupUi(self, Settings)` | 在 `gridLayout` 中创建两个复选框 |
| `retranslateUi` | `retranslateUi(self, Settings)` | 设置两个复选框文本（"开机自启动"/"关闭时最小化到托盘"） |

**关键控件**（均被 `tool_Settings.py` 引用）：

| 对象名 | 控件类型 | 用途 |
| --- | --- | --- |
| `isStartOnRoot` | `QCheckBox` | "开机自启动"选项开关 |
| `isSystemTray` | `QCheckBox` | "关闭时最小化到托盘"选项开关（状态经 `settings_bus` 广播到主窗口） |

---

## `CodesUI/StrongHoldFinder.py`

**功能**：要塞定位器界面（`Tools/tool_StrongHoldFinder.py` 的 `StrongHoldFinderWidget`）。顶层 `QWidget`（663×373），`layoutWidget` + `gridLayout`（2 列）：两行坐标输入（标签 + 输入框）、一行动作按钮（计算 / 清除）、底部 `informationBrowser` 结果输出（跨 2 列）。

注意一个命名细节：`retranslateUi` 中对象名与显示文本交叉——`coordinate2` 标签显示"坐标一"（位于第 0 行，与 `coordinate1Edit` 配对），`coordinate1` 标签显示"坐标二"（位于第 1 行，与 `coordinate2Edit` 配对）。视觉配对正确，仅对象名与行序号不对应。

**类与函数**：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `Ui_strongHoldFinder` | `class Ui_strongHoldFinder(object)` | 要塞定位器的 UI 描述类 |
| `setupUi` | `setupUi(self, strongHoldFinder)` | 创建两行坐标输入、动作按钮与结果输出区 |
| `retranslateUi` | `retranslateUi(self, strongHoldFinder)` | 设置标签文本（"坐标一"/"坐标二"）与按钮文本（"计算"/"清除"） |

**关键控件**（均被 `tool_StrongHoldFinder.py` 引用）：

| 对象名 | 控件类型 | 用途 |
| --- | --- | --- |
| `coordinate1Edit` | `QLineEdit` | 第一组投掷点坐标输入（"坐标一"行） |
| `coordinate2Edit` | `QLineEdit` | 第二组投掷点坐标输入（"坐标二"行） |
| `doCaculate` | `QPushButton` | "计算"：由两组末影之眼坐标三角定位要塞 |
| `clearCoordinates` | `QPushButton` | "清除"：清空输入与结果 |
| `informationBrowser` | `QTextBrowser` | 计算结果输出区 |

`coordinate1`/`coordinate2` 为纯标签，业务代码未引用。

---

## `CodesUI/StructurePreviewer.py`

**功能**：结构预览器界面（`Tools/tool_StructurePreviewer.py` 的 `StructurePreviewerWidget`）。顶层 `QWidget`（1170×826），`layoutWidget` 承载 10 列 `gridLayout`（第 4 行拉伸系数 2，第 8、9 列拉伸 7、8，右侧信息栏更宽）。分区：

- 顶部参数区：版本（`visionLabel` + `versionCombo`）、结构（`structureLabel` + `structCombo`）、种子（`label_3` + `seedEdit`）；
- 第二行：X/Z 坐标输入、"粘贴F3+C"、"预览"按钮、镜头灵敏度标签 + 水平滑块；
- 右侧信息栏（第 9 列，自上而下）：`infoGroupBox`"结构信息"（内含 `infoLabel`）、`locateGroupBox`"附近的实例"（内含 `treeWidget`）、`chestsGroupBox`"箱子与战利品"（内含 `chestList`）、`snapshotLabel`；
- 主体：`viewportPlaceholder`（跨 3 行 9 列的 3D 视口占位 `QLabel`）；
- 底部状态区：`hintLabel` 提示 + `progressBar` 进度条。

特殊点：.ui 中 `infoLabel`/`treeWidget`/`chestList` 用 `setGeometry` 绝对定位（GroupBox 缩放时不跟随），`tool_StructurePreviewer.py` 的 `_fit_groupbox_layouts()` 运行时为三个 GroupBox 装上 `QVBoxLayout` 让内容自动填满，并对两个树控件做防溢出设置。

**类与函数**：

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `Ui_structurePreviewer` | `class Ui_structurePreviewer(object)` | 结构预览器主界面的 UI 描述类 |
| `setupUi` | `setupUi(self, structurePreviewer)` | 创建参数区、右侧三个 GroupBox、视口占位与底部状态区，并设置行列拉伸 |
| `retranslateUi` | `retranslateUi(self, structurePreviewer)` | 设置各标签、GroupBox 标题（结构信息/附近的实例/箱子与战利品）、按钮文本（预览/粘贴F3+C）与占位文本（X/Z） |

**关键控件**（除注明外均被 `tool_StructurePreviewer.py` 引用）：

| 对象名 | 控件类型 | 用途 |
| --- | --- | --- |
| `versionCombo` | `QComboBox` | 选择游戏版本（决定结构拼装规则） |
| `structCombo` | `QComboBox` | 选择要预览的结构类型 |
| `seedEdit` | `QLineEdit` | 输入世界种子（支持十进制与 0x 十六进制） |
| `coordXEdit` / `coordZEdit` | `QLineEdit` | 预览锚点 X/Z 坐标 |
| `pasteBtn` | `QPushButton` | "粘贴F3+C"：解析剪贴板调试坐标填入种子与坐标 |
| `btnPreview` | `QPushButton` | "预览"：触发逐种子精确复现游戏结构拼装 |
| `lensSensitivitySlider` | `QSlider`（水平） | 3D 视口镜头灵敏度调节 |
| `lensSensitivityLabel` | `QLabel` | "镜头灵敏度"标签 |
| `viewportPlaceholder` | `QLabel` | 3D 视口占位区（业务代码在此挂载自绘渲染视图） |
| `infoGroupBox` | `QGroupBox` | "结构信息"容器 |
| `infoLabel` | `QLabel` | 结构信息文本（运行时改挂布局、开自动换行与文本交互） |
| `locateGroupBox` | `QGroupBox` | "附近的实例"容器 |
| `treeWidget` | `QTreeWidget` | 该种子附近的结构实例列表 |
| `chestsGroupBox` | `QGroupBox` | "箱子与战利品"容器 |
| `chestList` | `QTreeWidget` | 结构内箱子位置与战利品预测列表 |
| `hintLabel` | `QLabel` | 底部操作提示 |
| `progressBar` | `QProgressBar` | 预览生成进度条 |

`visionLabel`/`structureLabel`/`label_3`/`snapshotLabel` 为纯标签，业务代码未引用。

# 11. 资源与数据

> 所有路径相对项目根。标注"零引用"的资源已在 2026-09-23 整理中清理。

## 10.1 公共资源 `assets/Public/`（多工具共用）

| 内容 | 数量 | 加载方 |
|---|---|---|
| 群系图标 `<biome_key>.png`（16x16，中文 Wiki BiomeSprite 转存） | 54 | `Utils/Public/biome_names.py` 的 `icon_path()`（SeedReverser 群系下拉、MapPreviewer 群系锚点图标） |
| 结构图标 `EnvSprite_<name>.png`（16x16，英文 Wiki EnvSprite 转存） | 26 | `Utils/Public/structure_icons.py` 的 `icon_path()`（MapPreviewer 结构标记、SeedReverser/StructurePreviewer 结构下拉） |
| `enchanted_glint.png`（128x128 附魔流光纹理，游戏原版） | 1 | EnchantCaculator（enchanted_item_card / anvil_steps_tree）、StructurePreviewer（tool_StructurePreviewer._GLINT_PATH） |

## 10.2 私有资源（各工具自用）

### `assets/SeedReverser/`（种子逆推 + 结构渲染）
| 子目录 | 数量 | 用途 | 加载方 |
|---|---|---|---|
| `templates/` | 111 个 .nbt | 结构模板（igloo/endcity/shipwreck/underwater_ruin/trail_ruins/woodland_mansion 等） | structure_models.TEMPLATE_FILES |
| `schematics/` | 3 个 .schem | village/monument/trial_chambers 快照 | structure_models.SCHEM_FILES |
| `textures/block/` | 400 个 .png | 方块纹理（2D 预览与 3D 图集） | structure_models/structure_preview/structure_3dview.TEX_DIR |
| `previews/` | 13 个 .png | 2D 结构预览缓存图 | structure_preview.PREVIEW_DIR |
| `bastion/` | 229 文件 | 堡垒遗迹模板+template_pool+降解处理器 | jigsaw_assembly（ASSET_DIR） |
| `village/` | 561 文件 | 村庄六群系变体模板/池/处理器 | village_assembly |
| `trial_chambers/` | 217 文件 | 试炼密室模板/池/战利品定义 | trial_assembly |
| `woodland_mansion/` | 73 文件 | 林地府邸墙件模板 | mansion_pieces |
| `ancient_city/` | 72 文件 | 远古城市模板/池/降解 | ancient_city_assembly |
| `pillager_outpost/` | 15 文件 | 前哨站塔楼/配件模板/池 | outpost_assembly |

### `assets/StructurePreviewer/`
| 子目录 | 数量 | 用途 | 加载方 |
|---|---|---|---|
| `gui/` | 3（slot.png、generic_54.png、font_ascii.json） | 容器槽位/面板纹理与 ASCII 像素字体 | tool_StructurePreviewer._GUI_DIR |
| `items/` | 253 个 .png | 物品图标（战利品列表渲染） | tool_StructurePreviewer._ICON_DIR |

### `assets/EnchantCaculator/`
18 个物品图标 PNG（diamond_sword、enchanted_book、turtle_helmet 等），由 `enchanted_item_card.get_item_icon_path()` 按中文物品名映射加载。

## 10.3 数据文件

| 路径 | 用途 | 读写方 |
|---|---|---|
| `data/enchants.json` | 附魔定义（32KB，八字段结构） | enchant_data_manager（DataManager 单例） |
| `Utils/SeedReverser/btree_tables.npz` | 群系噪声 B 树查找表（按版本键 btree21wd/btree262） | biome_noise |
| `Utils/StructurePreviewer/data/loot/` | 65 个战利品表快照 JSON，命名 `<表>.<档>.json`（档：1_20/1_21/1_21_11，不分档无后缀） | loot_engine（快照加载）+ tool_StructurePreviewer._LOOT_DIR |
| `Utils/SeedReverser/_native/`、`Utils/MapPreviewer/_native/` | pybind11 原生扩展源码与构建脚本（build_*.py 调 MSVC cl.exe） | map_sampler / biome_noise / world_seed_refine 优先加载编译产物，失败回退纯 Python |

## 10.4 用户配置（不随项目走）

运行时配置写入 `QStandardPaths.AppConfigLocation`（失败回退模块所在目录）：`tab_order.json`（Tab 顺序）、`settings_config.json`（设置页）、`backup_config.json`（备份页）、`enchant_session.json`、`seed_reverser_session.json`、`structure_previewer_session.json` 等（会话持久化）。Windows 开机自启写注册表 Run 键。

