"""
agent/agent_search.py
---------------------
실제 agent_search 역할(신규 투자 방법론 탐색) 함수 정의.
- run_agent_search()는 신규 방법론 제안(딕셔너리/리스트) 반환
- 실제 구현은 향후 확장 가능, 예시는 더미 데이터
"""


import os

import json

try:
    import google.genai as genai
    GENAI_LIBRARY = 'genai'
except ImportError:
    try:
        import google.generativeai as genai
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
    if GENAI_LIBRARY == 'genai':
        return genai.GenerativeModel(model_name)
    if GENAI_LIBRARY == 'generativeai':
        genai.configure(api_key=api_key)
        if hasattr(genai, 'GenerativeModel'):
            return genai.GenerativeModel(model_name)
        if hasattr(genai, 'get_model'):
            return genai.get_model(model_name)
        raise RuntimeError('google.generativeai에서 모델을 생성할 수 없습니다.')
    raise RuntimeError('지원되지 않는 AI 모델 인터페이스입니다.')

def run_agent_search():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY 환경변수가 필요합니다.")
    exclude_names = get_existing_method_names()
    exclude_str = ", ".join(exclude_names) if exclude_names else "(없음)"
    model_name = 'gemini-pro'
    model = create_gemini_model(model_name, api_key)
    prompt = (
        f"최신 투자 전략 10가지를 아래 형식의 JSON 리스트로 요약해줘. "
        f"단, 우리 시스템에 이미 적용된 전략({exclude_str})은 모두 제외하고, "
        f"아직 적용하지 않은 새로운 전략만 포함해줘. "
        "각 전략은 반드시 고유해야 하며, 다음 key를 포함해야 해: "
        "방법론명, 출처/근거, 핵심 아이디어, 현재 시스템과의 차이점, 예상 적용 시장, 기대 효과, 구현 난이도, 검증 요청 사항. "
        "예시: [{\"방법론명\":..., ...}, ...]"
    )
    response = model.generate_content(prompt)
    content = response.text.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        if content.endswith("```"):
            content = content[:-3]
    try:
        methods = json.loads(content)
        if not isinstance(methods, list):
            raise ValueError("Gemini 응답이 리스트 형태가 아님")
        return methods
    except Exception as e:
        raise RuntimeError(f"Gemini 응답 파싱 실패: {e}\n원본: {content}")
