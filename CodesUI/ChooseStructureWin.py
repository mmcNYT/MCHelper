# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'ChooseStructureWin.ui'
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
from PySide6.QtWidgets import (QApplication, QListWidget, QListWidgetItem, QPushButton,
    QSizePolicy, QWidget)

class Ui_chooseStructureWin(object):
    def setupUi(self, chooseStructureWin):
        if not chooseStructureWin.objectName():
            chooseStructureWin.setObjectName(u"chooseStructureWin")
        chooseStructureWin.resize(690, 568)
        self.structureList = QListWidget(chooseStructureWin)
        self.structureList.setObjectName(u"structureList")
        self.structureList.setGeometry(QRect(0, 0, 691, 531))
        self.confirmBtn = QPushButton(chooseStructureWin)
        self.confirmBtn.setObjectName(u"confirmBtn")
        self.confirmBtn.setGeometry(QRect(300, 540, 83, 26))

        self.retranslateUi(chooseStructureWin)

        QMetaObject.connectSlotsByName(chooseStructureWin)
    # setupUi

    def retranslateUi(self, chooseStructureWin):
        chooseStructureWin.setWindowTitle(QCoreApplication.translate("chooseStructureWin", u"Form", None))
        self.confirmBtn.setText(QCoreApplication.translate("chooseStructureWin", u"\u786e\u8ba4", None))
    # retranslateUi

