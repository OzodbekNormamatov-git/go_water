// Takror buyurtma — o'tgan buyurtma itemlarini JORIY katalogga moslash.
//
// Bitta sof funksiya (yon ta'sirsiz, oson test). Operator "Takrorlash"
// bosganda eski buyurtma itemlarini hozirgi mahsulotlar bilan solishtiradi:
//   * Endi mavjud bo'lmagan mahsulotlar chiqarib tashlanadi (removed)
//   * Narx joriy narxdan olinadi (eski snapshot emas)
//   * Miqdor joriy `min_quantity` ga ko'tariladi (server item_below_minimum
//     bilan rad etmasligi uchun)
//
// Eslatma: mijoz Mini App'idagi `webapp/static/js/views/reorder.js` ham xuddi
// shu mantiqdan foydalanadi (alohida bundle bo'lgani uchun u yerda ham nusxasi
// bor) — ikkalasini o'zgartirganda sinxron saqlang.

export function resolveReorderItems(orderItems, products) {
  const productMap = new Map((products || []).map((p) => [p.id, p]));
  const resolved = (orderItems || []).map((it) => {
    const p = productMap.get(it.food_id);
    const available = !!p && p.is_available !== false && !p.deleted_at;
    const minQ = available ? Math.max(1, Number(p.min_quantity || 1)) : 1;
    const origQty = Number(it.quantity) || 0;
    const quantity = available ? Math.max(origQty, minQ) : origQty;
    return {
      food_id: it.food_id,
      name: available ? p.name : it.food_name,
      quantity,
      available,
      adjusted: available && quantity !== origQty,
      price: available ? Number(p.price) : Number(it.unit_price || 0),
    };
  });
  return {
    items: resolved,
    available: resolved.filter((r) => r.available),
    removed: resolved.filter((r) => !r.available),
    adjusted: resolved.filter((r) => r.available && r.adjusted),
  };
}
