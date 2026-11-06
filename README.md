# 🎯 칼바람 딜량 내기 기록소

스크린샷을 올리면 날짜 폴더에 사진이 쌓이고, OCR 초안을 표에서 고쳐 **경기 기록**으로 저장하는 Streamlit 앱입니다.
API 키 없이 동작합니다(로컬 Tesseract OCR + 내장 챔피언 사전).

## 되는 일

| 화면 | 기능 |
|---|---|
| 📷 사진 업로드 · OCR | 여러 장 동시 업로드, 오늘 날짜 폴더 자동 생성, 새 폴더 만들기, 폴더 선택 저장, 사진 여러 장을 **한 경기로 묶기**, 경기 시간·승패·내기 구간 지정, OCR 초안 표 수정 |
| 🗂 폴더 · 경기 기록 | 경기 목록, 경기 번호 중간 삽입, 경기별 참가기록 편집, 사진을 다른 폴더로 이동·삭제 |
| 📊 오늘 · 폴더 합계 | 아이디별 평균/합계, 경기별 DPS, 내기 구간별 집계, **정산(순위합·게임별 꼴등)**, 사진 갤러리 |
| 🏆 전체 종합 | 전 기간 참가자 통계(경기·딜량·순위·DPS·승률), 캐릭터별 성적, 함께한 사람별 경기 수·승률, 폴더 비교, CSV |
| ⚙️ 설정 · 백업 | OCR 진단, ZIP 백업/복원, 기존 엑셀·CSV 가져오기, 폴더 이름 변경·삭제 |

## 지표 정의

- **딜량 지분** = 같은 팀(아군/적군) 기록 딜량 합계 대비 비율
- **DPS** = 딜량 ÷ 경기시간(초), **DPM** = DPS × 60 — 경기 시간이 입력된 경기만 계산
- **순위합계** = 팀내 딜량 순위의 합 (낮을수록 좋음)
- **정산** = `순위합 최소 승`(구간 전체 순위합 1위가 나머지에게 1인당 금액 수령) 또는 `게임별 꼴등 지급`. 합계는 항상 0원
- 8명 이상 기록되면 같은 경기에 `적군` 팀으로 함께 저장 → 전체 종합에서 상대 전적까지 집계

## OCR에 대해 (정확히 알고 쓰기)

- 엔진: **Tesseract 5 + 한국어 학습데이터**, 이미지 자동 확대·CLAHE·이진화 후 4가지 조합으로 시도해 가장 좋은 결과 선택
- 글자 → 기록 변환: 줄 단위로 나눈 뒤 **챔피언 173종 사전(Data Dragon 16.22.1)** 과 퍼지 매칭, 숫자는 딜량/골드/순위 후보로 분류
- 그래서 결과는 **초안**입니다. 특히 어두운 배경의 한글 닉네임은 오인식이 잦습니다. **표에서 고친 뒤 저장**하는 흐름이 기본값이고, 원문 텍스트도 함께 볼 수 있습니다
- API 키가 필요한 상용 OCR보다 정확도는 낮습니다. 정확도가 중요하면 챔피언·닉네임만 손으로 채우고 딜량 숫자만 OCR로 받는 식으로 쓰세요

## 로컬 실행

```bash
pip install -r requirements.txt
# Ubuntu/Debian: OCR 언어팩 (없으면 OCR만 비활성)
sudo apt-get install -y tesseract-ocr tesseract-ocr-kor
streamlit run app.py
```

Windows는 [Tesseract 설치](https://github.com/UB-Mannheim/tesseract/wiki) 후 `kor` 언어 선택, 필요하면 `pytesseract.pytesseract.tesseract_cmd` 경로 지정.

## GitHub → Streamlit Cloud 배포

```bash
git init
git add .
git commit -m "칼바람 딜량 기록소 v1"
git branch -M main
git remote add origin https://github.com/<사용자>/<저장소>.git
git push -u origin main
```

1. https://share.streamlit.io → **New app** → 저장소·브랜치(`main`)·파일(`app.py`) 선택 → Deploy
2. `packages.txt` 가 자동 설치되어 `tesseract-ocr-kor` 포함 OCR이 바로 동작합니다
3. 앱 URL 공유

### 저장 공간 주의

Streamlit Cloud는 재시작 시 파일이 초기화될 수 있습니다. 기록·사진은 `data_store/` 에 저장되며 **git에 포함되지 않습니다**(`.gitignore`).
- 평소: ⚙️ 설정 → **ZIP 백업**을 주기적으로 내려받기
- 계속 보관: 같은 코드를 PC나 서버에서 실행하면 `data_store/` 가 그대로 남습니다
- 영구 보관이 필요하면 Google Drive/S3 같은 외부 저장소 연결이 다음 단계입니다

## 폴더 구조

```
app.py                  # 화면 5개
aram/db.py              # SQLite 스키마·CRUD (폴더/사진/경기/참가기록/내기)
aram/ocr.py             # 전처리·Tesseract·챔피언 매칭·후보 파싱
aram/metrics.py         # 집계(참가자/캐릭터/경기/내기/함께한 사람)
aram/settle.py          # 정산 규칙
aram/importer.py        # 엑셀·CSV 가져오기(쉼표 한 셀 형식 포함)
aram/champions.py       # 내장 챔피언 목록 로더
data/champions_ko.json  # 한국어 챔피언 173종
sample/                 # 예시 엑셀(가져오기 테스트용)
tests/                  # 정산·파서 테스트
```

## 테스트

```bash
python -m pytest -q
```

## 다음에 붙이면 좋은 것

- 경기 시간 자동 인식(현재는 직접 입력)
- 사진에서 승/패 아이콘 판독
- 참가자 닉네임 사전 학습(오인식 보정)
- 정산 규칙 추가(상위 절반 승 등)와 게임별 정산 내역 저장
