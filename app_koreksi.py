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

st.set_page_config(page_title="Koreksi Ujian AI - SMPN 4 Tamban", layout="wide")

KEY_FILE = "api_key_saved.txt"
def load_key():
    try:
        if "GEMINI_API_KEY" in st.secrets:
            return st.secrets["GEMINI_API_KEY"].strip()
    except Exception:
        pass
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "r") as f:
            return f.read().strip()
    return ""

# Kompresi gambar & ubah ke Base64 agar pengiriman stabil & cepat
def prepare_image_and_b64(img, rotasi=0, max_size=1024):
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
    pairs = re.findall(r'\b(\d+)\s*[\.\:\-\)]\s*([A-Ea-e])\b', teks)
    return {str(num): ans.upper() for num, ans in pairs}

# FUNGSI JALUR LANGSUNG HTTP
def panggil_ai_stabil(api_key, prompt_text, b64_acuan, b64_siswa, provider):
    if provider == "Groq Vision (Super Cepat 2 Detik)" or api_key.startswith("gsk_"):
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        content_list = [{"type": "text", "text": prompt_text}]
        if b64_acuan:
            content_list.append({"type": "text", "text": "FOTO ACUAN GURU:"})
            content_list.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_acuan}"}})
        content_list.append({"type": "text", "text": "FOTO LEMBAR JAWABAN SISWA:"})
        content_list.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_siswa}"}})
        
        payload = {
            "model": "meta-llama/llama-4-scout-17b-16e-instruct",
            "messages": [{"role": "user", "content": content_list}],
            "temperature": 0.1,
            "response_format": {"type": "json_object"}
        }
        res = requests.post(url, headers=headers, json=payload, timeout=25)
        if res.status_code == 200:
            return res.json()["choices"][0]["message"]["content"], "Groq Llama-4 Vision"
        else:
            raise Exception(f"Groq Error ({res.status_code}): {res.text}")

    list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    res_list = requests.get(list_url, timeout=10)
    model_tersedia = []
    if res_list.status_code == 200:
        for m in res_list.json().get("models", []):
            name = m.get("name", "").replace("models/", "")
            methods = m.get("supportedGenerationMethods", [])
            if "generateContent" in methods and ("flash" in name or "pro" in name) and "vision" not in name:
                model_tersedia.append(name)
    
    prioritas = [m for m in model_tersedia if "lite" in m] + [m for m in model_tersedia if "flash" in m and "lite" not in m] + model_tersedia
    urutan_model = list(dict.fromkeys(prioritas)) if prioritas else ["gemini-3.8-flash", "gemini-2.0-flash"]

    parts = [{"text": prompt_text}]
    if b64_acuan:
        parts.append({"text": "FOTO ACUAN GURU:"})
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64_acuan}})
    parts.append({"text": "FOTO LEMBAR JAWABAN SISWA:"})
    parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64_siswa}})

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json"
        }
    }

    detail_err = ""
    for m_name in urutan_model[:4]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m_name}:generateContent?key={api_key}"
        res = requests.post(url, json=payload, timeout=20)
        if res.status_code == 200:
            data = res.json()
            teks_hasil = data["candidates"][0]["content"]["parts"][0]["text"]
            return teks_hasil, m_name
        else:
            detail_err = f"[{m_name}: Kode {res.status_code}]"
            if res.status_code == 429:
                continue
    raise Exception(f"Kuota Google Gemini sedang penuh ({detail_err}). Silakan tunggu sebentar atau gunakan Groq.")

st.title("📝 Aplikasi Koreksi Ujian AI (Sistem Poin Langsung 🎯)")
st.caption("SMPN 4 Tamban - Koreksi Otomatis PG & Essay")
st.markdown("---")

with st.sidebar:
    st.header("⚙️ Konfigurasi Sistem")
    provider_ai = st.radio(
        "Pilih Mesin AI:",
        ["Google Gemini (Standar)", "Groq Vision (Super Cepat 2 Detik)"]
    )
    
    saved_api = load_key()
    api_key = st.text_input("Masukkan API Key:", value=saved_api, type="password")
    
    st.markdown("---")
    st.subheader("📊 Pengaturan Poin & Bobot")
    bobot_pg = st.number_input("Total Poin Maksimal PG:", min_value=0, max_value=100, value=60, help="Contoh: 60 poin. Jika ada 15 soal PG, maka 1 soal otomatis bernilai 4 poin.")
    bobot_essay = st.number_input("Total Poin Maksimal Essay:", min_value=0, max_value=100, value=40, help="Contoh: 40 poin. Jika ada 2 soal (masing-masing 2 anak soal = 4 butir), maka tiap anak soal bernilai 10 poin (1 soal utuh = 20 poin).")
    
    jml_butir_essay = st.number_input(
        "Jumlah Total Butir / Anak Soal Essay:", 
        min_value=1, max_value=50, value=4,
        help="Isi total anak soal essay. Contoh: 2 soal essay yang masing-masing punya anak soal a dan b berarti totalnya 4 butir (masing-masing bernilai 10 poin)."
    )
    poin_per_butir_essay = round(bobot_essay / jml_butir_essay, 2)
    st.caption(f"ℹ️ **Info Essay:** Dengan {jml_butir_essay} butir anak soal, maka setiap 1 anak soal benar mendapat **{poin_per_butir_essay} poin** (Total Maks: **{bobot_essay} poin**).")

    st.markdown("---")
    st.subheader("🧠 Gaya Koreksi Essay")
    mode_essay = st.radio(
        "Cara AI Menilai Essay:",
        [
            "Fleksibel & Kontekstual (Menilai makna, cara alternatif, & skor langkah)",
            "Ketat (Harus sama persis dengan kunci guru)"
        ],
        index=0
    )

