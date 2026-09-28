# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'ChooseTargetItemWin.ui'
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
from PySide6.QtWidgets import (QApplication, QComboBox, QGridLayout, QLabel,
    QLineEdit, QPushButton, QSizePolicy, QTextBrowser,
    QWidget)

class Ui_previewBtn(object):
    def setupUi(self, previewBtn):
        if not previewBtn.objectName():
            previewBtn.setObjectName(u"previewBtn")
        previewBtn.resize(428, 395)
        self.layoutWidget = QWidget(previewBtn)
        self.layoutWidget.setObjectName(u"layoutWidget")
        self.layoutWidget.setGeometry(QRect(10, 10, 411, 381))
        self.gridLayout = QGridLayout(self.layoutWidget)
        self.gridLayout.setObjectName(u"gridLayout")
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.targetItemLabel = QLabel(self.layoutWidget)
        self.targetItemLabel.setObjectName(u"targetItemLabel")

        self.gridLayout.addWidget(self.targetItemLabel, 0, 0, 1, 1)

        self.targetItemCombo = QComboBox(self.layoutWidget)
        self.targetItemCombo.setObjectName(u"targetItemCombo")

        self.gridLayout.addWidget(self.targetItemCombo, 0, 1, 1, 2)

        self.targetStructureLabel = QLabel(self.layoutWidget)
        self.targetStructureLabel.setObjectName(u"targetStructureLabel")

        self.gridLayout.addWidget(self.targetStructureLabel, 1, 0, 1, 1)

        self.targetStructureCombo = QComboBox(self.layoutWidget)
        self.targetStructureCombo.setObjectName(u"targetStructureCombo")

        self.gridLayout.addWidget(self.targetStructureCombo, 1, 1, 1, 2)

        self.coodinateLabel = QLabel(self.layoutWidget)
        self.coodinateLabel.setObjectName(u"coodinateLabel")

        self.gridLayout.addWidget(self.coodinateLabel, 2, 0, 1, 1)

        self.XEdit = QLineEdit(self.layoutWidget)
        self.XEdit.setObjectName(u"XEdit")

        self.gridLayout.addWidget(self.XEdit, 2, 1, 1, 1)

        self.ZEdit = QLineEdit(self.layoutWidget)
        self.ZEdit.setObjectName(u"ZEdit")

        self.gridLayout.addWidget(self.ZEdit, 2, 2, 1, 1)

        self.informationBrowser = QTextBrowser(self.layoutWidget)
        self.informationBrowser.setObjectName(u"informationBrowser")

        self.gridLayout.addWidget(self.informationBrowser, 3, 0, 1, 3)

        self.importPreviewBtn = QPushButton(self.layoutWidget)
        self.importPreviewBtn.setObjectName(u"importPreviewBtn")

        self.gridLayout.addWidget(self.importPreviewBtn, 4, 1, 1, 1)

        self.cancelBtn = QPushButton(self.layoutWidget)
        self.cancelBtn.setObjectName(u"cancelBtn")

        self.gridLayout.addWidget(self.cancelBtn, 4, 2, 1, 1)

        self.doFindBtn = QPushButton(self.layoutWidget)
        self.doFindBtn.setObjectName(u"doFindBtn")

        self.gridLayout.addWidget(self.doFindBtn, 4, 0, 1, 1)


        self.retranslateUi(previewBtn)

        QMetaObject.connectSlotsByName(previewBtn)
    # setupUi

    def retranslateUi(self, previewBtn):
        previewBtn.setWindowTitle(QCoreApplication.translate("previewBtn", u"Form", None))
        self.targetItemLabel.setText(QCoreApplication.translate("previewBtn", u"\u76ee\u6807\u7269\u54c1", None))
        self.targetStructureLabel.setText(QCoreApplication.translate("previewBtn", u"\u67e5\u627e\u7ed3\u6784", None))
        self.targetStructureCombo.setPlaceholderText(QCoreApplication.translate("previewBtn", u"\u65e0", None))
        self.coodinateLabel.setText(QCoreApplication.translate("previewBtn", u"\u8d77\u59cb\u5750\u6807", None))
        self.XEdit.setPlaceholderText(QCoreApplication.translate("previewBtn", u"X", None))
        self.ZEdit.setPlaceholderText(QCoreApplication.translate("previewBtn", u"Z", None))
        self.importPreviewBtn.setText(QCoreApplication.translate("previewBtn", u"\u5bfc\u5165\u9884\u89c8", None))
        self.cancelBtn.setText(QCoreApplication.translate("previewBtn", u"\u53d6\u6d88", None))
        self.doFindBtn.setText(QCoreApplication.translate("previewBtn", u"\u5f00\u59cb\u67e5\u627e", None))
    # retranslateUi

