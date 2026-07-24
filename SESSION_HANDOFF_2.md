# Session handoff #2 — продолжение от 2026-06-02 (вечер)

> Архивный handoff по инциденту BANDI. Актуальное состояние production и
> процедура релиза находятся в `DEPLOY_HANDOFF.md`. Не использовать этот файл
> как источник credentials или текущего статуса MOIL.

Если сессия закончится — открой этот файл в новой и продолжи отсюда.
Первый handoff — `DEPLOY_HANDOFF.md` (он описывает изначальный деплой). Этот — про правки логики после первого smoke-теста.

---

## Что произошло после первого деплоя

Заказчица (Карина) начала тестировать на реальной поставке **BANDI 20260501**. Полез вал багов, мы их фиксили в моменте.

Файлы поставки на сервере:
- `/opt/tg_uploads/bandi/20260501/bandi-inv-20260501-1.xlsx` (инвойс ALL — оба DG и NDG в одном файле)
- `/opt/tg_uploads/bandi/20260501/bandi-pac-20260501-1.xlsx` (общий пакинг)
- `/opt/tg_uploads/bandi/20260501/manifest.json`

Локальные эталоны и присланные файлы — `D:\w\pdf\проблема_bandi\` и `D:\w\pdf\прод\`.

## Поменяли таблицы Google Sheets на новые

Заказчица создала свежие пустые таблицы. Старые ID были везде в workflow — заменили все три на новые **через UI n8n** (заказчица сама):

| Бренд | Новый Spreadsheet ID |
| --- | --- |
| MOIL / BANDI / MOROCCANOIL (распределение между ID не уточнялось — спросить заказчицу!) | `1qMNUVwizL6okhjiTI6ViEbdVHAIc-prkqnAcYQkwEmI` |
| | `1Av1S2wFoiLrIeeaBO-gFGgsBtzuwMgL1ziVd2lS6c3k` |
| | `1nk0J3xog_TzVraMyAwpE494Q-2XQ1yw6-amtsrsoNaU` |

Проверил `sqlite3 /opt/n8n/.n8n/database.sqlite` — старых ID (`1yb8n-…`, `1y4t9W…`, `1Waz6Jk…`) в workflow больше нет. Только эти три.

**TODO в новой сессии:** уточнить у заказчицы, какой ID к какому бренду привязан, и обновить раздел в `DEPLOY_HANDOFF.md`.

## Парсер `parse_bandi_bundle.py` — изменения

Правил `/data/moil/parse_bandi_bundle.py` напрямую через ssh + sed/python. Бэкапы рядом как `.bak.<timestamp>`.

1. **`dgndg` сделан опциональным в пакинге** (строка 400). У некоторых поставщиков (этот WMI-RU20260501) колонки DG/NDG в пакинге **нет**. Раньше парсер падал с warning «Не найдена строка заголовков». Теперь не падает.
2. **Безопасное чтение `dgndg` в строке** (строка 429) — через `header_map.get('dgndg')`, если индекса нет → None.
3. **Backfill `__effectiveCustomsScope` для пакинговых строк** (вставлено перед формированием `dg_packing_rows` около строки 512). Если в пакинге scope = UNKNOWN, парсер строит карту `vendor_code → DG/NDG` из распарсенных инвойсных строк и проставляет на пакинг. Без этого DG/NDG листы получались пустыми (т.к. сплит идёт по `__effectiveCustomsScope`).
4. **Алиасы для grossWeight** (строка 407) — теперь ищет: `grossweight` → `individualgrossweight` → `grossweightkg` → `individualgrossweightkg`. У этого поставщика заголовок `INDIVIDUAL\nGROSS WEIGHT` → `individualgrossweight`. Раньше gross был None.

Все правки прошли syntax check (`/opt/moil-venv/bin/python -c "import ast; ast.parse(...)"` — ok).

## Build-нода n8n `Build Bandi Customs and CZ Rows` — изменения

Правил прямо в SQLite n8n (`/opt/n8n/.n8n/database.sqlite`, таблица `workflow_entity`, workflow id `oAsH9xGYN9uxtLPF`). Бэкапы DB рядом: `.bak.<timestamp>`. После каждой правки `systemctl restart n8n`.

Патчи (все применены, проверены `node --check`, n8n перезапущен в 18:18):

1. **ТНВЭД только из мастера** (строки 298 и 351). Раньше было: `invoice.hsCode || master.customsCode`. Теперь: только `master.customsCode || null`. Корейский HSCODE из инвойса/пакинга больше не используется. Это правило заказчицы — «только мастер, иначе пусто».
2. **DG/NDG в ЧЗ — fallback цепочка** (строка 348/346):
   ```js
   clean(packingRow.dgFlag) || master?.dgFlag || clean(packingRow.__effectiveCustomsScope) || (opts.scopeMap && opts.scopeMap[clean(packingRow.vendorCode)]) || null
   ```
3. **`scopeMap` строится в `buildCzRows`** перед циклом по пакингу: проходит по `dgInvoiceRows`/`ndgInvoiceRows`, строит `vendorCode → 'DG'/'NDG'`. Передаётся в `buildCzRowFromPacking` через `opts.scopeMap` во всех 3 точках вызова (regular row, kit row, component row).
4. **Новая колонка `ТНВЭД` в ЧЗ-листе** (после `Наименование РУС`).
5. **Новая колонка `Цена за шт.` в ЧЗ-листе** (в самом конце row-объекта). Сейчас всегда `null` — TODO дальше.
6. **Новые колонки `Дата изготовления` и `Годен до` в CUSTOMS-листе (DG/NDG)** — IIFE из первой пакинговой LOT через `parseLotToDate` + `addMonthsMinusOneDay(d, master.expiryMonths)`.

## Шаблоны в Google Sheets BANDI

Заказчица сама правила `TEMPLATE_CZ` и `TEMPLATE_CUSTOMS`. Сделала **правильно** в `bandi (2).xlsx` (последняя версия):

**TEMPLATE_CZ (23 колонки):** `# | GTIN | Артикул | DG/NDG | Наименование АНГЛ | Наименование РУС | ТНВЭД | LOT | Срок годности | Дата изгот | Годен до | Кол-во | Коробка № | № паллета | Data Matrix | Размер Этикетки | Примечание по этикетке | Концентрация спирта, % ЭТИЛОВЫЙ СПИРТ (ЭТАНОЛ) | Вложения в наборы | Цена за шт. | __row_warning | __warning_net_gt_gross | __warning_reason`

