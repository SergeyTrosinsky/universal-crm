// Выбор связанной записи с живым поиском (клиент, сделка).
// <div data-client-picker data-search-url="/clients/search"> … [data-picker-input] [data-picker-value] [data-picker-list]
(function () {
  'use strict';

  function init(root) {
    var input = root.querySelector('[data-picker-input]');
    var hidden = root.querySelector('[data-picker-value]');
    var list = root.querySelector('[data-picker-list]');
    var url = root.getAttribute('data-search-url') || '/clients/search';
    if (!input || !hidden || !list) return;
    var timer = null;
    var items = [];
    var active = -1;
    var seq = 0;

    function close() {
      list.classList.add('hidden');
      list.innerHTML = '';
      items = [];
      active = -1;
      input.setAttribute('aria-expanded', 'false');
    }

    function highlight() {
      Array.prototype.forEach.call(list.children, function (li, i) {
        li.classList.toggle('bg-indigo-50', i === active);
      });
    }

    function choose(item) {
      hidden.value = item.id;
      input.value = item.name;
      close();
    }

    function render(data) {
      list.innerHTML = '';
      items = data;
      active = -1;
      if (!data.length) {
        var empty = document.createElement('li');
        empty.className = 'px-3 py-2 text-slate-500';
        empty.textContent = 'Ничего не найдено';
        list.appendChild(empty);
      }
      data.forEach(function (item) {
        var li = document.createElement('li');
        li.setAttribute('role', 'option');
        li.className = 'cursor-pointer px-3 py-2 hover:bg-indigo-50';
        var title = document.createElement('div');
        title.className = 'font-medium text-slate-900';
        title.textContent = item.name;
        li.appendChild(title);
        var sub = item.sub || [item.phone, item.email].filter(Boolean).join(' · ');
        if (sub) {
          var s = document.createElement('div');
          s.className = 'text-xs text-slate-500';
          s.textContent = sub;
          li.appendChild(s);
        }
        li.addEventListener('mousedown', function (ev) {
          ev.preventDefault();
          choose(item);
        });
        list.appendChild(li);
      });
      list.classList.remove('hidden');
      input.setAttribute('aria-expanded', 'true');
    }

    function search() {
      var my = ++seq;
      fetch(url + '?q=' + encodeURIComponent(input.value.trim()), {
        headers: { Accept: 'application/json' },
        credentials: 'same-origin'
      })
        .then(function (r) { return r.ok ? r.json() : []; })
        .then(function (data) {
          if (my !== seq) return;
          render(Array.isArray(data) ? data : (data.items || []));
        })
        .catch(function () { if (my === seq) close(); });
    }

    input.addEventListener('input', function () {
      hidden.value = '';
      window.clearTimeout(timer);
      timer = window.setTimeout(search, 250);
    });
    input.addEventListener('focus', function () {
      if (!hidden.value) search();
    });
    input.addEventListener('blur', function () { window.setTimeout(close, 120); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { close(); return; }
      if (list.classList.contains('hidden') || !items.length) return;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        active = (active + 1) % items.length;
        highlight();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        active = (active - 1 + items.length) % items.length;
        highlight();
      } else if (e.key === 'Enter' && active >= 0) {
        e.preventDefault();
        choose(items[active]);
      }
    });
  }

  document.querySelectorAll('[data-client-picker]').forEach(init);
})();
