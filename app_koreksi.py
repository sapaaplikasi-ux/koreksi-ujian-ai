import streamlit as st
from PIL import Image, ImageOps
import pandas as pd
import json
import re
import os
import time
import io
import base64
import requests
import gc
import hashlib

st.set_page_config(
    page_title="Smart Koreksi AI - Pro Edition", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Membuat tombol panah >> di pojok kiri atas HP berwarna MERAH TERANG & BESAR agar mudah dilihat di HP!
st.markdown("""
<style>
[data-testid="collapsedControl"] {
    background-color: #ff4b4b !important;
    color: white !important;
    border-radius: 8px !important;
    padding: 4px !important;
    box-shadow: 0 2px 6px rgba(0,0,0,0.3) !important;
}
[data-testid="collapsedControl"] svg {
    fill: white !important;
    width: 28px !important;
    height: 28px !important;
}
</style>
""", unsafe_allow_html=True)

# ==========================================
# 🔐 FUNGSI KEAMANAN & DATABASE LOKAL
# ==========================================
def get_master_secret():
    try:
        if "MASTER_SECRET" in st.secrets:
            return st.secrets["MASTER_SECRET"].strip()
    except Exception:
        pass
    return "RAHASIA-SUPER-AMAN-2026"

def get_admin_password():
    try:
        if "ADMIN_PASSWORD" in st.secrets:
            return st.secrets["ADMIN_PASSWORD"].strip()
    except Exception:
        pass
    return "admin12345"

def buat_kode_lisensi(nama_user):
    id_bersih = re.sub(r'[^a-z0-9]', '', nama_user.lower())
    rahasia = get_master_secret()
    gabungan = f"{id_bersih}:{rahasia}"
    hash_hex = hashlib.sha256(gabungan.encode()).hexdigest().upper()
    return f"PRO-{hash_hex[:6]}"

def cek_validitas_lisensi(nama_user, kode_input):
    if not nama_user or not kode_input:
        return False
    if nama_user.strip().lower() == "admin" and kode_input.strip() == get_admin_password():
        return True
    kode_seharusnya = buat_kode_lisensi(nama_user)
    return kode_input.strip().upper() == kode_seharusnya

DB_GURU_FILE = "db_apikey_guru.json"

def muat_db_guru():
    if os.path.exists(DB_GURU_FILE):
        try:
            with open(DB_GURU_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def simpan_key_guru(nama_guru, api_key):
    if not nama_guru or not api_key:
        return
    db = muat_db_guru()
    id_guru = re.sub(r'[^a-z0-9]', '', nama_guru.lower())
    db[id_guru] = api_key.strip()
    try:
        with open(DB_GURU_FILE, "w") as f:
            json.dump(db, f)
    except Exception:
        pass

def ambil_key_guru(nama_guru):
    if not nama_guru:
        try:
            if "GEMINI_API_KEY" in st.secrets:
                return st.secrets["GEMINI_API_KEY"].strip()
        except Exception:
            pass
        return ""
    id_guru = re.sub(r'[^a-z0-9]', '', nama_guru.lower())
    db = muat_db_guru()
    if id_guru in db:
        return db[id_guru]
    try:
        if "GEMINI_API_KEY" in st.secrets:
            return st.secrets["GEMINI_API_KEY"].strip()
    except Exception:
        pass
    return ""

def hitung_skema_poin_essay(struktur_str, total_bobot_essay):
    items = [x.strip() for x in re.split(r'[,\n]+', struktur_str) if x.strip()]
    if not items:
        return {"1": float(total_bobot_essay)}
    
    custom_poin = {}
    ada_custom = False
    for it in items:
        if "=" in it or ":" in it:
            parts = re.split(r'[\=\:]', it)
            kode = parts[0].strip().lower()
            try:
                val = float(parts[1].strip())
                custom_poin[kode] = val
                ada_custom = True
            except Exception:
                custom_poin[kode] = None
        else:
            custom_poin[it.strip().lower()] = None

    if ada_custom and all(v is not None for v in custom_poin.values()):
        total_input = sum(custom_poin.values())
        if total_input > 0:
            return {k: round((v / total_input) * total_bobot_essay, 2) for k, v in custom_poin.items()}

    grup_induk = {}
    for it in items:
        kode_bersih = re.split(r'[\=\:]', it)[0].strip().lower()
        kode_bersih = re.sub(r'[^0-9a-z]', '', kode_bersih)
        if not kode_bersih:
            continue
        match_induk = re.match(r'^(\d+)', kode_bersih)
        no_induk = match_induk.group(1) if match_induk else kode_bersih
        if no_induk not in grup_induk:
            grup_induk[no_induk] = []
        grup_induk[no_induk].append(kode_bersih)

    jml_soal_induk = len(grup_induk)
    if jml_soal_induk == 0:
        return {"1": float(total_bobot_essay)}

    poin_per_induk = float(total_bobot_essay) / jml_soal_induk
    peta_poin = {}
    for no_induk, daftar_anak in grup_induk.items():
        poin_per_anak = poin_per_induk / len(daftar_anak)
        for anak in daftar_anak:
            peta_poin[anak] = round(poin_per_anak, 2)

    return peta_poin

# ==========================================
# 📌 INISIALISASI MEMORI & SIDEBAR KIRI
# ==========================================
nama_url = st.query_params.get("u", "")
lisensi_url = st.query_params.get("k", "")

if "lisensi_aktif" not in st.session_state:
    st.session_state.lisensi_aktif = False
if "user_aktif" not in st.session_state:
    st.session_state.user_aktif = "admin"
if "acuan_guru_img" not in st.session_state:
    st.session_state.acuan_guru_img = None
if "acuan_guru_b64" not in st.session_state:
    st.session_state.acuan_guru_b64 = None
if "acuan_guru_teks" not in st.session_state:
    st.session_state.acuan_guru_teks = ""
if "struktur_essay_str" not in st.session_state:
    st.session_state.struktur_essay_str = "1a, 1b, 2a, 2b"
if "bobot_pg_val" not in st.session_state:
    st.session_state.bobot_pg_val = 60
if "bobot_essay_val" not in st.session_state:
    st.session_state.bobot_essay_val = 40
if "mode_pg_val" not in st.session_state:
    st.session_state.mode_pg_val = "Ketat (Coretan kotor, silang meleset/tengah-tengah, atau ganda = SALAH)"
if "data_nilai" not in st.session_state:
    st.session_state.data_nilai = []

if not st.session_state.lisensi_aktif and nama_url and lisensi_url:
    if cek_validitas_lisensi(nama_url, lisensi_url):
        st.session_state.lisensi_aktif = True
        st.session_state.user_aktif = nama_url

# SIDEBAR UNTUK LAPTOP & TOMBOL MERAH KIRI ATAS HP
with st.sidebar:
    st.header("⚙️ Menu Konfigurasi")
    if st.session_state.lisensi_aktif:
        st.success(f"👤 Pengguna: **{st.session_state.user_aktif}**")
        if st.button("🚪 Keluar / Kunci Aplikasi", use_container_width=True, key="keluar_side"):
            st.session_state.lisensi_aktif = False
            st.query_params.clear()
            st.rerun()

    st.markdown("---")
    saved_key_guru = ambil_key_guru(st.session_state.user_aktif)
    api_key_side = st.text_input("🔑 API Key Google AI Studio:", value=saved_key_guru, type="password", key="key_side")
    if st.button("💾 Simpan API Key", use_container_width=True, key="simpan_side"):
        simpan_key_guru(st.session_state.user_aktif, api_key_side)
        st.success("✅ API Key disimpan!")

    st.markdown("---")
    st.subheader("🔍 Aturan Ketegasan PG")
    st.session_state.mode_pg_val = st.radio(
        "Perlakuan Coretan PG:",
        [
            "Ketat (Coretan kotor, silang meleset/tengah-tengah, atau ganda = SALAH)",
            "Toleran (Tetap tebak 1 huruf yang paling bersih jika ada coretan)"
        ],
        index=0 if st.session_state.mode_pg_val.startswith("Ketat") else 1,
        key="radio_side"
    )

    st.markdown("---")
    st.subheader("📊 Bobot & Struktur Essay")
    st.session_state.bobot_pg_val = st.number_input("Total Poin Maksimal PG:", min_value=0, max_value=100, value=st.session_state.bobot_pg_val, key="pg_side")
    st.session_state.bobot_essay_val = st.number_input("Total Poin Maksimal Essay:", min_value=0, max_value=100, value=st.session_state.bobot_essay_val, key="es_side")
    
    preset_side = st.selectbox(
        "Pilih Cepat Struktur Essay:",
        [
            "Custom (Sesuai Kotak di Bawah)",
            "Kelas 7 (2 Soal: 1a, 1b, 2a, 2b)",
            "Kelas 8 (2 Soal: 1a, 1b, 2)",
            "Kelas 9 (3 Soal: 1a, 1b, 2a, 2b, 2c, 3)"
        ],
        key="pres_side"
    )
    if preset_side == "Kelas 7 (2 Soal: 1a, 1b, 2a, 2b)":
        st.session_state.struktur_essay_str = "1a, 1b, 2a, 2b"
    elif preset_side == "Kelas 8 (2 Soal: 1a, 1b, 2)":
        st.session_state.struktur_essay_str = "1a, 1b, 2"
    elif preset_side == "Kelas 9 (3 Soal: 1a, 1b, 2a, 2b, 2c, 3)":
        st.session_state.struktur_essay_str = "1a, 1b, 2a, 2b, 2c, 3"

    st.session_state.struktur_essay_str = st.text_input("Daftar Nomor Essay:", value=st.session_state.struktur_essay_str, key="str_side")

# ==========================================
# 🚪 HALAMAN LOGIN LISENSI (JIKA BELUM LOGIN)
# ==========================================
if not st.session_state.lisensi_aktif:
    st.title("🔒 Aktivasi Lisensi Aplikasi Koreksi AI")
    st.info("💡 **Cara Masuk Cepat untuk Pemilik:** Ketik **`admin`** pada Nama Pengguna dan ketik **`admin12345`** pada Kode Lisensi, lalu klik tombol merah di bawah.")
    
    input_user = st.text_input("👤 Nama Pengguna / Instansi:", value=nama_url if nama_url else "admin")
    input_kode = st.text_input("🔑 Kode Lisensi (Serial Key):", value=lisensi_url, type="password", placeholder="Ketik admin12345 (atau Kode PRO-XXXXXX)")
    
    if st.button("🔓 Masuk & Buka Aplikasi", type="primary", use_container_width=True):
        if cek_validitas_lisensi(input_user, input_kode):
            st.session_state.lisensi_aktif = True
            st.session_state.user_aktif = input_user.strip()
            st.query_params["u"] = re.sub(r'[^a-z0-9]', '', input_user.lower())
            st.query_params["k"] = input_kode.strip()
            st.rerun()
        else:
            st.error("❌ Nama Pengguna atau Kode Lisensi TIDAK VALID!")
    
    st.markdown("---")
    with st.expander("🛠️ Panel Pemilik / Admin (Buat Kode Lisensi untuk Pembeli)"):
        pw_admin = st.text_input("Password Admin (Default: admin12345):", type="password")
        calon_pembeli = st.text_input("Nama Pembeli / Guru yang Didaftarkan:")
        if st.button("⚡ Buat Kode Lisensi"):
            if pw_admin == get_admin_password():
                if calon_pembeli.strip():
                    kode_baru = buat_kode_lisensi(calon_pembeli)
                    st.success(f"✅ **Lisensi Berhasil Dibuat!**\n\n- **Nama Pengguna:** `{calon_pembeli}`\n- **Kode Lisensi:** `{kode_baru}`")
                else:
                    st.warning("Isi nama pembeli terlebih dahulu.")
            else:
                st.error("Password Admin salah!")
    st.stop()

# ==========================================
# 🚀 FUNGSI PEMROSESAN GAMBAR & AI
# ==========================================
def prepare_image_and_b64(img, rotasi=0, max_size=950):
    img_fixed = ImageOps.exif_transpose(img).copy()
    if img_fixed.mode in ("RGBA", "P"):
        img_fixed = img_fixed.convert("RGB")
    if rotasi != 0:
        img_fixed = img_fixed.rotate(-rotasi, expand=True)
    img_fixed.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    
    buf = io.BytesIO()
    img_fixed.save(buf, format="JPEG", quality=80, optimize=True)
    byte_data = buf.getvalue()
    b64_str = base64.b64encode(byte_data).decode("utf-8")
    buf.seek(0)
    return Image.open(buf), b64_str

def parse_kunci_pg(teks):
    bagian_pg = re.split(r'(?:ESSAY|ESAI|URAIAN)', teks, flags=re.IGNORECASE)[0]
    pairs = re.findall(r'\b(\d+)\s*[\.\:\-\)]\s*([A-Ea-e])\b', bagian_pg)
    return {str(num): ans.upper() for num, ans in pairs}

def ambil_acuan_essay_saja(teks):
    match = re.search(r'(?:ESSAY|ESAI|URAIAN).*', teks, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(0)
    tanpa_pg = re.sub(r'\b\d+\s*[\.\:\-\)]\s*[A-Ea-e]\b', '', teks)
    return tanpa_pg.strip()

def deteksi_struktur_essay_dari_teks(teks):
    bagian_essay = teks
    match_bagian = re.search(r'(?:ESSAY|ESAI|URAIAN).*', teks, re.IGNORECASE | re.DOTALL)
    if match_bagian:
        bagian_essay = match_bagian.group(0)
    
    baris_list = bagian_essay.split('\n')
    ditemukan = []
    for b in baris_list:
        b_strip = b.strip()
        m = re.match(r'^(\d+)\s*[\.]?\s*([a-eA-E])?\s*[\.\:\)\-]\s*(.+)', b_strip)
        if m:
            angka = m.group(1)
            huruf = (m.group(2) or "").lower()
            isi = m.group(3).strip()
            if not huruf and re.match(r'^[A-Ea-e]$', isi):
                continue
            kode = f"{angka}{huruf}"
            if kode not in ditemukan:
                ditemukan.append(kode)
    return ", ".join(ditemukan)

def ekstrak_json_aman(teks):
    teks_bersih = re.sub(r"```json|```", "", teks).strip()
    match = re.search(r'\{.*\}', teks_bersih, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    return json.loads(teks_bersih)

def panggil_ai_stabil(api_key, prompt_text, b64_acuan, b64_siswa):
    model_tersedia = []
    try:
        list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        res_list = requests.get(list_url, timeout=8)
        if res_list.status_code == 200:
            for m in res_list.json().get("models", []):
                name = m.get("name", "").replace("models/", "")
                methods = m.get("supportedGenerationMethods", [])
                if "generateContent" in methods and ("flash" in name or "pro" in name) and "vision" not in name and "tts" not in name and "image" not in name:
                    model_tersedia.append(name)
    except Exception:
        pass
    
    m_lite = [m for m in model_tersedia if "lite" in m]
    m_20 = [m for m in model_tersedia if "2.0-flash" in m or "1.5-flash" in m]
    m_flash = [m for m in model_tersedia if "flash" in m]
    prioritas = m_lite + m_20 + m_flash + model_tersedia
    urutan_model = list(dict.fromkeys(prioritas)) if prioritas else ["gemini-2.0-flash-lite", "gemini-2.0-flash", "gemini-3.8-flash"]

    parts = [{"text": prompt_text}]
    if b64_acuan:
        parts.append({"text": "FOTO ACUAN GURU:"})
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64_acuan}})
    parts.append({"text": "FOTO LEMBAR JAWABAN SISWA:"})
    parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64_siswa}})

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json"
        }
    }

    detail_err = []
    for m_name in urutan_model[:6]:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m_name}:generateContent?key={api_key}"
            res = requests.post(url, json=payload, timeout=30)
            if res.status_code == 200:
                data = res.json()
                teks_hasil = data["candidates"][0]["content"]["parts"][0]["text"]
                return teks_hasil, m_name
            else:
                detail_err.append(f"{m_name}({res.status_code})")
                continue
        except Exception:
            detail_err.append(f"{m_name}(Timeout)")
            continue

    raise Exception(f"Koneksi sedang padat ({', '.join(detail_err[:3])}). Pastikan API Key Anda benar atau tunggu 20 detik lalu coba lagi.")

