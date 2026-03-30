# BnDChat

Минимально рабочий desktop-чат на PyQt5 с реальным Matrix-бэкендом (Synapse) через `matrix-nio`.

## Что уже работает
- Подключение к Matrix homeserver (Synapse) по логину/паролю.
- Загрузка списка joined-комнат.
- Отправка текстовых сообщений (`m.room.message` + `m.text`).
- Получение входящих сообщений в реальном времени через sync-loop.

---

## 1) Локальный запуск для теста

### Быстрый sandbox-режим (эмуляция сервера + тестовый юзер)
Если нужен локальный тест без поднятия Synapse, в приложении есть эмуляция:

```bash
python bndchat_matrix_pyqt.py
```

В форме подключения укажи, например:
- **Homeserver:** `sandbox`
- **Логин:** `@sandbox-user:local`
- **Пароль:** `sandbox` (или оставь пустым)

После подключения появятся тестовые комнаты, echo-бот и админ-функции в песочнице.

### Вариант A: подключиться к уже существующему Synapse
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install PyQt5 "matrix-nio[e2e]"
```

Запуск:
```bash
export MATRIX_HOMESERVER="https://your-synapse.example.com"
export MATRIX_USER="@alice:your-synapse.example.com"
export MATRIX_PASSWORD="your-password"
python bndchat_matrix_pyqt.py
```

После старта:
1. Проверь поля homeserver/login/password (подтягиваются из env).
2. Нажми **«Подключиться к Matrix»**.
3. Выбери комнату и отправь сообщение.

### Вариант B: поднять Synapse локально через Docker Compose
Пример `docker-compose.yml`:

```yaml
services:
  synapse:
    image: matrixdotorg/synapse:latest
    container_name: bndchat-synapse
    ports:
      - "8008:8008"
    environment:
      - SYNAPSE_SERVER_NAME=localhost
      - SYNAPSE_REPORT_STATS=no
    volumes:
      - ./synapse-data:/data
```

Первичная генерация конфига:
```bash
mkdir -p synapse-data
docker run --rm \
  -e SYNAPSE_SERVER_NAME=localhost \
  -e SYNAPSE_REPORT_STATS=no \
  -v "$(pwd)/synapse-data:/data" \
  matrixdotorg/synapse:latest generate
```

Запуск Synapse:
```bash
docker compose up -d
```

Создание тестового пользователя:
```bash
docker exec -it bndchat-synapse register_new_matrix_user \
  -u alice -p alicepass -a -c /data/homeserver.yaml http://localhost:8008
```

Дальше запускай клиент:
```bash
export MATRIX_HOMESERVER="http://localhost:8008"
export MATRIX_USER="@alice:localhost"
export MATRIX_PASSWORD="alicepass"
python bndchat_matrix_pyqt.py
```

---

## 2) Production-развёртывание (базовый вариант)

### Рекомендуемая схема
- Synapse в Docker (или Kubernetes).
- PostgreSQL как основная БД Synapse.
- Reverse proxy (Nginx/Caddy/Traefik) с TLS.
- Отдельный домен, например `matrix.example.com`.
- Открытые federation-порты, если нужна федерация.

### Минимальный production checklist
1. Включить HTTPS (Let's Encrypt / корпоративный сертификат).
2. Использовать PostgreSQL вместо SQLite.
3. Настроить регулярные backup БД и `/data`.
4. Закрыть доступ к служебным endpoint’ам через firewall/reverse proxy.
5. Вынести секреты в безопасное хранилище (не хранить пароли в репозитории).
6. Настроить мониторинг/алерты (CPU, RAM, диск, ошибки Synapse).

### Запуск BnDChat-клиента в production
На рабочем месте пользователя достаточно:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install PyQt5 "matrix-nio[e2e]"
export MATRIX_HOMESERVER="https://matrix.example.com"
export MATRIX_USER="@alice:example.com"
export MATRIX_PASSWORD="***"
python bndchat_matrix_pyqt.py
```

---

## Ограничения MVP
- Только текстовые сообщения.
- Нет регистрации/создания комнаты из UI (предполагается, что пользователь и комнаты уже существуют на Synapse).
- Нет локального шифрования истории/медиа-файлов в интерфейсе.
