import streamlit as st
import pandas as pd
from PIL import Image
import datetime
import os
import numpy as np
import easyocr
import re

st.set_page_config(page_title="롤 내기 자동 정산기", page_icon="🎮", layout="wide")
st.title("🎮 롤 내기 종합 데이터 분석기 (EasyOCR AI)")

DB_FILE = "lol_records.csv"
TARGET_USERS = ['체리쥬빌뤠', '송블루', '멘탈지존', '배변엔돌체라떼', '양학살이요']

# --- AI 모델 로드 (캐싱하여 매번 로딩하는 시간 단축) ---
@st.cache_resource
def load_ocr_model():
    # 한국어와 영어 동시 인식, GPU가 없는 무료 서버를 위해 gpu=False 설정
    return easyocr.Reader(['ko', 'en'], gpu=False)

reader = load_ocr_model()

# --- 데이터 로드 및 저장 ---
def load_data():
    if os.path.exists(DB_FILE):
        return pd.read_csv(DB_FILE)
    else:
        return pd.DataFrame(columns=['폴더명', '날짜', '승패', '게임시간', '아이디', '캐릭터', '딜량', '순위', '딜량_지분_퍼센트', 'DPS', 'DPM'])

def save_data(new_df):
    df = load_data()
    df = pd.concat([df, new_df], ignore_index=True)
    df.to_csv(DB_FILE, index=False)

# --- 스마트폰 사진 대응 EasyOCR 파싱 ---
def analyze_image_with_easyocr(image):
    img_array = np.array(image)
    
    # AI 모델이 이미지를 분석하여 [좌표, 텍스트, 신뢰도] 리스트를 반환
    results = reader.readtext(img_array)
    
    extracted_data = []
    full_text_list = []
    
    # 1. 텍스트 추출 및 승패/시간 파싱
    win_loss = "알수없음"
    play_time = "00:00"
    
    for (bbox, text, prob) in results:
        clean_text = text.replace(" ", "")
        full_text_list.append(clean_text)
        
        if "승리" in clean_text:
            win_loss = "승리"
        elif "패배" in clean_text:
            win_loss = "패배"
            
        time_match = re.search(r'(\d{2}:\d{2})', clean_text)
        if time_match:
            play_time = time_match.group(1)
            
    # 2. 유저 아이디 검색 및 딜량 매칭 (근사치 매칭)
    # 폰으로 찍은 사진은 줄이 삐뚤어질 수 있어, 유저 이름 주변의 5자리 이상 숫자를 딜량으로 추정합니다.
    full_text_str = " ".join(full_text_list)
    
    for user in TARGET_USERS:
        if user in full_text_str:
            extracted_data.append({'아이디': user, '캐릭터': '', '딜량': 0})
            
    # 인식된 유저가 없으면 빈 칸 5개 제공
    if not extracted_data:
        extracted_data = [{'아이디': '', '캐릭터': '', '딜량': 0} for _ in range(5)]
        
    return win_loss, play_time, pd.DataFrame(extracted_data), full_text_str

# --- 사이드바: 폴더(세션) 관리 ---
history_df = load_data()
existing_folders = history_df['폴더명'].unique().tolist() if not history_df.empty else []
default_folder = datetime.datetime.now().strftime("%Y-%m-%d_내기")

if default_folder not in existing_folders:
    existing_folders.insert(0, default_folder)

with st.sidebar:
    st.header("📁 폴더(세션) 설정")
    selected_folder = st.selectbox("기존 폴더 선택", existing_folders)
    new_folder = st.text_input("새 폴더 만들기")
    active_folder = new_folder if new_folder.strip() else selected_folder

# --- 메인: 사진 업로드 및 자동화 ---
st.subheader(f"📸 [{active_folder}] 폴더에 사진 업로드")
uploaded_files = st.file_uploader("모니터 촬영 사진 여러 장 동시 업로드", type=["png", "jpg", "jpeg"], accept_multiple_files=True)

if uploaded_files:
    for idx, uploaded_file in enumerate(uploaded_files):
        st.markdown(f"### 📄 이미지 {idx+1}: {uploaded_file.name}")
        image = Image.open(uploaded_file)
        
        col1, col2 = st.columns([1, 2])
        with col1:
            st.image(image, use_container_width=True)
            
        with col2:
            with st.spinner('오픈소스 AI가 이미지를 딥러닝으로 분석 중입니다... (약 5~10초 소요)'):
                win_loss, play_time, df_parsed, raw_text = analyze_image_with_easyocr(image)
            
            st.success("데이터 추출 완료! 수정이 필요한 부분은 표를 클릭해 직접 입력하세요.")
            
            c1, c2 = st.columns(2)
            final_win = c1.text_input("승패", value=win_loss, key=f"win_{idx}")
            final_time = c2.text_input("게임 시간 (MM:SS)", value=play_time, key=f"time_{idx}")
            
            edited_df = st.data_editor(df_parsed, num_rows="dynamic", key=f"editor_{idx}")
            
            with st.expander("AI가 읽어낸 원본 텍스트 보기 (복사용)"):
                st.write(raw_text)
            
            if st.button(f"이미지 {idx+1} 정산 및 저장", key=f"save_{idx}"):
                try:
                    m, s = map(int, final_time.split(':'))
                    total_seconds = (m * 60) + s
                    total_minutes = m + (s / 60)
                except:
                    total_seconds, total_minutes = 1, 1 
                    
                edited_df['딜량'] = pd.to_numeric(edited_df['딜량'], errors='coerce').fillna(0)
                edited_df['순위'] = edited_df['딜량'].rank(method='min', ascending=False).astype(int)
                
                total_damage = edited_df['딜량'].sum()
                edited_df['딜량_지분_퍼센트'] = ((edited_df['딜량'] / total_damage) * 100).round(1) if total_damage > 0 else 0
                edited_df['DPS'] = (edited_df['딜량'] / total_seconds).round(1)
                edited_df['DPM'] = (edited_df['딜량'] / total_minutes).round(1)
                
                edited_df['폴더명'] = active_folder
                edited_df['날짜'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                edited_df['승패'] = final_win
                edited_df['게임시간'] = final_time
                
                save_data(edited_df)
                st.success(f"✅ 저장 완료!")
                st.dataframe(edited_df)

st.divider()
st.subheader(f"📊 [{active_folder}] 폴더 종합 통계")
current_db = load_data()

if not current_db.empty:
    folder_data = current_db[current_db['폴더명'] == active_folder]
    if not folder_data.empty:
        folder_summary = folder_data.groupby('아이디').agg(
            참여게임수=('아이디', 'count'),
            총_딜량=('딜량', 'sum'),
            평균_딜량=('딜량', 'mean'),
            평균_순위=('순위', 'mean'),
            평균_딜량지분=('딜량_지분_퍼센트', 'mean'),
            평균_DPM=('DPM', 'mean'),
            평균_DPS=('DPS', 'mean')
        ).reset_index()
        
        folder_summary['평균_딜량'] = folder_summary['평균_딜량'].astype(int)
        folder_summary['평균_순위'] = folder_summary['평균_순위'].round(1)
        folder_summary['평균_딜량지분'] = folder_summary['평균_딜량지분'].round(1).astype(str) + '%'
        folder_summary = folder_summary.sort_values(by='평균_순위')
        
        st.dataframe(folder_summary, use_container_width=True)
    else:
        st.info("이 폴더에는 아직 저장된 기록이 없습니다.")
else:
    st.info("아직 누적된 전체 기록이 없습니다.")
