# -*- coding: utf-8 -*-
"""SeedReverser 结构 3D 视口（QOpenGLWidget + 原生 OpenGL，GLSL 120）。

替换 SeedReverser 原平面示意图 label 的 3D 交互视口：
- 右键拖拽 = 环绕旋转（俯仰 5°~85° 限位）
- 滚轮     = 缩放；左键拖拽 = 平移；双击 = 复位视角
- 旁观者模式（StructurePreviewer 用，与环绕模式并存）：WASD/
  方向键沿视线水平移动、Space/Shift 世界升降、鼠标隐藏锁定
  视口中心自由转视角（按 ` 或 Esc 呼出鼠标）、滚轮调速；
  进入方式由工具层调 set_spectator_mode(True)（进入后默认
  锁定鼠标；切模型/退出模式时复位回环绕相机）；
- 模型：structure_models.build_model 的共享顶点网格；变种结构
  （海底废墟/废弃传送门）由 QTimer 轮播官方模板（2.5s/个；
  拖动/缩放期间暂停，停手 4s 后恢复）；
- 纹理：方块纹理拼 16x16 图集（槽 0 = 未知材质灰），
  世界坐标 UV fract 到槽内采样（槽原点烘焙进顶点属性 aTile，
  半像素防渗色），主体单次 draw call；
- 水：半透明第二遍绘制（深度只读，水体后景透出）；
- 光照：法线固定方向光 + 环境项；
- 锚点：红色无限延伸竖直线（monument 画在结构中心；village/
  trial_chambers 按 ANCHOR_OFFSETS 实测偏移画在水井/入口两水池
  处；其余画在西北角 (0,0)），地面十字标出精确点；区块网格
  同步对齐（锚点≡区块西北角）；2D overlay 图例文字；
- 方位：无地面罗盘层（早期地面白箭头+W/N 字母与右键旋转
  光标功能重复，已删）；方位提示由旋转光标承担（N/W 字母
  随视角同步旋转，见 _orbit_cursor）。

坐标约定：体素 (x,y,z) 直接作世界坐标，x 西→东、z 北→南、y 向上，
(0,0,0) = 包围盒西北角底部 = cubiomes 生成锚点（monument 特例：
锚点 = 结构中心，wiki：1.13+ 神殿生成于区块角上）。相机初始位于
西北上空看向结构中心（y-up 右手系，QMatrix4x4.perspective）。
"""
import math
import os
import struct
import time

from PySide6.QtCore import (QEvent, QPoint, QPointF, QRectF, Qt,
                            QTimer, Signal)
from PySide6.QtGui import (QColor, QCursor, QFont, QImage, QMatrix4x4,
                           QPainter, QPen, QPixmap, QVector2D, QVector3D)
from PySide6.QtOpenGL import (QOpenGLBuffer, QOpenGLShader,
                              QOpenGLShaderProgram,
                              QOpenGLTexture, QOpenGLVertexArrayObject)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication, QPushButton

import numpy as np

from Utils.SeedReverser import structure_models as sm

TEX_DIR = sm.TEX_DIR

_ATLAS_COLS = 16         # 16x32 = 512 槽：当前 272 张 + 未知灰；
                         # 16x16=256 已被新增纹理击穿（tuff bricks 槽 267
                         # 越界采样回绕 → trial 外壳渲染成暖褐，实证）
_ATLAS_ROWS = 32
_ATLAS_TEX = 16          # 每纹理边长（源 16x16，1:1）

_ANCHOR_RED = QColor("#E5484D")
_CHUNK_YELLOW = QColor(255, 214, 0)     # 区块边界线（琥珀黄）
_CHEST_AMBER = QColor(0xF1, 0xC4, 0x0F)  # 箱子高亮描边（琥珀，StructurePreviewer 用）
_FPS_OK = QColor(120, 200, 120, 220)     # FPS 正常（暗绿）
_FPS_BAD = QColor(229, 72, 77, 230)      # FPS 掉帧预警（红）
_FPS_BAD_TH = 30.0                       # 低于此阈值显红（掉帧预警）

# 旁观者模式参数（键位/语义见类 docstring）
_SP_FLY_MIN = 1.0        # 飞行速度限位（格/秒）
_SP_FLY_MAX = 120.0
_SP_MOUSE_SPEED = 0.05  # 鼠标转视角灵敏度默认值（度/像素，UI 可调）
_SP_MOUSE_MIN = 0.01    # 灵敏度下限（度/像素）
_SP_MOUSE_MAX = 0.30    # 灵敏度上限（度/像素）
_SP_PITCH_MAX = 89.9     # FP 俯仰限位（不翻转）
_SP_IDLE_MS = 120        # 无按键心跳：检查全松/光标出窗/失焦
_SP_WHEEL_STEP = 1.1    # 滚轮每格速度倍率
_SP_FLASH_MS = 1400      # 调速提示残显毫秒
_SP_FOV = 85.0           # 视场角（度，用户定 85）
_VSYNC = 0               # swapInterval：0 = 解除垂直同步（帧率不随
                         # 刷新率封顶，可能撕裂）；1 = 恢复 vsync
_SP_LOGIC_HZ = 500.0     # 逻辑 tick 频率（位移积分/渲染调度）：解除
                         # 帧率限制后 tick 不再跟随屏幕刷新率，交互
                         # 帧率上限 ≈ min(_SP_LOGIC_HZ, GPU 渲染能力)
_SP_HZ_MIN = 60.0        # 屏幕刷新率读取兜底（仅诊断展示用）
_SP_HZ_MAX = 240.0       # 屏幕刷新率读取钳制上限（防幽灵报告值）
# 初始眼高分档（用户定）：水平跨度 ≥ 阈值 = 大型结构（下界要塞/
# 堡垒遗迹/村庄等）最高点+10；否则小型（雪屋/沉船等）最高点+5
_SP_START_SPAN = 40.0
_SP_START_LARGE = 10.0
_SP_START_SMALL = 5.0
# 开箱交互：准星判定距离（格，眼睛 -> 箱子方块中心）与视线锥
# （方向点积下限，约 60° 锥角——距离够但箱子在背后/余光不显示）
_SP_CHEST_DIST = 4.0

# 槽宽高 1/16 硬编码进 shader（与 _ATLAS_COLS/_ATLAS_ROWS 同步）：
# PySide6 6.11 setUniformValue(int, float) 重载歧义会把小数截断成
# int 写入（实证 .temp/result_probe_uni.out T_wh 全黑），float 一律
# 不走 uniform。
_VS = """#version 120
attribute vec3 aPos;
attribute vec2 aUV;
attribute vec3 aNor;
attribute vec2 aTile;      // 图集槽原点（上传期烘焙，同 quad 内恒定）
uniform mat4 uMVP;
uniform mat4 uModel;
varying vec2 vUV;
varying vec3 vNor;
varying vec2 vTile;
void main() {
    vUV = aUV;
    vNor = mat3(uModel) * aNor;
    vTile = aTile;
    gl_Position = uMVP * vec4(aPos, 1.0);
}
"""

# 注意：#version 必须是源码首行（前导空行会报错）；桌面 GLSL 不支持
# ES 专用的 precision 语句（NVIDIA 宽松能过，Mesa/llvmpipe 直接拒编）。
_FS = """#version 120
varying vec2 vUV;
varying vec3 vNor;
varying vec2 vTile;
uniform sampler2D uAtlas;
uniform vec3 uLightDir;
const float SLOT_W = 0.0625;   // 1/16 图集 16 列，勿改单一处
const float SLOT_H = 0.03125;  // 1/32 图集 32 行（与 _ATLAS_ROWS 同步）
void main() {
    vec2 tileUV = fract(vUV);
    vec2 pad = vec2(0.5) / vec2(16.0, 16.0);
    tileUV = clamp(tileUV, pad, 1.0 - pad);
    vec2 uv = vTile + vec2(tileUV.x * SLOT_W,
                           (1.0 - tileUV.y) * SLOT_H);
    vec4 tex = texture2D(uAtlas, uv);
    if (tex.a < 0.5) discard;
    float diff = max(dot(normalize(vNor), normalize(uLightDir)), 0.0);
    vec3 col = tex.rgb * (0.42 + 0.58 * diff);
    gl_FragColor = vec4(col, 1.0);
}
"""

# 水第二遍 shader：同一纹理着色，输出半透明
_FS_WATER = """#version 120
varying vec2 vUV;
varying vec3 vNor;
varying vec2 vTile;
uniform sampler2D uAtlas;
uniform vec3 uLightDir;
const float SLOT_W = 0.0625;
const float SLOT_H = 0.03125;
void main() {
    vec2 tileUV = fract(vUV);
    vec2 pad = vec2(0.5) / vec2(16.0, 16.0);
    tileUV = clamp(tileUV, pad, 1.0 - pad);
    vec2 uv = vTile + vec2(tileUV.x * SLOT_W,
                           (1.0 - tileUV.y) * SLOT_H);
    vec4 tex = texture2D(uAtlas, uv);
    float diff = max(dot(normalize(vNor), normalize(uLightDir)), 0.0);
    vec3 col = tex.rgb * (0.42 + 0.58 * diff);
    gl_FragColor = vec4(col, 0.62);
}
"""

_VARIANT_MS = 2500       # 变种轮播间隔
_INTERACT_RESUME_MS = 4000  # 拖动/缩放停手后恢复轮播的等待时长

# 右键旋转光标（位图 _CURSOR_PIX 边长，箭尾共点 = 热点 = 位图中
# 心 C = _CURSOR_PIX//2）：北臂指上、西臂指左，绘制时按当前视角
# 的屏幕投影角整体旋转（_orbit_cursor）；N/W 字母线段（局部盒）
# 位于两箭尖前方 3px，与箭头同步旋转，识别哪支臂指北/西。
# 臂长（共点->箭尖）16px：原 9px 加长 80%（9*1.8≈16），位图随之
# 42->56（字母最远点距中心 26.1 + 描边半宽 < 28，旋转不裁边）。
_CURSOR_PIX = 56
_CURSOR_N_ARM = (
    (28, 28, 28, 14), (28, 12, 24, 16), (28, 12, 32, 16))
_CURSOR_W_ARM = (
    (28, 28, 14, 28), (12, 28, 16, 24), (12, 28, 16, 32))
# N：5x7 盒 @ x 25.5..30.5, y 2..9（左竖 + 对角 + 右竖）
_CURSOR_N_LETTER = (
    (25.5, 9, 25.5, 2), (25.5, 2, 30.5, 9), (30.5, 9, 30.5, 2))
# W：7x5 盒 @ x 2..9, y 25.5..30.5（双 V 四段，中点不到顶）
_CURSOR_W_LETTER = (
    (2, 25.5, 3.75, 30.5), (3.75, 30.5, 5.5, 27.5),
    (5.5, 27.5, 7.25, 30.5), (7.25, 30.5, 9, 25.5))


