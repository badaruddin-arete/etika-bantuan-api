"""Konfigurasi kebijakan, dimuat dari lingkungan proses dan berkas .env.

Angka kebijakan sengaja tidak punya nilai bawaan di kode. Batas kemiskinan dan
ambang kuota adalah keputusan kebijakan yang harus bisa ditinjau dan diubah
tanpa menyentuh kode; nilai bawaan tersembunyi akan membuat sebuah deployment
diam-diam memakai angka yang tidak pernah disetujui siapa pun.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, fields
from pathlib import Path

from dotenv import load_dotenv

# Jalur absolut agar .env yang sama ditemukan dari direktori kerja mana pun
# (uvicorn, pytest, IDE).
ENV_PATH = Path(__file__).resolve().parent / ".env"


class KonfigurasiTidakValid(ValueError):
    pass


def _ambil_angka(nama: str) -> float:
    mentah = os.environ.get(nama)
    if mentah is None or not mentah.strip():
        raise KonfigurasiTidakValid(
            f"Variabel {nama} belum diatur. Salin .env.example menjadi .env lalu isi nilainya."
        )
    try:
        nilai = float(mentah)
    except ValueError:
        raise KonfigurasiTidakValid(f"{nama} harus berupa angka, diterima {mentah!r}.") from None
    # float() menerima "nan" dan "inf"; keduanya meracuni setiap perbandingan
    # skor tanpa menimbulkan galat, jadi ditolak di pintu masuk.
    if not math.isfinite(nilai):
        raise KonfigurasiTidakValid(f"{nama} harus berupa angka terhingga, diterima {mentah!r}.")
    return nilai


@dataclass(frozen=True)
class KonfigurasiEtika:
    batas_kemiskinan: float
    kebutuhan_dasar_per_tanggungan: float
    pengali_kesehatan_kronis: float
    skala_utilitas: float
    bobot_utilitas: float
    bobot_ml: float
    ambang_kuota: float
    nilai_bantuan_per_pemohon: float

    def __post_init__(self) -> None:
        # Validasi ada di dataclass, bukan hanya di pemuat env, supaya nilai
        # yang dibuat lewat kode (uji, skrip) melewati pagar yang sama.
        for nama in (
            "batas_kemiskinan",
            "kebutuhan_dasar_per_tanggungan",
            "skala_utilitas",
            "nilai_bantuan_per_pemohon",
        ):
            if getattr(self, nama) <= 0:
                raise KonfigurasiTidakValid(f"{nama} harus lebih besar dari 0.")
        if self.pengali_kesehatan_kronis < 1.0:
            raise KonfigurasiTidakValid(
                "pengali_kesehatan_kronis tidak boleh di bawah 1.0; penyakit kronis "
                "tidak boleh menurunkan kebutuhan."
            )
        if not 0.0 < self.ambang_kuota <= 100.0:
            raise KonfigurasiTidakValid("ambang_kuota harus di rentang (0, 100].")
        if not (0.0 <= self.bobot_utilitas <= 1.0 and 0.0 <= self.bobot_ml <= 1.0):
            raise KonfigurasiTidakValid("bobot_utilitas dan bobot_ml harus di rentang [0, 1].")
        if abs(self.bobot_utilitas + self.bobot_ml - 1.0) > 1e-9:
            raise KonfigurasiTidakValid("bobot_utilitas + bobot_ml harus berjumlah 1.0")

        # Pagar etika: pengaruh maksimum ML pada skor gabungan adalah bobot_ml x 100.
        # Bila angka itu mencapai ambang, skor ML yang keliru saja sudah cukup
        # meloloskan pemohon yang tidak butuh bantuan, dan kalkulus kebutuhan
        # tidak lagi berfungsi sebagai penyaring kesalahan model. Konfigurasi
        # seperti itu ditolak saat startup, bukan ditemukan saat audit.
        if self.bobot_ml * 100.0 >= self.ambang_kuota:
            raise KonfigurasiTidakValid(
                f"bobot_ml x 100 ({self.bobot_ml * 100.0:.1f}) harus lebih kecil dari "
                f"ambang_kuota ({self.ambang_kuota:.1f}); jika tidak, skor ML saja "
                f"dapat meloloskan pemohon yang tidak membutuhkan bantuan."
            )

    @classmethod
    def dari_env(cls) -> KonfigurasiEtika:
        # override=False: variabel yang sudah diatur proses (CI, container, uji)
        # menang atas berkas, sehingga .env hanya menjadi cadangan lokal.
        load_dotenv(ENV_PATH, override=False)
        return cls(**{f.name: _ambil_angka(f.name.upper()) for f in fields(cls)})
