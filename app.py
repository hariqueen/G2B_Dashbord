from dash import Dash
import dash_bootstrap_components as dbc
import pandas as pd
from datetime import datetime
import firebase_admin
from firebase_admin import credentials
from firebase_admin import db
from layout import create_layout
import callbacks
from preprocess import generate_prediction_data
import os

# Firebase 초기화 함수
def initialize_firebase():
    try:
        # 이미 초기화된 경우 새 앱 인스턴스 생성
        firebase_admin.get_app()
    except ValueError:
        # 초기화되지 않은 경우 새로 초기화
        import os
        import json
        
        # 환경 변수에서 Firebase 인증 정보 가져오기
        firebase_credentials = os.environ.get('FIREBASE_CREDENTIALS')
        
        if firebase_credentials:
            # 환경 변수에 저장된 JSON 문자열을 딕셔너리로 변환
            cred_dict = json.loads(firebase_credentials)
            cred = credentials.Certificate(cred_dict)
        else:
            # 로컬 개발 환경일 경우 파일 사용
            try:
                cred = credentials.Certificate('g2b-db-6aae9-firebase-adminsdk-fbsvc-0e3b1ce560.json')
            except FileNotFoundError:
                print("Firebase 인증 파일을 찾을 수 없습니다.")
                raise
                
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://g2b-db-6aae9-default-rtdb.asia-southeast1.firebasedatabase.app/'
        })
    print("Firebase 초기화 완료")

# Firebase에서 데이터 로드하는 함수
def load_data_from_firebase():
    print("Firebase에서 데이터 로드 중...")
    
    # 기본 데이터와 사용자 입력 데이터 가져오기
    bids_ref = db.reference('/bids')
    user_inputs_ref = db.reference('/user_inputs')
    
    bids_data = bids_ref.get() or {}
    user_inputs = user_inputs_ref.get() or {}
    
    # 통합 데이터 프레임 생성
    rows = []
    
    for year in bids_data:
        for month in bids_data[year]:
            for bid_id, bid_info in bids_data[year][month].items():
                row = bid_info.copy()
                
                # Firebase 컬럼명을 앱 내부 컬럼명으로 매핑
                if "낙찰금액" in row:
                    row["입찰금액_1순위"] = row.pop("낙찰금액")
                if "사업금액" in row:
                    row["계약 기간 내"] = row.pop("사업금액")
                if "채권자명" in row:
                    row["실수요기관"] = row.pop("채권자명")
                if "개찰업체정보" in row:
                    row["입찰결과_1순위"] = row.pop("개찰업체정보")
                
                # 사용자 입력 데이터 추가
                if bid_id in user_inputs:
                    user_data = user_inputs[bid_id]
                    row['물동량 평균'] = user_data.get('물동량 평균', 0)
                    row['용역기간(개월)'] = user_data.get('용역기간(개월)', 0)
                
                # 연도 및 월 정보 추가 (숫자 형태로)
                row['예상_연도'] = int(year)
                row['예상_입찰월'] = int(month)
                
                # 입찰일시를 datetime으로 변환
                if '입찰일시' in row:
                    try:
                        row['예상_입찰일'] = pd.to_datetime(row['입찰일시'])
                    except:
                        # 변환 실패 시 기본값 설정
                        row['예상_입찰일'] = pd.to_datetime(f"{year}-{month}-01")
                
                # 예상_년월 추가
                row['예상_년월'] = f"{year}-{month}"
                
                # bid_id 추가 (나중에 업데이트할 때 필요)
                row['bid_id'] = bid_id
                
                rows.append(row)
    
    df = pd.DataFrame(rows)
    
    # CSV 로드와 일관성을 유지하기 위한 컬럼 이름 및 타입 조정
    if '예상_입찰일' not in df.columns and '입찰일시' in df.columns:
        df['예상_입찰일'] = pd.to_datetime(df['입찰일시'])
    
    print(f"총 {len(df)} 레코드 로드 완료")
    
    # 예측 데이터 생성 로직 추가
    prediction_df = generate_prediction_data(df, prediction_years=3)
    
    # 원본 데이터와 예측 데이터 병합
    if not prediction_df.empty:
        df = pd.concat([df, prediction_df], ignore_index=True)
        print(f"예측 데이터 {len(prediction_df)}개 생성 완료, 최종 데이터 수: {len(df)}")
    
    # 연도별 데이터 수 확인
    print(f"연도별 데이터 수:")
    print(df.groupby("예상_연도")["공고명"].count())
    
    return df

