# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'EnchantCaculator.ui'
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
from PySide6.QtWidgets import (QApplication, QComboBox, QGridLayout, QListWidget,
    QListWidgetItem, QPushButton, QSizePolicy, QWidget)

class Ui_EnchantCaculator(object):
    def setupUi(self, EnchantCaculator):
        if not EnchantCaculator.objectName():
            EnchantCaculator.setObjectName(u"EnchantCaculator")
        EnchantCaculator.resize(634, 518)
        self.layoutWidget = QWidget(EnchantCaculator)
        self.layoutWidget.setObjectName(u"layoutWidget")
        self.layoutWidget.setGeometry(QRect(20, 40, 591, 451))
        self.gridLayout = QGridLayout(self.layoutWidget)
        self.gridLayout.setObjectName(u"gridLayout")
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.addItems = QPushButton(self.layoutWidget)
        self.addItems.setObjectName(u"addItems")

        self.gridLayout.addWidget(self.addItems, 5, 0, 1, 1)

        self.clearItems = QPushButton(self.layoutWidget)
        self.clearItems.setObjectName(u"clearItems")

        self.gridLayout.addWidget(self.clearItems, 5, 1, 1, 1)

        self.startCaculate = QPushButton(self.layoutWidget)
        self.startCaculate.setObjectName(u"startCaculate")

        self.gridLayout.addWidget(self.startCaculate, 5, 2, 1, 1)

        self.displayMode = QComboBox(self.layoutWidget)
        self.displayMode.addItem("")
        self.displayMode.addItem("")
        self.displayMode.setObjectName(u"displayMode")

        self.gridLayout.addWidget(self.displayMode, 5, 3, 1, 1)

        self.realSteps = QListWidget(self.layoutWidget)
        self.realSteps.setObjectName(u"realSteps")

        self.gridLayout.addWidget(self.realSteps, 8, 0, 1, 4)

        self.chosenItemList = QListWidget(self.layoutWidget)
        self.chosenItemList.setObjectName(u"chosenItemList")

        self.gridLayout.addWidget(self.chosenItemList, 1, 0, 1, 4)


        self.retranslateUi(EnchantCaculator)

        QMetaObject.connectSlotsByName(EnchantCaculator)
    # setupUi

    def retranslateUi(self, EnchantCaculator):
        EnchantCaculator.setWindowTitle(QCoreApplication.translate("EnchantCaculator", u"Form", None))
        self.addItems.setText(QCoreApplication.translate("EnchantCaculator", u"\u6dfb\u52a0\u7269\u54c1", None))
        self.clearItems.setText(QCoreApplication.translate("EnchantCaculator", u"\u6e05\u7a7a\u7269\u54c1", None))
        self.startCaculate.setText(QCoreApplication.translate("EnchantCaculator", u"\u5f00\u59cb\u8ba1\u7b97", None))
        self.displayMode.setItemText(0, QCoreApplication.translate("EnchantCaculator", u"\u6811\u72b6\u56fe", None))
        self.displayMode.setItemText(1, QCoreApplication.translate("EnchantCaculator", u"\u6b65\u9aa4\u56fe", None))

    # retranslateUi

