import os, sys
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'C:\maomaochongD\Coding\PythonProject\MCHelper')
from PySide6.QtWidgets import QApplication, QDialog
app = QApplication(sys.argv)
import Tools.tool_EnchantCaculator as tec
p = tec.EnchantCalculatorWidget()._session_path()
out = open(r'C:\maomaochongD\Coding\PythonProject\MCHelper\.temp\_itc_out7.txt', 'w', encoding='utf-8')
results = {}

class FakeChooseWin:
    selected_data = None
    def __init__(self, parent=None, allowed_item_names=None):
        pass
    def exec(self):
        return QDialog.Accepted

orig = tec.ChooseItemsWindow
tec.ChooseItemsWindow = FakeChooseWin

# 变体A：只 mock + 实例化 w + do_choose_items(无 data)
w = tec.EnchantCalculatorWidget()
w.do_choose_items()
FakeChooseWin.selected_data = {'item_name': '剑', 'enchants': []}
w.do_choose_items()
w.close()
tec.ChooseItemsWindow = orig

w2 = tec.EnchantCalculatorWidget()
w2.chosenItemList.add_card({'item_name': '剑', 'enchants': []})
w2.chosenItemList.add_card({'item_name': '附魔书', 'enchants': [{'id': 'sharpness', 'name': '锋利', 'level': 5}]})
app.processEvents()
w2.do_start_calculate()
app.processEvents()
results['A_mock_without_clear'] = len(w2.realSteps.boxes())
w2.close()

out.write(str(results))
out.close()
