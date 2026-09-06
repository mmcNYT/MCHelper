from PySide6.QtCore import QObject, Signal

class SettingsSignals(QObject):
    is_start_on_boot = Signal(bool)

    is_system_tray = Signal(bool)

settings_bus = SettingsSignals()