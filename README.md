# Shipment PDF Automation

Автоматизация обработки документов поставок для `moil`, `moroccanoil` и
`bandi`.

Пользователь загружает invoice, packing list и при необходимости batch-файл
через Telegram-бота. Бот сохраняет комплект и вызывает webhook n8n. Python-
парсер приводит документы к единому JSON, после чего n8n обогащает строки
данными мастер-каталога и создаёт листы таможни и Честного Знака в Google
Sheets.

## Структура

- `bot/` — Telegram-бот и systemd unit.
- `пайтон скрипт/` — bundle-парсеры документов.
- `workflows/*.js` — поддерживаемые исходники MOIL и MOROCCANOIL Code-нод
  для n8n.
- `scripts/sync_moil_workflow_export.py` — синхронизация этих исходников и
  Google Sheets batch API-нод с `final.json`.
- `final.json` — экспорт workflow n8n; перед импортом сверять с production.
- `tests/` — регрессии парсера и Code-ноды.
- `CLAUDE.md` — подробные бизнес-правила и архитектура.
- `DEPLOY_HANDOFF.md` — актуальная карта production и процедура релиза.

Клиентские документы, локальные результаты, credentials и service-account
ключи намеренно исключены из Git с помощью allowlist в `.gitignore`.

## Локальная проверка

Требуется Python 3.10+:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Тесты `workflows/build_moil.js` и `workflows/build_moroccanoil.js`
дополнительно требуют Node.js 20+. Без Node они будут явно отмечены как
skipped.

Ручной запуск MOIL-парсера:

```bash
.venv/bin/python "пайтон скрипт/parse_moil_bundle.py" \
  --shipment-key LOAD0012605 \
  --input-dir /path/to/shipment \
  --pretty
```

Контракт MOIL: в одну поставку загружаются все invoice, ровно один общий
packing и не более одного общего batch-файла. Результат — отдельная пара
листов `<invoiceNo>` и `ЧЗ <invoiceNo>` для каждого invoice.

В ЧЗ набор, разделённый по нескольким паллетам или batch, выводится блоками:
сначала строка набора для конкретной паллеты, затем его компоненты в порядке
invoice и с количеством этой паллеты. Денежные суммы остаются только на
строке самого набора.

Ручной запуск MOROCCANOIL-парсера:

```bash
.venv/bin/python "пайтон скрипт/parse_moroccanoil_bundle.py" \
  --shipment-key ILSO000003204 \
  --input-dir /path/to/shipment \
  --pretty
```

Новый формат MOROCCANOIL от июля 2026 обрабатывается отдельным комплектом на
каждый `ILSO`: один invoice PDF, один `MO Packing Slip ...pdf` и, если товар
маркируется, batch XLSX. PDF читается по табличному слою; количество batch
автоматически определяется как коробки или штуки через сопоставление
SKU+паллета с packing. Неполные комплекты не следует объединять с полными.

Сквозная проверка трёх эталонных комплектов выполняется Node-скриптом:

```bash
node scripts/verify_moroccanoil_build.js \
  workflows/build_moroccanoil.js \
  /tmp/ILSO000003204-bundle.json \
  /tmp/ILSO000000570-bundle.json \
  /tmp/ILSO000000580-bundle.json
```

## Production

Production развёрнут на VPS и состоит из двух systemd-сервисов: `n8n` и
`tg-upload-bot`. Парсеры находятся в `/data/moil`, загрузки — в
`/opt/tg_uploads`. Перед изменениями обязательны резервные копии файла парсера
и SQLite-базы n8n. Секреты хранятся только на сервере и не должны попадать в
репозиторий.

Пошаговая процедура и текущие идентификаторы описаны в
`DEPLOY_HANDOFF.md`.
