"""Uji mesin etika, alokasi batch, dan pemuatan konfigurasi.

Angka harapan diturunkan dari .env.example (lihat conftest.py), bukan dari
.env lokal. Jalankan dengan: pytest -v
"""

from dataclasses import fields, replace

import pytest
from fastapi.testclient import TestClient

import config
from config import KonfigurasiEtika, KonfigurasiTidakValid
from main import app

client = TestClient(app)


def buat(nama, pendapatan, tanggungan, kronis, ml):
    return {
        "nama": nama,
        "pendapatan_bulanan": pendapatan,
        "jumlah_tanggungan": tanggungan,
        "kondisi_kesehatan_kronis": kronis,
        "skor_kelayakan_ml": ml,
    }


def analisis(pemohon):
    r = client.post("/analisis", json=pemohon)
    assert r.status_code == 200, r.text
    return r.json()


def batch(pemohon, kuota=4_000_000, besaran=2_000_000):
    r = client.post(
        "/analisis-batch",
        json={
            "kuota_anggaran_maksimal": kuota,
            "besaran_bantuan_per_pemohon": besaran,
            "pemohon": pemohon,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def nama_faktor(hasil):
    return {f["nama"] for f in hasil["skor_potensi_bias"]["faktor"]}


def konfig(**ubah):
    # replace() menjalankan ulang __post_init__, jadi pagar validasi ikut teruji.
    return replace(KonfigurasiEtika.dari_env(), **ubah)


KASUS = {
    # ML keliru memberi 99 pada pemohon kaya: simulasi error atau bias model.
    "A": buat("A", 75_000_000, 1, False, 99),
    # Miskin ekstrem, kronis, lajang, ML rendah: harus diselamatkan Kant.
    "B": buat("B", 150_000, 0, True, 10),
    # Menengah dengan 5 anak: harus diselamatkan kalkulus kebutuhan Bentham.
    "C": buat("C", 3_000_000, 5, False, 45),
    "D": buat("D", 2_500_000, 2, False, 60),
    "E": buat("E", 4_000_000, 1, False, 50),
}

# net utility, U ternormalisasi, skor gabungan, status Bentham, Kant terpicu,
# status akhir, dasar keputusan, level bias
HARAPAN = {
    "A": (-73_400_000, 0.0, 39.6, "TIDAK_LAYAK", False, "TIDAK_LAYAK", "UTILITARIAN_BENTHAM", "SEDANG"),
    "B": (1_050_000, 60.5, 40.3, "TIDAK_LAYAK", True, "LAYAK", "DEONTOLOGI_KANT", "TINGGI"),
    "C": (1_800_000, 68.0, 58.8, "LAYAK", False, "LAYAK", "UTILITARIAN_BENTHAM", "RENDAH"),
    "D": (-100_000, 49.0, 53.4, "LAYAK", False, "LAYAK", "UTILITARIAN_BENTHAM", "RENDAH"),
    "E": (-2_400_000, 26.0, 35.6, "TIDAK_LAYAK", False, "TIDAK_LAYAK", "UTILITARIAN_BENTHAM", "RENDAH"),
}


@pytest.mark.parametrize("kunci", list(KASUS))
def test_kasus_individual(kunci):
    u, u_norm, gabungan, bentham, kant, akhir, dasar, bias = HARAPAN[kunci]
    h = analisis(KASUS[kunci])
    b = h["perbandingan_bentham_vs_kant"]["bentham"]
    k = h["perbandingan_bentham_vs_kant"]["kant"]

    assert b["net_utility_score"] == pytest.approx(u, abs=0.01)
    assert b["skor_utilitas_ternormalisasi"] == pytest.approx(u_norm, abs=0.01)
    assert b["skor_gabungan"] == pytest.approx(gabungan, abs=0.01)
    assert b["status"] == bentham
    assert k["aturan_terpicu"] is kant
    assert h["status_kelayakan_akhir"] == akhir
    assert h["dasar_keputusan"] == dasar
    assert h["skor_potensi_bias"]["level"] == bias


def test_A_error_ml_tidak_bisa_meloloskan_pemohon_kaya():
    h = analisis(KASUS["A"])
    assert h["status_kelayakan_akhir"] == "TIDAK_LAYAK"
    assert "divergensi_ml_vs_kebutuhan" in nama_faktor(h)


@pytest.mark.parametrize("skor_ml", [99, 100])
def test_ml_sendirian_tidak_pernah_cukup(skor_ml):
    h = analisis(buat("Kaya", 500_000_000, 0, False, skor_ml))
    assert h["perbandingan_bentham_vs_kant"]["bentham"]["skor_gabungan"] < 50
    assert h["status_kelayakan_akhir"] == "TIDAK_LAYAK"


def test_B_diselamatkan_kant_meski_bentham_menolak():
    h = analisis(KASUS["B"])
    p = h["perbandingan_bentham_vs_kant"]
    assert p["bentham"]["status"] == "TIDAK_LAYAK"
    assert p["kant"]["status"] == "WAJIB_DIBERIKAN"
    assert p["terjadi_konflik"] is True
    assert {"konflik_bentham_kant", "ml_meremehkan_kondisi_kronis"} <= nama_faktor(h)


def test_C_rumus_tanggungan_plus_satu():
    h = analisis(KASUS["C"])
    b = h["perbandingan_bentham_vs_kant"]["bentham"]
    assert b["net_utility_score"] == pytest.approx(1_800_000)
    assert "5 tanggungan + 1 pemohon" in b["alasan"]


def test_pemohon_tanpa_tanggungan_tetap_dihitung():
    h = analisis(buat("Lajang", 400_000, 0, False, 50))
    assert h["perbandingan_bentham_vs_kant"]["bentham"]["net_utility_score"] == pytest.approx(400_000)


def test_batch_lima_kasus_kuota_dua_orang():
    hasil = batch(list(KASUS.values()))
    r = hasil["ringkasan"]

    assert r["kapasitas_penerima"] == 2
    assert r["jumlah_diterima"] == 2
    assert r["total_dialokasikan"] == 4_000_000
    assert r["sisa_anggaran"] == 0
    assert (r["jumlah_wajib_kant"], r["wajib_kant_diterima"], r["wajib_kant_tidak_terdanai"]) == (1, 1, 0)

    assert [x["nama"] for x in hasil["alokasi"]] == ["B", "C", "D", "A", "E"]

    status = {x["nama"]: x["status_alokasi"] for x in hasil["alokasi"]}
    assert status == {
        "B": "DITERIMA",
        "C": "DITERIMA",
        "D": "ANGGARAN_HABIS",
        "A": "TIDAK_LAYAK",
        "E": "TIDAK_LAYAK",
    }
    assert sum(x["dana_dialokasikan"] for x in hasil["alokasi"]) <= 4_000_000
    assert any("1 pemohon lolos ambang" in w for w in r["peringatan"])


def test_batch_urutan_input_tidak_mempengaruhi_hasil():
    maju = batch(list(KASUS.values()))
    mundur = batch(list(reversed(list(KASUS.values()))))
    assert [x["nama"] for x in maju["alokasi"]] == [x["nama"] for x in mundur["alokasi"]]


def test_batch_kant_didahulukan_walau_kapasitas_hanya_satu():
    hasil = batch(list(KASUS.values()), kuota=2_000_000)
    status = {x["nama"]: x["status_alokasi"] for x in hasil["alokasi"]}
    assert status["B"] == "DITERIMA"
    assert status["C"] == "ANGGARAN_HABIS" and status["D"] == "ANGGARAN_HABIS"


def test_batch_kapasitas_tiga_meloloskan_d():
    hasil = batch(list(KASUS.values()), kuota=6_000_000)
    diterima = {x["nama"] for x in hasil["alokasi"] if x["status_alokasi"] == "DITERIMA"}
    assert diterima == {"B", "C", "D"}


def test_batch_kekurangan_dana_untuk_pemohon_wajib_kant():
    hasil = batch(
        [buat("K1", 200_000, 1, True, 10), buat("K2", 300_000, 1, True, 20), buat("Kaya", 9_000_000, 0, False, 95)],
        kuota=2_000_000,
    )
    r = hasil["ringkasan"]
    assert r["wajib_kant_tidak_terdanai"] == 1
    assert any("KEWAJIBAN KANT TIDAK TERPENUHI" in w and "Rp2.000.000" in w for w in r["peringatan"])
    assert [x for x in hasil["alokasi"] if x["nama"] == "Kaya"][0]["status_alokasi"] == "TIDAK_LAYAK"


def test_batch_anggaran_lebih_kecil_dari_satu_bantuan():
    hasil = batch([buat("K", 200_000, 0, True, 10)], kuota=1_000_000)
    assert hasil["ringkasan"]["kapasitas_penerima"] == 0
    assert hasil["alokasi"][0]["status_alokasi"] == "ANGGARAN_HABIS"


def test_batch_tanpa_besaran_memakai_default_dari_env():
    r = client.post(
        "/analisis-batch",
        json={"kuota_anggaran_maksimal": 4_000_000, "pemohon": [KASUS["C"]]},
    ).json()["ringkasan"]
    assert r["besaran_bantuan_per_pemohon"] == 2_000_000
    assert r["kapasitas_penerima"] == 2


# Dasar skenario tipis: pendapatan 1,6jt dengan 1 tanggungan menghasilkan U = 0,
# U ternormalisasi 50, sehingga skor gabungan = 0,6 x 50 + 0,4 x ML = 30 + 0,4 x ML.
@pytest.mark.parametrize(
    "skor_ml, gabungan, status",
    [
        (49.9, 49.96, "TIDAK_LAYAK"),
        (50.0, 50.00, "LAYAK"),
        (50.1, 50.04, "LAYAK"),
    ],
)
def test_tipis_di_sekitar_ambang_kuota(skor_ml, gabungan, status):
    h = analisis(buat("Tipis", 1_600_000, 1, False, skor_ml))
    b = h["perbandingan_bentham_vs_kant"]["bentham"]
    assert b["skor_utilitas_ternormalisasi"] == pytest.approx(50.0)
    assert b["skor_gabungan"] == pytest.approx(gabungan, abs=0.01)
    assert h["status_kelayakan_akhir"] == status
    assert "dekat_ambang_kuota" in nama_faktor(h)


def test_jauh_dari_ambang_tidak_ditandai_rapuh():
    h = analisis(buat("Jauh", 1_600_000, 1, False, 80))
    assert "dekat_ambang_kuota" not in nama_faktor(h)


def test_tepat_di_bawah_batas_kemiskinan_memicu_kant():
    h = analisis(buat("Bawah", 599_999, 0, True, 5))
    assert h["perbandingan_bentham_vs_kant"]["kant"]["aturan_terpicu"] is True
    assert h["status_kelayakan_akhir"] == "LAYAK"


def test_tepat_di_batas_kemiskinan_tidak_memicu_kant():
    h = analisis(buat("Tepat", 600_000, 0, True, 5))
    assert h["perbandingan_bentham_vs_kant"]["kant"]["aturan_terpicu"] is False
    assert "efek_tebing_batas_kemiskinan" in nama_faktor(h)


def test_miskin_tanpa_penyakit_kronis_tidak_memicu_kant():
    h = analisis(buat("MiskinSehat", 100_000, 0, False, 5))
    assert h["perbandingan_bentham_vs_kant"]["kant"]["aturan_terpicu"] is False


def test_konfigurasi_dari_env_valid():
    k = KonfigurasiEtika.dari_env()
    assert k.bobot_ml * 100 < k.ambang_kuota


@pytest.mark.parametrize(
    "bobot_utilitas, bobot_ml",
    [
        (0.4, 0.6),
        (0.5, 0.5),  # tepat sama dengan ambang: ditolak karena operatornya >=
    ],
)
def test_konfigurasi_menolak_bobot_ml_terlalu_besar(bobot_utilitas, bobot_ml):
    with pytest.raises(ValueError, match="ambang_kuota"):
        konfig(bobot_utilitas=bobot_utilitas, bobot_ml=bobot_ml)


def test_konfigurasi_menerima_bobot_ml_tepat_di_bawah_ambang():
    k = konfig(bobot_utilitas=0.51, bobot_ml=0.49)
    assert k.bobot_ml * 100 < k.ambang_kuota


def test_konfigurasi_menolak_ambang_diturunkan_hingga_ml_cukup():
    with pytest.raises(ValueError, match="ambang_kuota"):
        konfig(ambang_kuota=40.0)


def test_konfigurasi_menolak_bobot_tidak_berjumlah_satu():
    with pytest.raises(ValueError, match="berjumlah 1.0"):
        konfig(bobot_utilitas=0.5, bobot_ml=0.4)


@pytest.mark.parametrize(
    "ubah",
    [
        {"batas_kemiskinan": 0},
        {"batas_kemiskinan": -1},
        {"nilai_bantuan_per_pemohon": 0},
        {"pengali_kesehatan_kronis": 0.5},
        {"ambang_kuota": 0},
        {"ambang_kuota": 101},
        {"bobot_ml": -0.1, "bobot_utilitas": 1.1},
    ],
)
def test_konfigurasi_menolak_nilai_di_luar_rentang(ubah):
    with pytest.raises(KonfigurasiTidakValid):
        konfig(**ubah)


@pytest.fixture
def tanpa_berkas_env(tmp_path, monkeypatch):
    # Mengarahkan pemuat ke berkas yang tidak ada supaya .env lokal tidak
    # menambal variabel yang sengaja dihapus oleh uji.
    monkeypatch.setattr(config, "ENV_PATH", tmp_path / "tidak_ada.env")


def test_env_variabel_hilang_ditolak(tanpa_berkas_env, monkeypatch):
    monkeypatch.delenv("BATAS_KEMISKINAN")
    with pytest.raises(KonfigurasiTidakValid, match="BATAS_KEMISKINAN"):
        KonfigurasiEtika.dari_env()


@pytest.mark.parametrize("nilai", ["abc", "", "nan", "inf"])
def test_env_nilai_bukan_angka_terhingga_ditolak(tanpa_berkas_env, monkeypatch, nilai):
    monkeypatch.setenv("AMBANG_KUOTA", nilai)
    with pytest.raises(KonfigurasiTidakValid, match="AMBANG_KUOTA"):
        KonfigurasiEtika.dari_env()


def test_env_variabel_proses_menang_atas_berkas(tmp_path, monkeypatch):
    berkas = tmp_path / ".env"
    berkas.write_text("AMBANG_KUOTA=99\n")
    monkeypatch.setattr(config, "ENV_PATH", berkas)
    assert KonfigurasiEtika.dari_env().ambang_kuota == 50.0


def test_env_berkas_dipakai_bila_proses_tidak_mengatur(tmp_path, monkeypatch):
    berkas = tmp_path / ".env"
    berkas.write_text("AMBANG_KUOTA=55\n")
    monkeypatch.setattr(config, "ENV_PATH", berkas)
    monkeypatch.delenv("AMBANG_KUOTA")
    assert KonfigurasiEtika.dari_env().ambang_kuota == 55.0


def test_endpoint_konfigurasi_menampilkan_parameter_kebijakan():
    isi = client.get("/konfigurasi").json()
    assert set(isi) == {f.name for f in fields(KonfigurasiEtika)}
    assert isi["batas_kemiskinan"] == 600_000


def test_endpoint_root_dan_health():
    assert client.get("/health").json() == {"status": "ok"}
    assert "POST /analisis-batch" in client.get("/").json()["endpoint"]


@pytest.mark.parametrize(
    "ubah",
    [
        {"skor_kelayakan_ml": 150},
        {"skor_kelayakan_ml": -1},
        {"pendapatan_bulanan": -1},
        {"jumlah_tanggungan": -1},
        {"nama": ""},
    ],
)
def test_analisis_menolak_input_tidak_valid(ubah):
    assert client.post("/analisis", json={**KASUS["C"], **ubah}).status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"kuota_anggaran_maksimal": 0, "pemohon": [KASUS["C"]]},
        {"kuota_anggaran_maksimal": 1_000_000, "pemohon": []},
        {"kuota_anggaran_maksimal": 1_000_000, "besaran_bantuan_per_pemohon": -5, "pemohon": [KASUS["C"]]},
    ],
)
def test_batch_menolak_input_tidak_valid(payload):
    assert client.post("/analisis-batch", json=payload).status_code == 422
