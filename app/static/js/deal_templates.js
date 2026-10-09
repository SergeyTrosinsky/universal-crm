(function () {
  'use strict';
  var select = document.getElementById('template_id');
  var items = document.querySelectorAll('[data-field-template]');
  var section = document.querySelector('[data-custom-section]');
  if (!select || !items.length) return;

  function update() {
    var chosen = select.value;
    var visible = 0;
    items.forEach(function (item) {
      var own = item.getAttribute('data-field-template');
      var show = own === '' || own === chosen;
      item.classList.toggle('hidden', !show);
      item.querySelectorAll('input, select, textarea').forEach(function (control) {
        control.disabled = !show;
      });
      if (show) visible += 1;
    });
    if (section) section.classList.toggle('hidden', visible === 0);
  }

  select.addEventListener('change', update);
  update();
})();
