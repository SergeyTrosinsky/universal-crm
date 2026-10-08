// Общее поведение интерфейса: мобильное меню, подтверждения, закрытие уведомлений.
(function () {
  'use strict';

  document.addEventListener('click', function (e) {
    var toggle = e.target.closest('[data-toggle]');
    if (toggle) {
      var target = document.getElementById(toggle.getAttribute('data-toggle'));
      if (target) {
        var hidden = target.classList.toggle('hidden');
        toggle.setAttribute('aria-expanded', hidden ? 'false' : 'true');
      }
      return;
    }
    var dismiss = e.target.closest('[data-dismiss]');
    if (dismiss) {
      var flash = dismiss.closest('[data-flash]');
      if (flash) flash.remove();
    }
  });

  // <form data-confirm="Текст вопроса"> — подтверждение перед отправкой
  document.addEventListener('submit', function (e) {
    var message = e.target.getAttribute && e.target.getAttribute('data-confirm');
    if (message && !window.confirm(message)) e.preventDefault();
  });

  // <details data-dropdown> закрывается кликом снаружи и клавишей Esc
  document.addEventListener('click', function (e) {
    document.querySelectorAll('details[data-dropdown][open]').forEach(function (d) {
      if (!d.contains(e.target)) d.removeAttribute('open');
    });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    document.querySelectorAll('details[data-dropdown][open]').forEach(function (d) {
      d.removeAttribute('open');
    });
  });

  // Успешные уведомления исчезают сами; ошибки остаются, пока их не закроют
  window.setTimeout(function () {
    document.querySelectorAll('[data-flash][data-category="success"]').forEach(function (el) {
      el.remove();
    });
  }, 5000);
})();
