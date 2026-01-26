import streamlit as st
import os
import json
import pdfplumber
import folium
from google import genai
from streamlit_folium import st_folium
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# --- 설정 ---
# 배포용 Streamlit Cloud의 Secrets 설정
try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("API Key가 설정되지 않았습니다. Streamlit Secrets 설정을 확인해주세요.")
    st.stop()

# GEMINI_API_KEY = "사용자님의 키" 유지
client = genai.Client(api_key=GEMINI_API_KEY)

# --- 경로 설정 (안드로이드 배포용 상대경로) ---
BASE_DIR = os.getcwd()
# 한글 폰트파일 경로가 App과  같은 위치에 있다고 가정
FONT_PATH = os.path.join(BASE_DIR, "NanumGothic.ttf")
# FONT_PATH = "C:/Windows/Fonts/malgun.ttf" 

class TravelAppEngine:
    def __init__(self, country, city, web_sites_list):
        # 국가명과 도시명을 조합하여 상세 경로 설정
        self.country = country
        self.city = city
        # 경로 예: D:\TourGuide\Spain\Madrid
        self.target_path = os.path.join(BASE_DIR,"TourGuide",country, city)
        self.web_sites = web_sites_list
        # self.output_dir = "Travel_Results_App" # 배포 서버(리눅스)는 쓰기 권한이 제한될 수 있어 /tmp 또는 현재 작업 폴더 권장

        if not os.path.exists(self.target_path):
            os.makedirs(self.target_path, exist_ok=True)

    def extract_local_pdf(self):
        """설정된 국가/도시 폴더에서 PDF 텍스트 추출"""
        text_data = ""
        if os.path.exists(self.target_path):
            pdf_files = [f for f in os.listdir(self.target_path) if f.lower().endswith(".pdf")]
            if not pdf_files:
                return "해당 폴더에 PDF 파일이 없습니다."
            
            for file in pdf_files:
                with pdfplumber.open(os.path.join(self.target_path, file)) as pdf:
                    for page in pdf.pages:
                        text_data += (page.extract_text() or "")
        else:
            return f"경로를 찾을 수 없습니다: {self.target_path}"
        
        return text_data[:5000] # 토큰 제한을 고려한 슬라이싱

    def get_travel_plan(self, must_count, good_count, user_feedback=""):
        local_info = self.extract_local_pdf()
        
        # 피드백 반영 로직 추가
        feedback_context = f"\n[추가 요청사항]: {user_feedback}" if user_feedback else ""

        prompt = f"""
        당신은 전문 여행 가이드입니다. {self.country} {self.city} 여행 계획을 세워주세요.
        참고 소스: {self.web_sites} / 로컬 자료: {local_info} {feedback_context}
        
        요구사항:
        1. 선정된 'Must to visit' {must_count}곳, 'Good to visit' {good_count}곳을 지리적으로 가장 효율적인 이동 경로(TSP 알고리즘 고려) 순으로 배치하고 
           1번부터 번호를 부여하세요.
        2. 장소 간의 거리와 동선이 꼬이지 않도록 '직선 거리'와 '실제 도로망'을 고려하세요.
        3. 좌표(lat, lng)는 반드시 구글 지도(Google Maps)와 일치하는 실제 위치여야 합니다. 
           모르면 검색해서라도 정확한 값을 소수점 6자리까지 적으세요.
        4. 반드시 아래 JSON 형식으로만 답변하세요.
        {{
            "locations": [
                {{
                    "no": "번호",
                    "type": "Must to visit" 또는 "Good to visit",
                    "name": "장소이름", "lat": 위도, "lng": 경도,
                    "desc": "설명(예약/입장료/방문팁)",
                    "price": "입장료", "reserve": "예약여부"
                }}
            ]
        }}
        """
        response = client.models.generate_content(
            model='gemini-2.5-flash', # 혹은 사용자님의 모델 버전
            contents=prompt,
            config={'response_mime_type': 'application/json'}
        )
        return json.loads(response.text)


    # --- PDF 생성과 저장 루틴 ---
    def generate_and_save_pdf(self, data, map_html_path):
        """분석 결과를 PDF로 만들어 최상위 폴더에 저장"""
        root_path = BASE_DIR

         # 1. 만약 저장 폴더가 없으면 생성 (에러 방지)
        if not os.path.exists(root_path):
            try:
                os.makedirs(root_path)
            except Exception as e:
                return f"폴더 생성 실패: {e}"
            
        pdf_file_name = f"{self.country}_{self.city}_Tour_Guide.pdf"
        save_path = os.path.join(root_path, pdf_file_name)

        # 2. 폰트 등록 (파일 존재 여부 확인 필수)
        if not os.path.exists(FONT_PATH):
            return f"폰트 파일을 찾을 수 없습니다: {FONT_PATH}"
        
        # pdfmetrics.registerFont(TTFont('KoreanFont', FONT_PATH))

        # 3. PDF 문서 구성
        doc = SimpleDocTemplate(save_path, pagesize=A4)
        styles = getSampleStyleSheet()
        style_kor = ParagraphStyle('Kor', fontName='KoreanFont', fontSize=10, leading=14)
        style_title = ParagraphStyle('Title', fontName='KoreanFont', fontSize=16, leading=20, spaceAfter=18)
        style_link = ParagraphStyle('Link', fontName='KoreanFont', fontSize=10, textColor='blue', underline=True)

        elements = []
        elements.append(Paragraph(f"{self.city} 여행 가이드 리포트 ({self.country})", style_title))
        
        # PDF 내 지도 링크 삽입
        # map_url = f"file:///{map_html_path.replace(os.sep, '/')}"
        # elements.append(Paragraph(f'<a href="{map_url}">▶ 여기를 클릭하여 상세 경로 지도(HTML) 열기</a>', style_link))
        # elements.append(Spacer(1, 20))
        # 1. 모든 좌표를 구글 지도 경로용 URL로 합치기
        locs = data['locations']
        origin = f"{locs[0]['lat']},{locs[0]['lng']}"
        destination = f"{locs[-1]['lat']},{locs[-1]['lng']}"
        waypoints = "|".join([f"{l['lat']},{l['lng']}" for l in locs[1:-1]])
        
        # 구글 지도 길찾기 URL (브라우저/앱 모두 호환)
        google_maps_url = f"https://www.google.com/maps/dir/?api=1&origin={origin}&destination={destination}&waypoints={waypoints}&travelmode=driving"

        # 2. PDF 내 지도 링크 삽입 (HTML 파일 대신 구글 지도 링크로 교체)
        elements.append(Paragraph(f'<a href="{google_maps_url}" color="blue">▶ [스마트폰 전용] 구글 지도로 전체 경로 보기</a>', style_link))
        elements.append(Spacer(1, 20))

        for loc in data['locations']:
            text = f"<b>{loc['no']}. [{loc['type']}] {loc['name']}</b><br/>{loc['desc']}<br/>- 입장료: {loc['price']} | 예약: {loc['reserve']}<br/>"
            elements.append(Paragraph(text, style_kor))
            elements.append(Spacer(1, 15))

        try:
            # 빌드
            doc.build(elements)
            # 중요: 빌드 후 파일이 실제로 생성되었는지 다시 한 번 확인
            if os.path.exists(save_path):
                return save_path
            else:
                return "파일 생성 명령은 완료되었으나 실제 경로에서 파일을 찾을 수 없습니다."
        except PermissionError:
            return f"오류: '{pdf_file_name}' 파일이 이미 열려 있습니다. 닫고 다시 시도하세요."
        except Exception as e:
            return f"PDF 빌드 중 오류 발생: {e}"
               
