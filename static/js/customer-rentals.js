// Аккордеон истории аренд в карточке клиента.
// Раскрыта максимум одна аренда за раз — тогда фиксированные id карточки
// (#rental-summary, #modal-slot, ...) уникальны и модалко/OOB-механика
// редактирования работает как на странице аренды. Очистка #rbody убирает
// дубли id и любую открытую модалку (модалки — инлайн, без Bootstrap-подложки).
(function () {
    'use strict';

    function init() {
        var root = document.getElementById('customer-rentals');
        if (!root || typeof htmx === 'undefined') return;

        function bodyFor(id) { return document.getElementById('rbody-' + id); }
        function headerFor(id) { return document.getElementById('crow-' + id); }

        function collapse(id) {
            var body = bodyFor(id);
            var header = headerFor(id);
            if (body) body.innerHTML = '';
            if (header) header.setAttribute('aria-expanded', 'false');
        }

        function isOpen(id) {
            var body = bodyFor(id);
            return !!body && body.innerHTML.trim() !== '';
        }

        function expand(id) {
            // Закрыть все прочие открытые строки (single-open).
            root.querySelectorAll('.rental-acc-body').forEach(function (b) {
                var otherId = b.id.replace('rbody-', '');
                if (otherId !== id && b.innerHTML.trim() !== '') collapse(otherId);
            });
            var header = headerFor(id);
            var url = header.getAttribute('data-card-url');
            htmx.ajax('GET', url, {
                target: '#rbody-' + id, swap: 'innerHTML'
            }).then(function () {
                header.setAttribute('aria-expanded', 'true');
            });
        }

        function toggleFromHeader(header) {
            var id = header.getAttribute('data-rental-id');
            if (isOpen(id)) collapse(id); else expand(id);
        }

        root.addEventListener('click', function (evt) {
            // Клики по ссылкам/кнопкам и внутри уже открытой карточки — мимо.
            if (evt.target.closest('a, button, .rental-acc-body')) return;
            var header = evt.target.closest('.rental-acc-header');
            if (header && root.contains(header)) toggleFromHeader(header);
        });

        root.addEventListener('keydown', function (evt) {
            if (evt.key !== 'Enter' && evt.key !== ' ') return;
            var header = evt.target.closest('.rental-acc-header');
            if (!header || !root.contains(header)) return;
            evt.preventDefault();
            toggleFromHeader(header);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
