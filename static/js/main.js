// --- TOGGLE SUBMENU SIDEBAR ---
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

// --- PAGINATION VARS ---
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

// --- RENDER PAGINATION (ĐÃ SỬA LỖI CÚ PHÁP) ---
function renderPagination(containerTop, containerBottom, page, totalPages, onPageChange) {
    const html = `
        <button onclick="${onPageChange}(${page - 1})" ${page <= 1 ? "disabled" : ""}>前へ</button>
        <span style="font-size:12px;">[${page}] / ${totalPages}</span>
        <button onclick="${onPageChange}(${page + 1})" ${page >= totalPages ? "disabled" : ""}>次へ</button>
    `;
    if (containerTop) containerTop.innerHTML = html;
    if (containerBottom) containerBottom.innerHTML = html;
}

// --- RENDER PENDING LIST ---
function renderPending() {
    const list = document.getElementById("pending-list");
    const top = document.getElementById("pending-top");
    const bottom = document.getElementById("pending-bottom");

    if (!list || typeof pending === 'undefined') return;

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

// --- RENDER DONE LIST ---
function renderDone() {
    const list = document.getElementById("done-list");
    const top = document.getElementById("done-top");
    const bottom = document.getElementById("done-bottom");

    if (!list || typeof done === 'undefined') return;

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

// --- DOM CONTENT LOADED ---
document.addEventListener('DOMContentLoaded', function () {
    const btnSearch = document.getElementById('btn-search');
    const btnClear = document.getElementById('btn-clear');

    if (!btnSearch) return;

    const startDate = document.getElementById('date_from') || document.querySelector('input[name="date_from"]');
    const endDate = document.getElementById('date_to') || document.querySelector('input[name="date_to"]');
    const studentIdInput = document.getElementById('student_id') || document.querySelector('input[name="contact_id"]');

    // Hàm kiểm tra bật/tắt nút Search
    function checkInputs() {
        const hasStart = startDate && startDate.value.trim() !== '';
        const hasEnd = endDate && endDate.value.trim() !== '';
        const hasStudentId = studentIdInput && studentIdInput.value.trim() !== '';

        if (hasStart || hasEnd || hasStudentId) {
            btnSearch.removeAttribute('disabled');
        } else {
            btnSearch.setAttribute('disabled', 'true');
        }
    }

    // Lắng nghe thay đổi ô nhập liệu
    [startDate, endDate, studentIdInput].forEach(function (input) {
        if (input) {
            input.addEventListener('input', checkInputs);
            input.addEventListener('change', checkInputs);
            input.addEventListener('keyup', checkInputs);
        }
    });

    // Nút Clear bộ lọc
    if (btnClear) {
        btnClear.addEventListener('click', function () {
            if (startDate) startDate.value = '';
            if (endDate) endDate.value = '';
            if (studentIdInput) studentIdInput.value = '';
            
            checkInputs();
            window.location.href = window.location.pathname;
        });
    }

    checkInputs();
});

// --- CONTROLS CHO TẬP NÚT FILTER ---

// 1. Hàm Bật/Tắt (Ẩn/Hiện) khung tìm kiếm khi nhấn nút "フィルタ"
function toggleFilterContent() {
    const filterContent = document.getElementById("filter-content");
    if (!filterContent) return;
    
    if (filterContent.style.display === "none") {
        filterContent.style.display = "block";
    } else {
        filterContent.style.display = "none";
    }
}

// 2. Hàm Mở/Đóng menu xổ xuống khi nhấn nút mũi tên "▼"
function toggleClearDropdown(event) {
    if (event) event.stopPropagation();
    const dropdown = document.getElementById("filter-dropdown");
    if (!dropdown) return;

    if (dropdown.style.display === "none" || dropdown.style.display === "") {
        dropdown.style.display = "block";
    } else {
        dropdown.style.display = "none";
    }
}

// 3. Tự động đóng menu xổ xuống khi nhấp chuột ra ngoài
window.addEventListener('click', function(e) {
    const dropdown = document.getElementById("filter-dropdown");
    const arrowBtn = document.querySelector('.btn-arrow-only');
    
    if (dropdown && dropdown.style.display === "block") {
        if (arrowBtn && !arrowBtn.contains(e.target)) {
            dropdown.style.display = "none";
        }
    }
});