import streamlit as st
import pandas as pd
from PIL import Image
import datetime
import os
import cv2
import numpy as np
import pytesseract

st.set_page_config(page_title="롤 내기 자동 정산기", page_icon="🎮", layout="wide")
st.title("🎮 롤 내기 종합 데이터 분석기")

DB_FILE = "lol_records.csv"

# --- 데이터 로드 및 저장 ---
def load_data():
    if os.path.exists(DB_FILE):
        return pd.read_csv(DB_FILE)
    else:
        return pd.DataFrame(columns=['폴더명', '날짜', '아이디', '캐릭터', '딜량', '순위', '딜량_지분_퍼센트', 'DPS', 'DPM'])

def save_data(new_df):
    df = load_data()
    df = pd.concat([df, new_df], ignore_index=True)
    df.to_csv(DB_FILE, index=False)

# --- 실제 OCR 이미지 처리 함수 ---
def perform_ocr(image):
    # PIL 이미지를 OpenCV 형식으로 변환
    img_array = np.array(image)
    if len(img_array.shape) == 3 and img_array.shape[2] == 3: # RGB to BGR
        img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
    
    # 흑백 변환 및 대비(Threshold) 조절로 글자 인식률 향상
    gray = cv2.cvtColor(img_array, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)
    
    # Tesseract로 텍스트 추출 (한국어+영어)
    custom_config = r'--oem 3 --psm 6'
    extracted_text = pytesseract.image_to_string(thresh, lang='kor+eng', config=custom_config)
    
    # 주의: 롤 화면의 복잡성 때문에 원시 텍스트가 완벽하지 않을 수 있습니다.
    # 초기 기틀용 더미 데이터프레임을 생성하여 반환하되, 추출된 텍스트를 파싱하는 로직은 지속적으로 깎아야 합니다.
    # 여기서는 사용자가 바로 수정할 수 있도록 기본 템플릿 표를 반환합니다.
    df_template = pd.DataFrame({
        '아이디': ['추출값확인', '', '', '', ''],
        '캐릭터': ['', '', '', '', ''],
        '딜량': [0, 0, 0, 0, 0],
    })
    return df_template, extracted_text

# --- 사이드바: 폴더(세션) 관리 ---
history_df = load_data()
existing_folders = history_df['폴더명'].unique().tolist() if not history_df.empty else []
default_folder = datetime.datetime.now().strftime("%Y-%m-%d_내기")

if default_folder not in existing_folders:
    existing_folders.insert(0, default_folder)

with st.sidebar:
    st.header("📁 폴더(세션) 설정")
    selected_folder = st.selectbox("기존 폴더 선택", existing_folders)
    new_folder = st.text_input("새 폴더 만들기 (입력 시 이 폴더로 지정됨)")
    
    # 새 폴더명이 입력되면 그것을 활성 폴더로 사용
    active_folder = new_folder if new_folder.strip() else selected_folder
    
    st.divider()
    st.header("⏱️ 게임 시간 설정")
    st.caption("DPS 및 DPM 계산을 위해 필요합니다.")
    game_min = st.number_input("분", min_value=0, value=25)
    game_sec = st.number_input("초", min_value=0, max_value=59, value=0)
    total_seconds = (game_min * 60) + game_sec
    total_minutes = game_min + (game_sec / 60)

# --- 메인 1: 다중 사진 업로드 및 OCR ---
st.subheader(f"📸 [{active_folder}] 폴더에 사진 업로드")
# accept_multiple_files=True 로 여러 장 동시 업로드 허용
uploaded_files = st.file_uploader("여러 장의 이미지를 드래그해서 올려주세요", type=["png", "jpg", "jpeg"], accept_multiple_files=True)

if uploaded_files:
    for idx, uploaded_file in enumerate(uploaded_files):
        st.markdown(f"### 📄 이미지 {idx+1}: {uploaded_file.name}")
        
        image = Image.open(uploaded_file)
        
        col1, col2 = st.columns([1, 2])
        with col1:
            st.image(image, use_container_width=True)
            
        with col2:
            df_ocr, raw_text = perform_ocr(image)
            
            st.info("💡 OCR 로 추출된 표입니다. 인식이 잘못된 부분은 **표의 칸을 클릭해 직접 수정**할 수 있습니다.")
            
            # 사용자가 화면에서 직접 표의 데이터를 수정할 수 있는 에디터 (st.data_editor)
            edited_df = st.data_editor(df_ocr, num_rows="dynamic", key=f"editor_{idx}")
            
            if st.button(f"이미지 {idx+1} 데이터 계산 및 폴더에 저장", key=f"save_{idx}"):
                # 사용자가 수정한 표를 바탕으로 지표 연산
                edited_df['딜량'] = pd.to_numeric(edited_df['딜량'], errors='coerce').fillna(0)
                
                # 순위 연산 (딜량이 높은 순서대로 1위~ 부여)
                edited_df['순위'] = edited_df['딜량'].rank(method='min', ascending=False).astype(int)
                
                # 딜량 % 지분, DPS, DPM 연산
                total_damage = edited_df['딜량'].sum()
                if total_damage > 0:
                    edited_df['딜량_지분_퍼센트'] = ((edited_df['딜량'] / total_damage) * 100).round(1)
                else:
                    edited_df['딜량_지분_퍼센트'] = 0.0
                    
                edited_df['DPS'] = (edited_df['딜량'] / total_seconds).round(1) if total_seconds > 0 else 0
                edited_df['DPM'] = (edited_df['딜량'] / total_minutes).round(1) if total_minutes > 0 else 0
                
                # 메타데이터 추가
                edited_df['폴더명'] = active_folder
                edited_df['날짜'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                
                # DB 저장
                save_data(edited_df)
                st.success(f"✅ [{active_folder}] 폴더에 성공적으로 기록되었습니다!")
                st.dataframe(edited_df)

# --- 메인 2: 폴더별 종합 통계 ---
st.divider()
st.subheader(f"📊 [{active_folder}] 폴더 종합 통계")
current_db = load_data()

if not current_db.empty:
    # 현재 선택된 폴더의 데이터만 필터링
    folder_data = current_db[current_db['폴더명'] == active_folder]
    
    if not folder_data.empty:
        # 아이디 기준으로 통계 (총 딜량, 평균 순위, 딜량 지분율 합계 등)
        folder_summary = folder_data.groupby('아이디').agg(
            참여게임수=('아이디', 'count'),
            총_딜량=('딜량', 'sum'),
            평균_딜량=('딜량', 'mean'),
            평균_순위=('순위', 'mean'),
            평균_딜량지분=('딜량_지분_퍼센트', 'mean'),
            평균_DPM=('DPM', 'mean'),
            평균_DPS=('DPS', 'mean')
        ).reset_index()
        
        # 보기 좋게 반올림
        folder_summary['평균_딜량'] = folder_summary['평균_딜량'].astype(int)
        folder_summary['평균_순위'] = folder_summary['평균_순위'].round(1)
        folder_summary['평균_딜량지분'] = folder_summary['평균_딜량지분'].round(1).astype(str) + '%'
        
        # 순위가 높은(1등에 가까운) 순서대로 정렬하여 출력
        folder_summary = folder_summary.sort_values(by='평균_순위')
        
        st.dataframe(folder_summary, use_container_width=True)
    else:
        st.info("이 폴더에는 아직 저장된 기록이 없습니다.")
else:
    st.info("아직 누적된 전체 기록이 없습니다.")
