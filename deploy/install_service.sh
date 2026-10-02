#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# NTTunnel Bot — автоматическая установка на VPS.
#
# Использование (на VPS, root):
#   cd /root/nttunnel
#   chmod +x deploy/install_service.sh
#   bash deploy/install_service.sh
#
# После установки:
#   systemctl status nttunnel-bot     — статус
#   journalctl -u nttunnel-bot -f     — логи в реальном времени
#   systemctl restart nttunnel-bot    — перезапуск
set -euo pipefail

BOT_DIR="/root/nttunnel"
VENV_DIR="$BOT_DIR/venv"
SERVICE_NAME="nttunnel-bot"
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"
PY_BIN=""
PY_OK=0

echo "================================================"
echo " NTTunnel Bot — установка"
echo "================================================"

# ---- 0. проверяем, что мы в нужной папке -------------------------------
if [ ! -f "$BOT_DIR/bot/main.py" ]; then
    echo "[FATAL] Бот не найден в $BOT_DIR (нет bot/main.py)."
    echo "        Склонируй/скопируй проект в $BOT_DIR и запусти оттуда."
    exit 1
fi

cd "$BOT_DIR"

# ---- 1. системные зависимости ----------------------------------------
echo "[1/6] Проверяю системные зависимости..."
if ! command -v python3 >/dev/null 2>&1; then
    echo "      python3 не найден — устанавливаю..."
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -qq
        apt-get install -y -qq python3 python3-venv python3-pip
    elif command -v yum >/dev/null 2>&1; then
        yum install -y python3 python3-venv python3-pip
    else
        echo "[FATAL] Не могу установить python3 автоматически. Поставь вручную."
        exit 1
    fi
fi

# ---- 2. виртуальное окружение ---------------------------------------
echo "[2/6] Создаю виртуальное окружение..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi
PY_BIN="$VENV_DIR/bin/python"

echo "[3/6] Устанавливаю Python-зависимости..."
"$PY_BIN" -m pip install --upgrade pip wheel -q
"$PY_BIN" -m pip install -r requirements.txt -q

# ---- 3. .env существует? --------------------------------------------
echo "[4/6] Проверяю .env..."
if [ ! -f "$BOT_DIR/.env" ]; then
    echo "      .env не найден — копирую из .env.example..."
    if [ -f "$BOT_DIR/.env.example" ]; then
        cp "$BOT_DIR/.env.example" "$BOT_DIR/.env"
        echo "[WARN] .env создан из шаблона. ОБЯЗАТЕЛЬНО отредактируй:"
        echo "       BOT_TOKEN, ADMINS, PANEL_BASE, ADMIN_USERNAME, ADMIN_PASSWORD"
        echo "       nano $BOT_DIR/.env"
    else
        echo "[WARN] .env.example тоже нет. Создай .env вручную."
    fi
else
    echo "      .env на месте."
fi

# ---- 4. проверяем MongoDB -------------------------------------------
echo "[5/6] Проверяю MongoDB..."
if systemctl is-active --quiet mongod 2>/dev/null; then
    echo "      mongod запущен."
elif command -v mongod >/dev/null 2>&1; then
    echo "      mongod не запущен — пытаюсь стартовать..."
    systemctl start mongod 2>/dev/null || true
    if systemctl is-active --quiet mongod 2>/dev/null; then
        echo "      mongod запущен успешно."
        systemctl enable mongod
    else
        echo "[WARN] Не удалось запустить mongod автоматически."
        echo "       Запусти вручную: systemctl start mongod"
    fi
else
    echo "[WARN] MongoDB не установлен. Бот не сможет работать без неё."
fi

# ---- 5. генерируем systemd-сервис -----------------------------------
echo "[6/6] Создаю systemd-сервис..."
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=NTTunnel Telegram Bot
After=network.target mongod.service
Wants=mongod.service

[Service]
Type=simple
User=root
WorkingDirectory=$BOT_DIR
ExecStart=$VENV_DIR/bin/python -X utf8 -u -m bot
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-$BOT_DIR/.env

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

# ---- итог ------------------------------------------------------------
echo ""
echo "================================================"
echo " Установка завершена!"
echo "================================================"
echo ""
echo "Полезные команды:"
echo "  systemctl status $SERVICE_NAME     — статус"
echo "  journalctl -u $SERVICE_NAME -f     — логи"
echo "  systemctl restart $SERVICE_NAME    — перезапуск"
echo "  systemctl stop $SERVICE_NAME       — остановка"
echo ""
echo "Убедись, что в $BOT_DIR/.env заполнены:"
echo "  BOT_TOKEN, ADMINS, PANEL_BASE, ADMIN_USERNAME, ADMIN_PASSWORD"
echo ""

# показываем статус
if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    echo "[OK] Сервис $SERVICE_NAME запущен."
else
    echo "[WARN] Сервис не запустился. Проверь логи:"
    echo "       journalctl -u $SERVICE_NAME -n 50"
fi