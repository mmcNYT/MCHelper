from .tool_base import BaseToolWidget
from Utils.choose_items import ChooseItemsWindow
from CodesUI.EnchantCaculator import Ui_EnchantCaculator
from PySide6.QtCore import QCoreApplication, Slot, QThreadPool, QStandardPaths, QItemSelectionModel
from PySide6.QtWidgets import QFileDialog

class EnchantCalculatorWidget(BaseToolWidget, Ui_EnchantCaculator):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.addItems.clicked.connect(self.do_choose_items)

        self.selected_stuff = {}

    # ---------- 实现基类接口 ----------
    @classmethod
    def tool_name(cls) -> str:
        return "EnchantCaculator"

    def do_choose_items(self):
        win = ChooseItemsWindow()
        win.exec()
        # exec() 返回后读取打包数据（未点确认时 selected_data 为 None）
        self.selected_stuff = win.selected_data
        print(self.selected_stuff)
        # TODO: 后续计算逻辑使用 self.selected_stuff