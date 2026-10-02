# NTTunnel Bot — развёртывание на VPS

## Быстрый старт

```bash
# 1. Клонируй/скопируй проект на VPS
cd /root/nttunnel

# 2. Запусти установщик
chmod +x deploy/install_service.sh
bash deploy/install_service.sh

# 3. Отредактируй .env (если не сделал заранее)
nano /root/nttunnel/.env

# 4. Перезапусти
systemctl restart nttunnel-bot
```

## Что делает install_service.sh

1. Проверяет/устанавливает `python3`, `python3-venv`, `pip`
2. Создаёт venv в `/root/nttunnel/venv` и ставит `requirements.txt`
3. Создаёт `.env` из `.env.example` (если отсутствует)
4. Проверяет/запускает MongoDB
5. Генерирует `/etc/systemd/system/nttunnel-bot.service`
6. Включает автозапуск и стартует сервис

## Требования к VPS

- Ubuntu/Debian (или CentOS/RHEL)
- Python 3.10+
- MongoDB 6.0+ (локальный или удалённый)

## Обязательные переменные в `.env`

```
BOT_TOKEN=<токен от @BotFather>
ADMINS=<твой Telegram ID>
PANEL_BASE=https://<IP или домен панели>:2860/
ADMIN_USERNAME=<логин админа панели>
ADMIN_PASSWORD=<пароль админа панели>
```

## Управление сервисом

```bash
systemctl status nttunnel-bot      # статус
journalctl -u nttunnel-bot -f      # логи в реальном времени
journalctl -u nttunnel-bot -n 100  # последние 100 строк
systemctl restart nttunnel-bot     # перезапуск
systemctl stop nttunnel-bot        # остановка
```

## Структура systemd-сервиса

- **WorkingDirectory**: `/root/nttunnel` — бот читает `.env` оттуда
- **Restart=always** — перезапуск при падении или при недоступности MongoDB
- **RestartSec=5** — пауза между рестартами
- **WantedBy=multi-user.target** — автозапуск при загрузке VPS
