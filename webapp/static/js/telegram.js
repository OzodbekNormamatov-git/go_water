// Telegram WebApp SDK ustidan o'rama (wrapper).
// Telegram bo'lmagan brauzerda ham fallback qilamiz (developer testlash uchun).

const tg = window.Telegram && window.Telegram.WebApp;

export const isTelegram = !!tg;

export const initData = tg ? tg.initData : "";

export function ready() {
  if (tg) {
    try {
      tg.ready();
      tg.expand();
      // Disable swipe-down to close (yangi versiyalarda)
      if (typeof tg.disableVerticalSwipes === "function") {
        tg.disableVerticalSwipes();
      }
      // Telegram tema o'zgarsa — darhol ergashamiz (foydalanuvchi telefonda
      // light/dark almashtirsa, Mini App ham yangilanadi).
      if (typeof tg.onEvent === "function") {
        tg.onEvent("themeChanged", () => applyTheme());
      }
    } catch (e) {
      console.warn("Telegram.ready failed", e);
    }
  }
}

// Mijoz Mini App'i Telegram'ning rejimiga ergashadi:
//   * Telegram dark   → body.theme-dark qo'shiladi, dark tokenlar amal qiladi
//   * Telegram light  → body.theme-dark olib tashlanadi, light default
// Telegram'siz (developer brauzer) — default light.
//
// Brand ranglari (--brand-primary, --brand-success va h.k.) ikkala rejimda
// bir xil — faqat surface/text/border tokenlari o'zgaradi.
const COLORS = {
  light: {
    header: "#FFFFFF",
    background: "#F4F8FB",  // body bg-tint bilan moslangan
    bottomBar: "#FFFFFF",
    meta: "#FFFFFF",
  },
  dark: {
    header: "#131C25",
    background: "#0F1419",
    bottomBar: "#131C25",
    meta: "#0F1419",
  },
};

export function applyTheme() {
  const scheme = (tg && tg.colorScheme) === "dark" ? "dark" : "light";
  const palette = COLORS[scheme];

  document.body.classList.toggle("theme-dark", scheme === "dark");
  document.documentElement.style.colorScheme = scheme;

  // <meta name="theme-color"> — brauzer/Telegram top-bar uchun
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", palette.meta);

  // Telegram WebApp ramkasi — header + bg + (yangi versiya) pastki bar
  if (tg) {
    if (typeof tg.setHeaderColor === "function") {
      try { tg.setHeaderColor(palette.header); } catch (_) {}
    }
    if (typeof tg.setBackgroundColor === "function") {
      try { tg.setBackgroundColor(palette.background); } catch (_) {}
    }
    if (typeof tg.setBottomBarColor === "function") {
      try { tg.setBottomBarColor(palette.bottomBar); } catch (_) {}
    }
  }
}

// ---------------------- MainButton ----------------------
// Asosiy CTA tugmasi `cta.js` moduli orqali boshqariladi; bu yerda faqat
// view almashganda Telegram MainButton'ni yashirish kerak.

let _mainHandler = () => {};

export function hideMainButton() {
  if (!tg || !tg.MainButton) return;
  tg.MainButton.hide();
  tg.MainButton.hideProgress();
  tg.MainButton.offClick(_mainHandler);
}

// ---------------------- BackButton ----------------------

let _backHandler = null;
export function showBackButton(onClick) {
  if (!tg || !tg.BackButton) return;
  if (_backHandler) tg.BackButton.offClick(_backHandler);
  _backHandler = () => { try { onClick(); } catch (e) { console.error(e); } };
  tg.BackButton.onClick(_backHandler);
  tg.BackButton.show();
}

export function hideBackButton() {
  if (!tg || !tg.BackButton) return;
  if (_backHandler) tg.BackButton.offClick(_backHandler);
  _backHandler = null;
  tg.BackButton.hide();
}

// ---------------------- Haptic / Misc ----------------------

export function hapticImpact(style = "light") {
  if (!tg || !tg.HapticFeedback) return;
  try { tg.HapticFeedback.impactOccurred(style); } catch (_) {}
}

export function hapticNotification(type = "success") {
  if (!tg || !tg.HapticFeedback) return;
  try { tg.HapticFeedback.notificationOccurred(type); } catch (_) {}
}

export function showConfirm(message) {
  if (tg && tg.showConfirm) {
    return new Promise((res) => tg.showConfirm(message, (ok) => res(!!ok)));
  }
  return Promise.resolve(confirm(message));
}

