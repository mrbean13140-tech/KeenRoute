# Совместимость NDMS

| Модель | NDMS | Статус | Заметки |
|---|---|---|---|
| — | — | не проверено | |

Проверить и записать:
- реальный лимит доменов в одной группе и общий (сейчас `MAX_DOMAINS_PER_GROUP = 300` в `core/commands.py`);
- формат `show/running-config` (строки `route object-group … auto [reject]` внутри секции `dns-proxy`);
- поля `show/interface` (type `Wireguard`, `link`, `description`).
