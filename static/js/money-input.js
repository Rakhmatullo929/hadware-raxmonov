/*
 * Money-input: показывает «40 000» при наборе, отправляет «40000» серверу.
 *
 * Применяется к любому <input class="money-input">. Также реагирует на htmx
 * swap'ы — модалки и подгружаемые фрагменты автоматически перехватываются.
 *
 * Контракт с бэкендом: значение полей с этим классом обнуляется от пробелов
 * до Decimal-валидации (см. MoneyDecimalField в config/forms.py). JS — это
 * UX-улучшение, не источник истины: даже если он отвалится, ввод «40 000»
 * пройдёт через бэкендный strip.
 */
(function () {
    const SEP = ' '; // обычный пробел — как на скриншоте у пользователя

    function formatNumber(raw) {
        // Оставляем только цифры, точку/запятую и минус.
        let s = String(raw == null ? '' : raw).replace(/[^\d.,\-]/g, '');
        // Унифицируем разделитель дроби.
        s = s.replace(/,/g, '.');
        // Только одно «.» — лишние подрезаем (склеиваем хвост).
        const dotIdx = s.indexOf('.');
        if (dotIdx !== -1) {
            s = s.slice(0, dotIdx + 1) + s.slice(dotIdx + 1).replace(/\./g, '');
        }
        // Знак минус — только в начале.
        const neg = s.startsWith('-');
        s = s.replace(/-/g, '');
        const parts = s.split('.');
        const intPart = parts[0] || '';
        const fracPart = parts.length > 1 ? parts[1] : null;
        // Группируем по 3 справа.
        const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, SEP);
        return (neg ? '-' : '')
            + grouped
            + (fracPart !== null ? '.' + fracPart : '');
    }

    function attach(input) {
        if (input.dataset.moneyAttached === '1') return;
        input.dataset.moneyAttached = '1';

        // Стартовое форматирование (если форма пришла с уже введённым значением).
        if (input.value) input.value = formatNumber(input.value);

        input.addEventListener('input', function () {
            const before = input.value;
            const cursor = input.selectionStart || 0;
            // Сколько цифр стояло левее курсора — нужно вернуть курсор туда же
            // после переформатирования.
            const digitsBefore = (before.slice(0, cursor).match(/[\d.,-]/g) || []).length;
            const formatted = formatNumber(before);
            if (formatted === before) return;
            input.value = formatted;
            let seen = 0;
            let newCursor = formatted.length;
            for (let i = 0; i < formatted.length; i++) {
                if (/[\d.,-]/.test(formatted[i])) seen++;
                if (seen >= digitsBefore) { newCursor = i + 1; break; }
            }
            try {
                input.setSelectionRange(newCursor, newCursor);
            } catch (e) {
                // type="text" поддерживает selectionRange; на всякий случай ловим.
            }
        });
    }

    function attachAll(root) {
        const scope = root && root.querySelectorAll ? root : document;
        scope.querySelectorAll('input.money-input').forEach(attach);
    }

    // Снять пробелы перед отправкой формы — на случай, если на бэкенде
    // не подключён MoneyDecimalField (страховка).
    function stripBeforeSubmit(form) {
        if (!(form instanceof HTMLFormElement)) return;
        form.querySelectorAll('input.money-input').forEach(function (inp) {
            inp.value = (inp.value || '').replace(/\s+/g, '');
        });
    }

    document.addEventListener('DOMContentLoaded', function () { attachAll(); });
    document.body && document.body.addEventListener(
        'htmx:afterSettle', function (e) { attachAll(e.target); }
    );
    document.addEventListener('submit', function (e) {
        stripBeforeSubmit(e.target);
    }, true);
    // htmx тоже триггерит submit через POST из form — обработаем
    // htmx:configRequest, чтобы значение в payload было без пробелов.
    //
    // ВАЖНО: трогаем ТОЛЬКО поля money-input (по их name), а не любой
    // «похожий на число» параметр. Иначе пробелы вырезались бы и из
    // телефонов/причин/любых числовых строк (напр. поиск клиента по
    // «998 90 123» молча превращался бы в «99890123» и ничего не находил).
    document.body && document.body.addEventListener(
        'htmx:configRequest', function (e) {
            const p = e.detail && e.detail.parameters;
            const elt = e.detail && e.detail.elt;
            if (!p || !elt) return;
            const names = new Set();
            if (elt.matches && elt.matches('input.money-input') && elt.name) {
                names.add(elt.name);
            }
            if (elt.querySelectorAll) {
                elt.querySelectorAll('input.money-input').forEach(function (inp) {
                    if (inp.name) names.add(inp.name);
                });
            }
            names.forEach(function (name) {
                const v = p[name];
                if (typeof v === 'string') p[name] = v.replace(/\s+/g, '');
            });
        }
    );
})();
