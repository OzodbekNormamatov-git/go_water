// Ommaviy xabarnomalar (Rassilka) — matn yoki rasm + matn (bitta xabar).

import { api, ApiError } from "../api.js";
import { fmtCount, fmtDate, escapeHtml } from "../format.js";
import { toast } from "../toast.js";

const STATUS_LABELS = {
  pending:    { text: "Kutilmoqda",  cls: "pill--new" },
  sending:    { text: "Yuborilmoqda", cls: "pill--accepted" },
  done:       { text: "Tugadi",      cls: "pill--delivering" },
  failed:     { text: "Xatolik",     cls: "pill--cancelled" },
  cancelled:  { text: "Bekor qilindi", cls: "pill--inactive" },
};

// Telegram caption max — rasm bilan yuborilganda
const MAX_CAPTION = 1024;
const MAX_BODY = 3500;
const MAX_PHOTO_BYTES = 5 * 1024 * 1024;

let _pollTimer = null;
const PAGE_SIZE = 30;

export async function renderBroadcasts(root) {
  if (_pollTimer) { clearTimeout(_pollTimer); _pollTimer = null; }

  root.innerHTML = `
    <div class="toolbar" style="justify-content:space-between">
      <button class="btn" id="newBtn" type="button">➕ Yangi rassilka</button>
      <div class="muted" id="totalLabel" style="font-size:12px"></div>
    </div>
    <div id="list">Yuklanmoqda…</div>
    <div id="loadMoreWrap" style="margin-top:12px;text-align:center"></div>
  `;

  const listEl = root.querySelector("#list");
  const totalLabel = root.querySelector("#totalLabel");
  const loadMoreWrap = root.querySelector("#loadMoreWrap");

  let cache = [];
  let offset = 0;
  let total = 0;
  let loading = false;

  function render() {
    if (!cache.length) {
      listEl.innerHTML = `<div class="empty"><div class="empty__icon">📣</div><div class="empty__text">Hozircha rassilkalar yo'q.</div></div>`;
      loadMoreWrap.innerHTML = "";
      totalLabel.textContent = "";
      return;
    }
    listEl.innerHTML = cache.map(rowHtml).join("");
    listEl.querySelectorAll("[data-cancel-id]").forEach((el) => {
      el.addEventListener("click", async () => {
        const id = Number(el.getAttribute("data-cancel-id"));
        try {
          await api.cancelBroadcast(id);
          toast("To'xtatildi", "success");
          await reload();
        } catch (e) {
          toast(e.message || "Xatolik", "error");
        }
      });
    });

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

    // Aktiv rassilka bo'lsa — polling (faqat birinchi sahifani yangilab turamiz).
    const hasActive = cache.some((b) => b.status === "sending" || b.status === "pending");
    if (hasActive) {
      if (_pollTimer) clearTimeout(_pollTimer);
      _pollTimer = setTimeout(reload, 3000);
    } else if (_pollTimer) {
      clearTimeout(_pollTimer);
      _pollTimer = null;
    }
  }

  async function loadPage(reset) {
    if (loading) return;
    loading = true;
    try {
      const res = await api.broadcasts({ limit: PAGE_SIZE, offset: reset ? 0 : offset });
      const page = Array.isArray(res) ? { items: res, total: res.length } : res;
      if (reset) {
        cache = page.items || [];
        offset = (page.items || []).length;
      } else {
        cache = cache.concat(page.items || []);
        offset += (page.items || []).length;
      }
      total = Number(page.total || 0);
      render();
    } catch (e) {
      listEl.innerHTML = `<div class="empty"><div class="empty__icon">⚠️</div><div class="empty__text">${escapeHtml(e.message)}</div></div>`;
    } finally {
      loading = false;
    }
  }

  function reload() {
    cache = [];
    offset = 0;
    return loadPage(true);
  }

  root.querySelector("#newBtn").addEventListener("click", () => openComposer(reload));

  await reload();

  return () => {
    if (_pollTimer) clearTimeout(_pollTimer);
    _pollTimer = null;
  };
}

function rowHtml(b) {
  const sLabel = STATUS_LABELS[b.status] || { text: b.status, cls: "" };
  const pct = b.total ? Math.round(((b.sent + b.failed) / b.total) * 100) : 0;
  const isActive = b.status === "sending" || b.status === "pending";
  return `
    <div class="card" style="margin-bottom:12px">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px">
        <div style="flex:1;min-width:0">
          ${b.title ? `<div style="font-weight:700;margin-bottom:4px">${escapeHtml(b.title)}</div>` : ""}
          ${b.photo_url ? `
            <div style="margin-bottom:8px">
              <img src="${escapeHtml(b.photo_url)}" alt="" style="max-width:200px;max-height:140px;border-radius:8px;display:block" />
            </div>` : ""}
          <div style="white-space:pre-wrap;font-size:14px">${escapeHtml(b.body)}</div>
        </div>
        <span class="pill ${sLabel.cls}">${escapeHtml(sLabel.text)}</span>
      </div>
      <div style="display:flex;gap:18px;margin-top:10px;flex-wrap:wrap">
        <div class="muted" style="font-size:12px">Yuborildi: <b>${fmtCount(b.sent)}</b> / ${fmtCount(b.total)}</div>
        <div class="muted" style="font-size:12px">Xato: <b style="color:var(--brand-danger)">${fmtCount(b.failed)}</b></div>
        <div class="muted" style="font-size:12px">${escapeHtml(fmtDate(b.created_at))}</div>
      </div>
      <div class="progress" style="margin-top:8px;height:6px;background:var(--surface-2);border-radius:6px;overflow:hidden">
        <div style="height:100%;background:var(--brand-primary);width:${pct}%"></div>
      </div>
      ${isActive ? `
        <div style="margin-top:10px;text-align:right">
          <button class="btn btn--xs btn--danger" data-cancel-id="${b.id}" type="button">To'xtatish</button>
        </div>` : ""}
      ${b.last_error ? `<div class="muted" style="font-size:11px;margin-top:6px">Oxirgi xato: <code>${escapeHtml(b.last_error)}</code></div>` : ""}
    </div>
  `;
}

