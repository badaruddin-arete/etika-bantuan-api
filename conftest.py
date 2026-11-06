"""Menyematkan konfigurasi uji dari .env.example sebelum aplikasi diimpor.

Angka harapan di uji (mis. batas kemiskinan 600.000) bergantung pada parameter
kebijakan. Bila uji membaca .env lokal, seorang pengembang yang mengubah
kebijakan di mesinnya akan mematahkan uji tanpa ada bug. .env.example ikut
di-commit, jadi menjadi acuan tunggal yang sama di mesin mana pun dan di CI.
"""

import os
from pathlib import Path

from dotenv import dotenv_values

_templat = Path(__file__).resolve().parent / ".env.example"
os.environ.update({k: v for k, v in dotenv_values(_templat).items() if v is not None})
