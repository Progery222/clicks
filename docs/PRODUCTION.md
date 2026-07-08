# Продакшен Bio links

## Единственный публичный URL

**https://bytl.org/**

Админка: https://bytl.org/admin  
API: https://bytl.org/api/v1/...

Дубликаты **не используются**:

- ~~`clicks-production-3604.up.railway.app`~~ (Railway) — удалить вручную в [Railway Dashboard](https://railway.app)
- ~~`clk.atom-farm.com`~~ — убрать маршрут в Cloudflare Tunnel (см. ниже)

## Где физически крутится

| Параметр | Значение |
|----------|----------|
| Сервер | `10.20.87.230` (Mobile Farm, Coolify) |
| Приложение Coolify | `clicks:analytics` (uuid `q11rqz2pmrlq4auva577uapd`, id=14) |
| Внутренний порт | `127.0.0.1:8102` → контейнер `:8000` |
| Прокси | Traefik `coolify-proxy` на **`:80`** (см. ниже) |
| Публичный HTTPS | Cloudflare → origin (пока частично через Tunnel) |

### Состояние на 2026-07-08

- В Coolify для приложения указан домен **`https://bytl.org`**, выполнен redeploy — в Traefik/Caddy-лейблах контейнера `Host(\`bytl.org\`)`.
- Запущен **`coolify-proxy`** (Traefik v3.6) на порту **80** (`0.0.0.0:80`).
- Порт **443** на сервере занят **Tailscale** — Traefik на 443 не поднимается. Для HTTPS с интернета: Cloudflare (прокси) → origin **:80**, режим SSL **Flexible** или Full после появления origin HTTPS.
- С локального сервера: `curl -H 'Host: bytl.org' http://127.0.0.1/health` → `{"status":"ok"}`.

## Railway — отключить и удалить

Файл `railway.toml` из репозитория удалён. Сервис на Railway может ещё отвечать, пока проект не удалён:

1. [Railway Dashboard](https://railway.app) → проект **clicks** → **Settings** → **Delete Project** (или отключить GitHub deploy).
2. Убедиться, что `https://clicks-production-3604.up.railway.app/health` больше не отвечает.

CLI `railway` с этой машины сейчас без валидного OAuth — удаление только через Dashboard.

## Cloudflare Tunnel

На `10.20.87.230` контейнер **`cloudflared`** (host network) обслуживает **много** сервисов (не только Bio links). **Не останавливайте** его целиком.

Для Bio links нужно убрать только лишние hostname:

1. [Cloudflare Zero Trust](https://one.dash.cloudflare.com/) → **Networks** → **Tunnels** → туннель с `bytl.org` / `clk.atom-farm.com`.
2. Удалить маршрут **`clk.atom-farm.com`** → `localhost:8102` (дубликат).
3. Когда origin по **A-записи** `bytl.org` → `86.57.192.105` и порт **80** доступен с интернета (Traefik + Cloudflare Flexible):
   - удалить маршрут **`bytl.org`** из туннеля;
   - в DNS Cloudflare: `bytl.org` → A `86.57.192.105`, прокси включён (оранжевое облако).

**Важно:** пока снаружи не открыт HTTP(S) до Traefik, удаление `bytl.org` из туннеля **отключит сайт**.

## Деплой обновлений

Основной путь: **Coolify** (Git `Progery222/clicks` → build → контейнер на `8102`).

Запасной ручной путь (старый compose на `:8010`, не используется для bytl.org):

```powershell
.\scripts\deploy-mobilefarm.ps1
```

## Проверка

```bash
curl -fsS https://bytl.org/health
# {"status":"ok"}
```