# ==========================================
# 📱 LAYAR UTAMA DENGAN KOTAK PENGATURAN DI ATAS (PASTI TAMPIL DI HP!)
# ==========================================
st.title("📝 Smart Koreksi Ujian AI")

# KOTAK PENGATURAN KHUSUS HP DI ATAS LAYAR (PENGGANTI SIDEBAR KIRI DI HP!)
with st.expander("📲 KLIK DI SINI UNTUK BUKA MENU PENGATURAN & API KEY (TAMPILAN HP)", expanded=False):
    st.info("💡 Menu ini sama persis dengan Sidebar Kiri di Laptop, khusus disediakan di atas agar mudah dibuka di layar HP!")
    api_key_hp = st.text_input("🔑 API Key Google AI Studio:", value=api_key_side, type="password", key="key_hp_top")
    if st.button("💾 Simpan API Key Saya", type="primary", use_container_width=True, key="btn_hp_top"):
        simpan_key_guru(st.session_state.user_aktif, api_key_hp)
        st.success("✅ API Key berhasil disimpan!")
        st.rerun()

    c_hp1, c_hp2 = st.columns(2)
    with c_hp1:
        st.session_state.bobot_pg_val = st.number_input("Total Poin Maksimal PG:", min_value=0, max_value=100, value=st.session_state.bobot_pg_val, key="b_pg_hp")
    with c_hp2:
        st.session_state.bobot_essay_val = st.number_input("Total Poin Maksimal Essay:", min_value=0, max_value=100, value=st.session_state.bobot_essay_val, key="b_es_hp")

    pilih_kls_hp = st.selectbox(
        "Pilih Cepat Struktur Essay:",
        [
            "Custom (Sesuai Kotak di Bawah)",
            "Kelas 7 (2 Soal: 1a, 1b, 2a, 2b)",
            "Kelas 8 (2 Soal: 1a, 1b, 2)",
            "Kelas 9 (3 Soal: 1a, 1b, 2a, 2b, 2c, 3)"
        ],
        key="kls_hp_top"
    )
    if pilih_kls_hp == "Kelas 7 (2 Soal: 1a, 1b, 2a, 2b)":
        st.session_state.struktur_essay_str = "1a, 1b, 2a, 2b"
    elif pilih_kls_hp == "Kelas 8 (2 Soal: 1a, 1b, 2)":
        st.session_state.struktur_essay_str = "1a, 1b, 2"
    elif pilih_kls_hp == "Kelas 9 (3 Soal: 1a, 1b, 2a, 2b, 2c, 3)":
        st.session_state.struktur_essay_str = "1a, 1b, 2a, 2b, 2c, 3"

    st.session_state.struktur_essay_str = st.text_input("Daftar Nomor/Anak Soal Essay:", value=st.session_state.struktur_essay_str, key="str_hp_top")
    
    if st.button("🚪 Keluar dari Lisensi", use_container_width=True, key="keluar_hp_top"):
        st.session_state.lisensi_aktif = False
        st.query_params.clear()
        st.rerun()

