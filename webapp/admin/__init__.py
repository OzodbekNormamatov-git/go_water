"""Admin web panel — alohida API + sahifalar.

Autentifikatsiya: foydalanuvchi Mini App'i bilan bir xil — Telegram WebApp
`initData` HMAC tekshiruvi (`webapp/auth.py:verify_init_data`, admin bot tokeni
bilan), ustiga rol tekshiruvi (`webapp/admin/auth.py:role_of` — admin
ADMIN_TELEGRAM_IDS whitelist'idan, operator `operators` jadvalidagi AKTIV
qatordan). Hech qanday JWT/cookie/magic-link ishlatilmaydi.
"""
