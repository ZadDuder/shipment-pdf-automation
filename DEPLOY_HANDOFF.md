# Production handoff

Актуально на 2026-07-30. Этот документ не содержит паролей, токенов и закрытых
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
   - для каждого invoice созданы листы `<invoiceNo>` и `ЧЗ <invoiceNo>`;
   - суммы quantity invoice/packing совпадают;
   - FOC имеет `Total,$ = 0`;
   - строки компонентов набора без `#` и без денежных сумм;
   - Telegram получил итоговый статус.

Откат: восстановить parser и SQLite из созданных в том же релизе backup-файлов
и перезапустить `n8n`.

## Безопасный релиз MOROCCANOIL F&O

1. Обрабатывать каждый новый комплект отдельно по `ILSO`: invoice, packing и
   соответствующий batch. Не смешивать частично присланные комплекты.
2. Локально прогнать `tests/test_parse_moroccanoil_fno.py`.
3. Сформировать bundle для каждого контрольного `ILSO` и запустить
   `scripts/verify_moroccanoil_build.js` через Node.js 20+.
4. Перед релизом создать timestamp-backup:
   - `/data/moil/parse_moroccanoil_bundle.py`;
   - `/opt/n8n/.n8n/database.sqlite`.
5. Обновить parser и ноду `Build Moroccanoil Customs and CZ Rows` через
   `scripts/update_n8n_workflow.py`; источник ноды —
   `workflows/build_moroccanoil.js`.
6. После запуска проверить `systemctl is-active n8n`, `/healthz`, SQLite
   `PRAGMA integrity_check` и хеши установленных файлов.
7. Контрольные инварианты:
   - invoice quantity совпадает с packing quantity по агрегату SKU;
   - batch quantity после конвертации совпадает с packing pieces;
   - FOC сохраняет `Total,$ = 0`;
   - `boxes=0` остаётся нулём;
   - вес/коробки batch-строки относятся только к её паллете.

### Статус релиза MOROCCANOIL F&O 2026-07-30

- Релиз развёрнут с timestamp `20260730T124949Z`.
- Backup parser:
  `/data/moil/parse_moroccanoil_bundle.py.bak.moroc-fno-20260730T124949Z`.
- Backup n8n SQLite:
  `/opt/n8n/.n8n/database.sqlite.backup-moroc-fno-20260730T124949Z`.
- SHA-256 установленного parser:
  `a1a8b939ff339b464f07f0db98bf9894983ae2e08fedd6d4fb1d2e4ea3ff487a`.
- SHA-256 ноды `Build Moroccanoil Customs and CZ Rows`:
  `b4ccb951f6e058bf35db7ff53c3b5819f7c1ef279819cf1434b5d5f8b32813d2`;
  `workflow_entity` совпадает с текущей записью `workflow_history`.
- `PRAGMA integrity_check = ok`; `n8n` и `tg-upload-bot`: `active`;
  `/healthz`: HTTP 200 / `{"status":"ok"}`.
- Production parser через `/opt/moil-venv/bin/python` обработал без
  предупреждений:
  - `ILSO000003204`: 103 invoice / 103 packing / 105 batch;
  - `ILSO000000570`: 2 invoice / 3 packing / 3 batch;
  - `ILSO000000580`: 50 invoice / 50 packing / 50 batch;
  - старый формат `8251014`: 88 invoice / 71 packing / 83 batch.
- Node.js 20-проверка новых комплектов подтвердила:
  - `003204`: 103 customs / 105 ЧЗ, quantity 7 848, boxes 220,
    weight 919.902;
  - `570`: 2 customs / 3 ЧЗ, quantity 948, boxes 20, FOC total 0;
  - `580`: 50 customs / 50 ЧЗ, quantity 400, boxes 0, FOC total 0.
- Первая попытка релиза была автоматически откачена защитным скриптом:
  systemd уже сообщил `active`, но HTTP port ещё не открылся. После добавления
  ожидания `/healthz` повторный релиз и все проверки прошли успешно.
- Клиентские файлы и smoke-результаты удалены из `/tmp`. Webhook не
  запускался, поэтому тест не изменял Google Sheets и не отправлял Telegram.
- Локально: `40 passed`, `24 skipped` без Node.js; серверная Node.js-проверка
  прошла. Повторный reviewer agent не нашёл blocker/high/medium замечаний.

## Правила секретов

- Не коммитить `.env`, service-account JSON, production SQLite, клиентские
  документы или manifest.
- Не вставлять секреты в handoff-файлы и примеры.
- Telegram token и root credential, ранее переданные в открытом виде, следует
  ротировать отдельно после завершения работ.

## Текущий контракт MOIL (исправлен 2026-07-28)

- Один запуск содержит все invoice одной поставки, ровно один общий packing и
  не более одного общего batch-файла.
- Результат: отдельная пара `<invoiceNo>` / `ЧЗ <invoiceNo>` для каждого
  invoice.
