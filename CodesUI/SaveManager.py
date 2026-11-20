# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'SaveManager.ui'
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
from PySide6.QtWidgets import (QApplication, QGraphicsView, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget)

class Ui_SaveManager(object):
    def setupUi(self, SaveManager):
        if not SaveManager.objectName():
            SaveManager.setObjectName(u"SaveManager")
        SaveManager.resize(1000, 700)
        self.mainLayout = QHBoxLayout(SaveManager)
        self.mainLayout.setObjectName(u"mainLayout")
        self.leftLayout = QVBoxLayout()
        self.leftLayout.setObjectName(u"leftLayout")
        self.searchEdit = QLineEdit(SaveManager)
        self.searchEdit.setObjectName(u"searchEdit")

        self.leftLayout.addWidget(self.searchEdit)

        self.saveList = QListWidget(SaveManager)
        self.saveList.setObjectName(u"saveList")
        self.saveList.setMinimumSize(QSize(220, 0))

        self.leftLayout.addWidget(self.saveList)

        self.refreshButton = QPushButton(SaveManager)
        self.refreshButton.setObjectName(u"refreshButton")

        self.leftLayout.addWidget(self.refreshButton)


        self.mainLayout.addLayout(self.leftLayout)

        self.rightLayout = QVBoxLayout()
        self.rightLayout.setObjectName(u"rightLayout")
        self.detailLayout = QHBoxLayout()
        self.detailLayout.setObjectName(u"detailLayout")
        self.iconLabel = QLabel(SaveManager)
        self.iconLabel.setObjectName(u"iconLabel")
        self.iconLabel.setMinimumSize(QSize(72, 72))

        self.detailLayout.addWidget(self.iconLabel)

        self.nameVerLayout = QVBoxLayout()
        self.nameVerLayout.setObjectName(u"nameVerLayout")
        self.nameLabel = QLabel(SaveManager)
        self.nameLabel.setObjectName(u"nameLabel")
        self.nameLabel.setStyleSheet(u"font-size: 18px; font-weight: bold;")

        self.nameVerLayout.addWidget(self.nameLabel)

        self.versionLabel = QLabel(SaveManager)
        self.versionLabel.setObjectName(u"versionLabel")
        self.versionLabel.setStyleSheet(u"color: #888;")

        self.nameVerLayout.addWidget(self.versionLabel)


        self.detailLayout.addLayout(self.nameVerLayout)


        self.rightLayout.addLayout(self.detailLayout)

        self.opsLayout = QHBoxLayout()
        self.opsLayout.setObjectName(u"opsLayout")
        self.openFolderButton = QPushButton(SaveManager)
        self.openFolderButton.setObjectName(u"openFolderButton")

        self.opsLayout.addWidget(self.openFolderButton)

        self.renameButton = QPushButton(SaveManager)
        self.renameButton.setObjectName(u"renameButton")

        self.opsLayout.addWidget(self.renameButton)

        self.deleteButton = QPushButton(SaveManager)
        self.deleteButton.setObjectName(u"deleteButton")

        self.opsLayout.addWidget(self.deleteButton)

        self.backupButton = QPushButton(SaveManager)
        self.backupButton.setObjectName(u"backupButton")

        self.opsLayout.addWidget(self.backupButton)

        self.exportButton = QPushButton(SaveManager)
        self.exportButton.setObjectName(u"exportButton")

        self.opsLayout.addWidget(self.exportButton)


        self.rightLayout.addLayout(self.opsLayout)

        self.mapView = QGraphicsView(SaveManager)
        self.mapView.setObjectName(u"mapView")

        self.rightLayout.addWidget(self.mapView)

        self.statusLabel = QLabel(SaveManager)
        self.statusLabel.setObjectName(u"statusLabel")

        self.rightLayout.addWidget(self.statusLabel)


        self.mainLayout.addLayout(self.rightLayout)


        self.retranslateUi(SaveManager)

        QMetaObject.connectSlotsByName(SaveManager)
    # setupUi

    def retranslateUi(self, SaveManager):
        self.searchEdit.setPlaceholderText(QCoreApplication.translate("SaveManager", u"\u641c\u7d22\u5b58\u6863\u540d\u2026", None))
        self.refreshButton.setText(QCoreApplication.translate("SaveManager", u"\u5237\u65b0\u5b58\u6863\u5217\u8868", None))
        self.iconLabel.setText("")
        self.nameLabel.setText(QCoreApplication.translate("SaveManager", u"\u672a\u9009\u62e9\u5b58\u6863", None))
        self.versionLabel.setText("")
        self.openFolderButton.setText(QCoreApplication.translate("SaveManager", u"\u6253\u5f00\u6587\u4ef6\u5939", None))
        self.renameButton.setText(QCoreApplication.translate("SaveManager", u"\u91cd\u547d\u540d", None))
        self.deleteButton.setText(QCoreApplication.translate("SaveManager", u"\u5220\u9664", None))
        self.backupButton.setText(QCoreApplication.translate("SaveManager", u"\u5907\u4efd", None))
        self.exportButton.setText(QCoreApplication.translate("SaveManager", u"\u5bfc\u51fa", None))
        self.statusLabel.setText(QCoreApplication.translate("SaveManager", u"\u9009\u62e9\u4e00\u4e2a\u5b58\u6863\u67e5\u770b", None))
        pass
    # retranslateUi