function openComposer(reload) {
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.innerHTML = `
    <div class="modal">
      <div class="modal__head">
        <h3 class="modal__title">Yangi rassilka</h3>
        <button class="modal__close" type="button">×</button>
      </div>
      <div class="modal__body">
        <label class="label" for="b-title">Sarlavha (ixtiyoriy, ichki belgi)</label>
        <input class="input" id="b-title" maxlength="80" />

        <label class="label">Rasm (ixtiyoriy)</label>
        <div class="photo-picker" id="photoPicker">
          <input type="file" id="b-photo" accept="image/jpeg,image/png,image/webp" hidden />
          <div id="photoEmpty" class="photo-picker__empty">
            <div style="font-size:30px">📷</div>
            <div style="margin-top:4px">Rasm tanlash (JPG / PNG / WebP, max 5 MB)</div>
            <div class="muted" style="font-size:11px;margin-top:4px">Rasm bilan yuborilganda matn 1024 belgidan oshmasin.</div>
          </div>
          <div id="photoFilled" class="photo-picker__filled" hidden>
            <img id="photoPreview" alt="" />
            <button type="button" class="btn btn--xs btn--secondary" id="photoRemove">O'chirish</button>
          </div>
        </div>

        <label class="label" for="b-body">Matn</label>
        <textarea class="input textarea" id="b-body" placeholder="Mijozlarga yuborayotgan e'lon, aksiya yoki yangilik…"></textarea>
        <div class="muted" id="bodyHint" style="font-size:11px;margin-top:4px;text-align:right">0 / 3500</div>

        <p class="muted" style="font-size:11px;margin-top:8px">
          Eslatma: Telegram cheklovi — bir botdan ~30 xabar/sekund. 1000 ta mijozga taxminan 30+ soniya.
        </p>
      </div>
      <div class="modal__foot">
        <button class="btn btn--secondary" id="b-cancel" type="button">Bekor</button>
        <button class="btn" id="b-send" type="button">📣 Yuborish</button>
      </div>
    </div>
  `;
  document.body.appendChild(backdrop);
  const close = () => backdrop.remove();
  backdrop.querySelector(".modal__close").addEventListener("click", close);
  backdrop.querySelector("#b-cancel").addEventListener("click", close);
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });

  const titleEl = backdrop.querySelector("#b-title");
  const bodyEl = backdrop.querySelector("#b-body");
  const sendBtn = backdrop.querySelector("#b-send");
  const photoInput = backdrop.querySelector("#b-photo");
  const photoPicker = backdrop.querySelector("#photoPicker");
  const photoEmpty = backdrop.querySelector("#photoEmpty");
  const photoFilled = backdrop.querySelector("#photoFilled");
  const photoPreview = backdrop.querySelector("#photoPreview");
  const photoRemove = backdrop.querySelector("#photoRemove");
  const bodyHint = backdrop.querySelector("#bodyHint");

  let selectedFile = null;

  const updateHint = () => {
    const len = bodyEl.value.length;
    const limit = selectedFile ? MAX_CAPTION : MAX_BODY;
    const over = len > limit;
    bodyHint.textContent = `${len} / ${limit}${selectedFile ? " (rasm bilan)" : ""}`;
    bodyHint.style.color = over ? "var(--brand-danger)" : "";
    bodyEl.maxLength = limit;
  };

  bodyEl.addEventListener("input", updateHint);
  updateHint();

  photoEmpty.addEventListener("click", () => photoInput.click());

  photoInput.addEventListener("change", () => {
    const file = photoInput.files && photoInput.files[0];
    if (!file) return;
    if (file.size > MAX_PHOTO_BYTES) {
      toast("Rasm 5 MB dan oshmasin", "error");
      photoInput.value = "";
      return;
    }
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      toast("Faqat JPG/PNG/WebP rasmlar qabul qilinadi", "error");
      photoInput.value = "";
      return;
    }
    selectedFile = file;
    photoPreview.src = URL.createObjectURL(file);
    photoEmpty.hidden = true;
    photoFilled.hidden = false;
    updateHint();
  });

  photoRemove.addEventListener("click", () => {
    selectedFile = null;
    photoInput.value = "";
    photoPreview.src = "";
    photoEmpty.hidden = false;
    photoFilled.hidden = true;
    updateHint();
  });

  sendBtn.addEventListener("click", async () => {
    const body = bodyEl.value.trim();
    if (!body) return toast("Matn bo'sh bo'lishi mumkin emas", "error");
    if (selectedFile && body.length > MAX_CAPTION) {
      return toast(`Rasm bilan matn ${MAX_CAPTION} belgidan oshmasin`, "error");
    }
    if (!selectedFile && body.length > MAX_BODY) {
      return toast(`Matn ${MAX_BODY} belgidan oshmasin`, "error");
    }
    sendBtn.disabled = true;
    sendBtn.textContent = "Yuborilmoqda…";
    try {
      const fd = new FormData();
      fd.set("title", titleEl.value.trim());
      fd.set("body", body);
      if (selectedFile) fd.set("photo", selectedFile);
      await api.createBroadcast(fd);
      toast("Yuborish boshlandi", "success");
      close();
      await reload();
    } catch (e) {
      toast(e.message || "Xatolik", "error");
    } finally {
      sendBtn.disabled = false;
      sendBtn.textContent = "📣 Yuborish";
    }
  });
}