- Для повторяющегося SKU build сначала выбирает packing-строки по quantity,
  потребляет их один раз между invoice, затем связывает batch по SSCC,
  вложенному `IN CB` или паллете.
- Для Google Sheets используются пакетные create/clear/write запросы, чтобы
  полный комплект не умножал количество API-вызовов на число invoice.
- Контракт `1 invoice + 1 packing`, введённый 2026-07-24, отменён: полный
  пакет загружается один раз. Ошибочный общий ЧЗ от 2026-07-27 также отменён:
  ЧЗ остаётся отдельным для каждого invoice.

### Статус релиза 2026-07-28

- Исправление с индивидуальным ЧЗ на каждый invoice развёрнуто на production.
- Последний backup timestamp n8n SQLite: `20260728T110308Z`
  (первичный релиз пар invoice/ЧЗ: `20260728T091138Z`);
  `PRAGMA integrity_check`: `ok`.
- Executions `47` и `48` на полном комплекте `LOAD0006732` успешно прошли
  parser, build, создание, очистку и запись всех листов. Ошибка финальной
  Telegram-ноды ожидаема: использован тестовый `chat_id=0`, чтобы не
  отправлять клиенту служебное сообщение.
- В Google Sheets подтверждены 7 видимых customs-листов и 7 видимых
  индивидуальных ЧЗ-листов:
  `126022808`, `126022809`, `126022810`, `126022812`, `126022814`,
  `126022815`, `126022816`.
- Ошибочный общий лист `ЧЗ LOAD0006732` переименован в
  `_ARCHIVE_WRONG_COMBINED_CZ_LOAD0006732_20260728` и скрыт. Данные сохранены
  для обратимого отката.
- Follow-up execution `50` добавил блочную расшифровку набора в
  `ЧЗ 126022812`: parent `MP26TRAVELC` quantity `96` / pallet `14`,
  `576` / `15`, `304` / `16`; под каждым parent повторяются пять компонентов
  в порядке invoice с количеством своего блока. Полная построчная сверка
  всех 14 вкладок после записи дала `0` расхождений.
- `M101LT100` подтверждён чтением индивидуальных пар:
  - `126022814` / `ЧЗ 126022814`: quantity 5, boxes 0, weight 1.35,
    pallet 13, batch `14477BZ`, total 0;
  - `126022816` / `ЧЗ 126022816`: quantity 240, boxes 5, weight 69.1,
    pallet 9, batch `14734LDZ`, total 2126.4.
- `n8n` и `tg-upload-bot`: `active`; n8n `/healthz`: HTTP 200 / `ok`.
- Локальная проверка: `49 passed`, JS syntax, `compileall`, ручной прогон
  реального комплекта; reviewer agent не нашёл блокирующих замечаний.

### Статус релиза 2026-07-27

Этот статус описывает ошибочную версию с общим ЧЗ и сохранён только как
история инцидента. Версия заменена релизом 2026-07-28.

- Развёрнуто на production.
- Backup timestamp: `20260727T145610Z` для parser, bot validation и n8n
  SQLite.
- `PRAGMA integrity_check`: `ok`.
- `n8n` и `tg-upload-bot`: `active`; `/healthz`: HTTP 200 / `ok`.
- Execution `45` выполнил parser, build, создание листов и обе пакетные записи.
  Финальная Telegram-нода ожидаемо получила ошибку из-за тестового
  `chat_id=0`, выбранного специально, чтобы не отправлять клиенту сообщение
  без согласования.
- В Google Sheets подтверждены семь customs-листов и общий
  `ЧЗ LOAD0006732`.
- `M101LT100` подтверждён чтением итоговых ячеек:
  - invoice `126022814`: quantity 5, boxes 0, weight 1.35, pallet 13,
    batch `14477BZ`, total 0;
  - invoice `126022816`: quantity 240, boxes 5, weight 69.1, pallet 9,
    batch `14734LDZ`, total 2126.4.
- Семь старых индивидуальных ЧЗ-листов `ЧЗ 126022...` переименованы в
  `_ARCHIVE_OLD_CZ_<invoice>_20260727` и скрыты; восстановление возможно
  простым обратным переименованием.
- Локальная проверка релиза: `48 passed`, JS syntax, `compileall` и ручной
  прогон реального комплекта. Повторный reviewer agent не нашёл блокеров.

## Инцидент 2026-07-24

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
- Применённый 24 июля контракт `1 invoice + 1 packing` позднее оказался
  временной неверной интерпретацией и заменён контрактом от 27 июля.
- Проверки количества документов развёрнуты в боте и Code-ноде; parser
  добавляет диагностику. Отдельные листы каждого invoice проверены ниже.

### Временная коррекция модели обработки 2026-07-24

- Telegram-бот временно принимал для MOIL только `1 invoice + 1 packing`;
  это ограничение снято 2026-07-27.
- Code-нода повторяет эту проверку и не позволяет прямому webhook обойти её.
- Временная схема требовала повторно прикладывать общий packing к каждому
  invoice; с 2026-07-27 полный пакет загружается один раз.
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