def _build_atlas():
    """纹理目录全部 png 拼 RGBA 图集；返回 (QImage, {纹理键: 槽索引})。

    槽 0 固定灰（未知材质回退）；纹理按文件名排序入槽。
    """
    names = sorted(fn[:-4] for fn in os.listdir(TEX_DIR)
                   if fn.endswith(".png"))
    if len(names) + 1 > _ATLAS_COLS * _ATLAS_ROWS:
        raise ValueError(
            f"纹理数 {len(names) + 1} 超出图集槽位 "
            f"{_ATLAS_COLS}x{_ATLAS_ROWS}，需扩 _ATLAS_ROWS")
    img = QImage(_ATLAS_COLS * _ATLAS_TEX, _ATLAS_ROWS * _ATLAS_TEX,
                 QImage.Format.Format_RGBA8888)
    img.fill(0)
    p = QPainter(img)
    p.fillRect(0, 0, _ATLAS_TEX, _ATLAS_TEX, QColor(0x9A, 0xA0, 0xA6))
    p.end()
    slots = {"__unknown__": 0}
    for i, name in enumerate(names, start=1):
        tile = QImage(os.path.join(TEX_DIR, name + ".png")).convertToFormat(
            QImage.Format.Format_RGBA8888)
        if tile.width() != _ATLAS_TEX or tile.height() != _ATLAS_TEX:
            tile = tile.scaled(_ATLAS_TEX, _ATLAS_TEX)
        cx = (i % _ATLAS_COLS) * _ATLAS_TEX
        cy = (i // _ATLAS_COLS) * _ATLAS_TEX
        p = QPainter(img)
        p.drawImage(cx, cy, tile)
        p.end()
        slots[name] = i
    return img, slots


def _bake_tile_origin(verts, slots, slot_mat, atlas_slots, idx=None,
                      quad_slot=None) -> np.ndarray:
    """8 列顶点 -> 10 列（尾部追加图集槽原点 aTile）。

    - 主路径（quad_slot 提供）：quad→槽号直接查表，每 quad 4 顶点
      同 tile；空槽（count=0）不占 quad，槽号 = slots 下标；
    - quad_slot 缺省兼容旧 mesh：按「非空槽顺序填满」推归属；
    - idx 仅用于尾段水区间：按索引位置（主体 6/quad 之后）取引用
      值赋 water 槽原点；
    - halfheight: 前缀材质与基材质共纹理（半高变体）；
    - list/numpy 输入先 numpy 化（低层注入旧格式兼容）；
    - 空 verts 返回 (0,10) 数组；无归属顶点（防御）tile=(0,0)。
    """
    v8 = np.asarray(verts, dtype=np.float32)
    n8 = v8.size
    if n8 % 8:
        raise ValueError(f"verts 元素数 {n8} 非 8 倍数")
    n_v = n8 // 8
    A10 = np.zeros((n_v, 10), dtype=np.float32)
    if not n_v:
        return A10
    A10[:, :8] = v8.reshape(n_v, 8)
    if quad_slot is None:
        # 兼容路径：非空槽顺序填满顶点前缀（每 quad 4 顶点）
        vspan = np.array([c for (_s, c) in slots], dtype=np.int64) \
            // 6 * 4
        if len(slots):
            tsel = np.repeat(np.arange(len(slots), dtype=np.int64),
                             vspan)[:n_v]
        else:
            tsel = np.full(n_v, -1, dtype=np.int64)
    else:
        q = np.asarray(quad_slot, dtype=np.int64)
        # 每 quad 4 顶点同槽；越界 quad 号（防御）无归属走灰。
        # 水顶点不在 quad_slot 内（水走独立第二遍）：尾部补 -1，
        # tile 先走灰，水覆盖阶段再赋水槽原点
        q = np.where((q >= 0) & (q < len(slot_mat)), q, -1)
        tsel = np.repeat(q, 4)
        if tsel.size < n_v:
            tsel = np.concatenate(
                (tsel, np.full(n_v - tsel.size, -1, dtype=np.int64)))
        tsel = tsel[:n_v]
    m2t = []
    for m in slot_mat:
        base = m[len("halfheight:"):] if m.startswith("halfheight:") \
            else m
        s = atlas_slots.get(base, atlas_slots.get("__unknown__", 0))
        m2t.append(((s % _ATLAS_COLS) / _ATLAS_COLS,
                    (s // _ATLAS_COLS) / _ATLAS_ROWS))
    while len(m2t) < len(slots):        # 防御：slot_mat 缺项走灰
        m2t.append((0.0, 0.0))
    m2t.append((0.0, 0.0))              # 无归属（-1）兜底槽
    # tsel 语义：>=0 = slots 下标（直接查 m2t[tsel]）；-1 = 无归属
    # （水顶点先兜底，随后水覆盖阶段赋水槽原点）
    tsel2 = np.where(tsel >= 0, tsel, len(m2t) - 1)
    tile = np.array([m2t[i] for i in tsel2], dtype=np.float32)
    A10[:, 8:10] = tile
    if idx is not None:
        # 水顶点 tile 覆盖（整体 tile 赋值之后）：水区间按索引
        # 「位置」划定（主体 6/quad 之后），引用「值」才是水顶点号
        ref = np.asarray(idx).reshape(-1).astype(np.int64, copy=False)
        if quad_slot is not None:
            n_body = int(len(quad_slot)) * 6
        else:
            n_body = sum(c for (_s, c) in slots) if slots else 0
        wv = ref[n_body:]
        wv = wv[(wv >= 0) & (wv < n_v)]
        if wv.size:
            ws = atlas_slots.get("water",
                                 atlas_slots.get("__unknown__", 0))
            A10[wv, 8] = (ws % _ATLAS_COLS) / _ATLAS_COLS
            A10[wv, 9] = (ws // _ATLAS_COLS) / _ATLAS_ROWS
    return A10


class Structure3DView(QOpenGLWidget):
    """结构 3D 交互视口（右键环绕 / 滚轮缩放 / 左键平移 / 双击复位）。"""

    # 渲染报错（构建模型/上传/绘制任一环节异常）：tool 层连接后写入
    # 信息框；视口自身同步停渲染并复位开关按钮
    render_error = Signal(str)
    # 右键开箱（准星态）：参数 = model["chests"] 内索引；tool 层
    # 连接后弹箱子 GUI（战利品求值与图标资产都在工具层）
    chest_open_requested = Signal(int)
    # 锁定态（开箱 GUI 期间）按 Esc/E：用户想关 GUI，但焦点可能被
    # 视口/主窗拿走（非模态弹窗失焦即死锁：无边框无关闭钮、锁定
    # 态吞键盘）；tool 层连接后转发关闭 self._chest_dlg
    spectator_close_request = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        if self.format().swapInterval() != _VSYNC:
            fmt = self.format()
            fmt.setSwapInterval(_VSYNC)   # 解除 vsync：须 expose 前
            self.setFormat(fmt)
        self._key = None
        self._variant = None                 # 变种序号（None = 默认模板）
        self._variant_n = 0                  # 变种总数（0 = 非变种键）
        self._model = None
        self._slot_of_mat = {}               # 网格槽序 -> 图集槽号
        self._gl_ready = False
        self._needs_upload = False           # 模型待上传（GL 上下文内执行）
        # 渲染开关：默认不渲染（用户点右上角按钮开启；渲染出错自动
        # 复位为关闭，错误写入工具层信息框）
        self._render_enabled = False
        self._render_failed = False         # 出错后本模型不再重试（防刷屏）
        self._cursor_angle = 0.0             # 光标当前旋转角（缓存供退化分支）
        self._render_btn = QPushButton("渲染模型", self)
        self._render_btn.setObjectName("renderToggleBtn")
        self._render_btn.setFixedSize(76, 24)
        self._render_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._render_btn.clicked.connect(self._on_render_toggle)
        self._render_btn.raise_()
        self._reposition_render_btn()
        # 相机状态
        self._yaw = 225.0
        self._pitch = 35.0
        self._dist = None                    # None = 按模型尺寸自适应
        self._pan = QVector3D(0, 0, 0)
        self._center = QVector3D(0, 0, 0)
        self._radius = 10.0
        self._last_pos: QPoint | None = None
        # GL 资源占位
        self._vao = None
        self._vbo = None
        self._ibo = None
        self._idx_type = 0x1403
        self._anchor_verts = None
        self._anchor_vbo = None
        self._chunk_verts = None             # 区块边界线段（展平 xyz）
        self._chunk_vbo = None
        # 水第二遍数据（paintGL 内使用）
        self._water_off = 0
        self._water_count = 0
        self._water_slot = 0
        # chunk 剔除数据（_upload_model 注入）：[(idx_off, idx_count,
        # AABB...)]；_idx_itemsize = 索引元素字节数（draw 偏移换算）
        self._chunks: list = []
        self._idx_itemsize = 2
        # 逐 section 可见性矩阵（_upload_model 注入 mesh["occl"]）；
        # 无（旧 mesh/低层注入）= None，旁观模式退化为纯视锥剔除
        self._occl: dict | None = None
        # 眼 section BFS 传播结果缓存（_occl_cells_for_eye 用）：
        # 键 = 眼 section 16³ 键，值 = 允许 chunk 序号集
        self._occl_cache_key = None
        self._occl_cache_cells: set | None = None
        # 阻挡格集合（set_model 时注入，isSolidRender 同款语义：
        # 整格且非透明）：眼实心格判定 O(1)
        self._occl_opaque: set = set()
        # 箱子高亮描边（set_chest_highlights 注入；(cx,cy,cz)->展平顶点）
        self._chest_verts: dict | None = None
        self._chest_vbo = None
        self._needs_chest_upload = False
        # 开箱交互：箱子位置（set_interact_chests 注入，模型坐标）
        # 与当前准星命中索引（-1 = 不显示准星）
        self._interact_chests: list | None = None
        self._sp_crosshair_idx = -1
        self._sp_resume_grab = False      # 箱子 GUI 关闭后是否恢复锁定
        # FPS 统计（帧间滚动均值）：_fps_frame_t 上帧时刻，
        # _fps_frames/_fps_accum 窗口内帧数与累计时长，_fps_text
        # 上次刷新的显示文本（0.5s 刷新一次防数字闪烁）
        self._fps_frame_t = None
        self._fps_frames = 0
        self._fps_accum = 0.0
        self._fps_text = ""
        # 变种轮播定时器：应用退出时停止，防退出阶段析构崩溃
        # （PySide6 退出期 QThread/QTimer/顶层窗口析构 -> 0xC0000409）
        self._variant_timer = QTimer(self)
        self._variant_timer.setInterval(_VARIANT_MS)
        self._variant_timer.timeout.connect(self._cycle_variant)
        # 交互暂停轮播：拖动/缩放期间停轮播，停手 4s 后恢复
        #（单发定时器到点重启轮播；拖动中每帧续期）
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(_INTERACT_RESUME_MS)
        self._idle_timer.timeout.connect(self._resume_rotation)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._stop_spin_timers)
        # 旁观者相机（FP 飞行）：默认关闭（SeedReverser 保持环绕模式）
        self._sp_mode = False
        self._sp_keys: set[int] = set()  # 当前按下的移动键（Key 枚举 int）
        self._sp_input_locked = False    # True = 输入总闸（开箱 GUI 期间）
        self._sp_input_locked = False    # True = 输入总闸（开箱 GUI 期间）
        self._sp_speed = 20.0            # 格/秒
        self._sp_grabbed = False         # True = 鼠标锁定转视角
        self._sp_mouse_speed = _SP_MOUSE_SPEED   # 转视角灵敏度（度/像素）
        self._sp_last_ev_pos: QPoint | None = None
        self._sp_speed_until_ms = 0      # 调速提示残显截止（ms，monotonic）
        self._sp_eye = QVector3D(0, 0, 0)   # 旁观者眼睛位置（世界坐标）
        # 锁定期钉扎定时器 + 飞行 tick：解除帧率限制后固定
        # _SP_LOGIC_HZ 高频（位移积分按 interval 缩放自适应，飞行
        # 平滑度不变；交互帧率上限 ≈ min(_SP_LOGIC_HZ, GPU 能力)，
        # 不再随屏幕刷新率封顶）。钉扎不依赖 mouseMove 事件流
        # （Windows 事件合并/延迟会导致回中滞后、光标漂出窗口边缘）。
        self._sp_hz = _SP_HZ_MIN         # 所在屏刷新率（仅诊断展示）
        self._sp_pin = QTimer(self)
        self._sp_pin.setInterval(int(1000.0 / _SP_LOGIC_HZ))
        # PreciseTimer：Windows 默认 CoarseTimer 的 2ms 实际会被
        # 系统定时器分辨率拖到 ~8ms（实测 126Hz），高刷屏下帧率
        # 被隐形钳半；PreciseTimer 走高精度等待，2ms 精确触发。
        self._sp_pin.setTimerType(Qt.TimerType.PreciseTimer)
        self._sp_pin.timeout.connect(self._spectator_pin_tick)
        self._sp_tick = QTimer(self)
        self._sp_tick.setInterval(int(1000.0 / _SP_LOGIC_HZ))  # 飞行 tick
        self._sp_tick.setTimerType(Qt.TimerType.PreciseTimer)
        self._sp_tick.timeout.connect(self._spectator_tick)
        # 无按键心跳：检查全松/光标出窗/失焦（低频）
        self._sp_idle = QTimer(self)
        self._sp_idle.setInterval(_SP_IDLE_MS)
        self._sp_idle.timeout.connect(self._spectator_idle_check)

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------
    def set_structure(self, key: str | None, name: str = "") -> None:
        """切换结构（模型走 build_model 缓存；GL 就绪后上传缓冲）。

        变种结构（VARIANT_KEYS）额外启动轮播定时器：先显示默认
        模板，2.5s 起每间隔换下一个官方模板变种。
        """
        if key == self._key and self._model is not None:
            return
        model = None
        if key:
            try:
                model = sm.build_model(key)
            except Exception as exc:
                # 模型构建失败：信息框提示 + 停渲染（同 paintGL 出错链路）
                self._render_enabled = False
                self._render_btn.setText("渲染模型")
                self.render_error.emit(
                    f"3D 预览：结构 {name or key} 模型构建失败，已停止渲染（{exc}）")
        self._load_model(model, key, len(sm.VARIANT_FILES.get(key, ())))

    def set_model(self, model: dict | None) -> None:
        """低层注入入口（StructurePreviewer 用）：外建模型直接进视口。

        model 为 compose_display_model + build_mesh 组装的完整 dict
        （含 mesh/tex_keys），格式与 build_model 输出一致；与
        set_structure 互斥——注入后 _key 置 None 退出结构键模式
        （不轮播、锚点/区块线按模型 size 默认西北角口径）。
        注入模型可带两个覆盖字段：anchor_local=(ax,az) 指定锚点
        红线在模型内坐标，chunk_origin=(gx0,gz0) 指定区块黄框相位
        （均相对模型原点；缺省仍为 (0,0) 西北角口径）。
        """
        self._load_model(model, None, 0)

    def _load_model(self, model: dict | None, key: str | None,
                    variant_n: int = 0) -> None:
        """模型装填公共段（set_structure / set_model 共用）。

        model 构建异常在调用方处理；这里只负责状态复位与上传标记。
        variant_n 仅结构键模式非零（变种轮播）；注入模式恒 0。
        """
        self._variant_timer.stop()
        self._key = key
        self._variant = None
        self._variant_n = variant_n
        self._model = model
        self._slot_of_mat = {}
        self._render_failed = False      # 新模型重新允许尝试渲染
        self._chest_verts = None         # 换模型：旧箱子高亮失效
        self._needs_chest_upload = False
        # 换模型：旧箱子交互坐标失效（tool 层预览后重新注入）
        self._interact_chests = None
        self._sp_crosshair_idx = -1
        if variant_n and model is not None:
            self._variant_timer.start()
        self._idle_timer.stop()          # 切模型后不在交互暂停态
        self._reset_camera_for_model()
        if self._sp_mode:
            # 换模型：旁观者相机重置到新模型前缘。不改变鼠标锁定
            # 状态——未控制时光标不该凭空隐藏；控制中保持连续
            #（仅刷新回中基准点，防换模型瞬间视角跳变）
            self._spectator_reposition()
            self._sp_keys.clear()
            if self._sp_grabbed:
                self._spectator_recenter(reset_base=True)
        # GL 上传只能在上下文就绪时执行（paintGL），此处只标记
        self._needs_upload = bool(self._model)
        self.update()

    def stop_variant_timer(self) -> None:
        """停掉轮播与空闲定时器（应用退出钩子调用，防退出期析构崩溃）。"""
        self._stop_spin_timers()
        # 旁观者定时器一并停（tick/心跳/钉扎持引用，防退出期回调）
        self._sp_tick.stop()
        self._sp_idle.stop()
        self._sp_pin.stop()

    def set_chest_highlights(self, positions) -> None:
        """箱子高亮描边（StructurePreviewer 箱子行点击联动用）。

        positions: [(x, y, z), ...] 模型坐标（None/空清空）；每个箱子
        画一个跨度 1.1 的包围盒描边（比体素大 0.05，避免与模型面
        z-fighting）。
        """
        verts = []
        for (cx, cy, cz) in (positions or []):
            e = 0.05
            x0, x1 = cx - e, cx + 1.0 + e
            y0, y1 = cy - e, cy + 1.0 + e
            z0, z1 = cz - e, cz + 1.0 + e
            for (a, b, c, d) in (   # 12 条棱：六个矩形环各 4 条
                    ((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)),
                    ((x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)),
                    ((x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0)),
                    ((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)),
                    ((x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)),
                    ((x1, y0, z0), (x1, y0, z1), (x1, y1, z1), (x1, y1, z0))):
                ring = (a, b, c, d)
                for i in range(4):
                    p = ring[i]
                    q = ring[(i + 1) % 4]
                    verts.extend((*p, *q))
        self._chest_verts = verts or None
        self._needs_chest_upload = True
        self.update()

    def set_interact_chests(self, positions) -> None:
        """注入可交互箱子坐标（开箱准星判定用，模型坐标）。

        positions: [(x, y, z), ...]（None/空清空）；与
        set_chest_highlights 的数据同源（model["chests"]），独立
        存储以便换模型时分别失效。
        """
        self._interact_chests = list(positions) if positions else None
        self._spectator_update_crosshair()
        self.update()

    def crosshair_active(self) -> bool:
        """当前是否显示开箱准星（准星命中箱子）。"""
        return self._sp_crosshair_idx >= 0

    def note_chest_gui_closed(self) -> None:
        """箱子 GUI 已关闭（tool 层回调）：按需恢复鼠标锁定。

        开箱瞬间若处于锁定态（转视角中），GUI 关闭后自动恢复
        锁定继续飞行（还原开箱前的控制状态）；呼出态开箱则不
        抢锁定。
        """
        if self._sp_resume_grab and self._sp_mode and self.isVisible():
            self._sp_resume_grab = False
            self._spectator_grab_mouse()
        self._sp_resume_grab = False

    def set_spectator_input_locked(self, on: bool) -> None:
        """旁观者输入总闸：开箱 GUI 显示期间锁死 FP 飞行输入。

        True：清按键集、停飞行 tick、呼出鼠标（若锁定转视角中）；
        之后键盘/鼠标点击/滚轮事件全部吞掉，视口不可移动/转视角。
        False：恢复控制；若开箱前处于锁定态（_sp_resume_grab），
        按既有语义恢复鼠标捕获继续飞行。
        与 set_spectator_mode 正交：仅锁输入，不切相机/不重置位置。
        """
        on = bool(on)
        if on == self._sp_input_locked:
            return
        self._sp_input_locked = on
        if on:
            self._sp_keys.clear()
            self._sp_tick.stop()
            if self._sp_grabbed:
                self._spectator_release_mouse()
        else:
            self.note_chest_gui_closed()
        self.update()

    def spectator_input_locked(self) -> bool:
        """输入总闸当前状态（测试/诊断用）。"""
        return self._sp_input_locked

    def set_spectator_input_locked(self, on: bool) -> None:
        """旁观者输入总闸：开箱 GUI 显示期间锁死 FP 飞行输入。

        True：清按键集、停飞行 tick、呼出鼠标（若锁定转视角中）；
        之后键盘/鼠标/滚轮事件全部吞掉，视口不可移动/转视角。
        False：恢复控制；若开箱前处于锁定态（_sp_resume_grab），
        按既有语义恢复鼠标捕获继续飞行。
        与 set_spectator_mode 正交：仅锁输入，不切相机/不重置位置。
        """
        on = bool(on)
        if on == self._sp_input_locked:
            return
        self._sp_input_locked = on
        if on:
            self._sp_keys.clear()
            self._sp_tick.stop()
            if self._sp_grabbed:
                self._spectator_release_mouse()
        else:
            self.note_chest_gui_closed()
        self.update()

    def spectator_input_locked(self) -> bool:
        """输入总闸当前状态（测试/诊断用）。"""
        return self._sp_input_locked

    # ------------------------------------------------------------------
    # 渲染开关（右上角按钮；默认不渲染）
    # ------------------------------------------------------------------
    def _reposition_render_btn(self) -> None:
        """开关按钮固定在视口右上角（resizeEvent 同步调用）。"""
        self._render_btn.move(self.width() - self._render_btn.width() - 8,
                              8)

    def resizeEvent(self, ev) -> None:  # noqa: N802
        self._reposition_render_btn()
        super().resizeEvent(ev)

    def set_render_enabled(self, on: bool) -> None:
        """开关模型渲染（按钮点击与测试/外部控制共用入口）。"""
        self._render_enabled = bool(on)
        self._render_btn.setText("停止渲染" if self._render_enabled
                                 else "渲染模型")
        self.update()

    def _on_render_toggle(self) -> None:
        """按钮点击：切换渲染开关（同步文案 + 重绘）。"""
        self.set_render_enabled(not self._render_enabled)

    # ------------------------------------------------------------------
    # 旁观者模式（FP 飞行；StructurePreviewer 用，环绕模式不受影响）
    # ------------------------------------------------------------------
    def set_spectator_mode(self, on: bool) -> None:
        """切换旁观者相机模式。

        True：进入 FP 飞行相机——眼睛置于模型前缘中点，视线指向
        模型中心（默认锁定鼠标自由转视角）；飞行速度按模型半径
        自适应。False：退出旁观者，恢复环绕相机复位态。
        两种模式各自保留状态；切换后 update() 重绘。
        """
        on = bool(on)
        if on == self._sp_mode:
            return
        self._sp_mode = on
        if on:
            self._spectator_enter()
        else:
            self._spectator_exit()
        self.update()

    def is_spectator_mode(self) -> bool:
        """当前是否旁观者模式（tool 层 ` 兜底转发判断用）。"""
        return self._sp_mode

    def mouse_grabbed(self) -> bool:
        """旁观者模式下鼠标是否处于锁定（转视角）状态。"""
        return self._sp_grabbed

    def spectator_toggle_grab(self) -> None:
        """` 键公开入口：锁定/呼出鼠标（视口键处理与 tool 兜底共用）。"""
        self._spectator_toggle_grab()

    def spectator_sensitivity(self) -> float:
        """当前鼠标转视角灵敏度（度/像素）。"""
        return self._sp_mouse_speed

    def set_spectator_sensitivity(self, deg_per_px: float) -> None:
        """设置鼠标转视角灵敏度（度/像素），限位后生效。

        tool 层灵敏度滑条联动入口；立即对所有模式生效（旁观者
        转视角与 orbit 拖拽系数独立，orbit 不受影响）。
        """
        self._sp_mouse_speed = max(_SP_MOUSE_MIN,
                                   min(_SP_MOUSE_MAX, float(deg_per_px)))

    def fov_deg(self) -> float:
        """当前视场角（度）。"""
        return _SP_FOV

    def _spectator_exit(self) -> None:
        """退出旁观者：停 tick、松键、还原鼠标与窗口元键态。"""
        self._spectator_release_mouse()
        self._sp_keys.clear()
        self._sp_tick.stop()
        self._sp_idle.stop()
        # 清残留的窗口级元键（否则松键后 shift/space 影响点击行为）
        w = self.window()
        if hasattr(w, "clear_meta_pressed_keys"):
            w.clear_meta_pressed_keys()
        self._reset_camera_for_model()

    def _spectator_enter(self) -> None:
        """进入旁观者：相机复位到模型前缘中点，看向模型中心。

        不自动锁鼠标：待用户点击视口（或按 `）才开始控制视角。
        """
        self._reset_camera_for_model()
        self._spectator_reposition()
        self._sp_keys.clear()
        self._sp_grabbed = False
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _spectator_reposition(self) -> None:
        """按当前模型体素范围，重置旁观者眼睛与姿态。

        进入模式与换模型（_load_model）共用：眼睛悬于模型水平
        中点正上方俯视（pitch -89.9°，不用 -90° 规避 lookAt 与
        up 向量共线的退化）；高度按结构体量分档——水平跨度 ≥
        _SP_START_SPAN 视为大型（下界要塞/堡垒遗迹/村庄等）取
        最高点+10 格，否则小型（雪屋/沉船等）取最高点+5 格。
        体素范围直接从 voxels 扫描（两条模型路径的 size 元组
        顺序不同，不可靠）；速度仍随 orbit 半径自适应。
        """
        if self._model and self._model["voxels"]:
            vox = self._model["voxels"]
            xs = [p[0] for p in vox]
            ys = [p[1] for p in vox]
            zs = [p[2] for p in vox]
            span = max(max(xs) - min(xs), max(zs) - min(zs))
            h_above = _SP_START_LARGE if span >= _SP_START_SPAN \
                else _SP_START_SMALL
            self._sp_eye = QVector3D(
                (min(xs) + max(xs) + 1) / 2.0, max(ys) + h_above,
                (min(zs) + max(zs) + 1) / 2.0)
        else:
            # 空模型兜底：沿用 orbit 包围盒口径（正上空俯视）
            self._sp_eye = self._center + QVector3D(0.0, self._radius * 1.35,
                                                    0.0)
        self._yaw = 0.0
        self._pitch = -_SP_PITCH_MAX
        self._sp_speed = max(_SP_FLY_MIN,
                             min(_SP_FLY_MAX, self._radius * 1.2))

    def _stop_spin_timers(self) -> None:
        """轮播 + 交互空闲定时器一并停（aboutToQuit/退出钩子共用）。"""
        self._variant_timer.stop()
        self._idle_timer.stop()

    def _pause_rotation(self) -> None:
        """拖动/缩放期间暂停轮播；停手 _INTERACT_RESUME_MS 后恢复。

        空闲定时器单发：持续拖动中每次事件都重启计时，只在真正
        停手后到点恢复；非变种键（_variant_n=0）无必要，跳过。
        """
        if not self._variant_n:
            return
        self._variant_timer.stop()
        self._idle_timer.start()         # 单发，重复 start = 续期

    def _resume_rotation(self) -> None:
        """停手超时：重启轮播（隐藏期由 hideEvent 保持停止）。"""
        self._idle_timer.stop()          # 撤销暂停态计时（防残留空触发）
        if self._variant_n and self.isVisible() \
                and not self._variant_timer.isActive():
            self._variant_timer.start()

    def _cycle_variant(self) -> None:
        """轮播定时器到点：切到下一变种模板（相机保持方位自适应）。"""
        if not self._variant_n or not self._key:
            return
        nxt = 0 if self._variant is None else (self._variant + 1) \
            % self._variant_n
        self._variant = nxt
        self._render_failed = False      # 下一变种重新允许尝试渲染
        try:
            self._model = sm.build_model(self._key, nxt)
        except Exception as exc:
            self._model = None
            self._render_enabled = False
            self._render_btn.setText("渲染模型")
            self.render_error.emit(
                f"3D 预览：变种模型构建失败，已停止渲染（{exc}）")
        self._adapt_camera_for_model()
        self._needs_upload = bool(self._model)
        self.update()

    def _reset_camera_for_model(self) -> None:
        """按模型包围盒自适应中心/半径，复位角度、距离与平移。"""
        if self._model and self._model["voxels"]:
            w, d, h = self._model["size"]    # x/z/y 跨度
            self._center = QVector3D(w / 2.0, h * 0.38, d / 2.0)
            self._radius = max(w, d, h) * 0.72 + 2.0
        else:
            self._center = QVector3D(0, 0, 0)
            self._radius = 10.0
        self._yaw = 225.0
        self._pitch = 35.0
        self._dist = None
        self._pan = QVector3D(0, 0, 0)

    def _adapt_camera_for_model(self) -> None:
        """变种轮播：保持用户方位角/俯仰，仅适配中心/半径/平移。"""
        if self._model and self._model["voxels"]:
            w, d, h = self._model["size"]
            self._center = QVector3D(w / 2.0, h * 0.38, d / 2.0)
            self._radius = max(w, d, h) * 0.72 + 2.0
            self._dist = None
            self._pan = QVector3D(0, 0, 0)

    # ------------------------------------------------------------------
    # 鼠标交互（环绕模式；旁观者分支见下方覆写版）
    # ------------------------------------------------------------------
    def _screen_angle(self) -> float:
        """世界北向的屏幕投影角（度，0° = 屏幕正上，顺时针为正）。

        与 _pan_screen 同款视线基：right/up 即 gluLookAt 的相机
        右/上轴（视空间 +x 右、+y 上）。方向 d 的屏幕投影分量 =
        (d·right, d·up)，角 = atan2(x, y)（0°上/90°右/180°下/270°左）。
        物理锚点自检：正对北看（yaw=90，俯视地图视图）时北投影
        = 正上（0°）；正对西看（yaw=0）时北在屏幕右（90°）。
        相机俯仰被钳制在 5°~85°，视线永不水平/竖直，北向投影
        模长恒近 1，无退化；sx=sy 双零分支仅作纯防御。
        """
        yr, pr = math.radians(self._yaw), math.radians(self._pitch)
        fwd = QVector3D(-math.cos(yr) * math.cos(pr), -math.sin(pr),
                        -math.sin(yr) * math.cos(pr))
        right = QVector3D.crossProduct(fwd, QVector3D(0, 1, 0)).normalized()
        up = QVector3D.crossProduct(right, fwd).normalized()
        north = QVector3D(0, 0, -1)
        sx = QVector3D.dotProduct(north, right)
        sy = QVector3D.dotProduct(north, up)   # 视空间 +y = 屏幕上
        if abs(sx) < 1e-6 and abs(sy) < 1e-6:
            return self._cursor_angle          # 投影退化（不可达）：保持上帧
        return math.degrees(math.atan2(sx, sy)) % 360.0

    def _orbit_cursor(self) -> QCursor:
        """右键旋转光标：北/西双箭头 + N/W 字母按视角整体旋转。

        字母置于箭尖前方 3px（沿臂延长线），与箭头同步旋转，
        标识哪支臂指北/西（替代已删的地面罗盘层）；白色主线 +
        半透明深色描边（DestinationOver 垫底），浅色/深色地图上
        都可读；热点 = 位图中心 = 箭尾共点，光标点 = 用户
        视角中心。旋转角来自 _screen_angle()（世界北向的屏幕
        投影），随右键拖拽实时变化；结果缓存 _cursor_angle 供
        退化分支复用。
        """
        angle = self._screen_angle()
        self._cursor_angle = angle
        c = _CURSOR_PIX // 2                # 共点 = 位图中心
        pm = QPixmap(_CURSOR_PIX, _CURSOR_PIX)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        # 以共点 C 为轴整体旋转后画同一套箭臂 + 字母线段
        #（字母 1.5px 细线区别于箭臂 2px 主线）
        p.translate(c, c)
        p.rotate(angle)
        p.translate(-c, -c)
        for width, segs in (
                (1.5, _CURSOR_N_LETTER + _CURSOR_W_LETTER),
                (2.0, _CURSOR_N_ARM + _CURSOR_W_ARM)):
            pen = QPen(QColor(255, 255, 255), width)
            pen.setCosmetic(True)
            p.setPen(pen)
            for seg in segs:
                p.drawLine(*seg)
        p.end()
        # 深色底面提高浅色地图上的可读性（DestinationOver 只垫
        # 透明区，不覆盖已画白色主线；描边 3.5px 覆盖全部线段）
        p2 = QPainter(pm)
        p2.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_DestinationOver)
        p2.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p2.translate(c, c)
        p2.rotate(angle)
        p2.translate(-c, -c)
        p2.setPen(QPen(QColor(30, 30, 30, 180), 3.5))
        for seg in (_CURSOR_N_ARM + _CURSOR_W_ARM
                    + _CURSOR_N_LETTER + _CURSOR_W_LETTER):
            p2.drawLine(*seg)
        p2.end()
        return QCursor(pm, c, c)

    def mouseDoubleClickEvent(self, ev) -> None:  # noqa: N802
        if self._sp_mode:
            ev.accept()      # 旁观者模式：双击无环绕复位语义
            return
        self._reset_camera_for_model()
        self.update()

    def showEvent(self, ev) -> None:  # noqa: N802
        if self._variant_n and not self._variant_timer.isActive():
            self._variant_timer.start()
        self._idle_timer.stop()          # 交互暂停态不跨隐藏保留
        self._spectator_apply_refresh_rate()
        super().showEvent(ev)

    def event(self, ev) -> bool:  # noqa: N802
        # 跨屏拖动：记录目标屏刷新率（QWindow.screenChanged 的
        # widget 层等价信号，QEvent 层拦截；仅诊断，不再节流定时器）
        if ev.type() == QEvent.Type.ScreenChangeInternal:
            self._spectator_apply_refresh_rate()
        return super().event(ev)

    def _spectator_apply_refresh_rate(self) -> None:
        """记录所在屏幕刷新率（诊断展示）。

        解除帧率限制后逻辑 tick 固定 _SP_LOGIC_HZ、swapInterval
        固定 _VSYNC，屏幕刷新率不再节流定时器（保留读取仅作诊断
        展示；无效值 offscreen/虚拟屏报告 0 兑底 60Hz）。
        """
        hz = _SP_HZ_MIN
        try:
            r = float(self.screen().refreshRate())
            if r >= 1.0:
                hz = r
        except Exception:
            pass
        self._sp_hz = hz

    def _orbit(self, dx: float, dy: float) -> None:
        self._yaw = (self._yaw + dx) % 360.0
        self._pitch = max(5.0, min(85.0, self._pitch + dy))

    def _pan_screen(self, d: QPoint) -> None:
        """屏幕像素平移 -> 世界平移（按当前距离与 45° 视野估算）。"""
        dist = self._dist if self._dist else self._radius * 2.2
        scale = 2.0 * dist * math.tan(math.radians(22.5)) / max(
            1, self.height())
        yr, pr = math.radians(self._yaw), math.radians(self._pitch)
        # 视线方向的水平垂直基
        fwd = QVector3D(-math.cos(yr) * math.cos(pr), -math.sin(pr),
                        -math.sin(yr) * math.cos(pr))
        right = QVector3D.crossProduct(fwd, QVector3D(0, 1, 0)).normalized()
        up = QVector3D.crossProduct(right, fwd).normalized()
        self._pan += right * (-d.x() * scale) + up * (d.y() * scale)

    def _eye_pos(self) -> QVector3D:
        dist = self._dist if self._dist else self._radius * 2.2
        yr, pr = math.radians(self._yaw), math.radians(self._pitch)
        off = QVector3D(math.cos(yr) * math.cos(pr), math.sin(pr),
                        math.sin(yr) * math.cos(pr)) * dist
        return self._center + self._pan + off

    # ------------------------------------------------------------------
    # 旁观者：键盘 / 鼠标 / 飞行 tick
    # ------------------------------------------------------------------
    # 键集合存 int；PySide6 枚举成员 hash 与 int 不同，匹配必须
    # 双侧统一 int（tick 内用下划线常量）
    _SP_K_W = int(Qt.Key.Key_W)
    _SP_K_A = int(Qt.Key.Key_A)
    _SP_K_S = int(Qt.Key.Key_S)
    _SP_K_D = int(Qt.Key.Key_D)
    _SP_K_UP = int(Qt.Key.Key_Up)
    _SP_K_DOWN = int(Qt.Key.Key_Down)
    _SP_K_LEFT = int(Qt.Key.Key_Left)
    _SP_K_RIGHT = int(Qt.Key.Key_Right)
    _SP_K_SPACE = int(Qt.Key.Key_Space)
    _SP_K_SHIFT = int(Qt.Key.Key_Shift)
    _SP_K_QUOTE = int(Qt.Key.Key_QuoteLeft)
    _SP_K_TILDE = int(Qt.Key.Key_AsciiTilde)
    _SP_K_ESC = int(Qt.Key.Key_Escape)
    _SP_K_E = int(Qt.Key.Key_E)

    def keyPressEvent(self, ev) -> None:  # noqa: N802
        if not self._sp_mode or ev.isAutoRepeat():
            super().keyPressEvent(ev)
            return
        if self._sp_input_locked:    # 开箱 GUI 期间：Esc/E 转发关
            # 弹窗（焦点可能已不在弹窗：非模态窗失焦后 Esc/E 会
            # 到这里被吞，不转发则 GUI 关不掉），其余全吞
            if int(ev.key()) in (self._SP_K_ESC, self._SP_K_E):
                self.spectator_close_request.emit()
            ev.accept()
            return
        k = int(ev.key())
        if k == self._SP_K_QUOTE or k == self._SP_K_TILDE:
            self.spectator_toggle_grab()
            ev.accept()
            return
        if k == self._SP_K_ESC and self._sp_grabbed:
            self._spectator_release_mouse()
            ev.accept()
            return
        if k == self._SP_K_E and self._sp_crosshair_idx >= 0 \
                and self._sp_grabbed:
            # E 也可开箱（准星态，与游戏按键一致）；仅锁定态拦截
            #（呼出态 E 不截胡）
            idx = self._sp_crosshair_idx
            self._sp_resume_grab = True
            self._spectator_release_mouse()
            self._sp_keys.clear()
            self.chest_open_requested.emit(idx)
            ev.accept()
            return
        if (k in (self._SP_K_W, self._SP_K_A, self._SP_K_S, self._SP_K_D,
                  self._SP_K_UP, self._SP_K_DOWN, self._SP_K_LEFT,
                  self._SP_K_RIGHT, self._SP_K_SPACE, self._SP_K_SHIFT)):
            self._sp_keys.add(k)
            self._sp_start_loop()
            self.update()
            ev.accept()
            return
        super().keyPressEvent(ev)

    def keyReleaseEvent(self, ev) -> None:  # noqa: N802
        if not self._sp_mode or ev.isAutoRepeat():
            super().keyReleaseEvent(ev)
            return
        if self._sp_input_locked:    # 锁定期：键集已清，吞掉释放
            ev.accept()
            return
        k = int(ev.key())
        if k in self._sp_keys:
            self._sp_keys.discard(k)
            ev.accept()
            return
        super().keyReleaseEvent(ev)

    def focusOutEvent(self, ev) -> None:  # noqa: N802
        # 失焦时立刻松全部键（切换窗口/控件后按键态不残留）
        if self._sp_mode:
            self._sp_keys.clear()
            if self._sp_grabbed:
                self._spectator_release_mouse()
        super().focusOutEvent(ev)

    def _sp_start_loop(self) -> None:
        """有键按下：启动飞行 tick；低频心跳兜底。"""
        if not self._sp_tick.isActive():
            self._sp_tick.start()
        if not self._sp_idle.isActive():
            self._sp_idle.start()

    def _spectator_tick(self) -> None:
        """按屏幕刷新率 FP 飞行：按当前键集沿视线/世界轴推进眼睛。

        WASD/方向键 = 水平四向（无视 pitch，MC 玩家习惯）；Space/
        Shift = 世界升降；速度由滚轮调节。位移按真实 interval 换算
        dt（speed 格/秒 × interval/1000），高刷屏 tick 更频但
        每步更短，速度手感不随刷新率变化。无键时停 tick 只留心跳。
        """
        if not self._sp_mode:
            self._sp_tick.stop()
            return
        # 水平前向 = _sp_dir 去俯仰归一化 = (-cos yaw, 0, -sin yaw)，
        # 与 orbit 相机视线基一致（W = 朝画面里走）；右向 = fw × up
        # （d(forward)/d(yaw) = (sin,0,-cos)，yaw 增大视线向右转）
        s = math.radians(self._yaw)
        fw = QVector3D(-math.cos(s), 0.0, -math.sin(s))
        rt = QVector3D(math.sin(s), 0.0, -math.cos(s))
        mv = QVector3D(0, 0, 0)
        K = self
        if K._SP_K_W in self._sp_keys or K._SP_K_UP in self._sp_keys:
            mv += fw
        if K._SP_K_S in self._sp_keys or K._SP_K_DOWN in self._sp_keys:
            mv -= fw
        if K._SP_K_A in self._sp_keys or K._SP_K_LEFT in self._sp_keys:
            mv -= rt
        if K._SP_K_D in self._sp_keys or K._SP_K_RIGHT in self._sp_keys:
            mv += rt
        if K._SP_K_SPACE in self._sp_keys:
            mv += QVector3D(0, 1, 0)
        if K._SP_K_SHIFT in self._sp_keys:
            mv -= QVector3D(0, 1, 0)
        if mv.lengthSquared() > 1e-10:
            self._sp_eye += mv.normalized() * self._sp_speed \
                * (self._sp_tick.interval() / 1000.0)
            self._spectator_update_crosshair()
            self.update()
        if not self._sp_keys:
            self._sp_tick.stop()

    def _spectator_idle_check(self) -> None:
        """低频心跳：全松/光标出窗/失焦 → 松键；确保 tick 已停。"""
        if not self._sp_mode:
            self._sp_idle.stop()
            return
        if self._sp_grabbed and not self.underMouse():
            self._spectator_release_mouse()
        if not self._sp_keys:
            self._sp_idle.stop()

    def _sp_dir(self) -> QVector3D:
        """旁观者视线方向单位向量（yaw/pitch -> 前向）。"""
        yr, pr = math.radians(self._yaw), math.radians(self._pitch)
        return QVector3D(-math.cos(yr) * math.cos(pr), math.sin(pr),
                         -math.sin(yr) * math.cos(pr))

# ==== PART2 ====

    def _spectator_toggle_grab(self) -> None:
        """` 键：锁定/呼出鼠标切换。"""
        if self._sp_grabbed:
            self._spectator_release_mouse()
        else:
            self._spectator_grab_mouse()

    def _spectator_grab_mouse(self) -> None:
        """锁定鼠标：真回中捕获（FPS 相机标准做法）。

        启动按屏幕刷新率的钉扎定时器：把光标钉在视口正中心并
        隐藏；转视角按「光标相对中心的位移」计算后立即拉回中心，
        光标物理上出不了窗口，不按任何键纯滑动即可持续转视角。
        """
        if not self._sp_mode:
            return
        self._spectator_recenter(reset_base=True)
        self.setCursor(Qt.CursorShape.BlankCursor)
        self._sp_grabbed = True
        if not self._sp_pin.isActive():
            self._sp_pin.start()

    def _spectator_release_mouse(self) -> None:
        """呼出鼠标：恢复箭头光标并停钉扎。"""
        self._sp_grabbed = False
        self._sp_last_ev_pos = None
        self._sp_pin.stop()
        self.unsetCursor()

    def _spectator_center(self) -> QPoint:
        return QPoint(self.width() // 2, self.height() // 2)

    def _draw_crosshair(self, p: QPainter) -> None:
        """开箱准星：屏幕中心十字（同游戏）。

        双层绘制（黑描边 + 白芯）走普通 SourceOver：
        CompositionMode_Difference 在 GL 绘制引擎上的支持随驱动/
        帧缓冲格式有差异，失效时白线在雪/沙等浅色方块上不可见；
        描边方案任何背景都可见。用 fillRect 逐像素精确控制——
        drawLine 在 1px/3px 笔宽 + FlatCap 下端点光栅化有歧义
        （实测臂端缺 1px、左右不对称）。几何：臂从 ±G 到 ±L
        （含端点），描边横跨 ±1 行/列，中心 (2G-1)² 空隙。
        抽独立方法：paintGL 才执行的代码 offscreen 测试够不着，
        用 QImage 画布直接测本方法。
        """
        if not (self._sp_mode and self._sp_crosshair_idx >= 0):
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        c = self._spectator_center()
        cx_c, cy_c = c.x(), c.y()
        L, G = 7, 2                    # 臂长 / 空隙半径（像素）
        blk = QColor(0, 0, 0, 180)     # 描边（3px 带宽）
        wht = QColor(255, 255, 255)    # 白芯（1px）
        arm = L - G + 1                # 每侧臂像素数
        # 横臂（黑带 y±1，白芯中行）
        p.fillRect(cx_c - L, cy_c - 1, arm, 3, blk)
        p.fillRect(cx_c + G, cy_c - 1, arm, 3, blk)
        p.fillRect(cx_c - L, cy_c, arm, 1, wht)
        p.fillRect(cx_c + G, cy_c, arm, 1, wht)
        # 竖臂（黑带 x±1，白芯中列）
        p.fillRect(cx_c - 1, cy_c - L, 3, arm, blk)
        p.fillRect(cx_c - 1, cy_c + G, 3, arm, blk)
        p.fillRect(cx_c, cy_c - L, 1, arm, wht)
        p.fillRect(cx_c, cy_c + G, 1, arm, wht)

    def _spectator_update_crosshair(self) -> None:
        """按眼睛位置/视线重判开箱准星命中（在 tick/转视角后调用）。

        命中 = 准星射线与箱子方块 AABB 相交（slab 法，游戏同款
        「指哪打哪」，不能指向箱间空气也命中），沿视线取最近者；
        进入距离 ≤ _SP_CHEST_DIST；命中索引变化时重绘（准星显隐）。
        """
        idx = -1
        if self._sp_mode and self._interact_chests and self._sp_eye:
            fw = self._sp_dir()
            o = self._sp_eye
            best_t = None
            for i, (cx, cy, cz) in enumerate(self._interact_chests):
                # slab 法：射线 vs AABB [c, c+1)^3，三轴区间求交；
                # t1 初值即最大开箱距离，眼睛在盒内时 t0=0 也算命中
                t0, t1 = 0.0, _SP_CHEST_DIST
                hit = True
                for org, d, lo in ((o.x(), fw.x(), cx),
                                   (o.y(), fw.y(), cy),
                                   (o.z(), fw.z(), cz)):
                    if abs(d) < 1e-9:
                        if org <= lo or org >= lo + 1.0:
                            hit = False
                            break
                    else:
                        ta = (lo - org) / d
                        tb = (lo + 1.0 - org) / d
                        if ta > tb:
                            ta, tb = tb, ta
                        if ta > t0:
                            t0 = ta
                        if tb < t1:
                            t1 = tb
                        if t0 > t1:
                            hit = False
                            break
                if hit and t0 <= t1:
                    if best_t is None or t0 < best_t:
                        best_t = t0
                        idx = i
        if idx != self._sp_crosshair_idx:
            self._sp_crosshair_idx = idx
            self.update()

    def _spectator_recenter(self, reset_base: bool = False) -> None:
        """把真实光标钉回视口正中心（全局坐标）。

        reset_base=True 时同时重置位移基准（grab 时防吃掉进入
        前的一次大幅移动）。
        """
        c = self._spectator_center()
        g = self.mapToGlobal(c)
        if reset_base or self._sp_last_ev_pos is None:
            self._sp_last_ev_pos = g
        cur = QCursor.pos()
        if cur != g:
            QCursor.setPos(g)

    def _spectator_pin_tick(self) -> None:
        """锁定期钉扎：直读全局光标位移转视角后钉回中心。

        与事件流解耦：即便 mouseMove 被系统合并/延迟，钉扎仍按
        屏幕刷新率拉回中心，转视角不受事件到达影响。
        """
        if not self._sp_grabbed or not self._sp_mode:
            self._sp_pin.stop()
            self._sp_last_ev_pos = None
            return
        g = QCursor.pos()
        base = self._sp_last_ev_pos
        if base is not None and g != base:
            d = g - base
            spd = self._sp_mouse_speed
            # FPS 语义：鼠标右移视线右转（yaw 增）、右移 pitch 减；
            # 上下同理（下移低头，pitch 减）
            self._yaw = (self._yaw + d.x() * spd) % 360.0
            self._pitch = max(-_SP_PITCH_MAX,
                              min(_SP_PITCH_MAX,
                                  self._pitch - d.y() * spd))
            self._spectator_update_crosshair()
            self.update()
        self._spectator_recenter(reset_base=True)

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if self._sp_mode:
            if self._sp_input_locked:  # 开箱 GUI 期间：不抢焦点不控制
                ev.accept()
                return
            self.setFocus()
            if ev.button() == Qt.MouseButton.RightButton \
                    and self._sp_crosshair_idx >= 0:
                # 准星态右键：开箱（呼出鼠标给 GUI；若原本锁定，
                # GUI 关闭后恢复锁定继续飞行）
                idx = self._sp_crosshair_idx
                self._sp_resume_grab = self._sp_grabbed
                self._spectator_release_mouse()
                self._sp_keys.clear()
                self.chest_open_requested.emit(idx)
                ev.accept()
                return
            if not self._sp_grabbed:
                # 未控制态点击：开始控制视角（回中捕获鼠标）
                self._spectator_grab_mouse()
            ev.accept()
            return
        self._last_pos = ev.position().toPoint()
        if ev.button() == Qt.MouseButton.RightButton:
            # 旋转光标：北↑西← 双箭头随视角旋转，直观提示拖拽方向
            self.setCursor(self._orbit_cursor())
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        if self._sp_mode:
            ev.accept()
            return

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        if self._sp_mode:
            # 转视角由钉扎 tick 直读光标驱动（不依赖事件流）；
            # 这里只兜底刷新一次基准点（首次移动事件可能先于
            # 定时器到点）并吞掉事件
            if self._sp_grabbed and self._sp_last_ev_pos is None:
                self._spectator_recenter(reset_base=True)
            ev.accept()
            return
        if self._last_pos is None:
            return
        pos = ev.position().toPoint()
        d = pos - self._last_pos
        self._last_pos = pos
        if ev.buttons() & Qt.MouseButton.RightButton:
            self._orbit(d.x() * 0.4, d.y() * 0.4)
            # 视角变了：旋转光标同步跟随（北/西臂指向实时朝向）
            if self.cursor().shape() == Qt.CursorShape.BitmapCursor:
                self.setCursor(self._orbit_cursor())
        elif ev.buttons() & Qt.MouseButton.LeftButton:
            self._pan_screen(d)
        self._pause_rotation()           # 拖动中：停轮播 + 续期空闲计时
        self.update()

    def wheelEvent(self, ev) -> None:
        if self._sp_mode:
            if self._sp_input_locked:  # 开箱 GUI 期间：不调速
                ev.accept()
                return
            steps = ev.angleDelta().y() / 120.0
            if steps:
                self._sp_speed = max(_SP_FLY_MIN, min(
                    _SP_FLY_MAX, self._sp_speed * _SP_WHEEL_STEP ** steps))
                self._sp_speed_until_ms = (time.monotonic_ns()
                                           // 1_000_000) + _SP_FLASH_MS
            ev.accept()
            self.update()
            return
        steps = ev.angleDelta().y() / 120.0
        if steps:
            base = self._dist if self._dist else self._radius * 2.2
            self._dist = max(self._radius * 0.6,
                             min(self._radius * 6.0, base * 0.87 ** steps))
        self._pause_rotation()           # 缩放同样暂停轮播 + 续期
        self.update()

    def hideEvent(self, ev) -> None:  # noqa: N802
        # 视口不可见时暂停轮播并撤销交互暂停态（后台空转浪费且
        # 切换无意义；重显时 showEvent 直接恢复轮播）；旁观者模式
        # 同步还原鼠标（tab 切走时不留隐藏光标）
        self._stop_spin_timers()
        if self._sp_mode:
            self._spectator_release_mouse()
            self._sp_keys.clear()
        super().hideEvent(ev)

    # ------------------------------------------------------------------
    # GL 生命周期
    # ------------------------------------------------------------------
    def initializeGL(self) -> None:  # noqa: N802
        self._glf = self.context().functions()
        # PySide6 6.11 的 QOpenGLFunctions.glDrawElements 包装在
        # "IBO + c_void_p 偏移"形态下静默不画（llvmpipe 上 A/B 实证，
        # .temp/result_probe_z4_*.out）：包装器 0%，原生指针 10.33%。
        # 纯 int 形态又被 ValueError 拒收 -> 必须 getProcAddress 解析
        # 原生函数指针。
        import ctypes as _ct
        _addr = self.context().getProcAddress(b"glDrawElements")
        _proto = _ct.CFUNCTYPE(None, _ct.c_uint, _ct.c_int, _ct.c_uint,
                               _ct.c_void_p)
        self._native_glDrawElements = _proto(int(_addr))
        self._shader = QOpenGLShaderProgram()
        self._shader.addShaderFromSourceCode(
            QOpenGLShader.ShaderTypeBit.Vertex, _VS)
        self._shader.addShaderFromSourceCode(
            QOpenGLShader.ShaderTypeBit.Fragment, _FS)
        self._shader.bindAttributeLocation("aPos", 0)
        self._shader.bindAttributeLocation("aUV", 1)
        self._shader.bindAttributeLocation("aNor", 2)
        self._shader.bindAttributeLocation("aTile", 3)   # 显式绑定：不绑则由驱动分配（实测 NVIDIA 顺序分配到 3，但不保证），环境变化会让 _upload_model 的硬编码 index 3 错位
        self._shader.link()
        # 水第二遍着色器：顶点同 _VS，片元输出半透明
        self._wshader = QOpenGLShaderProgram()
        self._wshader.addShaderFromSourceCode(
            QOpenGLShader.ShaderTypeBit.Vertex, _VS)
        self._wshader.addShaderFromSourceCode(
            QOpenGLShader.ShaderTypeBit.Fragment, _FS_WATER)
        self._wshader.bindAttributeLocation("aPos", 0)
        self._wshader.bindAttributeLocation("aUV", 1)
        self._wshader.bindAttributeLocation("aNor", 2)
        self._wshader.bindAttributeLocation("aTile", 3)
        self._wshader.link()
        self._vao = QOpenGLVertexArrayObject()
        self._vao.create()
        self._vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self._vbo.create()
        self._ibo = QOpenGLBuffer(QOpenGLBuffer.Type.IndexBuffer)
        self._ibo.create()
        # 锚点线框专用简易着色器 + VBO（同样用桌面 GLSL 1.20）
        self._plain = QOpenGLShaderProgram()
        self._plain.addShaderFromSourceCode(
            QOpenGLShader.ShaderTypeBit.Vertex,
            "#version 120\n"
            "attribute vec3 aPos; uniform mat4 uMVP;"
            "void main(){ gl_Position = uMVP * vec4(aPos,1.0); }")
        self._plain.addShaderFromSourceCode(
            QOpenGLShader.ShaderTypeBit.Fragment,
            "#version 120\n"
            "uniform vec4 uColor;"
            "void main(){ gl_FragColor = uColor; }")
        self._plain.bindAttributeLocation("aPos", 0)
        self._plain.link()
        self._anchor_vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self._anchor_vbo.create()
        self._chunk_vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self._chunk_vbo.create()
        # 纹理图集
        atlas_img, self._atlas_slots = _build_atlas()
        self._qtex = QOpenGLTexture(atlas_img)
        self._qtex.setMinMagFilters(QOpenGLTexture.Filter.Nearest,
                                    QOpenGLTexture.Filter.Nearest)
        self._qtex.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
        self._qtex.create()
        # uniform 定位缓存：PySide6 6.11 绑定实测（.temp/result_uniform_probe.out）：
        # 名字形态仅 str + 矩阵/向量/QColor/int 可用，str/bytes + float
        # 均无匹配重载；location + 任意类型全可用 -> 统一走 location。
        self._shader.bind()
        self._u = {n: self._shader.uniformLocation(n)
                   for n in ("uMVP", "uModel", "uAtlas", "uLightDir",
                             "uSlotOrigin")}
        # 静态渲染状态 + 静态 uniform 一次设置（paintGL 不再每帧
        # 重复）：深度测试/背向剔除（面绕序 = 面法线朝外，_FACES
        # 与 _box_face 绕序一致）/混合/清屏色，uModel 恒单位阵，
        # 光照方向固定。QOpenGLWidget 每帧自动重新绑定上下文
        # VAO=0，enable 状态驻留安全（无 QOpenGLVertexArrayObject
        # 残留 enable0 干扰）。
        glf = self._glf
        glf.glEnable(0x0B71)                 # GL_DEPTH_TEST
        glf.glEnable(0x0BE2)                 # GL_BLEND
        glf.glEnable(0x0BC5)                 # GL_CULL_FACE（背面裁剪）
        # 标准预乘式混合：src*SRC_ALPHA + dst*(1-src_alpha)
        # 注意 0x0306 是 GL_DST_COLOR，不是 GL_SRC_ALPHA(0x0302)——
        # 写成 (0x0306,0x0303) 会让输出乘背景色系统性变暗(0.17x)
        glf.glBlendFunc(0x0302, 0x0303)
        bg = QColor(0x2B, 0x2F, 0x36)
        glf.glClearColor(bg.redF(), bg.greenF(), bg.blueF(), 1.0)
        self._shader.setUniformValue(self._u["uModel"], QMatrix4x4())
        self._shader.setUniformValue(
            self._u["uLightDir"], QVector3D(-0.45, 0.85, 0.28))
        self._shader.release()
        self._wshader.bind()
        self._wu = {n: self._wshader.uniformLocation(n)
                    for n in ("uMVP", "uModel", "uAtlas", "uLightDir",
                              "uSlotOrigin")}
        self._wshader.setUniformValue(self._wu["uModel"], QMatrix4x4())
        self._wshader.setUniformValue(
            self._wu["uLightDir"], QVector3D(-0.45, 0.85, 0.28))
        self._wshader.release()
        self._plain.bind()
        self._pu = {n: self._plain.uniformLocation(n)
                    for n in ("uMVP", "uColor")}
        self._plain.release()
        self._gl_ready = True
        if self._model:
            self._needs_upload = True

    def _upload_model(self) -> None:
        """网格 -> VBO/IBO；材质槽 -> 图集槽号表；锚点/区块/方位线 -> VBO。

        必须在 GL 上下文内调用（paintGL 开头或 initializeGL）。
        """
        self._needs_upload = False
        if not self._model:
            return
        mesh = self._model["mesh"]
        self._slot_of_mat = {}
        for i, m in enumerate(mesh["slot_mat"]):
            base = m[len("halfheight:"):] if m.startswith("halfheight:") \
                else m
            self._slot_of_mat[i] = self._atlas_slots.get(
                base, self._atlas_slots.get("__unknown__", 0))
        # 水第二遍数据（build_mesh 已把水面分离到索引尾部）
        self._water_off = mesh.get("water_off", 0)
        self._water_count = mesh.get("water_count", 0)
        self._water_slot = self._atlas_slots.get("water", 0)
        # 顶点重排 8→10 列：图集槽原点烘焙进 aTile（上传期一次性
        # numpy 向量化），绘制期不再逐槽设 uSlotOrigin；quad_slot
        # 主路径（build_mesh 直接给出 quad→槽号表，空槽天然跳过）
        vdata = _bake_tile_origin(mesh["verts"], mesh["slots"],
                                  mesh["slot_mat"], self._atlas_slots,
                                  idx=mesh["idx"],
                                  quad_slot=mesh.get("quad_slot"))
        # chunk 空间重排数据（MC 式视锥剔除）：无则整体单 draw
        self._chunks = mesh.get("chunks") or []
        # numpy 矩阵化：draw 期向量化视锥判定（避免逐 chunk Python 循环）
        self._chunk_arr = (np.asarray(self._chunks, dtype=np.float64)
                           if self._chunks else None)
        # 逐 section 可见性矩阵（MC 洞穴剔除构建期同款）：眼 section
        # BFS 传播用；无数据 = None 走纯视锥
        self._occl = mesh.get("occl") or None
        self._occl_cache_key = None
        self._occl_cache_cells = None
        # 阻挡格集合：与 build_occlusion 同一判据（实心整格且
        # 非透明；异形/透明不挡视线，游戏 isSolidRender 同款）
        self._occl_opaque = set()
        if self._occl:
            for p, v in self._model["voxels"].items():
                mat, shape = sm._mat_shape(v)
                if not shape and mat not in sm._TRANSPARENT_MATS:
                    self._occl_opaque.add(p)
        # 每次上传销毁重建缓冲：同一 buffer 重复 allocate/重指定
        # 属性指针在 NVIDIA 驱动下触发 0xC0000409（事件日志定位）
        for obj in (self._vao, self._vbo, self._ibo, self._anchor_vbo,
                    self._chunk_vbo):
            if obj is not None and obj.isCreated():
                obj.destroy()
        self._vao = QOpenGLVertexArrayObject()
        self._vao.create()
        self._vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self._vbo.create()
        self._ibo = QOpenGLBuffer(QOpenGLBuffer.Type.IndexBuffer)
        self._ibo.create()
        self._anchor_vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self._anchor_vbo.create()
        self._chunk_vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self._chunk_vbo.create()
        self._vao.bind()
        self._vbo.bind()
        # build_mesh 已输出 numpy 数组：tobytes() 一次成型直传
        #（旧路径 struct.pack 逐元素 12 万顶点要 20+ms）；
        # vdata 已在上方重排为 10 列（aTile 烘焙）；bytes 兜底
        # 保持低层注入模型的旧格式兼容。
        buf = vdata.tobytes() if hasattr(vdata, "tobytes") \
            else struct.pack(f"<{len(vdata)}f", *vdata)
        self._vbo.allocate(buf, len(buf))
        self._ibo.bind()
        idx = mesh["idx"]
        if (idx.size == 0 if hasattr(idx, "size") else not idx):
            # 空网格：线框/网格数据一并清空（VBO 已重建为空，
            # 残留旧顶点数会让 glDrawArrays 读空缓冲）
            self._anchor_verts = None
            self._chunk_verts = None
            self._water_count = 0
            self._chunks = []
            self._chunk_arr = None
            self._vao.release()
            self._vbo.release()
            self._ibo.release()
            return
        if hasattr(idx, "dtype"):
            # numpy 索引：build_mesh 已按值域定型 uint16/uint32，
            # 直接 tobytes 直传（dtype 决定 GL 类型，勿再判 max）
            if idx.dtype == np.uint16:
                self._idx_type = 0x1403            # GL_UNSIGNED_SHORT
            else:
                self._idx_type = 0x1405            # GL_UNSIGNED_INT
            self._idx_itemsize = 2 if self._idx_type == 0x1403 else 4
            self._ibo.allocate(idx.tobytes(), idx.size * idx.itemsize)
        else:
            # list 兜底（低层注入旧格式）：按值域选类型打包
            if max(idx) < 65536:
                self._idx_type = 0x1403            # GL_UNSIGNED_SHORT
                self._idx_itemsize = 2
                self._ibo.allocate(struct.pack(f"<{len(idx)}H", *idx),
                                   len(idx) * 2)
            else:
                self._idx_type = 0x1405            # GL_UNSIGNED_INT
                self._idx_itemsize = 4
                self._ibo.allocate(struct.pack(f"<{len(idx)}I", *idx),
                                   len(idx) * 4)
        # 属性指针：用 QOpenGLShaderProgram.setAttributeBuffer
        # （glVertexAttribPointer 的 PySide6 绑定不接受裸 int 偏移）
        # stride 10 列 40 字节：aPos/aUV/aNor/aTile
        self._vao.bind()
        self._vbo.bind()
        self._shader.bind()
        stride = 10 * 4
        self._shader.enableAttributeArray(0)
        self._shader.setAttributeBuffer(0, 0x1406, 0, 3, stride)
        self._shader.enableAttributeArray(1)
        self._shader.setAttributeBuffer(1, 0x1406, 12, 2, stride)
        self._shader.enableAttributeArray(2)
        self._shader.setAttributeBuffer(2, 0x1406, 20, 3, stride)
        self._shader.enableAttributeArray(3)
        self._shader.setAttributeBuffer(3, 0x1406, 32, 2, stride)
        self._shader.release()
        self._vao.release()
        self._vbo.release()
        self._ibo.release()
        # 锚点位置：monument = 结构中心（ANCHOR_CENTER_KEYS）；
        # ANCHOR_OFFSETS 键 = 模型局部坐标偏移（village 水井 /
        # trial_chambers 入口两水池，用户 GUI 对照校准）；
        # 缺省 = 包围盒西北角 (0,0)。
        w, d, _h = self._model["size"]
        ov_anchor = self._model.get("anchor_local")
        ov_chunk = self._model.get("chunk_origin")
        if self._key in sm.ANCHOR_CENTER_KEYS:
            ax, az = w / 2.0, d / 2.0
        elif self._key in sm.ANCHOR_OFFSETS:
            ax, az = sm.ANCHOR_OFFSETS[self._key]
        elif ov_anchor is not None:
            ax, az = ov_anchor            # 低层注入：模型内显式锚点
        else:
            ax = az = 0.0
        # 区块边界方框：只画结构足迹覆盖的区块格（用户需求：结构之外
        # 的网格长线全部省略）。每格输出 16×16 完整矩形，相邻格共享
        # 边由 _seen 键去重（同一条边只入一次 VBO）。
        # 世界对齐：结构锚点=其所在区块的西北角（cubiomes 语义，
        # 视口局部坐标 x/z = 世界坐标 mod 16 的平移原点），
        # 故区块边界 = x≡gx0, z≡gz0 (mod 16)；网格原点随锚点平移：
        # 中心锚点结构（monument）取 (w/2, d/2) mod 16，偏移锚点结构
        # 取偏移量 mod 16，其余 = (0,0)。
        # y 取 min_y-0.02 贴地微降避免与模型底面 z-fighting。
        if self._key in sm.ANCHOR_CENTER_KEYS:
            gx0 = (w / 2.0) % 16.0
            gz0 = (d / 2.0) % 16.0
        elif self._key in sm.ANCHOR_OFFSETS:
            gx0 = sm.ANCHOR_OFFSETS[self._key][0] % 16.0
            gz0 = sm.ANCHOR_OFFSETS[self._key][1] % 16.0
        elif ov_chunk is not None:
            gx0, gz0 = float(ov_chunk[0]), float(ov_chunk[1])
        else:
            gx0 = gz0 = 0.0
        y0 = float(min((yy for (_x, yy, _z) in self._model["voxels"]),
                       default=-1) - 0.02)
        cx0i = int((0.0 - gx0) // 16.0)       # 首个边界 <= 0 的列索引
        cx1i = int((w - 1 - gx0) // 16.0)     # 末块所在区块列索引
        cz0i = int((0.0 - gz0) // 16.0)
        cz1i = int((d - 1 - gz0) // 16.0)
        _seen = set()
        cv = []

        def _edge(x1, z1, x2, z2):
            k = (round(x1, 4), round(z1, 4), round(x2, 4), round(z2, 4))
            if k not in _seen:                # 相邻格共享边只画一次
                _seen.add(k)
                cv.extend([x1, y0, z1, x2, y0, z2])

        for cz in range(cz0i, cz1i + 1):
            bz0 = gz0 + 16.0 * cz
            for cx in range(cx0i, cx1i + 1):
                bx0 = gx0 + 16.0 * cx
                _edge(bx0, bz0, bx0, bz0 + 16.0)              # 西边
                _edge(bx0 + 16.0, bz0, bx0 + 16.0, bz0 + 16.0)  # 东边
                _edge(bx0, bz0, bx0 + 16.0, bz0)              # 北边
                _edge(bx0, bz0 + 16.0, bx0 + 16.0, bz0 + 16.0)  # 南边
        self._chunk_verts = cv or None
        # 锚点：无限延伸红色竖直线（穿过整模型高度，上下露出）
        # + 地面十字标出精确点
        yb = float(min((yy for (_x, yy, _z) in self._model["voxels"]),
                       default=-1))
        ext = max(w, d, float(_h)) * 8.0 + 64.0
        v = [ax, yb - ext, az, ax, yb + ext, az]
        v += [ax - 1.0, yb - 0.01, az, ax + 1.0, yb - 0.01, az]
        v += [ax, yb - 0.01, az - 1.0, ax, yb - 0.01, az + 1.0]
        self._anchor_verts = v
        for vbo, verts in ((self._anchor_vbo, v), (self._chunk_vbo, cv)):
            vbo.bind()
            vbo.allocate(struct.pack(f"<{len(verts)}f", *verts),
                         len(verts) * 4)
            vbo.release()
    def _occl_cells_for_eye(self) -> set | None:
        """旁观模式眼语义（MC 洞穴剔除运行期同款）-> 允许 chunk 序号集。

        移植自 1.21.11 反编译源码 SectionOcclusionGraph.runUpdates：
        - 眼在实心整格：None（LevelRenderer.cullTerrain 同款——
          isSolidRender 时 smartCull=false，洞穴剔除整体关闭，
          全量渲染 = 游戏进方块内部可看到外部）；
        - 眼在空气格：从眼 section 出发做 section 级 BFS 传播。
          眼 section 无条件可见且 6 方向传播（源码 initializeQueue
          种子无 sourceDirection -> 跳过 facesCanSeeEachother 检查）；
          后续传播到方向 e 的邻居 N 时，要求存在来向 d 使当前
          section 的矩阵 facesCanSeeEachother(d.opposite, e)——
          即光能经本 section 空域从进光面透到出光面（门窗空域
          自然连通，房间内可看到窗外）。
        - 结果按眼 section 缓存（游戏相机跨 8 格才 invalidate，
          视口内眼不跨 section 时传播结果不变）。

        返回 set[chunk 序号]（空集=眼 section 周围全被堵死）。
        """
        o = self._occl
        ex = int(math.floor(self._sp_eye.x()))
        ey = int(math.floor(self._sp_eye.y()))
        ez = int(math.floor(self._sp_eye.z()))
        bx0, by0, bz0, bx1, by1, bz1 = o["bounds"]
        if not (bx0 <= ex <= bx1 and by0 <= ey <= by1
                and bz0 <= ez <= bz1):
            return None
        sections: dict = o["sections"]
        if (ex, ey, ez) in self._occl_opaque:
            # 实心整格：smartCull=false（游戏同款，全渲染）；
            # 空气/透明格不在此集合，走下方 BFS 传播
            return None
        # 眼所在 section（16³ 键与体素键同系）
        esx, esy, esz = ex // 16, ey // 16, ez // 16
        cache_key = (esx, esy, esz)
        if self._occl_cache_key == cache_key:
            return self._occl_cache_cells
        # ---- BFS 传播（runUpdates 移植；方向原版序：
        # 0=-Y 1=+Y 2=-Z 3=+Z 4=-X 5=+X）----
        D6 = ((0, -1, 0), (0, 1, 0), (0, 0, -1), (0, 0, 1),
              (-1, 0, 0), (1, 0, 0))          # ordinal 对应位移
        OPP = (1, 0, 3, 2, 5, 4)              # getOpposite()
        # node: section -> (sourceDirections, directions)
        nodes: dict = {}
        seed = (esx, esy, esz)
        nodes[seed] = (0, 0)                  # 种子无 sourceDirection
        # directions：种子初始为空集？源码 Node(section,null,0) 后
        # runUpdates 里遍历 6 方向时 hasDirection 用于 advanced
        # 射线检查（本实现无高级模式，不参与）；传播条件只用
        # sourceDirections。directions 仅记录到达方向供调试。
        queue = [seed]
        while queue:
            cur = queue.pop(0)
            srcs, _dirs = nodes[cur]
            csx, csy, csz = cur
            mat = sections.get(cur, (1 << 36) - 1)
            for e in range(6):
                dx, dy, dz = D6[e]
                nb = (csx + dx, csy + dy, csz + dz)
                # 模型 AABB 相交的 section 才参与（游戏为已加载
                # section：initializeQueueForFullUpdate 只向存在
                # bundle 的邻居传播，未加载=阻断）。预览中界外=未
                # 加载；凸性保证可见视线不越出模型 AABB，界外
                # section 对可见性无贡献——若放行（旧 bx1+15 写法
                # 等于界外=全通空气），BFS 会沿界外空 section
                # 「高速路」绕过实心 section，密封房间剔除失效
                # （视线管探针实测：堵管 (2,0,0) 仍可达）。
                nx, ny, nz = nb[0] * 16, nb[1] * 16, nb[2] * 16
                if (nx > bx1 or nx + 15 < bx0 or ny > by1
                        or ny + 15 < by0 or nz > bz1 or nz + 15 < bz0):
                    continue
                if nb in nodes:
                    nodes[nb] = (nodes[nb][0] | (1 << e),
                                 nodes[nb][1] | (1 << e))
                    continue
                # 传播条件（advanced 无射线版）：存在来向 d 使
                # facesCanSeeEachother(d.opposite, e)。种子 srcs=0
                # -> 条件恒真（源码同款：hasSourceDirections 为假
                # 跳过检查）
                ok = srcs == 0
                if not ok:
                    d = 0
                    s = srcs
                    while s and not ok:
                        if s & 1:
                            # facesCanSeeEachother(d.opposite, e)：
                            # bit = from.ordinal + to.ordinal * 6
                            ok = ((mat >> (OPP[d] + 6 * e)) & 1) != 0
                        s >>= 1
                        d += 1
                if not ok:
                    continue
                nodes[nb] = (1 << e, 1 << e)
                queue.append(nb)
        # 可见 section 集 -> chunk 序号集（含眼 section 本身）
        vis_secs = set(nodes.keys())
        cells: set = set()
        ca = o["chunk_at"]
        for (sx, sy, sz) in vis_secs:
            ci = ca.get((sx, sy, sz))
            if ci is not None:
                cells.add(ci)
        self._occl_cache_key = cache_key
        self._occl_cache_cells = cells
        return cells

    def _draw_model_body(self, mvp: QMatrix4x4,
                         occl_cells: set | None = None) -> None:
        """模型主体：逐 chunk 视锥剔除绘制（GL 上下文内调用）。

        图集槽原点已烘焙进顶点 aTile（_upload_model），运行时
        无逐槽 uniform；uModel/uLightDir 状态驻留（initializeGL
        绑定后不再每帧写）。

        chunk 剔除（MC 式）：build_mesh 已把主体索引按 16³ 立方
        重排并输出每 chunk 索引区间 + AABB；本帧对每 chunk 做
        6 平面 p-vertex 判（MVP 行向量组合，GPU 管线同款判定），
        视锥外的 chunk 整段不提交。FS 有 alpha discard（树叶/
        玻璃等），early-z 不可用，被剔 chunk 同时省下顶点与
        填充两头的浪费。无 chunk 数据（旧 mesh/低层注入）回退
        单次全量 draw。

        occl_cells（旁观模式眼语义，MC 洞穴剔除同款）：眼格
        预解析出的允许 chunk 序号集合；与视锥判定结果取交集
        后提交。None = 不启用（orbit 模式/无 occl 数据）。
        注：近→远排序绘制已在真窗口 A/B 实测（probe_sort_ab）：
        discard 禁用 early-z 后近→远不省填充，热身后无收益
        甚至略亏，不采用。
        """
        self._shader.bind()
        self._shader.setUniformValue(self._u["uMVP"], mvp)
        self._qtex.bind(0)
        self._shader.setUniformValue(self._u["uAtlas"], 0)
        self._vao.bind()
        if self._chunks:
            # 6 视锥平面 = MVP 行向量组合（p_clip = M·p 语义）：
            # x+w≥0, w-x≥0, y+w≥0, w-y≥0, z+w≥0, w-z≥0
            # 全部 chunk 一次性向量化判定（每帧 6×N 次点积，
            # numpy 比 Python 双层循环快两个数量级）
            ch = self._chunk_arr
            row0 = mvp.row(0)
            row1 = mvp.row(1)
            row2 = mvp.row(2)
            row3 = mvp.row(3)
            r0x, r0y, r0z, r0w = row0.x(), row0.y(), row0.z(), row0.w()
            r1x, r1y, r1z, r1w = row1.x(), row1.y(), row1.z(), row1.w()
            r2x, r2y, r2z, r2w = row2.x(), row2.y(), row2.z(), row2.w()
            r3x, r3y, r3z, r3w = row3.x(), row3.y(), row3.z(), row3.w()
            planes = (
                (r0x + r3x, r0y + r3y, r0z + r3z, r0w + r3w),
                (r3x - r0x, r3y - r0y, r3z - r0z, r3w - r0w),
                (r1x + r3x, r1y + r3y, r1z + r3z, r1w + r3w),
                (r3x - r1x, r3y - r1y, r3z - r1z, r3w - r1w),
                (r2x + r3x, r2y + r3y, r2z + r3z, r2w + r3w),
                (r3x - r2x, r3y - r2y, r3z - r2z, r3w - r2w))
            mn = ch[:, 2:5]
            mx = ch[:, 5:8]
            visible = np.ones(len(ch), dtype=bool)
            for (a, b, c, d) in planes:
                px = np.where(a > 0.0, mx[:, 0], mn[:, 0])
                py = np.where(b > 0.0, mx[:, 1], mn[:, 1])
                pz = np.where(c > 0.0, mx[:, 2], mn[:, 2])
                visible &= (a * px + b * py + c * pz + d) >= 0.0
            vis_idx = np.nonzero(visible)[0]
            if occl_cells is not None:
                # 遮挡连通域交集：域可达 chunk 集 ∩ 视锥内 chunk。
                # 眼 section 周围全连通（cells == 全部 chunk）时
                # 跳过过滤（np.isin 对满集是纯开销）；cells 为空集
                # 时全剔（罕见：眼 section 被完全封死）
                if not occl_cells:
                    vis_idx = vis_idx[:0]
                elif len(occl_cells) < len(self._chunks):
                    vis_idx = vis_idx[np.isin(
                        vis_idx,
                        np.fromiter(occl_cells, np.int64))]
            if vis_idx.size:
                # 连续可见 chunk 合并成一段 draw（区间首尾相接；
                # 全景大部分可见时 = 1 次 draw，贴脸时也仅几段），
                # draw call 数 = 可见段数而非 chunk 数
                offs = ch[vis_idx, 0]
                cnts = ch[vis_idx, 1]
                seg_start = np.concatenate(([0], np.nonzero(
                    np.diff(vis_idx) > 1)[0] + 1))
                seg_end = np.concatenate((seg_start[1:], [len(vis_idx)]))
                for s, e in zip(seg_start, seg_end):
                    self._native_glDrawElements(
                        0x0004, int(cnts[s:e].sum()), self._idx_type,
                        _VOIDP(int(offs[s]) * self._idx_itemsize))
        else:
            # 全部不透明索引一次画完（水区间在索引尾部，单独排除）
            total = self._water_off if self._water_count \
                else _seq_len(self._model["mesh"]["idx"])
            self._native_glDrawElements(0x0004, total, self._idx_type,
                                        _VOIDP(0))
        self._vao.release()
        self._shader.release()

    def _draw_guide_lines(self, mvp: QMatrix4x4) -> None:
        """线框层：区块黄框 + 锚点红线。

        不受渲染开关影响（开关只隐藏模型主体与水）：锚点/区块
        是逆推核心信息，未渲染时也应可读。
        """
        glf = self._glf
        # ---- 区块边界线（模型之下，先画让深度测试自然裁剪） ----
        if self._chunk_verts:
            self._plain.bind()
            self._plain.setUniformValue(self._pu["uMVP"], mvp)
            self._plain.setUniformValue(self._pu["uColor"],
                                        _CHUNK_YELLOW)
            self._chunk_vbo.bind()
            self._plain.enableAttributeArray(0)
            self._plain.setAttributeBuffer(0, 0x1406, 0, 3, 12)
            glf.glLineWidth(1.5)
            glf.glDrawArrays(0x0001, 0, len(self._chunk_verts) // 3)
            self._plain.disableAttributeArray(0)
            self._chunk_vbo.release()
            self._plain.release()
        # ---- 锚点无限红线 ----
        if self._anchor_verts:
            self._plain.bind()
            self._plain.setUniformValue(self._pu["uMVP"], mvp)
            self._plain.setUniformValue(self._pu["uColor"], _ANCHOR_RED)
            self._anchor_vbo.bind()
            self._plain.enableAttributeArray(0)
            self._plain.setAttributeBuffer(0, 0x1406, 0, 3, 12)
            glf.glLineWidth(2.0)
            glf.glDrawArrays(0x0001, 0, len(self._anchor_verts) // 3)
            self._plain.disableAttributeArray(0)
            self._anchor_vbo.release()
            self._plain.release()
        # ---- 箱子高亮琥珀描边（模型主体之上，最上层） ----
        if self._chest_verts:
            self._plain.bind()
            self._plain.setUniformValue(self._pu["uMVP"], mvp)
            self._plain.setUniformValue(self._pu["uColor"], _CHEST_AMBER)
            if self._needs_chest_upload:
                self._needs_chest_upload = False
                self._chest_vbo.bind()
                self._chest_vbo.allocate(
                    struct.pack(f"<{len(self._chest_verts)}f",
                                *self._chest_verts),
                    len(self._chest_verts) * 4)
                self._chest_vbo.release()
            self._chest_vbo.bind()
            self._plain.enableAttributeArray(0)
            self._plain.setAttributeBuffer(0, 0x1406, 0, 3, 12)
            glf.glLineWidth(2.0)
            glf.glDrawArrays(0x0001, 0, len(self._chest_verts) // 3)
            self._plain.disableAttributeArray(0)
            self._chest_vbo.release()
            self._plain.release()

    def _draw_water(self, mvp: QMatrix4x4) -> None:
        """水第二遍：半透明，深度只读（渲染开关关闭时不画）。"""
        if not self._water_count:
            return
        glf = self._glf
        # 在线框之后绘制：水面混合叠在网格线上（透过水看到网格，
        # 与游戏内俯视观感一致）；不写深度避免挡住后画的透明面。
        # 水体几何同为闭合盒（第二遍含底/背面），双面绘制保证
        # 水下视角/斜视水侧不被背向剔除误裁。
        glf.glDepthMask(0)
        glf.glDisable(0x0BC5)                # GL_CULL_FACE：水双面
        self._wshader.bind()
        self._wshader.setUniformValue(self._wu["uMVP"], mvp)
        self._qtex.bind(0)
        self._wshader.setUniformValue(self._wu["uAtlas"], 0)
        self._vao.bind()
        byte_off = self._water_off * (2 if self._idx_type == 0x1403
                                      else 4)
        self._native_glDrawElements(0x0004, self._water_count,
                                    self._idx_type, _VOIDP(byte_off))
        self._vao.release()
        self._wshader.release()
        glf.glEnable(0x0BC5)                 # GL_CULL_FACE 恢复
        glf.glDepthMask(1)

    def _handle_render_failure(self, msg: str) -> None:
        """渲染链路任一环节出错：停渲染 + 复位按钮 + 发错误信号。

        paintGL 内不能弹对话框，信息框由 tool 层连接 render_error
        更新；glDepthMask 强制恢复，防水阶段失败后深度写入永久关闭
        导致后续帧 glClear(DEPTH) 失效；_render_failed 拦住后续帧
        重试（模型仍在，每帧失败会重复发信号刷屏信息框），切结构/
        变种时重置重新尝试。
        """
        try:
            if getattr(self, "_glf", None) is not None:
                self._glf.glDepthMask(1)
        except Exception:
            pass
        self._render_enabled = False
        self._render_failed = True
        self._render_btn.setText("渲染模型")
        self.render_error.emit(msg)

    def paintGL(self) -> None:  # noqa: N802
        glf = self._glf
        dpr = self.devicePixelRatioF()
        glf.glViewport(0, 0, int(self.width() * dpr),
                       int(self.height() * dpr))
        glf.glClear(0x4100)                  # COLOR_BUFFER_BIT | DEPTH
        # 每帧重设 GL 状态：帧末 QPainter overlay 会弄脏全局状态
        # （QPainter 内部关闭深度测试），不重设则下一帧深度测试失效，
        # 后画的几何按画序覆盖先画的 -> 建筑透视（用户实测复现）。
        # 非冗余开销，属必要状态恢复；顺序与原实现一致。
        glf.glEnable(0x0B71)                 # GL_DEPTH_TEST
        glf.glEnable(0x0BE2)                 # GL_BLEND
        glf.glEnable(0x0BC5)                 # GL_CULL_FACE（新增：剔除
                                             #  依赖每帧重开，QP 后状态被关）
        # 标准预乘式混合：src*SRC_ALPHA + dst*(1-src_alpha)
        # 注意 0x0306 是 GL_DST_COLOR，不是 GL_SRC_ALPHA(0x0302)——
        # 写成 (0x0306,0x0303) 会让输出乘背景色系统性变暗(0.17x)
        glf.glBlendFunc(0x0302, 0x0303)
        bg = QColor(0x2B, 0x2F, 0x36)
        glf.glClearColor(bg.redF(), bg.greenF(), bg.blueF(), 1.0)
        if self._needs_upload and self._model:
            if self._render_failed:
                self._needs_upload = False   # 已报过错：不再重试上传
            else:
                try:
                    self._upload_model()
                except Exception as exc:
                    # 上传失败：停渲染 + 信息框（tool 层连接 render_error）
                    self._needs_upload = False
                    self._handle_render_failure(
                        f"3D 渲染出错：模型上传失败（{exc}）")
                    return
        if not self._model or not _seq_len(self._model["mesh"]["idx"]):
            return
        proj = QMatrix4x4()
        proj.perspective(_SP_FOV,
                         max(0.1, self.width() / max(1.0, self.height())),
                         0.5, 4000.0)
        view = QMatrix4x4()
        if self._sp_mode:
            view.lookAt(self._sp_eye,
                        self._sp_eye + self._sp_dir(),
                        QVector3D(0, 1, 0))
        else:
            view.lookAt(self._eye_pos(), self._center + self._pan,
                        QVector3D(0, 1, 0))
        mvp = proj * view
        # 旁观模式眼语义（MC 洞穴剔除）：眼格预解析允许 chunk 集
        #（每帧一次 dict 查表，O(1)；occl 缺数据 = None 走纯视锥）
        occl_cells = None
        if self._sp_mode and self._occl and self._chunks:
            occl_cells = self._occl_cells_for_eye()
        # 渲染开关：默认关闭只画线框层；开启后画模型主体与水。
        # 任一环节异常 -> 停渲染 + 信息框提示（本帧到此为止）；
        # 出错后 _render_failed 拦住后续帧重试，信号只发一次
        try:
            if self._render_enabled and not self._render_failed:
                self._draw_model_body(mvp, occl_cells)
            self._draw_guide_lines(mvp)
            if self._render_enabled and not self._render_failed:
                self._draw_water(mvp)
        except Exception as exc:
            self._handle_render_failure(f"3D 渲染出错：{exc}")
            return
        # ---- 2D overlay：图例 + 操作提示 + FPS ----
        # QOpenGLWidget 仅允许在 paintGL 内开 QPainter
        # （覆写 paintEvent 里画属未定义行为，真实 GUI 下随机 0xC0000409）
        p = QPainter(self)
        # FPS 统计：帧间 perf_counter 差滚动均值，0.5s 刷一次显示。
        # 在 paintGL 末段统计（QPainter overlay 之后）→ 含全部帧开销
        now_t = time.perf_counter()
        if self._fps_frame_t is not None:
            self._fps_frames += 1
            self._fps_accum += now_t - self._fps_frame_t
            if self._fps_accum >= 0.5:
                fps = self._fps_frames / self._fps_accum
                self._fps_text = f"{fps:.0f} FPS ({self._fps_accum / self._fps_frames * 1000.0:.1f} ms/帧)"
                self._fps_frames = 0
                self._fps_accum = 0.0
        self._fps_frame_t = now_t
        # 像素风对齐：文字/准星均硬边，不做平滑（Antialiasing 的
        # 全窗口 pass 在大视口下可测开销；观感更贴游戏字体）
        # ---- 开箱准星：屏幕中心十字（同游戏）
        self._draw_crosshair(p)
        f = QFont()
        f.setPixelSize(11)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QPen(_ANCHOR_RED, 3))
        if self._key in sm.ANCHOR_CENTER_KEYS:
            p.drawText(QPointF(8, 16), "红线 = 锚点（结构中心）")
        else:
            p.drawText(QPointF(8, 16), "红线 = 锚点（西北角）")
        p.setPen(QPen(_CHUNK_YELLOW, 3))
        p.drawText(QPointF(8, 31), "黄框 = 覆盖区块 (16×16)")
        f2 = QFont()
        f2.setPixelSize(10)
        p.setFont(f2)
        p.setPen(QColor(235, 235, 235, 200))
        if self._sp_mode:
            now_ms = time.monotonic_ns() // 1_000_000
            if now_ms < self._sp_speed_until_ms:
                hint = f"飞行速度 {self._sp_speed:.1f} 格/秒"
            elif self._sp_crosshair_idx >= 0:
                hint = "右键/E 打开箱子"
            elif self._sp_grabbed:
                hint = ("WASD/方向键 水平移动 · Space/Shift 升降 · "
                        "鼠标转视角 · 滚轮调速 · ` 呼出鼠标")
            else:
                hint = "点击 3D 预览开始控制视角（或按 ` 键）"
        else:
            hint = "右键拖拽旋转 · 滚轮缩放 · 左键拖拽平移 · 双击复位"
        if self._variant_n and not self._sp_mode:
            cur = 0 if self._variant is None else self._variant
            hint = f"变种 {cur + 1}/{self._variant_n} · {hint}"
        p.drawText(QRectF(0, self.height() - 18, self.width(), 14),
                   Qt.AlignmentFlag.AlignHCenter, hint)
        if self._fps_text:
            # 右上角 FPS（图像例/底部提示/中央准星不重叠）；
            # 红色提示掉帧预警，暗绿正常
            fps_val = self._fps_text.split(" ")[0]
            try:
                fps_color = (_FPS_BAD if float(fps_val) < _FPS_BAD_TH
                             else _FPS_OK)
            except ValueError:
                fps_color = _FPS_OK
            p.setPen(QPen(fps_color, 1))
            p.drawText(QPointF(self.width() - p.fontMetrics()
                               .horizontalAdvance(self._fps_text) - 8, 16),
                       self._fps_text)
        p.end()
        # ---- 连续渲染自驱动：飞行/锁定交互态下每帧渲染完立即调度
        # 下一帧，帧率 = min(GPU 渲染能力, 合成节奏)，摆脱定时器精度
        # 对帧率的钳制。用 singleShot(0) 让出事件循环（tick 积分/
        # 输入事件优先处理，避免 paint 洪流挤压 tick——paintGL 内直
        # 接 update() 实测会把 tick 从 248Hz 挤到 139Hz、帧时间膨胀
        # 7.5ms）。静止/非交互态条件不满足即自然停转，不空烧 GPU。
        if self._sp_mode and not self._render_failed \
                and (self._sp_tick.isActive() or self._sp_pin.isActive()):
            QTimer.singleShot(0, self.update)


def _VOIDP(byte_offset: int):
    """int 字节偏移 -> glDrawElements 的 POINTER 期望对象。"""
    import ctypes
    return ctypes.c_void_p(byte_offset)


def _seq_len(seq) -> int:
    """数组/列表通用长度（numpy 数组禁 bool 真值判断，统一走 len）。"""
    return len(seq)
