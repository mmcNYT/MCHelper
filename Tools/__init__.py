from .tool_base import BaseToolWidget
from .tool_AutoBackUp import AutoBackUpWidget
from .tool_EnchantCaculator import EnchantCalculatorWidget
from .tool_StrongHoldFinder import StrongHoldFinderWidget

# 核心：所有工具类都放在这个列表里，主窗口靠它来加载
TOOL_CLASSES = [
    AutoBackUpWidget,
    EnchantCalculatorWidget,
    StrongHoldFinderWidget
    # 以后加了新工具（比如 tool_backup.py），把类名追加到这里即可
]