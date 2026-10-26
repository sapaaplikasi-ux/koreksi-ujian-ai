import streamlit as st
import google.generativeai as genai
from PIL import Image, ImageOps
import pandas as pd
import json
import re
import os
import time
import io

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

def save_key(k):
    try:
        with open(KEY_FILE, "w") as f:
            f.write(k.strip())
    except Exception:
        pass

# Kompresi super ringan (<80 KB) agar cepat terkirim meski sinyal HP lambat
def prepare_image(img, rotasi=0, max_size=1100):
    img_fixed = ImageOps.exif_transpose(img).copy()
    if img_fixed.mode in ("RGBA", "P"):
        img_fixed = img_fixed.convert("RGB")
    if rotasi != 0:
        img_fixed = img_fixed.rotate(-rotasi, expand=True)
    img_fixed.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    
    # Kompresi ke buffer JPEG kualitas 80% agar ukuran byte sangat kecil tapi teks tajam
    buf = io.BytesIO()
    img_fixed.save(buf, format="JPEG", quality=80, optimize=True)
    buf.seek(0)
    return Image.open(buf)

def parse_kunci_pg(teks):
    pairs = re.findall(r'\b(\d+)\s*[\.\:\-\)]\s*([A-Ea-e])\b', teks)
    return {str(num): ans.upper() for num, ans in pairs}

# FUNGSI ANTI-LIMIT (OTOMATIS GANTI MODEL JIKA KUOTA PENUH & TANPA LOADING LAMA)
def generate_with_fallback(prompt_parts, model_utama):
    daftar_model = [model_utama, "gemini-2.0-flash", "gemini-3.8-flash-lite", "gemini-3.8-flash", "gemini-3.8-pro"]
    # Hapus duplikat dengan menjaga urutan
    urutan_model = list(dict.fromkeys(daftar_model))
    
    generation_config = {
        "temperature": 0.0,
        "top_p": 1.0,
        "top_k": 1,
        "response_mime_type": "application/json"
    }
    
    last_error = None
    for m_name in urutan_model:
        try:
            model = genai.GenerativeModel(m_name, generation_config=generation_config)
            # Timeout 25 detik agar tidak pernah nyangkut sampai 3-4 menit
            response = model.generate_content(prompt_parts, request_options={"timeout": 25})
            return response, m_name
        except Exception as e:
            err_str = str(e)
            last_error = err_str
            # Jika kena limit 429, timeout, atau model tidak tersedia, langsung loncat ke model berikutnya
            if "429" in err_str or "Quota" in err_str or "404" in err_str or "Deadline" in err_str or "503" in err_str:
                time.sleep(1)
                continue
            else:
                continue
    raise Exception(f"Semua jalur model sedang sibuk. Silakan tunggu 30 detik lalu coba lagi. Detail: {last_error}")

st.title("📝 Aplikasi Koreksi Ujian AI (Anti-Limit ⚡)")
st.caption("SMPN 4 Tamban - Koreksi Otomatis PG & Essay")
st.markdown("---")

with st.sidebar:
    st.header("⚙️ Konfigurasi Sistem")
    saved_api = load_key()
    api_key = st.text_input("Google Gemini API Key:", value=saved_api, type="password")
    if api_key and api_key != saved_api:
        save_key(api_key)
        st.success("✅ API Key aktif!")
    
    pilihan_model = st.selectbox(
        "Model AI Utama (Otomatis pindah ke cadangan jika limit):", 
        ["gemini-2.0-flash", "gemini-3.8-flash", "gemini-3.8-pro"], 
        index=0
    )
    
    st.markdown("---")
    bobot_pg = st.number_input("Bobot Total Nilai PG (%):", min_value=0, max_value=100, value=60)
    bobot_essay = st.number_input("Bobot Total Nilai Essay (%):", min_value=0, max_value=100, value=40)

