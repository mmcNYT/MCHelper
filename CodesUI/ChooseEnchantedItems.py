# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'ChooseEnchantedItems.ui'
##
## Created by: Qt User Interface Compiler version 6.11.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QComboBox, QGridLayout, QListWidgetItem,
    QPushButton, QSizePolicy, QTabWidget, QWidget)

from Utils.drop_list_widget import DropListWidget
from Utils.enchant_list_widget import EnchantListWidget

class Ui_enchantedItems(object):
    def setupUi(self, enchantedItems):
        if not enchantedItems.objectName():
            enchantedItems.setObjectName(u"enchantedItems")
        enchantedItems.resize(585, 417)
        self.layoutWidget = QWidget(enchantedItems)
        self.layoutWidget.setObjectName(u"layoutWidget")
        self.layoutWidget.setGeometry(QRect(70, 20, 461, 381))
        self.gridLayout = QGridLayout(self.layoutWidget)
        self.gridLayout.setObjectName(u"gridLayout")
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.itemsList = QComboBox(self.layoutWidget)
        self.itemsList.addItem("")
        self.itemsList.addItem("")
        self.itemsList.addItem("")
        self.itemsList.addItem("")
        self.itemsList.addItem("")
        self.itemsList.addItem("")
        self.itemsList.addItem("")
        self.itemsList.addItem("")
        self.itemsList.addItem("")
        self.itemsList.addItem("")
        self.itemsList.addItem("")
        self.itemsList.addItem("")
        self.itemsList.addItem("")
        self.itemsList.addItem("")
        self.itemsList.addItem("")
        self.itemsList.addItem("")
        self.itemsList.setObjectName(u"itemsList")

        self.gridLayout.addWidget(self.itemsList, 0, 0, 1, 1)

        self.chosenEnchantmentList = DropListWidget(self.layoutWidget)
        self.chosenEnchantmentList.setObjectName(u"chosenEnchantmentList")
        self.chosenEnchantmentList.setAcceptDrops(True)

        self.gridLayout.addWidget(self.chosenEnchantmentList, 0, 1, 1, 1)

        self.allEnchantmentTab = QTabWidget(self.layoutWidget)
        self.allEnchantmentTab.setObjectName(u"allEnchantmentTab")
        self.meleeTab = QWidget()
        self.meleeTab.setObjectName(u"meleeTab")
        self.meleeEnchantmentList = EnchantListWidget(self.meleeTab)
        self.meleeEnchantmentList.setObjectName(u"meleeEnchantmentList")
        self.meleeEnchantmentList.setGeometry(QRect(0, 0, 451, 121))
        self.allEnchantmentTab.addTab(self.meleeTab, "")
        self.toolTab = QWidget()
        self.toolTab.setObjectName(u"toolTab")
        self.toolEnchantmentList = EnchantListWidget(self.toolTab)
        self.toolEnchantmentList.setObjectName(u"toolEnchantmentList")
        self.toolEnchantmentList.setGeometry(QRect(0, 0, 451, 121))
        self.allEnchantmentTab.addTab(self.toolTab, "")
        self.rangedTab = QWidget()
        self.rangedTab.setObjectName(u"rangedTab")
        self.rangedEnchantmentList = EnchantListWidget(self.rangedTab)
        self.rangedEnchantmentList.setObjectName(u"rangedEnchantmentList")
        self.rangedEnchantmentList.setGeometry(QRect(0, 0, 451, 121))
        self.allEnchantmentTab.addTab(self.rangedTab, "")
        self.armorTab = QWidget()
        self.armorTab.setObjectName(u"armorTab")
        self.armorEnchantmentList = EnchantListWidget(self.armorTab)
        self.armorEnchantmentList.setObjectName(u"armorEnchantmentList")
        self.armorEnchantmentList.setGeometry(QRect(0, 0, 451, 121))
        self.allEnchantmentTab.addTab(self.armorTab, "")
        self.tridentTab = QWidget()
        self.tridentTab.setObjectName(u"tridentTab")
        self.tridentEnchantmentList = EnchantListWidget(self.tridentTab)
        self.tridentEnchantmentList.setObjectName(u"tridentEnchantmentList")
        self.tridentEnchantmentList.setGeometry(QRect(0, 0, 451, 121))
        self.allEnchantmentTab.addTab(self.tridentTab, "")
        self.commonTab = QWidget()
        self.commonTab.setObjectName(u"commonTab")
        self.commonEnchantmentList = EnchantListWidget(self.commonTab)
        self.commonEnchantmentList.setObjectName(u"commonEnchantmentList")
        self.commonEnchantmentList.setGeometry(QRect(0, 0, 451, 121))
        self.allEnchantmentTab.addTab(self.commonTab, "")
        self.curseTab = QWidget()
        self.curseTab.setObjectName(u"curseTab")
        self.curseEnchantmentList = EnchantListWidget(self.curseTab)
        self.curseEnchantmentList.setObjectName(u"curseEnchantmentList")
        self.curseEnchantmentList.setGeometry(QRect(0, 0, 451, 121))
        self.allEnchantmentTab.addTab(self.curseTab, "")

        self.gridLayout.addWidget(self.allEnchantmentTab, 7, 0, 1, 2)

        self.clearEnchantList = QPushButton(self.layoutWidget)
        self.clearEnchantList.setObjectName(u"clearEnchantList")

        self.gridLayout.addWidget(self.clearEnchantList, 2, 1, 1, 1)

        self.confirmItem = QPushButton(self.layoutWidget)
        self.confirmItem.setObjectName(u"confirmItem")

        self.gridLayout.addWidget(self.confirmItem, 2, 0, 1, 1)


        self.retranslateUi(enchantedItems)

        self.allEnchantmentTab.setCurrentIndex(4)


        QMetaObject.connectSlotsByName(enchantedItems)
    # setupUi

    def retranslateUi(self, enchantedItems):
        enchantedItems.setWindowTitle(QCoreApplication.translate("enchantedItems", u"ChooseEnchantedItems", None))
        self.itemsList.setItemText(0, QCoreApplication.translate("enchantedItems", u"\u9644\u9b54\u4e66", None))
        self.itemsList.setItemText(1, QCoreApplication.translate("enchantedItems", u"\u5251", None))
        self.itemsList.setItemText(2, QCoreApplication.translate("enchantedItems", u"\u65a7", None))
        self.itemsList.setItemText(3, QCoreApplication.translate("enchantedItems", u"\u77db", None))
        self.itemsList.setItemText(4, QCoreApplication.translate("enchantedItems", u"\u9550", None))
        self.itemsList.setItemText(5, QCoreApplication.translate("enchantedItems", u"\u94f2", None))
        self.itemsList.setItemText(6, QCoreApplication.translate("enchantedItems", u"\u9504", None))
        self.itemsList.setItemText(7, QCoreApplication.translate("enchantedItems", u"\u5f13", None))
        self.itemsList.setItemText(8, QCoreApplication.translate("enchantedItems", u"\u5f29", None))
        self.itemsList.setItemText(9, QCoreApplication.translate("enchantedItems", u"\u4e09\u53c9\u621f", None))
        self.itemsList.setItemText(10, QCoreApplication.translate("enchantedItems", u"\u91cd\u9524", None))
        self.itemsList.setItemText(11, QCoreApplication.translate("enchantedItems", u"\u5934\u76d4", None))
        self.itemsList.setItemText(12, QCoreApplication.translate("enchantedItems", u"\u80f8\u7532", None))
        self.itemsList.setItemText(13, QCoreApplication.translate("enchantedItems", u"\u62a4\u817f", None))
        self.itemsList.setItemText(14, QCoreApplication.translate("enchantedItems", u"\u9774\u5b50", None))
        self.itemsList.setItemText(15, QCoreApplication.translate("enchantedItems", u"\u9493\u9c7c\u7aff", None))

        self.allEnchantmentTab.setTabText(self.allEnchantmentTab.indexOf(self.meleeTab), QCoreApplication.translate("enchantedItems", u"\u8fd1\u6218\u6b66\u5668", None))
        self.allEnchantmentTab.setTabText(self.allEnchantmentTab.indexOf(self.toolTab), QCoreApplication.translate("enchantedItems", u"\u5de5\u5177", None))
        self.allEnchantmentTab.setTabText(self.allEnchantmentTab.indexOf(self.rangedTab), QCoreApplication.translate("enchantedItems", u"\u8fdc\u7a0b\u6b66\u5668", None))
        self.allEnchantmentTab.setTabText(self.allEnchantmentTab.indexOf(self.armorTab), QCoreApplication.translate("enchantedItems", u"\u9632\u5177", None))
        self.allEnchantmentTab.setTabText(self.allEnchantmentTab.indexOf(self.tridentTab), QCoreApplication.translate("enchantedItems", u"\u4e09\u53c9\u621f", None))
        self.allEnchantmentTab.setTabText(self.allEnchantmentTab.indexOf(self.commonTab), QCoreApplication.translate("enchantedItems", u"\u901a\u7528\u9644\u9b54", None))
        self.allEnchantmentTab.setTabText(self.allEnchantmentTab.indexOf(self.curseTab), QCoreApplication.translate("enchantedItems", u"\u8bc5\u5492", None))
        self.clearEnchantList.setText(QCoreApplication.translate("enchantedItems", u"\u6e05\u7a7a", None))
        self.confirmItem.setText(QCoreApplication.translate("enchantedItems", u"\u786e\u8ba4", None))
    # retranslateUi

