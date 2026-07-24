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
  - 23 июля — семь пар «один invoice + один и тот же общий packing»;
  - 24 июля — invoice/packing/batch `5904`, batch boxes `422`;
  - регрессии запускаются с Node.js 20.20.2.
- Production smoke `LOAD0006732` (execution `22`) был технически успешным,
  но функционально невалидным: он ошибочно объединил семь invoice в два
  итоговых листа. Листы переименованы в
  `_ARCHIVE_WRONG_LOAD0006732_20260724` и
  `_ARCHIVE_WRONG_ЧЗ_LOAD0006732_20260724`, затем скрыты.
- Актуальный контракт: один запуск MOIL = ровно один invoice + ровно один
  packing. Для следующего invoice тот же общий packing загружается повторно.
- Проверки количества документов развёрнуты в боте и Code-ноде; parser
  добавляет диагностику. Отдельные листы каждого invoice проверены ниже.

### Коррекция модели обработки

- Telegram-бот принимает для MOIL только `1 invoice + 1 packing`.
- Code-нода повторяет эту проверку и не позволяет прямому webhook обойти её.
- Общий packing прикладывается повторно к каждому invoice.
- Для повторяющегося SKU build выбирает точный набор packing-строк по
  quantity. Exact-subset поиск ограничен 20 строками и 5000 состояниями;
  неоднозначный результат остаётся warning и обрабатывается
  пропорциональным fallback.
- `_master_catalog` синхронизирован только по однозначным данным клиентского
  Excel или точному barcode. Backup:
  `_BACKUP_master_catalog_20260724_before_sku_sync` (hidden).
- Без источника остались:
  `BAGM26TRAVEL`, `BAGMP22STYLIST`, `M202BDM100`, `M205BDM100`,
  `MP26TRAVELC`. Эти поля должны оставаться подсвеченными до ответа клиента.

### Финальная проверка production

- Backup перед установкой parser/bot:
  - `/data/moil/parse_moil_bundle.py.bak.20260724T160505Z`;
  - `/opt/tg-upload-bot/bot.py.bak.20260724T160505Z`;
  - `/opt/n8n/.n8n/database.sqlite.bak.20260724T160505Z`.
- Дополнительные backup SQLite перед обновлениями Code-ноды:
  - `/opt/n8n/.n8n/database.sqlite.bak.20260724T161840Z`;
  - `/opt/n8n/.n8n/database.sqlite.bak.20260724T162157Z`.
- `PRAGMA integrity_check`: `ok`; `n8n` и `tg-upload-bot`: `active`;
  `/healthz`: HTTP `200`.
- Негативный E2E `LOAD0006732`: execution `23`, ожидаемый `error` до записи
  итоговых листов.
- Отдельные пары листов созданы для invoice:
  `126022808`, `126022809`, `126022810`, `126022812`, `126022814`,
  `126022815`, `126022816`, `126023953`.
- Временные executions `39`/`40` остановились только из-за Google Sheets
  read quota. После паузы повторные executions `41`/`42` завершились
  `success`; неполные листы скрыты с префиксом
  `_ARCHIVE_QUOTA_FAILED_`.
- Production-значения:
  - `126022816 / M201HCM40`: article `146549`, quantity `432`,
    total `1213.92`, boxes `3`, weight `25.92`, pallet `12`;
  - `126022816 / M105THL100`: article `877657`, quantity `360`,
    commercial discount `97.92`, boxes `6`, weight `54`, pallet `6`;
  - `126022815 / M201BDM100`: quantity `6`, boxes `0`, weight `1.68`,
    pallet `14`;
  - `126022810 / M201BDM100`: quantity `1188`, boxes `33`,
    weight `332.64`, pallet `16`.
- Итоговая локальная проверка: `37 passed`, `node --check` и
  `compileall` успешны; reviewer agent блокеров не нашёл.
