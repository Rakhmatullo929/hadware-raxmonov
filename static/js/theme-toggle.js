/* Переключатель темы (светлая / тёмная).
 *
 * Тема хранится в атрибуте data-bs-theme на <html> (см. инлайн-скрипт в <head>,
 * который выставляет её ДО отрисовки, чтобы не было мигания — FOUC).
 * Здесь — только реакция на клики и синхронизация состояния контролов.
 *
 * Поддерживаются два вида контролов:
 *   [data-theme-value="light|dark"] — сегментированные кнопки (сайдбар)
 *   [data-theme-toggle]             — кнопка-переключатель (плавающая на входе)
 */
(function () {
    'use strict';

    var KEY = 'rt-theme';
    var root = document.documentElement;

    function stored() {
        try {
            var t = localStorage.getItem(KEY);
            return (t === 'light' || t === 'dark') ? t : null;
        } catch (e) {
            return null;
        }
    }

    function currentTheme() {
        return stored() || root.getAttribute('data-bs-theme') || 'dark';
    }

    function apply(theme) {
        root.setAttribute('data-bs-theme', theme);
        try { localStorage.setItem(KEY, theme); } catch (e) { /* приватный режим */ }
        sync(theme);
    }

    /* Синхронизирует визуальное состояние всех контролов с текущей темой. */
    function sync(theme) {
        document.querySelectorAll('[data-theme-value]').forEach(function (btn) {
            var on = btn.getAttribute('data-theme-value') === theme;
            btn.classList.toggle('theme-btn-active', on);
            btn.setAttribute('aria-pressed', on ? 'true' : 'false');
        });

        document.querySelectorAll('[data-theme-toggle]').forEach(function (btn) {
            // Иконка показывает тему, НА КОТОРУЮ переключит (в тёмной — солнце).
            var toLight = theme === 'dark';
            var icon = btn.querySelector('i');
            if (icon) {
                icon.className = toLight ? 'bi bi-sun-fill' : 'bi bi-moon-stars-fill';
            }
            var label = btn.getAttribute(toLight ? 'data-label-light' : 'data-label-dark');
            if (label) {
                btn.setAttribute('aria-label', label);
                btn.setAttribute('title', label);
            }
        });
    }

    function init() {
        var theme = currentTheme();
        root.setAttribute('data-bs-theme', theme);
        sync(theme);

        document.querySelectorAll('[data-theme-value]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                apply(btn.getAttribute('data-theme-value'));
            });
        });

        document.querySelectorAll('[data-theme-toggle]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                apply(root.getAttribute('data-bs-theme') === 'dark' ? 'light' : 'dark');
            });
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
