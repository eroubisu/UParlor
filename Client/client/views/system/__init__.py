"""系统页面"""
from .tutorial import TutorialWindow, TutorialPanel
from .docs import DocsWindow
from .root_menu import RootMenuWindow
from .records import RecordsWindow
from .settings import SettingsWindow
from .remote import RemoteWindow

__all__ = [
    'TutorialWindow', 'TutorialPanel', 'DocsWindow', 'RootMenuWindow',
    'RecordsWindow', 'SettingsWindow', 'RemoteWindow',
]
