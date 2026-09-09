# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'SeedReverser.ui'
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
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QGridLayout,
    QGroupBox, QHeaderView, QLabel, QLineEdit,
    QProgressBar, QPushButton, QSizePolicy, QTextBrowser,
    QTreeWidget, QTreeWidgetItem, QWidget)

class Ui_seedReverser(object):
    def setupUi(self, seedReverser):
        if not seedReverser.objectName():
            seedReverser.setObjectName(u"seedReverser")
        seedReverser.resize(1170, 826)
        self.layoutWidget = QWidget(seedReverser)
        self.layoutWidget.setObjectName(u"layoutWidget")
        self.layoutWidget.setGeometry(QRect(20, 0, 1135, 811))
        self.gridLayout = QGridLayout(self.layoutWidget)
        self.gridLayout.setObjectName(u"gridLayout")
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.structTypeLabel = QLabel(self.layoutWidget)
        self.structTypeLabel.setObjectName(u"structTypeLabel")

        self.gridLayout.addWidget(self.structTypeLabel, 1, 0, 1, 1)

        self.verifyButton = QPushButton(self.layoutWidget)
        self.verifyButton.setObjectName(u"verifyButton")

        self.gridLayout.addWidget(self.verifyButton, 6, 2, 1, 2)

        self.addButton = QPushButton(self.layoutWidget)
        self.addButton.setObjectName(u"addButton")

        self.gridLayout.addWidget(self.addButton, 2, 9, 1, 1)

        self.coordXEdit = QLineEdit(self.layoutWidget)
        self.coordXEdit.setObjectName(u"coordXEdit")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.coordXEdit.sizePolicy().hasHeightForWidth())
        self.coordXEdit.setSizePolicy(sizePolicy)

        self.gridLayout.addWidget(self.coordXEdit, 1, 3, 1, 2)

        self.clearAllButton = QPushButton(self.layoutWidget)
        self.clearAllButton.setObjectName(u"clearAllButton")

        self.gridLayout.addWidget(self.clearAllButton, 6, 4, 1, 2)

        self.structList = QTreeWidget(self.layoutWidget)
        __qtreewidgetitem = QTreeWidgetItem()
        __qtreewidgetitem.setText(0, u"1")
        self.structList.setHeaderItem(__qtreewidgetitem)
        self.structList.setObjectName(u"structList")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Expanding)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.structList.sizePolicy().hasHeightForWidth())
        self.structList.setSizePolicy(sizePolicy1)

        self.gridLayout.addWidget(self.structList, 2, 0, 3, 9)

        self.clearInputButton = QPushButton(self.layoutWidget)
        self.clearInputButton.setObjectName(u"clearInputButton")

        self.gridLayout.addWidget(self.clearInputButton, 4, 9, 1, 1)

        self.infoProgressBar = QProgressBar(self.layoutWidget)
        self.infoProgressBar.setObjectName(u"infoProgressBar")
        self.infoProgressBar.setValue(24)

        self.gridLayout.addWidget(self.infoProgressBar, 5, 1, 1, 4)

        self.pasteF3CButton = QPushButton(self.layoutWidget)
        self.pasteF3CButton.setObjectName(u"pasteF3CButton")

        self.gridLayout.addWidget(self.pasteF3CButton, 3, 9, 1, 1)

        self.informationBrowser = QTextBrowser(self.layoutWidget)
        self.informationBrowser.setObjectName(u"informationBrowser")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.MinimumExpanding)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.informationBrowser.sizePolicy().hasHeightForWidth())
        self.informationBrowser.setSizePolicy(sizePolicy2)

        self.gridLayout.addWidget(self.informationBrowser, 7, 0, 1, 9)

        self.versionCombo = QComboBox(self.layoutWidget)
        self.versionCombo.setObjectName(u"versionCombo")
        sizePolicy.setHeightForWidth(self.versionCombo.sizePolicy().hasHeightForWidth())
        self.versionCombo.setSizePolicy(sizePolicy)

        self.gridLayout.addWidget(self.versionCombo, 0, 1, 1, 2)

        self.infoHintLabel = QLabel(self.layoutWidget)
        self.infoHintLabel.setObjectName(u"infoHintLabel")

        self.gridLayout.addWidget(self.infoHintLabel, 5, 5, 1, 4)

        self.structTypeCombo = QComboBox(self.layoutWidget)
        self.structTypeCombo.setObjectName(u"structTypeCombo")

        self.gridLayout.addWidget(self.structTypeCombo, 1, 1, 1, 2)

        self.biomeModeCheckBox = QCheckBox(self.layoutWidget)
        self.biomeModeCheckBox.setObjectName(u"biomeModeCheckBox")
        sizePolicy.setHeightForWidth(self.biomeModeCheckBox.sizePolicy().hasHeightForWidth())
        self.biomeModeCheckBox.setSizePolicy(sizePolicy)

        self.gridLayout.addWidget(self.biomeModeCheckBox, 0, 3, 1, 2)

        self.calcButton = QPushButton(self.layoutWidget)
        self.calcButton.setObjectName(u"calcButton")

        self.gridLayout.addWidget(self.calcButton, 6, 0, 1, 2)

        self.versionLabel = QLabel(self.layoutWidget)
        self.versionLabel.setObjectName(u"versionLabel")
        sizePolicy.setHeightForWidth(self.versionLabel.sizePolicy().hasHeightForWidth())
        self.versionLabel.setSizePolicy(sizePolicy)

        self.gridLayout.addWidget(self.versionLabel, 0, 0, 1, 1)

        self.infoLabel = QLabel(self.layoutWidget)
        self.infoLabel.setObjectName(u"infoLabel")

        self.gridLayout.addWidget(self.infoLabel, 5, 0, 1, 1)

        self.refineGroupBox = QGroupBox(self.layoutWidget)
        self.refineGroupBox.setObjectName(u"refineGroupBox")
        self.gridLayout_2 = QGridLayout(self.refineGroupBox)
        self.gridLayout_2.setObjectName(u"gridLayout_2")
        self.biomeXEdit = QLineEdit(self.refineGroupBox)
        self.biomeXEdit.setObjectName(u"biomeXEdit")

        self.gridLayout_2.addWidget(self.biomeXEdit, 0, 2, 1, 1)

        self.candidateFromCalcBtn = QPushButton(self.refineGroupBox)
        self.candidateFromCalcBtn.setObjectName(u"candidateFromCalcBtn")

        self.gridLayout_2.addWidget(self.candidateFromCalcBtn, 0, 1, 1, 1)

        self.biomeObsList = QTreeWidget(self.refineGroupBox)
        __qtreewidgetitem1 = QTreeWidgetItem()
        __qtreewidgetitem1.setText(0, u"1")
        self.biomeObsList.setHeaderItem(__qtreewidgetitem1)
        self.biomeObsList.setObjectName(u"biomeObsList")

        self.gridLayout_2.addWidget(self.biomeObsList, 2, 0, 2, 6)

        self.biomeNameCombo = QComboBox(self.refineGroupBox)
        self.biomeNameCombo.setObjectName(u"biomeNameCombo")
        self.biomeNameCombo.setEditable(True)

        self.gridLayout_2.addWidget(self.biomeNameCombo, 0, 5, 1, 1)

        self.candidateSeedEdit = QLineEdit(self.refineGroupBox)
        self.candidateSeedEdit.setObjectName(u"candidateSeedEdit")

        self.gridLayout_2.addWidget(self.candidateSeedEdit, 0, 0, 1, 1)

        self.pushButton = QPushButton(self.refineGroupBox)
        self.pushButton.setObjectName(u"pushButton")

        self.gridLayout_2.addWidget(self.pushButton, 2, 9, 1, 1)

        self.clearBiomeBtn = QPushButton(self.refineGroupBox)
        self.clearBiomeBtn.setObjectName(u"clearBiomeBtn")

        self.gridLayout_2.addWidget(self.clearBiomeBtn, 4, 9, 1, 1)

        self.worldSeedDetailBrowser = QTextBrowser(self.refineGroupBox)
        self.worldSeedDetailBrowser.setObjectName(u"worldSeedDetailBrowser")

        self.gridLayout_2.addWidget(self.worldSeedDetailBrowser, 6, 0, 1, 6)

        self.refineInfoLabel = QLabel(self.refineGroupBox)
        self.refineInfoLabel.setObjectName(u"refineInfoLabel")

        self.gridLayout_2.addWidget(self.refineInfoLabel, 4, 5, 1, 1)

        self.biomeZEdit = QLineEdit(self.refineGroupBox)
        self.biomeZEdit.setObjectName(u"biomeZEdit")

        self.gridLayout_2.addWidget(self.biomeZEdit, 0, 3, 1, 1)

        self.biomeYEdit = QLineEdit(self.refineGroupBox)
        self.biomeYEdit.setObjectName(u"biomeYEdit")

        self.gridLayout_2.addWidget(self.biomeYEdit, 0, 4, 1, 1)

        self.addBiomeObsBtn = QPushButton(self.refineGroupBox)
        self.addBiomeObsBtn.setObjectName(u"addBiomeObsBtn")

        self.gridLayout_2.addWidget(self.addBiomeObsBtn, 0, 9, 1, 1)

        self.refineClearBtn = QPushButton(self.refineGroupBox)
        self.refineClearBtn.setObjectName(u"refineClearBtn")
        sizePolicy3 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sizePolicy3.setHorizontalStretch(0)
        sizePolicy3.setVerticalStretch(0)
        sizePolicy3.setHeightForWidth(self.refineClearBtn.sizePolicy().hasHeightForWidth())
        self.refineClearBtn.setSizePolicy(sizePolicy3)

        self.gridLayout_2.addWidget(self.refineClearBtn, 4, 1, 1, 1)

        self.refineButton = QPushButton(self.refineGroupBox)
        self.refineButton.setObjectName(u"refineButton")
        sizePolicy3.setHeightForWidth(self.refineButton.sizePolicy().hasHeightForWidth())
        self.refineButton.setSizePolicy(sizePolicy3)

        self.gridLayout_2.addWidget(self.refineButton, 4, 0, 1, 1)

        self.refineProgressBar = QProgressBar(self.refineGroupBox)
        self.refineProgressBar.setObjectName(u"refineProgressBar")
        self.refineProgressBar.setValue(24)

        self.gridLayout_2.addWidget(self.refineProgressBar, 4, 2, 1, 2)


        self.gridLayout.addWidget(self.refineGroupBox, 8, 0, 4, 10)

        self.coordZEdit = QLineEdit(self.layoutWidget)
        self.coordZEdit.setObjectName(u"coordZEdit")
        sizePolicy.setHeightForWidth(self.coordZEdit.sizePolicy().hasHeightForWidth())
        self.coordZEdit.setSizePolicy(sizePolicy)
        self.coordZEdit.setMinimumSize(QSize(0, 0))

        self.gridLayout.addWidget(self.coordZEdit, 1, 5, 1, 1)


        self.retranslateUi(seedReverser)

        QMetaObject.connectSlotsByName(seedReverser)
    # setupUi

    def retranslateUi(self, seedReverser):
        seedReverser.setWindowTitle(QCoreApplication.translate("seedReverser", u"Form", None))
        self.structTypeLabel.setText(QCoreApplication.translate("seedReverser", u"\u7ed3\u6784\u7c7b\u578b", None))
        self.verifyButton.setText(QCoreApplication.translate("seedReverser", u"\u9a8c\u8bc1\u5019\u9009\u79cd\u5b50", None))
        self.addButton.setText(QCoreApplication.translate("seedReverser", u"\u6dfb\u52a0", None))
        self.coordXEdit.setPlaceholderText(QCoreApplication.translate("seedReverser", u"X", None))
        self.clearAllButton.setText(QCoreApplication.translate("seedReverser", u"\u6e05\u7a7a\u5168\u90e8", None))
        self.clearInputButton.setText(QCoreApplication.translate("seedReverser", u"\u6e05\u9664", None))
        self.pasteF3CButton.setText(QCoreApplication.translate("seedReverser", u"\u7c98\u8d34F3+C", None))
        self.infoHintLabel.setText("")
        self.biomeModeCheckBox.setText(QCoreApplication.translate("seedReverser", u"\u7fa4\u7cfb\u6a21\u5f0f", None))
        self.calcButton.setText(QCoreApplication.translate("seedReverser", u"\u8ba1\u7b97", None))
        self.versionLabel.setText(QCoreApplication.translate("seedReverser", u"\u76ee\u6807\u7248\u672c", None))
        self.infoLabel.setText(QCoreApplication.translate("seedReverser", u"\u4fe1\u606f\u91cf", None))
        self.refineGroupBox.setTitle(QCoreApplication.translate("seedReverser", u"\u4e16\u754c\u79cd\u5b50\u7cbe\u5316\uff08\u7fa4\u7cfb\u9a8c\u8bc1\uff09", None))
        self.biomeXEdit.setPlaceholderText(QCoreApplication.translate("seedReverser", u"X", None))
        self.candidateFromCalcBtn.setText(QCoreApplication.translate("seedReverser", u"\u4ece\u8ba1\u7b97\u7ed3\u679c\u5bfc\u5165", None))
        self.biomeNameCombo.setPlaceholderText(QCoreApplication.translate("seedReverser", u"\u7fa4\u7cfb\u540d", None))
        self.candidateSeedEdit.setPlaceholderText(QCoreApplication.translate("seedReverser", u"\u7ed3\u6784\u79cd\u5019\u9009", None))
        self.pushButton.setText(QCoreApplication.translate("seedReverser", u"\u7c98\u8d34F3+C", None))
        self.clearBiomeBtn.setText(QCoreApplication.translate("seedReverser", u"\u6e05\u7a7a\u5217\u8868", None))
        self.refineInfoLabel.setText("")
        self.biomeZEdit.setPlaceholderText(QCoreApplication.translate("seedReverser", u"Z", None))
        self.biomeYEdit.setPlaceholderText(QCoreApplication.translate("seedReverser", u"Y", None))
        self.addBiomeObsBtn.setText(QCoreApplication.translate("seedReverser", u"\u6dfb\u52a0", None))
        self.refineClearBtn.setText(QCoreApplication.translate("seedReverser", u"\u6e05\u9664\u7cbe\u5316", None))
        self.refineButton.setText(QCoreApplication.translate("seedReverser", u"\u5f00\u59cb\u7cbe\u5316", None))
        self.coordZEdit.setPlaceholderText(QCoreApplication.translate("seedReverser", u"Z", None))
    # retranslateUi

