# -*- coding: utf-8 -*-
"""SeedReverser 结构 3D 视口（QOpenGLWidget + 原生 OpenGL，GLSL 120）。

替换 SeedReverser 原平面示意图 label 的 3D 交互视口：
- 右键拖拽 = 环绕旋转（俯仰 5°~85° 限位）
- 滚轮     = 缩放；左键拖拽 = 平移；双击 = 复位视角
- 模型：structure_models.build_model 的共享顶点网格；变种结构
  （海底废墟/废弃传送门）由 QTimer 轮播官方模板（2.5s/个；
  拖动/缩放期间暂停，停手 4s 后恢复）；
- 纹理：98 张方块纹理拼 12x12 图集（槽 0 = 未知材质灰），
  世界坐标 UV fract 到槽内采样，半像素防渗色；
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

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QImage, QMatrix4x4,
                           QPainter, QPen, QPixmap, QVector2D, QVector3D)
from PySide6.QtOpenGL import (QOpenGLBuffer, QOpenGLShader,
                              QOpenGLShaderProgram,
                              QOpenGLTexture, QOpenGLVertexArrayObject)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication, QPushButton

from Utils.SeedReverser import structure_models as sm

TEX_DIR = sm.TEX_DIR

_ATLAS_COLS = 12         # 12x12 = 144 槽 ≥ 98 纹理 + 1 未知灰
_ATLAS_ROWS = 12
_ATLAS_TEX = 16          # 每纹理边长（源 16x16，1:1）

_ANCHOR_RED = QColor("#E5484D")
_CHUNK_YELLOW = QColor(255, 214, 0)     # 区块边界线（琥珀黄）

# 槽宽高 1/12 硬编码进 shader（与 _ATLAS_COLS/_ATLAS_ROWS 同步）：
# PySide6 6.11 setUniformValue(int, float) 重载歧义会把小数截断成
# int 写入（实证 .temp/result_probe_uni.out T_wh 全黑），float 一律
# 不走 uniform。
_VS = """#version 120
attribute vec3 aPos;
attribute vec2 aUV;
attribute vec3 aNor;
uniform mat4 uMVP;
uniform mat4 uModel;
varying vec2 vUV;
varying vec3 vNor;
void main() {
    vUV = aUV;
    vNor = mat3(uModel) * aNor;
    gl_Position = uMVP * vec4(aPos, 1.0);
}
"""

# 注意：#version 必须是源码首行（前导空行会报错）；桌面 GLSL 不支持
# ES 专用的 precision 语句（NVIDIA 宽松能过，Mesa/llvmpipe 直接拒编）。
_FS = """#version 120
varying vec2 vUV;
varying vec3 vNor;
uniform sampler2D uAtlas;
uniform vec2 uSlotOrigin;   // 当前槽左下角归一化坐标
uniform vec3 uLightDir;
const float SLOT_W = 0.08333333;   // 1/12 图集 12x12，勿改单一处
const float SLOT_H = 0.08333333;
void main() {
    vec2 tileUV = fract(vUV);
    vec2 pad = vec2(0.5) / vec2(16.0, 16.0);
    tileUV = clamp(tileUV, pad, 1.0 - pad);
    vec2 uv = uSlotOrigin + vec2(tileUV.x * SLOT_W,
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
uniform sampler2D uAtlas;
uniform vec2 uSlotOrigin;
uniform vec3 uLightDir;
const float SLOT_W = 0.08333333;
const float SLOT_H = 0.08333333;
void main() {
    vec2 tileUV = fract(vUV);
    vec2 pad = vec2(0.5) / vec2(16.0, 16.0);
    tileUV = clamp(tileUV, pad, 1.0 - pad);
    vec2 uv = uSlotOrigin + vec2(tileUV.x * SLOT_W,
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
    img = QImage(_ATLAS_COLS * _ATLAS_TEX, _ATLAS_ROWS * _ATLAS_TEX,
                 QImage.Format.Format_RGBA8888)
    img.fill(0)
    p = QPainter(img)
    p.fillRect(0, 0, _ATLAS_TEX, _ATLAS_TEX, QColor(0x9A, 0xA0, 0xA6))
    p.end()
    slots = {"__unknown__": 0}
    names = sorted(fn[:-4] for fn in os.listdir(TEX_DIR)
                   if fn.endswith(".png"))
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


class Structure3DView(QOpenGLWidget):
    """结构 3D 交互视口（右键环绕 / 滚轮缩放 / 左键平移 / 双击复位）。"""

    # 渲染报错（构建模型/上传/绘制任一环节异常）：tool 层连接后写入
    # 信息框；视口自身同步停渲染并复位开关按钮
    render_error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
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

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------
    def set_structure(self, key: str | None, name: str = "") -> None:
        """切换结构（模型走 build_model 缓存；GL 就绪后上传缓冲）。

        变种结构（VARIANT_KEYS）额外启动轮播定时器：先显示默认
        模板，2.5s 起每间隔换下一个官方模板变种。
        """
        if key == self._key:
            return
        self._variant_timer.stop()
        self._key = key
        self._variant = None
        self._variant_n = len(sm.VARIANT_FILES.get(key, ()))
        self._model = None
        self._slot_of_mat = {}
        self._render_failed = False      # 新模型重新允许尝试渲染
        if key:
            try:
                self._model = sm.build_model(key)
            except Exception as exc:
                self._model = None
                # 模型构建失败：信息框提示 + 停渲染（同 paintGL 出错链路）
                self._render_enabled = False
                self._render_btn.setText("渲染模型")
                self.render_error.emit(
                    f"3D 预览：结构 {name or key} 模型构建失败，已停止渲染（{exc}）")
            if self._variant_n and self._model is not None:
                self._variant_timer.start()
        self._idle_timer.stop()          # 切键后不在交互暂停态
        self._reset_camera_for_model()
        # GL 上传只能在上下文就绪时执行（paintGL），此处只标记
        self._needs_upload = bool(self._model)
        self.update()

    def stop_variant_timer(self) -> None:
        """停掉轮播与空闲定时器（应用退出钩子调用，防退出期析构崩溃）。"""
        self._stop_spin_timers()

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
    # 鼠标交互
    # ------------------------------------------------------------------
    def mousePressEvent(self, ev) -> None:  # noqa: N802
        self._last_pos = ev.position().toPoint()
        if ev.button() == Qt.MouseButton.RightButton:
            # 旋转光标：北↑西← 双箭头随视角旋转，直观提示拖拽方向
            self.setCursor(self._orbit_cursor())
        self.setFocus()
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        self._last_pos = None
        if ev.button() == Qt.MouseButton.RightButton:
            self.unsetCursor()
        super().mouseReleaseEvent(ev)

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

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
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

    def mouseDoubleClickEvent(self, ev) -> None:  # noqa: N802
        self._reset_camera_for_model()
        self.update()

    def wheelEvent(self, ev) -> None:
        steps = ev.angleDelta().y() / 120.0
        if steps:
            base = self._dist if self._dist else self._radius * 2.2
            self._dist = max(self._radius * 0.6,
                             min(self._radius * 6.0, base * 0.87 ** steps))
        self._pause_rotation()           # 缩放同样暂停轮播 + 续期
        self.update()

    def hideEvent(self, ev) -> None:  # noqa: N802
        # 视口不可见时暂停轮播并撤销交互暂停态（后台空转浪费且
        # 切换无意义；重显时 showEvent 直接恢复轮播）
        self._stop_spin_timers()
        super().hideEvent(ev)

    def showEvent(self, ev) -> None:  # noqa: N802
        if self._variant_n and not self._variant_timer.isActive():
            self._variant_timer.start()
        self._idle_timer.stop()          # 交互暂停态不跨隐藏保留
        super().showEvent(ev)

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

# ==== PART2 ====

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
        self._shader.release()
        self._wshader.bind()
        self._wu = {n: self._wshader.uniformLocation(n)
                    for n in ("uMVP", "uModel", "uAtlas", "uLightDir",
                              "uSlotOrigin")}
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
        floats = mesh["verts"]
        self._vbo.allocate(struct.pack(f"<{len(floats)}f", *floats),
                           len(floats) * 4)
        self._ibo.bind()
        idx = mesh["idx"]
        if not idx:
            # 空网格：线框/网格数据一并清空（VBO 已重建为空，
            # 残留旧顶点数会让 glDrawArrays 读空缓冲）
            self._anchor_verts = None
            self._chunk_verts = None
            self._water_count = 0
            self._vao.release()
            self._vbo.release()
            self._ibo.release()
            return
        if max(idx) < 65536:
            self._idx_type = 0x1403            # GL_UNSIGNED_SHORT
            self._ibo.allocate(struct.pack(f"<{len(idx)}H", *idx),
                               len(idx) * 2)
        else:
            self._idx_type = 0x1405            # GL_UNSIGNED_INT
            self._ibo.allocate(struct.pack(f"<{len(idx)}I", *idx),
                               len(idx) * 4)
        # 属性指针：用 QOpenGLShaderProgram.setAttributeBuffer
        # （glVertexAttribPointer 的 PySide6 绑定不接受裸 int 偏移）
        self._vao.bind()
        self._vbo.bind()
        self._shader.bind()
        stride = 8 * 4
        self._shader.enableAttributeArray(0)
        self._shader.setAttributeBuffer(0, 0x1406, 0, 3, stride)
        self._shader.enableAttributeArray(1)
        self._shader.setAttributeBuffer(1, 0x1406, 12, 2, stride)
        self._shader.enableAttributeArray(2)
        self._shader.setAttributeBuffer(2, 0x1406, 20, 3, stride)
        self._shader.release()
        self._vao.release()
        self._vbo.release()
        self._ibo.release()
        # 锚点位置：monument = 结构中心（ANCHOR_CENTER_KEYS）；
        # ANCHOR_OFFSETS 键 = 模型局部坐标偏移（village 水井 /
        # trial_chambers 入口两水池，用户 GUI 对照校准）；
        # 缺省 = 包围盒西北角 (0,0)。
        w, d, _h = self._model["size"]
        if self._key in sm.ANCHOR_CENTER_KEYS:
            ax, az = w / 2.0, d / 2.0
        elif self._key in sm.ANCHOR_OFFSETS:
            ax, az = sm.ANCHOR_OFFSETS[self._key]
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

    def _draw_model_body(self, mvp: QMatrix4x4) -> None:
        """模型主体：不透明网格逐材质槽绘制（GL 上下文内调用）。"""
        self._shader.bind()
        self._shader.setUniformValue(self._u["uMVP"], mvp)
        self._shader.setUniformValue(self._u["uModel"], QMatrix4x4())
        self._qtex.bind(0)
        self._shader.setUniformValue(self._u["uAtlas"], 0)
        # uSlotW/uSlotH 已硬编码进 shader（SLOT_W/SLOT_H = 1/12），
        # 与 _ATLAS_COLS/_ATLAS_ROWS = 12 必须同步。
        self._shader.setUniformValue(self._u["uLightDir"],
                                     QVector3D(-0.45, 0.85, 0.28))
        self._vao.bind()
        for slot_i, (start, count) in enumerate(self._model["mesh"]["slots"]):
            s = self._slot_of_mat.get(slot_i, 0)
            col, row = s % _ATLAS_COLS, s // _ATLAS_COLS
            self._shader.setUniformValue(
                self._u["uSlotOrigin"],
                QVector2D(col / _ATLAS_COLS, row / _ATLAS_ROWS))
            byte_off = start * (2 if self._idx_type == 0x1403 else 4)
            self._native_glDrawElements(0x0004, count, self._idx_type,
                                        _VOIDP(byte_off))
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

    def _draw_water(self, mvp: QMatrix4x4) -> None:
        """水第二遍：半透明，深度只读（渲染开关关闭时不画）。"""
        if not self._water_count:
            return
        glf = self._glf
        # 在线框之后绘制：水面混合叠在网格线上（透过水看到网格，
        # 与游戏内俯视观感一致）；不写深度避免挡住后画的透明面。
        glf.glDepthMask(0)
        self._wshader.bind()
        self._wshader.setUniformValue(self._wu["uMVP"], mvp)
        self._wshader.setUniformValue(self._wu["uModel"], QMatrix4x4())
        self._qtex.bind(0)
        self._wshader.setUniformValue(self._wu["uAtlas"], 0)
        self._wshader.setUniformValue(self._wu["uLightDir"],
                                      QVector3D(-0.45, 0.85, 0.28))
        col, row = (self._water_slot % _ATLAS_COLS,
                    self._water_slot // _ATLAS_COLS)
        self._wshader.setUniformValue(
            self._wu["uSlotOrigin"],
            QVector2D(col / _ATLAS_COLS, row / _ATLAS_ROWS))
        self._vao.bind()
        byte_off = self._water_off * (2 if self._idx_type == 0x1403
                                      else 4)
        self._native_glDrawElements(0x0004, self._water_count,
                                    self._idx_type, _VOIDP(byte_off))
        self._vao.release()
        self._wshader.release()
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
        glf.glEnable(0x0B71)                 # GL_DEPTH_TEST
        glf.glEnable(0x0BE2)                 # GL_BLEND
        # 标准预乘式混合：src*SRC_ALPHA + dst*(1-src_alpha)
        # 注意 0x0306 是 GL_DST_COLOR，不是 GL_SRC_ALPHA(0x0302)——
        # 写成 (0x0306,0x0303) 会让输出乘背景色系统性变暗(0.17x)
        glf.glBlendFunc(0x0302, 0x0303)
        bg = QColor(0x2B, 0x2F, 0x36)
        glf.glClearColor(bg.redF(), bg.greenF(), bg.blueF(), 1.0)
        glf.glClear(0x4100)                  # COLOR_BUFFER_BIT | DEPTH
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
        if not self._model or not self._model["mesh"]["idx"]:
            return
        proj = QMatrix4x4()
        proj.perspective(45.0,
                         max(0.1, self.width() / max(1.0, self.height())),
                         0.5, 4000.0)
        view = QMatrix4x4()
        view.lookAt(self._eye_pos(), self._center + self._pan,
                    QVector3D(0, 1, 0))
        mvp = proj * view
        # 渲染开关：默认关闭只画线框层；开启后画模型主体与水。
        # 任一环节异常 -> 停渲染 + 信息框提示（本帧到此为止）；
        # 出错后 _render_failed 拦住后续帧重试，信号只发一次
        try:
            if self._render_enabled and not self._render_failed:
                self._draw_model_body(mvp)
            self._draw_guide_lines(mvp)
            if self._render_enabled and not self._render_failed:
                self._draw_water(mvp)
        except Exception as exc:
            self._handle_render_failure(f"3D 渲染出错：{exc}")
            return
        # ---- 2D overlay：图例 + 操作提示 ----
        # QOpenGLWidget 仅允许在 paintGL 内开 QPainter
        # （覆写 paintEvent 里画属未定义行为，真实 GUI 下随机 0xC0000409）
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
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
        hint = "右键拖拽旋转 · 滚轮缩放 · 左键拖拽平移 · 双击复位"
        if self._variant_n:
            cur = 0 if self._variant is None else self._variant
            hint = f"变种 {cur + 1}/{self._variant_n} · {hint}"
        p.drawText(QRectF(0, self.height() - 18, self.width(), 14),
                   Qt.AlignmentFlag.AlignHCenter, hint)
        p.end()


def _VOIDP(byte_offset: int):
    """int 字节偏移 -> glDrawElements 的 POINTER 期望对象。"""
    import ctypes
    return ctypes.c_void_p(byte_offset)
