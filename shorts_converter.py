import sys
import re
import json
import requests
import os
import platform
from pathlib import Path

from datetime import datetime
from collections import Counter
from bs4 import BeautifulSoup

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QTabWidget,
    QWidget,
    QVBoxLayout,
    QListWidget,
    QLabel,
    QMenu,
    QCheckBox,
    QSpinBox,
    QPushButton,
    QHBoxLayout,
    QSystemTrayIcon
)
from PyQt6.QtGui import QClipboard, QIcon
from PyQt6.QtCore import QTimer, Qt, QEvent

SETTINGS_FILE = "settings.json"
HISTORY_FILE = "history.json"
STATS_FILE = "stats.json"  # File to store stats

class StatsCategoryWidget(QWidget):
    """Widget that displays stats text for a given category (Shorts or Regular)."""
    def __init__(self, parent, title, stats):
        super().__init__(parent)
        self.title = title
        self.stats = stats
        layout = QVBoxLayout(self)
        
        text = self.format_stats_text()
        label = QLabel(text, self)
        layout.addWidget(label)

    def format_stats_text(self):
        if not self.stats:
            return f"{self.title}\nNo conversions yet.\n"
        return (
            f"{self.title}\n"
            f"Most conversions in one day: {self.stats['top_day']} with {self.stats['max_count']} conversions\n"
            f"Avg/day: {self.stats['daily_avg']}\n"
            f"Avg/week: {self.stats['weekly_avg']}\n"
            f"Avg/month: {self.stats['monthly_avg']}\n"
        )