if "acuan_guru_img" not in st.session_state:
    st.session_state.acuan_guru_img = None
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
    st.info("💡 Cukup **sekali upload** foto kertas yang berisi Kunci PG sekaligus Soal & Jawaban Essay, atau ketik langsung di bawah.")
    
    foto_acuan = st.file_uploader(
        "📷 Ambil Foto / Pilih dari Galeri (Kunci PG + Soal & Jawaban Essay):", 
        type=["jpg", "jpeg", "png"], 
        key="up_acuan_gabungan"
    )
    
    if foto_acuan:
        rotasi_acuan = st.radio(
            "Putar Foto Acuan (Jika Miring):", 
            [0, 90, 180, 270], 
            format_func=lambda x: f"Putar {x}°" if x > 0 else "Normal (0°)", 
            horizontal=True,
            key="rot_acuan"
        )
        st.session_state.acuan_guru_img = prepare_image(Image.open(foto_acuan), rotasi=rotasi_acuan)
        st.image(st.session_state.acuan_guru_img, caption="Foto Acuan Guru (PG & Essay)", use_container_width=True)

    input_acuan_teks = st.text_area(
        "✍️ Atau Ketik / Copy-Paste Kunci PG & Essay Sekaligus di Sini (Sangat Cepat & Hemat Kuota):", 
        value=st.session_state.acuan_guru_teks,
        placeholder="Contoh:\nKUNCI PG:\n1.B 2.B 3.D 4.B 5.A\n\nKUNCI ESSAY:\n1a. 12 + 25 - 10 = 27\n1b. 2 x 3 : 6 = 1",
        height=180
    )

    if st.button("💾 Simpan Acuan Guru", type="primary", use_container_width=True):
        st.session_state.acuan_guru_teks = input_acuan_teks
        st.success("✅ Acuan penilaian berhasil disimpan! Silakan pindah ke Tab 2.")

