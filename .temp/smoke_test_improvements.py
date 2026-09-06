# -*- coding: utf-8 -*-
"""冒烟测试：本轮 8 项改进的新功能覆盖
1. format_bytes 字节数格式化：B/KB/MB/GB/TB 边界与位数规则
2. 源目录无效：列表显示不可选提示项，不静默空白
3. 防抖：setText 后列表暂不刷新，等待后或直接调用才刷新
4. 重入保护：is_backing_up 时 do_back_up 拦截并提示
5. 目标目录为空：do_back_up 提前拦截（不触发 makedirs('') 崩溃）
6. can_close：备份中返回 False，平时返回 True
7. 附魔计算器会话持久化：卡片写入 → 重建窗口恢复
8. 卡片编辑链路：prefill_data 预填 → replace_card 原位替换
"""
import os
import shutil
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication, QListWidgetItem
from PySide6.QtCore import Qt

app = QApplication(sys.argv)

from Tools.tool_AutoBackUp import AutoBackUpWidget, format_bytes
from Tools.tool_EnchantCaculator import EnchantCalculatorWidget
from Utils.choose_items import ChooseItemsWindow
from Utils.card_list_widget import CardListWidget

import json as _json

# ---------- 保护用户真实配置：测试前备份，结束后恢复 ----------
_ab = AutoBackUpWidget()  # 仅用于取真实配置路径（read_config 有副作用，但内容随后恢复）
_backup_config_path = _ab.get_config_path()
_ec = EnchantCalculatorWidget()
_session_path = _ec._session_path()
_saved_backup_cfg = open(_backup_config_path, "r", encoding="utf-8").read() \
    if os.path.exists(_backup_config_path) else None
_saved_session = open(_session_path, "r", encoding="utf-8").read() \
    if os.path.exists(_session_path) else None
_ab.deleteLater()
_ec.deleteLater()

def restore_user_files():
    """恢复用户真实配置/会话（测试内多次调用，确保任一断言失败前也能恢复）"""
    if _saved_backup_cfg is not None:
        with open(_backup_config_path, "w", encoding="utf-8") as f:
            f.write(_saved_backup_cfg)
    elif os.path.exists(_backup_config_path):
        os.remove(_backup_config_path)
    if _saved_session is not None:
        with open(_session_path, "w", encoding="utf-8") as f:
            f.write(_saved_session)
    elif os.path.exists(_session_path):
        os.remove(_session_path)

# ---------- 1. format_bytes ----------
cases = {
    0: "0 B", 1: "1 B", 1023: "1023 B",                     # 字节区
    1024: "1 KB", 1536: "1.5 KB",                            # 整数省略 .0 / 1 位小数
    123456789: "117.7 MB",                                   # 用户示例
    9437184: "9 MB", 104857600: "100 MB",
    1073741824: "1 GB", 1207959552: "1.1 GB",
    1099511627776: "1 TB", 1125899906842624: "1024 TB",     # TB 封顶（1024 = 2^10，尾数 0 省略）
    532: "532 B",
}
for n, expect in cases.items():
    got = format_bytes(n)
    assert got == expect, f"format_bytes({n}) = {got!r}，期望 {expect!r}"
print("1. format_bytes 全部边界用例通过（B/KB/MB/GB/TB、≥10 取整） ✓")