class ClipboardMonitor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube Shorts Converter")
        self.setWindowIcon(QIcon("icon.png"))
        self.setGeometry(200, 200, 600, 400)

        self.clipboard = QApplication.clipboard()
        self.last_clipboard_content = ""
        self.history = []
        self.settings = self.load_settings()

        self.tabs = QTabWidget(self)
        self.setCentralWidget(self.tabs)

        self.history_tab = QWidget()
        self.settings_tab = QWidget()
        self.stats_tab = QWidget()

        self.tabs.addTab(self.history_tab, "History")
        self.tabs.addTab(self.settings_tab, "Settings")
        self.tabs.addTab(self.stats_tab, "Statistics")

        self.init_history_tab()
        self.init_settings_tab()
        self.init_stats_tab()

        # System tray icon
        self.tray_icon = QSystemTrayIcon(QIcon("icon.png"), self) 
        self.tray_icon.setToolTip("YouTube Shorts Converter")
        self.tray_icon.activated.connect(self.on_tray_icon_activated)

        # Timer to check the clipboard every second
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_clipboard)
        self.timer.start(1000)

    def init_history_tab(self):
        layout = QVBoxLayout(self.history_tab)
        self.history_list = QListWidget()
        self.history_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_list.customContextMenuRequested.connect(self.show_context_menu)
        layout.addWidget(self.history_list)
        self.load_history()

    def load_history(self):
        try:
            with open(HISTORY_FILE, "r") as file:
                self.history = json.load(file)
                for entry in self.history:
                    title = entry.get("title", "Unknown Title")
                    url = entry.get("url", "")
                    self.history_list.addItem(f"{title} - {url}")
        except FileNotFoundError:
            self.history = []

    def init_settings_tab(self):
        layout = QVBoxLayout(self.settings_tab)

        # Keep History Forever
        self.keep_history_forever = QCheckBox("Keep history forever")
        self.keep_history_forever.setChecked(self.settings.get("keep_history_forever", False))
        self.keep_history_forever.toggled.connect(self.toggle_history_spinbox)
        layout.addWidget(self.keep_history_forever)

        # "Keep history for:" label and spinbox on the same row
        keep_history_hbox = QHBoxLayout()
        keep_history_label = QLabel("Keep history for:")
        keep_history_hbox.addWidget(keep_history_label)

        self.history_days_spinbox = QSpinBox()
        self.history_days_spinbox.setMinimum(1)
        self.history_days_spinbox.setMaximum(365)
        self.history_days_spinbox.setValue(self.settings.get("history_days", 30))
        self.history_days_spinbox.setSuffix(" days")
        keep_history_hbox.addWidget(self.history_days_spinbox)
        layout.addLayout(keep_history_hbox)

        # "Always start minimized" checkbox
        self.always_start_minimized_checkbox = QCheckBox("Always start minimized")
        self.always_start_minimized_checkbox.setChecked(
            self.settings.get("always_start_minimized", False)
        )
        layout.addWidget(self.always_start_minimized_checkbox)

        # Start with Windows logon
        self.start_with_windows_checkbox = QCheckBox("Start with Windows logon")
        self.start_with_windows_checkbox.setChecked(
            self.settings.get("start_with_windows", False)
        )
        layout.addWidget(self.start_with_windows_checkbox)

        # Save button
        save_button = QPushButton("Save Settings")
        save_button.clicked.connect(self.save_settings)
        layout.addWidget(save_button)

        self.toggle_history_spinbox(self.keep_history_forever.isChecked())

    def toggle_history_spinbox(self, checked: bool):
        self.history_days_spinbox.setEnabled(not checked)

    def load_settings(self):
        try:
            with open(SETTINGS_FILE, "r") as file:
                return json.load(file)
        except FileNotFoundError:
            return {}

    def save_settings(self):
        self.settings["keep_history_forever"] = self.keep_history_forever.isChecked()
        self.settings["history_days"] = self.history_days_spinbox.value()
        self.settings["start_with_windows"] = self.start_with_windows_checkbox.isChecked()
        self.settings["always_start_minimized"] = self.always_start_minimized_checkbox.isChecked()

        with open(SETTINGS_FILE, "w") as file:
            json.dump(self.settings, file, indent=4)

        # If user wants to start with Windows, add a .bat to Startup folder (Windows only)
        if platform.system() == "Windows":
            self.update_windows_startup(self.settings["start_with_windows"])

    def update_windows_startup(self, enabled: bool):
        from os import path
        startup_path = path.join(
            os.environ.get("APPDATA", ""),
            "Microsoft",
            "Windows",
            "Start Menu",
            "Programs",
            "Startup"
        )
        if not startup_path:
            return

        bat_name = "YouTubeShortsConverter.bat"
        bat_file = path.join(startup_path, bat_name)
        
        if enabled:
            script_path = os.path.abspath(sys.argv[0])
            with open(bat_file, "w") as f:
                f.write("@echo off\n")
                f.write(f"cd /d \"{os.path.dirname(script_path)}\"\n")
                f.write(f"python \"{script_path}\"\n")
        else:
            if os.path.exists(bat_file):
                os.remove(bat_file)

    def init_stats_tab(self):
        self.stats_layout = QVBoxLayout(self.stats_tab)
        self.update_stats()

    def update_stats(self):
        # Clear layout
        while self.stats_layout.count() > 0:
            item = self.stats_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Separate history entries by category
        shorts_entries = [e for e in self.history if e.get("type") == "shorts"]
        regular_entries = [e for e in self.history if e.get("type") == "regular"]

        def compute_stats_for(entries):
            valid_dates = []
            for entry in entries:
                date_str = entry.get("date")
                if date_str:
                    try:
                        dt = datetime.strptime(date_str, "%Y-%m-%d")
                        valid_dates.append(dt)
                    except:
                        pass
            if not valid_dates:
                return None

            date_strings = [d.strftime('%Y-%m-%d') for d in valid_dates]
            day_counter = Counter(date_strings)
            top_day, max_count = day_counter.most_common(1)[0]

            total_conversions = len(valid_dates)
            unique_days = set(date_strings)
            daily_avg = total_conversions / len(unique_days)

            unique_weeks = set()
            for dt in valid_dates:
                year, week_num, _ = dt.isocalendar()
                unique_weeks.add((year, week_num))
            weekly_avg = total_conversions / len(unique_weeks)

            unique_months = set()
            for dt in valid_dates:
                unique_months.add((dt.year, dt.month))
            monthly_avg = total_conversions / len(unique_months)

            stats_dict = {
                "top_day": top_day,
                "max_count": max_count,
                "daily_avg": round(daily_avg, 2),
                "weekly_avg": round(weekly_avg, 2),
                "monthly_avg": round(monthly_avg, 2)
            }
            return stats_dict

        shorts_stats = compute_stats_for(shorts_entries)
        regular_stats = compute_stats_for(regular_entries)

        shorts_widget = StatsCategoryWidget(self, "Shorts Stats", shorts_stats)
        regular_widget = StatsCategoryWidget(self, "Regular Videos Stats", regular_stats)

        self.stats_layout.addWidget(shorts_widget)
        self.stats_layout.addWidget(regular_widget)

        combined_data = {
            "shorts": shorts_stats if shorts_stats else {"message": "No shorts conversions yet."},
            "regular": regular_stats if regular_stats else {"message": "No regular conversions yet."}
        }
        self.save_stats_file(combined_data)

    def save_stats_file(self, stats_data):
        with open(STATS_FILE, 'w') as file:
            json.dump(stats_data, file, indent=4)

    def show_context_menu(self, position):
        menu = QMenu(self)
        copy_action = menu.addAction("Copy URL")
        delete_action = menu.addAction("Delete")
        action = menu.exec(self.history_list.mapToGlobal(position))

        selected_item = self.history_list.currentItem()
        if selected_item:
            text = selected_item.text()
            url = text.split(" - ")[-1]
            if action == copy_action:
                self.clipboard.setText(url)
            elif action == delete_action:
                self.history_list.takeItem(self.history_list.row(selected_item))
                self.history = [e for e in self.history if e.get("url", "") != url]
                self.save_history()
                self.update_stats()

    def check_clipboard(self):
        shorts_pattern = re.compile(r"https?://(www\.)?youtube\.com/shorts/[a-zA-Z0-9_-]+")
        normal_pattern = re.compile(r"https?://(www\.)?youtube\.com/watch\?v=[a-zA-Z0-9_-]+")
        youtu_pattern = re.compile(r"https?://youtu\.be/([a-zA-Z0-9_-]+)")

        current_text = self.clipboard.text().strip()

        if current_text != self.last_clipboard_content:
            link_type = None
            if shorts_pattern.match(current_text):
                converted_url = self.convert_shorts_url(current_text)
                link_type = "shorts"
            elif normal_pattern.match(current_text):
                converted_url = current_text
                link_type = "regular"
            elif youtu_pattern.match(current_text):
                match = youtu_pattern.match(current_text)
                video_id = match.group(1)
                converted_url = f"https://www.youtube.com/watch?v={video_id}"
                link_type = "regular"
            else:
                return

            if not any(e.get("url", "") == converted_url for e in self.history):
                video_title = self.get_video_title(converted_url)
                self.history.append({
                    "title": video_title,
                    "url": converted_url,
                    "date": datetime.today().strftime('%Y-%m-%d'),
                    "type": link_type
                })
                self.history_list.addItem(f"{video_title} - {converted_url}")
                self.last_clipboard_content = converted_url

                self.clipboard.setText(converted_url)
                self.save_history()
                self.update_stats()

    def convert_shorts_url(self, url):
        return re.sub(r"youtube\.com/shorts/([a-zA-Z0-9_-]+)", r"youtube.com/watch?v=\1", url)

    def get_video_title(self, url):
        try:
            response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(response.text, 'html.parser')
            title_tag = soup.find("title")
            return title_tag.text.replace(" - YouTube", "") if title_tag else "Unknown Title"
        except:
            return "Unknown Title"

    def save_history(self):
        with open(HISTORY_FILE, "w") as file:
            json.dump(self.history, file, indent=4)
        self.update_stats()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange:
            if self.isMinimized():
                self.hide()
                self.tray_icon.show()
                self.tray_icon.showMessage(
                    self.windowTitle(),
                    "Double-click the tray icon to restore",
                    QSystemTrayIcon.MessageIcon.Information,
                    3000
                )
        super().changeEvent(event)

    def on_tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.showNormal()
            self.activateWindow()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("icon.png"))

    window = ClipboardMonitor()

    # If the "always_start_minimized" setting is true, show minimized
    if window.settings.get("always_start_minimized", False):
        window.showMinimized()
    else:
        window.show()

    sys.exit(app.exec())
