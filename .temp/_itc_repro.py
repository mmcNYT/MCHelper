import os, sys
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'C:\maomaochongD\Coding\PythonProject\MCHelper')
from PySide6.QtWidgets import QApplication, QDialog
app = QApplication(sys.argv)
import Tools.tool_EnchantCaculator as tec
from Utils.choose_items import ChooseItemsWindow
p = tec.EnchantCalculatorWidget()._session_path()
if os.path.exists(p): os.remove(p)
out = open(r'C:\maomaochongD\Coding\PythonProject\MCHelper\.temp\_itc_out5.txt', 'w', encoding='utf-8')
# 用例 1/1b
win = ChooseItemsWindow(allowed_item_names={'附魔书', '剑'})
win.close()
win = ChooseItemsWindow()
win.close()
# 用例 2
w = tec.EnchantCalculatorWidget()
w.chosenItemList.add_card({'item_name': '附魔书', 'enchants': []})
w.chosenItemList.add_card({'item_name': '剑', 'enchants': []})
w.chosenItemList.add_card({'item_name': '镐', 'enchants': []})
w.close()
# 用例 4
w2 = tec.EnchantCalculatorWidget()
w2.resize(658, 518)
w2.show()
app.processEvents()
w2.chosenItemList.add_card({'item_name': '剑', 'enchants': []})
w2.chosenItemList.add_card({'item_name': '附魔书', 'enchants': [{'id': 'sharpness', 'name': '锋利', 'level': 5}]})
app.processEvents()
w2.do_start_calculate()
app.processEvents()
out.write(f'boxes={len(w2.realSteps.boxes())} mode={w2.displayMode.currentIndex()}')
out.close()