# --- Streamlit UI ---
st.set_page_config(page_title="AI 스마트 가이드", layout="centered")

# 세션 상태 초기화
if "plan_data" not in st.session_state:
    st.session_state.plan_data = None
if "result_path" not in st.session_state:
    st.session_state.result_path = None

st.title("🌍 AI 맞춤형 도시 여행 가이드")

# 사이드바 설정
st.sidebar.header("📍 여행지 선택")
country_select = st.sidebar.selectbox("국가 선택", ["Spain", "Portugal"])
city_input = st.sidebar.text_input("도시 입력", value="Madrid")
web_sites_input = st.sidebar.text_area("참고 사이트", value="https://www.spain.info")
web_sites_list = [url.strip() for url in web_sites_input.split(',')]
must_n = st.sidebar.number_input("Must to visit", 1, 10, 5)
good_n = st.sidebar.number_input("Good to visit", 1, 10, 5)

# 헬퍼 함수: 계획 생성 및 PDF 저장까지 한 번에 처리
# 헬퍼 함수: feedback 변수를 get_travel_plan에 정확히 전달
def generate_all(country, city, web_list, must, good, feedback=""):
    engine = TravelAppEngine(country, city, web_list)
    
    # 1. Gemini로부터 플랜 가져오기 (피드백 반영)
    plan = engine.get_travel_plan(must, good, user_feedback=feedback)
    
    # 2. 데이터 최적화 (PDF 생성 전 반드시 수행)
    locs = plan['locations']
    
    def optimize_route_internal(locations):
        if not locations: return []
        # 위경도를 실수형으로 변환하여 계산 오류 방지
        for l in locations:
            l['lat'] = float(l['lat'])
            l['lng'] = float(l['lng'])
            
        unvisited = locations[:]
        optimized = [unvisited.pop(0)]
        while unvisited:
            last = optimized[-1]
            next_loc = min(unvisited, key=lambda x: (x['lat']-last['lat'])**2 + (x['lng']-last['lng'])**2)
            optimized.append(next_loc)
            unvisited.remove(next_loc)
        return optimized

    plan['locations'] = optimize_route_internal(locs)
    
    # 3. 번호 재부여
    for i, loc in enumerate(plan['locations']):
        loc['no'] = str(i + 1)

    # 4. 지도 저장 및 PDF 생성
    m_temp = folium.Map(location=[plan['locations'][0]['lat'], plan['locations'][0]['lng']], zoom_start=14)
    map_path = os.path.join(engine.target_path, "route_map.html")
    m_temp.save(map_path)
    
    pdf_path = engine.generate_and_save_pdf(plan, map_path)
    return plan, pdf_path

