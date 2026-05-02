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

    # strategy_config.json에서 조정 가능한 숫자/불리언 파라미터 목록 동적 로드
    import pathlib, json as _json
    config_path = pathlib.Path(__file__).parent.parent / 'strategy_config.json'
    try:
        _cfg = _json.loads(config_path.read_text(encoding='utf-8'))
        tunable_keys = [k for k, v in _cfg.items() if isinstance(v, (int, float, bool)) and not isinstance(v, list)]
        tunable_str = ", ".join(tunable_keys)
    except Exception:
        tunable_str = "SMA50, SMA150, SMA200, RSI_LENGTH, BB_LENGTH, BB_STD, STOCH_RSI_LENGTH, TRAILING_STOP_PCT, PROFIT_TARGET_PCT, ATR_STOP_MULTIPLIER, ATR_TARGET_MULTIPLIER, VALIDATE_MAX_HOLD_DAYS, TIER1_WIN_RATE, TIER2_WIN_RATE"

    model_name = 'gemini-flash-latest'
    model = create_gemini_model(model_name, api_key)
    prompt = (
        "너는 40년 경력의 투자 방법 검색 전문가(agent_search)다.\n\n"
        "【핵심 제약】\n"
        "우리 시스템은 새로운 지표나 코드를 추가할 수 없다. "
        "오직 아래 strategy_config.json 파라미터 값 조정만으로 전략을 변경할 수 있다.\n\n"
        f"【조정 가능한 파라미터 목록】\n{tunable_str}\n\n"
        "위 파라미터들의 의미:\n"
        "- SMA50/150/200: 이동평균 기간\n"
        "- RSI_LENGTH: RSI 계산 기간\n"
        "- BB_LENGTH/BB_STD: 볼린저밴드 기간/표준편차 배수\n"
        "- STOCH_RSI_LENGTH/STOCH_K/STOCH_D: 스토캐스틱RSI 파라미터\n"
        "- TRAILING_STOP_PCT/TRAILING_STOP_ACTIVATE_PCT: 트레일링 스톱 비율\n"
        "- PROFIT_TARGET_PCT/VALIDATE_MAX_HOLD_DAYS: 목표수익률/최대보유기간\n"
        "- ATR_STOP_MULTIPLIER/ATR_TARGET_MULTIPLIER: ATR 기반 손절/목표 배수\n"
        "- TIER1_WIN_RATE/TIER2_WIN_RATE: 매수 진입 기준 승률 임계값\n"
        "- US_* 계열: 미국 시장 전용 동일 파라미터\n\n"
        "【요청】\n"
        f"이미 시도된 전략({exclude_str})을 제외하고, "
        "위 파라미터 조정만으로 구현 가능한 투자 전략 20가지를 제안해줘.\n\n"
        "각 전략은 반드시:\n"
        "1. 어떤 파라미터를 어떤 값으로 바꿔야 하는지 구체적으로 명시할 것\n"
        "2. 차트 기술(패턴, 기술적 지표, 시각적 신호) 기반 근거가 있을 것\n"
        "3. 새로운 코드/지표 추가 없이 파라미터 조정만으로 적용 가능할 것\n\n"
        "각 항목에 반드시 다음 key를 포함해줘: "
        "방법론명, 출처/근거, 핵심 아이디어, 현재 시스템과의 차이점, 예상 적용 시장, 기대 효과, 구현 난이도, 검증 요청 사항, 제안_파라미터_변경.\n\n"
        "'제안_파라미터_변경'은 반드시 {\"파라미터명\": 제안값, ...} 형태의 객체로, "
        "조정 가능한 파라미터 목록에 있는 키만 사용할 것. "
        "파라미터 변경이 없는 전략은 제외할 것.\n\n"
        "예시: [{\"방법론명\": \"...\", ..., \"제안_파라미터_변경\": {\"RSI_LENGTH\": 10, \"TRAILING_STOP_PCT\": 0.04}}, ...]\n"
        "반드시 JSON 리스트로만 응답하라."
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
