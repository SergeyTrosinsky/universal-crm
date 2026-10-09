(function () {
  'use strict';
  var board = document.querySelector('[data-board]');
  if (!board || board.getAttribute('data-movable') !== 'true') return;

  var message = document.getElementById('board-message');
  var symbols = {};
  try {
    symbols = JSON.parse(document.getElementById('board-currencies').textContent) || {};
  } catch (e) { }
  var dragged = null;

  function showError(text) {
    if (!message) return;
    message.textContent = text;
    message.classList.remove('hidden');
    window.clearTimeout(showError.timer);
    showError.timer = window.setTimeout(function () { message.classList.add('hidden'); }, 6000);
  }

  function formatMoney(value, currency) {
    var parts = value.toFixed(2).split('.');
    var int = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
    return int + ',' + parts[1] + ' ' + (symbols[currency] || currency);
  }

  function refresh(column) {
    var cards = column.querySelectorAll('[data-card]');
    var hiddenLink = column.querySelector('a[href^="/deals?status="]');
    var extra = 0;
    if (hiddenLink) {
      var m = hiddenLink.textContent.match(/\d+/);
      extra = m ? parseInt(m[0], 10) : 0;
    }
    column.querySelector('[data-count]').textContent = String(cards.length + extra);
    if (extra) return;
    var sums = {};
    cards.forEach(function (card) {
      var cur = card.getAttribute('data-currency');
      sums[cur] = (sums[cur] || 0) + parseFloat(card.getAttribute('data-amount') || '0');
    });
    column.querySelector('[data-totals]').textContent = Object.keys(sums).sort().map(function (cur) {
      return formatMoney(sums[cur], cur);
    }).join(' · ');
  }

  function syncSelect(card, statusId) {
    var select = card.querySelector('[data-move-select]');
    if (select) select.value = String(statusId);
  }

  function move(card, targetColumn, beforeNode) {
    var sourceColumn = card.closest('[data-column]');
    var sourceNext = card.nextElementSibling;
    var statusId = targetColumn.getAttribute('data-status-id');
    if (sourceColumn === targetColumn) return;

    var zone = targetColumn.querySelector('[data-dropzone]');
    zone.insertBefore(card, beforeNode === undefined ? zone.firstChild : beforeNode);
    syncSelect(card, statusId);
    refresh(sourceColumn);
    refresh(targetColumn);
    card.classList.add('opacity-60');

    fetch('/api/v1/deals/' + card.getAttribute('data-deal-id') + '/status', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        'X-CSRF-Token': (document.querySelector('meta[name="csrf-token"]') || {}).content || ''
      },
      body: JSON.stringify({ status_id: parseInt(statusId, 10) })
    }).then(function (resp) {
      if (resp.ok) return;
      return resp.json().catch(function () { return {}; }).then(function (data) {
        var detail = data && data.detail;
        var text = typeof detail === 'string' ? detail
          : detail && typeof detail === 'object' ? Object.keys(detail).map(function (k) { return detail[k]; }).join('; ')
          : 'Не удалось изменить статус (' + resp.status + ')';
        throw new Error(resp.status === 401 || resp.status === 403 ? 'Недостаточно прав или сессия истекла — обновите страницу' : text);
      });
    }).catch(function (err) {
      var srcZone = sourceColumn.querySelector('[data-dropzone]');
      srcZone.insertBefore(card, sourceNext && sourceNext.parentNode === srcZone ? sourceNext : null);
      syncSelect(card, sourceColumn.getAttribute('data-status-id'));
      refresh(sourceColumn);
      refresh(targetColumn);
      showError(err && err.message ? err.message : 'Не удалось изменить статус');
    }).then(function () {
      card.classList.remove('opacity-60');
    });
  }

  function dropBefore(zone, y) {
    var cards = Array.prototype.filter.call(zone.querySelectorAll('[data-card]'), function (c) { return c !== dragged; });
    for (var i = 0; i < cards.length; i++) {
      var box = cards[i].getBoundingClientRect();
      if (y < box.top + box.height / 2) return cards[i];
    }
    return null;
  }

  function clearHighlight() {
    board.querySelectorAll('[data-column]').forEach(function (c) { c.classList.remove('ring-2', 'ring-indigo-400'); });
  }

  board.addEventListener('dragstart', function (e) {
    var card = e.target.closest && e.target.closest('[data-card]');
    if (!card) return;
    dragged = card;
    e.dataTransfer.effectAllowed = 'move';
    try { e.dataTransfer.setData('text/plain', card.getAttribute('data-deal-id')); } catch (err) { }
    window.setTimeout(function () { card.classList.add('opacity-40'); }, 0);
  });

  board.addEventListener('dragend', function () {
    if (dragged) dragged.classList.remove('opacity-40');
    dragged = null;
    clearHighlight();
  });

  board.addEventListener('dragover', function (e) {
    var column = e.target.closest && e.target.closest('[data-column]');
    if (!column || !dragged) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    clearHighlight();
    column.classList.add('ring-2', 'ring-indigo-400');
  });

  board.addEventListener('drop', function (e) {
    var column = e.target.closest && e.target.closest('[data-column]');
    if (!column || !dragged) return;
    e.preventDefault();
    var card = dragged;
    var before = dropBefore(column.querySelector('[data-dropzone]'), e.clientY);
    clearHighlight();
    move(card, column, before);
  });

  board.addEventListener('change', function (e) {
    var select = e.target.closest && e.target.closest('[data-move-select]');
    if (!select) return;
    var card = select.closest('[data-card]');
    var target = board.querySelector('[data-column][data-status-id="' + select.value + '"]');
    if (card && target) move(card, target, undefined);
  });
})();
