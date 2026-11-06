def rupiah(nilai: float) -> str:
    # Pemisah ribuan ditulis manual, bukan lewat modul locale: locale bergantung
    # pada paket bahasa OS, sedangkan teks penjelasan ini dibandingkan persis di
    # uji dan dibaca sebagai bukti audit sehingga harus identik di semua mesin.
    tanda = "-" if nilai < 0 else ""
    return f"{tanda}Rp{abs(nilai):,.0f}".replace(",", ".")
