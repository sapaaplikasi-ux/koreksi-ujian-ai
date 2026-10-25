import streamlit as st
import google.generativeai as genai
from PIL import Image, ImageOps
import pandas as pd
import json
import re
import os
import time

st.set_page_config(page_title="Koreksi Ujian AI Akurat - SMPN 4 Tamban", layout="wide")

KEY_FILE = "api_key_saved.txt"
def load_key():
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "r") as f:
            return f.read().strip()
    return ""

def save_key(k):
    with open(KEY_FILE, "w") as f:
        f.write(k.strip())

# Kompresi dengan memperbaiki orientasi EXIF kamera HP & ketajaman tinggi (1600px)
def prepare_image(img, rotasi=0, max_size=1600):
    img_fixed = ImageOps.exif_transpose(img).copy()
    if img_fixed.mode in ("RGBA", "P"):
        img_fixed = img_fixed.convert("RGB")
    if rotasi != 0:
        img_fixed = img_fixed.rotate(-rotasi, expand=True)
    img_fixed.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    return img_fixed

# Fungsi ekstrak kunci PG dari teks guru (Contoh: "1.A 2.B" -> {"1": "A", "2": "B"})
def parse_kunci_pg(teks):
    pairs = re.findall(r'(\d+)\s*[\.\:\-\)]?\s*([A-Ea-e])', teks)
    return {str(num): ans.upper() for num, ans in pairs}

st.title("📝 Aplikasi Koreksi Ulangan PG & Essay Berbasis AI (Akurasi Tinggi 🎯)")
st.markdown("Pastikan posisi foto **Tegak Lurus (Tidak Miring)** sebelum diproses agar pembacaan tabel PG 100% akurat dan konsisten.")
st.markdown("---")

with st.sidebar:
    st.header("⚙️ Konfigurasi Sistem")
    saved_api = load_key()
    api_key = st.text_input("Masukkan Google Gemini API Key:", value=saved_api, type="password")
    if api_key and api_key != saved_api:
        save_key(api_key)
        st.success("✅ API Key tersimpan otomatis!")
    
    pilihan_model = st.selectbox(
        "Model AI:", 
        ["gemini-3.8-flash", "gemini-3.8-pro", "gemini-2.0-flash"], 
        index=0
    )
    
    st.markdown("---")
    bobot_pg = st.number_input("Bobot Total Nilai PG (%):", min_value=0, max_value=100, value=60)
    bobot_essay = st.number_input("Bobot Total Nilai Essay (%):", min_value=0, max_value=100, value=40)

if "acuan_pg_img" not in st.session_state:
    st.session_state.acuan_pg_img = None
if "acuan_essay_img" not in st.session_state:
    st.session_state.acuan_essay_img = None
if "kunci_pg_teks" not in st.session_state:
    st.session_state.kunci_pg_teks = ""
if "rubrik_essay_teks" not in st.session_state:
    st.session_state.rubrik_essay_teks = ""
if "data_nilai" not in st.session_state:
    st.session_state.data_nilai = []

tab1, tab2, tab3 = st.tabs([
    "1️⃣ Upload / Ketik Acuan Guru", 
    "2️⃣ Foto Jawaban Siswa (HP)", 
    "3️⃣ Review & Persetujuan Guru"
])

# TAB 1: ACUAN GURU
with tab1:
    st.subheader("📸 1. Masukkan Acuan Penilaian (Oleh Guru)")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### A. Kunci Jawaban PG")
        input_pg_teks = st.text_area(
            "Ketik Kunci PG (Sangat Direkomendasikan agar 100% Eksak):", 
            value=st.session_state.kunci_pg_teks,
            placeholder="Contoh: 1.B 2.B 3.D 4.B 5.A 6.A 7.C 8.A 9.B 10.C 11.C 12.B 13.C 14.A 15.A",
            height=130
        )
        foto_kunci_pg = st.file_uploader("Atau Upload Foto Kunci PG:", type=["jpg", "jpeg", "png"], key="up_pg")
        if foto_kunci_pg:
            st.session_state.acuan_pg_img = prepare_image(Image.open(foto_kunci_pg))
            st.image(st.session_state.acuan_pg_img, caption="Foto Acuan Kunci PG", use_container_width=True)

    with col2:
        st.markdown("#### B. Soal & Kunci Jawaban Essay")
        input_essay_teks = st.text_area(
            "Ketik Soal & Kunci Jawaban Essay:", 
            value=st.session_state.rubrik_essay_teks,
            placeholder="Contoh:\n1a. 12 + 25 - 10 = 27\n1b. 2 x 3 : 6 = 1\n2a. 24/2 = 12\n2b. 1/3 + 2/3 = 3/3 = 1",
            height=130
        )
        foto_acuan_essay = st.file_uploader("Atau Upload Foto Soal & Jawaban Essay:", type=["jpg", "jpeg", "png"], key="up_essay")
        if foto_acuan_essay:
            st.session_state.acuan_essay_img = prepare_image(Image.open(foto_acuan_essay))
            st.image(st.session_state.acuan_essay_img, caption="Foto Acuan Soal & Jawaban Essay", use_container_width=True)

    if st.button("💾 Simpan Acuan Guru", type="primary"):
        st.session_state.kunci_pg_teks = input_pg_teks
        st.session_state.rubrik_essay_teks = input_essay_teks
        kunci_dict = parse_kunci_pg(input_pg_teks)
        st.success(f"✅ Acuan berhasil disimpan! Terdeteksi {len(kunci_dict)} nomor kunci PG.")

