# API Etika Seleksi Bantuan Sosial
**Demo antarmuka:** https://etika-bantuan-demo.lovable.app (kode: https://github.com/badaruddin-arete/etika-bantuan-web)

Backend FastAPI yang menganalisis seleksi bantuan sosial dengan dua kerangka etika Barat, lalu menjelaskan alasan setiap keputusan (explainable AI):

- **Utilitarianisme (Bentham):** siapa yang paling besar manfaatnya bila dibantu?
- **Deontologi (Kant):** siapa yang *wajib* dibantu, apa pun hitungan manfaatnya?

Proyek ini adalah eksplorasi tentang bagaimana prinsip etika dapat dijadikan aturan yang bisa diaudit dalam sistem keputusan otomatis, bukan produk siap pakai.

## Gagasan inti

**Kant adalah veto, bukan bobot.** Pemohon dengan pendapatan di bawah batas kemiskinan *dan* penyakit kronis berhak atas bantuan sebagai kewajiban mutlak. Aturan ini dievaluasi sebelum kalkulus Bentham dan tidak bisa dikalahkan oleh skor setinggi apa pun. Menjadikannya sekadar bobot akan membuat hak seseorang bisa "ditebus" oleh angka lain.

**Bentham menghitung kebutuhan bersih:**

```
U = (jumlah_tanggungan + 1) x kebutuhan_dasar x pengali_kesehatan - pendapatan
```

`U` dinormalkan ke skala 0-100, lalu digabung dengan skor model ML (bobot 60% : 40%). Pemohon lolos bila skor gabungan mencapai ambang kuota.

**Pagar etika saat startup.** Konfigurasi ditolak bila `bobot_ml x 100 >= ambang_kuota`, karena pada kondisi itu skor ML yang keliru saja sudah bisa meloloskan orang yang tidak membutuhkan bantuan. Lebih baik server tidak menyala daripada salah diam-diam.

**Skor bias heuristik.** Setiap analisis menyertakan level bias (RENDAH, SEDANG, TINGGI) beserta faktor penyebabnya, misalnya konflik Kant vs Bentham, divergensi skor ML, atau posisi tepat di dekat ambang.

## Endpoint

| Method | Path | Fungsi |
|---|---|---|
| POST | `/analisis` | Analisis satu pemohon: status, penjelasan, perbandingan Bentham vs Kant, skor bias |
| POST | `/analisis-batch` | Peringkat dan alokasi untuk banyak pemohon dengan kuota anggaran |
| GET | `/konfigurasi` | Parameter kebijakan yang sedang berlaku (sengaja terbuka demi transparansi) |
| GET | `/health` | Pemeriksaan kesehatan |

Pada `/analisis-batch`, urutan pendanaan adalah: (1) pemohon wajib Kant, (2) yang lolos ambang, (3) yang di bawah ambang. Di dalam tiap tingkat, skor tertinggi lebih dulu. Bila dana tidak cukup untuk semua pemohon wajib Kant, respons memuat peringatan beserta kekurangan dananya.

## Menjalankan

Butuh Python 3.13.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # Windows; salin lalu sesuaikan nilainya
uvicorn main:app --reload
```

Buka `http://127.0.0.1:8000/docs` untuk dokumentasi interaktif.

## Pengujian

```bash
python -m pytest -q
```

Uji mencakup lima kasus ekstrem (termasuk konflik Kant vs Bentham), batas tepat garis kemiskinan dan ambang kuota, validasi konfigurasi, serta skenario alokasi anggaran.

## Struktur

```
main.py                  titik masuk HTTP
config.py                konfigurasi dari .env, validasi, pagar etika
schemas.py               skema request dan respons
models/ethical_engine.py mesin Bentham, pemeriksa Kant, skor bias
models/allocator.py      alokasi anggaran bertingkat
models/formatting.py     format Rupiah untuk teks audit
test_ethical_engine.py   uji otomatis
.env.example             templat parameter kebijakan
```

## Keterbatasan

- Semua angka kebijakan (batas kemiskinan, kebutuhan dasar, ambang) bersifat **ilustratif**. Penggunaan nyata memerlukan data resmi, misalnya garis kemiskinan BPS daerah.
- Skor ML pada kode ini diterima sebagai masukan; tidak ada model yang dilatih di repositori ini.
- Skor bias adalah heuristik, bukan audit statistik terhadap kelompok demografis.
- Dua kerangka etika adalah penyederhanaan. Keadilan distributif punya pendekatan lain (Rawls, kapabilitas) yang tidak dicakup di sini.
- Tidak ada autentikasi; proyek ini bukan untuk dipakai langsung pada keputusan tentang manusia sungguhan.

## Transparansi pembuatan

Rancangan etika, keputusan desain, dan pengujian saya susun dengan bantuan AI (Claude). Antarmuka demonya dibuat dengan Lovable.

## Lisensi

Hak cipta dilindungi. Kode boleh dibaca dan dinilai; penggunaan ulang memerlukan izin tertulis. Lihat [LICENSE](LICENSE).
