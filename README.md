<p align="center"><img src="assets/icon.png" width="96" alt="KeenRoute"></p>

<h1 align="center">KeenRoute</h1>
<p align="center"><b>Умные DNS-маршруты для Keenetic / Netcraze</b><br>для тех, кто устал вручную вносить списки доменов · Windows 10/11</p>

<p align="center">
  <a href="https://github.com/mrbean13140-tech/KeenRoute/releases/latest/download/KeenRoute.exe"><b>⬇ Скачать KeenRoute.exe</b></a>
  &nbsp;·&nbsp; <a href="https://github.com/mrbean13140-tech/KeenRoute/releases">Все версии</a>
</p>

<p align="center"><img src="docs/screenshots/main.png" width="860" alt="Главное окно"></p>

| Каталог сервисов | DNS / DoT / DoH |
|---|---|
| <img src="docs/screenshots/catalog.png" width="420"> | <img src="docs/screenshots/dns.png" width="420"> |
| **Сохранённые роутеры** | **Светлая тема** |
| <img src="docs/screenshots/login.png" width="420"> | <img src="docs/screenshots/main_light.png" width="420"> |

## Для кого

Для тех, кто **устал вручную вносить списки доменов** в веб-интерфейс Keenetic: копировать домены по одному, искать, какие нужны для YouTube или ChatGPT, переключать каждый список на нужный VPN и бояться что-то сломать.

KeenRoute делает это за вас:

- **Каталог сервисов** — отметили галочками YouTube, Telegram, ChatGPT, Netflix и т. д., выбрали туннель — списки появились на роутере. Есть поиск по базе из ~1500 сервисов, большие списки (Apple, Google, Microsoft) автоматически ужимаются до главного.
- **Маршрутизация DNS** — все списки в одной таблице: какой список через какой шлюз идёт и в сети ли туннель. Перевести один, несколько или все списки на другой WireGuard — пара кликов или перетаскивание.
- **DoT / DoH** — шифрованный DNS из готовых шаблонов (Cloudflare, Google, Quad9, AdGuard, Яндекс), в том числе только для отдельных доменов. Учитывает лимит Keenetic — не больше 8 записей DoT и 8 DoH (каждый домен — отдельная запись).
- **Безопасно** — перед любым изменением показывается, что именно поменяется; перед применением делается бэкап, после — проверка, при ошибке — откат одной кнопкой.
- **Несколько роутеров** — сохраняйте дом, офис, дачу и подключайтесь в один клик, в том числе удалённо через KeenDNS.
- **Проверка домена** — вводите `m.youtube.com` и видите, в каком он списке и через какой туннель пойдёт.
- **Импорт и экспорт в файл** — перенести списки с одного роутера на другой.

Работает через встроенный API роутера (RCI): SSH, Entware и OPKG не нужны. Подходят Keenetic и Netcraze на NDMS 3.x–5.x.

## Установка

Скачайте [KeenRoute.exe](https://github.com/mrbean13140-tech/KeenRoute/releases/latest/download/KeenRoute.exe) и запустите — Windows 10/11, 64-бит, ничего дополнительно ставить не нужно. При первом запуске программа предложит установиться в `%LOCALAPPDATA%\Programs\KeenRoute` и создаст ярлыки на рабочем столе и в меню «Пуск». Обновления программа проверяет и ставит сама.

При первом запуске Windows может показать «Windows защитила ваш компьютер» — файл без цифровой подписи. Нажмите «Подробнее → Выполнить в любом случае».

## Где хранятся данные

`%APPDATA%\KeenRoute\` — сохранённые роутеры, бэкапы (`backups\`), база доменов (`db\`), журнал (`logs\app.log`). Пароли роутеров хранятся в диспетчере учётных данных Windows, а не в файлах.

## Сборка из исходников

```
pip install -r requirements-dev.txt
python -m pytest -q
python run.py
pyinstaller --onefile --windowed --name KeenRoute --icon assets/icon.ico --add-data "assets;assets" --paths src run.py
```

Каждый коммит в `main` собирается в GitHub Actions и публикуется в Releases.

---

Keenetic и Netcraze — товарные знаки их владельцев. KeenRoute — независимый проект и не связан с производителем.