bobot_pg = st.session_state.bobot_pg_val
bobot_essay = st.session_state.bobot_essay_val
peta_poin_essay = hitung_skema_poin_essay(st.session_state.struktur_essay_str, bobot_essay)
rincian_skema = ", ".join([f"**No.{k}** = `{v}` poin" for k, v in peta_poin_essay.items()])
api_key_aktif = api_key_side.strip() if api_key_side.strip() else ambil_key_guru(st.session_state.user_aktif)

tab1, tab2, tab3 = st.tabs([
    "1️⃣ Acuan Guru", 
    "2️⃣ Foto Siswa", 
    "3️⃣ Rekap Nilai"
])

# TAB 1: ACUAN GURU
with tab1:
    st.subheader("📸 1. Upload / Ketik Acuan Penilaian (PG & Essay Jadi Satu)")
    st.info(f"⚖️ **Skema Essay Saat Ini (Total {bobot_essay} Poin):** {rincian_skema}")
    
    input_acuan_teks = st.text_area(
        "✍️ Ketik / Copy-Paste Kunci PG & Soal/Jawaban Essay di Sini:", 
        value=st.session_state.acuan_guru_teks,
        placeholder="Contoh:\nKUNCI PG:\n1.B 2.B 3.D 4.B 5.A 6.A 7.C 8.A 9.B 10.C 11.C 12.B 13.C 14.A 15.A\n\nKUNCI ESSAY:\n1a. 12 + 25 - 10 = 27\n1b. 2 x 3 : 6 = 1\n2a. 24 / 2 = 12\n2b. 1/3 + 2/3 = 3/3 = 1",
        height=180
    )

    foto_acuan = st.file_uploader(
        "📷 Atau Ambil Foto Lembar Soal & Kunci Guru (Opsional):", 
        type=["jpg", "jpeg", "png"], 
        key="up_acuan_gabungan"
    )
    
    if foto_acuan:
        rotasi_acuan = st.radio("Putar Foto Acuan:", [0, 90, 180, 270], horizontal=True, key="rot_acuan")
        img_ac, b64_ac = prepare_image_and_b64(Image.open(foto_acuan), rotasi=rotasi_acuan)
        st.session_state.acuan_guru_img = img_ac
        st.session_state.acuan_guru_b64 = b64_ac
        st.image(img_ac, caption="Foto Acuan Guru", use_container_width=True)

    if st.button("💾 Simpan Acuan Guru", type="primary", use_container_width=True):
        st.session_state.acuan_guru_teks = input_acuan_teks
        terdeteksi = deteksi_struktur_essay_dari_teks(input_acuan_teks)
        if terdeteksi:
            st.session_state.struktur_essay_str = terdeteksi
            peta_poin_essay = hitung_skema_poin_essay(terdeteksi, bobot_essay)
            
        kunci_cek = parse_kunci_pg(input_acuan_teks)
        info_pg = f"Terdeteksi **{len(kunci_cek)} soal PG** (1 soal = **{round(bobot_pg / len(kunci_cek), 2)} poin**)." if len(kunci_cek) > 0 else ""
        info_es = ", ".join([f"No.{k}={v}p" for k, v in peta_poin_essay.items()])
        st.success(f"✅ Acuan disimpan! {info_pg} Struktur Essay: **{info_es}**.")