# TAB 2: JAWABAN SISWA
with tab2:
    st.subheader("📱 2. Foto & Upload Lembar Jawaban Siswa")
    
    c1, c2 = st.columns(2)
    with c1:
        nama_siswa = st.text_input("Nama Siswa (Kosongkan jika ingin AI membaca otomatis dari kertas):")
    with c2:
        kelas_siswa = st.text_input("Kelas / Mapel:", value="Kelas 7 - Matematika")

    metode_input = st.radio("Metode Input:", ["Buka Kamera HP / Galeri (Rekomendasi)", "Kamera Web Langsung"], horizontal=True)
    
    raw_img = None
    if metode_input == "Buka Kamera HP / Galeri (Rekomendasi)":
        file_siswa = st.file_uploader("Klik untuk Memotret / Upload Jawaban Siswa:", type=["jpg", "jpeg", "png"], key="up_siswa")
        if file_siswa:
            raw_img = Image.open(file_siswa)
    else:
        cam_siswa = st.camera_input("Jepret Lembar Jawaban Siswa")
        if cam_siswa:
            raw_img = Image.open(cam_siswa)

    if raw_img:
        st.markdown("##### 🔄 Atur Posisi Kertas (PENTING: Pastikan Teks Tegak Lurus & Tidak Miring)")
        rotasi = st.radio("Putar Foto:", [0, 90, 180, 270], format_func=lambda x: f"Putar {x}°" if x > 0 else "Normal (0°)", horizontal=True)
        
        img_siswa = prepare_image(raw_img, rotasi=rotasi, max_size=1600)
        st.image(img_siswa, caption="Preview Lembar Jawaban (Pastikan sudah tegak lurus)", width=420)
        
        if st.button("🎯 Proses Koreksi Akurat (AI)", type="primary"):
            pg_teks_final = input_pg_teks if input_pg_teks else st.session_state.kunci_pg_teks
            essay_teks_final = input_essay_teks if input_essay_teks else st.session_state.rubrik_essay_teks

            if not api_key:
                st.error("⚠️ Masukkan Google Gemini API Key di menu sebelah kiri!")
            elif not st.session_state.acuan_pg_img and not pg_teks_final and not st.session_state.acuan_essay_img and not essay_teks_final:
                st.error("⚠️ Mohon isi ketikan kunci jawaban atau upload foto acuan guru di Tab 1 terlebih dahulu!")
            else:
                waktu_mulai = time.time()
                with st.spinner("🔍 AI sedang membaca huruf jawaban per nomor secara presisi..."):
                    try:
                        genai.configure(api_key=api_key)
                        # Temperature 0.0 membuat AI 100% deterministik dan tidak berubah-ubah
                        generation_config = {
                            "temperature": 0.0,
                            "top_p": 1.0,
                            "top_k": 1,
                            "response_mime_type": "application/json"
                        }
                        model = genai.GenerativeModel(pilihan_model, generation_config=generation_config)
                        
                        prompt_parts = [
                            f"""Anda adalah sistem OCR dan korektor ujian matematika tingkat presisi tinggi.
                            
                            ATURAN KETAT MEMBACA TABEL PILIHAN GANDA (PG):
                            1. Baca setiap baris nomor dengan teliti (Perhatikan kolom 1-10, 11-20, 21-30).
                            2. ATURAN CORETAN / GANTI JAWABAN: Jika pada satu nomor terdapat tanda silang (X) yang DICORET dengan garis mendatar/tebal (seperti tanda '=' di atas X) dan ada tanda silang (X) lain yang bersih di sebelahnya, maka tanda yang dicoret itu BATAL. Pilihlah huruf yang memiliki tanda silang (X) BERSIH sebagai jawaban sah siswa (BUKAN jawaban ganda).
                            3. Abaikan nomor yang biarkan kosong semua (tidak diisi).
                            
                            Tugas Anda:
                            - Baca Nama Siswa yang tertulis di lembar jawaban.
                            - Ekstrak huruf jawaban PG siswa yang terisi pada setiap nomor ke dalam dictionary JSON "jawaban_pg_siswa" (contoh: {{"1": "B", "2": "B", "3": "D"}}).
                            - Jika kunci PG berupa foto, ekstrak juga ke dalam "kunci_pg_guru".
                            - Periksa langkah dan hasil jawaban Essay siswa dibandingkan dengan Acuan Essay, lalu berikan "skor_essay" (0-100) dan "detail_essay".
                            
                            Kembalikan HANYA format JSON berikut:
                            {{
                                "nama_terbaca": "Nama di kertas",
                                "jawaban_pg_siswa": {{"1": "B", "2": "B"}},
                                "kunci_pg_guru": {{"1": "B", "2": "B"}},
                                "skor_essay": 100,
                                "detail_essay": "Penjelasan singkat koreksi tiap nomor essay"
                            }}"""
                        ]
                        
                        if st.session_state.acuan_pg_img:
                            prompt_parts.append("FOTO KUNCI PG GURU:")
                            prompt_parts.append(st.session_state.acuan_pg_img)
                        if pg_teks_final:
                            prompt_parts.append(f"KUNCI PG GURU (TEKS): {pg_teks_final}")
                            
                        if st.session_state.acuan_essay_img:
                            prompt_parts.append("FOTO ACUAN ESSAY GURU:")
                            prompt_parts.append(st.session_state.acuan_essay_img)
                        if essay_teks_final:
                            prompt_parts.append(f"ACUAN ESSAY GURU (TEKS): {essay_teks_final}")

                        prompt_parts.append("FOTO LEMBAR JAWABAN SISWA:")
                        prompt_parts.append(img_siswa)

                        response = model.generate_content(prompt_parts)
                        cleaned_text = re.sub(r"```json|```", "", response.text).strip()
                        hasil_json = json.loads(cleaned_text)
                        
                        # PERHITUNGAN PG EKSAK MENGGUNAKAN PYTHON (AGAR KONSISTEN 100%)
                        jawaban_siswa_dict = {str(k): str(v).upper().strip() for k, v in hasil_json.get("jawaban_pg_siswa", {}).items()}
                        kunci_manual_dict = parse_kunci_pg(pg_teks_final)
                        kunci_final_dict = kunci_manual_dict if len(kunci_manual_dict) > 0 else {str(k): str(v).upper().strip() for k, v in hasil_json.get("kunci_pg_guru", {}).items()}
                        
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
                            rincian_pg_teks = "Kunci PG belum terbaca"
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
                        
                        st.success(f"✅ Koreksi presisi selesai dalam **{durasi} detik**! Nama Terbaca: **{nama_final}**")
                        col_r1, col_r2, col_r3 = st.columns(3)
                        col_r1.metric("Skor PG (Skala 100)", skor_pg)
                        col_r2.metric("Skor Essay (Skala 100)", skor_essay)
                        col_r3.metric("Nilai Akhir Sementara", nilai_akhir)
                        
                        st.info(f"**Rincian PG:** {rincian_pg_teks}\n\n** Pembacaan Per Nomor:** {', '.join(detail_per_nomor)}\n\n**Catatan Essay:** {hasil_json.get('detail_essay', '')}")
                        
                    except Exception as e:
                        st.error(f"Gagal memproses dengan AI: {e}")