if "acuan_guru_img" not in st.session_state:
    st.session_state.acuan_guru_img = None
if "acuan_guru_b64" not in st.session_state:
    st.session_state.acuan_guru_b64 = None
if "acuan_guru_teks" not in st.session_state:
    st.session_state.acuan_guru_teks = ""
if "data_nilai" not in st.session_state:
    st.session_state.data_nilai = []

tab1, tab2, tab3 = st.tabs([
    "1️⃣ Acuan Guru", 
    "2️⃣ Foto Jawaban Siswa", 
    "3️⃣ Rekap & Setujui"
])

# TAB 1: ACUAN GURU
with tab1:
    st.subheader("📸 1. Upload / Ketik Acuan Penilaian (PG & Essay Jadi Satu)")
    st.info("💡 Ketik atau foto Kunci PG beserta Soal/Jawaban Essay Anda. Poin per nomor akan dihitung otomatis sesuai bobot di sebelah kiri.")
    
    input_acuan_teks = st.text_area(
        "✍️ Ketik / Copy-Paste Kunci PG & Soal/Jawaban Essay di Sini:", 
        value=st.session_state.acuan_guru_teks,
        placeholder="Contoh:\nKUNCI PG:\n1.B 2.B 3.D 4.B 5.A 6.A 7.C 8.A 9.B 10.C 11.C 12.B 13.C 14.A 15.A\n\nKUNCI ESSAY:\n1a. 12 + 25 - 10 = 27\n1b. 2 x 3 : 6 = 1\n2a. 24/2 = 12\n2b. 1/3 + 2/3 = 3/3 = 1",
        height=180
    )

    foto_acuan = st.file_uploader(
        "📷 Atau Ambil Foto Lembar Soal & Kunci Guru:", 
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
        kunci_cek = parse_kunci_pg(input_acuan_teks)
        if len(kunci_cek) > 0:
            poin_pg_per_no = round(bobot_pg / len(kunci_cek), 2)
            st.success(f"✅ Acuan disimpan! Terdeteksi **{len(kunci_cek)} soal PG** (1 soal benar = **{poin_pg_per_no} poin**, Total PG Maks = **{bobot_pg} poin**).")
        else:
            st.success("✅ Acuan penilaian berhasil disimpan! Silakan pindah ke Tab 2.")

# TAB 2: JAWABAN SISWA
with tab2:
    st.subheader("📱 2. Foto & Upload Lembar Jawaban Siswa")
    
    c1, c2 = st.columns(2)
    with c1:
        nama_siswa = st.text_input("Nama Siswa (Kosongkan agar dibaca AI):")
    with c2:
        kelas_siswa = st.text_input("Kelas / Mapel:", value="Kelas 7 - Matematika")

    file_siswa = st.file_uploader(
        "📸 Buka Kamera HP / Pilih Foto dari Galeri:", 
        type=["jpg", "jpeg", "png"], 
        key="up_siswa"
    )

    if file_siswa:
        raw_img = Image.open(file_siswa)
        rotasi = st.radio("Putar Foto Siswa (Pastikan Tegak Lurus):", [0, 90, 180, 270], horizontal=True, key="rot_siswa")
        
        img_siswa, b64_siswa = prepare_image_and_b64(raw_img, rotasi=rotasi, max_size=1024)
        st.image(img_siswa, caption="Preview Lembar Jawaban Siswa", use_container_width=True)
        
        if st.button("🎯 Proses Koreksi Sekarang", type="primary", use_container_width=True):
            teks_acuan_final = input_acuan_teks if input_acuan_teks else st.session_state.acuan_guru_teks

            if not api_key:
                st.error("⚠️ Masukkan API Key terlebih dahulu di menu sebelah kiri!")
            elif not st.session_state.acuan_guru_b64 and not teks_acuan_final:
                st.error("⚠️ Mohon ketik atau foto acuan guru di Tab 1 terlebih dahulu!")
            else:
                waktu_mulai = time.time()
                with st.spinner("🧠 AI sedang menghitung poin PG & Essay siswa..."):
                    try:
                        if "Fleksibel" in mode_essay:
                            instruksi_essay = f"""ATURAN PENILAIAN & POIN ESSAY (FLEKSIBEL & KONTEKSTUAL):
                            - Total Poin Maksimal untuk seluruh Essay adalah {bobot_essay} poin.
                            - Terdapat {jml_butir_essay} butir/anak soal essay, sehingga setiap 1 butir anak soal (misal 1a, 1b, 2a, 2b) memiliki nilai maksimal {poin_per_butir_essay} poin (Jika 1 nomor terdiri dari 2 anak soal dan keduanya benar, maka mendapat {poin_per_butir_essay * 2} poin).
                            - Jangan menilai kaku kata-per-kata! Jika jawaban siswa secara substansi, konsep, atau cara matematis BENAR dan sesuai soal, berikan poin penuh ({poin_per_butir_essay} poin) untuk butir tersebut.
                            - Jika langkah pengerjaan benar namun hasil akhir sedikit keliru, berikan poin sebagian secara bijaksana.
                            - Jumlahkan poin dari seluruh butir essay siswa ke dalam "poin_essay" (rentang 0 sampai {bobot_essay})."""
                        else:
                            instruksi_essay = f"""ATURAN PENILAIAN & POIN ESSAY (KETAT):
                            - Total Poin Maksimal seluruh Essay adalah {bobot_essay} poin ({jml_butir_essay} butir anak soal, masing-masing bernilai {poin_per_butir_essay} poin).
                            - Jumlahkan poin essay yang benar ke dalam "poin_essay" (rentang 0 sampai {bobot_essay})."""

                        prompt_text = f"""Anda adalah guru pengoreksi ujian yang cerdas, objektif, dan bijaksana.
                        ACUAN GURU (TEKS):
                        {teks_acuan_final}
                        
                        ATURAN MEMBACA PILIHAN GANDA (PG):
                        1. Baca setiap baris nomor dengan teliti.
                        2. Jika ada tanda silang (X) yang dicoret tebal/garis datar dan ada tanda silang (X) lain yang bersih di baris yang sama, maka yang dicoret itu BATAL. Ambil tanda silang (X) yang bersih.
                        3. Abaikan nomor yang kosong.
                        
                        {instruksi_essay}
                        
                        Kembalikan HANYA JSON valid dengan struktur persis seperti ini:
                        {{
                            "nama_terbaca": "Nama Siswa di Kertas",
                            "jawaban_pg_siswa": {{"1": "B", "2": "B"}},
                            "kunci_pg_guru": {{"1": "B", "2": "B"}},
                            "poin_essay": {bobot_essay},
                            "detail_essay": "Rincian poin tiap nomor/anak soal essay (contoh: No.1a: {poin_per_butir_essay} poin, No.1b: {poin_per_butir_essay} poin [Total No.1 = {poin_per_butir_essay*2} poin], dst)"
                        }}"""

                        res_text, model_terpakai = panggil_ai_stabil(
                            api_key.strip(), 
                            prompt_text, 
                            st.session_state.acuan_guru_b64, 
                            b64_siswa, 
                            provider_ai
                        )
                        
                        cleaned_text = re.sub(r"```json|```", "", res_text).strip()
                        hasil_json = json.loads(cleaned_text)
                        
                        jawaban_siswa_dict = {str(k): str(v).upper().strip() for k, v in hasil_json.get("jawaban_pg_siswa", {}).items()}
                        kunci_ai_dict = {str(k): str(v).upper().strip() for k, v in hasil_json.get("kunci_pg_guru", {}).items()}
                        kunci_manual_dict = parse_kunci_pg(teks_acuan_final)
                        
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
                                    nomor_salah.append(f"No.{no} (Dijawab {jwb_s}, Kunci {kunci_benar})")
                                    detail_per_nomor.append(f"{no}:{jwb_s}[Kunci:{kunci_benar}](❌)")
                            
                            poin_pg = round(benar_pg * poin_per_soal_pg, 2)
                            info_salah = f"Salah di: {', '.join(nomor_salah)}" if nomor_salah else "Benar Semua!"
                            rincian_pg_teks = f"Benar {benar_pg} dari {total_soal_pg} soal x {round(poin_per_soal_pg, 2)} poin = {poin_pg} poin ({info_salah})"
                        else:
                            poin_pg = 0.0
                            rincian_pg_teks = "Tidak ada kunci PG"
                            detail_per_nomor = []

                        poin_essay = float(hasil_json.get("poin_essay", 0))
                        # Pastikan poin essay tidak melebihi batas bobot_essay
                        if poin_essay > bobot_essay:
                            poin_essay = float(bobot_essay)
                            
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
                            "Rincian Poin Essay": hasil_json.get("detail_essay", ""),
                            "Status": "⏳ Sementara (Perlu Review)"
                        })
                        
                        st.success(f"✅ Berhasil dalam **{durasi} detik** (Mesin: `{model_terpakai}`)! Siswa: **{nama_final}**")
                        col_r1, col_r2, col_r3 = st.columns(3)
                        col_r1.metric(f"Poin PG (Maks {bobot_pg})", poin_pg)
                        col_r2.metric(f"Poin Essay (Maks {bobot_essay})", poin_essay)
                        col_r3.metric("Nilai Akhir (PG + Essay)", nilai_akhir)
                        
                        st.info(f"**Perhitungan PG:** {rincian_pg_teks}\n\n**Per Nomor PG:** {', '.join(detail_per_nomor)}\n\n**Rincian Poin Essay:** {hasil_json.get('detail_essay', '')}")
                        
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
