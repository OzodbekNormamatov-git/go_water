// Klassik pagination — `‹ [N] ›` ko'rinishida.
//
// Foydalanish:
//   import { renderPagination, bindPagination } from "../pagination.js";
//
//   container.innerHTML = renderPagination({
//     page: currentPage,        // 1-based (1, 2, 3, ...)
//     pageSize: PAGE_SIZE,
//     total: total,
//     showInfo: true,           // "21–40 / 56" matnini ko'rsatish
//   });
//   bindPagination(container, (newPage) => {
//     currentPage = newPage;
//     loadPage();
//   });

import { fmtCount } from "./format.js";

/**
 * Pagination HTML qaytaradi (yoki bo'sh string — agar 1 ta sahifa bo'lsa).
 *
 * @param {Object} opts
 * @param {number} opts.page      — joriy sahifa (1-based)
 * @param {number} opts.pageSize  — har sahifadagi elementlar soni
 * @param {number} opts.total     — jami elementlar soni
 * @param {boolean} [opts.showInfo=true] — "21–40 / 56" matnini ko'rsatish
 * @returns {string} HTML
 */
export function renderPagination({ page, pageSize, total, showInfo = true }) {
  const pages = Math.max(1, Math.ceil(Number(total || 0) / Number(pageSize || 1)));
  const cur = Math.min(Math.max(1, Number(page) || 1), pages);
  if (pages <= 1) return "";  // 1 sahifa bo'lsa pagination kerak emas

  const from = (cur - 1) * pageSize + 1;
  const to = Math.min(cur * pageSize, total);

  const prevDisabled = cur <= 1;
  const nextDisabled = cur >= pages;

  // ‹ — U+2039 (SINGLE LEFT-POINTING ANGLE QUOTATION MARK)
  // › — U+203A (SINGLE RIGHT-POINTING ANGLE QUOTATION MARK)
  // (oddiy < > emas — typography'siroq ko'rinadi)
  return `
    <div class="pagination" role="navigation" aria-label="Sahifalash">
      <button
        type="button"
        class="pagination__btn"
        data-page="${cur - 1}"
        aria-label="Oldingi sahifa"
        ${prevDisabled ? "disabled" : ""}
      >‹</button>
      <span class="pagination__current" aria-current="page">${cur}</span>
      <button
        type="button"
        class="pagination__btn"
        data-page="${cur + 1}"
        aria-label="Keyingi sahifa"
        ${nextDisabled ? "disabled" : ""}
      >›</button>
      ${showInfo ? `<span class="pagination__info">${fmtCount(from)}–${fmtCount(to)} / ${fmtCount(total)}</span>` : ""}
    </div>
  `;
}

/**
 * Pagination tugmalariga click handler ulaydi.
 * `container.innerHTML` qayta render qilinganda — yangi handlerlar ulanadi.
 *
 * @param {HTMLElement} container — `renderPagination` natijasi joylashgan element
 * @param {(newPage: number) => void} onPageChange
 */
export function bindPagination(container, onPageChange) {
  container.querySelectorAll(".pagination__btn[data-page]").forEach((btn) => {
    if (btn.disabled) return;
    btn.addEventListener("click", () => {
      const newPage = Number(btn.dataset.page);
      if (Number.isFinite(newPage) && newPage >= 1) {
        onPageChange(newPage);
      }
    });
  });
}
