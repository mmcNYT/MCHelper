from .tool_base import BaseToolWidget
from Utils.choose_items import ChooseItemsWindow
from CodesUI.EnchantCaculator import Ui_EnchantCaculator
from Utils.card_list_widget import CardListWidget
from Utils.conflict_resolver import (find_conflict_clusters,
                                     resolve_conflicts, ConflictResolveDialog)
from Utils.enchant_data_manager import DataManager
from Utils.anvil_optimizer import AnvilOptimizer, AnvilError, build_items_from_cards
from Utils.anvil_steps_tree import AnvilStepsTree
from PySide6.QtCore import QCoreApplication, Slot, QThreadPool, QStandardPaths, QItemSelectionModel
from PySide6.QtWidgets import QFileDialog, QMessageBox
import os
import json

class EnchantCalculatorWidget(BaseToolWidget, Ui_EnchantCaculator):
    preferred_size = (634, 518)  # UI 设计尺寸，主窗口切到本 tab 时自适应
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

        # 清空物品按钮：清空全部卡片、同步冲突决策，并把步骤图恢复占位
        self.clearItems.clicked.connect(self.do_clear_cards)

        # 结果区：UI 生成的原生 realSteps(QListWidget) 替换为步骤树控件
        # （同上方卡片列表的替换模式：同父组件同网格位置替换，原布局不受影响）
        old_steps = self.realSteps
        self.realSteps = AnvilStepsTree(old_steps.parentWidget())
        self.gridLayout.replaceWidget(old_steps, self.realSteps)
        old_steps.deleteLater()

        # 开始计算按钮：计算合并所有卡片的最少经验等级与最优合成步骤
        self.startCaculate.clicked.connect(self.do_start_calculate)

        # 展示模式下拉框：树状图 / 步骤图，切换时用最近方案即时重渲染
        self.displayMode.currentIndexChanged.connect(self._on_display_mode_changed)

        self.selected_stuff = {}
        # 跨卡片冲突保留决策 {簇序号: 保留的附魔ID}：只影响最终合成物组成，
        # 不从卡片移除任何附魔（未保留的仍计费）；开始计算时重新检测并预选
        self.conflict_choices = {}
        # 铁砧优化器（DataManager 单例，构造开销极小）
        self._optimizer = AnvilOptimizer(DataManager())
        # 最近一次计算成功的方案（displayMode 切换时重渲染用；含当时的数据管理器）
        self._last_plan = None
        self._last_dm = None

        # 双击卡片 → 编辑模式重新打开选择窗（预填该卡数据，确认后原位替换）
        self.chosenItemList.itemDoubleClicked.connect(self._edit_card_at)

        # 启动时恢复上次会话的卡片（异常时静默丢弃，不影响启动）
        self._restore_session()

    # ---------- 会话持久化（卡片重启不丢） ----------
    def _session_path(self) -> str:
        """会话文件路径（用户配置目录下 enchant_session.json）"""
        config_dir = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
        if not config_dir:
            config_dir = os.path.dirname(os.path.abspath(__file__))
        os.makedirs(config_dir, exist_ok=True)
        return os.path.join(config_dir, "enchant_session.json")

    def _restore_session(self):
        """启动时从会话文件恢复卡片列表（文件缺失/损坏时静默跳过）"""
        path = self._session_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                cards = json.load(f)
            if not isinstance(cards, list):
                return
            for data in cards:
                # 逐项校验数据包结构，异常项跳过（不阻止其余恢复）
                if (isinstance(data, dict) and data.get("item_name")
                        and isinstance(data.get("enchants"), list)):
                    self.chosenItemList.add_card(data)
        except (OSError, ValueError) as e:
            print(f"恢复附魔计算器会话失败: {e}")

    def _save_session(self):
        """把当前卡片列表写入会话文件（卡片结构变化时调用）"""
        try:
            with open(self._session_path(), 'w', encoding='utf-8') as f:
                json.dump(self.chosenItemList.all_card_data(), f,
                          ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"保存附魔计算器会话失败: {e}")

    def save_config(self):
        """主窗口退出时调用（save_all_tools_config 协议）：保存卡片会话"""
        self._save_session()

    # ---------- 实现基类接口 ----------
    @classmethod
    def tool_name(cls) -> str:
        return "EnchantCaculator"

    def do_choose_items(self):
        """打开物品选择窗口，确认后把物品卡片添加到展示列表

        物品类型约束：已存在非附魔书卡片时，选择窗口只开放
        「附魔书 + 已有非书类型」（铁砧不能合并不同类型物品）；
        无非书卡片时开放全部类型。
        """
        win = ChooseItemsWindow(self, allowed_item_names=self.allowed_item_types())
        win.exec()
        # exec() 返回后读取打包数据（未点确认时 selected_data 为 None）
        self.selected_stuff = win.selected_data
        # 确认后把物品卡片（图标+附魔方框）添加到展示列表
        if self.selected_stuff:
            self.add_item_card(self.selected_stuff)
            self._save_session()  # 卡片变化，同步保存会话

    def allowed_item_types(self):
        """当前允许选择的物品类型集合（None = 不限制）

        已有非附魔书卡片 → 只允许附魔书与该类型；
        没有卡片或只有附魔书卡片 → 全部类型可选。
        """
        names = {d["item_name"] for d in self.chosenItemList.all_card_data()
                 if d["item_name"] != "附魔书"}
        if len(names) > 1:
            # 理论不可达（下约束后无法选入第二类型）；双保险返回空集
            return set()
        if names:
            return {"附魔书"} | names
        return None

    def add_item_card(self, data: dict):
        """把一次确认选择的物品生成为卡片并加入卡片列表

        参数：
            data: ChooseItemsWindow 打包的数据
                  {"item_name": str, "enchants": [{"id","name","level"}, ...]}
        """
        self.chosenItemList.add_card(data)

    def _edit_card_at(self, item):
        """双击卡片：编辑模式重新打开选择窗（预填该卡数据，确认后原位替换）

        与新增的区别：确认后不是 append 而是替换被双击的卡片；取消则不动。
        """
        data = item.data(self.chosenItemList.CARD_DATA_ROLE)
        if not data:
            return
        # 编辑时类型约束以「除本卡外的其它卡片」计算（本卡要被替换，不算既存类型）
        others = [d for d in self.chosenItemList.all_card_data() if d is not data]
        names = {d["item_name"] for d in others if d["item_name"] != "附魔书"}
        allowed = ({"附魔书"} | names) if names else None
        win = ChooseItemsWindow(self, allowed_item_names=allowed, prefill_data=data)
        win.exec()
        if win.selected_data:
            # 原位替换：把新数据写回被双击的条目并重建卡片控件
            self.chosenItemList.replace_card(item, win.selected_data)
            self._save_session()  # 卡片变化，同步保存会话

    def _resolve_conflicts_for_calculate(self, cards, dm) -> bool:
        """开始计算时的冲突决策（统一在此处理，添加卡片时不再弹窗）

        流程：检测冲突簇 → 自动决策（附魔出现在全部非书卡片上 → 必然
        保留，如唯一剑上的锋利；用户例中剑锋利 vs 书亡灵杀手自动保留
        锋利）→ 剩余簇弹窗（预选上次决策，取消则本次不计算）。
        更新并返回 self.conflict_choices（供优化器作 required_enchants）。
        """
        clusters = find_conflict_clusters(cards, dm)
        if not clusters:
            self.conflict_choices = {}  # 无冲突，过期决策作废
            return True
        auto, pending = resolve_conflicts(clusters, cards)
        choices = dict(auto)
        if pending:
            # 弹窗只处理需用户决策的簇；defaults 按新序号映射上次决策
            pending_orig = [ci for ci in range(len(clusters))
                            if ci not in auto]
            dlg = ConflictResolveDialog(
                pending, self,
                defaults={new_ci: self.conflict_choices.get(orig_ci)
                          for new_ci, orig_ci in enumerate(pending_orig)
                          if self.conflict_choices.get(orig_ci)})
            if dlg.exec() != ConflictResolveDialog.DialogCode.Accepted:
                return False  # 用户取消：本次不计算
            for new_ci, eid in dlg.choices().items():
                choices[pending_orig[new_ci]] = eid
        # 决策值集合 = 保留约束（自动决策 + 用户选择）
        self.conflict_choices = choices
        return True

    def _on_display_mode_changed(self, index: int):
        """展示模式切换：树状图(0) / 步骤图(1)，用最近方案重渲染

        无方案（未计算/已清空）时不动结果区，保持占位或旧图。
        """
        if self._last_plan is None:
            return
        self.realSteps.show_plan(self._last_plan, self._last_dm,
                                 mode="steps" if index == 1 else "tree")

    def do_clear_cards(self):
        """清空物品：清空全部卡片 + 冲突决策清零 + 步骤图恢复占位提示

        清空后不存在任何卡片，冲突决策必然过期，直接作废。
        """
        self.chosenItemList.clear_cards()
        self.conflict_choices = {}
        self._last_plan = None
        self._last_dm = None
        self.realSteps.clear_plan()
        self._save_session()  # 卡片变化，同步保存会话（空列表）

    def do_start_calculate(self):
        """开始计算：收集卡片数据 → 冲突决策（自动+弹窗）→ 优化 → 步骤图展示

        冲突统一在此时处理：必然保留的自动决策，其余弹窗询问；
        用户取消弹窗则本次不计算。优化失败（无法合成一件/约束无法满足）
        以弹窗提示原因，结果区维持原状。
        """
        cards = self.chosenItemList.all_card_data()
        if not cards:
            QMessageBox.information(self, "提示", "请先添加物品卡片")
            return
        dm = DataManager()
        if not self._resolve_conflicts_for_calculate(cards, dm):
            return  # 用户取消冲突弹窗：本次不计算
        # 决策转约束：保留的附魔必须出现在最终合成物上
        required = frozenset(self.conflict_choices.values())
        try:
            plan = self._optimizer.optimize(
                build_items_from_cards(cards), required_enchants=required)
        except AnvilError as e:
            QMessageBox.warning(self, "无法计算", str(e))
            return
        self._last_plan = plan
        self._last_dm = dm
        self.realSteps.show_plan(
            plan, dm,
            mode="steps" if self.displayMode.currentIndex() == 1 else "tree")