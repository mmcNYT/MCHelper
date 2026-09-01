# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'Settings.ui'
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
from PySide6.QtWidgets import (QApplication, QCheckBox, QGridLayout, QSizePolicy,
    QWidget)

class Ui_Settings(object):
    def setupUi(self, Settings):
        if not Settings.objectName():
            Settings.setObjectName(u"Settings")
        Settings.resize(229, 120)
        self.layoutWidget = QWidget(Settings)
        self.layoutWidget.setObjectName(u"layoutWidget")
        self.layoutWidget.setGeometry(QRect(30, 20, 161, 61))
        self.gridLayout = QGridLayout(self.layoutWidget)
        self.gridLayout.setObjectName(u"gridLayout")
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.isStartOnRoot = QCheckBox(self.layoutWidget)
        self.isStartOnRoot.setObjectName(u"isStartOnRoot")

        self.gridLayout.addWidget(self.isStartOnRoot, 0, 0, 1, 1)

        self.isSystemTray = QCheckBox(self.layoutWidget)
        self.isSystemTray.setObjectName(u"isSystemTray")

        self.gridLayout.addWidget(self.isSystemTray, 1, 0, 1, 1)


        self.retranslateUi(Settings)

        QMetaObject.connectSlotsByName(Settings)
    # setupUi

    def retranslateUi(self, Settings):
        Settings.setWindowTitle(QCoreApplication.translate("Settings", u"Form", None))
        self.isStartOnRoot.setText(QCoreApplication.translate("Settings", u"\u5f00\u673a\u81ea\u542f\u52a8", None))
        self.isSystemTray.setText(QCoreApplication.translate("Settings", u"\u5173\u95ed\u65f6\u6700\u5c0f\u5316\u5230\u6258\u76d8", None))
    # retranslateUi

