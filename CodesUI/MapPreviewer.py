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
        self.layoutWidget = QWidget(mapPreviewer)
        self.layoutWidget.setObjectName(u"layoutWidget")
        self.layoutWidget.setGeometry(QRect(10, 10, 1061, 781))
        self.gridLayout = QGridLayout(self.layoutWidget)
        self.gridLayout.setObjectName(u"gridLayout")
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.btnStructures = QPushButton(self.layoutWidget)
        self.btnStructures.setObjectName(u"btnStructures")

        self.gridLayout.addWidget(self.btnStructures, 0, 6, 2, 1)

        self.btnRender = QPushButton(self.layoutWidget)
        self.btnRender.setObjectName(u"btnRender")

        self.gridLayout.addWidget(self.btnRender, 0, 8, 2, 1)

        self.zEdit = QLineEdit(self.layoutWidget)
        self.zEdit.setObjectName(u"zEdit")

        self.gridLayout.addWidget(self.zEdit, 2, 2, 1, 1)

        self.labelInfo = QLabel(self.layoutWidget)
        self.labelInfo.setObjectName(u"labelInfo")

        self.gridLayout.addWidget(self.labelInfo, 5, 7, 1, 2)

        self.progressRender = QProgressBar(self.layoutWidget)
        self.progressRender.setObjectName(u"progressRender")
        self.progressRender.setValue(24)

        self.gridLayout.addWidget(self.progressRender, 4, 0, 1, 9)

        self.viewMap = QGraphicsView(self.layoutWidget)
        self.viewMap.setObjectName(u"viewMap")

        self.gridLayout.addWidget(self.viewMap, 3, 0, 1, 9)

        self.labelHover = QLabel(self.layoutWidget)
        self.labelHover.setObjectName(u"labelHover")

        self.gridLayout.addWidget(self.labelHover, 5, 0, 1, 4)

        self.xEdit = QLineEdit(self.layoutWidget)
        self.xEdit.setObjectName(u"xEdit")

        self.gridLayout.addWidget(self.xEdit, 2, 1, 1, 1)

        self.editSeed = QLineEdit(self.layoutWidget)
        self.editSeed.setObjectName(u"editSeed")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.editSeed.sizePolicy().hasHeightForWidth())
        self.editSeed.setSizePolicy(sizePolicy)

        self.gridLayout.addWidget(self.editSeed, 0, 3, 2, 1)

        self.comboRadius = QComboBox(self.layoutWidget)
        self.comboRadius.addItem("")
        self.comboRadius.addItem("")
        self.comboRadius.setObjectName(u"comboRadius")

        self.gridLayout.addWidget(self.comboRadius, 1, 5, 1, 1)

        self.labelVersion = QLabel(self.layoutWidget)
        self.labelVersion.setObjectName(u"labelVersion")

        self.gridLayout.addWidget(self.labelVersion, 0, 0, 2, 1)

        self.labelSeed = QLabel(self.layoutWidget)
        self.labelSeed.setObjectName(u"labelSeed")
        self.labelSeed.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.gridLayout.addWidget(self.labelSeed, 1, 2, 1, 1)

        self.labelRadius = QLabel(self.layoutWidget)
        self.labelRadius.setObjectName(u"labelRadius")

        self.gridLayout.addWidget(self.labelRadius, 0, 4, 2, 1)

        self.locateLabel = QLabel(self.layoutWidget)
        self.locateLabel.setObjectName(u"locateLabel")

        self.gridLayout.addWidget(self.locateLabel, 2, 0, 1, 1)

        self.comboVersion = QComboBox(self.layoutWidget)
        self.comboVersion.addItem("")
        self.comboVersion.addItem("")
        self.comboVersion.addItem("")
        self.comboVersion.addItem("")
        self.comboVersion.setObjectName(u"comboVersion")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.comboVersion.sizePolicy().hasHeightForWidth())
        self.comboVersion.setSizePolicy(sizePolicy1)

        self.gridLayout.addWidget(self.comboVersion, 0, 1, 2, 1)

        self.worldCombo = QComboBox(self.layoutWidget)
        self.worldCombo.addItem("")
        self.worldCombo.addItem("")
        self.worldCombo.addItem("")
        self.worldCombo.setObjectName(u"worldCombo")

        self.gridLayout.addWidget(self.worldCombo, 1, 7, 1, 1)

        self.structureLocateLabel = QLabel(self.layoutWidget)
        self.structureLocateLabel.setObjectName(u"structureLocateLabel")

        self.gridLayout.addWidget(self.structureLocateLabel, 2, 4, 1, 1)

        self.structureLocateList = QComboBox(self.layoutWidget)
        self.structureLocateList.setObjectName(u"structureLocateList")

        self.gridLayout.addWidget(self.structureLocateList, 2, 5, 1, 1)

        self.biomeLocateLabel = QLabel(self.layoutWidget)
        self.biomeLocateLabel.setObjectName(u"biomeLocateLabel")
        self.biomeLocateLabel.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.gridLayout.addWidget(self.biomeLocateLabel, 2, 6, 1, 1)

        self.biomeLocateList = QComboBox(self.layoutWidget)
        self.biomeLocateList.setObjectName(u"biomeLocateList")

        self.gridLayout.addWidget(self.biomeLocateList, 2, 7, 1, 1)


        self.retranslateUi(mapPreviewer)

        QMetaObject.connectSlotsByName(mapPreviewer)
    # setupUi

    def retranslateUi(self, mapPreviewer):
        mapPreviewer.setWindowTitle(QCoreApplication.translate("mapPreviewer", u"Form", None))
        self.btnStructures.setText(QCoreApplication.translate("mapPreviewer", u"\u9009\u62e9\u663e\u793a\u7684\u7ed3\u6784 ", None))
        self.btnRender.setText(QCoreApplication.translate("mapPreviewer", u"\u751f\u6210\u5730\u56fe", None))
        self.zEdit.setPlaceholderText(QCoreApplication.translate("mapPreviewer", u"Z", None))
        self.labelInfo.setText(QCoreApplication.translate("mapPreviewer", u"\u5c31\u7eea", None))
        self.labelHover.setText(QCoreApplication.translate("mapPreviewer", u"\u60ac\u505c\u5730\u56fe\u67e5\u770b\u5750\u6807\u4e0e\u7fa4\u7cfb", None))
        self.xEdit.setPlaceholderText(QCoreApplication.translate("mapPreviewer", u"X", None))
        self.comboRadius.setItemText(0, QCoreApplication.translate("mapPreviewer", u"2048", None))
        self.comboRadius.setItemText(1, QCoreApplication.translate("mapPreviewer", u"4096", None))

        self.labelVersion.setText(QCoreApplication.translate("mapPreviewer", u"\u7248\u672c", None))
        self.labelSeed.setText(QCoreApplication.translate("mapPreviewer", u"\u79cd\u5b50", None))
        self.labelRadius.setText(QCoreApplication.translate("mapPreviewer", u"\u89c6\u91ce\u534a\u5f84", None))
        self.locateLabel.setText(QCoreApplication.translate("mapPreviewer", u"\u5b9a\u4f4d", None))
        self.comboVersion.setItemText(0, QCoreApplication.translate("mapPreviewer", u"1.21", None))
        self.comboVersion.setItemText(1, QCoreApplication.translate("mapPreviewer", u"1.20", None))
        self.comboVersion.setItemText(2, QCoreApplication.translate("mapPreviewer", u"1.19", None))
        self.comboVersion.setItemText(3, QCoreApplication.translate("mapPreviewer", u"1.18", None))

        self.worldCombo.setItemText(0, QCoreApplication.translate("mapPreviewer", u"\u4e3b\u4e16\u754c", None))
        self.worldCombo.setItemText(1, QCoreApplication.translate("mapPreviewer", u"\u4e0b\u754c", None))
        self.worldCombo.setItemText(2, QCoreApplication.translate("mapPreviewer", u"\u672b\u5730", None))

        self.structureLocateLabel.setText(QCoreApplication.translate("mapPreviewer", u"\u7ed3\u6784\u5b9a\u4f4d", None))
        self.biomeLocateLabel.setText(QCoreApplication.translate("mapPreviewer", u"\u7fa4\u7cfb\u5b9a\u4f4d", None))
    # retranslateUi