// ---------------------- Location request ----------------------
//
// Strategiya — progressive accuracy via watchPosition (Uber/Wolt namunasi):
//   • `navigator.geolocation.watchPosition` ishlaydi va aniqlik yaxshilanishini
//     kuzatadi. `accuracy <= desiredAccuracy` bo'lganda darhol to'xtaydi —
//     batareya tejaladi.
//   • Birinchi fix odatda 200-500m (Wi-Fi/Network), keyin 3-8s ichida GPS
//     chip'i ulanib 10-50m gacha tushadi. Bir martalik `getCurrentPosition`
//     bilan farqi: progressive yaxshilanishni ko'ramiz.
//   • Telegram WebView (Android: Chromium, iOS: WKWebView) ikkalasi ham
//     watchPosition'ni qo'llab-quvvatlaydi.
//   • `Telegram.WebApp.LocationManager` ishlatmaymiz: Android'da stale kesh
//     bug'i (issue #56), Desktop'da yo'q. `navigator.geolocation` har joyda
//     ishlaydi va biz unga to'liq nazoratga egamiz.
//   • Map picker — manzilning yakuniy manbai. GPS faqat boshlang'ich
//     pin pozitsiyasi uchun maslahat — hech qachon bloklamaydi.

// Diagnostika logi — production'da o'chirilgan (faqat opt-in).
//
// Enable qilish: brauzer konsolida `localStorage.gps_debug = "1"` yozing va
// sahifani qayta yuklang. Default'da `console.log` ham, server fetch ham yo'q
// (production'da shovqin va bandwidth iste'mol qilmasin).
const _GPS_DEBUG = (() => {
  try { return localStorage.getItem("gps_debug") === "1"; }
  catch (_) { return false; }
})();

function _glog(t0, msg, extra) {
  if (!_GPS_DEBUG) return;
  const dt = Date.now() - t0;
  try { console.log(`[GPS T+${dt}ms] ${msg}`, extra || ""); } catch (_) {}
  try {
    fetch("/api/debug/log", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tag: "gps", msg, t_ms: dt, extra: extra || null }),
      keepalive: true,
    }).catch(() => {});
  } catch (_) {}
}

// In-flight dedup — qaytma takroriy klikda yangi GPS sessiyasi ochmaymiz.
let _inflightLocation = null;

// Default'lar — rejim bo'yicha.
const _DEFAULTS = {
  // Fon: xarita ochilganda silliq pin uchun. Tez bo'lishi muhim, sifat ikkinchi.
  background: { desiredAccuracy: 100, maxWait: 6000 },
  // Explicit: foydalanuvchi "Mening joyim" tugmasini bosgan — sifatli fix.
  explicit:   { desiredAccuracy: 30,  maxWait: 12000 },
};

/**
 * Joylashuvni `navigator.geolocation.watchPosition` orqali progressive ravishda so'raydi.
 *
 * Aniqlik yaxshilanishini kuzatib boradi — `desiredAccuracy` ga yetganda darhol
 * resolve qiladi va `clearWatch` chaqiradi (batareya tejash). `maxWait` davomida
 * threshold'ga yetilmasa — hozircha mavjud eng yaxshi fix bilan resolve qiladi.
 *
 * Options:
 *   - background: true   — fon GPS (xarita ochilganda, foydalanuvchi kutmaydi).
 *                           Default: 100m, maxWait 6s.
 *   - background: false  — explicit ("Mening joyim" tugmasi). Default: 30m, 12s.
 *   - desiredAccuracy    — override (meter). Past qiymat — sifatliroq fix,
 *                           lekin maxWait ga uchrash ehtimoli yuqori.
 *   - maxWait            — override (ms). Threshold yetilmasa, shu vaqtdan
 *                           keyin eng yaxshi mavjud fix qaytariladi.
 *   - onProgress         — (fix) => void. Har oraliq yaxshilanishda chaqiriladi.
 *                           UI accuracy progress'ni ko'rsatish uchun (pin'ni
 *                           silliq ko'chirish, hint matnini yangilash).
 *
 * Qaytaradi: Promise<{ latitude, longitude, accuracy }> | reject(Error)
 *   - resolve: threshold yetilgan yoki maxWait tugab, `bestFix` mavjud
 *   - reject:  permission denied / no geolocation / hech qanday fix kelmadi
 */
