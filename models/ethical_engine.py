"""Mesin etika: kalkulus kemanfaatan Bentham, uji kewajiban Kant, dan orkestrasinya.

Urutan evaluasi adalah keputusan desain, bukan detail implementasi. Kewajiban
Kant bertindak sebagai veto atas hasil Bentham, bukan sebagai bobot tambahan
dalam skor. Jika dijadikan bobot, pemohon yang seharusnya dilindungi bisa kalah
oleh skor ML yang keliru, dan "aturan absolut" tinggal nama.
"""

from __future__ import annotations

from config import KonfigurasiEtika
from models.formatting import rupiah
from schemas import (
    DasarKeputusan,
    FaktorBias,
    HasilAnalisis,
    HasilBentham,
    HasilKant,
    LevelBias,
    PemohonInput,
    PerbandinganEtika,
    SkorBias,
    StatusKant,
    StatusKelayakan,
)

# Bobot skor bias bersifat heuristik dan belum dikalibrasi terhadap data riil.
# Disusun agar konflik Bentham-Kant saja berstatus SEDANG, dan TINGGI baru
# tercapai bila ada sinyal tambahan; dengan begitu TINGGI tetap berarti
# "tinjau oleh manusia" dan tidak menyala untuk setiap kasus.
_BIAS_KONFLIK = 0.35
_BIAS_DIVERGENSI_MAKS = 0.30
_BIAS_ML_MEREMEHKAN = 0.20
_BIAS_DEKAT_AMBANG = 0.15
_BIAS_TEBING = 0.15

# Divergensi kecil antara skor ML dan skor kebutuhan adalah derau normal dua
# model berbeda; hanya selisih yang cukup besar yang layak dicatat sebagai faktor.
_BIAS_DIVERGENSI_MIN = 0.05

_BATAS_BIAS_SEDANG = 0.25
_BATAS_BIAS_TINGGI = 0.50

# Titik tengah skala 0-100: di bawahnya model menilai pemohon lebih mungkin
# tidak layak daripada layak.
_ML_TITIK_TENGAH = 50.0

# Hasil dalam jarak ini dari ambang dapat berbalik hanya karena penyesuaian
# kecil parameter, sehingga keputusannya perlu ditandai rapuh.
_JARAK_DEKAT_AMBANG = 5.0

# Pita 25% di atas batas kemiskinan: kerentanannya praktis sama dengan yang
# tepat di bawah garis, tetapi aturan Kant tidak berlaku bagi mereka.
_PITA_TEBING = 1.25