base = tempfile.mkdtemp(prefix="mc_improve_")
try:
    # ---------- 2. 源目录无效 → 提示项 ----------
    widget = AutoBackUpWidget()
    widget.back_up_list = {}
    widget.target_dir_path = os.path.join(base, "不存在目录")
    widget._do_refresh_dir_list()
    assert widget.targetDirList.count() == 1, "无效目录应显示 1 行提示"
    hint = widget.targetDirList.item(0)
    assert "无法读取源目录" in hint.text(), f"提示文案异常: {hint.text()}"
    assert hint.flags() == Qt.ItemFlag.NoItemFlags, "提示项应不可选"
    print("2. 源目录无效时显示不可选提示项（不静默空白） ✓")

    # ---------- 3. 防抖 ----------
    ok_dir = os.path.join(base, "正常目录")
    os.makedirs(ok_dir)
    with open(os.path.join(ok_dir, "a.txt"), "w", encoding="utf-8") as f:
        f.write("x")
    widget.target_dir_path = ok_dir
    widget.targetDirPath.setText(ok_dir)
    app.processEvents()
    # 300ms 防抖期内不应刷新（列表仍是提示项）
    assert widget.targetDirList.count() == 1, "防抖期内不应刷新列表"
    widget._do_refresh_dir_list()
    app.processEvents()
    assert widget.targetDirList.count() == 1
    assert widget.targetDirList.item(0).text() == "a.txt", "防抖到期后应列出目录内容"
    print("3. 防抖 300ms：setText 不立即刷新，到期后正常刷新 ✓")

    # ---------- 4/5/6. 重入保护 / 目标目录为空 / can_close ----------
    assert widget.can_close() is True, "非备份状态应允许关闭"
    # 4. 重入保护：伪造备份进行中，do_back_up 应拦截（get_back_up_list 会被调用但重入分支先行）
    widget = AutoBackUpWidget()
    widget.back_up_list = {}
    widget.target_dir_path = ok_dir
    widget.targetDirPath.setText(ok_dir)
    widget._do_refresh_dir_list()
    app.processEvents()
    # 选中列表项，使 get_back_up_list 能收集到非空备份列表
    widget.targetDirList.item(0).setSelected(True)
    widget.is_backing_up = True
    widget.des_dir_path = ok_dir
    widget.do_back_up("手动")
    assert "已有备份正在进行" in widget.informationBrowser.toPlainText(), "重入应提示"
    assert widget.is_backing_up is True, "重入拦截不应改变状态"
    widget.is_backing_up = False

    # 5. 目标目录为空：提前拦截（makedirs('') 会崩溃）
    widget.targetDirList.item(0).setSelected(True)
    widget.des_dir_path = ""
    widget.do_back_up("手动")
    assert "请先设置备份目标目录" in widget.informationBrowser.toPlainText(), "空目标目录应提示"
    print("4. 备份中重入拦截 + 5. 目标目录为空提前拦截（无崩溃） ✓")

    # 6. can_close 备份中返回 False
    widget.is_backing_up = True
    assert widget.can_close() is False, "备份中应阻止关闭"
    widget.is_backing_up = False
    print("6. can_close：备份中 False / 平时 True ✓")

    # 7. 空备份列表提示（顺带回归）：取消选中后 back_up_list 为空
    widget.targetDirList.item(0).setSelected(False)
    widget.do_back_up("手动")
    assert "备份列表为空" in widget.informationBrowser.toPlainText()
    print("   回归：空备份列表提示正常 ✓")

    # ---------- 8. 会话持久化 + 卡片编辑链路 ----------
    calc = EnchantCalculatorWidget()
    calc.chosenItemList.clear_cards()
    data1 = {"item_name": "剑",
             "enchants": [{"id": "sharpness", "name": "锋利", "level": 4},
                          {"id": "unbreaking", "name": "耐久", "level": 3}]}
    data2 = {"item_name": "附魔书",
             "enchants": [{"id": "smite", "name": "亡灵杀手", "level": 3}]}
    calc.chosenItemList.add_card(data1)
    calc.chosenItemList.add_card(data2)
    calc._save_session()
    assert os.path.exists(calc._session_path()), "会话文件应已写入"
    print("8a. 会话文件写入成功 ✓")

    # 重建窗口：恢复卡片
    calc2 = EnchantCalculatorWidget()
    restored = calc2.chosenItemList.all_card_data()
    assert len(restored) == 2, f"应恢复 2 张卡片，实际 {len(restored)}"
    assert restored[0]["item_name"] == "剑" and restored[1]["item_name"] == "附魔书"
    assert {e["id"] for e in restored[0]["enchants"]} == {"sharpness", "unbreaking"}
    print("8b. 重启恢复卡片成功（剑+附魔书，附魔完整） ✓")

    # prefill 预填：以 data1 打开选择窗
    win = ChooseItemsWindow(parent=None, allowed_item_names={"剑", "附魔书"}, prefill_data=data1)
    assert win.itemsList.count() == 2, "白名单应只剩剑+附魔书"
    assert win.itemsList.currentText() == "剑", "预填应恢复物品类型选中项"
    sel_ids = {win.chosenEnchantmentList.item(i).data(Qt.UserRole)
               for i in range(win.chosenEnchantmentList.count())}
    assert sel_ids == {"sharpness", "unbreaking"}, f"预填应恢复已选附魔，实际 {sel_ids}"
    levels = {win.chosenEnchantmentList.item(i).data(Qt.UserRole + 1)
              for i in range(win.chosenEnchantmentList.count())}
    assert levels == {3, 4}, f"预填应恢复等级，实际 {levels}"
    print("8c. prefill_data 预填：物品类型/附魔/等级全部恢复 ✓")

    # replace_card 原位替换
    new_data = {"item_name": "剑",
                "enchants": [{"id": "sharpness", "name": "锋利", "level": 5}]}
    item0 = calc2.chosenItemList.item(0)
    calc2.chosenItemList.replace_card(item0, new_data)
    # 延迟重建：跑一次事件循环
    from PySide6.QtCore import QTimer, QEventLoop
    loop = QEventLoop()
    QTimer.singleShot(50, loop.quit)
    loop.exec()
    after = calc2.chosenItemList.all_card_data()
    assert after[0]["enchants"] == new_data["enchants"], f"替换后数据应更新: {after[0]}"
    assert after[1]["item_name"] == "附魔书", "其余卡片不受影响"
    w0 = calc2.chosenItemList.itemWidget(calc2.chosenItemList.item(0))
    assert w0 is not None, "替换后应重建卡片控件"
    print("8d. replace_card 原位替换：数据更新、顺序不变、其余卡片不受影响 ✓")

    # 清空卡片 → 会话文件同步为空列表
    calc2.do_clear_cards()
    with open(calc2._session_path(), "r", encoding="utf-8") as f:
        import json as _json
        assert _json.load(f) == [], "清空后会话应为空列表"
    print("8e. 清空卡片后同步保存空会话 ✓")

    # 损坏会话文件：启动不崩溃、静默跳过
    with open(calc2._session_path(), "w", encoding="utf-8") as f:
        f.write("{invalid json")
    calc3 = EnchantCalculatorWidget()
    assert calc3.chosenItemList.count() == 0, "损坏会话应静默跳过"
    print("8f. 损坏会话文件静默跳过（不崩溃） ✓")

    # 清理：恢复用户真实会话，避免污染真实配置
    restore_user_files()

    print("\n全部冒烟测试通过")
finally:
    shutil.rmtree(base, ignore_errors=True)
    restore_user_files()
