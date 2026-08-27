"""법령검색 MCP 서버.

Claude Desktop이나 ChatGPT Desktop이 이 파일을 별도 프로세스로 띄워
표준입출력(stdio)으로 대화한다. 그 프로세스 안에서 Claude나 ChatGPT가
직접 법제처 API를 검색하고 조문을 읽을 수 있게 도구들을 내놓는다.

llm/tools.py가 Gemini에 넘기던 도구 함수를 그대로 가져다 쓴다. 함수
시그니처와 docstring이 곧 "모델이 읽는 도구 설명"이라는 점은 Gemini의
자동 함수 호출이나 MCP나 똑같아서, 새로 쓸 이유가 없었다.

실행 방법
---------
Claude Desktop 설정(claude_desktop_config.json)이나 ChatGPT Desktop의
MCP servers 설정에 이 파일을 STDIO 서버로 등록한다. 자세한 안내는
mcp_server/README.md를 본다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Claude/ChatGPT Desktop은 이 파일을 프로젝트 루트가 아닌 임의의 실행
# 위치에서 띄운다. sys.path에 루트를 직접 넣지 않으면 molit_cgm_expc_api나
# models.law를 못 찾는다.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from llm.tools import build_tools  # noqa: E402

# 국가법령정보 공동활용 OC 인증키. Claude/ChatGPT Desktop 설정에서 이
# 서버를 등록할 때 환경변수로 넘긴다. 코드에 박아 두지 않는 이유는
# 이 저장소가 공개될 수 있기 때문이다.
_OC_KEY = os.environ.get("LAW_API_KEY", "").strip()
if not _OC_KEY:
    # 여기서 그냥 죽으면 Claude/ChatGPT 쪽에는 "서버 연결 끊김"으로만
    # 보이고 이유를 알 수 없다. 서버는 띄우고 도구 호출마다 나는
    # 자연스러운 실패(빈 키로 API 호출 실패)로 이유가 전달되게 둔다.
    print(
        "[법령검색 MCP] 경고: LAW_API_KEY 환경변수가 비어 있습니다. "
        "도구를 부르면 인증 오류가 날 것입니다. "
        "https://open.law.go.kr 에서 발급받은 키를 설정하세요.",
        file=sys.stderr,
    )

mcp = FastMCP(
    "법령검색",
    instructions=(
        "대한민국 법제처 국가법령정보를 검색하고 조문을 읽는 도구입니다. "
        "법령ㆍ행정규칙ㆍ자치법규의 내용을 답할 때는 기억에 의존하지 말고 "
        "반드시 search_law로 먼저 찾은 뒤 get_article이나 get_document로 "
        "실제 본문을 읽고 답하십시오. 절차·제출서류는 legal_research, "
        "중앙부처 질의회신은 search_inquiries, "
        "해석례·판례·헌재·행심은 search_cases를 쓰십시오. 개정 전후는 "
        "compare_old_new, 특정 날짜의 적용 법령은 get_historical_law, "
        "조례 정비 여부는 ordinance_radar, 조문의 파급은 impact_map, "
        "판례 변경·폐기는 cite_check를 쓰십시오. 법이 개정되었을 수 "
        "있고 기억이 틀렸을 수 있습니다."
    ),
)

(
    search_law,
    get_article,
    get_document,
    search_admin_rule,
    get_annexes,
    legal_research,
    search_cases,
    get_case,
    search_inquiries,
    get_inquiry,
    get_historical_law,
    compare_old_new,
    ordinance_radar,
    cite_check,
    impact_map,
) = build_tools(_OC_KEY)
mcp.tool()(search_law)
mcp.tool()(get_article)
mcp.tool()(get_document)
mcp.tool()(search_admin_rule)
mcp.tool()(get_annexes)
mcp.tool()(legal_research)
mcp.tool()(search_cases)
mcp.tool()(get_case)
mcp.tool()(search_inquiries)
mcp.tool()(get_inquiry)
mcp.tool()(get_historical_law)
mcp.tool()(compare_old_new)
mcp.tool()(ordinance_radar)
mcp.tool()(cite_check)
mcp.tool()(impact_map)


if __name__ == "__main__":
    mcp.run()