**TEMPLATE_CUSTOMS (36 колонок):** есть дубль `Цена за шт.` (col 7 и col 19). Один из них надо убрать. Также есть лишний `Описание упаковки` (col 18) — это правильно. Порядок не идеальный, но работает потому что n8n auto-map по ключам.

## ⚠️ Главное на момент конца сессии

Заказчица прислала результат прогона `bandi (2).xlsx` (`C:\Users\egort\Downloads\bandi (2).xlsx`) и пожаловалась что:
- DG/NDG в ЧЗ всё ещё пустой
- ТНВЭД в DG/NDG = `3304301000` (корейский), а должен быть `3304300000` из мастера

**Я проверил БД n8n: последний execution 13 был запущен в 16:47, а мои патчи закончились в 18:18.** То есть `bandi (2).xlsx` — это результат **ДО** последних патчей. Заказчица просто скачала старый файл.

**Что делать в новой сессии:**
1. Попросить заказчицу:
   - В Google Sheets BANDI **удалить листы** `ЧЗ 20260501`, `DG 20260501`, `NDG 20260501` (чтобы пересоздались по новым шаблонам).
   - Прогнать поставку 20260501 заново через бот (`/start → bandi → 20260501 → /done`) или re-execute последний execution в n8n UI.
   - Прислать новый xlsx.
2. Проверить новый файл:
   - DG/NDG в ЧЗ должно быть заполнено (`'DG'`/`'NDG'`)
   - ТНВЭД в DG/NDG листах = `3304300000` (или то что в мастер-каталоге)
   - В ЧЗ есть колонки ТНВЭД, Цена за шт.
   - В DG/NDG есть колонки Дата изготовления, Годен до
3. Если DG/NDG в ЧЗ всё ещё пустой — посмотреть промежуточные данные в build-ноде через UI n8n (запустить execution с pinned data, посмотреть JSON на выходе `Build Bandi Customs and CZ Rows`).

## Открытые задачи

1. **Цена за шт. в ЧЗ** — сейчас всегда null. Заказчица просила заполнять. Нужно через scopeMap-паттерн прокинуть `vendor_code → unitPrice` из инвойса в `buildCzRowFromPacking`. Аналогично тому как сделан scopeMap для DG/NDG.
2. **Дубль `Цена за шт.` в TEMPLATE_CUSTOMS** — заказчица оставила col 7 и col 19. Один надо убрать (и предупредить её). В build-ноде колонка одна (после Volume, перед Amount $).
3. **Распределение Spreadsheet ID между брендами** — уточнить у заказчицы и записать в `DEPLOY_HANDOFF.md`.
4. **Колонка DG/NDG в _master_catalog** — у заказчицы пустой 3-й столбец без заголовка между `Артикул РУ` и `ТНВЭД`. Build-нода пытается прочитать `get('DG/NDG', 'DG/ NDG', 'DGNDG')` — ничего не находит. Если заказчица заполнит этот столбец и назовёт `DG/NDG` — `master.dgFlag` будет не пустым, и backfill через scopeMap будет страховочным.
5. **Окончательный smoke test** на 20260501 — после которого можно закрывать таску #5 в TaskList.
6. **Smoke test для MOIL и MOROCCANOIL** — пока не делали, ждём пока заказчица сама принесёт файлы.
7. **MOROCCANOIL + общий пакинг с несколькими инвойсами** (CLAUDE.md раздел 4.2) — отдельная нерешённая задача.

## Полезные команды для восстановления контекста

```bash
# Состояние n8n + executions
ssh root@103.112.69.124 "systemctl status n8n --no-pager"
ssh root@103.112.69.124 "sqlite3 /opt/n8n/.n8n/database.sqlite 'SELECT id, status, startedAt FROM execution_entity ORDER BY startedAt DESC LIMIT 10;'"

# Достать build-ноду BANDI из БД
ssh root@103.112.69.124 "sqlite3 /opt/n8n/.n8n/database.sqlite \"SELECT nodes FROM workflow_entity WHERE id='oAsH9xGYN9uxtLPF';\" > /tmp/wf.json"
# python3 + json.load(open('/tmp/wf.json')) и фильтр по name == 'Build Bandi Customs and CZ Rows'

# Прогнать парсер вручную
ssh root@103.112.69.124 "/opt/moil-venv/bin/python /data/moil/parse_bandi_bundle.py --shipment-key 20260501 --input-dir /opt/tg_uploads/bandi/20260501 --kits-file '/data/bandi/Наборы Банди для Ч З.xlsx'" | python -m json.tool | head -200
```

## Бэкапы (можно откатиться в случае чего)

- Парсер: `/data/moil/parse_bandi_bundle.py.bak.<timestamp>` на сервере
- БД n8n: `/opt/n8n/.n8n/database.sqlite.bak.<timestamp>` на сервере (есть три бэкапа: 17:29, 18:07, 18:18)
