import { api, ApiError } from "../api.js";
import { session } from "../state.js";
import { normalizePhone } from "../format.js";
import { hideBackButton, hideMainButton } from "../telegram.js";
import { toast } from "../toast.js";
import { reset } from "../router.js";
import { showCTA, hideCTA, setCTALoading } from "../cta.js";

export function renderRegistration(root) {
  document.getElementById("screen-title").textContent = "Ro'yxatdan o'tish";
  hideBackButton();
  hideMainButton();

  const me = session.me || {};
  const presetName = me.tg_first_name
    ? `${me.tg_first_name} ${me.tg_last_name || ""}`.trim()
    : "";

  root.innerHTML = `
    <div class="form">
      <p class="muted" style="margin-top:0">Buyurtma berish uchun bir martalik ro'yxatdan o'ting.</p>

      <label class="label" for="r-name">Ismingiz</label>
      <input class="input" id="r-name" type="text" placeholder="Ism Familiya" autocomplete="name" />

      <label class="label" for="r-phone">Telefon raqam</label>
      <input class="input" id="r-phone" type="tel" placeholder="+998 90 123 45 67" autocomplete="tel" inputmode="tel" />

      <p class="muted" style="font-size:12px;margin-top:8px">Telefon yetkazib berish uchun ishlatiladi.</p>
    </div>
  `;

  const nameInput = root.querySelector("#r-name");
  const phoneInput = root.querySelector("#r-phone");
  nameInput.value = presetName;
  if (me.phone_number) phoneInput.value = me.phone_number;

  let busy = false;
  const submit = async () => {
    if (busy) return;
    const full_name = nameInput.value.trim();
    const phone_number = normalizePhone(phoneInput.value);
    if (full_name.length < 2) return toast("Ismni to'liq kiriting.", { error: true });
    if (!phone_number) return toast("Telefon raqam noto'g'ri. Masalan: 901234567", { error: true });
    phoneInput.value = phone_number;

    busy = true;
    setCTALoading(true);
    try {
      const updated = await api.register(full_name, phone_number);
      session.set(updated);
      toast("Tayyor!");
      reset("home");
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Xatolik";
      toast(msg, { error: true });
    } finally {
      busy = false;
      setCTALoading(false);
    }
  };

  showCTA("Davom etish", submit, { variant: "secondary" });

  return () => hideCTA();
}
