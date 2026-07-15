// Mahsulotlar — aktivlar + Arxiv tab (soft-deleted) + paginatsiya + rasm yuklash.

import { api } from "../api.js";
import { fmtMoney, fmtCount, fmtDate, escapeHtml } from "../format.js";
import { toast } from "../toast.js";

const PAGE_SIZE = 50;

export async function renderProducts(root) {
  let tab = "active";   // "active" | "archived"

  root.innerHTML = `
    <div class="toolbar" style="flex-wrap:wrap;gap:10px">
      <h2 style="margin:0;font-size:16px">Mahsulotlar</h2>
      <div class="seg" id="tabSeg">
        <button data-tab="active"   class="active" type="button">Aktiv</button>
        <button data-tab="archived" type="button">Arxiv</button>
      </div>
      <div class="muted" id="totalLabel" style="font-size:12px"></div>
      <div style="flex:1"></div>
      <button class="btn" id="new-btn">➕ Yangi mahsulot</button>
    </div>
    <div class="table-wrap">
      <table class="table">
        <thead id="thead">
          <tr>
            <th class="hide-narrow">#</th>
            <th>Rasm</th>
            <th>Nom</th>
            <th class="hide-narrow">Tavsif</th>
            <th style="text-align:right">Narx</th>
            <th>Holat</th>
            <th></th>
          </tr>
        </thead>
        <tbody id="tbody"><tr><td colspan="7" class="loading">Yuklanmoqda…</td></tr></tbody>
      </table>
    </div>
    <div id="loadMoreWrap" style="margin-top:12px;text-align:center"></div>
  `;

  const tbody = document.getElementById("tbody");
  const tabSeg = document.getElementById("tabSeg");
  const newBtn = document.getElementById("new-btn");
  const totalLabel = document.getElementById("totalLabel");
  const loadMoreWrap = document.getElementById("loadMoreWrap");

  let cache = [];
  let offset = 0;
  let total = 0;
  let loading = false;

  // Tannarx (COGS) — moliyaviy ma'lumot, faqat admin ko'radi (backend
  // operatorga cost_price=null qaytaradi). Yaratish formasida input'ni
  // ko'rsatish/yashirish uchun role'ni aniqlab olamiz.
  let isAdmin = false;
  api.me().then((me) => { isAdmin = !!me && me.role === "admin"; }).catch(() => {});

  function setTab(next) {
    if (tab === next) return;
    tab = next;
    tabSeg.querySelectorAll("button[data-tab]").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === tab);
    });
    newBtn.style.display = tab === "archived" ? "none" : "";
    reload();
  }

  tabSeg.querySelectorAll("button[data-tab]").forEach((b) => {
    b.addEventListener("click", () => setTab(b.dataset.tab));
  });

  function thumbCell(image_path) {
    // Rasm "media/foods/..." formatida (server-side endpoint shu yo'lni qaytaradi);
    // statik mount `/media/...` ga moslashtirilgan.
    if (image_path && image_path.startsWith("media/")) {
      return `<img class="product-thumb" src="/${escapeHtml(image_path)}" alt="" loading="lazy" />`;
    }
    return `<div class="product-thumb product-thumb--empty" title="Rasmsiz">📷</div>`;
  }

  function renderRows() {
    if (!cache.length) {
      const emptyText = tab === "archived"
        ? "Arxivlangan mahsulot yo'q."
        : "Mahsulot yo'q.";
      tbody.innerHTML = `<tr><td colspan="7" class="empty"><div class="empty__icon">💧</div><div class="empty__text">${emptyText}</div></td></tr>`;
      loadMoreWrap.innerHTML = "";
      totalLabel.textContent = "";
      return;
    }
    tbody.innerHTML = cache.map((p) => rowHtml(p, tab)).join("");
    bindRowActions(cache);
    totalLabel.textContent = `${fmtCount(cache.length)} / ${fmtCount(total)}`;
    if (cache.length < total) {
      const remaining = total - cache.length;
      loadMoreWrap.innerHTML = `
        <button class="btn btn--secondary" id="loadMoreBtn" type="button">
          Yana yuklash (${fmtCount(remaining)} qoldi)
        </button>
      `;
      loadMoreWrap.querySelector("#loadMoreBtn").addEventListener("click", () => loadPage(false));
    } else {
      loadMoreWrap.innerHTML = "";
    }
  }

  async function loadPage(reset) {
    if (loading) return;
    loading = true;
    try {
      const res = await api.products({
        archived: tab === "archived",
        limit: PAGE_SIZE,
        offset: reset ? 0 : offset,
      });
      const page = Array.isArray(res) ? { items: res, total: res.length } : res;
      if (reset) {
        cache = page.items || [];
        offset = (page.items || []).length;
      } else {
        cache = cache.concat(page.items || []);
        offset += (page.items || []).length;
      }
      total = Number(page.total || 0);
      renderRows();
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="7" class="empty"><div class="empty__icon">⚠️</div><div class="empty__text">${escapeHtml(e.message)}</div></td></tr>`;
    } finally {
      loading = false;
    }
  }

  function reload() {
    cache = [];
    offset = 0;
    loadPage(true);
  }

  // Idish hisobi belgisi — admin bir qarashda ko'rishi uchun. Oddiy idish
  // (bottles_per_unit === 1) — yashirin (eng keng tarqalgan holat, shovqin qilmaymiz).
  function bottlesHint(p) {
    const bpu = Number(p.bottles_per_unit ?? 1);
    if (bpu === 0) {
      return `<div class="muted" style="font-size:11px">♻️ idish sanalmaydi</div>`;
    }
    if (bpu > 1) {
      return `<div class="muted" style="font-size:11px">♻️ ${bpu} idish/dona</div>`;
    }
    return "";
  }

  // Tannarx belgisi — narx yonida kichik qilib (faqat admin ko'radi: operator
  // uchun cost_price null keladi; 0 = kiritilmagan — ko'rsatmaymiz).
  function costHint(p) {
    if (p.cost_price == null || !(Number(p.cost_price) > 0)) return "";
    return `<div class="muted" style="font-size:11px">tannarx ${fmtMoney(p.cost_price)}</div>`;
  }

  function rowHtml(p, mode) {
    if (mode === "archived") {
      return `
        <tr style="opacity:0.7">
          <td class="hide-narrow"><b>${p.id}</b></td>
          <td>${thumbCell(p.image_path)}</td>
          <td>${escapeHtml(p.name)}</td>
          <td class="hide-narrow muted">${escapeHtml(p.description || "—")}</td>
          <td style="text-align:right;font-weight:600">${fmtMoney(p.price)}${costHint(p)}</td>
          <td><span class="pill pill--inactive">📦 ${escapeHtml(fmtDate(p.deleted_at))}</span></td>
          <td style="text-align:right">
            <button class="btn btn--xs btn--success" data-act="restore" data-id="${p.id}">↩️ Qaytarish</button>
          </td>
        </tr>
      `;
    }
    return `
      <tr>
        <td class="hide-narrow"><b>${p.id}</b></td>
        <td>${thumbCell(p.image_path)}</td>
        <td>${escapeHtml(p.name)}${Number(p.min_quantity || 1) > 1 ? `<div class="muted" style="font-size:11px">min ${p.min_quantity} dona</div>` : ""}${bottlesHint(p)}</td>
        <td class="hide-narrow muted">${escapeHtml(p.description || "—")}</td>
        <td style="text-align:right;font-weight:600">${fmtMoney(p.price)}${costHint(p)}</td>
        <td><span class="pill pill--${p.is_available ? 'active' : 'inactive'}">${p.is_available ? "✅" : "⛔️"}</span></td>
        <td style="text-align:right">
          <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">
            <button class="btn btn--xs btn--secondary" data-act="edit"   data-id="${p.id}">✏️</button>
            <button class="btn btn--xs btn--secondary" data-act="toggle" data-id="${p.id}">${p.is_available ? "🔒" : "🔓"}</button>
            <button class="btn btn--xs btn--danger"    data-act="delete" data-id="${p.id}">🗑</button>
          </div>
        </td>
      </tr>
    `;
  }

  function bindRowActions(items) {
    tbody.querySelectorAll("button[data-act]").forEach((btn) => {
      const id = Number(btn.dataset.id);
      const act = btn.dataset.act;
      btn.addEventListener("click", async () => {
        const p = items.find((x) => x.id === id);
        if (!p) return;
        if (act === "toggle") {
          try {
            await api.updateProduct(id, { is_available: !p.is_available });
            toast("Holat yangilandi", "success");
            reload();
          } catch (e) { toast(e.message, "error"); }
        } else if (act === "edit") {
          openEditModal(p, reload);
        } else if (act === "delete") {
          // Soft delete — "Arxivlash" terminologiyasi (foydalanuvchiga aniqroq)
          if (!confirm(`"${p.name}" mahsulotini arxivga ko'chiramizmi?\n\nEski buyurtmalarda u o'z joyida ko'rinishda davom etadi.\n"Arxiv" tab'idan istalgan vaqtda qaytarish mumkin.`)) return;
          try {
            await api.deleteProduct(id);
            toast("Arxivlandi (qaytarish mumkin)", "success");
            reload();
          } catch (e) { toast(e.message, "error"); }
        } else if (act === "restore") {
          try {
            await api.restoreProduct(id);
            toast("Qaytarildi", "success");
            reload();
          } catch (e) { toast(e.message, "error"); }
        }
      });
    });
  }

  newBtn.addEventListener("click", () => openCreateModal(reload, isAdmin));

  reload();
}

// ---------------------- Image picker (shared widget) ----------------------
//
// Modal ichida ishlatiladi. State: file (yangi tanlangan, hali yuklanmagan)
// YOKI existing_url (DB'dagi joriy rasm). Foydalanuvchi yangisini tanlasa,
// preview yangisini ko'rsatadi.
//
// `getFile()` — agar yangi tanlangan bo'lsa qaytaradi, aks holda null.
// `isCleared()` — foydalanuvchi rasmni o'chirgan bo'lsa true.

function attachImagePicker(container, { initialUrl } = {}) {
  let currentUrl = initialUrl || null;
  let pendingFile = null;
  let cleared = false;

  function render() {
    if (pendingFile) {
      const url = URL.createObjectURL(pendingFile);
      container.innerHTML = `
        <div class="photo-picker__filled">
          <img src="${url}" alt="" />
          <button type="button" class="btn btn--xs" data-act="remove">Bekor qilish</button>
        </div>
        <div class="muted" style="font-size:12px;margin-top:4px">
          Yangi rasm tanlandi: <b>${escapeHtml(pendingFile.name)}</b> (saqlash uchun "Saqlash" bosing)
        </div>
      `;
    } else if (currentUrl && !cleared) {
      container.innerHTML = `
        <div class="photo-picker__filled">
          <img src="${escapeHtml(currentUrl)}" alt="" />
          <div style="position:absolute;top:8px;right:8px;display:flex;gap:6px">
            <label class="btn btn--xs" style="cursor:pointer">
              ✏️ Almashtirish
              <input type="file" accept="image/*" hidden />
            </label>
            <button type="button" class="btn btn--xs btn--danger" data-act="clear">🗑</button>
          </div>
        </div>
      `;
    } else {
      // Bo'sh — yuklash uchun katta drop zone
      container.innerHTML = `
        <label class="photo-picker__empty" style="cursor:pointer;display:block">
          <div style="font-size:32px">📷</div>
          <div>Rasm yuklash uchun bosing</div>
          <div style="font-size:11px;margin-top:4px">JPG / PNG / WEBP, max 5 MB</div>
          <input type="file" accept="image/*" hidden />
        </label>
      `;
    }
    bind();
  }

  function bind() {
    const fileInput = container.querySelector('input[type="file"]');
    if (fileInput) {
      fileInput.addEventListener("change", (e) => {
        const file = e.target.files && e.target.files[0];
        if (!file) return;
        if (file.size > 5 * 1024 * 1024) {
          toast("Rasm 5 MB dan oshmasin", "error");
          return;
        }
        pendingFile = file;
        cleared = false;
        render();
      });
    }
    const removeBtn = container.querySelector('[data-act="remove"]');
    if (removeBtn) {
      removeBtn.addEventListener("click", () => {
        pendingFile = null;
        render();
      });
    }
    const clearBtn = container.querySelector('[data-act="clear"]');
    if (clearBtn) {
      clearBtn.addEventListener("click", () => {
        if (!confirm("Mahsulot rasmini o'chiramizmi?")) return;
        cleared = true;
        currentUrl = null;
        pendingFile = null;
        render();
      });
    }
  }

  render();
  return {
    getFile: () => pendingFile,
    isCleared: () => cleared && !pendingFile,
  };
}

function openCreateModal(onSaved, showCost) {
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.innerHTML = `
    <div class="modal">
      <div class="modal__head">
        <h3 class="modal__title">Yangi mahsulot</h3>
        <button class="modal__close" data-close>×</button>
      </div>
      <div class="modal__body">
        <label class="label">Nom</label>
        <input class="input" id="m-name" placeholder="Suv 18.9 l" />
        <label class="label">Tavsif (ixtiyoriy)</label>
        <textarea class="textarea" id="m-desc"></textarea>
        <label class="label">Narx</label>
        <input class="input" id="m-price" type="number" inputmode="numeric" placeholder="22000" />
        ${showCost ? `
        <label class="label">Tannarx (so'm)</label>
        <input class="input" id="m-cost" type="number" inputmode="numeric" min="0" placeholder="15000" />
        <div class="muted" style="font-size:12px;margin-top:4px">
          Bir dona mahsulotning xarid narxi — foyda hisobotida ishlatiladi. Bo'sh = kiritilmagan (0).
        </div>` : ""}
        <label class="label">Minimal buyurtma (dona)</label>
        <input class="input" id="m-minq" type="number" inputmode="numeric" min="1" max="999" step="1" value="1" />
        <div class="muted" style="font-size:12px;margin-top:4px">
          Mijoz shu mahsulotdan kamida shuncha dona olishi shart. <b>1</b> = cheklov yo'q.
        </div>
        <label class="label">♻️ Qaytariladigan idish (har dona)</label>
        <input class="input" id="m-bpu" type="number" inputmode="numeric" min="0" max="99" step="1" value="1" />
        <div class="muted" style="font-size:12px;margin-top:4px">
          Har dona necha qaytariladigan idish beradi (idish balansiga qo'shiladi).
          <b>0</b> = sanalmaydi (suv pumpasi, kuller, filtr), <b>1</b> = oddiy idish (suv).
        </div>
        <label class="label">Rasm (ixtiyoriy)</label>
        <div id="m-image" class="photo-picker"></div>
      </div>
      <div class="modal__foot">
        <button class="btn btn--secondary" data-close>Bekor</button>
        <button class="btn btn--success" id="m-save">Saqlash</button>
      </div>
    </div>
  `;
  document.body.appendChild(backdrop);
  const close = () => backdrop.remove();
  backdrop.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", close));
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });

  const picker = attachImagePicker(document.getElementById("m-image"));

  document.getElementById("m-save").addEventListener("click", async () => {
    const name = document.getElementById("m-name").value.trim();
    const description = document.getElementById("m-desc").value.trim();
    const price = Number(document.getElementById("m-price").value);
    const minQty = Math.floor(Number(document.getElementById("m-minq").value)) || 1;
    const bpu = Math.floor(Number(document.getElementById("m-bpu").value));
    if (name.length < 2) return toast("Nomi juda qisqa", "error");
    if (!(price > 0)) return toast("Narx noto'g'ri", "error");
    if (minQty < 1 || minQty > 999) return toast("Minimal buyurtma 1..999 oralig'ida bo'lishi shart", "error");
    if (!(bpu >= 0) || bpu > 99) return toast("Qaytariladigan idish 0..99 oralig'ida bo'lishi shart", "error");
    // Tannarx — input faqat adminda bor; bo'sh qoldirilsa yubormaymiz (server 0 qiladi).
    const costEl = document.getElementById("m-cost");
    const body = { name, description, price, min_quantity: minQty, bottles_per_unit: bpu };
    if (costEl && costEl.value.trim() !== "") {
      const cost = Number(costEl.value);
      if (!Number.isFinite(cost) || cost < 0) return toast("Tannarx manfiy bo'la olmaydi", "error");
      body.cost_price = cost;
    }
    const saveBtn = document.getElementById("m-save");
    saveBtn.disabled = true;
    saveBtn.textContent = "Saqlanmoqda…";
    try {
      const created = await api.createProduct(body);
      const file = picker.getFile();
      if (file) {
        // Mahsulot yaratildi — rasmni alohida POST qilamiz. Xato bo'lsa,
        // mahsulot rasmsiz qoladi (admin keyin tahrirlashi mumkin).
        try {
          await api.uploadProductImage(created.id, file);
        } catch (e) {
          toast(`Mahsulot yaratildi, lekin rasm yuklanmadi: ${e.message}`, "error");
        }
      }
      toast("Yaratildi", "success");
      close();
      onSaved && onSaved();
    } catch (e) {
      toast(e.message, "error");
      saveBtn.disabled = false;
      saveBtn.textContent = "Saqlash";
    }
  });
}

function openEditModal(p, onSaved) {
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  // Mavjud rasm URL'i — static mount orqali keladi.
  const currentImageUrl = p.image_path && p.image_path.startsWith("media/")
    ? `/${p.image_path}` : null;
  backdrop.innerHTML = `
    <div class="modal">
      <div class="modal__head">
        <h3 class="modal__title">Tahrirlash: ${escapeHtml(p.name)}</h3>
        <button class="modal__close" data-close>×</button>
      </div>
      <div class="modal__body">
        <label class="label">Nom</label>
        <input class="input" id="m-name" value="${escapeHtml(p.name)}" />
        <label class="label">Tavsif</label>
        <textarea class="textarea" id="m-desc">${escapeHtml(p.description || "")}</textarea>
        <label class="label">Narx</label>
        <input class="input" id="m-price" type="number" value="${p.price}" />
        ${p.cost_price != null ? `
        <label class="label">Tannarx (so'm)</label>
        <input class="input" id="m-cost" type="number" inputmode="numeric" min="0" value="${Number(p.cost_price)}" />
        <div class="muted" style="font-size:12px;margin-top:4px">
          Bir dona mahsulotning xarid narxi — foyda hisobotida ishlatiladi. <b>0</b> = kiritilmagan.
        </div>` : ""}
        <label class="label">Minimal buyurtma (dona)</label>
        <input class="input" id="m-minq" type="number" inputmode="numeric" min="1" max="999" step="1" value="${Number(p.min_quantity || 1)}" />
        <div class="muted" style="font-size:12px;margin-top:4px">
          Mijoz shu mahsulotdan kamida shuncha dona olishi shart. <b>1</b> = cheklov yo'q.
        </div>
        <label class="label">♻️ Qaytariladigan idish (har dona)</label>
        <input class="input" id="m-bpu" type="number" inputmode="numeric" min="0" max="99" step="1" value="${Number(p.bottles_per_unit ?? 1)}" />
        <div class="muted" style="font-size:12px;margin-top:4px">
          Har dona necha qaytariladigan idish beradi (idish balansiga qo'shiladi).
          <b>0</b> = sanalmaydi (suv pumpasi, kuller, filtr), <b>1</b> = oddiy idish (suv).
        </div>
        <label class="label">Rasm</label>
        <div id="m-image" class="photo-picker"></div>
      </div>
      <div class="modal__foot">
        <button class="btn btn--secondary" data-close>Bekor</button>
        <button class="btn btn--success" id="m-save">Saqlash</button>
      </div>
    </div>
  `;
  document.body.appendChild(backdrop);
  const close = () => backdrop.remove();
  backdrop.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", close));
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });

  const picker = attachImagePicker(document.getElementById("m-image"), { initialUrl: currentImageUrl });

  document.getElementById("m-save").addEventListener("click", async () => {
    const name = document.getElementById("m-name").value.trim();
    const description = document.getElementById("m-desc").value.trim();
    const price = Number(document.getElementById("m-price").value);
    const minQty = Math.floor(Number(document.getElementById("m-minq").value)) || 1;
    const bpu = Math.floor(Number(document.getElementById("m-bpu").value));
    if (minQty < 1 || minQty > 999) return toast("Minimal buyurtma 1..999 oralig'ida bo'lishi shart", "error");
    if (!(bpu >= 0) || bpu > 99) return toast("Qaytariladigan idish 0..99 oralig'ida bo'lishi shart", "error");
    // Tannarx — input faqat adminda bor; bo'sh qoldirilsa o'zgartirmaymiz.
    const costEl = document.getElementById("m-cost");
    const body = { name, description, price, min_quantity: minQty, bottles_per_unit: bpu };
    if (costEl && costEl.value.trim() !== "") {
      const cost = Number(costEl.value);
      if (!Number.isFinite(cost) || cost < 0) return toast("Tannarx manfiy bo'la olmaydi", "error");
      body.cost_price = cost;
    }
    const saveBtn = document.getElementById("m-save");
    saveBtn.disabled = true;
    saveBtn.textContent = "Saqlanmoqda…";
    try {
      // 1) Matn maydonlari (PATCH)
      await api.updateProduct(p.id, body);
      // 2) Rasm o'zgargan bo'lsa, alohida endpoint
      const file = picker.getFile();
      if (file) {
        await api.uploadProductImage(p.id, file);
      } else if (picker.isCleared()) {
        await api.deleteProductImage(p.id);
      }
      toast("Saqlandi", "success");
      close();
      onSaved && onSaved();
    } catch (e) {
      toast(e.message, "error");
      saveBtn.disabled = false;
      saveBtn.textContent = "Saqlash";
    }
  });
}
