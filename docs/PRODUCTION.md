# Продакшен Bio links

## Единственный публичный URL

**https://bytl.org/**

Админка: https://bytl.org/admin  
API: https://bytl.org/api/v1/...

## Где физически крутится

| Параметр | Значение |
|----------|----------|
| Сервер | `10.20.87.230` (Mobile Farm, Coolify) |
| Приложение Coolify | `clicks:analytics` (uuid `q11rqz2pmrlq4auva577uapd`) |
| Внутренний порт | `127.0.0.1:8102` |
| Публичный доступ | домен `bytl.org` через Coolify / Cloudflare |

## Railway — не используется

Деплой на Railway (`clicks-production-3604.up.railway.app`) **отключён**.

Чтобы окончательно убрать дубликат:

1. [Railway Dashboard](https://railway.app) → проект **clicks** → **Settings** → **Delete Project** (или отключить GitHub deploy).
2. Удалить сервис из Railway, если проект нужен для других целей.

Файл `railway.toml` из репозитория удалён.

## Cloudflare Tunnel

Ранее `bytl.org` и дубликат `clk.atom-farm.com` шли через контейнер `cloudflared` на `10.20.87.230` → `localhost:8102`.

Чтобы оставить **только bytl.org** и убрать лишние маршруты:

1. [Cloudflare Zero Trust](https://one.dash.cloudflare.com/) → **Networks** → **Tunnels** → ваш туннель.
2. В **Public Hostname** удалить маршрут **`clk.atom-farm.com`** (дубликат того же приложения).
3. Если переводите `bytl.org` на прямой прокси Coolify (без туннеля):
   - в Coolify для приложения указать домен **bytl.org**, включить SSL, сделать **Redeploy**;
   - в DNS Cloudflare для `bytl.org` указать origin (публичный IP сервера или прокси Coolify);
   - только после проверки `https://bytl.org/health` удалить маршрут **`bytl.org`** из туннеля.

**Важно:** пока туннель — единственный путь с интернета к `127.0.0.1:8102`, удаление маршрута `bytl.org` без замены **отключит сайт**.

## Деплой обновлений

Основной путь: **Coolify** (Git → build → контейнер на `8102`).

Запасной ручной путь (старый compose на `:8010`, сейчас не используется для bytl.org):

```powershell
.\scripts\deploy-mobilefarm.ps1
```

## Проверка после деплоя

```bash
curl -fsS https://bytl.org/health
# {"status":"ok"}
```
