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
    QSplitter,
    QTabWidget,
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
    border-radius: 14px;
}
QLabel#title {
    font-size: 20px;
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
QTabWidget::pane {
    border: 1px solid #1f1f1f;
    border-radius: 10px;
    background: #0f0f0f;
}
QTabBar::tab {
    background: #151515;
    border: 1px solid #242424;
    padding: 8px 14px;
    margin-right: 4px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}
QTabBar::tab:selected {
    background: #232323;
    border-bottom-color: #ff8025;
}
"""


@dataclass
class MatrixRoom:
    room_id: str
    display_name: str


class MatrixService:
    """Рабочий адаптер Matrix поверх matrix-nio."""

    def __init__(self):
        self.on_message = None
        self.on_rooms = None
        self.running = False
        self.connected = False
        self.demo_mode = False
        self.client = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._sync_timeout_ms = 30_000
        self._next_batch = None
        self.rooms: Dict[str, MatrixRoom] = {
            "!general:local": MatrixRoom("!general:local", "Общий чат"),
            "!admins:local": MatrixRoom("!admins:local", "Админская"),
        }

    def connect(self, homeserver: str, user: str, password: str):
        if self.running:
            self.stop()
        if self._should_use_demo(homeserver, user, password):
            self._connect_demo(user)
            return

        try:
            from nio import (  # pylint: disable=import-outside-toplevel
                AsyncClient,
                LoginError,
                LoginResponse,
                MatrixRoom as NioRoom,
                RoomMessageText,
            )
        except ImportError as exc:
            raise RuntimeError(
                "Не найден matrix-nio. Установи зависимости: pip install matrix-nio[e2e]"
            ) from exc

        self.running = True
        self.connected = False
        self._next_batch = None

        def worker():
            import asyncio  # pylint: disable=import-outside-toplevel

            async def run():
                self.client = AsyncClient(homeserver, user)
                login = await self.client.login(password=password, device_name="BnDChat Desktop")
                if isinstance(login, LoginError):
                    self.running = False
                    raise RuntimeError(f"Ошибка Matrix login: {login.message}")
                if not isinstance(login, LoginResponse):
                    self.running = False
                    raise RuntimeError("Неожиданный ответ при авторизации Matrix")

                self.connected = True
                await self._sync_once()
                self._emit_rooms()

                def on_room_message(room: NioRoom, event: RoomMessageText):
                    if getattr(event, "decrypted", True) is False:
                        return
                    if self.on_message:
                        self.on_message(
                            {
                                "sender": event.sender,
                                "room_id": room.room_id,
                                "body": event.body,
                                "mine": event.sender == self.client.user_id,
                            }
                        )

                self.client.add_event_callback(on_room_message, RoomMessageText)

                while self.running:
                    try:
                        await self._sync_once()
                        self._emit_rooms()
                    except Exception:
                        await asyncio.sleep(2)

                await self.client.close()

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            try:
                loop.run_until_complete(run())
            finally:
                self._loop = None
                loop.close()

        self._worker_thread = threading.Thread(target=worker, daemon=True)
        self._worker_thread.start()

    def stop(self):
        self.running = False
        self.connected = False
        self.client = None
        self.demo_mode = False

    def _should_use_demo(self, homeserver: str, user: str, password: str) -> bool:
        hs = homeserver.strip().lower()
        return hs in {"demo", "sandbox", "mock"} or user.startswith("@sandbox") or password == "sandbox"

    def _connect_demo(self, user: str):
        self.running = True
        self.connected = True
        self.demo_mode = True
        self.client = None
        self.rooms = {
            "!general:sandbox": MatrixRoom("!general:sandbox", "Песочница / Общий"),
            "!qa:sandbox": MatrixRoom("!qa:sandbox", "Песочница / QA"),
        }
        self._emit_rooms()
        if self.on_message:
            demo_user = user or "@sandbox-user:local"
            self.on_message(
                {
                    "sender": "@sandbox-bot:local",
                    "room_id": "!general:sandbox",
                    "body": f"Сэндбокс включён. Тестовый юзер: {demo_user}",
                    "mine": False,
                }
            )

    async def _sync_once(self):
        if not self.client:
            return
        response = await self.client.sync(
            timeout=self._sync_timeout_ms,
            since=self._next_batch,
            full_state=False,
        )
        if getattr(response, "next_batch", None):
            self._next_batch = response.next_batch

    def send_message(self, text: str, room_id: str):
        if self.demo_mode:
            if self.on_message:
                self.on_message(
                    {
                        "sender": "@sandbox-bot:local",
                        "room_id": room_id,
                        "body": f"Эхо от тестового сервера: {text}",
                        "mine": False,
                    }
                )
            return
        if not self.running or not self.client:
            return
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self.client.room_send(
                    room_id=room_id,
                    message_type="m.room.message",
                    content={"msgtype": "m.text", "body": text},
                ),
                self._loop,
            )

    def run_admin_action(self, coro, timeout: float = 15.0):
        if not self.running or not self.client or not self._loop:
            raise RuntimeError("Matrix клиент не подключён")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def create_room(self, room_name: str, is_public: bool):
        if self.demo_mode:
            slug = room_name.strip().lower().replace(" ", "-") or "new-room"
            room_id = f"!{slug}:sandbox"
            self.rooms[room_id] = MatrixRoom(room_id=room_id, display_name=f"Песочница / {room_name}")
            self._emit_rooms()
            return room_id
        preset = "public_chat" if is_public else "private_chat"
        visibility = "public" if is_public else "private"
        response = self.run_admin_action(
            self.client.room_create(name=room_name, preset=preset, visibility=visibility)
        )
        if getattr(response, "room_id", None):
            self._emit_rooms()
            return response.room_id
        raise RuntimeError(getattr(response, "message", "Не удалось создать комнату"))

    def get_joined_members(self, room_id: str):
        if self.demo_mode:
            return [
                ("Sandbox Admin", "@sandbox-admin:local"),
                ("Sandbox User", "@sandbox-user:local"),
                ("Echo Bot", "@sandbox-bot:local"),
            ]
        response = self.run_admin_action(self.client.joined_members(room_id))
        if not hasattr(response, "members"):
            raise RuntimeError(getattr(response, "message", "Не удалось получить участников"))
        members = []
        for member in response.members:
            user_id = getattr(member, "user_id", "")
            display = getattr(member, "display_name", "") or user_id
            members.append((display, user_id))
        return members

    def _power_levels(self, room_id: str):
        response = self.run_admin_action(
            self.client.room_get_state_event(room_id, "m.room.power_levels", "")
        )
        if not hasattr(response, "content"):
            raise RuntimeError(getattr(response, "message", "Не удалось проверить power levels"))
        return response.content

    def is_admin_in_room(self, room_id: str):
        if self.demo_mode:
            return True
        if not self.client or not self.client.user_id:
            return False
        try:
            content = self._power_levels(room_id)
        except Exception:
            return False
        users = content.get("users", {})
        users_default = int(content.get("users_default", 0))
        kick_level = int(content.get("kick", 50))
        ban_level = int(content.get("ban", 50))
        my_level = int(users.get(self.client.user_id, users_default))
        return my_level >= max(kick_level, ban_level)

    def kick_user(self, room_id: str, user_id: str, reason: str):
        if self.demo_mode:
            return
        response = self.run_admin_action(self.client.room_kick(room_id, user_id, reason=reason))
        if response.__class__.__name__.endswith("Error"):
            raise RuntimeError(getattr(response, "message", "Не удалось кикнуть пользователя"))

    def ban_user(self, room_id: str, user_id: str, reason: str):
        if self.demo_mode:
            return
        response = self.run_admin_action(self.client.room_ban(room_id, user_id, reason=reason))
        if response.__class__.__name__.endswith("Error"):
            raise RuntimeError(getattr(response, "message", "Не удалось забанить пользователя"))

    def unban_user(self, room_id: str, user_id: str):
        if self.demo_mode:
            return
        response = self.run_admin_action(self.client.room_unban(room_id, user_id))
        if response.__class__.__name__.endswith("Error"):
            raise RuntimeError(getattr(response, "message", "Не удалось разбанить пользователя"))

    def _emit_rooms(self):
        if self.client and self.client.rooms:
            mapped = {}
            for room_id, room in self.client.rooms.items():
                display_name = room.display_name or room.room_id
                mapped[room_id] = MatrixRoom(room_id=room_id, display_name=display_name)
            self.rooms = mapped
        if self.on_rooms:
            self.on_rooms(list(self.rooms.values()))


class BnDChatWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 760)

        self.matrix = MatrixService()
        self.matrix.on_message = self._handle_message
        self.matrix.on_rooms = self._handle_rooms
        self.rooms: Dict[str, MatrixRoom] = {}
        self.current_user_id = ""
        self.admin_room_ids: List[str] = []

        self._build_ui()
        self._append_system("Готово к подключению Matrix (Synapse).")

    def closeEvent(self, event):
        self.matrix.stop()
        super().closeEvent(event)

    def _build_ui(self):
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        left = self._build_sidebar()
        right = self._build_content()

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        layout.addWidget(splitter)
        self.setCentralWidget(root)

    def _build_sidebar(self):
        side = QFrame()
        side.setObjectName("card")
        side_l = QVBoxLayout(side)
        side_l.setContentsMargins(14, 14, 14, 14)
        side_l.setSpacing(8)

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
        self.password_input.setText(os.getenv("MATRIX_PASSWORD", ""))
        self.password_input.setToolTip("Для тестового режима можно указать пароль: sandbox")

        connect_btn = QPushButton("Подключиться к Matrix")
        connect_btn.clicked.connect(self._connect_matrix)

        self.room_select = QComboBox()
        self.room_select.addItem("Нет комнаты", "")

        self.room_list = QTextEdit()
        self.room_list.setReadOnly(True)
        self.room_list.setMinimumHeight(200)

        side_l.addWidget(title)
        side_l.addWidget(subtitle)
        side_l.addSpacing(4)
        side_l.addWidget(QLabel("Имя:"))
        side_l.addWidget(self.name_input)
        side_l.addWidget(QLabel("Homeserver:"))
        side_l.addWidget(self.hs_input)
        side_l.addWidget(QLabel("Логин:"))
        side_l.addWidget(self.login_input)
        side_l.addWidget(QLabel("Пароль:"))
        side_l.addWidget(self.password_input)
        side_l.addWidget(connect_btn)
        side_l.addSpacing(6)
        side_l.addWidget(QLabel("Комната:"))
        side_l.addWidget(self.room_select)
        side_l.addWidget(QLabel("Доступные комнаты:"))
        side_l.addWidget(self.room_list)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("subtitle")
        side_l.addWidget(self.summary_label)
        self._refresh_summary()

        return side

    def _build_content(self):
        main = QFrame()
        main.setObjectName("card")
        main_l = QVBoxLayout(main)
        main_l.setContentsMargins(12, 12, 12, 12)

        tabs = QTabWidget()
        tabs.addTab(self._build_chat_tab(), "Чат")
        tabs.addTab(self._build_admin_tab(), "Админ")

        main_l.addWidget(tabs)
        return main

    def _build_chat_tab(self):
        tab = QWidget()
        tab_l = QVBoxLayout(tab)
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
        tab_l.addWidget(self.chat_view)
        tab_l.addLayout(bottom)
        return tab

    def _build_admin_tab(self):
        tab = QWidget()
        tab_l = QVBoxLayout(tab)

        self.admin_status = QLabel("Админ-функции недоступны: нужна роль администратора в Matrix комнате")
        self.admin_status.setObjectName("subtitle")

        self.admin_room_select = QComboBox()
        self.admin_room_select.currentIndexChanged.connect(self._refresh_admin_members)

        create_row = QHBoxLayout()
        self.new_room_input = QLineEdit()
        self.new_room_input.setPlaceholderText("Название новой комнаты")
        self.new_room_public = QComboBox()
        self.new_room_public.addItem("Приватная", "private")
        self.new_room_public.addItem("Публичная", "public")
        self.create_room_btn = QPushButton("Создать комнату")
        self.create_room_btn.clicked.connect(self._create_room)
        create_row.addWidget(self.new_room_input)
        create_row.addWidget(self.new_room_public)
        create_row.addWidget(self.create_room_btn)

        self.member_select = QComboBox()
        self.reason_input = QLineEdit()
        self.reason_input.setPlaceholderText("Причина (опционально)")

        actions_row = QHBoxLayout()
        self.kick_btn = QPushButton("Кик")
        self.kick_btn.clicked.connect(self._kick_member)
        self.ban_btn = QPushButton("Бан")
        self.ban_btn.clicked.connect(self._ban_member)
        self.unban_btn = QPushButton("Разбан")
        self.unban_btn.setObjectName("ghost")
        self.unban_btn.clicked.connect(self._unban_member)
        refresh_btn = QPushButton("Обновить участников")
        refresh_btn.setObjectName("ghost")
        refresh_btn.clicked.connect(self._refresh_admin_members)

        actions_row.addWidget(self.kick_btn)
        actions_row.addWidget(self.ban_btn)
        actions_row.addWidget(self.unban_btn)
        actions_row.addWidget(refresh_btn)

        self.admin_log = QTextEdit()
        self.admin_log.setReadOnly(True)
        self.admin_log.setMinimumHeight(210)

        tab_l.addWidget(self.admin_status)
        tab_l.addWidget(QLabel("Админ-комната:"))
        tab_l.addWidget(self.admin_room_select)
        tab_l.addLayout(create_row)
        tab_l.addWidget(QLabel("Участник:"))
        tab_l.addWidget(self.member_select)
        tab_l.addWidget(QLabel("Причина:"))
        tab_l.addWidget(self.reason_input)
        tab_l.addLayout(actions_row)
        tab_l.addWidget(QLabel("Лог админ-действий:"))
        tab_l.addWidget(self.admin_log)

        self._set_admin_controls_enabled(False)
        return tab

    def _connect_matrix(self):
        hs = self.hs_input.text().strip()
        user = self.login_input.text().strip()
        password = self.password_input.text()
        demo_requested = self.matrix._should_use_demo(hs, user, password)
        if not hs or not user or (not password and not demo_requested):
            QMessageBox.warning(self, APP_NAME, "Укажи homeserver, логин и пароль")
            return
        self.current_user_id = user
        if demo_requested:
            self._append_system("Включён тестовый sandbox-режим (эмуляция сервера и тестовый пользователь).")
        self._append_system(f"Подключение к Matrix: {hs} как {user}")
        try:
            self.matrix.connect(hs, user, password)
        except RuntimeError as err:
            QMessageBox.critical(self, APP_NAME, str(err))
            return
        self._append_system("Matrix login отправлен, ожидай синхронизацию комнат...")

    def _send_message(self):
        text = self.message_input.text().strip()
        if not text:
            return
        room_id = self.room_select.currentData()
        if not room_id:
            QMessageBox.warning(self, APP_NAME, "Выбери комнату")
            return
        self.matrix.send_message(text, room_id)
        self._handle_message(
            {
                "sender": "you",
                "room_id": room_id,
                "body": text,
                "mine": True,
            }
        )
        self.message_input.clear()

    def _create_room(self):
        if not self._admin_guard():
            return
        room_name = self.new_room_input.text().strip()
        if not room_name:
            QMessageBox.warning(self, APP_NAME, "Введи название комнаты")
            return
        try:
            room_id = self.matrix.create_room(room_name, self.new_room_public.currentData() == "public")
            self._append_admin(f"Комната создана: {room_name} ({room_id})")
            self.new_room_input.clear()
        except Exception as err:
            QMessageBox.critical(self, APP_NAME, f"Ошибка создания комнаты: {err}")

    def _kick_member(self):
        self._moderate_member("kick")

    def _ban_member(self):
        self._moderate_member("ban")

    def _unban_member(self):
        self._moderate_member("unban")

    def _moderate_member(self, action: str):
        if not self._admin_guard():
            return
        room_id = self.admin_room_select.currentData()
        user_id = self.member_select.currentData()
        if not room_id or not user_id:
            QMessageBox.warning(self, APP_NAME, "Выбери комнату и участника")
            return
        if self.matrix.client and user_id == self.matrix.client.user_id:
            QMessageBox.warning(self, APP_NAME, "Нельзя применить действие к самому себе")
            return

        reason = self.reason_input.text().strip()
        try:
            if action == "kick":
                self.matrix.kick_user(room_id, user_id, reason)
                self._append_admin(f"Кик: {user_id} из {room_id}. Причина: {reason or '—'}")
            elif action == "ban":
                self.matrix.ban_user(room_id, user_id, reason)
                self._append_admin(f"Бан: {user_id} в {room_id}. Причина: {reason or '—'}")
            else:
                self.matrix.unban_user(room_id, user_id)
                self._append_admin(f"Разбан: {user_id} в {room_id}")
        except Exception as err:
            QMessageBox.critical(self, APP_NAME, f"Админ-действие отклонено Matrix API: {err}")
            return

        self.reason_input.clear()
        self._refresh_admin_members()

    def _admin_guard(self):
        if not self.admin_room_ids:
            QMessageBox.warning(
                self,
                APP_NAME,
                "Админ-действия доступны только если у аккаунта есть права kick/ban в комнате (power levels).",
            )
            return False
        return True

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
            self._rebuild_admin_rooms(rooms)

        QTimer.singleShot(0, render)

    def _rebuild_admin_rooms(self, rooms: List[MatrixRoom]):
        self.admin_room_ids = [room.room_id for room in rooms if self.matrix.is_admin_in_room(room.room_id)]
        self.admin_room_select.clear()
        for room_id in self.admin_room_ids:
            room_name = self.rooms[room_id].display_name if room_id in self.rooms else room_id
            self.admin_room_select.addItem(room_name, room_id)

        has_admin = bool(self.admin_room_ids)
        self._set_admin_controls_enabled(has_admin)
        if has_admin:
            self.admin_status.setText(
                "Админ-режим активен: проверено через m.room.power_levels (действия ограничены Matrix API)"
            )
            self._refresh_admin_members()
        else:
            self.admin_status.setText(
                "Админ-функции недоступны: у аккаунта нет достаточного power level для kick/ban"
            )
            self.member_select.clear()

    def _refresh_admin_members(self):
        room_id = self.admin_room_select.currentData()
        self.member_select.clear()
        if not room_id:
            return
        try:
            members = self.matrix.get_joined_members(room_id)
            members.sort(key=lambda item: item[0].lower())
            for display, user_id in members:
                self.member_select.addItem(f"{display} ({user_id})", user_id)
        except Exception as err:
            self._append_admin(f"Ошибка загрузки участников: {err}")

    def _set_admin_controls_enabled(self, enabled: bool):
        self.create_room_btn.setEnabled(enabled)
        self.kick_btn.setEnabled(enabled)
        self.ban_btn.setEnabled(enabled)
        self.unban_btn.setEnabled(enabled)
        self.member_select.setEnabled(enabled)
        self.reason_input.setEnabled(enabled)
        self.new_room_input.setEnabled(enabled)
        self.new_room_public.setEnabled(enabled)

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

    def _append_admin(self, message: str):
        self.admin_log.setTextColor(QColor("#ffb37a"))
        self.admin_log.append(message)
        self.admin_log.setTextColor(QColor("#ffffff"))

    def _append_chat(self, author: str, message: str, mine: bool):
        color = "#7fd4ff" if mine else "#e8a600"
        self.chat_view.setTextColor(QColor(color))
        self.chat_view.append(f"{author}: {message}")
        self.chat_view.setTextColor(QColor("#ffffff"))

    def _refresh_summary(self):
        total_rooms = max(1, len(self.rooms))
        mode = "demo" if self.matrix.demo_mode else "live"
        self.summary_label.setText(f"Matrix: {mode} • комнат — {total_rooms}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(BASE_STYLE)
    win = BnDChatWindow()
    win.show()
    sys.exit(app.exec_())