# TAB 2: JAWABAN SISWA
with tab2:
    st.subheader("📱 2. Foto & Upload Lembar Jawaban Siswa")
    
    c1, c2 = st.columns(2)
    with c1:
        nama_siswa = st.text_input("Nama Siswa (Kosongkan agar dibaca AI):")
    with c2:
        kelas_siswa = st.text_input("Kelas / Mapel:", value="Kelas 7 - Matematika")

    st.caption("Klik tombol di bawah, lalu pilih **Kamera** atau pilih dari **Galeri**:")
    file_siswa = st.file_uploader(
        "📸 Buka Kamera HP / Pilih Foto dari Galeri:", 
        type=["jpg", "jpeg", "png"], 
        key="up_siswa"
    )

    if file_siswa:
        raw_img = Image.open(file_siswa)
        st.markdown("##### 🔄 Atur Posisi Foto (Pastikan Tegak Lurus)")
        rotasi = st.radio(
            "Putar Foto Siswa:", 
            [0, 90, 180, 270], 
            format_func=lambda x: f"Putar {x}°" if x > 0 else "Normal (0°)", 
            horizontal=True,
            key="rot_siswa"
        )
        
        img_siswa = prepare_image(raw_img, rotasi=rotasi, max_size=1100)
        st.image(img_siswa, caption="Preview Lembar Jawaban Siswa", use_container_width=True)
        
        if st.button("🎯 Proses Koreksi Cepat & Akurat (AI)", type="primary", use_container_width=True):
            teks_acuan_final = input_acuan_teks if input_acuan_teks else st.session_state.acuan_guru_teks

            if not api_key:
                st.error("⚠️ Masukkan Google Gemini API Key terlebih dahulu di menu sebelah kiri!")
            elif not st.session_state.acuan_guru_img and not teks_acuan_final:
                st.error("⚠️ Mohon upload foto atau ketik acuan guru di Tab 1 terlebih dahulu!")
            else:
                waktu_mulai = time.time()
                with st.spinner("⚡ Mengoreksi jawaban siswa (Otomatis mencari jalur server tercepat)..."):
                    try:
                        genai.configure(api_key=api_key)
                        
                        prompt_parts = [
                            f"""Anda adalah sistem OCR dan korektor ujian tingkat presisi tinggi.
                            
                            ATURAN KETAT MEMBACA TABEL PILIHAN GANDA (PG):
                            1. Baca setiap baris nomor dengan teliti.
                            2. ATURAN CORETAN / GANTI JAWABAN: Jika pada satu nomor terdapat tanda silang (X) yang DICORET dengan garis mendatar/tebal (seperti tanda '=' di atas X) dan ada tanda silang (X) lain yang bersih di sebelahnya, maka tanda yang dicoret itu BATAL. Pilihlah huruf yang memiliki tanda silang (X) BERSIH sebagai jawaban sah siswa (BUKAN jawaban ganda).
                            3. Abaikan nomor yang dibiarkan kosong semua.
                            
                            Tugas Anda:
                            - Baca Nama Siswa yang tertulis di lembar jawaban.
                            - Dari ACUAN GURU, ekstrak kunci jawaban PG ke dalam "kunci_pg_guru" (contoh: {{"1": "B", "2": "B"}}).
                            - Dari LEMBAR JAWABAN SISWA, ekstrak huruf jawaban PG siswa yang terisi pada setiap nomor ke dalam "jawaban_pg_siswa" (contoh: {{"1": "B", "2": "B"}}).
                            - Periksa jawaban Essay siswa dibandingkan dengan Acuan Essay Guru, lalu berikan "skor_essay" (skala 0-100) dan "detail_essay".
                            
                            Kembalikan HANYA format JSON berikut:
                            {{
                                "nama_terbaca": "Nama di kertas",
                                "jawaban_pg_siswa": {{"1": "B", "2": "B"}},
                                "kunci_pg_guru": {{"1": "B", "2": "B"}},
                                "skor_essay": 100,
                                "detail_essay": "Penjelasan singkat koreksi tiap nomor essay"
                            }}"""
                        ]
                        
                        if st.session_state.acuan_guru_img:
                            prompt_parts.append("FOTO ACUAN GURU:")
                            prompt_parts.append(st.session_state.acuan_guru_img)
                        if teks_acuan_final:
                            prompt_parts.append(f"TEKS ACUAN GURU: {teks_acuan_final}")

                        prompt_parts.append("FOTO LEMBAR JAWABAN SISWA:")
                        prompt_parts.append(img_siswa)

                        # Panggil fungsi Anti-Limit dengan Auto-Fallback
                        response, model_terpakai = generate_with_fallback(prompt_parts, pilihan_model)
                        cleaned_text = re.sub(r"```json|```", "", response.text).strip()
                        hasil_json = json.loads(cleaned_text)
                        
                        jawaban_siswa_dict = {str(k): str(v).upper().strip() for k, v in hasil_json.get("jawaban_pg_siswa", {}).items()}
                        kunci_ai_dict = {str(k): str(v).upper().strip() for k, v in hasil_json.get("kunci_pg_guru", {}).items()}
                        kunci_manual_dict = parse_kunci_pg(teks_acuan_final)
                        
                        kunci_final_dict = kunci_ai_dict if len(kunci_ai_dict) >= len(kunci_manual_dict) else kunci_manual_dict
                        
                        if len(kunci_final_dict) > 0:
                            total_soal_pg = len(kunci_final_dict)
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
                            
                            skor_pg = round((benar_pg / total_soal_pg) * 100, 2)
                            info_salah = f"Salah di: {', '.join(nomor_salah)}" if nomor_salah else "Benar Semua!"
                            rincian_pg_teks = f"Benar {benar_pg} dari {total_soal_pg} soal ({info_salah})"
                        else:
                            skor_pg = 0.0
                            rincian_pg_teks = "Tidak ada kunci PG (Hanya Essay)"
                            detail_per_nomor = []

                        skor_essay = float(hasil_json.get("skor_essay", 0))
                        nilai_akhir = round((skor_pg * bobot_pg / 100.0) + (skor_essay * bobot_essay / 100.0), 2)
                        durasi = round(time.time() - waktu_mulai, 1)

                        nama_final = nama_siswa.strip() if nama_siswa.strip() else hasil_json.get("nama_terbaca", f"Siswa {len(st.session_state.data_nilai)+1}")

                        st.session_state.data_nilai.append({
                            "Nama Siswa": nama_final,
                            "Kelas": kelas_siswa,
                            "Skor PG": skor_pg,
                            "Skor Essay": skor_essay,
                            "Nilai Akhir": nilai_akhir,
                            "Rincian PG": rincian_pg_teks,
                            "Catatan Essay": hasil_json.get("detail_essay", ""),
                            "Status": "⏳ Sementara (Perlu Review)"
                        })
                        
                        st.success(f"✅ Selesai dalam **{durasi} detik** (Menggunakan jalur: `{model_terpakai}`)! Nama: **{nama_final}**")
                        col_r1, col_r2, col_r3 = st.columns(3)
                        col_r1.metric("Skor PG", skor_pg)
                        col_r2.metric("Skor Essay", skor_essay)
                        col_r3.metric("Nilai Akhir", nilai_akhir)
                        
                        st.info(f"**Rincian PG:** {rincian_pg_teks}\n\n**Per Nomor:** {', '.join(detail_per_nomor)}\n\n**Catatan Essay:** {hasil_json.get('detail_essay', '')}")
                        
                    except Exception as e:
                        st.error(f"Gagal memproses: {e}")

# TAB 3: REVIEW GURU
with tab3:
    st.subheader("👨‍🏫 3. Verifikasi & Persetujuan Guru")
    st.caption("Nilai masih bersifat SEMENTARA. Klik angka pada tabel jika ingin merevisi nilai sebelum disetujui.")
    
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
