const Cart = (() => {
    let key = null;

    function init(tableToken, customerId) {
        key = `cart:${tableToken}:${customerId || "anon"}`;
        syncUI();
      }
      

    function _load() {
        try { return JSON.parse(localStorage.getItem(key) || "[]"); } catch { return []; }
    }
    function _save(lines) {
        localStorage.setItem(key, JSON.stringify(lines));
        syncUI();
    }

    function add(menu_item_id, name, price) {
        const lines = _load();
        const found = lines.find(x => x.menu_item_id === menu_item_id);
        if (found) found.qty += 1;
        else lines.push({ menu_item_id, name, price, qty: 1, note: "" });
        _save(lines);
    }

    function remove(menu_item_id) {
        const lines = _load().filter(x => x.menu_item_id !== menu_item_id);
        _save(lines);
    }

    function setQty(menu_item_id, qty) {
        const lines = _load();
        const found = lines.find(x => x.menu_item_id === menu_item_id);
        if (!found) return;
        found.qty = Math.max(1, parseInt(qty || 1, 10));
        _save(lines);
    }

    function setNote(menu_item_id, note) {
        const lines = _load();
        const found = lines.find(x => x.menu_item_id === menu_item_id);
        if (!found) return;
        found.note = (note || "").slice(0, 300);
        _save(lines);
    }

    function getLines() { return _load(); }
    function clear() { localStorage.removeItem(key); syncUI(); }

    function total() {
        return _load().reduce((s, x) => s + (Number(x.price) || 0) * (Number(x.qty) || 0), 0);
    }
    function count() {
        return _load().reduce((s, x) => s + (Number(x.qty) || 0), 0);
    }

    function syncUI() {
        const c = document.getElementById("cartCount");
        const t = document.getElementById("cartTotal");
        if (c) c.textContent = String(count());
        if (t) t.textContent = total().toFixed(2);
    }

    function renderCheckout() {
        const lines = _load();
        const empty = document.getElementById("cartEmpty");
        const list = document.getElementById("cartList");
        const sum = document.getElementById("sumTotal");

        if (sum) sum.textContent = total().toFixed(2);

        if (!list || !empty) return;
        list.innerHTML = "";
        if (!lines.length) {
            empty.style.display = "";
            return;
        }
        empty.style.display = "none";

        lines.forEach(line => {
            const row = document.createElement("div");
            row.className = "border rounded p-2";
            row.innerHTML = `
        <div class="d-flex justify-content-between align-items-start">
          <div>
            <div class="fw-bold">${escapeHtml(line.name)}</div>
            <div class="small text-muted">฿${Number(line.price).toFixed(2)}</div>
          </div>
          <button class="btn btn-sm btn-outline-danger" data-del>ลบ</button>
        </div>

        <div class="row g-2 mt-2">
          <div class="col-6">
            <input class="form-control form-control-sm"
                   type="number" min="1" inputmode="numeric"
                   value="${line.qty}" data-qty />
          </div>
          <div class="col-6 text-end small pt-1">
            รวม: ฿${(Number(line.price) * Number(line.qty)).toFixed(2)}
          </div>
        </div>

        <div class="mt-2">
          <input class="form-control form-control-sm"
                 placeholder="หมายเหตุรายการ..."
                 value="${escapeAttr(line.note || "")}" data-note />
        </div>
      `;

            row.querySelector("[data-del]").addEventListener("click", () => {
                remove(line.menu_item_id);
                renderCheckout();
            });

            // ✅ เปลี่ยน change -> input (แก้เคสกดย้อนกลับแล้วไม่เซฟ)
            const qtyEl = row.querySelector("[data-qty]");
            qtyEl.addEventListener("input", (e) => {
                setQty(line.menu_item_id, e.target.value);
                renderCheckout();
            });
            // ✅ กันเหนียว: ถ้ากดย้อนกลับตอนยังโฟกัสอยู่
            qtyEl.addEventListener("blur", (e) => {
                setQty(line.menu_item_id, e.target.value);
            });

            row.querySelector("[data-note]").addEventListener("input", (e) => {
                setNote(line.menu_item_id, e.target.value);
            });

            list.appendChild(row);
        });
    }

    function escapeHtml(s) {
        return String(s || "").replace(/[&<>"']/g, m => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
        }[m]));
    }
    function escapeAttr(s) { return escapeHtml(s).replace(/"/g, "&quot;"); }

    return { init, add, remove, setQty, setNote, getLines, clear, total, count, syncUI, renderCheckout };
})();