class UtilitarianEngine:
    """Bentham: nilai suatu tindakan diukur dari kebahagiaan agregat.

    Intensitas diwakili tingkat kebutuhan, jangkauan diwakili jumlah orang
    terdampak. Kebutuhan dinyatakan dalam Rupiah per anggota agar satu satuan
    dengan pendapatan; tanpa itu selisih keduanya tidak bermakna.
    """

    def __init__(self, konfigurasi: KonfigurasiEtika) -> None:
        self.k = konfigurasi

    def hitung_kebutuhan(self, kronis: bool) -> float:
        # Biaya penyakit kronis berulang tiap bulan, maka dimodelkan sebagai
        # pengali kebutuhan dan bukan biaya sekali bayar.
        pengali = self.k.pengali_kesehatan_kronis if kronis else 1.0
        return self.k.kebutuhan_dasar_per_tanggungan * pengali

    def hitung_net_utility(self, p: PemohonInput) -> float:
        # "+ 1" menghitung pemohon sebagai anggota rumah tangganya sendiri.
        # Tanpa itu pemohon lajang selalu berjangkauan nol dan secara struktural
        # kalah dari rumah tangga yang berpendapatan sama.
        kebutuhan = self.hitung_kebutuhan(p.kondisi_kesehatan_kronis)
        return (p.jumlah_tanggungan + 1) * kebutuhan - p.pendapatan_bulanan

    def normalisasi(self, u: float) -> float:
        # U = 0 (kebutuhan persis sama dengan pendapatan) dijadikan titik netral 50.
        # Dijepit ke 0-100 agar satu pemohon ekstrem tidak mendominasi skor
        # gabungan dan agar batas pengaruh ML tetap dapat dianalisis secara tertutup.
        nilai = 50.0 + (u / self.k.skala_utilitas) * 50.0
        return max(0.0, min(100.0, nilai))

    def evaluasi(self, p: PemohonInput) -> HasilBentham:
        kebutuhan = self.hitung_kebutuhan(p.kondisi_kesehatan_kronis)
        u = self.hitung_net_utility(p)
        u_norm = self.normalisasi(u)

        # Kebutuhan memegang bobot terbesar supaya skor ML hanya menjadi sinyal
        # pendukung. Batas atas pengaruh ML dijaga oleh KonfigurasiEtika.
        gabungan = self.k.bobot_utilitas * u_norm + self.k.bobot_ml * p.skor_kelayakan_ml

        # Skor tepat di ambang dinyatakan lolos: bila ragu, keputusan berpihak
        # pada pemohon, bukan pada ketelitian pembulatan.
        lolos = gabungan >= self.k.ambang_kuota
        status = StatusKelayakan.LAYAK if lolos else StatusKelayakan.TIDAK_LAYAK

        alasan = (
            f"Net Utility Score = ({p.jumlah_tanggungan} tanggungan + 1 pemohon) x {rupiah(kebutuhan)} "
            f"- {rupiah(p.pendapatan_bulanan)} = {rupiah(u)} "
            f"(ternormalisasi {u_norm:.1f}/100). "
            f"Digabung dengan skor ML {p.skor_kelayakan_ml:.1f} "
            f"(bobot {self.k.bobot_utilitas:.0%}/{self.k.bobot_ml:.0%}) "
            f"menghasilkan skor {gabungan:.1f} "
            f"{'>=' if lolos else '<'} ambang kuota {self.k.ambang_kuota:.1f}."
        )

        return HasilBentham(
            status=status,
            net_utility_score=round(u, 2),
            skor_utilitas_ternormalisasi=round(u_norm, 2),
            skor_gabungan=round(gabungan, 2),
            ambang_kuota=self.k.ambang_kuota,
            alasan=alasan,
        )


class KantianDutyChecker:
    """Imperatif Kategoris sebagai aturan yang tidak dapat ditawar.

    Dasarnya dua formulasi Kant: manusia diperlakukan sebagai tujuan pada
    dirinya dan bukan sarana pemenuhan kuota, dan maksim "abaikan orang miskin
    yang sakit kronis demi efisiensi" tidak dapat dikehendaki menjadi hukum
    universal. Karena itu aturan ini sengaja tanpa bobot dan tanpa ambang.
    """

    def __init__(self, konfigurasi: KonfigurasiEtika) -> None:
        self.k = konfigurasi

    def evaluasi(self, p: PemohonInput) -> HasilKant:
        # Perbandingan ketat mengikuti rumusan aturan "di bawah batas kemiskinan".
        # Pemohon tepat di garis tidak tercakup; celah itu ditandai sebagai
        # faktor bias efek_tebing alih-alih ditutup diam-diam dengan operator lain.
        di_bawah_batas = p.pendapatan_bulanan < self.k.batas_kemiskinan
        kronis = p.kondisi_kesehatan_kronis
        terpicu = di_bawah_batas and kronis

        if terpicu:
            return HasilKant(
                status=StatusKant.WAJIB_DIBERIKAN,
                aturan_terpicu=True,
                alasan=(
                    f"Kewajiban mutlak terpicu: pendapatan {rupiah(p.pendapatan_bulanan)} "
                    f"di bawah batas kemiskinan {rupiah(self.k.batas_kemiskinan)} "
                    f"dan pemohon memiliki kondisi kesehatan kronis. Bantuan wajib "
                    f"diberikan tanpa memedulikan skor kuota."
                ),
            )

        # Alasan wajib menyebut syarat yang gagal: keputusan yang tidak bisa
        # ditelusuri tidak bisa digugat oleh pemohon.
        gagal = []
        if not di_bawah_batas:
            gagal.append(
                f"pendapatan {rupiah(p.pendapatan_bulanan)} tidak di bawah batas "
                f"{rupiah(self.k.batas_kemiskinan)}"
            )
        if not kronis:
            gagal.append("tidak ada kondisi kesehatan kronis")
        return HasilKant(
            status=StatusKant.TIDAK_ADA_KEWAJIBAN_MUTLAK,
            aturan_terpicu=False,
            alasan=(
                "Imperatif Kategoris tidak terpicu karena " + " dan ".join(gagal) + ". "
                "Ini bukan penolakan, hanya tidak ada kewajiban mutlak; "
                "keputusan diserahkan pada pertimbangan lain."
            ),
        )


