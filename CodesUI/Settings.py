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
from PySide6.QtWidgets import (QApplication, QCheckBox, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSizePolicy,
    QWidget)

class Ui_Settings(object):
    def setupUi(self, Settings):
        if not Settings.objectName():
            Settings.setObjectName(u"Settings")
        Settings.resize(420, 210)
        self.layoutWidget = QWidget(Settings)
        self.layoutWidget.setObjectName(u"layoutWidget")
        self.layoutWidget.setGeometry(QRect(30, 20, 161, 88))
        self.gridLayout = QGridLayout(self.layoutWidget)
        self.gridLayout.setObjectName(u"gridLayout")
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.isSystemTray = QCheckBox(self.layoutWidget)
        self.isSystemTray.setObjectName(u"isSystemTray")

        self.gridLayout.addWidget(self.isSystemTray, 1, 0, 1, 1)

        self.isStartOnRoot = QCheckBox(self.layoutWidget)
        self.isStartOnRoot.setObjectName(u"isStartOnRoot")

        self.gridLayout.addWidget(self.isStartOnRoot, 0, 0, 1, 1)

        self.checkRenderingSupportButton = QPushButton(self.layoutWidget)
        self.checkRenderingSupportButton.setObjectName(u"checkRenderingSupportButton")

        self.gridLayout.addWidget(self.checkRenderingSupportButton, 2, 0, 1, 1)

        self.savesDirLayout = QHBoxLayout()
        self.savesDirLayout.setObjectName(u"savesDirLayout")
        self.savesDirLabel = QLabel(self.layoutWidget)
        self.savesDirLabel.setObjectName(u"savesDirLabel")

        self.savesDirLayout.addWidget(self.savesDirLabel)

        self.savesDirEdit = QLineEdit(self.layoutWidget)
        self.savesDirEdit.setObjectName(u"savesDirEdit")

        self.savesDirLayout.addWidget(self.savesDirEdit)

        self.savesDirBrowseButton = QPushButton(self.layoutWidget)
        self.savesDirBrowseButton.setObjectName(u"savesDirBrowseButton")

        self.savesDirLayout.addWidget(self.savesDirBrowseButton)


        self.gridLayout.addLayout(self.savesDirLayout, 3, 0, 1, 1)


        self.retranslateUi(Settings)

        QMetaObject.connectSlotsByName(Settings)
    # setupUi

    def retranslateUi(self, Settings):
        Settings.setWindowTitle(QCoreApplication.translate("Settings", u"Form", None))
        self.isSystemTray.setText(QCoreApplication.translate("Settings", u"\u5173\u95ed\u65f6\u6700\u5c0f\u5316\u5230\u6258\u76d8", None))
        self.isStartOnRoot.setText(QCoreApplication.translate("Settings", u"\u5f00\u673a\u81ea\u542f\u52a8", None))
        self.checkRenderingSupportButton.setText(QCoreApplication.translate("Settings", u"\u68c0\u6d4b\u6e32\u67d3\u652f\u6301", None))
        self.savesDirLabel.setText(QCoreApplication.translate("Settings", u"\u5b58\u6863\u76ee\u5f55", None))
        self.savesDirBrowseButton.setText(QCoreApplication.translate("Settings", u"\u6d4f\u89c8\u2026", None))
    # retranslateUi

