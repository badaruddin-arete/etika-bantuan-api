"""Alokasi anggaran lintas pemohon.

Perangkingan memakai tier, bukan satu skor tunggal, karena kewajiban Kant tidak
boleh dapat dikalahkan oleh skor setinggi apa pun. Menyisipkan "bonus Kant" ke
dalam skor akan menciptakan angka ajaib yang suatu hari bisa dilampaui.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from models.ethical_engine import MesinEtika
from models.formatting import rupiah
from schemas import (
    BatchInput,
    HasilAnalisis,
    HasilBatch,
    ItemAlokasi,
    RingkasanBatch,
    StatusAlokasi,
    StatusKelayakan,
)

_TIER_KANT = 0
_TIER_LOLOS_AMBANG = 1
_TIER_DI_BAWAH_AMBANG = 2


@dataclass
class _Kandidat:
    indeks: int
    nama: str
    pendapatan: float
    hasil: HasilAnalisis
    wajib_kant: bool
    skor: float

    @property
    def tier(self) -> int:
        if self.wajib_kant:
            return _TIER_KANT
        bentham = self.hasil.perbandingan_bentham_vs_kant.bentham
        return _TIER_LOLOS_AMBANG if bentham.status == StatusKelayakan.LAYAK else _TIER_DI_BAWAH_AMBANG

    def kunci_urut(self) -> tuple:
        # Seri skor dipecahkan oleh pendapatan terendah (yang lebih membutuhkan),
        # lalu oleh urutan input agar hasilnya deterministik dan tidak bergantung
        # pada kestabilan sort atau urutan kiriman klien.
        return (self.tier, -self.skor, self.pendapatan, self.indeks)


class PengalokasiAnggaran:
    def __init__(self, mesin: MesinEtika) -> None:
        self.mesin = mesin

    def alokasikan(self, permintaan: BatchInput) -> HasilBatch:
        k = self.mesin.k
        besaran = permintaan.besaran_bantuan_per_pemohon or k.nilai_bantuan_per_pemohon

        # Bantuan seragam membuat urutan peringkat sama dengan urutan pendanaan.
        # Besaran bervariasi mengubah masalah menjadi knapsack, yang bisa
        # mengorbankan pemohon berperingkat tinggi demi mengisi sisa dana.
        # Epsilon menahan galat floating point (mis. 0,3 / 0,1 = 2,9999...).
        kapasitas = max(0, math.floor(permintaan.kuota_anggaran_maksimal / besaran + 1e-9))

        kandidat: list[_Kandidat] = []
        for i, p in enumerate(permintaan.pemohon):
            hasil = self.mesin.analisis(p)
            perbandingan = hasil.perbandingan_bentham_vs_kant
            kandidat.append(
                _Kandidat(
                    indeks=i,
                    nama=p.nama,
                    pendapatan=p.pendapatan_bulanan,
                    hasil=hasil,
                    wajib_kant=perbandingan.kant.aturan_terpicu,
                    skor=perbandingan.bentham.skor_gabungan,
                )
            )

        kandidat.sort(key=_Kandidat.kunci_urut)

        sisa_kapasitas = kapasitas
        item: list[ItemAlokasi] = []
        for peringkat, c in enumerate(kandidat, start=1):
            # Tier terbawah tidak didanai walau anggaran bersisa: ambang yang
            # sama dengan /analisis menjaga agar satu pemohon tidak mendapat
            # jawaban berbeda hanya karena dikirim lewat endpoint lain.
            if c.tier == _TIER_DI_BAWAH_AMBANG:
                status = StatusAlokasi.TIDAK_LAYAK
            elif sisa_kapasitas > 0:
                status = StatusAlokasi.DITERIMA
                sisa_kapasitas -= 1
            else:
                status = StatusAlokasi.ANGGARAN_HABIS

            item.append(
                ItemAlokasi(
                    peringkat=peringkat,
                    indeks_input=c.indeks,
                    nama=c.nama,
                    wajib_kant=c.wajib_kant,
                    skor_gabungan=c.skor,
                    status_alokasi=status,
                    dana_dialokasikan=besaran if status == StatusAlokasi.DITERIMA else 0.0,
                    level_bias=c.hasil.skor_potensi_bias.level,
                    penjelasan_alokasi=self._penjelasan(c, status, peringkat, k.ambang_kuota),
                )
            )

        return HasilBatch(
            ringkasan=self._ringkasan(permintaan, besaran, kapasitas, item),
            alokasi=item,
        )

    @staticmethod
    def _ringkasan(
        permintaan: BatchInput,
        besaran: float,
        kapasitas: int,
        item: list[ItemAlokasi],
    ) -> RingkasanBatch:
        diterima = [x for x in item if x.status_alokasi == StatusAlokasi.DITERIMA]
        wajib = [x for x in item if x.wajib_kant]
        wajib_tak_terdanai = [
            x for x in wajib if x.status_alokasi == StatusAlokasi.ANGGARAN_HABIS
        ]
        layak_tak_terdanai = [
            x
            for x in item
            if x.status_alokasi == StatusAlokasi.ANGGARAN_HABIS and not x.wajib_kant
        ]
        total = len(diterima) * besaran

        # Kekurangan dana bagi pemohon wajib Kant bukan hasil normal melainkan
        # kegagalan kebijakan, jadi dilaporkan sebagai peringatan eksplisit
        # lengkap dengan nilai kekurangannya agar bisa langsung ditindaklanjuti.
        peringatan: list[str] = []
        if kapasitas == 0:
            peringatan.append(
                f"Anggaran {rupiah(permintaan.kuota_anggaran_maksimal)} lebih kecil dari "
                f"satu bantuan ({rupiah(besaran)}); tidak ada pemohon yang dapat didanai."
            )
        if wajib_tak_terdanai:
            tambahan = len(wajib_tak_terdanai) * besaran
            peringatan.append(
                f"KEWAJIBAN KANT TIDAK TERPENUHI: {len(wajib_tak_terdanai)} pemohon yang wajib "
                f"dibantu tidak terdanai karena anggaran habis. Tambahan minimal "
                f"{rupiah(tambahan)} diperlukan. Urutan di antara sesama pemohon wajib "
                f"hanya berdasar skor, bukan prinsip moral, sehingga sebaiknya "
                f"ditinjau manusia."
            )
        if layak_tak_terdanai:
            peringatan.append(
                f"{len(layak_tak_terdanai)} pemohon lolos ambang kuota tetapi tidak terdanai "
                f"karena anggaran habis."
            )

        return RingkasanBatch(
            total_pemohon=len(item),
            kuota_anggaran_maksimal=permintaan.kuota_anggaran_maksimal,
            besaran_bantuan_per_pemohon=besaran,
            kapasitas_penerima=kapasitas,
            jumlah_diterima=len(diterima),
            total_dialokasikan=total,
            sisa_anggaran=round(permintaan.kuota_anggaran_maksimal - total, 2),
            jumlah_wajib_kant=len(wajib),
            wajib_kant_diterima=len(wajib) - len(wajib_tak_terdanai),
            wajib_kant_tidak_terdanai=len(wajib_tak_terdanai),
            peringatan=peringatan,
        )

    @staticmethod
    def _penjelasan(
        c: _Kandidat, status: StatusAlokasi, peringkat: int, ambang: float
    ) -> str:
        if status == StatusAlokasi.DITERIMA and c.wajib_kant:
            return (
                f"Prioritas mutlak Kant: didanai lebih dulu terlepas dari skor "
                f"gabungan {c.skor:.1f}."
            )
        if status == StatusAlokasi.DITERIMA:
            return (
                f"Skor gabungan {c.skor:.1f} >= ambang {ambang:.1f} dan masuk "
                f"kapasitas anggaran pada peringkat {peringkat}."
            )
        if status == StatusAlokasi.ANGGARAN_HABIS and c.wajib_kant:
            return (
                "PERINGATAN: memenuhi syarat absolut Kant tetapi anggaran habis. "
                "Perlu tambahan dana atau tinjauan manusia."
            )
        if status == StatusAlokasi.ANGGARAN_HABIS:
            return f"Skor gabungan {c.skor:.1f} lolos ambang, tetapi anggaran habis."
        return (
            f"Skor gabungan {c.skor:.1f} di bawah ambang {ambang:.1f} dan tidak "
            f"memenuhi syarat absolut Kant."
        )
