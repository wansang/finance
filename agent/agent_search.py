"""
agent/agent_search.py
---------------------
실제 agent_search 역할(신규 투자 방법론 탐색) 함수 정의.
- run_agent_search()는 신규 방법론 제안(딕셔너리/리스트) 반환
- 실제 구현은 향후 확장 가능, 예시는 더미 데이터
"""

import os
import json
from google.generativeai import GenerativeModel

def run_agent_search():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY 환경변수가 필요합니다.")
    # Gemini 모델 초기화
    model = GenerativeModel('gemini-pro', api_key=api_key)
    prompt = (
        "최신 투자 전략 10가지를 아래 형식의 JSON 리스트로 요약해줘. "
        "단, 우리 시스템(예: 모멘텀, 밸류, 퀀트, ETF 분산, 인덱스, AI 추천 등 기존에 적용된 전략)은 모두 제외하고, "
        "아직 적용하지 않은 새로운 전략만 포함해줘. "
        "각 전략은 반드시 고유해야 하며, 다음 key를 포함해야 해: "
        "방법론명, 출처/근거, 핵심 아이디어, 현재 시스템과의 차이점, 예상 적용 시장, 기대 효과, 구현 난이도, 검증 요청 사항. "
        "예시: [{\"방법론명\":..., ...}, ...]"
    )
    response = model.generate_content(prompt)
    # Gemini 응답에서 JSON 파싱
    try:
        # Gemini가 코드블록으로 감싸서 줄 수도 있음
        content = response.text.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
            if content.endswith("```"):
                content = content[:-3]
        methods = json.loads(content)
        # 리스트가 아니면 예외
        if not isinstance(methods, list):
            raise ValueError("Gemini 응답이 리스트 형태가 아님")
        return methods
    except Exception as e:
        raise RuntimeError(f"Gemini 응답 파싱 실패: {e}\n원본: {response.text}")
