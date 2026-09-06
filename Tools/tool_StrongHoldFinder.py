from .tool_base import BaseToolWidget
from CodesUI.StrongHoldFinder import Ui_strongHoldFinder

class StrongHoldFinderWidget(BaseToolWidget, Ui_strongHoldFinder):
    preferred_size = (634, 518)  # UI 设计尺寸，主窗口切到本 tab 时自适应
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

    # ---------- 实现基类接口 ----------
    @classmethod
    def tool_name(cls) -> str:
        return "StrongHoldFinder"