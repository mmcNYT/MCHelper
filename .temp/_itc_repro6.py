import os, sys
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'C:\maomaochongD\Coding\PythonProject\MCHelper')
from PySide6.QtWidgets import QApplication, QDialog
app = QApplication(sys.argv)
import Tools.tool_EnchantCaculator as tec
from Utils.choose_items import ChooseItemsWindow
p = tec.EnchantCalculatorWidget()._session_path()
if os.path.exists(p): os.remove(p)
out = open(r'C:\maomaochongD\Coding\PythonProject\MCHelper\.temp\_itc_out10.txt', 'w', encoding='utf-8')
results = {}

class FakeChooseWin:
    selected_data = None
    def __init__(self, parent=None, allowed_item_names=None):
        pass
    def exec(self):
        return QDialog.Accepted

# C1：mock 中 add 一张卡（会话存 1 张剑）
tec.ChooseItemsWindow = FakeChooseWin
w = tec.EnchantCalculatorWidget()
FakeChooseWin.selected_data = {'item_name': '剑', 'enchants': []}
w.do_choose_items()
n_after = w.chosenItemList.count()
w.close()
tec.ChooseItemsWindow = ChooseItemsWindow

# C2：还原后新部件：会话恢复 1 张剑 + 测试又加剑+书 → 2剑+1书？还是1剑1书？
w2 = tec.EnchantCalculatorWidget()
restored = w2.chosenItemList.count()
w2.chosenItemList.add_card({'item_name': '剑', 'enchants': []})
w2.chosenItemList.add_card({'item_name': '附魔书', 'enchants': [{'id': 'sharpness', 'name': '锋利', 'level': 5}]})
app.processEvents()
w2.do_start_calculate()
app.processEvents()
results['C1'] = {'n_after_add': n_after, 'restored': restored,
                 'total_cards': w2.chosenItemList.count(),
                 'boxes': len(w2.realSteps.boxes())}
w2.close()
out.write(str(results))
out.close()
