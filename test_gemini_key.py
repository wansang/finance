import os
import sys

KEY = os.environ.get('GEMINI_API_KEY')
if not KEY:
    print('ERROR: GEMINI_API_KEY 환경 변수가 설정되지 않았습니다.')
    print('예: export GEMINI_API_KEY=AIza...')
    sys.exit(1)

print('GEMINI_API_KEY is set. Checking library availability...')

try:
    import google.genai as genai
    library = 'genai'
except Exception:
    try:
        import google.generativeai as genai
        library = 'generativeai'
    except Exception as e:
        print('ERROR: Neither google.genai nor google.generativeai 라이브러리를 import할 수 없습니다.')
        print('Exception:', repr(e))
        sys.exit(1)

print(f'Using library: {library}')

def supported_models():
    return [
        'gemini-flash-latest',
        'gemini-pro-latest',
        'gemini-2.5-flash',
        'gemini-2.5-pro',
        'gemini-2.5-flash-lite',
        'gemini-2.0-flash',
        'gemini-2.0-flash-001'
]


def try_model(model_name):
    global genai
    if library == 'genai':
        client = genai.Client(api_key=KEY)
        chat = client.chats.create(model=model_name)
        response = chat.send_message('안녕하세요. API 키 테스트입니다.')
        if hasattr(response, 'candidates') and response.candidates:
            return response.candidates[0].content
        if hasattr(response, 'text'):
            return response.text
        return str(response)

    genai.configure(api_key=KEY)
    if hasattr(genai, 'get_model'):
        model = genai.get_model(model_name)
        response = model.generate_content('안녕하세요. API 키 테스트입니다.')
        return getattr(response, 'text', str(response))
    if hasattr(genai, 'generate_text'):
        response = genai.generate_text(model=model_name, prompt='안녕하세요. API 키 테스트입니다.')
        return getattr(response, 'text', str(response))
    raise RuntimeError('지원되지 않는 genai/generativeai 인터페이스입니다.')

try:
    content = None
    for model_name in supported_models():
        try:
            print(f'Trying model: {model_name}')
            content = try_model(model_name)
            print(f'Success with model: {model_name}')
            break
        except Exception as err:
            err_str = str(err)
            print(f'Model {model_name} failed: {err_str}')
            if 'NOT_FOUND' in err_str or 'no longer available' in err_str:
                continue
            raise
    if content is None:
        raise RuntimeError('사용 가능한 Gemini 모델을 찾을 수 없습니다.')

    print('=== API 호출 결과 ===')
    print(content)
    print('=== 호출 성공 ===')
except Exception as err:
    print('ERROR: Gemini/Generative AI API 호출 중 실패했습니다.')
    print(type(err).__name__, err)
    sys.exit(1)

    print('=== API 호출 결과 ===')
    print(content)
    print('=== 호출 성공 ===')
except Exception as err:
    print('ERROR: Gemini/Generative AI API 호출 중 실패했습니다.')
    print(type(err).__name__, err)
    sys.exit(1)
