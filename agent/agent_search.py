"""
agent/agent_search.py
---------------------
실제 agent_search 역할(신규 투자 방법론 탐색) 함수 정의.
- run_agent_search()는 신규 방법론 제안(딕셔너리/리스트) 반환
- 실제 구현은 향후 확장 가능, 예시는 더미 데이터
"""


import os

import json

genai = None
GENAI_LIBRARY = None
try:
    import google.genai as genai
    if hasattr(genai, 'GenerativeModel'):
        GENAI_LIBRARY = 'genai'
    else:
        # google.genai에 GenerativeModel이 없으면 google.generativeai로 fallback
        import google.generativeai as genai2
        if hasattr(genai2, 'GenerativeModel') or hasattr(genai2, 'get_model'):
            genai = genai2
            GENAI_LIBRARY = 'generativeai'
except ImportError:
    try:
        import google.generativeai as genai
        if hasattr(genai, 'GenerativeModel') or hasattr(genai, 'get_model'):
            GENAI_LIBRARY = 'generativeai'
    except ImportError:
        genai = None
        GENAI_LIBRARY = None

BACKLOG_HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'searchBacklog_history.json')

# 기존 시스템에 적용된 전략명 자동 추출
def get_existing_method_names():
    names = set()
    if os.path.exists(BACKLOG_HISTORY_FILE):
        try:
            with open(BACKLOG_HISTORY_FILE, 'r', encoding='utf-8') as f:
                items = json.load(f)
                for entry in items:
                    method = entry.get('method', {})
                    name = method.get('방법론명')
                    if name:
                        names.add(name)
        except Exception:
            pass
    return sorted(list(names))


def create_gemini_model(model_name, api_key):
    # 단발성 프롬프트는 GenerativeModel/generate_content만 사용
    # google.genai에서 GenerativeModel 미지원 시 google.generativeai로 fallback
    if GENAI_LIBRARY is None:
        raise RuntimeError('google-genai 및 google-generativeai 패키지가 모두 import되지 않았거나, GenerativeModel/get_model 속성이 없습니다.\n패키지 설치 및 버전을 확인하세요. (pip install --upgrade google-genai google-generativeai)')
    if GENAI_LIBRARY == 'genai':
        # 최신 방식: GenerativeModel, 구버전: Client/chats.create
        if hasattr(genai, 'GenerativeModel'):
            return genai.GenerativeModel(model_name)
        if hasattr(genai, 'Client'):
            client = genai.Client(api_key=api_key)
            return client.chats.create(model=model_name)
        raise RuntimeError('google-genai에서 GenerativeModel/Client를 찾을 수 없습니다.')
    if GENAI_LIBRARY == 'generativeai':
        genai.configure(api_key=api_key)
        if hasattr(genai, 'GenerativeModel'):
            return genai.GenerativeModel(model_name)
        if hasattr(genai, 'get_model'):
            return genai.get_model(model_name)
        raise RuntimeError('google-generativeai에서 GenerativeModel/get_model을 찾을 수 없습니다.')
    raise RuntimeError('지원되지 않는 AI 모델 인터페이스입니다.')

def run_agent_search():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY 환경변수가 필요합니다.")
    exclude_names = get_existing_method_names()
    exclude_str = ", ".join(exclude_names) if exclude_names else "(없음)"
    model_name = 'gemini-flash-latest'
    model = create_gemini_model(model_name, api_key)
    prompt = (
        f"최신 투자 전략 20가지를 아래 형식의 JSON 리스트로 요약해줘. "
        f"단, 우리 시스템에 이미 적용된 전략({exclude_str})은 모두 제외하고, "
        f"아직 적용하지 않은 새로운 전략만 포함해줘. "
        "각 전략은 반드시 고유해야 하며, 다음 key를 포함해야 해: "
        "방법론명, 출처/근거, 핵심 아이디어, 현재 시스템과의 차이점, 예상 적용 시장, 기대 효과, 구현 난이도, 검증 요청 사항. "
        "단, 반드시 '차트의 기술'(차트 패턴, 기술적 분석, 시각적 신호 등) 기반의 근거가 명확히 드러나는 전략만 포함하고, "
        "차트적으로 우리 시스템에 실제 적용할 수 있는 전략만 제안해줘. "
        "차트와 무관하거나, 차트 근거가 불명확한 전략은 모두 제외해줘. "
        "예시: [{\"방법론명\":..., ...}, ...]"
    )
    # 모델 객체가 generate_content/send_message 중 지원하는 메서드로 분기
    if hasattr(model, 'generate_content'):
        response = model.generate_content(prompt)
        content = response.text.strip()
    elif hasattr(model, 'send_message'):
        response = model.send_message(prompt)
        content = response.text.strip() if hasattr(response, 'text') else str(response)
    else:
        raise RuntimeError('AI 모델 객체가 generate_content/send_message를 지원하지 않습니다.')

    # 코드블록 내 JSON만 추출
    import re
    json_block = None
    # ```json ... ``` 또는 ``` ... ``` 블록 추출
    match = re.search(r"```json\\s*([\s\S]+?)```", content)
    if not match:
        match = re.search(r"```[\s\S]*?([\[{][\s\S]+?)```", content)
    if match:
        json_block = match.group(1).strip()
    else:
        # 코드블록이 없으면 기존 content 전체 사용
        json_block = content

    try:
        methods = json.loads(json_block)
        if not isinstance(methods, list):
            raise ValueError("Gemini 응답이 리스트 형태가 아님")
        return methods
    except Exception as e:
        raise RuntimeError(f"Gemini 응답 파싱 실패: {e}\n원본: {json_block}")
