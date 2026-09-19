# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'StructurePreviewer.ui'
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
from PySide6.QtWidgets import (QApplication, QComboBox, QGridLayout, QGroupBox,
    QHeaderView, QLabel, QLineEdit, QProgressBar,
    QPushButton, QSizePolicy, QSlider, QTreeWidget,
    QTreeWidgetItem, QWidget)

class Ui_structurePreviewer(object):
    def setupUi(self, structurePreviewer):
        if not structurePreviewer.objectName():
            structurePreviewer.setObjectName(u"structurePreviewer")
        structurePreviewer.resize(1170, 826)
        self.layoutWidget = QWidget(structurePreviewer)
        self.layoutWidget.setObjectName(u"layoutWidget")
        self.layoutWidget.setGeometry(QRect(10, 10, 1151, 801))
        self.gridLayout = QGridLayout(self.layoutWidget)
        self.gridLayout.setObjectName(u"gridLayout")
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.visionLabel = QLabel(self.layoutWidget)
        self.visionLabel.setObjectName(u"visionLabel")

        self.gridLayout.addWidget(self.visionLabel, 0, 0, 1, 1)

        self.versionCombo = QComboBox(self.layoutWidget)
        self.versionCombo.setObjectName(u"versionCombo")

        self.gridLayout.addWidget(self.versionCombo, 0, 1, 1, 2)

        self.structureLabel = QLabel(self.layoutWidget)
        self.structureLabel.setObjectName(u"structureLabel")

        self.gridLayout.addWidget(self.structureLabel, 0, 3, 1, 2)

        self.structCombo = QComboBox(self.layoutWidget)
        self.structCombo.setObjectName(u"structCombo")

        self.gridLayout.addWidget(self.structCombo, 0, 5, 1, 2)

        self.label_3 = QLabel(self.layoutWidget)
        self.label_3.setObjectName(u"label_3")
        self.label_3.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.gridLayout.addWidget(self.label_3, 0, 7, 1, 1)

        self.seedEdit = QLineEdit(self.layoutWidget)
        self.seedEdit.setObjectName(u"seedEdit")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.seedEdit.sizePolicy().hasHeightForWidth())
        self.seedEdit.setSizePolicy(sizePolicy)

        self.gridLayout.addWidget(self.seedEdit, 0, 8, 1, 1)

        self.coordZEdit = QLineEdit(self.layoutWidget)
        self.coordZEdit.setObjectName(u"coordZEdit")

        self.gridLayout.addWidget(self.coordZEdit, 1, 3, 1, 2)

        self.infoGroupBox = QGroupBox(self.layoutWidget)
        self.infoGroupBox.setObjectName(u"infoGroupBox")
        self.infoLabel = QLabel(self.infoGroupBox)
        self.infoLabel.setObjectName(u"infoLabel")
        self.infoLabel.setGeometry(QRect(10, 20, 281, 201))

        self.gridLayout.addWidget(self.infoGroupBox, 2, 9, 1, 1)

        self.locateGroupBox = QGroupBox(self.layoutWidget)
        self.locateGroupBox.setObjectName(u"locateGroupBox")
        self.treeWidget = QTreeWidget(self.locateGroupBox)
        __qtreewidgetitem = QTreeWidgetItem()
        __qtreewidgetitem.setText(0, u"1")
        self.treeWidget.setHeaderItem(__qtreewidgetitem)
        self.treeWidget.setObjectName(u"treeWidget")
        self.treeWidget.setGeometry(QRect(0, 20, 291, 211))

        self.gridLayout.addWidget(self.locateGroupBox, 3, 9, 1, 1)

        self.chestsGroupBox = QGroupBox(self.layoutWidget)
        self.chestsGroupBox.setObjectName(u"chestsGroupBox")
        self.chestList = QTreeWidget(self.chestsGroupBox)
        __qtreewidgetitem1 = QTreeWidgetItem()
        __qtreewidgetitem1.setText(0, u"1")
        self.chestList.setHeaderItem(__qtreewidgetitem1)
        self.chestList.setObjectName(u"chestList")
        self.chestList.setGeometry(QRect(0, 20, 291, 211))

        self.gridLayout.addWidget(self.chestsGroupBox, 4, 9, 1, 1)

        self.snapshotLabel = QLabel(self.layoutWidget)
        self.snapshotLabel.setObjectName(u"snapshotLabel")

        self.gridLayout.addWidget(self.snapshotLabel, 5, 9, 1, 1)

        self.viewportPlaceholder = QLabel(self.layoutWidget)
        self.viewportPlaceholder.setObjectName(u"viewportPlaceholder")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.viewportPlaceholder.sizePolicy().hasHeightForWidth())
        self.viewportPlaceholder.setSizePolicy(sizePolicy1)
        self.viewportPlaceholder.setMinimumSize(QSize(6, 0))

        self.gridLayout.addWidget(self.viewportPlaceholder, 2, 0, 3, 9)

        self.coordXEdit = QLineEdit(self.layoutWidget)
        self.coordXEdit.setObjectName(u"coordXEdit")

        self.gridLayout.addWidget(self.coordXEdit, 1, 1, 1, 2)

        self.btnPreview = QPushButton(self.layoutWidget)
        self.btnPreview.setObjectName(u"btnPreview")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.btnPreview.sizePolicy().hasHeightForWidth())
        self.btnPreview.setSizePolicy(sizePolicy2)

        self.gridLayout.addWidget(self.btnPreview, 1, 7, 1, 1)

        self.pasteBtn = QPushButton(self.layoutWidget)
        self.pasteBtn.setObjectName(u"pasteBtn")

        self.gridLayout.addWidget(self.pasteBtn, 1, 5, 1, 1)

        self.progressBar = QProgressBar(self.layoutWidget)
        self.progressBar.setObjectName(u"progressBar")
        self.progressBar.setValue(24)

        self.gridLayout.addWidget(self.progressBar, 5, 3, 1, 6)

        self.hintLabel = QLabel(self.layoutWidget)
        self.hintLabel.setObjectName(u"hintLabel")

        self.gridLayout.addWidget(self.hintLabel, 5, 0, 1, 3)

        self.lensSensitivitySlider = QSlider(self.layoutWidget)
        self.lensSensitivitySlider.setObjectName(u"lensSensitivitySlider")
        self.lensSensitivitySlider.setOrientation(Qt.Orientation.Horizontal)

        self.gridLayout.addWidget(self.lensSensitivitySlider, 1, 9, 1, 1)

        self.lensSensitivityLabel = QLabel(self.layoutWidget)
        self.lensSensitivityLabel.setObjectName(u"lensSensitivityLabel")
        self.lensSensitivityLabel.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.gridLayout.addWidget(self.lensSensitivityLabel, 1, 8, 1, 1)

        self.gridLayout.setRowStretch(1, 1)
        self.gridLayout.setRowStretch(2, 1)
        self.gridLayout.setRowStretch(3, 1)
        self.gridLayout.setRowStretch(4, 2)
        self.gridLayout.setColumnStretch(0, 1)
        self.gridLayout.setColumnStretch(1, 2)
        self.gridLayout.setColumnStretch(2, 2)
        self.gridLayout.setColumnStretch(3, 2)
        self.gridLayout.setColumnStretch(4, 2)
        self.gridLayout.setColumnStretch(5, 2)
        self.gridLayout.setColumnStretch(6, 2)
        self.gridLayout.setColumnStretch(7, 2)
        self.gridLayout.setColumnStretch(8, 7)
        self.gridLayout.setColumnStretch(9, 8)

        self.retranslateUi(structurePreviewer)

        QMetaObject.connectSlotsByName(structurePreviewer)
    # setupUi

    def retranslateUi(self, structurePreviewer):
        structurePreviewer.setWindowTitle(QCoreApplication.translate("structurePreviewer", u"Form", None))
        self.visionLabel.setText(QCoreApplication.translate("structurePreviewer", u"\u7248\u672c", None))
        self.structureLabel.setText(QCoreApplication.translate("structurePreviewer", u"\u7ed3\u6784", None))
        self.label_3.setText(QCoreApplication.translate("structurePreviewer", u"\u79cd\u5b50", None))
        self.coordZEdit.setPlaceholderText(QCoreApplication.translate("structurePreviewer", u"Z", None))
        self.infoGroupBox.setTitle(QCoreApplication.translate("structurePreviewer", u"\u7ed3\u6784\u4fe1\u606f", None))
        self.infoLabel.setText("")
        self.locateGroupBox.setTitle(QCoreApplication.translate("structurePreviewer", u"\u9644\u8fd1\u7684\u5b9e\u4f8b", None))
        self.chestsGroupBox.setTitle(QCoreApplication.translate("structurePreviewer", u"\u7bb1\u5b50\u4e0e\u6218\u5229\u54c1", None))
        self.snapshotLabel.setText("")
        self.viewportPlaceholder.setText("")
        self.coordXEdit.setPlaceholderText(QCoreApplication.translate("structurePreviewer", u"X", None))
        self.btnPreview.setText(QCoreApplication.translate("structurePreviewer", u"\u9884\u89c8", None))
        self.pasteBtn.setText(QCoreApplication.translate("structurePreviewer", u"\u7c98\u8d34F3+C", None))
        self.hintLabel.setText("")
        self.lensSensitivityLabel.setText(QCoreApplication.translate("structurePreviewer", u"\u955c\u5934\u7075\u654f\u5ea6", None))
    # retranslateUi