# 애플리케이션 초기화
app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP], suppress_callback_exceptions=True)
server = app.server

# Firebase 초기화
initialize_firebase()

# Firebase 실시간 리스너 설정
def setup_firebase_listeners():
    """Firebase 실시간 리스너 설정"""
    global df
    
    def on_bids_change(event):
        """입찰 데이터 변경 시 실행되는 콜백"""
        print(f"Firebase 데이터 변경 감지: {event.path}")
        
        # 데이터 다시 로드
        global df
        df = load_data_from_firebase()
        print(f"데이터 업데이트 완료: 총 {len(df)}건")
    
    def on_user_inputs_change(event):
        """사용자 입력 데이터 변경 시 실행되는 콜백"""
        print(f"사용자 입력 데이터 변경: {event.path}")
        
        # 데이터 다시 로드
        global df
        df = load_data_from_firebase()
        print(f"사용자 입력 반영 완료: 총 {len(df)}건")
    
    # 입찰 데이터 리스너
    bids_ref = db.reference('/bids')
    bids_ref.listen(on_bids_change)
    
    # 사용자 입력 데이터 리스너
    user_inputs_ref = db.reference('/user_inputs')
    user_inputs_ref.listen(on_user_inputs_change)
    
    print("Firebase 실시간 리스너 설정 완료")

setup_firebase_listeners()

# Firebase에서 데이터 로드
df = load_data_from_firebase()
print(f"총 {len(df)} 레코드 로드 완료")
print(f"원본 데이터 최대 연도: {df[~df['공고명'].str.contains('예측')]['예상_연도'].max()}")

# 항상 고정된 월 그룹 사용: (1-4), (5-8), (9-12)
months = list(range(1, 13))
month_groups = [months[i:i+4] for i in range(0, len(months), 4)]
today = datetime.today()

# 현재 월이 속한 그룹 찾기
default_page = next(i for i, group in enumerate(month_groups) if today.month in group)

initial_state = {
    "year": today.year,
    "month_page": default_page  # 현재 월이 포함된 그룹으로 시작
}

# 앱 레이아웃 설정
app.layout = create_layout(initial_state)

# 콜백 등록
callbacks.register_callbacks(app, df)

# 데이터 업데이트 함수 (callbacks.py 파일에서 접근 가능하도록 전역 함수로 추가)
def update_firebase_data(bid_id, field, value):
    """Firebase에 데이터 업데이트 함수"""
    try:
        # 앱 내부 컬럼명을 Firebase 컬럼명으로 변환
        firebase_field = field
        if field == "입찰금액_1순위":
            firebase_field = "낙찰금액"
        elif field == "계약 기간 내":
            firebase_field = "사업금액"
        elif field == "실수요기관":
            firebase_field = "채권자명"
        elif field == "입찰결과_1순위":
            firebase_field = "개찰업체정보"
        
        # 사용자 입력 레퍼런스
        user_input_ref = db.reference(f'/user_inputs/{bid_id}')
        
        # 현재 값 가져오기
        current_data = user_input_ref.get() or {}
        
        # 값 업데이트
        current_data[firebase_field] = float(value)
        current_data['마지막_수정일'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        current_data['수정자'] = 'dashboard_user'
        
        # Firebase 업데이트
        user_input_ref.set(current_data)
        
        # 로컬 DataFrame도 업데이트
        global df
        df.loc[df['bid_id'] == bid_id, field] = float(value)
        
        return True, "데이터가 성공적으로 업데이트되었습니다."
    except Exception as e:
        print(f"데이터 업데이트 오류: {e}")
        return False, f"업데이트 중 오류가 발생했습니다: {str(e)}"

# app 객체에 함수 추가 (callbacks.py에서 접근할 수 있도록)
app.update_firebase_data = update_firebase_data

# 실행
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)