# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'MapPreviewer.ui'
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
from PySide6.QtWidgets import (QApplication, QComboBox, QGraphicsView, QGridLayout,
    QLabel, QLineEdit, QProgressBar, QPushButton,
    QSizePolicy, QWidget)

class Ui_mapPreviewer(object):
    def setupUi(self, mapPreviewer):
        if not mapPreviewer.objectName():
            mapPreviewer.setObjectName(u"mapPreviewer")
        mapPreviewer.resize(1081, 801)
        self.widget = QWidget(mapPreviewer)
        self.widget.setObjectName(u"widget")
        self.widget.setGeometry(QRect(10, 10, 1061, 781))
        self.gridLayout = QGridLayout(self.widget)
        self.gridLayout.setObjectName(u"gridLayout")
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.labelVersion = QLabel(self.widget)
        self.labelVersion.setObjectName(u"labelVersion")

        self.gridLayout.addWidget(self.labelVersion, 0, 0, 2, 1)

        self.comboVersion = QComboBox(self.widget)
        self.comboVersion.addItem("")
        self.comboVersion.addItem("")
        self.comboVersion.addItem("")
        self.comboVersion.addItem("")
        self.comboVersion.setObjectName(u"comboVersion")

        self.gridLayout.addWidget(self.comboVersion, 0, 1, 2, 1)

        self.editSeed = QLineEdit(self.widget)
        self.editSeed.setObjectName(u"editSeed")

        self.gridLayout.addWidget(self.editSeed, 0, 3, 2, 1)

        self.labelRadius = QLabel(self.widget)
        self.labelRadius.setObjectName(u"labelRadius")

        self.gridLayout.addWidget(self.labelRadius, 0, 4, 2, 1)

        self.btnStructures = QPushButton(self.widget)
        self.btnStructures.setObjectName(u"btnStructures")

        self.gridLayout.addWidget(self.btnStructures, 0, 6, 2, 1)

        self.btnCommon = QPushButton(self.widget)
        self.btnCommon.setObjectName(u"btnCommon")

        self.gridLayout.addWidget(self.btnCommon, 0, 7, 2, 1)

        self.btnAll = QPushButton(self.widget)
        self.btnAll.setObjectName(u"btnAll")

        self.gridLayout.addWidget(self.btnAll, 0, 8, 2, 1)

        self.btnRender = QPushButton(self.widget)
        self.btnRender.setObjectName(u"btnRender")

        self.gridLayout.addWidget(self.btnRender, 0, 9, 2, 1)

        self.comboRadius = QComboBox(self.widget)
        self.comboRadius.addItem("")
        self.comboRadius.addItem("")
        self.comboRadius.addItem("")
        self.comboRadius.addItem("")
        self.comboRadius.setObjectName(u"comboRadius")

        self.gridLayout.addWidget(self.comboRadius, 1, 5, 1, 1)

        self.viewMap = QGraphicsView(self.widget)
        self.viewMap.setObjectName(u"viewMap")

        self.gridLayout.addWidget(self.viewMap, 2, 0, 1, 10)

        self.progressRender = QProgressBar(self.widget)
        self.progressRender.setObjectName(u"progressRender")
        self.progressRender.setValue(24)

        self.gridLayout.addWidget(self.progressRender, 3, 0, 1, 10)

        self.labelSeed = QLabel(self.widget)
        self.labelSeed.setObjectName(u"labelSeed")

        self.gridLayout.addWidget(self.labelSeed, 1, 2, 1, 1)

        self.labelHover = QLabel(self.widget)
        self.labelHover.setObjectName(u"labelHover")

        self.gridLayout.addWidget(self.labelHover, 4, 0, 1, 4)

        self.labelInfo = QLabel(self.widget)
        self.labelInfo.setObjectName(u"labelInfo")

        self.gridLayout.addWidget(self.labelInfo, 4, 7, 1, 3)


        self.retranslateUi(mapPreviewer)

        QMetaObject.connectSlotsByName(mapPreviewer)
    # setupUi

    def retranslateUi(self, mapPreviewer):
        mapPreviewer.setWindowTitle(QCoreApplication.translate("mapPreviewer", u"Form", None))
        self.labelVersion.setText(QCoreApplication.translate("mapPreviewer", u"\u7248\u672c", None))
        self.comboVersion.setItemText(0, QCoreApplication.translate("mapPreviewer", u"1.21", None))
        self.comboVersion.setItemText(1, QCoreApplication.translate("mapPreviewer", u"1.20", None))
        self.comboVersion.setItemText(2, QCoreApplication.translate("mapPreviewer", u"1.19", None))
        self.comboVersion.setItemText(3, QCoreApplication.translate("mapPreviewer", u"1.18", None))

        self.labelRadius.setText(QCoreApplication.translate("mapPreviewer", u"\u89c6\u91ce\u534a\u5f84", None))
        self.btnStructures.setText(QCoreApplication.translate("mapPreviewer", u"\u7ed3\u6784 \u25be", None))
        self.btnCommon.setText(QCoreApplication.translate("mapPreviewer", u"\u5e38\u7528", None))
        self.btnAll.setText(QCoreApplication.translate("mapPreviewer", u"\u5168\u9009", None))
        self.btnRender.setText(QCoreApplication.translate("mapPreviewer", u"\u751f\u6210\u5730\u56fe", None))
        self.comboRadius.setItemText(0, QCoreApplication.translate("mapPreviewer", u"512", None))
        self.comboRadius.setItemText(1, QCoreApplication.translate("mapPreviewer", u"1024", None))
        self.comboRadius.setItemText(2, QCoreApplication.translate("mapPreviewer", u"2048", None))
        self.comboRadius.setItemText(3, QCoreApplication.translate("mapPreviewer", u"4096", None))

        self.labelSeed.setText(QCoreApplication.translate("mapPreviewer", u"\u79cd\u5b50", None))
        self.labelHover.setText(QCoreApplication.translate("mapPreviewer", u"\u60ac\u505c\u5730\u56fe\u67e5\u770b\u5750\u6807\u4e0e\u7fa4\u7cfb", None))
        self.labelInfo.setText(QCoreApplication.translate("mapPreviewer", u"\u5c31\u7eea", None))
    # retranslateUi

