# MediaHub

Личный медиахаб на Flask + React для больших коллекций мемов, картинок и видео.

## Что уже реализовано

- first-run setup с созданием первого админа
- отдельный Flask API и отдельный React frontend
- массовая загрузка файлов и архивов с клиентским прогрессом
- resumable upload: продолжение загрузки после сетевого обрыва
- библиотека с поиском, фильтрами и редактированием тегов
- кастомные теги: solid, gradient, image-avatar
- потоковая разметка файлов
- поиск точных дубликатов по SHA-256
- временные сгораемые ссылки
- роли `admin` и `user`
- серверный мониторинг: CPU, RAM, network, disk
- предупреждение о нехватке места и блокировка загрузок для обычных пользователей
- экспорт и импорт архива
- отправка экспортов и алертов в Telegram
- Telegram bot polling: `/start`, `/help`, приём архивов document-сообщением
- хранение финальных данных рядом с проектом в `./data`
- быстрый upload runtime через внутренний Docker volume для временных chunk-файлов
- опциональное шифрование файлов через `MEDIAHUB_ENCRYPTION_PASSPHRASE`

## Структура

- `backend/` - Flask API
- `frontend/` - React/Vite UI
- `data/` - база, файлы, превью, экспорты
- временные chunk/upload-файлы в Docker по умолчанию вынесены во внутренний volume `mediahub_imports`

## Быстрый запуск через Docker

1. Скопируйте `.env.example` в `.env` и поменяйте `MEDIAHUB_SECRET_KEY`.
2. Если хотите шифрование файлов на диске, задайте `MEDIAHUB_ENCRYPTION_PASSPHRASE`.
3. Запустите:

```bash
docker compose up --build
```

4. Контейнеры слушают на `0.0.0.0`, то есть будут доступны и локально, и по сети.
5. Откройте [http://localhost:8080](http://localhost:8080) или `http://<IP_вашего_сервера>:8080` с другого устройства.
6. Если хотите, чтобы временные ссылки и фронтовые URL генерировались не на `localhost`, а на ваш IP/домен, укажите это в `.env` через `MEDIAHUB_FRONTEND_BASE_URL`.
7. На первом запуске создайте админа и при желании сразу заполните Telegram-настройки.
8. Если хотите вернуть временные upload-файлы обратно в host path, можно задать `MEDIAHUB_IMPORTS_ROOT` в `.env`, но на Windows это часто медленнее, чем внутренний Docker volume.

## Telegram

- `telegram.bot_token` и `telegram.chat_id` можно задать при первом запуске или в настройках.
- Экспорт можно отправлять в Telegram из админского экрана.
- При низком месте на диске бот шлёт уведомления, если Telegram настроен.
- Большие экспортные архивы режутся на части по 48 МБ.
- Бот отвечает на `/start` и показывает `chat_id`, который потом можно вставить в настройки.
- Если архив `.zip/.tar/.tgz` прислать боту документом из разрешённого чата, он уйдёт в импорт.
- Важно: через обычный cloud `api.telegram.org` бот может скачать только небольшие файлы. Для больших архивов через Telegram нужен локальный Telegram Bot API server.

### Локальный Telegram Bot API в Docker

Если хотите, чтобы локальный Telegram Bot API server поднимался и опускался вместе с проектом, включите отдельный compose-сервис:

1. Получите `api_id` и `api_hash` на [my.telegram.org](https://my.telegram.org).
2. В `.env` пропишите:

```env
MEDIAHUB_TELEGRAM_API_BASE_URL=http://telegram-bot-api:8081
MEDIAHUB_TELEGRAM_LOCAL_API_ID=123456
MEDIAHUB_TELEGRAM_LOCAL_API_HASH=your_api_hash
COMPOSE_PROFILES=telegram-local-api
```

3. Если бот раньше работал через обычный cloud Bot API, один раз разлогиньте его там перед первым запуском локального сервера:

```text
https://api.telegram.org/bot<YOUR_BOT_TOKEN>/logOut
```

4. После этого запускайте проект как обычно:

```bash
docker compose up --build
```

5. Сервис `telegram-bot-api` будет жить внутри того же `docker compose`, а backend будет ходить к нему по `http://telegram-bot-api:8081`.
6. Файлы локального Bot API будут лежать рядом с проектом в `./data/telegram-bot-api`.

## Ограничения текущей версии

- perceptual duplicates сейчас рассчитаны только для изображений, не для видео
- видео-метаданные и кадры-превью сделаны минимально, без ffmpeg
- фоновая обработка построена на потоках Flask-процесса, поэтому production-конфиг сейчас рассчитан на один backend worker

## Локальная разработка

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Backend:

```bash
cd backend
pip install -r requirements.txt
python app.py
```
