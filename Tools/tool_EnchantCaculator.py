from .tool_base import BaseToolWidget
from Utils.choose_items import ChooseItemsWindow
from CodesUI.EnchantCaculator import Ui_EnchantCaculator
from Utils.card_list_widget import CardListWidget
from Utils.conflict_resolver import find_conflict_clusters, ConflictResolveDialog
from Utils.enchant_data_manager import DataManager
from Utils.anvil_optimizer import AnvilOptimizer, AnvilError, build_items_from_cards
from Utils.anvil_steps_tree import AnvilStepsTree
from PySide6.QtCore import QCoreApplication, Slot, QThreadPool, QStandardPaths, QItemSelectionModel
from PySide6.QtWidgets import QFileDialog, QMessageBox

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

        # 结果区：UI 生成的原生 realSteps(QListWidget) 替换为步骤树控件
        # （同上方卡片列表的替换模式：同父组件同网格位置替换，原布局不受影响）
        old_steps = self.realSteps
        self.realSteps = AnvilStepsTree(old_steps.parentWidget())
        self.gridLayout.replaceWidget(old_steps, self.realSteps)
        old_steps.deleteLater()

        # 开始计算按钮：计算合并所有卡片的最少经验等级与最优合成步骤
        self.startCaculate.clicked.connect(self.do_start_calculate)

        self.selected_stuff = {}
        # 跨卡片冲突保留决策 {簇序号: 保留的附魔ID}：只影响最终合成物组成，
        # 不从卡片移除任何附魔（未保留的仍计费）；开始计算时重新检测并预选
        self.conflict_choices = {}
        # 铁砧优化器（DataManager 单例，构造开销极小）
        self._optimizer = AnvilOptimizer(DataManager())

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

    def add_item_card(self, data: dict):
        """把一次确认选择的物品生成为卡片并加入卡片列表

        参数：
            data: ChooseItemsWindow 打包的数据
                  {"item_name": str, "enchants": [{"id","name","level"}, ...]}
        """
        self.chosenItemList.add_card(data)
        self.resolve_cross_card_conflicts()

    def resolve_cross_card_conflicts(self):
        """检测全部卡片间的互斥附魔冲突，弹窗让用户选择最终合成物保留哪个

        流程：簇检测（无冲突则清空过期决策直接返回）→ 模态对话框逐簇单选
        （预选上次决策）→ 确定后只记录决策到 conflict_choices（供开始计算
        时作为 required_enchants 约束），不修改任何卡片；
        「暂不处理」保持现有决策不变（首次则无决策）。
        """
        clusters = find_conflict_clusters(
            self.chosenItemList.all_card_data(), DataManager())
        if not clusters:
            self.conflict_choices = {}  # 冲突已不存在，过期决策作废
            return
        dlg = ConflictResolveDialog(clusters, self,
                                    defaults=self.conflict_choices)
        if dlg.exec() != ConflictResolveDialog.DialogCode.Accepted:
            return  # 暂不处理：决策维持现状，下次添加物品会再次弹窗提醒
        self.conflict_choices = dlg.choices()

    def do_start_calculate(self):
        """开始计算：收集卡片数据 → 冲突决策 → 优化 → 步骤树展示

        冲突决策在开始时重新检测（卡片可能增删过），弹窗预选上次决策；
        用户取消弹窗则本次不计算。优化失败（无法合成一件/约束无法满足）
        以弹窗提示原因，结果区维持原状。
        """
        cards = self.chosenItemList.all_card_data()
        if not cards:
            QMessageBox.information(self, "提示", "请先添加物品卡片")
            return
        dm = DataManager()
        # 冲突决策：开始计算时以当前卡片重新检测，预选上次决策
        clusters = find_conflict_clusters(cards, dm)
        if clusters:
            dlg = ConflictResolveDialog(clusters, self,
                                        defaults=self.conflict_choices)
            if dlg.exec() != ConflictResolveDialog.DialogCode.Accepted:
                return  # 用户取消：本次不计算
            self.conflict_choices = dlg.choices()
        else:
            self.conflict_choices = {}  # 无冲突，过期决策作废
        # 决策转约束：保留的附魔必须出现在最终合成物上
        required = frozenset(self.conflict_choices.values())
        try:
            plan = self._optimizer.optimize(
                build_items_from_cards(cards), required_enchants=required)
        except AnvilError as e:
            QMessageBox.warning(self, "无法计算", str(e))
            return
        self.realSteps.show_plan(plan, dm)