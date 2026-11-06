import streamlit as st
import pandas as pd
from PIL import Image
import datetime
import os

# --- 페이지 기본 설정 ---
st.set_page_config(page_title="대마왕의 롤 내기 정산기", page_icon="🎮", layout="wide")
st.title("🎮 대마왕의 롤 내기 자동 정산기")

# --- 데이터 저장소 (CSV 기반 임시 DB) ---
DB_FILE = "lol_records.csv"

def load_data():
    if os.path.exists(DB_FILE):
        return pd.read_csv(DB_FILE)
    else:
        return pd.DataFrame(columns=['날짜', '내기_태그', '경기', '아이디', '캐릭터', '딜량', '순위', '게임시간_초', 'DPS'])

def save_data(new_df):
    df = load_data()
    df = pd.concat([df, new_df], ignore_index=True)
    df.to_csv(DB_FILE, index=False)
    return df

# --- 가상의 OCR 추출 함수 (실제 OCR 연동 전 테스트용) ---
# ※ 나중에 이 부분을 OpenCV + Tesseract 또는 Google Vision API로 교체하시면 됩니다.
def extract_data_from_image(image, main_user):
    st.info("이미지에서 텍스트를 추출하는 중입니다... (시뮬레이션)")
    # 가상의 추출 데이터
    data = {
        '아이디': [main_user, '멘탈지존', '송블루', '배변엔돌체라떼', '양학살이요'],
        '캐릭터': ['올라프', '그레이브즈', '스몰더', '그라가스', '갈리오'],
        '딜량': [49543, 84316, 65895, 58442, 105063],
        '순위': [5, 2, 3, 4, 1],
        '게임시간_초': [1800, 1800, 1800, 1800, 1800] # 30분 가정
    }
    return pd.DataFrame(data)

# --- 사이드바: 기본 설정 ---
with st.sidebar:
    st.header("⚙️ 기본 설정")
    main_user = st.selectbox("메인 플레이어 (나)", ["체리쥬빌뤠", "송블루", "멘탈지존", "배변엔돌체라떼", "양학살이요"])
    bet_tag = st.text_input("현재 내기 태그", value="커피내기 1차전")
    match_num = st.number_input("경기 번호", min_value=1, value=1)
    
# --- 메인 화면: 사진 업로드 ---
st.subheader(f"📸 롤 결과창 캡처 업로드 ({bet_tag})")
uploaded_file = st.file_uploader("이미지를 올려주세요 (png, jpg, jpeg)", type=["png", "jpg", "jpeg"])

if uploaded_file is not None:
    # 1. 이미지 화면에 띄우기
    image = Image.open(uploaded_file)
    st.image(image, caption='업로드된 결과창', use_container_width=True)
    
    if st.button("분석 및 정산하기"):
        # 2. 데이터 추출 (가상 OCR)
        df_extracted = extract_data_from_image(image, main_user)
        
        # 3. 데이터 가공 (메타데이터 및 DPS 추가)
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        df_extracted['날짜'] = today
        df_extracted['내기_태그'] = bet_tag
        df_extracted['경기'] = match_num
        df_extracted['DPS'] = (df_extracted['딜량'] / df_extracted['게임시간_초']).round(2)
        
        # 4. DB(CSV) 저장
        save_data(df_extracted)
        st.success("데이터가 성공적으로 기록되었습니다!")
        
        # 5. 현재 경기 결과 표시 및 패배자(꼴찌) 색출
        st.subheader(f"📊 {bet_tag} - {match_num}경기 결과")
        st.dataframe(df_extracted[['순위', '아이디', '캐릭터', '딜량', 'DPS']].sort_values(by='순위'))
        
        loser = df_extracted.loc[df_extracted['순위'].idxmax()]
        st.error(f"🚨 이번 경기 벌칙자(꼴찌)는 **{loser['아이디']}** ({loser['딜량']} 딜) 입니다! 🚨")

# --- 하단 화면: 누적 전적 조회 ---
st.divider()
st.subheader("🏆 전체 누적 전적 및 종합 통계")
history_df = load_data()

if not history_df.empty:
    # 탭으로 보기 좋게 분리
    tab1, tab2 = st.tabs(["오늘의 내기 진행 상황", "역대 종합 통계"])
    
    with tab1:
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        today_df = history_df[history_df['날짜'] == today_str]
        if not today_df.empty:
            st.write("오늘 그룹별(태그별) 평균 순위 및 딜량 합계")
            today_summary = today_df.groupby(['내기_태그', '아이디']).agg(
                경기수=('경기', 'count'),
                딜량합계=('딜량', 'sum'),
                평균순위=('순위', 'mean')
            ).reset_index().sort_values(by=['내기_태그', '평균순위'])
            st.dataframe(today_summary)
        else:
            st.info("오늘 기록된 게임이 없습니다.")
            
    with tab2:
        st.write("나와 게임한 모든 사람의 누적 통계")
        total_summary = history_df.groupby('아이디').agg(
            총게임수=('경기', 'count'),
            총딜량=('딜량', 'sum'),
            평균순위=('순위', 'mean'),
            평균DPS=('DPS', 'mean')
        ).reset_index().sort_values(by='평균순위')
        st.dataframe(total_summary)
else:
    st.info("아직 기록된 데이터가 없습니다. 사진을 업로드해 보세요!")
