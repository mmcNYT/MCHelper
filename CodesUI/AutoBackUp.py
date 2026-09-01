# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'AutoBackUp.ui'
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
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QGridLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QProgressBar,
    QPushButton, QSizePolicy, QSpacerItem, QTextBrowser,
    QWidget)

class Ui_AutoBackUp(object):
    def setupUi(self, AutoBackUp):
        if not AutoBackUp.objectName():
            AutoBackUp.setObjectName(u"AutoBackUp")
        AutoBackUp.setEnabled(True)
        AutoBackUp.resize(633, 475)
        self.layoutWidget = QWidget(AutoBackUp)
        self.layoutWidget.setObjectName(u"layoutWidget")
        self.layoutWidget.setGeometry(QRect(40, 30, 541, 431))
        self.gridLayout = QGridLayout(self.layoutWidget)
        self.gridLayout.setObjectName(u"gridLayout")
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.verticalSpacer_2 = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.gridLayout.addItem(self.verticalSpacer_2, 1, 3, 1, 1)

        self.targetDesPath = QLineEdit(self.layoutWidget)
        self.targetDesPath.setObjectName(u"targetDesPath")
        self.targetDesPath.setClearButtonEnabled(True)

        self.gridLayout.addWidget(self.targetDesPath, 2, 2, 1, 1)

        self.chooseTargetDir = QPushButton(self.layoutWidget)
        self.chooseTargetDir.setObjectName(u"chooseTargetDir")

        self.gridLayout.addWidget(self.chooseTargetDir, 0, 3, 1, 1)

        self.label_2 = QLabel(self.layoutWidget)
        self.label_2.setObjectName(u"label_2")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.label_2.sizePolicy().hasHeightForWidth())
        self.label_2.setSizePolicy(sizePolicy)
        self.label_2.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.gridLayout.addWidget(self.label_2, 2, 0, 1, 1)

        self.informationBrowser = QTextBrowser(self.layoutWidget)
        self.informationBrowser.setObjectName(u"informationBrowser")

        self.gridLayout.addWidget(self.informationBrowser, 5, 0, 1, 4)

        self.targetDirList = QListWidget(self.layoutWidget)
        self.targetDirList.setObjectName(u"targetDirList")
        self.targetDirList.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.targetDirList.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.targetDirList.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.targetDirList.setSelectionRectVisible(True)

        self.gridLayout.addWidget(self.targetDirList, 1, 2, 1, 1)

        self.chooseDesDir = QPushButton(self.layoutWidget)
        self.chooseDesDir.setObjectName(u"chooseDesDir")

        self.gridLayout.addWidget(self.chooseDesDir, 2, 3, 1, 1)

        self.targetDirPath = QLineEdit(self.layoutWidget)
        self.targetDirPath.setObjectName(u"targetDirPath")
        self.targetDirPath.setClearButtonEnabled(True)

        self.gridLayout.addWidget(self.targetDirPath, 0, 2, 1, 1)

        self.startBackUp = QPushButton(self.layoutWidget)
        self.startBackUp.setObjectName(u"startBackUp")

        self.gridLayout.addWidget(self.startBackUp, 4, 0, 1, 1)

        self.label = QLabel(self.layoutWidget)
        self.label.setObjectName(u"label")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Preferred)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.label.sizePolicy().hasHeightForWidth())
        self.label.setSizePolicy(sizePolicy1)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.gridLayout.addWidget(self.label, 0, 0, 1, 1)

        self.verticalSpacer = QSpacerItem(10, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.gridLayout.addItem(self.verticalSpacer, 1, 0, 1, 1)

        self.backUpProgress = QProgressBar(self.layoutWidget)
        self.backUpProgress.setObjectName(u"backUpProgress")
        self.backUpProgress.setValue(24)

        self.gridLayout.addWidget(self.backUpProgress, 4, 2, 1, 1)

        self.label_3 = QLabel(self.layoutWidget)
        self.label_3.setObjectName(u"label_3")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.label_3.sizePolicy().hasHeightForWidth())
        self.label_3.setSizePolicy(sizePolicy2)
        self.label_3.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.gridLayout.addWidget(self.label_3, 3, 0, 1, 1)

        self.processName = QLineEdit(self.layoutWidget)
        self.processName.setObjectName(u"processName")
        self.processName.setClearButtonEnabled(True)

        self.gridLayout.addWidget(self.processName, 3, 2, 1, 1)

        self.monitorController = QPushButton(self.layoutWidget)
        self.monitorController.setObjectName(u"monitorController")

        self.gridLayout.addWidget(self.monitorController, 3, 3, 1, 1)

        self.gridLayout.setColumnStretch(0, 1)
        self.gridLayout.setColumnStretch(2, 4)
        self.gridLayout.setColumnStretch(3, 1)
        self.gridLayout.setColumnMinimumWidth(0, 1)

        self.retranslateUi(AutoBackUp)

        QMetaObject.connectSlotsByName(AutoBackUp)
    # setupUi

    def retranslateUi(self, AutoBackUp):
        AutoBackUp.setWindowTitle(QCoreApplication.translate("AutoBackUp", u"Form", None))
        self.chooseTargetDir.setText(QCoreApplication.translate("AutoBackUp", u"\u6d4f\u89c8\u6587\u4ef6\u5939", None))
        self.label_2.setText(QCoreApplication.translate("AutoBackUp", u"\u5907\u4efd\u76ee\u5f55", None))
        self.chooseDesDir.setText(QCoreApplication.translate("AutoBackUp", u"\u6d4f\u89c8\u6587\u4ef6\u5939", None))
        self.startBackUp.setText(QCoreApplication.translate("AutoBackUp", u"\u5f00\u59cb\u5907\u4efd", None))
        self.label.setText(QCoreApplication.translate("AutoBackUp", u"\u5b58\u6863\u76ee\u5f55", None))
        self.label_3.setText(QCoreApplication.translate("AutoBackUp", u"\u76d1\u6d4b\u8fdb\u7a0b\u540d", None))
        self.processName.setInputMask("")
        self.processName.setText("")
        self.processName.setPlaceholderText(QCoreApplication.translate("AutoBackUp", u"java.exe", None))
        self.monitorController.setText(QCoreApplication.translate("AutoBackUp", u"\u5f00\u59cb\u76d1\u6d4b", None))
    # retranslateUi