class MesinEtika:
    def __init__(self, konfigurasi: KonfigurasiEtika) -> None:
        self.k = konfigurasi
        self.bentham = UtilitarianEngine(konfigurasi)
        self.kant = KantianDutyChecker(konfigurasi)

    def analisis(self, p: PemohonInput) -> HasilAnalisis:
        hasil_bentham = self.bentham.evaluasi(p)
        hasil_kant = self.kant.evaluasi(p)

        # Kedua kerangka selalu dihitung penuh, bahkan bila Kant sudah pasti
        # menang: perbandingan keduanya adalah keluaran, dan konflik di antara
        # keduanya adalah sinyal audit yang tidak boleh hilang.
        if hasil_kant.aturan_terpicu:
            status_akhir = StatusKelayakan.LAYAK
            dasar = DasarKeputusan.DEONTOLOGI
        else:
            status_akhir = hasil_bentham.status
            dasar = DasarKeputusan.UTILITARIAN

        konflik = (
            hasil_kant.aturan_terpicu
            and hasil_bentham.status == StatusKelayakan.TIDAK_LAYAK
        )

        bias = self._hitung_bias(p, hasil_bentham, hasil_kant)
        perbandingan = PerbandinganEtika(
            bentham=hasil_bentham,
            kant=hasil_kant,
            terjadi_konflik=konflik,
            catatan=self._catatan_perbandingan(hasil_bentham, hasil_kant, konflik),
        )

        return HasilAnalisis(
            nama=p.nama,
            status_kelayakan_akhir=status_akhir,
            dasar_keputusan=dasar,
            penjelasan_keputusan=self._penjelasan(
                p, status_akhir, dasar, hasil_bentham, hasil_kant, konflik, bias
            ),
            skor_potensi_bias=bias,
            perbandingan_bentham_vs_kant=perbandingan,
        )

    def _hitung_bias(
        self, p: PemohonInput, b: HasilBentham, kt: HasilKant
    ) -> SkorBias:
        # Skor ini penanda untuk ditinjau, bukan uji fairness statistik. Tanpa
        # data populasi, bias sistematis antar kelompok tidak bisa diukur; yang
        # bisa dilakukan adalah menandai pola kasus yang rawan tidak adil.
        faktor: list[FaktorBias] = []

        if kt.aturan_terpicu and b.status == StatusKelayakan.TIDAK_LAYAK:
            faktor.append(FaktorBias(
                nama="konflik_bentham_kant",
                kontribusi=_BIAS_KONFLIK,
                penjelasan="Metrik kemanfaatan menolak pemohon yang menurut kewajiban "
                           "mutlak harus dibantu (risiko 'tirani mayoritas').",
            ))

        # Dua penilaian independen (ML dan kebutuhan) yang berselisih jauh berarti
        # salah satunya keliru atau memakai proxy yang bias; mana yang keliru
        # tidak bisa ditentukan dari sini, jadi yang dicatat adalah selisihnya.
        divergensi = abs(p.skor_kelayakan_ml - b.skor_utilitas_ternormalisasi) / 100.0
        kontribusi_div = round(divergensi * _BIAS_DIVERGENSI_MAKS, 3)
        if kontribusi_div >= _BIAS_DIVERGENSI_MIN:
            faktor.append(FaktorBias(
                nama="divergensi_ml_vs_kebutuhan",
                kontribusi=kontribusi_div,
                penjelasan=f"Skor ML ({p.skor_kelayakan_ml:.1f}) berbeda jauh dari skor "
                           f"kebutuhan ({b.skor_utilitas_ternormalisasi:.1f}); "
                           "periksa fitur model ML yang mungkin menjadi proxy diskriminasi.",
            ))

        if p.kondisi_kesehatan_kronis and p.skor_kelayakan_ml < _ML_TITIK_TENGAH:
            faktor.append(FaktorBias(
                nama="ml_meremehkan_kondisi_kronis",
                kontribusi=_BIAS_ML_MEREMEHKAN,
                penjelasan="Pemohon berpenyakit kronis tetapi skor ML rendah; model "
                           "berpotensi kurang menangkap kerentanan kesehatan.",
            ))

        jarak = abs(b.skor_gabungan - b.ambang_kuota)
        if jarak < _JARAK_DEKAT_AMBANG:
            faktor.append(FaktorBias(
                nama="dekat_ambang_kuota",
                kontribusi=_BIAS_DEKAT_AMBANG,
                penjelasan=f"Skor gabungan hanya {jarak:.1f} poin dari ambang; "
                           "hasil mudah berbalik bila parameter diubah sedikit.",
            ))

        if (
            p.kondisi_kesehatan_kronis
            and self.k.batas_kemiskinan <= p.pendapatan_bulanan < self.k.batas_kemiskinan * _PITA_TEBING
        ):
            faktor.append(FaktorBias(
                nama="efek_tebing_batas_kemiskinan",
                kontribusi=_BIAS_TEBING,
                penjelasan="Pendapatan hanya sedikit di atas batas kemiskinan sehingga "
                           "luput dari kewajiban mutlak meski kerentanannya serupa.",
            ))

        skor = round(min(1.0, sum(f.kontribusi for f in faktor)), 3)
        if skor < _BATAS_BIAS_SEDANG:
            level = LevelBias.RENDAH
        elif skor < _BATAS_BIAS_TINGGI:
            level = LevelBias.SEDANG
        else:
            level = LevelBias.TINGGI
        return SkorBias(skor=skor, level=level, faktor=faktor)

    @staticmethod
    def _catatan_perbandingan(b: HasilBentham, kt: HasilKant, konflik: bool) -> str:
        if konflik:
            return (
                "KONFLIK: Bentham menolak (efisiensi kuota), Kant mewajibkan "
                "(martabat individu). Sistem memenangkan Kant: hak dasar kelompok "
                "rentan tidak boleh dikorbankan demi agregat kemanfaatan."
            )
        if kt.aturan_terpicu:
            return "SEJALAN: Bentham dan Kant sama-sama mengarah pada pemberian bantuan."
        if b.status == StatusKelayakan.LAYAK:
            return ("Kant tidak mewajibkan apa pun; Bentham menilai layak, "
                    "sehingga keputusan mengikuti Bentham.")
        return ("Kant tidak mewajibkan apa pun; Bentham menilai tidak layak, "
                "sehingga keputusan mengikuti Bentham.")

    @staticmethod
    def _penjelasan(
        p: PemohonInput,
        status: StatusKelayakan,
        dasar: DasarKeputusan,
        b: HasilBentham,
        kt: HasilKant,
        konflik: bool,
        bias: SkorBias,
    ) -> str:
        label = "LAYAK" if status == StatusKelayakan.LAYAK else "TIDAK LAYAK"
        if dasar == DasarKeputusan.DEONTOLOGI:
            inti = (
                f"{p.nama} dinyatakan {label} berdasarkan kewajiban mutlak "
                f"(Deontologi Kant). {kt.alasan} "
            )
            inti += (
                f"Meski kalkulus Bentham menolak (skor {b.skor_gabungan:.1f} < "
                f"ambang {b.ambang_kuota:.1f}), aturan kategoris tidak dapat ditawar."
                if konflik
                else "Kalkulus Bentham juga menyetujui."
            )
        else:
            inti = (
                f"{p.nama} dinyatakan {label} berdasarkan kalkulus kemanfaatan "
                f"(Utilitarian Bentham) karena tidak ada kewajiban mutlak Kant. {b.alasan}"
            )
        return f"{inti} Potensi bias etika: {bias.level.value} ({bias.skor:.2f})."
