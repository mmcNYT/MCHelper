# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'CommandGenerator.ui'
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
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QListWidget, QListWidgetItem,
    QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
    QSpacerItem, QSpinBox, QStackedWidget, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget)

class Ui_commandGenerator(object):
    def setupUi(self, commandGenerator):
        if not commandGenerator.objectName():
            commandGenerator.setObjectName(u"commandGenerator")
        commandGenerator.resize(1440, 920)
        self.rootLayout = QVBoxLayout(commandGenerator)
        self.rootLayout.setSpacing(6)
        self.rootLayout.setObjectName(u"rootLayout")
        self.rootLayout.setContentsMargins(8, 6, 8, 8)
        self.topBar = QHBoxLayout()
        self.topBar.setSpacing(8)
        self.topBar.setObjectName(u"topBar")
        self.versionLabel = QLabel(commandGenerator)
        self.versionLabel.setObjectName(u"versionLabel")

        self.topBar.addWidget(self.versionLabel)

        self.versionCombo = QComboBox(commandGenerator)
        self.versionCombo.setObjectName(u"versionCombo")
        self.versionCombo.setMinimumSize(QSize(110, 0))

        self.topBar.addWidget(self.versionCombo)

        self.topSep1 = QFrame(commandGenerator)
        self.topSep1.setObjectName(u"topSep1")
        self.topSep1.setFrameShape(QFrame.Shape.VLine)
        self.topSep1.setFrameShadow(QFrame.Shadow.Sunken)

        self.topBar.addWidget(self.topSep1)

        self.nsPrefixCheck = QCheckBox(commandGenerator)
        self.nsPrefixCheck.setObjectName(u"nsPrefixCheck")
        self.nsPrefixCheck.setChecked(True)

        self.topBar.addWidget(self.nsPrefixCheck)

        self.topSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.topBar.addItem(self.topSpacer)

        self.copyBtn = QPushButton(commandGenerator)
        self.copyBtn.setObjectName(u"copyBtn")

        self.topBar.addWidget(self.copyBtn)

        self.clearBtn = QPushButton(commandGenerator)
        self.clearBtn.setObjectName(u"clearBtn")

        self.topBar.addWidget(self.clearBtn)


        self.rootLayout.addLayout(self.topBar)

        self.bodyLayout = QHBoxLayout()
        self.bodyLayout.setSpacing(8)
        self.bodyLayout.setObjectName(u"bodyLayout")
        self.cmdTree = QTreeWidget(commandGenerator)
        self.cmdTree.setObjectName(u"cmdTree")
        self.cmdTree.setMinimumSize(QSize(180, 0))
        self.cmdTree.setMaximumSize(QSize(200, 16777215))
        self.cmdTree.setHeaderHidden(True)

        self.bodyLayout.addWidget(self.cmdTree)

        self.centerStack = QStackedWidget(commandGenerator)
        self.centerStack.setObjectName(u"centerStack")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        sizePolicy.setHorizontalStretch(1)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.centerStack.sizePolicy().hasHeightForWidth())
        self.centerStack.setSizePolicy(sizePolicy)
        self.pageUnsupported = QWidget()
        self.pageUnsupported.setObjectName(u"pageUnsupported")
        self.unsupportedLayout = QVBoxLayout(self.pageUnsupported)
        self.unsupportedLayout.setObjectName(u"unsupportedLayout")
        self.unsupportedLabel = QLabel(self.pageUnsupported)
        self.unsupportedLabel.setObjectName(u"unsupportedLabel")
        self.unsupportedLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.unsupportedLayout.addWidget(self.unsupportedLabel)

        self.centerStack.addWidget(self.pageUnsupported)
        self.pageGeneric = QWidget()
        self.pageGeneric.setObjectName(u"pageGeneric")
        self.genericLayout = QVBoxLayout(self.pageGeneric)
        self.genericLayout.setSpacing(6)
        self.genericLayout.setObjectName(u"genericLayout")
        self.genericLayout.setContentsMargins(0, 0, 0, 0)
        self.genericScroll = QScrollArea(self.pageGeneric)
        self.genericScroll.setObjectName(u"genericScroll")
        self.genericScroll.setWidgetResizable(True)
        self.genericHost = QWidget()
        self.genericHost.setObjectName(u"genericHost")
        self.genericHost.setGeometry(QRect(0, 0, 900, 700))
        self.genericHostLayout = QVBoxLayout(self.genericHost)
        self.genericHostLayout.setSpacing(8)
        self.genericHostLayout.setObjectName(u"genericHostLayout")
        self.genericTitle = QLabel(self.genericHost)
        self.genericTitle.setObjectName(u"genericTitle")
        font = QFont()
        font.setBold(True)
        self.genericTitle.setFont(font)

        self.genericHostLayout.addWidget(self.genericTitle)

        self.genericFormHost = QWidget(self.genericHost)
        self.genericFormHost.setObjectName(u"genericFormHost")
        self.genericFormHostLayout = QVBoxLayout(self.genericFormHost)
        self.genericFormHostLayout.setObjectName(u"genericFormHostLayout")
        self.genericFormHostLayout.setContentsMargins(0, 0, 0, 0)

        self.genericHostLayout.addWidget(self.genericFormHost)

        self.genericSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.genericHostLayout.addItem(self.genericSpacer)

        self.genericScroll.setWidget(self.genericHost)

        self.genericLayout.addWidget(self.genericScroll)

        self.centerStack.addWidget(self.pageGeneric)
        self.pageGive = QWidget()
        self.pageGive.setObjectName(u"pageGive")
        self.giveLayout = QVBoxLayout(self.pageGive)
        self.giveLayout.setSpacing(6)
        self.giveLayout.setObjectName(u"giveLayout")
        self.giveLayout.setContentsMargins(0, 0, 0, 0)
        self.giveScroll = QScrollArea(self.pageGive)
        self.giveScroll.setObjectName(u"giveScroll")
        self.giveScroll.setWidgetResizable(True)
        self.giveContent = QWidget()
        self.giveContent.setObjectName(u"giveContent")
        self.giveContentLayout = QVBoxLayout(self.giveContent)
        self.giveContentLayout.setSpacing(8)
        self.giveContentLayout.setObjectName(u"giveContentLayout")
        self.giveBaseBox = QGroupBox(self.giveContent)
        self.giveBaseBox.setObjectName(u"giveBaseBox")
        self.giveBaseGrid = QGridLayout(self.giveBaseBox)
        self.giveBaseGrid.setObjectName(u"giveBaseGrid")
        self.giveTargetLabel = QLabel(self.giveBaseBox)
        self.giveTargetLabel.setObjectName(u"giveTargetLabel")

        self.giveBaseGrid.addWidget(self.giveTargetLabel, 0, 0, 1, 1)

        self.giveTargetCombo = QComboBox(self.giveBaseBox)
        self.giveTargetCombo.setObjectName(u"giveTargetCombo")
        self.giveTargetCombo.setEditable(True)
        self.giveTargetCombo.setMinimumSize(QSize(260, 0))

        self.giveBaseGrid.addWidget(self.giveTargetCombo, 0, 1, 1, 1)

        self.giveTargetBuilderBtn = QPushButton(self.giveBaseBox)
        self.giveTargetBuilderBtn.setObjectName(u"giveTargetBuilderBtn")

        self.giveBaseGrid.addWidget(self.giveTargetBuilderBtn, 0, 2, 1, 1)

        self.giveCountLabel = QLabel(self.giveBaseBox)
        self.giveCountLabel.setObjectName(u"giveCountLabel")
        self.giveCountLabel.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.giveBaseGrid.addWidget(self.giveCountLabel, 0, 3, 1, 1)

        self.giveCountSpin = QSpinBox(self.giveBaseBox)
        self.giveCountSpin.setObjectName(u"giveCountSpin")
        self.giveCountSpin.setMinimum(1)
        self.giveCountSpin.setMaximum(6400)
        self.giveCountSpin.setValue(1)

        self.giveBaseGrid.addWidget(self.giveCountSpin, 0, 4, 1, 1)

        self.giveItemLabel = QLabel(self.giveBaseBox)
        self.giveItemLabel.setObjectName(u"giveItemLabel")

        self.giveBaseGrid.addWidget(self.giveItemLabel, 1, 0, 1, 1)

        self.giveItemCombo = QComboBox(self.giveBaseBox)
        self.giveItemCombo.setObjectName(u"giveItemCombo")
        self.giveItemCombo.setEditable(True)

        self.giveBaseGrid.addWidget(self.giveItemCombo, 1, 1, 1, 1)

        self.giveItemPickBtn = QPushButton(self.giveBaseBox)
        self.giveItemPickBtn.setObjectName(u"giveItemPickBtn")

        self.giveBaseGrid.addWidget(self.giveItemPickBtn, 1, 2, 1, 1)

        self.giveItemHint = QLabel(self.giveBaseBox)
        self.giveItemHint.setObjectName(u"giveItemHint")

        self.giveBaseGrid.addWidget(self.giveItemHint, 1, 3, 1, 2)


        self.giveContentLayout.addWidget(self.giveBaseBox)

        self.giveCompBox = QGroupBox(self.giveContent)
        self.giveCompBox.setObjectName(u"giveCompBox")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(1)
        sizePolicy1.setHeightForWidth(self.giveCompBox.sizePolicy().hasHeightForWidth())
        self.giveCompBox.setSizePolicy(sizePolicy1)
        self.giveCompLayout = QVBoxLayout(self.giveCompBox)
        self.giveCompLayout.setSpacing(6)
        self.giveCompLayout.setObjectName(u"giveCompLayout")
        self.giveCompAddRow = QHBoxLayout()
        self.giveCompAddRow.setObjectName(u"giveCompAddRow")
        self.giveCompAddLabel = QLabel(self.giveCompBox)
        self.giveCompAddLabel.setObjectName(u"giveCompAddLabel")

        self.giveCompAddRow.addWidget(self.giveCompAddLabel)

        self.giveCompCombo = QComboBox(self.giveCompBox)
        self.giveCompCombo.setObjectName(u"giveCompCombo")
        self.giveCompCombo.setMinimumSize(QSize(300, 0))

        self.giveCompAddRow.addWidget(self.giveCompCombo)

        self.giveCompAddBtn = QPushButton(self.giveCompBox)
        self.giveCompAddBtn.setObjectName(u"giveCompAddBtn")

        self.giveCompAddRow.addWidget(self.giveCompAddBtn)

        self.giveCompAddSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.giveCompAddRow.addItem(self.giveCompAddSpacer)


        self.giveCompLayout.addLayout(self.giveCompAddRow)

        self.giveCompScroll = QScrollArea(self.giveCompBox)
        self.giveCompScroll.setObjectName(u"giveCompScroll")
        self.giveCompScroll.setMinimumSize(QSize(0, 240))
        self.giveCompScroll.setWidgetResizable(True)
        self.giveCompHost = QWidget()
        self.giveCompHost.setObjectName(u"giveCompHost")
        self.giveCompHost.setGeometry(QRect(0, 0, 860, 236))
        self.giveCompHostLayout = QVBoxLayout(self.giveCompHost)
        self.giveCompHostLayout.setSpacing(6)
        self.giveCompHostLayout.setObjectName(u"giveCompHostLayout")
        self.giveCompHostSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.giveCompHostLayout.addItem(self.giveCompHostSpacer)

        self.giveCompScroll.setWidget(self.giveCompHost)

        self.giveCompLayout.addWidget(self.giveCompScroll)


        self.giveContentLayout.addWidget(self.giveCompBox)

        self.giveScroll.setWidget(self.giveContent)

        self.giveLayout.addWidget(self.giveScroll)

        self.centerStack.addWidget(self.pageGive)

        self.bodyLayout.addWidget(self.centerStack)

        self.rightCol = QWidget(commandGenerator)
        self.rightCol.setObjectName(u"rightCol")
        self.rightCol.setMinimumSize(QSize(250, 0))
        self.rightCol.setMaximumSize(QSize(290, 16777215))
        self.rightLayout = QVBoxLayout(self.rightCol)
        self.rightLayout.setSpacing(8)
        self.rightLayout.setObjectName(u"rightLayout")
        self.rightLayout.setContentsMargins(0, 0, 0, 0)
        self.previewBox = QGroupBox(self.rightCol)
        self.previewBox.setObjectName(u"previewBox")
        sizePolicy1.setHeightForWidth(self.previewBox.sizePolicy().hasHeightForWidth())
        self.previewBox.setSizePolicy(sizePolicy1)
        self.previewLayout = QVBoxLayout(self.previewBox)
        self.previewLayout.setSpacing(6)
        self.previewLayout.setObjectName(u"previewLayout")
        self.previewTopRow = QHBoxLayout()
        self.previewTopRow.setObjectName(u"previewTopRow")
        self.previewIcon = QLabel(self.previewBox)
        self.previewIcon.setObjectName(u"previewIcon")
        self.previewIcon.setMinimumSize(QSize(64, 64))
        self.previewIcon.setMaximumSize(QSize(64, 64))
        self.previewIcon.setFrameShape(QFrame.Shape.StyledPanel)
        self.previewIcon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.previewTopRow.addWidget(self.previewIcon)

        self.previewTextCol = QVBoxLayout()
        self.previewTextCol.setSpacing(2)
        self.previewTextCol.setObjectName(u"previewTextCol")
        self.previewName = QLabel(self.previewBox)
        self.previewName.setObjectName(u"previewName")
        self.previewName.setFont(font)
        self.previewName.setWordWrap(True)

        self.previewTextCol.addWidget(self.previewName)

        self.previewSub = QLabel(self.previewBox)
        self.previewSub.setObjectName(u"previewSub")
        self.previewSub.setWordWrap(True)

        self.previewTextCol.addWidget(self.previewSub)


        self.previewTopRow.addLayout(self.previewTextCol)


        self.previewLayout.addLayout(self.previewTopRow)

        self.previewEnch = QLabel(self.previewBox)
        self.previewEnch.setObjectName(u"previewEnch")
        self.previewEnch.setWordWrap(True)
        self.previewEnch.setAlignment(Qt.AlignmentFlag.AlignLeading|Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignTop)

        self.previewLayout.addWidget(self.previewEnch)


        self.rightLayout.addWidget(self.previewBox)

        self.outputBox = QGroupBox(self.rightCol)
        self.outputBox.setObjectName(u"outputBox")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(2)
        sizePolicy2.setHeightForWidth(self.outputBox.sizePolicy().hasHeightForWidth())
        self.outputBox.setSizePolicy(sizePolicy2)
        self.outputLayout = QVBoxLayout(self.outputBox)
        self.outputLayout.setSpacing(6)
        self.outputLayout.setObjectName(u"outputLayout")
        self.outputEdit = QPlainTextEdit(self.outputBox)
        self.outputEdit.setObjectName(u"outputEdit")
        self.outputEdit.setMinimumSize(QSize(0, 100))
        self.outputEdit.setReadOnly(True)

        self.outputLayout.addWidget(self.outputEdit)

        self.outputBtnRow = QHBoxLayout()
        self.outputBtnRow.setObjectName(u"outputBtnRow")
        self.outputLenLabel = QLabel(self.outputBox)
        self.outputLenLabel.setObjectName(u"outputLenLabel")

        self.outputBtnRow.addWidget(self.outputLenLabel)

        self.outputSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.outputBtnRow.addItem(self.outputSpacer)

        self.outputCopyBtn = QPushButton(self.outputBox)
        self.outputCopyBtn.setObjectName(u"outputCopyBtn")

        self.outputBtnRow.addWidget(self.outputCopyBtn)


        self.outputLayout.addLayout(self.outputBtnRow)


        self.rightLayout.addWidget(self.outputBox)

        self.checkBox = QGroupBox(self.rightCol)
        self.checkBox.setObjectName(u"checkBox")
        sizePolicy3 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        sizePolicy3.setHorizontalStretch(0)
        sizePolicy3.setVerticalStretch(0)
        sizePolicy3.setHeightForWidth(self.checkBox.sizePolicy().hasHeightForWidth())
        self.checkBox.setSizePolicy(sizePolicy3)
        self.checkLayout = QVBoxLayout(self.checkBox)
        self.checkLayout.setSpacing(4)
        self.checkLayout.setObjectName(u"checkLayout")
        self.checkTitleLabel = QLabel(self.checkBox)
        self.checkTitleLabel.setObjectName(u"checkTitleLabel")
        self.checkTitleLabel.setWordWrap(True)

        self.checkLayout.addWidget(self.checkTitleLabel)

        self.checkList = QListWidget(self.checkBox)
        self.checkList.setObjectName(u"checkList")
        self.checkList.setMinimumSize(QSize(0, 70))
        self.checkList.setMaximumSize(QSize(16777215, 120))
        self.checkList.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

        self.checkLayout.addWidget(self.checkList)


        self.rightLayout.addWidget(self.checkBox)


        self.bodyLayout.addWidget(self.rightCol)


        self.rootLayout.addLayout(self.bodyLayout)


        self.retranslateUi(commandGenerator)

        self.centerStack.setCurrentIndex(0)


        QMetaObject.connectSlotsByName(commandGenerator)
    # setupUi

    def retranslateUi(self, commandGenerator):
        commandGenerator.setWindowTitle(QCoreApplication.translate("commandGenerator", u"\u6307\u4ee4\u751f\u6210\u5668", None))
        self.versionLabel.setText(QCoreApplication.translate("commandGenerator", u"\u7248\u672c", None))
        self.nsPrefixCheck.setText(QCoreApplication.translate("commandGenerator", u"minecraft: \u524d\u7f00", None))
        self.copyBtn.setText(QCoreApplication.translate("commandGenerator", u"\u590d\u5236\u6307\u4ee4", None))
        self.clearBtn.setText(QCoreApplication.translate("commandGenerator", u"\u6e05\u7a7a\u53c2\u6570", None))
        ___qtreewidgetitem = self.cmdTree.headerItem()
        ___qtreewidgetitem.setText(0, QCoreApplication.translate("commandGenerator", u"\u6307\u4ee4", None))
        self.unsupportedLabel.setText(QCoreApplication.translate("commandGenerator", u"\u8be5\u6307\u4ee4\u5c1a\u672a\u5b9e\u73b0\uff0c\u656c\u8bf7\u671f\u5f85\u3002", None))
        self.genericTitle.setText("")
        self.giveBaseBox.setTitle(QCoreApplication.translate("commandGenerator", u"\u57fa\u7840\u53c2\u6570", None))
        self.giveTargetLabel.setText(QCoreApplication.translate("commandGenerator", u"\u76ee\u6807", None))
        self.giveTargetBuilderBtn.setText(QCoreApplication.translate("commandGenerator", u"\u9009\u62e9\u5668\u2026", None))
        self.giveCountLabel.setText(QCoreApplication.translate("commandGenerator", u"\u6570\u91cf", None))
        self.giveItemLabel.setText(QCoreApplication.translate("commandGenerator", u"\u7269\u54c1", None))
        self.giveItemPickBtn.setText(QCoreApplication.translate("commandGenerator", u"\u9009\u62e9\u7269\u54c1\u2026", None))
        self.giveItemHint.setText(QCoreApplication.translate("commandGenerator", u"\u53ef\u76f4\u63a5\u8f93\u5165 id\uff0c\u6216\u7528\u300c\u9009\u62e9\u7269\u54c1\u300d\u6309\u4e2d\u6587\u540d\u641c\u7d22", None))
        self.giveCompBox.setTitle(QCoreApplication.translate("commandGenerator", u"\u6570\u636e\u7ec4\u4ef6", None))
        self.giveCompAddLabel.setText(QCoreApplication.translate("commandGenerator", u"\u6dfb\u52a0\u7ec4\u4ef6", None))
        self.giveCompAddBtn.setText(QCoreApplication.translate("commandGenerator", u"\u6dfb\u52a0", None))
        self.previewBox.setTitle(QCoreApplication.translate("commandGenerator", u"\u9884\u89c8", None))
        self.previewIcon.setText("")
        self.previewName.setText("")
        self.previewSub.setText("")
        self.previewEnch.setText("")
        self.outputBox.setTitle(QCoreApplication.translate("commandGenerator", u"\u8f93\u51fa", None))
        self.outputLenLabel.setText("")
        self.outputCopyBtn.setText(QCoreApplication.translate("commandGenerator", u"\u590d\u5236", None))
        self.checkBox.setTitle(QCoreApplication.translate("commandGenerator", u"\u6821\u9a8c", None))
        self.checkTitleLabel.setText("")
    # retranslateUi

