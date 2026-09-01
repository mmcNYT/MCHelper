# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'MCHelperMainWindow.ui'
##
## Created by: Qt User Interface Compiler version 6.11.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QAction, QBrush, QColor, QConicalGradient,
    QCursor, QFont, QFontDatabase, QGradient,
    QIcon, QImage, QKeySequence, QLinearGradient,
    QPainter, QPalette, QPixmap, QRadialGradient,
    QTransform)
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QMainWindow, QMenu,
    QMenuBar, QSizePolicy, QStatusBar, QTabWidget,
    QWidget)

class Ui_MCHelper(object):
    def setupUi(self, MCHelper):
        if not MCHelper.objectName():
            MCHelper.setObjectName(u"MCHelper")
        MCHelper.resize(800, 600)
        self.action = QAction(MCHelper)
        self.action.setObjectName(u"action")
        self.centralwidget = QWidget(MCHelper)
        self.centralwidget.setObjectName(u"centralwidget")
        self.horizontalLayout = QHBoxLayout(self.centralwidget)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.tabWidget = QTabWidget(self.centralwidget)
        self.tabWidget.setObjectName(u"tabWidget")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.tabWidget.sizePolicy().hasHeightForWidth())
        self.tabWidget.setSizePolicy(sizePolicy)
        self.tabWidget.setTabShape(QTabWidget.TabShape.Rounded)

        self.horizontalLayout.addWidget(self.tabWidget)

        MCHelper.setCentralWidget(self.centralwidget)
        self.menubar = QMenuBar(MCHelper)
        self.menubar.setObjectName(u"menubar")
        self.menubar.setGeometry(QRect(0, 0, 800, 33))
        self.menu = QMenu(self.menubar)
        self.menu.setObjectName(u"menu")
        MCHelper.setMenuBar(self.menubar)
        self.statusbar = QStatusBar(MCHelper)
        self.statusbar.setObjectName(u"statusbar")
        MCHelper.setStatusBar(self.statusbar)

        self.menubar.addAction(self.menu.menuAction())
        self.menu.addAction(self.action)

        self.retranslateUi(MCHelper)

        self.tabWidget.setCurrentIndex(-1)


        QMetaObject.connectSlotsByName(MCHelper)
    # setupUi

    def retranslateUi(self, MCHelper):
        MCHelper.setWindowTitle(QCoreApplication.translate("MCHelper", u"MainWindow", None))
        self.action.setText(QCoreApplication.translate("MCHelper", u"\u8bbe\u7f6e", None))
        self.menu.setTitle("")
    # retranslateUi

