# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'StrongHoldFinder.ui'
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
from PySide6.QtWidgets import (QApplication, QGridLayout, QLabel, QLineEdit,
    QPushButton, QSizePolicy, QTextBrowser, QWidget)

class Ui_strongHoldFinder(object):
    def setupUi(self, strongHoldFinder):
        if not strongHoldFinder.objectName():
            strongHoldFinder.setObjectName(u"strongHoldFinder")
        strongHoldFinder.resize(663, 373)
        self.layoutWidget = QWidget(strongHoldFinder)
        self.layoutWidget.setObjectName(u"layoutWidget")
        self.layoutWidget.setGeometry(QRect(30, 20, 601, 341))
        self.gridLayout = QGridLayout(self.layoutWidget)
        self.gridLayout.setObjectName(u"gridLayout")
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.doCaculate = QPushButton(self.layoutWidget)
        self.doCaculate.setObjectName(u"doCaculate")

        self.gridLayout.addWidget(self.doCaculate, 2, 0, 1, 1)

        self.coordinate2Edit = QLineEdit(self.layoutWidget)
        self.coordinate2Edit.setObjectName(u"coordinate2Edit")

        self.gridLayout.addWidget(self.coordinate2Edit, 1, 1, 1, 1)

        self.coordinate2 = QLabel(self.layoutWidget)
        self.coordinate2.setObjectName(u"coordinate2")
        self.coordinate2.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.coordinate2.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.gridLayout.addWidget(self.coordinate2, 0, 0, 1, 1)

        self.clearCoordinates = QPushButton(self.layoutWidget)
        self.clearCoordinates.setObjectName(u"clearCoordinates")

        self.gridLayout.addWidget(self.clearCoordinates, 2, 1, 1, 1)

        self.coordinate1Edit = QLineEdit(self.layoutWidget)
        self.coordinate1Edit.setObjectName(u"coordinate1Edit")

        self.gridLayout.addWidget(self.coordinate1Edit, 0, 1, 1, 1)

        self.coordinate1 = QLabel(self.layoutWidget)
        self.coordinate1.setObjectName(u"coordinate1")
        self.coordinate1.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.gridLayout.addWidget(self.coordinate1, 1, 0, 1, 1)

        self.informationBrowser = QTextBrowser(self.layoutWidget)
        self.informationBrowser.setObjectName(u"informationBrowser")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.informationBrowser.sizePolicy().hasHeightForWidth())
        self.informationBrowser.setSizePolicy(sizePolicy)

        self.gridLayout.addWidget(self.informationBrowser, 3, 0, 1, 2)


        self.retranslateUi(strongHoldFinder)

        QMetaObject.connectSlotsByName(strongHoldFinder)
    # setupUi

    def retranslateUi(self, strongHoldFinder):
        strongHoldFinder.setWindowTitle(QCoreApplication.translate("strongHoldFinder", u"Form", None))
        self.doCaculate.setText(QCoreApplication.translate("strongHoldFinder", u"\u8ba1\u7b97", None))
        self.coordinate2.setText(QCoreApplication.translate("strongHoldFinder", u"\u5750\u6807\u4e00", None))
        self.clearCoordinates.setText(QCoreApplication.translate("strongHoldFinder", u"\u6e05\u9664", None))
        self.coordinate1.setText(QCoreApplication.translate("strongHoldFinder", u"\u5750\u6807\u4e8c", None))
    # retranslateUi