# TAB 2: JAWABAN SISWA
with tab2:
    st.subheader("📱 2. Foto & Upload Lembar Jawaban Siswa")
    
    c1, c2 = st.columns(2)
    with c1:
        nama_siswa = st.text_input("Nama Siswa (Kosongkan agar dibaca AI):")
    with c2:
        kelas_siswa = st.text_input("Kelas / Mapel:", value="Matematika")

    file_siswa = st.file_uploader(
        "📸 Buka Kamera HP / Pilih Foto dari Galeri:", 
        type=["jpg", "jpeg", "png"], 
        key="up_siswa"
    )

    if file_siswa:
        raw_img = Image.open(file_siswa)
        rotasi = st.radio("Putar Foto Siswa (Pastikan Tegak Lurus):", [0, 90, 180, 270], horizontal=True, key="rot_siswa")
        
        img_siswa, b64_siswa = prepare_image_and_b64(raw_img, rotasi=rotasi, max_size=950)
        st.image(img_siswa, caption="Preview Lembar Jawaban Siswa", use_container_width=True)
        
        if st.button("🎯 Proses Koreksi Sekarang", type="primary", use_container_width=True):
            teks_acuan_final = input_acuan_teks if input_acuan_teks else st.session_state.acuan_guru_teks

            if not api_key_aktif:
                st.error("⚠️ Masukkan API Key Anda terlebih dahulu di kotak '📲 KLIK DI SINI UNTUK BUKA MENU PENGATURAN' di atas!")
            elif not st.session_state.acuan_guru_b64 and not teks_acuan_final:
                st.error("⚠️ Mohon ketik atau foto acuan guru di Tab 1 terlebih dahulu!")
            else:
                simpan_key_guru(st.session_state.user_aktif, api_key_aktif)
                waktu_mulai = time.time()
                with st.spinner("🔍 Membaca lembar siswa secara objektif..."):
                    try:
                        kunci_manual_dict = parse_kunci_pg(teks_acuan_final)
                        acuan_essay_saja = ambil_acuan_essay_saja(teks_acuan_final)
                        daftar_kode_essay = list(peta_poin_essay.keys())
                        contoh_json_essay = [{"no": k, "jwb": "tulisan siswa", "status": "BENAR"} for k in daftar_kode_essay]
                        
                        if st.session_state.mode_pg_val.startswith("Ketat"):
                            aturan_pg_prompt = """ATURAN KETAT MEMBACA PILIHAN GANDA (PG) - DILARANG MENEBAK!:
                            1. Siswa bisa menjawab dengan membulati hitam (●), melingkari (O), atau menyilang (X).
                            2. LIHAT TITIK TENGAH TANDA: Huruf yang sah HANYA huruf yang tepat berada di titik pusat/tengah silang atau bulatan.
                            3. ATURAN DISKUALIFIKASI (ISI DENGAN "RAGU"):
                               - Jika pada satu nomor terdapat BANYAK CORETAN KOTOR atau lebih dari 1 huruf yang disilang/dibulati tanpa kejelasan 100% mana yang dibatalkan, WAJIB tulis "RAGU" (JANGAN memilih salah satu huruf!).
                               - Jika tanda silang terlalu besar atau meleset di garis batas antara dua huruf sehingga tidak tepat di atas satu huruf, WAJIB tulis "RAGU".
                               - Hanya tuliskan huruf "A", "B", "C", atau "D" jika tandanya JELAS dan TIDAK MERAGUKAN."""
                        else:
                            aturan_pg_prompt = """ATURAN TOLERAN MEMBACA PILIHAN GANDA (PG):
                            1. Baca huruf yang disilang (X), dibulati hitam (●), atau dilingkari (O) pada tiap nomor.
                            2. Jika ada tanda yang dicoret tebal/garis datar (=) dan ada tanda lain yang bersih di baris yang sama, ambil huruf yang BERSIH. Jika keduanya sama-sama kotor/ganda tanpa pembatalan, tulis "GANDA"."""

                        teks_acuan_untuk_ai = acuan_essay_saja if len(kunci_manual_dict) > 0 else teks_acuan_final

                        prompt_text = f"""Anda adalah mesin pembaca optik (OCR) ujian yang sangat objektif dan tanpa kompromi.
                        
                        {aturan_pg_prompt}
                        
                        ACUAN ESSAY GURU:
                        {teks_acuan_untuk_ai}
                        
                        ATURAN ESSAY:
                        Periksa jawaban essay siswa untuk daftar nomor berikut: {', '.join(daftar_kode_essay)}.
                        1. BENAR: Jawaban yang nilainya SETARA secara matematis dengan kunci (contoh: `3/3` dan `1` sama-sama BENAR), atau hasil akhir benar walau tanpa langkah pengerjaan, atau kalimat teori semakna.
                        2. SALAH: Jika hasil akhirnya SALAH secara matematis (tidak setara dengan kunci), wajib beri status "SALAH"!
                        
                        Kembalikan HANYA format JSON berikut:
                        {{
                            "nama_terbaca": "Nama Siswa",
                            "jawaban_pg_siswa": {{"1": "B", "2": "RAGU", "3": "D"}},
                            "kunci_pg_guru": {{"1": "B"}},
                            "essay": {json.dumps(contoh_json_essay)}
                        }}"""

                        res_text, model_terpakai = panggil_ai_stabil(
                            api_key_aktif, 
                            prompt_text, 
                            st.session_state.acuan_guru_b64 if len(kunci_manual_dict) == 0 else None, 
                            b64_siswa
                        )
                        
                        hasil_json = ekstrak_json_aman(res_text)
                        
                        # 1. HITUNG POIN PG
                        jawaban_siswa_dict = {str(k): str(v).upper().strip() for k, v in hasil_json.get("jawaban_pg_siswa", {}).items()}
                        kunci_ai_dict = {str(k): str(v).upper().strip() for k, v in hasil_json.get("kunci_pg_guru", {}).items()}
                        
                        kunci_final_dict = kunci_manual_dict if len(kunci_manual_dict) > 0 else kunci_ai_dict
                        
                        if len(kunci_final_dict) > 0:
                            total_soal_pg = len(kunci_final_dict)
                            poin_per_soal_pg = bobot_pg / total_soal_pg
                            benar_pg = 0
                            nomor_salah = []
                            detail_per_nomor = []
                            
                            for no, kunci_benar in kunci_final_dict.items():
                                jwb_s = jawaban_siswa_dict.get(no, "-")
                                if jwb_s == kunci_benar:
                                    benar_pg += 1
                                    detail_per_nomor.append(f"{no}:{jwb_s}(✅)")
                                else:
                                    nomor_salah.append(f"No.{no} (Terbaca: {jwb_s}, Kunci: {kunci_benar})")
                                    detail_per_nomor.append(f"{no}:{jwb_s}[Kunci:{kunci_benar}](❌)")
                            
                            poin_pg = round(benar_pg * poin_per_soal_pg, 2)
                            info_salah = f"Salah/Ragu di: {', '.join(nomor_salah)}" if nomor_salah else "Benar Semua!"
                            rincian_pg_teks = f"Benar {benar_pg} dari {total_soal_pg} soal x {round(poin_per_soal_pg, 2)} poin = {poin_pg} poin ({info_salah})"
                        else:
                            poin_pg = 0.0
                            rincian_pg_teks = "Tidak ada kunci PG"
                            detail_per_nomor = []

                        # 2. HITUNG POIN ESSAY SESUAI STRUKTUR
                        list_essay = hasil_json.get("essay", [])
                        poin_essay = 0.0
                        rincian_butir_list = []
                        
                        hasil_ai_map = {}
                        for item in list_essay:
                            kode_norm = re.sub(r'[^0-9a-z]', '', str(item.get("no", "")).lower())
                            hasil_ai_map[kode_norm] = item

                        for kode_soal, bobot_butir in peta_poin_essay.items():
                            item_ai = hasil_ai_map.get(kode_soal, {})
                            jwb_e = item_ai.get("jwb", "-")
                            stat_e = str(item_ai.get("status", "SALAH")).upper()
                            if "BENAR" in stat_e and "SALAH" not in stat_e:
                                p_e = bobot_butir
                                ikon_e = "✅"
                            else:
                                p_e = 0.0
                                ikon_e = "❌"
                            poin_essay += p_e
                            rincian_butir_list.append(f"No.{kode_soal} (Dijawab: {jwb_e}) -> {ikon_e} {stat_e} [{p_e} / {bobot_butir} poin]")

                        if abs(poin_essay - bobot_essay) < 0.15:
                            poin_essay = float(bobot_essay)
                        else:
                            poin_essay = round(min(max(poin_essay, 0.0), float(bobot_essay)), 2)
                            
                        detail_essay_teks = " | ".join(rincian_butir_list)
                        nilai_akhir = round(poin_pg + poin_essay, 2)
                        durasi = round(time.time() - waktu_mulai, 1)

                        nama_final = nama_siswa.strip() if nama_siswa.strip() else hasil_json.get("nama_terbaca", f"Siswa {len(st.session_state.data_nilai)+1}")

                        st.session_state.data_nilai.append({
                            "Nama Siswa": nama_final,
                            "Kelas": kelas_siswa,
                            f"Poin PG (Maks {bobot_pg})": poin_pg,
                            f"Poin Essay (Maks {bobot_essay})": poin_essay,
                            "Nilai Akhir (Total)": nilai_akhir,
                            "Rincian PG": rincian_pg_teks,
                            "Catatan Essay": detail_essay_teks,
                            "Status": "⏳ Sementara (Perlu Review)"
                        })
                        
                        gc.collect()
                        
                        st.success(f"✅ Berhasil dalam **{durasi} detik** (Mesin: `{model_terpakai}`)! Siswa: **{nama_final}**")
                        col_r1, col_r2, col_r3 = st.columns(3)
                        col_r1.metric(f"Poin PG (Maks {bobot_pg})", poin_pg)
                        col_r2.metric(f"Poin Essay (Maks {bobot_essay})", poin_essay)
                        col_r3.metric("Nilai Akhir (PG + Essay)", nilai_akhir)
                        
                        st.info(f"**Perhitungan PG:** {rincian_pg_teks}\n\n**Per Nomor PG:** {', '.join(detail_per_nomor)}\n\n**Verifikasi Per Nomor Essay:**\n" + "\n".join([f"- {x}" for x in rincian_butir_list]))
                        
                    except Exception as e:
                        st.error(f"⚠️ {e}")

# TAB 3: REVIEW GURU
with tab3:
    st.subheader("👨‍🏫 3. Verifikasi & Persetujuan Guru")
    if len(st.session_state.data_nilai) == 0:
        st.info("Belum ada lembar jawaban siswa yang dikoreksi.")
    else:
        st.session_state.data_nilai = [row for row in st.session_state.data_nilai if row.get("Nama Siswa") is not None]
        df = pd.DataFrame(st.session_state.data_nilai)
        edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)
        st.session_state.data_nilai = edited_df.to_dict('records')

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            if st.button("✅ Setujui Semua Nilai", type="primary", use_container_width=True):
                for item in st.session_state.data_nilai:
                    item["Status"] = "✅ Disetujui Guru (Final)"
                st.rerun()
        with col_b:
            csv = edited_df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download Excel/CSV", data=csv, file_name="Rekap_Nilai_Ujian.csv", mime="text/csv", use_container_width=True)
        with col_c:
            if st.button("🗑️ Kosongkan Tabel", use_container_width=True):
                st.session_state.data_nilai = []
                st.rerun()
