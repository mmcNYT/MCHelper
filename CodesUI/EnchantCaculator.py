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
from PySide6.QtWidgets import (QApplication, QGridLayout, QListWidget, QListWidgetItem,
    QPushButton, QSizePolicy, QWidget)

class Ui_EnchantCaculator(object):
    def setupUi(self, EnchantCaculator):
        if not EnchantCaculator.objectName():
            EnchantCaculator.setObjectName(u"EnchantCaculator")
        EnchantCaculator.resize(658, 518)
        self.widget = QWidget(EnchantCaculator)
        self.widget.setObjectName(u"widget")
        self.widget.setGeometry(QRect(20, 40, 591, 226))
        self.gridLayout = QGridLayout(self.widget)
        self.gridLayout.setObjectName(u"gridLayout")
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.listWidget = QListWidget(self.widget)
        self.listWidget.setObjectName(u"listWidget")

        self.gridLayout.addWidget(self.listWidget, 0, 0, 1, 1)

        self.addItems = QPushButton(self.widget)
        self.addItems.setObjectName(u"addItems")

        self.gridLayout.addWidget(self.addItems, 1, 0, 1, 1)


        self.retranslateUi(EnchantCaculator)

        QMetaObject.connectSlotsByName(EnchantCaculator)
    # setupUi

    def retranslateUi(self, EnchantCaculator):
        EnchantCaculator.setWindowTitle(QCoreApplication.translate("EnchantCaculator", u"Form", None))
        self.addItems.setText(QCoreApplication.translate("EnchantCaculator", u"\u6dfb\u52a0\u7269\u54c1", None))
    # retranslateUi

