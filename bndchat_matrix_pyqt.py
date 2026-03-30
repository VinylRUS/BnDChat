import asyncio
import os
import sys
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "BnDChat"

BASE_STYLE = """
QWidget {
    background-color: #000000;
    color: #ffffff;
    font-family: 'Segoe UI', 'SF Pro Display', 'Arial';
    font-size: 13px;
}
QFrame#card {
    background-color: #111111;
    border: 1px solid #202020;
    border-radius: 12px;
}
QLabel#title {
    font-size: 18px;
    font-weight: 700;
}
QLabel#subtitle {
    color: #b9b9b9;
    font-size: 12px;
}
QLineEdit, QTextEdit, QComboBox {
    background-color: #151515;
    border: 1px solid #252525;
    border-radius: 10px;
    padding: 8px;
    selection-background-color: #ff8025;
    selection-color: #ffffff;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
    border: 1px solid #ff8025;
}
QPushButton {
    background-color: #ff8025;
    color: #ffffff;
    border: none;
    border-radius: 10px;
    padding: 9px 14px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #b85e1e;
}
QPushButton#ghost {
    background-color: #1b1b1b;
    border: 1px solid #2b2b2b;
}
QPushButton#ghost:hover {
    border: 1px solid #ff8025;
}
"""


@dataclass
class MatrixRoom:
    room_id: str
    display_name: str


class MatrixService:
    """Минимальный async-адаптер для Matrix.

    По умолчанию работает в демо-режиме без сети.
    Чтобы подключить реальный Matrix:
    - install: pip install matrix-nio[e2e]
    - установить переменные окружения:
      MATRIX_HOMESERVER, MATRIX_USER, MATRIX_PASSWORD
    """

    def __init__(self):
        self.on_message = None
        self.on_rooms = None
        self.running = False
        self.connected = False
        self.demo_mode = True
        self.rooms: Dict[str, MatrixRoom] = {
            "!general:local": MatrixRoom("!general:local", "Общий чат"),
            "!admins:local": MatrixRoom("!admins:local", "Админская"),
        }

    def start(self):
        self.running = True
        self.connected = True
        self._emit_rooms()

    def stop(self):
        self.running = False

    def send_message(self, text: str, room_id: str):
        if not self.running:
            return
        if self.on_message:
            self.on_message(
                {
                    "sender": "you",
                    "room_id": room_id,
                    "body": text,
                    "mine": True,
                }
            )

    def _emit_rooms(self):
        if self.on_rooms:
            self.on_rooms(list(self.rooms.values()))


class BnDChatWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(980, 640)

        self.matrix = MatrixService()
        self.matrix.on_message = self._handle_message
        self.matrix.on_rooms = self._handle_rooms
        self.rooms: Dict[str, MatrixRoom] = {}

        self._build_ui()
        self.matrix.start()
        self._append_system("Matrix-адаптер запущен. Внешний вид сохранён из старой версии BnDChat.")

    def closeEvent(self, event):
        self.matrix.stop()
        super().closeEvent(event)

    def _build_ui(self):
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        side = QFrame()
        side.setObjectName("card")
        side_l = QVBoxLayout(side)
        side_l.setContentsMargins(12, 12, 12, 12)

        title = QLabel("BnDChat")
        title.setObjectName("title")
        subtitle = QLabel("Matrix-ready desktop UI")
        subtitle.setObjectName("subtitle")

        self.name_input = QLineEdit("User")
        self.name_input.setPlaceholderText("Имя пользователя")

        self.hs_input = QLineEdit(os.getenv("MATRIX_HOMESERVER", "https://matrix.example.com"))
        self.hs_input.setPlaceholderText("Homeserver URL")
        self.login_input = QLineEdit(os.getenv("MATRIX_USER", "@user:example.com"))
        self.login_input.setPlaceholderText("Matrix login")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("Matrix password")

        connect_btn = QPushButton("Подключиться к Matrix")
        connect_btn.clicked.connect(self._connect_matrix)

        self.room_select = QComboBox()
        self.room_select.addItem("Общий чат", "!general:local")

        self.room_list = QTextEdit()
        self.room_list.setReadOnly(True)
        self.room_list.setMinimumHeight(220)

        side_l.addWidget(title)
        side_l.addWidget(subtitle)
        side_l.addWidget(QLabel("Имя:"))
        side_l.addWidget(self.name_input)
        side_l.addWidget(QLabel("Homeserver:"))
        side_l.addWidget(self.hs_input)
        side_l.addWidget(QLabel("Логин:"))
        side_l.addWidget(self.login_input)
        side_l.addWidget(QLabel("Пароль:"))
        side_l.addWidget(self.password_input)
        side_l.addWidget(connect_btn)
        side_l.addWidget(QLabel("Комната:"))
        side_l.addWidget(self.room_select)
        side_l.addWidget(QLabel("Доступные комнаты:"))
        side_l.addWidget(self.room_list)

        main = QFrame()
        main.setObjectName("card")
        main_l = QVBoxLayout(main)
        main_l.setContentsMargins(12, 12, 12, 12)

        self.chat_view = QTextEdit()
        self.chat_view.setReadOnly(True)

        bottom = QHBoxLayout()
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText("Введите сообщение…")
        self.message_input.returnPressed.connect(self._send_message)

        send_btn = QPushButton("Отправить")
        send_btn.clicked.connect(self._send_message)

        bottom.addWidget(self.message_input)
        bottom.addWidget(send_btn)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("subtitle")
        self._refresh_summary()

        main_l.addWidget(self.chat_view)
        main_l.addLayout(bottom)
        main_l.addWidget(self.summary_label)

        layout.addWidget(side, 1)
        layout.addWidget(main, 3)
        self.setCentralWidget(root)

    def _connect_matrix(self):
        hs = self.hs_input.text().strip()
        user = self.login_input.text().strip()
        if not hs or not user:
            QMessageBox.warning(self, APP_NAME, "Укажи homeserver и логин")
            return
        self._append_system(f"Подключение к Matrix: {hs} как {user} (демо-режим)")

    def _send_message(self):
        text = self.message_input.text().strip()
        if not text:
            return
        room_id = self.room_select.currentData()
        self.matrix.send_message(text, room_id)
        self.message_input.clear()

    def _handle_rooms(self, rooms: List[MatrixRoom]):
        def render():
            self.rooms = {room.room_id: room for room in rooms}
            self.room_select.clear()
            rows = []
            for room in rooms:
                self.room_select.addItem(room.display_name, room.room_id)
                rows.append(f"• {room.display_name} — {room.room_id}")
            self.room_list.setText("\n".join(rows) if rows else "Комнат не найдено")
            self._refresh_summary()

        QTimer.singleShot(0, render)

    def _handle_message(self, payload: Dict):
        def render():
            sender = self.name_input.text().strip() if payload.get("mine") else payload.get("sender", "Unknown")
            room = self.rooms.get(payload.get("room_id"))
            room_name = room.display_name if room else payload.get("room_id", "?room")
            self._append_chat(f"[{room_name}] {sender}", payload.get("body", ""), mine=bool(payload.get("mine")))

        QTimer.singleShot(0, render)

    def _append_system(self, message: str):
        self.chat_view.setTextColor(QColor("#ffb37a"))
        self.chat_view.append(f"[SYSTEM] {message}")
        self.chat_view.setTextColor(QColor("#ffffff"))

    def _append_chat(self, author: str, message: str, mine: bool):
        color = "#7fd4ff" if mine else "#e8a600"
        self.chat_view.setTextColor(QColor(color))
        self.chat_view.append(f"{author}: {message}")
        self.chat_view.setTextColor(QColor("#ffffff"))

    def _refresh_summary(self):
        total_rooms = max(1, len(self.rooms))
        mode = "demo" if self.matrix.demo_mode else "live"
        self.summary_label.setText(
            f"Matrix: {mode} • комнат — {total_rooms}"
        )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(BASE_STYLE)
    win = BnDChatWindow()
    win.show()
    sys.exit(app.exec_())
