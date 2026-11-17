// Reusable client-side table pagination; the server-side forms and filters are untouched.
(function () {
  function initialize() {
    const table = document.querySelector('[data-tist-paginated]');
    const sizePicker = document.getElementById('tist-page-size');
    const summary = document.getElementById('tist-page-summary');
    const controlsTop = document.getElementById('tist-page-top');
    const controlsBottom = document.getElementById('tist-page-bottom');
    if (!table || !sizePicker || !summary || !controlsTop || !controlsBottom) return;
    const rows = Array.from(table.querySelectorAll('tbody > tr[data-page-record]'));
    let currentPage = 1;
    function makeButton(caption, page, disabled, active) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = caption;
      button.disabled = disabled;
      if (active) button.setAttribute('aria-current', 'page');
      if (!disabled && !active) button.addEventListener('click', function () { currentPage = page; render(); });
      return button;
    }
    function drawControls(container, pages) {
      container.replaceChildren();
      if (pages <= 1) return;
      container.append(makeButton('« 最初', 1, currentPage === 1, false));
      container.append(makeButton('‹ 前へ', currentPage - 1, currentPage === 1, false));
      const first = Math.max(1, Math.min(currentPage - 2, pages - 4));
      const last = Math.min(pages, first + 4);
      for (let n = first; n <= last; n++) container.append(makeButton(String(n), n, false, n === currentPage));
      container.append(makeButton('次へ ›', currentPage + 1, currentPage === pages, false));
      container.append(makeButton('最後 »', pages, currentPage === pages, false));
    }
    function render() {
      const size = Number(sizePicker.value) || 20;
      const pages = Math.max(1, Math.ceil(rows.length / size));
      currentPage = Math.max(1, Math.min(currentPage, pages));
      const offset = (currentPage - 1) * size;
      rows.forEach(function (row, idx) { row.style.display = idx >= offset && idx < offset + size ? '' : 'none'; });
      const first = rows.length ? offset + 1 : 0;
      const last = Math.min(rows.length, offset + size);
      summary.textContent = rows.length + '件中 ' + first + '～' + last + '件を表示（' + currentPage + '/' + pages + 'ページ）';
      drawControls(controlsTop, pages);
      drawControls(controlsBottom, pages);
    }
    sizePicker.addEventListener('change', function () { currentPage = 1; render(); });
    render();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize);
  else initialize();
})();
