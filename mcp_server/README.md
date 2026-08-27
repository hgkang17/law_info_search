# 법령검색 MCP 서버

Claude Desktop이나 ChatGPT Desktop 안에서 대한민국 법제처 국가법령정보를
직접 검색하고 조문을 읽게 해 주는 서버다. Claude나 ChatGPT의 **기존
구독으로 그대로 돌아간다** — 이 서버 자체는 요금이 없다. 국가법령정보
API 키만 무료로 발급받으면 된다(https://open.law.go.kr).

## 하는 일

도구 열다섯 개를 내놓는다. `llm/tools.py`가 AI 검토 탭에서 Gemini에게
주던 것과 같은 함수다.

- **search_law** — 법령ㆍ행정규칙ㆍ자치법규를 이름이나 본문 키워드로 찾는다.
- **get_article** — 법령의 특정 조문 본문을 읽는다.
- **get_document** — 행정규칙ㆍ자치법규 전체 본문을 읽는다.
- **search_admin_rule** — 훈령ㆍ예규ㆍ고시ㆍ지침을 별도로 찾는다.
- **get_annexes** — 별표ㆍ별지서식을 찾고, 한 건이면 원문을 Markdown으로 읽는다.
- **legal_research** — 절차ㆍ제출서류 같은 복합 질문을 법령ㆍ행정규칙ㆍ
  별표 검색으로 나누어 종합 조사한다.
- **search_cases** — 법령해석례ㆍ판례ㆍ헌재ㆍ행심ㆍ위원회 결정례를 찾는다.
- **get_case** — 해석례ㆍ판례ㆍ결정례 본문을 읽는다.
- **search_inquiries** — 중앙부처 질의회신(부처 1차 해석)을 찾는다.
- **get_inquiry** — 질의회신 본문(질의요지·회답)을 읽는다.
- **get_historical_law** — 특정 날짜의 시행본(행위시법) 또는 조문 이력을 읽는다.
- **compare_old_new** — 신구법 대조표를 읽는다.
- **ordinance_radar** — 조례 목적 조문의 근거 상위법과 현행 시행일을 대조한다.
- **cite_check** — 판례가 후속 판결에서 변경·폐기됐는지 추적한다.
- **impact_map** — 특정 조문이 판례·해석례·헌재·행심·조례에 인용된 영향을 모은다.

Claude나 ChatGPT가 법령 내용을 답할 때 기억에 의존하지 않고 이 도구로
실제 자료를 찾아 답하도록 시스템 지시문에 못박아 뒀다.

## 준비물

1. 이 저장소를 내려받은 폴더의 절대경로
   (예: `D:\path\to\law-search-ai`)
2. 국가법령정보 공동활용 OC 인증키 (https://open.law.go.kr, 무료 발급)
3. 파이썬과 의존 패키지

```
pip install -r requirements.txt
```

## Claude Desktop에 연결하기

1. Claude Desktop → 설정 → 개발자(Developer) → "구성 편집"을 누르면
   `claude_desktop_config.json`이 열린다.
   - Windows 경로: `%APPDATA%\Claude\claude_desktop_config.json`
2. `mcpServers`에 아래를 추가한다. **경로 두 곳과 인증키를 자기 것으로
   바꾼다.**

```json
{
  "mcpServers": {
    "법령검색": {
      "command": "C:\\Users\\사용자이름\\AppData\\Local\\Programs\\Python\\Python311\\python.exe",
      "args": [
        "D:\\path\\to\\law-search-ai\\mcp_server\\server.py"
      ],
      "env": {
        "LAW_API_KEY": "발급받은 OC 인증키"
      }
    }
  }
}
```

3. Claude Desktop을 완전히 껐다가 다시 켠다(창만 닫지 말고 완전 종료).
4. 새 대화에서 도구 아이콘(🔨)을 눌러 "법령검색"이 보이면 연결된 것이다.

## ChatGPT Desktop에 연결하기

ChatGPT Desktop은 설정 화면에서 직접 등록한다(JSON 파일을 손으로
고치지 않는다).

1. ChatGPT Desktop → 설정 → **MCP servers** → **Add server**
2. 이름: `법령검색` (아무 이름이나 괜찮다)
3. 타입: **STDIO**
4. 명령어에 아래 한 줄을 넣는다 (경로는 자기 것으로 바꾼다):

```
C:\Users\사용자이름\AppData\Local\Programs\Python\Python311\python.exe "D:\path\to\law-search-ai\mcp_server\server.py"
```

5. 환경변수에 `LAW_API_KEY` = 발급받은 OC 인증키를 추가한다.
6. 저장 후 ChatGPT Desktop을 재시작한다.

## 확인

Claude나 ChatGPT에서 아무 법령이나 물어본다.

```
농지법 제1조 목적이 뭐야?
```

도구를 부르는 과정이 화면에 보이고(검색 → 조문 읽기), 답이 실제
조문 원문에 근거해서 나오면 정상이다.

## 인증키를 안 넣었다면

서버는 뜨지만 도구를 부르는 순간 인증 오류가 난다. 콘솔 로그에
"LAW_API_KEY 환경변수가 비어 있습니다"가 남는다. 위 설정의 `env`
자리에 키를 넣었는지 다시 확인한다.

## 법령프로그램(Qt 앱)과의 관계

Claude/ChatGPT Desktop에 등록했을 때는 별도 프로세스로 독립 실행된다.
법령프로그램 안의 AI 채팅을 쓸 때는 프로그램이 같은 서버를 자동으로
띄우므로 전역 MCP 등록이 필요 없다. 소스 실행은
`python -m mcp_server.server`, onefile 배포본은
`국가법령정보 통합검색.exe --mcp-server` 방식이다.

ChatGPT 데스크톱 앱, Codex CLI, IDE 확장은 같은 Codex 호스트의 MCP
설정을 공유한다. 한쪽에서 `법령검색` 서버를 등록한 뒤 재시작하면 다른
Codex 클라이언트에서도 같은 도구를 사용할 수 있다.
