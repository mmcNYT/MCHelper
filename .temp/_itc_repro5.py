import os, sys
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'C:\maomaochongD\Coding\PythonProject\MCHelper')
from PySide6.QtWidgets import QApplication, QDialog
app = QApplication(sys.argv)
import Tools.tool_EnchantCaculator as tec
p = tec.EnchantCalculatorWidget()._session_path()
if os.path.exists(p): os.remove(p)
out = open(r'C:\maomaochongD\Coding\PythonProject\MCHelper\.temp\_itc_out9.txt', 'w', encoding='utf-8')
results = {}

class FakeChooseWin:
    selected_data = None
    def __init__(self, parent=None, allowed_item_names=None):
        pass
    def exec(self):
        return QDialog.Accepted

# 变体B：mock 期间只实例化 w，不调用 do_choose_items，再还原
tec.ChooseItemsWindow = FakeChooseWin
w = tec.EnchantCalculatorWidget()
w.close()
tec.ChooseItemsWindow = __import__('Utils.choose_items', fromlist=['ChooseItemsWindow']).ChooseItemsWindow

w2 = tec.EnchantCalculatorWidget()
w2.chosenItemList.add_card({'item_name': '剑', 'enchants': []})
w2.chosenItemList.add_card({'item_name': '附魔书', 'enchants': [{'id': 'sharpness', 'name': '锋利', 'level': 5}]})
app.processEvents()
w2.do_start_calculate()
app.processEvents()
results['B_mock_only_instantiate'] = len(w2.realSteps.boxes())
w2.close()

out.write(str(results))
out.close()
