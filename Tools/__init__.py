from .tool_base import BaseToolWidget
from .tool_EnchantCaculator import EnchantCalculatorWidget
from .tool_MapPreviewer import MapPreviewerWidget
from .tool_StrongHoldFinder import StrongHoldFinderWidget
from .tool_SeedReverser import SeedReverserWidget
from .tool_StructurePreviewer import StructurePreviewerWidget

# 核心：所有工具类都放在这个列表里，主窗口靠它来加载
TOOL_CLASSES = [
    SeedReverserWidget,
    MapPreviewerWidget,
    StructurePreviewerWidget,
    EnchantCalculatorWidget,
    StrongHoldFinderWidget,

    # 以后加了新工具，把类名追加到这里即可
]