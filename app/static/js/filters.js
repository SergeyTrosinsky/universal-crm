// Фильтры списков: пустые поля не попадают в адрес страницы.
(function () {
  'use strict';
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form.matches || !form.matches('form[data-filter-form]')) return;
    Array.prototype.forEach.call(form.elements, function (el) {
      if (el.name && !el.disabled && el.type !== 'submit' && el.type !== 'button' && el.value === '') {
        el.disabled = true;
      }
    });
  });
  // Возврат по кнопке «назад» не должен оставлять поля отключёнными
  window.addEventListener('pageshow', function () {
    document.querySelectorAll('form[data-filter-form] [disabled]').forEach(function (el) {
      el.disabled = false;
    });
  });
})();
