function toggleSubmenu(menuId, arrowId) {
    const menu = document.getElementById(menuId);
    const arrow = document.getElementById(arrowId);
    
    if (menu.classList.contains('collapsed')) {
        menu.classList.remove('collapsed');
        arrow.textContent = '∨';
    } else {
        menu.classList.add('collapsed');
        arrow.textContent = '∧';
    }
}

let pendingPage = 1;
let donePage = 1;

const pendingPerPage = 5;
const donePerPage = 5;

function safePage(page, totalPages) {
    if (totalPages === 0) return 1;
    if (page < 1) return 1;
    if (page > totalPages) return totalPages;
    return page;
}

function renderPagination(containerTop, containerBottom, page, totalPages, onPageChange) {
    const html = `
        <button onclick="${onPageChange}(${page - 1})" ${page <= 1 ? "disabled" : ""}>前へ</button>
        <span style="font-size:12px;">[${page}] / ${totalPages}</span>
        <button onclick="${onPageChange}(${page + 1})" ${page >= totalPages ? "disabled" : ""}>次へ</button>
    `;
    containerTop.innerHTML = html;
    containerBottom.innerHTML = html;
}

function renderPending() {
    const list = document.getElementById("pending-list");
    const top = document.getElementById("pending-top");
    const bottom = document.getElementById("pending-bottom");

    const totalPages = Math.ceil(pending.length / pendingPerPage);
    pendingPage = safePage(pendingPage, totalPages);

    const start = (pendingPage - 1) * pendingPerPage;
    const items = pending.slice(start, start + pendingPerPage);

    if (items.length === 0) {
        list.innerHTML = '<div class="card" style="color:#777;">未処理のデータはありません。</div>';
        renderPagination(top, bottom, 1, 1, "changePendingPage");
        return;
    }

    list.innerHTML = items.map(item => `
        <div class="card">
            <div class="time">${item.time}</div>
            <div class="info-grid">
                <div><strong>教室:</strong> ${item.key}（${item.action}）</div>
                <div><strong>名前:</strong> ${item.name}</div>
                <div><strong>学籍番号:</strong> ${item.student_id}</div>
                <div><strong>学科:</strong> ${item.department}</div>
                <div><strong>コース:</strong> ${item.course}</div>
                <div><strong>クラス:</strong> ${item.class}</div>
                <div><strong>出席番号:</strong> ${item.number}</div>
            </div>
            <div class="buttons">
                <button class="btn btn-approve" onclick="location.href='/approve/${item.id}'">承認</button>
                <button class="btn btn-reject" onclick="location.href='/reject/${item.id}'">却下</button>
                <button class="btn btn-delete" onclick="location.href='/delete/${item.id}'">削除</button>
            </div>
        </div>
    `).join("");

    renderPagination(top, bottom, pendingPage, totalPages || 1, "changePendingPage");
}

function renderDone() {
    const list = document.getElementById("done-list");
    const top = document.getElementById("done-top");
    const bottom = document.getElementById("done-bottom");

    const totalPages = Math.ceil(done.length / donePerPage);
    donePage = safePage(donePage, totalPages);

    const start = (donePage - 1) * donePerPage;
    const items = done.slice(start, start + donePerPage);

    if (items.length === 0) {
        list.innerHTML = '<div class="card" style="color:#777;">操作済みのデータはありません。</div>';
        renderPagination(top, bottom, 1, 1, "changeDonePage");
        return;
    }

    list.innerHTML = items.map(item => `
        <div class="card">
            <div class="time">${item.time}</div>
            <div class="info-grid">
                <div><strong>教室:</strong> ${item.key}（${item.action}）</div>
                <div><strong>名前:</strong> ${item.name}</div>
                <div><strong>学籍番号:</strong> ${item.student_id}</div>
                <div><strong>学科:</strong> ${item.department}</div>
                <div><strong>コース:</strong> ${item.course}</div>
                <div><strong>クラス:</strong> ${item.class}</div>
                <div><strong>出席番号:</strong> ${item.number}</div>
                <div><strong>状態:</strong> 
                    <span class="${item.status === '承認' ? 'status-approved' : 'status-rejected'}">
                        ${item.status}
                    </span>
                </div>
            </div>
            <div class="buttons">
                <button class="btn btn-approve" onclick="location.href='/approve/${item.id}'">承認に変更</button>
                <button class="btn btn-reject" onclick="location.href='/reject/${item.id}'">却下に変更</button>
                <button class="btn btn-delete" onclick="location.href='/delete/${item.id}'">削除</button>
            </div>
        </div>
    `).join("");

    renderPagination(top, bottom, donePage, totalPages || 1, "changeDonePage");
}

function changePendingPage(page) {
    pendingPage = page;
    renderPending();
}

function changeDonePage(page) {
    donePage = page;
    renderDone();
}