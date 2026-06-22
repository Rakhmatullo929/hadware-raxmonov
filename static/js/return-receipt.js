/*
 * Авто-открытие чека возврата.
 *
 * После оформления возврата сервер шлёт HTMX-событие `openReturnReceipt`
 * с {url} чека (заголовок HX-Trigger). Открываем чек в новой вкладке.
 * Если попап заблокирован (window.open вернул null — обработчик ответа htmx
 * не всегда считается «прямым» жестом пользователя), показываем заметный
 * fallback-баннер со ссылкой.
 */
(function () {
    function showFallback(url) {
        var old = document.getElementById('return-receipt-fallback');
        if (old) old.remove();

        var box = document.createElement('div');
        box.id = 'return-receipt-fallback';
        box.style.cssText =
            'position:fixed;top:1rem;left:50%;transform:translateX(-50%);' +
            'z-index:1090;background:#0d6efd;color:#fff;padding:.6rem 1rem;' +
            'border-radius:.5rem;box-shadow:0 .25rem .75rem rgba(0,0,0,.3);' +
            'font-size:.95rem;';

        var a = document.createElement('a');
        a.href = url;
        a.target = '_blank';
        a.rel = 'noopener';
        a.style.cssText = 'color:#fff;font-weight:600;text-decoration:underline;';
        a.textContent = '🧾 Открыть чек возврата';

        box.appendChild(a);
        document.body.appendChild(box);

        setTimeout(function () {
            var el = document.getElementById('return-receipt-fallback');
            if (el) el.remove();
        }, 15000);
    }

    document.body && document.body.addEventListener(
        'openReturnReceipt', function (e) {
            var url = (e.detail && e.detail.url) || '';
            if (!url) return;
            var win = window.open(url, '_blank');
            if (!win) showFallback(url);
        }
    );
})();
