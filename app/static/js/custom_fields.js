// Форма поля: блок «Варианты» нужен только для типов select / multiselect.
(function () {
  'use strict';
  var typeSelect = document.getElementById('field_type');
  var blocks = document.querySelectorAll('[data-options-block]');
  if (!typeSelect || !blocks.length) return;

  function update() {
    var needs = typeSelect.value === 'select' || typeSelect.value === 'multiselect';
    blocks.forEach(function (block) {
      block.classList.toggle('hidden', !needs);
    });
  }
  typeSelect.addEventListener('change', update);
  update();
})();
