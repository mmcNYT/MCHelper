from .tool_base import BaseToolWidget
from Utils.choose_items import ChooseItemsWindow
from CodesUI.EnchantCaculator import Ui_EnchantCaculator
from Utils.card_list_widget import CardListWidget
from Utils.conflict_resolver import find_conflict_clusters, ConflictResolveDialog
from Utils.enchant_data_manager import DataManager
from PySide6.QtCore import QCoreApplication, Slot, QThreadPool, QStandardPaths, QItemSelectionModel
from PySide6.QtWidgets import QFileDialog

class EnchantCalculatorWidget(BaseToolWidget, Ui_EnchantCaculator):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.addItems.clicked.connect(self.do_choose_items)

        # 卡片列表替换为增强型子类：横排布局（构造内置） + Del键删除
        # + 再次点击取消选中 + 拖动交换位置
        # （同父组件同网格位置替换 UI 生成的原生 QListWidget，原布局不受影响）
        old_list = self.chosenItemList
        self.chosenItemList = CardListWidget(old_list.parentWidget())
        self.gridLayout.replaceWidget(old_list, self.chosenItemList)
        old_list.deleteLater()

        # 清空物品按钮：清空全部卡片并同步内部计算状态
        self.clearItems.clicked.connect(self.chosenItemList.clear_cards)

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
        # 确认后把物品卡片（图标+附魔方框）添加到展示列表
        if self.selected_stuff:
            self.add_item_card(self.selected_stuff)
        # TODO: 后续计算逻辑使用 self.selected_stuff

    def add_item_card(self, data: dict):
        """把一次确认选择的物品生成为卡片并加入卡片列表

        参数：
            data: ChooseItemsWindow 打包的数据
                  {"item_name": str, "enchants": [{"id","name","level"}, ...]}
        """
        self.chosenItemList.add_card(data)
        self.resolve_cross_card_conflicts()

    def resolve_cross_card_conflicts(self):
        """检测全部卡片间的互斥附魔冲突，弹窗让用户选择最终保留哪个

        流程：簇检测（无冲突直接返回）→ 模态对话框逐簇单选 →
        确定后把未保留的附魔从对应卡片移除重绘；「暂不处理」保持现状。
        """
        clusters = find_conflict_clusters(
            self.chosenItemList.all_card_data(), DataManager())
        if not clusters:
            return
        dlg = ConflictResolveDialog(clusters, self)
        if dlg.exec() != ConflictResolveDialog.DialogCode.Accepted:
            return  # 暂不处理：卡片维持现状，下次添加物品会再次弹窗提醒
        choices = dlg.choices()
        removals = {}  # {物品名: [要移除的附魔 ID, ...]}
        for ci, members in enumerate(clusters):
            keep_id = choices.get(ci)
            for m in members:
                if m["id"] == keep_id:
                    continue
                for item_name in m["items"]:
                    removals.setdefault(item_name, [])
                    if m["id"] not in removals[item_name]:
                        removals[item_name].append(m["id"])
        self.chosenItemList.remove_enchants_everywhere(removals)