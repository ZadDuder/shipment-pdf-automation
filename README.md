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
- `scripts/prepare_moroccanoil_color_catalog.py` — детерминированная подготовка
  обновления color SKU по Excel поставщика без записи в Google Sheets.
- `scripts/apply_google_sheet_values.py` — защищённое применение проверенного
  снимка: stale-check, резервная копия листа, запись, полная сверка и rollback.
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
маркируется, batch XLSX. Invoice сначала читается по табличному слою; fallback
по текстовому слою включается только для PDF, в которых товарная таблица не
распознана. В частности, fallback восстанавливает перенесённый SKU
`M408BVPW` + `7L750` как `M408BVPW7L750`. Количество batch автоматически
определяется как коробки или штуки через сопоставление SKU+паллета с packing.

Пути из manifest сохраняют внутренние пробелы в именах файлов, но после
разрешения обязаны оставаться внутри каталога комплекта. DGD не является ни
invoice, ни packing и не загружается в эти роли. Для поставки
`ILSO000008323` replacement invoice и packing с номером `ILSO000005313`
загружаются одним комплектом под номером `ILSO000008323`, как указано в
сопроводительном guide. Неполные комплекты не следует объединять с полными.

Старый формат MOROCCANOIL продолжает поддерживаться. Если invoice содержит
наборы, а packing — их компоненты (или документы расходятся иным образом),
система не выдумывает отсутствующие соответствия и сохраняет диагностируемое
расхождение для ручной проверки. В архивном `8250699` это также оставляет
разницу в одну копейку между invoice-total и суммой округлённых ЧЗ-строк:
автоматически назначать остаток конкретному компоненту без правила от
поставщика нельзя.

### Артикулы MOROCCANOIL Color

Переход поставщика со старых FNO SKU на новые не должен ломать ранее
присланные документы. В `_master_catalog` одна карточка товара доступна по
всем известным идентификаторам:

- `SKU Code - 2` — текущий SKU поставщика;
- `SKU Code - 1` и `Old SKU FNO` — старый SKU;
- `Legacy SKU Code - 2` — значение `SKU Code - 2`, использовавшееся до
  миграции.

Build-нода индексирует все эти колонки как алиасы одной карточки. Новые
позиции из прайс-листа добавляются только с полями, которые прямо указаны
поставщиком: SKU, российский артикул, GTIN/barcode и английское описание.
ТН ВЭД, перевод и описание упаковки нельзя угадывать; до их заполнения
система явно помечает такую строку для ручной проверки.

Обновление справочника выполняется в два этапа. Сначала формируется локальный
candidate и отчёт:

```bash
.venv/bin/python scripts/prepare_moroccanoil_color_catalog.py \
  /path/to/Color-FNO.xlsx /tmp/master-before.json \
  --output /tmp/master-candidate.json \
  --report /tmp/master-report.json
```

Затем `scripts/apply_google_sheet_values.py` запускается без `--apply` для
preflight. Запись разрешается только после ревью с флагом `--apply` и
уникальным `--backup-title`. Скрипт прекращает работу, если production-лист
изменился после исходного снимка.

Сквозная проверка пяти эталонных комплектов выполняется Node-скриптом:

```bash
node scripts/verify_moroccanoil_build.js \
  workflows/build_moroccanoil.js \
  /tmp/ILSO000003204-bundle.json \
  /tmp/ILSO000000570-bundle.json \
  /tmp/ILSO000000580-bundle.json \
  /tmp/ILSO000004437-bundle.json \
  /tmp/ILSO000008323-bundle.json
```

## Production

Production развёрнут на VPS и состоит из двух systemd-сервисов: `n8n` и
`tg-upload-bot`. Парсеры находятся в `/data/moil`, загрузки — в
`/opt/tg_uploads`. Перед изменениями обязательны резервные копии файла парсера
и SQLite-базы n8n. Секреты хранятся только на сервере и не должны попадать в
репозиторий.

Пошаговая процедура и текущие идентификаторы описаны в
`DEPLOY_HANDOFF.md`.
