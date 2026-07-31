// Живой расчёт для формы создания аренды: период в днях, суммы за позиции и
// «к оплате», а также авто-подстановка срока возврата по «Норме (макс)» товара.
//
// Работает и на полной странице «Новая аренда», и в модалке создания аренды на
// карточке клиента (форма вставляется htmx-ом позже). Поэтому:
//   * элементы формы ищем ЛЕНИВО в момент расчёта (не кэшируем при загрузке);
//   * если формы на странице нет — тихо выходим;
//   * «тронутость» срока возврата храним на самом input через data-атрибуты,
//     чтобы состояние не протекало между разными экземплярами формы.
(function () {
    'use strict';

    var fmt = new Intl.NumberFormat('ru-RU', {
        minimumFractionDigits: 2, maximumFractionDigits: 2,
    });

    // В поле цены лежит отформатированное значение вида «40 000.50»
    // (money-input.js), поэтому перед разбором снимаем пробелы и приводим
    // запятую к точке — той же нормализацией, что делает бэкенд.
    function parseMoney(raw) {
        var s = String(raw == null ? '' : raw).replace(/\s/g, '').replace(',', '.');
        var n = parseFloat(s);
        return isNaN(n) ? 0 : n;
    }

    function readDt(name) {
        var el = document.querySelector('[name="' + name + '"]');
        if (!el || !el.value) return null;
        var d = new Date(el.value);
        return isNaN(d) ? null : d;
    }

    function computeDays() {
        var start = readDt('created_at') || new Date();
        var end = readDt('due_date');
        if (!end) return 0;
        var diffMs = end - start;
        if (diffMs <= 0) return 0;
        // Округление вверх до полных суток — частичный день оплачивается как день.
        return Math.max(1, Math.ceil(diffMs / 86400000));
    }

    function recalc() {
        var totalDaysEl = document.getElementById('total-days');
        if (!totalDaysEl) return;               // формы создания нет на странице
        var itemsTotalEl = document.getElementById('items-total');
        var grandTotalEl = document.getElementById('grand-total');

        var days = computeDays();
        totalDaysEl.textContent = days;

        var itemsSum = 0;     // Σ цена * qty (за сутки)
        var perPeriodSum = 0; // Σ * days
        document.querySelectorAll('.item-row').forEach(function (row) {
            // Цена справочника хранится в data-price на скрытом
            // input[name=item_product] (продуктовый пикер). Запасной путь —
            // старый select.
            var pidInp = row.querySelector('input[name="item_product"]');
            var sel = row.querySelector('select.item-product');
            var qtyInp = row.querySelector('input.item-qty');
            var subEl = row.querySelector('.row-subtotal');
            if (!qtyInp) return;
            // Приоритет — цена, введённая админом в строке. Пустое поле
            // (или его отсутствие у оператора) означает «цена из справочника».
            var priceInp = row.querySelector('input.item-price');
            var price = 0;
            if (priceInp && priceInp.value.trim() !== '') {
                price = parseMoney(priceInp.value);
            } else if (pidInp && pidInp.dataset.price) {
                price = parseFloat(pidInp.dataset.price) || 0;
            } else if (sel) {
                var opt = sel.options[sel.selectedIndex];
                price = parseFloat((opt && opt.dataset.price) || '0') || 0;
            }
            var qty = parseInt(qtyInp.value || '0', 10) || 0;
            var daily = price * qty;
            var subtotal = daily * Math.max(days, 1);
            itemsSum += daily;
            perPeriodSum += subtotal;
            if (subEl) subEl.textContent = fmt.format(subtotal);
        });
        if (itemsTotalEl) itemsTotalEl.textContent = fmt.format(itemsSum);
        if (grandTotalEl) grandTotalEl.textContent = fmt.format(perPeriodSum);
    }

    function fmtLocal(d) {
        // datetime-local ждёт 'YYYY-MM-DDTHH:MM' в ЛОКАЛЬНОМ времени.
        var p = function (n) { return String(n).padStart(2, '0'); };
        return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) +
               'T' + p(d.getHours()) + ':' + p(d.getMinutes());
    }

    function syncDueDate() {
        var dueInput = document.querySelector('[name="due_date"]');
        if (!dueInput) return;
        // Значение, которое поставили НЕ мы (серверный ре-рендер или ручной
        // ввод), не трогаем. Своё авто-значение помечаем data-autofilled.
        if (dueInput.value && dueInput.dataset.autofilled !== '1') return;
        if (dueInput.dataset.touched === '1') return;

        // Собрать сроки со всех выбранных товаров (целые >= 1) и взять минимум.
        var days = [];
        document.querySelectorAll('input[name="item_product"]').forEach(function (inp) {
            var n = parseInt(inp.dataset.returnDays || '', 10);
            if (Number.isInteger(n) && n >= 1) days.push(n);
        });
        if (!days.length) return;              // нет норм — поле не трогаем
        var n = Math.min.apply(null, days);
        var base = readDt('created_at') || new Date();
        var due = new Date(base.getTime() + n * 86400000);
        dueInput.value = fmtLocal(due);
        dueInput.dataset.autofilled = '1';
        recalc();
    }

    // Подставить цену товара в поле «Цена/сут.», пока админ не правил его сам.
    // «Тронутость» храним на самом input (data-touched), чтобы состояние не
    // протекало между экземплярами формы — так же, как для срока возврата.
    function syncPrices() {
        document.querySelectorAll('.item-row').forEach(function (row) {
            var priceInp = row.querySelector('input.item-price');
            var pidInp = row.querySelector('input[name="item_product"]');
            if (!priceInp || !pidInp) return;          // оператор: поля нет
            if (priceInp.dataset.touched === '1') return;
            if (!pidInp.value) return;                 // товар не выбран
            var price = pidInp.dataset.price || '';
            if (!price) return;
            if (parseMoney(priceInp.value) === parseFloat(price)) return;
            priceInp.value = price;
            // money-input.js форматирует значение по событию input; заодно
            // отрабатывает наш пересчёт подытогов.
            priceInp.dispatchEvent(new Event('input', {bubbles: true}));
        });
    }

    // Ручной ввод/правка срока замораживает авто-подстановку (снимаем авто-флаг).
    function markDueTouched(el) {
        if (el && el.name === 'due_date') {
            el.dataset.touched = '1';
            delete el.dataset.autofilled;
        }
    }

    // Ручная правка цены замораживает автоподстановку для этой строки.
    // isTrusted отсекает наше же синтетическое событие из syncPrices().
    function markPriceTouched(e) {
        var el = e.target;
        if (!el || !el.classList || !el.classList.contains('item-price')) return;
        if (!e.isTrusted) return;
        el.dataset.touched = '1';
    }

    document.addEventListener('input', function (e) {
        markDueTouched(e.target);
        markPriceTouched(e);
        if (e.target && e.target.name === 'created_at') syncDueDate();
        recalc();
    });
    document.addEventListener('change', function (e) {
        markDueTouched(e.target);
        markPriceTouched(e);
        recalc();
    });

    // htmx подменил строку/пикер/вставил модалку — пересчитать, подстроить
    // срок возврата и подставить цены выбранных товаров.
    document.body.addEventListener('htmx:afterSettle', function () {
        syncDueDate();
        syncPrices();
        recalc();
    });

    document.addEventListener('DOMContentLoaded', function () {
        syncDueDate();
        syncPrices();
        recalc();
    });
})();
