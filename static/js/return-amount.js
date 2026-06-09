/*
 * Return-amount: в окне приёма возврата подсказывает сумму начисления.
 *
 * Когда оператор вводит количество к возврату, поле суммы авто-заполняется
 * «кол-во × дни × цена/сут» (значения берутся из data-атрибутов строки), пока
 * оператор не правил сумму руками. Как только сумму тронули — авто-подстановка
 * её больше не перезатирает (data-manual="1"). Итог в подвале считается вживую.
 *
 * Это UX-подсказка, не источник истины: если оставить поле пустым, сервер
 * посчитает точную сумму сам (billing.compute_return_amount_for_qty), а если
 * JS не отработает — оператор просто введёт сумму вручную.
 */
(function () {
    var SEP = ' ';

    function parseMoney(v) {
        if (v == null) return 0;
        var s = String(v).replace(/\s+/g, '').replace(/[^\d.,\-]/g, '').replace(',', '.');
        var n = parseFloat(s);
        return isNaN(n) ? 0 : n;
    }

    function groupInt(n) {
        return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, SEP);
    }

    function recalcTotal() {
        var totalEl = document.getElementById('return-total');
        if (!totalEl) return;
        var total = 0;
        document.querySelectorAll('input.return-amount').forEach(function (a) {
            total += parseMoney(a.value);
        });
        totalEl.textContent = groupInt(total);
    }

    function onInput(e) {
        var el = e.target;
        if (!el || !el.classList) return;
        if (el.classList.contains('return-qty')) {
            var item = el.dataset.item;
            var amount = document.querySelector(
                'input.return-amount[data-item="' + item + '"]'
            );
            if (amount && amount.dataset.manual !== '1') {
                var qty = parseMoney(el.value);
                var days = parseFloat(el.dataset.days || '0') || 0;
                var price = parseFloat(el.dataset.price || '0') || 0;
                var suggested = qty * days * price;
                amount.value = suggested > 0 ? groupInt(suggested) : '';
            }
            recalcTotal();
        } else if (el.classList.contains('return-amount')) {
            el.dataset.manual = '1';
            recalcTotal();
        }
    }

    document.body && document.body.addEventListener('input', onInput);
    document.body && document.body.addEventListener(
        'htmx:afterSettle', function () { recalcTotal(); }
    );
    document.addEventListener('DOMContentLoaded', function () { recalcTotal(); });
})();