# TAB 3: REVIEW GURU
with tab3:
    st.subheader("👨‍🏫 3. Verifikasi & Persetujuan Guru")
    st.caption("Nilai di bawah ini masih bersifat SEMENTARA. Anda dapat mengklik dan mengubah langsung angka nilai atau menghapus baris kosong di dalam tabel sebelum menyetujuinya.")
    
    if len(st.session_state.data_nilai) == 0:
        st.info("Belum ada lembar jawaban siswa yang dikoreksi.")
    else:
        # Bersihkan baris kosong (None) secara otomatis jika ada
        st.session_state.data_nilai = [row for row in st.session_state.data_nilai if row.get("Nama Siswa") is not None]
        df = pd.DataFrame(st.session_state.data_nilai)
        edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)
        st.session_state.data_nilai = edited_df.to_dict('records')

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            if st.button("✅ Setujui Semua Nilai (Finalisasi)", type="primary"):
                for item in st.session_state.data_nilai:
                    item["Status"] = "✅ Disetujui Guru (Final)"
                st.rerun()
        with col_b:
            csv = edited_df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download Rekap Nilai (Excel/CSV)", data=csv, file_name="Rekap_Nilai_Ujian.csv", mime="text/csv")
        with col_c:
            if st.button("🗑️ Kosongkan Tabel Rekap"):
                st.session_state.data_nilai = []
                st.rerun()