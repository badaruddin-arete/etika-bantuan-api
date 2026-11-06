"""Kontrak data API.

Rentang nilai divalidasi di sini sekali, sehingga mesin etika dapat berasumsi
inputnya bersih dan tidak mengulang pemeriksaan di setiap rumus.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class StatusKelayakan(str, Enum):
    LAYAK = "LAYAK"
    TIDAK_LAYAK = "TIDAK_LAYAK"


class StatusKant(str, Enum):
    # Sengaja tidak ada status "ditolak". Deontologi menjawab "apakah ada
    # kewajiban mutlak", bukan "seberapa layak"; tanpa kewajiban, Kant hanya
    # tidak memaksa dan keputusan diserahkan ke kerangka lain.
    WAJIB_DIBERIKAN = "WAJIB_DIBERIKAN"
    TIDAK_ADA_KEWAJIBAN_MUTLAK = "TIDAK_ADA_KEWAJIBAN_MUTLAK"


class DasarKeputusan(str, Enum):
    DEONTOLOGI = "DEONTOLOGI_KANT"
    UTILITARIAN = "UTILITARIAN_BENTHAM"


class LevelBias(str, Enum):
    RENDAH = "RENDAH"
    SEDANG = "SEDANG"
    TINGGI = "TINGGI"


class StatusAlokasi(str, Enum):
    DITERIMA = "DITERIMA"
    TIDAK_LAYAK = "TIDAK_LAYAK"
    # Dipisahkan dari TIDAK_LAYAK: pemohon yang layak tetapi kehabisan dana
    # adalah masalah anggaran, bukan masalah kelayakan, dan harus terlihat
    # berbeda bagi pengambil kebijakan.
    ANGGARAN_HABIS = "ANGGARAN_HABIS"


class PemohonInput(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "nama": "Siti Aminah",
                "pendapatan_bulanan": 450000,
                "jumlah_tanggungan": 3,
                "kondisi_kesehatan_kronis": True,
                "skor_kelayakan_ml": 38.5,
            }
        },
    )

    nama: str = Field(..., min_length=1, max_length=100, description="Nama pemohon")
    pendapatan_bulanan: float = Field(
        ..., ge=0, description="Pendapatan bulanan rumah tangga (Rupiah)"
    )
    jumlah_tanggungan: int = Field(..., ge=0, description="Jumlah anggota yang ditanggung")
    kondisi_kesehatan_kronis: bool = Field(
        ..., description="True bila pemohon atau tanggungan memiliki penyakit kronis"
    )
    skor_kelayakan_ml: float = Field(
        ..., ge=0, le=100, description="Skor kelayakan dari model ML (0-100)"
    )


class HasilBentham(BaseModel):
    status: StatusKelayakan
    net_utility_score: float = Field(
        ..., description="U = (Tanggungan + 1) x Kebutuhan - Pendapatan (Rupiah)"
    )
    skor_utilitas_ternormalisasi: float = Field(
        ..., description="Net utility dipetakan ke skala 0-100"
    )
    skor_gabungan: float = Field(
        ..., description="Gabungan utilitas ternormalisasi dan skor ML (0-100)"
    )
    ambang_kuota: float = Field(..., description="Skor minimum untuk lolos kuota")
    alasan: str


class HasilKant(BaseModel):
    status: StatusKant
    aturan_terpicu: bool = Field(
        ..., description="True bila Imperatif Kategoris mewajibkan bantuan"
    )
    alasan: str


class PerbandinganEtika(BaseModel):
    bentham: HasilBentham
    kant: HasilKant
    terjadi_konflik: bool = Field(
        ..., description="True bila Bentham menolak sedangkan Kant mewajibkan"
    )
    catatan: str


class FaktorBias(BaseModel):
    nama: str
    kontribusi: float = Field(..., description="Sumbangan terhadap skor bias (0-1)")
    penjelasan: str


class SkorBias(BaseModel):
    skor: float = Field(..., ge=0, le=1, description="Skor potensi bias etika (0-1)")
    level: LevelBias
    faktor: list[FaktorBias]


class HasilAnalisis(BaseModel):
    nama: str
    status_kelayakan_akhir: StatusKelayakan
    dasar_keputusan: DasarKeputusan
    penjelasan_keputusan: str
    skor_potensi_bias: SkorBias
    perbandingan_bentham_vs_kant: PerbandinganEtika


class BatchInput(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "kuota_anggaran_maksimal": 100_000_000,
                "besaran_bantuan_per_pemohon": 2_000_000,
                "pemohon": [
                    {
                        "nama": "Siti Aminah",
                        "pendapatan_bulanan": 450000,
                        "jumlah_tanggungan": 3,
                        "kondisi_kesehatan_kronis": True,
                        "skor_kelayakan_ml": 38.5,
                    },
                    {
                        "nama": "Budi Santoso",
                        "pendapatan_bulanan": 2500000,
                        "jumlah_tanggungan": 3,
                        "kondisi_kesehatan_kronis": False,
                        "skor_kelayakan_ml": 70,
                    },
                ],
            }
        }
    )

    kuota_anggaran_maksimal: float = Field(
        ..., gt=0, description="Total anggaran yang tersedia (Rupiah)"
    )
    besaran_bantuan_per_pemohon: float | None = Field(
        None,
        gt=0,
        description="Nilai bantuan per penerima (Rupiah). Kosong = pakai NILAI_BANTUAN_PER_PEMOHON dari .env.",
    )
    # Tiap pemohon menghasilkan penjelasan teks sendiri sehingga respons tumbuh
    # linear. Batas ini melindungi memori server; memecah batch bukan jalan
    # keluar karena peringkat dan anggaran hanya bermakna untuk satu populasi utuh.
    pemohon: list[PemohonInput] = Field(..., min_length=1, max_length=5000)


class ItemAlokasi(BaseModel):
    peringkat: int
    indeks_input: int = Field(..., description="Posisi pemohon pada array input (mulai 0)")
    nama: str
    wajib_kant: bool = Field(..., description="Memenuhi syarat absolut Deontologi")
    skor_gabungan: float = Field(..., description="Skor Bentham + skor ML (0-100)")
    status_alokasi: StatusAlokasi
    dana_dialokasikan: float
    level_bias: LevelBias
    penjelasan_alokasi: str


class RingkasanBatch(BaseModel):
    total_pemohon: int
    kuota_anggaran_maksimal: float
    besaran_bantuan_per_pemohon: float
    kapasitas_penerima: int = Field(..., description="Jumlah maksimum penerima yang terdanai")
    jumlah_diterima: int
    total_dialokasikan: float
    sisa_anggaran: float
    jumlah_wajib_kant: int
    wajib_kant_diterima: int
    wajib_kant_tidak_terdanai: int
    peringatan: list[str]


class HasilBatch(BaseModel):
    ringkasan: RingkasanBatch
    alokasi: list[ItemAlokasi] = Field(..., description="Terurut menurut peringkat")
