// Xaritadan joy tanlash (Leaflet + OpenStreetMap — bepul, kalit yo'q).
//
// Foydalanish:
//   import { openMapPicker } from "./mappicker.js";
//   const loc = await openMapPicker({ initial: { latitude, longitude }, title: "Yetkazib berish nuqtasi" });
//   // loc = { latitude, longitude } yoki null (bekor)
//
// Pin xarita markazida turadi (Telegram'dagi sharing UX uchun standart pattern).
// Foydalanuvchi xaritani surganda pin xarita markazida qoladi — chiqarayotgan
// koordinata = xarita markazi. Tugma bosilganda shu qiymat qaytariladi.
//
// Manzil qidiruv: xarita tepasida search input — Nominatim (OpenStreetMap)
// orqali manzil yoki ko'cha nomi bilan topish mumkin. Tanlangan natija
// bosilsa, pin shu joyga ko'chadi.

import { requestLocation, hapticImpact } from "./telegram.js";
import { api } from "./api.js";
import { escapeHtml } from "./format.js";

const LEAFLET_CSS = "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css";
const LEAFLET_JS  = "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js";

// Default markaz: Toshkent
const FALLBACK = { latitude: 41.3111, longitude: 69.2797 };

// Manzil qidiruv — bizning backend (Photon/OSM) orqali. Ko'cha/uy/mahalla
// nomlarini topadi, kalit kerak emas. Natija: [{title, subtitle, latitude, longitude}].

let _leafletLoading = null;

function _loadLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  if (_leafletLoading) return _leafletLoading;
  _leafletLoading = new Promise((resolve, reject) => {
    if (!document.querySelector(`link[href="${LEAFLET_CSS}"]`)) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = LEAFLET_CSS;
      document.head.appendChild(link);
    }
    const s = document.createElement("script");
    s.src = LEAFLET_JS;
    s.onload = () => resolve(window.L);
    s.onerror = () => reject(new Error("Xarita yuklanmadi. Internet aloqasini tekshiring."));
    document.head.appendChild(s);
  });
  return _leafletLoading;
}

/**
 * Modal map picker. Returns Promise<{ latitude, longitude } | null>.
 *
 * Options:
 *   - initial: { latitude, longitude }     — boshlang'ich markaz (yo'q bo'lsa Toshkent)
 *   - title:   string                       — modal sarlavhasi
 */
