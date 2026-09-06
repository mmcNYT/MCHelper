import os, sys
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'C:\maomaochongD\Coding\PythonProject\MCHelper')
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
import Tools.tool_EnchantCaculator as tec
p = tec.EnchantCalculatorWidget()._session_path()
if os.path.exists(p): os.remove(p)
out = open(r'C:\maomaochongD\Coding\PythonProject\MCHelper\.temp\_itc_out8.txt', 'w', encoding='utf-8')
results = {}

# 对照1：只实例化 w 加卡片（不 close）
w = tec.EnchantCalculatorWidget()
w.chosenItemList.add_card({'item_name': '剑', 'enchants': []})
w.close()

w2 = tec.EnchantCalculatorWidget()
w2.chosenItemList.add_card({'item_name': '剑', 'enchants': []})
w2.chosenItemList.add_card({'item_name': '附魔书', 'enchants': [{'id': 'sharpness', 'name': '锋利', 'level': 5}]})
app.processEvents()
w2.do_start_calculate()
app.processEvents()
results['first_w_close'] = len(w2.realSteps.boxes())
w2.close()

# 对照2：完全不建第一个 w
w3 = tec.EnchantCalculatorWidget()
w3.chosenItemList.add_card({'item_name': '剑', 'enchants': []})
w3.chosenItemList.add_card({'item_name': '附魔书', 'enchants': [{'id': 'sharpness', 'name': '锋利', 'level': 5}]})
app.processEvents()
w3.do_start_calculate()
app.processEvents()
results['fresh'] = len(w3.realSteps.boxes())
w3.close()

out.write(str(results))
out.close()
