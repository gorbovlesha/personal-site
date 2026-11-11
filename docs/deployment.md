# Развёртывание на VPS

## Что понадобится

Для текущего статического сайта достаточно примерно 1 vCPU, 1 ГБ RAM и 20 ГБ SSD. Это оценка для самого сайта с небольшим или умеренным трафиком; большие фото, видео и дополнительные сервисы меняют расчёт.

Нужны поддерживаемый Linux, Git, Python 3.10+, Docker Engine с Compose plugin и домен. Node.js нужен для полной проверки при сборке на VPS; можно вместо этого собирать и проверять сайт на машине разработчика и передавать готовый `dist/`. В работающем контейнере Python и Node.js не используются.

Документация установки: [Docker Engine](https://docs.docker.com/engine/install/). HTTPS: [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https).

## Первый запуск из Git

1. Создайте DNS A-запись домена на публичный IPv4 VPS. AAAA добавляйте только при настроенном IPv6. Откройте TCP 80 и 443 у провайдера и в ОС; UDP 443 можно открыть для HTTP/3. Сохраните доступ по SSH.
2. Клонируйте **свой** репозиторий (замените URL), затем настройте окружение:

```bash
git clone YOUR_REPOSITORY_URL personal-site
cd personal-site
cp .env.example .env
```

3. В `.env` укажите свой домен без протокола и пути: `SITE_DOMAIN=me.example.com`.
4. Если Node.js доступен, выполните полный набор:

```bash
python3 scripts/project.py test
python3 scripts/project.py build --require-node
```

Если JS уже проверен в CI для этого коммита, на VPS без Node.js можно запустить `python3 scripts/project.py build`. Пропуск JS-проверки будет явно выведен в консоль.

5. Проверьте конфигурацию и запустите сервис:

```bash
docker compose config --quiet
docker compose run --rm --no-deps web caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker compose up -d
docker compose logs --tail=50 web
```

После распространения DNS и получения сертификата откройте `https://ВАШ_ДОМЕН`. Проверка CLI недостаточна: проверьте страницу, ссылки, модальные окна и ошибки CSP в консоли браузера.

Без публичного домена значение `localhost` использует локальный сертификат Caddy; это не production-настройка. Домен `.example` из шаблона нужно заменить.

## Вариант без Git, Python и Node.js на VPS

На машине разработчика выполните проверки и сборку. Передайте на сервер `dist/`, `Caddyfile`, `compose.yaml`, `.env.example`. В рабочей папке сервера создайте `.env` и запустите Caddy командами выше. Папка `dist/` должна существовать до запуска контейнера.

## Обновление

Запишите текущий SHA: `git rev-parse HEAD`. Сохраните локальные изменения до обновления; не используйте force/reset для их удаления.

```bash
git pull --ff-only
python3 scripts/project.py test
python3 scripts/project.py build --require-node
docker compose up -d --force-recreate web
```

На VPS без Node.js допускается `build`, если JS этого коммита проверен отдельно. Пересоздание контейнера после сборки нужно потому, что `dist/` заменяется целиком и старый bind mount может продолжать указывать на прежний каталог. На время сборки/перезапуска возможна короткая недоступность; схема рассчитана на небольшой личный сайт, без гарантии zero downtime.

После изменения `Caddyfile` снова выполните валидацию. После изменения домена обновите DNS и `.env`, затем пересоздайте сервис.

## Откат

Для отката к известному коммиту при чистой рабочей папке:

```bash
git switch --detach KNOWN_GOOD_COMMIT
python3 scripts/project.py build --require-node
docker compose up -d --force-recreate web
```

После восстановления разберитесь с причиной, вернитесь в `main` командой `git switch main`, получите исправление, повторите сборку и пересоздайте сервис. Конфигурация `.env` не хранится в Git: её изменения восстанавливаются отдельно.

## Эксплуатация

- Логи: `docker compose logs --tail=100 web`.
- Состояние: `docker compose ps`.
- Обновление образа: `docker compose pull web`, затем валидация и `docker compose up -d`.
- Резервные копии: исходники в Git, `.env` отдельно, постоянные volumes `caddy_data` и `caddy_config` средствами провайдера или Docker.
- Остановка: `docker compose down`. Volumes сохраняются; не используйте `down -v`, если хотите сохранить сертификаты.

Образ Caddy закреплён на major-версии `2-alpine`, поэтому новые патчи приходят при `pull`. Для воспроизводимого production-релиза закрепите проверенный digest образа. Автоматической выкладки и доступов к серверу в CI нет.