export async function openMapPicker({ initial, title = "Manzilni tanlang" } = {}) {
  const L = await _loadLeaflet().catch((e) => {
    alert(e.message || "Xarita yuklanmadi.");
    return null;
  });
  if (!L) return null;

  return new Promise((resolve) => {
    const start = initial && Number.isFinite(initial.latitude) && Number.isFinite(initial.longitude)
      ? initial
      : FALLBACK;

    const backdrop = document.createElement("div");
    backdrop.className = "map-picker__backdrop";
    backdrop.innerHTML = `
      <div class="map-picker">
        <div class="map-picker__head">
          <div class="map-picker__title">${title}</div>
          <button class="map-picker__close" type="button" aria-label="Yopish">×</button>
        </div>
        <div class="map-picker__search">
          <input
            class="map-picker__search-input"
            id="mp-search"
            type="text"
            inputmode="search"
            autocomplete="off"
            placeholder="Manzil yoki ko'cha bo'yicha qidirish…"
          />
          <button class="map-picker__search-btn" id="mp-search-btn" type="button" aria-label="Qidirish">🔍</button>
        </div>
        <div class="map-picker__results" id="mp-results" hidden></div>
        <div class="map-picker__map" id="mp-map"></div>
        <div class="map-picker__pin">📍</div>
        <div class="map-picker__hint">Xaritani surib, pin'ni manzilingizga to'g'rilang.</div>
        <div class="map-picker__address" id="mp-address" style="font-size:13px;font-weight:600;text-align:center;min-height:18px;padding:0 12px"></div>
        <div class="map-picker__coord" id="mp-coord"></div>
        <div class="map-picker__foot">
          <button class="btn btn--secondary" id="mp-locate" type="button">📍 Mening joyim</button>
          <button class="btn" id="mp-ok" type="button">Tanlash</button>
        </div>
      </div>
    `;
    document.body.appendChild(backdrop);

    const map = L.map(backdrop.querySelector("#mp-map"), {
      attributionControl: false,
      zoomControl: true,
    }).setView([start.latitude, start.longitude], 14);

    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
    }).addTo(map);

    const coordEl = backdrop.querySelector("#mp-coord");
    const addressEl = backdrop.querySelector("#mp-address");
    const fmt = (n) => n.toFixed(5);
    let lastAddress = "";
    const refresh = () => {
      const c = map.getCenter();
      coordEl.textContent = `Lat: ${fmt(c.lat)}, Lon: ${fmt(c.lng)}`;
    };
    refresh();
    map.on("move", refresh);

    // Pin to'xtaganda — manzilni teskari aniqlaymiz (ko'cha/uy/mahalla ko'rinsin).
    // x,y baribir saqlanadi; bu faqat odam o'qiydigan nom.
    let revTimer = null;
    const refreshAddress = () => {
      const c = map.getCenter();
      addressEl.textContent = "📍 manzil aniqlanmoqda…";
      addressEl.style.opacity = "0.6";
      clearTimeout(revTimer);
      revTimer = setTimeout(async () => {
        try {
          const r = await api.reverseGeocode(c.lat, c.lng);
          lastAddress = (r && r.address) || "";
          addressEl.textContent = lastAddress || "📍 manzil nomi topilmadi (joylashuv saqlanadi)";
          addressEl.style.opacity = lastAddress ? "1" : "0.6";
        } catch {
          addressEl.textContent = "";
        }
      }, 500);
    };
    refreshAddress();
    map.on("moveend", refreshAddress);

    let cancelled = false;
    const finish = (result) => {
      cancelled = true;
      map.remove();
      backdrop.remove();
      resolve(result);
    };

    backdrop.querySelector(".map-picker__close").addEventListener("click", () => finish(null));
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) finish(null);
    });

    backdrop.querySelector("#mp-ok").addEventListener("click", async () => {
      const c = map.getCenter();
      let address = lastAddress;
      if (!address) {
        try { const r = await api.reverseGeocode(c.lat, c.lng); address = (r && r.address) || ""; } catch { /* x,y baribir qaytadi */ }
      }
      finish({ latitude: c.lat, longitude: c.lng, address });
    });

    const locateBtn = backdrop.querySelector("#mp-locate");
    const hintEl = backdrop.querySelector(".map-picker__hint");
    const originalHint = hintEl.textContent;

    // Foydalanuvchi pin'ni qo'lda surdimi? Surgan bo'lsa, fon GPS pin'ni
    // ko'chirmaymiz (foydalanuvchi tanlovini buzmaslik).
    let userTouchedMap = false;
    map.on("dragstart", () => { userTouchedMap = true; });
    map.on("zoomstart", () => { userTouchedMap = true; });

    // ---------------------- SEARCH (Photon/OSM — ko'cha/uy/mahalla) ----------------------

    const searchEl = backdrop.querySelector("#mp-search");
    const searchBtn = backdrop.querySelector("#mp-search-btn");
    const resultsEl = backdrop.querySelector("#mp-results");
    let searchTimer = null;

    const doSearch = async () => {
      const q = (searchEl.value || "").trim();
      if (q.length < 2) { resultsEl.hidden = true; return; }
      resultsEl.hidden = false;
      resultsEl.innerHTML = `<div class="map-picker__result-status">Qidirilmoqda…</div>`;
      try {
        const center = map.getCenter();
        const results = await api.geocode(q, { lat: center.lat, lon: center.lng });
        if (!results || !results.length) {
          resultsEl.innerHTML = `<div class="map-picker__result-status">Topilmadi. Boshqa nom bilan urinib ko'ring.</div>`;
          return;
        }
        resultsEl.innerHTML = results.map((r, i) => `
            <button type="button" class="map-picker__result" data-idx="${i}">
              <div class="map-picker__result-title">${escapeHtml(r.title)}</div>
              <div class="map-picker__result-sub">${escapeHtml(r.subtitle)}</div>
            </button>`).join("");
        resultsEl.querySelectorAll(".map-picker__result").forEach((el) => {
          el.addEventListener("click", () => {
            const r = results[Number(el.dataset.idx)];
            if (!r || !Number.isFinite(r.latitude) || !Number.isFinite(r.longitude)) return;
            map.setView([r.latitude, r.longitude], 17);
            userTouchedMap = true;  // tanlangan manzilni fon GPS bilan almashtirmaylik
            if (r.address) {
              lastAddress = r.address;
              addressEl.textContent = r.address;
              addressEl.style.opacity = "1";
            }
            resultsEl.hidden = true;
            hapticImpact("light");
          });
        });
      } catch (e) {
        resultsEl.innerHTML = `<div class="map-picker__result-status">${escapeHtml(e.message || "Qidiruv xatosi")}</div>`;
      }
    };

    // Jonli avtocomplete (yozayotganda) + tugma + Enter.
    searchEl.addEventListener("input", () => {
      clearTimeout(searchTimer);
      const q = (searchEl.value || "").trim();
      if (q.length < 2) { resultsEl.hidden = true; return; }
      searchTimer = setTimeout(doSearch, 350);
    });
    searchBtn.addEventListener("click", doSearch);
    searchEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); clearTimeout(searchTimer); doSearch(); }
    });
    // Xarita bosilsa — natijalar yashirinadi (yo'ldan olib tashlash)
    backdrop.querySelector("#mp-map").addEventListener("pointerdown", () => {
      resultsEl.hidden = true;
    });

    // FON GPS — xarita ochilgach watchPosition ishga tushadi. Har oraliq fix'da
    // pin silliq ko'chib boradi (aniqlik yaxshilangani sari pin maqsadga
    // yaqinlashadi). Final (threshold yoki maxWait) — bir kuchliroq flyTo bilan
    // tasdiqlash. Fail bo'lsa hech narsa demaymiz (xarita o'zicha ishlaydi).
    requestLocation({
      background: true,
      onProgress: (fix) => {
        if (cancelled || userTouchedMap) return;
        // Oraliq fix — qisqa silliq harakat, zoom o'zgartirmaymiz (titroq oldi).
        map.panTo([fix.latitude, fix.longitude], { animate: true, duration: 0.4 });
      },
    })
      .then((loc) => {
        if (cancelled || userTouchedMap) return;
        map.flyTo([loc.latitude, loc.longitude], 16, { duration: 0.8 });
        hapticImpact("light");
      })
      .catch(() => { /* fon — sukutda fail */ });

    // EXPLICIT GPS — "Mening joyim" tugmasi. Foydalanuvchi tanlasa, aniqroq.
    // Oraliq fix'larda hint accuracy bilan yangilanib boradi (80m → 45m → 28m).
    locateBtn.addEventListener("click", async () => {
      if (locateBtn.disabled) return;
      locateBtn.disabled = true;
      const originalText = locateBtn.textContent;
      locateBtn.textContent = "⏳ Aniqlanmoqda…";
      hintEl.textContent = "Brauzer ruxsat so'rashi mumkin — \"Allow\" ni bosing.";
      try {
        const loc = await requestLocation({
          onProgress: (fix) => {
            // Foydalanuvchi kutyapti — har yaxshilanishni ko'rsatamiz.
            const acc = Math.round(fix.accuracy || 0);
            hintEl.textContent = `📡 Aniqlanmoqda… ${acc}m`;
            // Pin xaritada ham silliq ko'chsin — zoom o'zgartirmaymiz.
            map.panTo([fix.latitude, fix.longitude], { animate: true, duration: 0.3 });
          },
        });
        // Final fix — kuchliroq flyTo + zoom + haptic.
        map.flyTo([loc.latitude, loc.longitude], 17, { duration: 0.6 });
        userTouchedMap = true;  // explicit chaqiruvdan keyin fon GPS ortiqcha
        hapticImpact("light");
        hintEl.textContent = `✅ Aniqlik: ${Math.round(loc.accuracy || 0)}m`;
        setTimeout(() => { hintEl.textContent = originalHint; }, 3000);
      } catch (e) {
        hintEl.textContent = e.message || "Joylashuv olinmadi.";
        setTimeout(() => { hintEl.textContent = originalHint; }, 6000);
      } finally {
        locateBtn.disabled = false;
        locateBtn.textContent = originalText;
      }
    });
  });
}
