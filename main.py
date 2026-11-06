"""Titik masuk HTTP.

Konfigurasi dan mesin dibuat sekali saat impor. Konfigurasi immutable dan mesin
tidak menyimpan state per request, sehingga satu instans aman dipakai bersama
semua worker. Konfigurasi yang tidak valid menggagalkan startup (fail fast);
lebih baik server tidak naik daripada baru ketahuan salah saat keputusan
pertama tentang seseorang dibuat.
"""

from dataclasses import asdict

from fastapi import FastAPI

from config import KonfigurasiEtika
from models.allocator import PengalokasiAnggaran
from models.ethical_engine import MesinEtika
from schemas import BatchInput, HasilAnalisis, HasilBatch, PemohonInput

konfigurasi = KonfigurasiEtika.dari_env()
mesin = MesinEtika(konfigurasi)
pengalokasi = PengalokasiAnggaran(mesin)

app = FastAPI(
    title="API Etika Seleksi Bantuan Sosial",
    version="1.0.0",
    description=(
        "Menganalisis keputusan AI dalam seleksi bantuan sosial dengan dua "
        "kerangka etika: Utilitarianisme (Bentham) dan Deontologi (Kant). "
        "Kewajiban Kant mendahului kalkulus kemanfaatan Bentham."
    ),
)


@app.get("/", tags=["info"], summary="Ringkasan layanan")
def root() -> dict:
    return {
        "layanan": "API Etika Seleksi Bantuan Sosial",
        "endpoint": {
            "POST /analisis": "analisis satu pemohon",
            "POST /analisis-batch": "peringkat dan alokasi anggaran untuk banyak pemohon",
            "GET /konfigurasi": "parameter kebijakan",
        },
        "dokumentasi": "/docs",
    }


@app.get("/health", tags=["info"], summary="Pemeriksaan kesehatan layanan")
def health() -> dict:
    return {"status": "ok"}


# Parameter kebijakan dibuka tanpa autentikasi dengan sengaja: pihak terdampak
# berhak mengetahui angka di balik keputusan tentang mereka. Berkas konfigurasi
# hanya berisi parameter kebijakan, tidak ada rahasia.
@app.get("/konfigurasi", tags=["transparansi"], summary="Parameter kebijakan yang sedang berlaku")
def lihat_konfigurasi() -> dict:
    return asdict(konfigurasi)


@app.post(
    "/analisis",
    response_model=HasilAnalisis,
    tags=["analisis"],
    summary="Analisis etika satu pemohon",
)
def analisis(pemohon: PemohonInput) -> HasilAnalisis:
    return mesin.analisis(pemohon)


@app.post(
    "/analisis-batch",
    response_model=HasilBatch,
    tags=["analisis"],
    summary="Peringkat dan alokasi anggaran untuk banyak pemohon",
    description=(
        "Pemohon yang memenuhi syarat absolut Kant didanai lebih dulu, berapa pun "
        "skornya. Sisa anggaran dibagikan menurut skor gabungan Bentham + ML "
        "tertinggi di antara yang lolos ambang kuota. Bila dana tidak cukup untuk "
        "semua pemohon wajib, respons memuat peringatan beserta kebutuhan dana tambahan."
    ),
)
def analisis_batch(permintaan: BatchInput) -> HasilBatch:
    return pengalokasi.alokasikan(permintaan)