export function requestLocation({
  background = false,
  desiredAccuracy,
  maxWait,
  onProgress,
} = {}) {
  if (_inflightLocation) return _inflightLocation;

  const t0 = Date.now();
  const cfg = background ? _DEFAULTS.background : _DEFAULTS.explicit;
  const target = Number.isFinite(desiredAccuracy) ? desiredAccuracy : cfg.desiredAccuracy;
  const limit  = Number.isFinite(maxWait)         ? maxWait         : cfg.maxWait;

  _glog(t0, background ? "watch.start (background)" : "watch.start (explicit)", {
    target_m: target, max_ms: limit,
  });

  _inflightLocation = new Promise((resolve, reject) => {
    if (!navigator.geolocation || typeof navigator.geolocation.watchPosition !== "function") {
      _glog(t0, "navigator.geolocation.watchPosition yo'q");
      return reject(new Error("Bu qurilma joylashuvni qo'llab-quvvatlamaydi. Xaritadan tanlang."));
    }

    let watchId = null;
    let timerId = null;
    let bestFix = null;
    let settled = false;

    const stop = () => {
      if (watchId !== null) {
        try { navigator.geolocation.clearWatch(watchId); } catch (_) {}
        watchId = null;
      }
      if (timerId !== null) {
        clearTimeout(timerId);
        timerId = null;
      }
    };

    const succeed = (fix, reason) => {
      if (settled) return;
      settled = true;
      stop();
      _glog(t0, "SUCCESS " + reason, { accuracy_m: Math.round(fix.accuracy || 0) });
      resolve(fix);
    };

    const fail = (msg, extra) => {
      if (settled) return;
      settled = true;
      stop();
      _glog(t0, "FAIL", extra || { msg });
      reject(new Error(msg));
    };

    navigator.geolocation.watchPosition(
      (pos) => {
        if (settled) return;
        const fix = {
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
          accuracy: pos.coords.accuracy,
        };
        // Eng yaxshi fix'ni saqlab boramiz — maxWait urganda shu qaytariladi.
        if (!bestFix || (Number.isFinite(fix.accuracy) && fix.accuracy < bestFix.accuracy)) {
          bestFix = fix;
        }
        _glog(t0, "fix", { accuracy_m: Math.round(fix.accuracy || 0) });
        // UI'ga oraliq progress — pin silliq ko'chsin, hint yangilansin.
        if (typeof onProgress === "function") {
          try { onProgress(fix); } catch (_) { /* UI xato GPS'ni to'xtatmasin */ }
        }
        // Threshold yetildi — darhol to'xtatamiz (batareya himoya).
        if (Number.isFinite(fix.accuracy) && fix.accuracy <= target) {
          succeed(fix, "threshold");
        }
      },
      (err) => {
        const code = err && err.code;
        // PERMISSION_DENIED / POSITION_UNAVAILABLE — qaytarib bo'lmaydi.
        // Lekin agar shu paytgacha bestFix kelgan bo'lsa, undan foydalanamiz.
        if (bestFix) {
          succeed(bestFix, "fallback-after-error");
          return;
        }
        let msg;
        switch (code) {
          case 1: msg = "Joylashuvga ruxsat berilmadi. Telegram'da Allow bering yoki xaritadan tanlang."; break;
          case 2: msg = "Joylashuv aniqlanmadi. Xaritadan tanlang."; break;
          case 3: msg = "Joylashuv vaqti tugadi. Xaritadan tanlang."; break;
          default: msg = "Joylashuv olinmadi. Xaritadan tanlang.";
        }
        fail(msg, { code, raw: err && err.message });
      },
      {
        // enableHighAccuracy:true — GPS chip yoqiladi. watchPosition bilan
        // batareya muammosi yo'q: threshold yetganda darhol clearWatch.
        enableHighAccuracy: true,
        // timeout — har bitta fix uchun emas, bizning maxWait alohida boshqaradi.
        timeout: limit,
        // explicit'da kesh ishlatmaymiz (foydalanuvchi yangi fix kutadi);
        // background'da 60s kesh OK (xarita tez ochilsin).
        maximumAge: background ? 60_000 : 0,
      },
    );

    // Sessiya umumiy timeout — bestFix bo'lsa qaytaramiz, yo'q bo'lsa reject.
    timerId = setTimeout(() => {
      if (settled) return;
      if (bestFix) {
        succeed(bestFix, "maxwait");
      } else {
        fail("Joylashuv vaqti tugadi. Xaritadan tanlang.", { reason: "maxwait-no-fix" });
      }
    }, limit);
  });

  _inflightLocation.finally(() => { _inflightLocation = null; });
  return _inflightLocation;
}
