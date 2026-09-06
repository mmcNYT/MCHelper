# -*- coding: utf-8 -*-
"""快速验证：步骤图方框流光初始化 + 帧推进（结果写文件）"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from Utils.anvil_steps_tree import AnvilStepsTree, _glint_texture
from Utils.enchant_data_manager import DataManager
from Utils.anvil_optimizer import AnvilOptimizer, build_items_from_cards

dm = DataManager()
opt = AnvilOptimizer(dm)


def card(n, *e):
    return {"item_name": n,
            "enchants": [{"id": x[0], "name": x[1], "level": x[2]} for x in e]}


lines = []
tex = _glint_texture()
lines.append(f"glint_tex_null={tex.isNull()} size={tex.width()}x{tex.height()}")

cards = [card("剑", ("sharpness", "锋利", 5)),      # 带附魔 → 应有流光
         card("剑"),                                  # 无附魔 → 无流光
         card("附魔书", ("unbreaking", "耐久", 3))]  # 带附魔 → 应有流光
plan = opt.optimize(build_items_from_cards(cards))

for mode in ("tree", "steps"):
    t = AnvilStepsTree()
    t.show_plan(plan, dm, mode=mode)
    boxes = t.boxes()
    glint_boxes = [b for b in boxes if b._glint_scaled is not None]
    lines.append(f"mode={mode}: 框数={len(boxes)} 带流光框数={len(glint_boxes)} "
                 f"final框流光={t.final_box()._glint_scaled is not None}")
    off0 = glint_boxes[0]._glint_offset if glint_boxes else None
    for b in glint_boxes:
        b.advance_glint()
    lines.append(f"mode={mode}: 帧推进前 offset={off0} 推进后={glint_boxes[0]._glint_offset if glint_boxes else None}")
    # 渲染一帧（离屏 grab，验证 paint 路径无异常）
    t.grab()
    lines.append(f"mode={mode}: grab 渲染无异常")

with open(r"C:\maomaochongD\Coding\PythonProject\MCHelper\.temp\glint_check_result.txt",
          "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