# --- 결과 출력 영역 내 다운로드 버튼 부분 ---
# 최적화 로직이 generate_all 내부로 들어갔으므로, 
# 결과 출력 영역(if st.session_state.plan_data:) 안에 있는 중복된 optimize_route 함수는 삭제해도 됩니다.
    

# 실행 버튼
if st.sidebar.button("가이드북 생성 시작"):
    with st.spinner("정보 분석 및 PDF 생성 중..."):
        plan, pdf = generate_all(country_select, city_input, web_sites_list, must_n, good_n)
        st.session_state.plan_data = plan
        st.session_state.result_path = pdf

# --- 결과 출력 영역 ---
if st.session_state.plan_data:
    plan_data = st.session_state.plan_data
    locs = plan_data['locations']
    pdf_path = st.session_state.get("result_path")
       
    # 1. 다운로드 버튼 (성공 메시지 포함)
    if pdf_path and os.path.exists(pdf_path):
        st.success(f"✅ 가이드 분석 완료!")
        with open(pdf_path, "rb") as f:
            st.download_button(
                label="📥 가이드북 PDF 저장하기 (휴대폰 저장)",
                data=f.read(),
                file_name=os.path.basename(pdf_path),
                mime="application/pdf",
                use_container_width=True, # 모바일 화면 꽉차게
                type="primary" #파란색 강조버튼
            )
    
    # 2. 지도 표시
    st.subheader(f"🗺️ {city_input} 추천 방문 경로")
    m = folium.Map(location=[locs[0]['lat'], locs[0]['lng']], zoom_start=13, control_scale=True)
    path_points = [[l['lat'], l['lng']] for l in locs]
    
    for loc in locs:
        color = 'red' if loc['type'] == 'Must to visit' else 'blue'
        folium.Marker([loc['lat'], loc['lng']], popup=loc['name'], 
                      icon=folium.Icon(color=color)).add_to(m)
    
    folium.PolyLine(path_points, color="green", weight=2.5).add_to(m)
    # 부모 컨테이너 너비에 맞춤, 모바일에서 한눈에 들어오는 높이, 불필요한 데이터 반환을 막아 성능 향상
    st_folium(m, use_container_width=True, height=350, key=f"map_{len(locs)}", returned_objects=[]) 
    
    # 3. 상세 정보 카드
    st.subheader("📋 장소별 상세 가이드")
    for idx, loc in enumerate(locs):
        # 모바일 가독성을 위해 번호와 이름을 강조
        title = f"📍 {loc.get('no')}. {loc.get('name')}"
        with st.expander(title, expanded=False): # 모바일에서는 닫아두는 것이 좋음
            st.markdow(f"**[{loc.get('type')}]**")
            st.write(loc.get('desc', '설명이 없습니다.'))
            st.caption(f"💰 {loc.get('price', '-')} | 🎟️ {loc.get('reserve', '-')}")
            
            # 구글 지도 링크 생성 (안전하게 get() 사용)
            lat = loc.get('lat')
            lng = loc.get('lng')
            
            if lat and lng:
                # 폰에서 클릭 시 바로 구글 지도 앱으로 연결되는 링크
                map_link = f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
                st.link_button(f"📍 {loc.get('name')} 위치 확인 (구글 지도)", map_link, use_container_width=True)

    # 4. 추가 요청 (채팅 입력창)
    st.divider()
    user_feedback = st.chat_input("수정 요청사항을 입력하세요 (예: 2번 장소 제외해줘)")
    
    if user_feedback:
        with st.spinner("요청하신 내용을 반영하여 다시 생성 중..."):
            # 피드백 반영하여 데이터와 PDF를 동시에 갱신
            new_plan, new_pdf = generate_all(country_select, city_input, web_sites_list, must_n, good_n, user_feedback)
            st.session_state.plan_data = new_plan
            st.session_state.result_path = new_pdf
            st.rerun()

    if st.button("처음부터 다시 시작"):
        st.session_state.plan_data = None
        st.session_state.result_path = None

        st.rerun()




