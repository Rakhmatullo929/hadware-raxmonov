# Дизайн: отчёт «Возвраты товара»

Дата: 2026-06-09
Статус: утверждён (брейншторм)

## Цель

Дать владельцу/бухгалтеру отчёт по **приёмке возвращённого товара** за период:
сколько позиций принято и **сколько аренды начислено** при возврате. Нужен
быстрый ответ на вопрос «сколько было возвратов за сегодня / за период».

Важно (смысл цифр): отчёт показывает **начисленную аренду** при приёмке
(`Movement` вида `RETURN`, поле `amount`), а не деньги в кассе и не возврат
залога клиенту. Платежи (наличные/карта, в т.ч. возврат залога `REFUND`) — в
отдельном отчёте «Способы оплаты». Под заголовком — поясняющая подпись об этом.

## Принятые решения (из брейншторма)

1. **Состав:** сводка (Σ начислено · позиций, шт · число возвратов) + столбчатый
   график Σ по дням (стиль «Выручки») + детальный список построчно.
2. **Источник суммы — существующий `billing.return_charge_map(rental)`.** Берёт
   сохранённый `Movement.amount`, иначе авто-расчёт `unit_days × price`. Дни
   возврата привязаны к дате самого возврата (`_billable_days(issue_dt, m.date)`),
   поэтому отчёт за прошлые даты исторически корректен. Логику FIFO не дублируем.
3. **Период** — общий `_parse_period` (дефолт = текущий месяц), кнопка «Сегодня»
   (= сброс фильтра, как в «Движении склада»).
4. **Экспорт CSV** детального списка — как у «Должников» (UTF-8 BOM, `;`).
5. **Только админ** — `@role_required('admin')`, как все отчёты.

## Архитектура

### View (config/views.py) — рядом с прочими отчётами

Общий помощник (как `_debtors_rows`), чтобы страница и CSV считали одинаково:

```python
def _returns_rows(date_from, date_to):
    """(rows, daily, totals) по движениям возврата за период.
      rows  — [{date, customer, rental_id, product, qty, amount}], по дате;
      daily — {labels: [...], values: [...]} Σ начислено по дням (с нулями);
      totals— {amount: Σ, qty: Σ шт, count: N возвратов}.
    """
```

Реализация:

- Запрос:
  `Movement.objects.filter(kind=RETURN, date__date__gte=date_from, date__date__lte=date_to)`
  `.select_related('rental_item__product', 'rental_item__rental__customer').order_by('date', 'id')`.
- Сумма по движению: собрать distinct аренды из выборки, вызвать
  `billing.return_charge_map(rental)` один раз на аренду, слить в общий
  `charge_by_mid`; `amount = charge_by_mid.get(m.id, 0)`.
- `daily` — проход по дням `date_from..date_to` с заполнением нулей (как в
  `report_revenue._series`).
- `totals` — суммы по выборке.

Вьюхи:

- `report_returns(request)` — `_parse_period` → `_returns_rows` → рендер
  `config/reports/returns.html`.
- `report_returns_csv(request)` — тот же помощник → CSV, колонки:
  `Дата`, `Клиент`, `Телефон`, `Аренда №`, `Товар`, `Кол-во`, `Начислено`.
  Имя файла `returns-<from>_<to>.csv`.

### Роуты (config/urls.py)

```python
path('reports/returns/',  views.report_returns,     name='report_returns'),
path('reports/returns.csv', views.report_returns_csv, name='report_returns_csv'),
```

### Шаблон (config/templates/config/reports/returns.html)

- Шапка + «← К списку отчётов».
- Форма `date_from`/`date_to` + «Применить» + «Сегодня» (reset) + «Скачать CSV»
  (ссылка с текущими параметрами периода).
- Поясняющая подпись о смысле «начислено».
- 3 карточки итогов.
- `<canvas>` + Chart.js (bar) — Σ начислено по дням (json_script, как в revenue).
- Таблица: Дата · Клиент · Аренда № · Товар · Кол-во · Начислено; строка «Итого».

### Индекс отчётов (config/templates/config/reports/index.html)

Карточка «Возвраты» со ссылкой `report_returns` и кратким описанием.

### i18n

Новые строки через `{% trans %}`/`_()`; перевод на uz в `locale/uz`,
ru — в `locale/ru`; `makemessages` + `compilemessages`.

## Тестирование (tests/test_returns_report.py, pytest-django)

По образцу `tests/test_payment_methods_report.py`:

- рендерится, ключевые лейблы присутствуют;
- Σ начислено = сумма `amount` возвратов в периоде (сохранённый `amount`);
- возврат с `amount=None` учитывается по авто-расчёту;
- возврат вне диапазона дат не попадает;
- число возвратов и Σ позиций (шт) верны;
- CSV отдаёт 200, `text/csv`, содержит строки;
- не-админ → 302/403.

## Вне рамок (YAGNI)

- Сравнение с прошлым периодом.
- Разбивка по способу оплаты (это не про возврат товара).
- Фильтры по клиенту/товару, пагинация.
- Возврат залога клиенту (`Payment.REFUND`) — уже в «Способах оплаты».
