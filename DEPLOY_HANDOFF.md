# Production handoff

Актуально на 2026-07-24. Этот документ не содержит паролей, токенов и закрытых
ключей. Доступы передаются отдельно через менеджер секретов.

## Сервер и сервисы

- VPS: `103.112.69.124`, Ubuntu 22.04.
- n8n: systemd unit `n8n`, данные `/opt/n8n/.n8n`, HTTP port `5678`.
- Telegram bot: systemd unit `tg-upload-bot`, каталог
  `/opt/tg-upload-bot`.
- Python environment: `/opt/moil-venv`.
- Парсеры: `/data/moil/parse_{moil,moroccanoil,bandi}_bundle.py`.
- Загрузки: `/opt/tg_uploads/<company>/<shipment>/`.
- Service account: `/data/gcp-service-account.json`, режим доступа `0600`.

Основные команды:

```bash
systemctl status n8n tg-upload-bot --no-pager
journalctl -u n8n -n 100 --no-pager
journalctl -u tg-upload-bot -n 100 --no-pager
```

## n8n

- Workflow id: `oAsH9xGYN9uxtLPF`.
- Webhook path: `tg-upload-finished`.
- MOIL Code node: `Build Customs and CZ Rows`.
- Production MOIL spreadsheet:
  `1Av1S2wFoiLrIeeaBO-gFGgsBtzuwMgL1ziVd2lS6c3k`.
- Production BANDI spreadsheet:
  `1nk0J3xog_TzVraMyAwpE494Q-2XQ1yw6-amtsrsoNaU`.
- Production MOROCCANOIL spreadsheet:
  `1qMNUVwizL6okhjiTI6ViEbdVHAIc-prkqnAcYQkwEmI`.
- Обязательные MOIL-листы:
  `_master_catalog`, `TEMPLATE_CUSTOMS`, `TEMPLATE_CZ`.

Google credentials хранятся в n8n. Они не экспортируются в Git и после
чистого импорта workflow должны быть переподключены вручную.

## Безопасный релиз MOIL

1. Проверить локально:

   ```bash
   .venv/bin/python -m pytest -q
   ```

2. Сохранить резервные копии с timestamp:
   - `/data/moil/parse_moil_bundle.py`;
   - `/opt/n8n/.n8n/database.sqlite`.
3. Загрузить новый parser во временный путь и выполнить ручной smoke test на
   существующей поставке.
4. Выполнить Node.js-регрессии для `workflows/build_moil.js`.
5. Остановить n8n, атомарно обновить parser и код MOIL-ноды в SQLite, затем
   запустить n8n и проверить статус/логи.
   Для обновления Code-нод используется
   `scripts/update_n8n_workflow.py`; он синхронно меняет `workflow_entity` и
   текущую запись `workflow_history` в одной SQLite-транзакции.
6. Убедиться, что лист называется строго `TEMPLATE_CZ`. Если он имеет имя
   `Copy of TEMPLATE_CZ`, переименовать его перед пользовательским прогоном.
7. Запустить один контролируемый webhook-прогон и проверить:
   - execution завершён успешно;
   - созданы листы `<shipment>` и `ЧЗ <shipment>`;
   - суммы quantity invoice/packing совпадают;
   - FOC имеет `Total,$ = 0`;
   - строки компонентов набора без `#` и без денежных сумм;
   - Telegram получил итоговый статус.

Откат: восстановить parser и SQLite из созданных в том же релизе backup-файлов
и перезапустить `n8n`.

## Правила секретов

- Не коммитить `.env`, service-account JSON, production SQLite, клиентские
  документы или manifest.
- Не вставлять секреты в handoff-файлы и примеры.
- Telegram token и root credential, ранее переданные в открытом виде, следует
  ротировать отдельно после завершения работ.

## Текущий инцидент 2026-07-24

Новые документы поставщика F&O имеют другой PDF layout. Старый parser
возвращал ноль строк invoice/packing, после чего workflow дополнительно
останавливался из-за листа `Copy of TEMPLATE_CZ`. Исправление включает новый
layout parser, обработку общего packing, нового batch XLSX, kit/FOC и
восстановление канонического имени шаблона.

### Статус релиза

- Развёрнуто 2026-07-24.
- Backup parser:
  `/data/moil/parse_moil_bundle.py.bak.20260724T131646Z`.
- Backup n8n:
  `/opt/n8n/.n8n/database.sqlite.bak.20260724T131646Z`.
- SQLite `integrity_check`: `ok`.
- `n8n` и `tg-upload-bot`: `active`.
- Google Sheets: `_master_catalog`, `TEMPLATE_CUSTOMS`, `TEMPLATE_CZ`.
- Security smoke: некорректный shipment key остановлен в
  `Normalize Bot Payload` до SSH-ноды (execution `21`, ожидаемый `error`).
- Fixture validation:
  - 23 июля — invoice/packing `32266`, 7 invoice + 1 общий packing;
  - 24 июля — invoice/packing/batch `5904`, batch boxes `422`;
  - полный набор тестов с Node.js 20.20.2 — `15 passed`.
- Production end-to-end smoke: execution `22`, статус `success`.
  Полный комплект сохранён в `/opt/tg_uploads/moil/LOAD0006732`; созданы
  листы `LOAD0006732` и `ЧЗ LOAD0006732`.
  - customs: 94 строки, из них 89 товарных + 5 компонентов;
  - ЧЗ: 106 строк, из них 101 товарная + 5 компонентов;
  - товарное quantity в обоих листах: `32266`;
  - коробки в обоих листах: `854`;
  - денежные поля пяти component-строк пустые.
