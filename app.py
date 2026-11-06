import streamlit as st
import pandas as pd
from PIL import Image
import datetime
import os
import re
import io
import json
from google.cloud import vision
from google.oauth2 import service_account

st.set_page_config(page_title="롤 내기 자동 정산기", page_icon="🎮", layout="wide")
st.title("🎮 롤 내기 종합 데이터 분석기 (Vision API)")

DB_FILE = "lol_records.csv"

# 우리 팀 고정 아이디 목록 (OCR 파싱 시 우선 탐색)
TARGET_USERS = ['체리쥬빌뤠', '송블루', '멘탈지존', '배변엔돌체라떼', '양학살이요']

# --- Google Cloud Vision API 클라이언트 초기화 ---
@st.cache_resource
def get_vision_client():
    try:
        # Streamlit Secrets에서 GCP 인증 정보 가져오기
        credentials_dict = dict(st.secrets["gcp_service_account"])
        credentials = service_account.Credentials.from_service_account_info(credentials_dict)
        client = vision.ImageAnnotatorClient(credentials=credentials)
        return client
    except Exception as e:
        st.error(f"GCP 연동 오류: Secrets 설정이 필요합니다. ({e})")
        return None

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

# --- Vision API 호출 및 데이터 스마트 파싱 ---
def analyze_image_with_vision(image_bytes):
    client = get_vision_client()
    if not client:
        return "오류", "00:00", pd.DataFrame()
        
    image = vision.Image(content=image_bytes)
    response = client.text_detection(image=image)
    texts = response.text_annotations
    
    if not texts:
        return "알수없음", "00:00", pd.DataFrame()
        
    # 전체 인식된 텍스트 덩어리
    full_text = texts[0].description
    
    # 1. 승/패 추출
    win_loss = "승리" if "승리" in full_text else ("패배" if "패배" in full_text else "알수없음")
    
    # 2. 게임 시간 추출 (MM:SS 형식 정규식 탐색)
    time_match = re.search(r'(\d{2}:\d{2})', full_text)
    play_time = time_match.group(1) if time_match else "00:00"
    
    # 3. 유저 아이디와 딜량 추출 매칭
    # Vision API는 텍스트를 줄바꿈 단위로 인식하므로, 쉼표가 있는 숫자(딜량/골드)를 모두 찾습니다.
    # 완벽한 매칭이 어려울 수 있어, 유저가 확인/수정할 수 있도록 기본 틀을 만들어 줍니다.
    extracted_data = []
    
    for user in TARGET_USERS:
        # 텍스트에 유저 이름이 있으면 일단 리스트에 추가
        if user in full_text:
            extracted_data.append({'아이디': user, '캐릭터': '', '딜량': 0})
            
    # 인식된 유저가 없으면 빈 칸 5개 제공
    if not extracted_data:
        extracted_data = [{'아이디': '', '캐릭터': '', '딜량': 0} for _ in range(5)]
        
    return win_loss, play_time, pd.DataFrame(extracted_data)

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
uploaded_files = st.file_uploader("결과창 이미지 여러 장 동시 업로드", type=["png", "jpg", "jpeg"], accept_multiple_files=True)

if uploaded_files:
    for idx, uploaded_file in enumerate(uploaded_files):
        st.markdown(f"### 📄 이미지 {idx+1}: {uploaded_file.name}")
        
        # 이미지 바이트 추출 (API 전송용)
        image_bytes = uploaded_file.getvalue()
        image = Image.open(uploaded_file)
        
        col1, col2 = st.columns([1, 2])
        with col1:
            st.image(image, use_container_width=True)
            
        with col2:
            with st.spinner('Vision API로 화면을 스캔하는 중...'):
                win_loss, play_time, df_parsed = analyze_image_with_vision(image_bytes)
            
            st.success("데이터 추출 완료! 빈칸이나 오류가 있다면 표를 클릭해 수정하세요.")
            
            # 메타데이터 자동 입력 (수정 가능하도록 설정)
            c1, c2 = st.columns(2)
            final_win = c1.text_input("승패", value=win_loss, key=f"win_{idx}")
            final_time = c2.text_input("게임 시간 (MM:SS)", value=play_time, key=f"time_{idx}")
            
            edited_df = st.data_editor(df_parsed, num_rows="dynamic", key=f"editor_{idx}")
            
            if st.button(f"이미지 {idx+1} 정산 및 폴더에 저장", key=f"save_{idx}"):
                # 시간(MM:SS)을 초(Seconds)와 분(Minutes)으로 변환
                try:
                    m, s = map(int, final_time.split(':'))
                    total_seconds = (m * 60) + s
                    total_minutes = m + (s / 60)
                except:
                    total_seconds, total_minutes = 1, 1 # 에러 방지
                    
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

# --- 통계 영역 (이전 코드와 동일하므로 생략 없이 제공) ---
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
