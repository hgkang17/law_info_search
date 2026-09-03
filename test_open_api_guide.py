"""
법제처 OPEN API 활용가이드(guideResult.do) 응답 확인용 단독 스크립트

https://open.law.go.kr/LSO/openApi/guideResult.do 가 어떤 식으로 내려오는지,
그리고 그 가이드에 적힌 요청 URL로 실제 API를 부르면 응답이 어떤 모양인지를
한 파일에서 확인하기 위한 테스트 코드다. 프로그램 본체와는 무관하며 아무것도
import 하지 않는다.

확인된 사실(실제 호출로 검증)
  - 가이드 목록 : https://open.law.go.kr/LSO/openApi/guideList.do
    페이지 안의 JS 함수 openApiGuide('htmlName') 호출로 각 API 가이드가 열린다.
    링크에 URL이 안 박혀 있어서 htmlName 값을 정규식으로 긁어와야 한다.
  - 가이드 본문 : guideResult.do?htmlName=<htmlName>
    원래는 POST(form)로 넘기지만 GET 쿼리스트링으로도 동일하게 200/HTML이 온다.
    htmlName 없이 부르면 "현행법령 목록 조회 API" 가이드가 기본으로 나온다.
  - 응답은 HTML(UTF-8). 응답 헤더의 charset 추정이 부실해서 utf-8로 고정 디코딩한다.
    본문은 <div class="guide_area"> 안에 h3(API 이름) / dt(섹션 제목) /
    table.blist.guide(요청변수·출력필드 표) 구조로 들어 있다.
  - 섹션 구성은 API마다 다르다. 표 개수도 다르고 "샘플 URL"은 dt 제목 없이
    표 안에 들어있는 API도 있어서, dt/table을 나온 순서대로 훑는 방식으로 뽑는다.

사용법
    python test_open_api_guide.py                    # 대화형(목록 -> 선택)
    python test_open_api_guide.py list               # 가이드 전체 목록
    python test_open_api_guide.py list 행정규칙       # 제목 키워드로 필터
    python test_open_api_guide.py guide admrulListGuide
    python test_open_api_guide.py raw  admrulListGuide --out guide.html
    python test_open_api_guide.py call admrulListGuide query=주차 display=3
    python test_open_api_guide.py call admrulListGuide --type XML

옵션
    --oc <인증키>   기본값은 환경변수 LAW_API_OC, 없으면 DEFAULT_OC("HGKANG17")
    --type <형식>   JSON(기본) / XML / HTML
    --out <파일>    raw / call 결과를 파일로 저장 (--out auto = 아래 자동 이름)
    --full          응답을 자르지 않고 전부 출력

저장 위치ㆍ이름
    결과 파일은 언제나 스크립트 옆의 '가이드_조회결과' 폴더 안에 만든다
    (절대경로를 직접 준 경우만 그 경로를 그대로 쓴다).
    대화형에서 y 를 치면 응답에서 뽑은 이름(법령명ㆍ행정규칙명ㆍ별표명 등)을
    파일명으로 쓰고, 이름을 못 찾으면 htmlName_시각 으로 떨어진다.

준비물
    pip install requests
"""

import html
import json
import os
import re
import shlex
import sys
import time
import xml.etree.ElementTree as ET

import requests

BASE = "https://open.law.go.kr/LSO/openApi"
GUIDE_LIST_URL = BASE + "/guideList.do"
GUIDE_URL = BASE + "/guideResult.do"

# 법제처는 Referer/User-Agent 없는 요청을 막는 경우가 있어 항상 같이 보낸다.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Python requests",
    "Referer": "https://open.law.go.kr/LSO/openApi/guideList.do",
}

PREVIEW_LIMIT = 4000  # --full 이 없을 때 응답 본문 출력 상한(문자)

# 가이드 목록은 195건이지만 110번(중앙부처 1차 해석 계열)부터는 쓸 일이 없어
# 목록 단계에서 잘라낸다. 전체를 다시 보려면 None 으로 두면 된다.
GUIDE_LIMIT = 109

# 인증키(OC). 법제처에 등록한 계정 아이디이며, --oc 나 환경변수 LAW_API_OC 로
# 덮어쓸 수 있다.
DEFAULT_OC = "HGKANG17"

# 결과 파일을 모아 두는 폴더. 실행 위치와 무관하게 스크립트 옆에 만든다.
RESULT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "가이드_조회결과")

# 응답에서 파일명으로 쓸 '이름'을 찾을 때 볼 필드. 앞쪽이 우선이다.
# (법령 본문은 법령명_한글, 3단비교는 법령명, 행정규칙은 행정규칙명,
#  별표서식은 별표명 식으로 API마다 필드가 다르다.)
NAME_KEYS = (
    "별표명", "별표서식명", "서식명",
    "법령명_한글", "법령명한글", "법령명", "법령명칭",
    "행정규칙명", "자치법규명", "조약명",
    "사건명", "안건명", "제목", "질의요지",
    "관련법령명",
)

# 목록 조회 응답이면 '외 N건'을 붙이려고 총 건수도 같이 본다.
COUNT_KEYS = ("totalCnt", "totalCount")

# type=HTML 응답의 <title>은 늘 이 사이트 이름이라 파일명으로 쓰지 않는다.
SITE_TITLES = ("국가법령통합관리시스템", "국가법령정보")


# ---------------------------------------------------------------- 공통 유틸


def _get_html(url, params=None):
    res = requests.get(url, params=params, headers=HEADERS, timeout=20)
    res.raise_for_status()
    # 응답 헤더의 charset을 신뢰할 수 없어(EUC-KR로 잘못 추정됨) 실제 바이트에 맞춰 고정.
    res.encoding = "utf-8"
    return res.text


def _strip_tags(fragment):
    """HTML 조각을 한 줄 텍스트로. <br>은 ' / '로 살려둔다."""
    text = re.sub(r"(?is)<br\s*/?>", " / ", fragment)
    text = re.sub(r"(?is)<script.*?</script>", "", text)
    text = re.sub(r"(?is)<style.*?</style>", "", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _cut(text, limit):
    if limit is None or len(text) <= limit:
        return text
    return text[:limit] + "\n... (이하 {:,}자 생략, --full 로 전체 출력)".format(len(text) - limit)


# ---------------------------------------------------------- 가이드 목록/본문


def fetch_guide_list():
    """guideList.do 에서 (htmlName, 제목) 목록을 뽑는다.

    GUIDE_LIMIT 이 정수면 앞에서부터 그 개수만 돌려준다(110번 이후 제외).
    """
    page = _get_html(GUIDE_LIST_URL)
    items = []
    seen = set()
    pattern = r"openApiGuide\(\s*['\"]([^'\"]+)['\"]\s*\)[^>]*>(.*?)</a>"
    for match in re.finditer(pattern, page, re.S):
        name = match.group(1).strip()
        title = _strip_tags(match.group(2))
        if name and name not in seen:
            seen.add(name)
            items.append((name, title))
    return items[:GUIDE_LIMIT] if GUIDE_LIMIT else items


def fetch_guide_html(html_name=None):
    """guideResult.do 원본 HTML. html_name 이 None이면 기본 가이드."""
    params = {"htmlName": html_name} if html_name else None
    return _get_html(GUIDE_URL, params)


def _parse_table(table_html):
    """table 조각을 (헤더 리스트, 행 리스트)로."""
    headers = [_strip_tags(c) for c in re.findall(r"(?is)<th[^>]*>(.*?)</th>", table_html)]
    rows = []
    for row_html in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", table_html):
        cells = [_strip_tags(c) for c in re.findall(r"(?is)<td[^>]*>(.*?)</td>", row_html)]
        if cells:
            rows.append(cells)
    return headers, rows


def parse_guide(page):
    """guideResult.do HTML을 구조화한다.

    반환: {"title", "request_url", "sections": [{"title", "tables", "urls"}]}
    섹션 구성이 API마다 달라서 dt(제목)와 표를 나온 순서 그대로 담는다.
    """
    start = page.find('<div class="guide_area"')
    body = page[start:] if start >= 0 else page

    title_match = re.search(r"(?is)<h3[^>]*>(.*?)</h3>", body)
    title = _strip_tags(title_match.group(1)) if title_match else "(제목 없음)"

    request_url = ""
    url_match = re.search(r"요청\s*URL\s*[:：]\s*([^\s<]+)", _strip_tags(body[:4000]))
    if url_match:
        request_url = url_match.group(1)

    sections = []
    current = None
    token = re.compile(
        r"(?is)<dt[^>]*>(.*?)</dt>"
        r"|<table[^>]*class=\"[^\"]*guide[^\"]*\"[^>]*>(.*?)</table>"
    )
    for match in token.finditer(body):
        if match.group(1) is not None:
            text = _strip_tags(match.group(1))
            if not text or text.startswith("- 요청 URL"):
                continue
            current = {"title": text, "tables": [], "urls": []}
            sections.append(current)
        else:
            headers, rows = _parse_table(match.group(2))
            if current is None:
                current = {"title": "(표)", "tables": [], "urls": []}
                sections.append(current)
            current["tables"].append((headers, rows))

    # 샘플 URL은 표가 아니라 <dd> 안 평문으로 들어있어서 따로 긁는다.
    for dd_html in re.findall(r"(?is)<dd[^>]*>(.*?)</dd>", body):
        if "<table" in dd_html.lower():
            continue
        urls = re.findall(r"https?://[^\s<\"']+", html.unescape(dd_html))
        if not urls or not sections:
            continue
        for section in reversed(sections):
            if not section["tables"]:
                section["urls"].extend(urls)
                break
        else:
            sections[-1]["urls"].extend(urls)

    return {"title": title, "request_url": request_url, "sections": sections}


def _print_table(headers, rows):
    if not rows:
        return
    width = max(len(headers), max(len(r) for r in rows))
    norm = [(headers + [""] * width)[:width]] if headers else []
    norm += [(r + [""] * width)[:width] for r in rows]
    widths = [min(60, max(len(r[i]) for r in norm)) for i in range(width)]

    def line(cells):
        # 정렬용으로만 폭을 맞추고, 샘플 URL처럼 긴 값은 잘라내지 않는다.
        return " | ".join(c.ljust(widths[i]) for i, c in enumerate(cells)).rstrip()

    if headers:
        print("    " + line(norm[0]))
        print("    " + "-+-".join("-" * w for w in widths))
        norm = norm[1:]
    for row in norm:
        print("    " + line(row))


def print_guide(guide, html_name):
    print("=" * 78)
    print("[가이드] " + guide["title"])
    print("  htmlName    : " + (html_name or "(기본값 - 현행법령 목록 조회)"))
    print("  가이드 주소 : {}?htmlName={}".format(GUIDE_URL, html_name or ""))
    if guide["request_url"]:
        print("  요청 URL    : " + guide["request_url"])
    print("=" * 78)
    for section in guide["sections"]:
        print("\n[{}]".format(section["title"]))
        for headers, rows in section["tables"]:
            _print_table(headers, rows)
            print()
        for url in section["urls"]:
            print("    " + url)


# ------------------------------------------------------------- 실제 API 호출


def _summarize_json(data, indent=0, depth=0, max_depth=4):
    pad = "  " * indent
    if depth >= max_depth:
        print(pad + "...")
        return
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, dict):
                print("{}{}: dict({}키)".format(pad, key, len(value)))
                _summarize_json(value, indent + 1, depth + 1, max_depth)
            elif isinstance(value, list):
                print("{}{}: list({}건)".format(pad, key, len(value)))
                if value:
                    _summarize_json(value[0], indent + 1, depth + 1, max_depth)
            else:
                shown = str(value).replace("\n", " ")
                print("{}{}: {}".format(pad, key, shown[:70]))
    elif isinstance(data, list):
        print("{}list({}건)".format(pad, len(data)))
        if data:
            _summarize_json(data[0], indent + 1, depth + 1, max_depth)
    else:
        print(pad + str(data)[:70])


def _summarize_xml(text):
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        print("  XML 파싱 실패: {}".format(exc))
        return

    def walk(node, indent=0, depth=0):
        if depth > 3:
            return
        pad = "  " * indent
        value = (node.text or "").strip().replace("\n", " ")
        print("{}<{}>{}".format(pad, node.tag, (" " + value[:60]) if value else ""))
        seen = {}
        for child in node:
            seen[child.tag] = seen.get(child.tag, 0) + 1
            if seen[child.tag] <= 1:  # 같은 태그 반복은 첫 건만 펼친다
                walk(child, indent + 1, depth + 1)
        for tag, count in seen.items():
            if count > 1:
                print("{}  <{}> x {}건".format(pad, tag, count))

    walk(root)


def ask(prompt):
    """영문ㆍ숫자를 넣는 입력. ESC 를 누르면 None(취소)을 돌려준다.

    한 글자씩 직접 읽어야 ESC 를 잡을 수 있는데, 그렇게 하면 한글 IME 조합이
    화면에 안 보인다. 그래서 한글을 넣는 '추가 파라미터' 입력에는 쓰지 않는다.
    콘솔이 아니거나(파이프 입력) msvcrt 가 없는 환경이면 그냥 input() 을 쓴다.
    """
    try:
        import msvcrt
    except ImportError:
        msvcrt = None
    if msvcrt is None or not sys.stdin.isatty():
        return input(prompt)

    sys.stdout.write(prompt)
    sys.stdout.flush()
    typed = []
    while True:
        char = msvcrt.getwch()
        if char == "\x1b":                       # ESC
            sys.stdout.write("  (취소)\n")
            sys.stdout.flush()
            return None
        if char in ("\r", "\n"):
            sys.stdout.write("\n")
            sys.stdout.flush()
            return "".join(typed)
        if char == "\x03":                       # Ctrl+C 는 원래 동작대로
            raise KeyboardInterrupt
        if char in ("\b", "\x7f"):              # 백스페이스
            if typed:
                typed.pop()
                sys.stdout.write("\b \b")
                sys.stdout.flush()
            continue
        if char in ("\x00", "\xe0"):            # 방향키ㆍ기능키는 두 글자로 온다
            msvcrt.getwch()
            continue
        typed.append(char)
        sys.stdout.write(char)
        sys.stdout.flush()


def _candidates(data, limit=10):
    """목록 조회 응답에서 (제목, 일련번호, 항목)을 뽑는다.

    target마다 키 이름이 달라(행정규칙명/법령명한글/제목…) '명'ㆍ'제목'으로 끝나는
    키와 '일련번호'로 끝나는 키를 짝지어 찾는다. 소관부처명처럼 문서 이름이 아닌
    것은 걸러낸다.
    """
    skip = ("부처", "기관", "담당", "부서", "자명", "법원")
    rows = []

    def walk(node):
        if isinstance(node, dict):
            keys = list(node)
            title = next((k for k in keys
                          if (k.endswith("명") or k.endswith("제목"))
                          and not any(word in k for word in skip)), "")
            seq = next((k for k in keys if k.endswith("일련번호")), "")
            if title and seq:
                rows.append((str(node[title]), str(node[seq]), node))
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return rows[:limit]


def search_by_name(request_url, name, oc, limit=10):
    """본문 조회 API는 정확한 이름만 받으므로, 같은 target의 목록 조회로 후보를 찾는다."""
    base, _, query = request_url.partition("?")
    if "lawService.do" not in base:
        return []
    params = {}
    for pair in query.split("&"):
        if "=" in pair:
            key, value = pair.split("=", 1)
            params[key] = value
    params.update({"OC": oc, "type": "JSON", "query": name, "display": str(limit)})
    url = base.replace("http://", "https://").replace("lawService.do", "lawSearch.do")
    try:
        res = requests.get(url, params=params, headers=HEADERS, timeout=20)
        res.encoding = "utf-8"
        return _candidates(res.json(), limit)
    except Exception:                     # 목록 조회가 없거나 실패하면 그냥 넘어간다
        return []


def resolve_by_name(request_url, extra, oc):
    """이름으로 본문을 찾을 때 후보를 먼저 보여 주고 고르게 한다.

    LM 은 정확한 명칭만 받아서 '조달수수료'처럼 일부만 넣거나 '조문수수료'처럼
    오타가 나면 엉뚱한 옛 규칙이 나오거나 아무것도 안 나온다. 목록 조회로 후보를
    뽑아 ID(일련번호)로 바꿔 준다.
    """
    name = extra.get("LM", "")
    rows = search_by_name(request_url, name, oc)
    if not rows:
        print('  ("{}" 로 찾은 후보가 없습니다. 이름 그대로 불러 봅니다)'.format(name))
        return extra
    if len(rows) == 1 and rows[0][0] == name:
        return extra                      # 이름이 정확히 맞으면 그대로 LM 으로 부른다

    print()
    print('"{}" 로 찾은 후보 {}건'.format(name, len(rows)))
    for index, (title, seq, node) in enumerate(rows, 1):
        extras = [str(node[k]) for k in ("시행일자", "현행연혁구분") if k in node]
        note = ("  [" + " ".join(extras) + "]") if extras else ""
        print("  {:>2}. {}{}  (일련번호 {})".format(index, title, note, seq))
    token = ask("번호 선택 (엔터=1번, s=이름 그대로 조회, ESC=취소): ")
    if token is None:
        return None
    token = token.strip()
    if token.lower() == "s":
        return extra

    index = int(token) - 1 if token.isdigit() and 0 < int(token) <= len(rows) else 0
    title, seq, _node = rows[index]
    print("  -> {} (ID={})".format(title, seq))
    extra = dict(extra)
    extra.pop("LM", None)
    extra["ID"] = seq
    return extra


EXT_BY_TYPE = {"JSON": "json", "XML": "xml", "HTML": "html"}


def _collect_fields(node, found, wanted, depth=0):
    """JSON 트리를 훑어 wanted 에 든 필드의 첫 값을 모은다."""
    if depth > 12:
        return
    if isinstance(node, dict):
        for key, value in node.items():
            if key in wanted and not isinstance(value, (dict, list)):
                text = str(value).strip()
                if text:
                    found.setdefault(key, text)
            elif isinstance(value, (dict, list)):
                _collect_fields(value, found, wanted, depth + 1)
    elif isinstance(node, list):
        # 목록 응답은 첫 몇 건만 봐도 이름을 찾기에 충분하다.
        for item in node[:5]:
            _collect_fields(item, found, wanted, depth + 1)


def guess_result_name(text, out_type):
    """응답에서 법령명ㆍ행정규칙명ㆍ별표명 같은 '이름'을 뽑는다. 못 찾으면 None."""
    if not text:
        return None
    stripped = text.lstrip()
    wanted = set(NAME_KEYS) | set(COUNT_KEYS)
    found = {}

    if stripped.startswith(("{", "[")):
        try:
            _collect_fields(json.loads(text), found, wanted)
        except ValueError:
            return None
    elif stripped.startswith("<?xml") or (out_type or "").upper() == "XML":
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return None
        for node in root.iter():
            if node.tag in wanted and (node.text or "").strip():
                found.setdefault(node.tag, node.text.strip())
    else:
        # type=HTML 응답은 iframe 껍데기라 <title> 이 사이트 이름으로만 온다.
        # 그런 제목은 파일명으로 쓸 수 없으니 버리고 폴백 이름을 쓰게 둔다.
        match = re.search(r"(?is)<title[^>]*>(.*?)</title>", text)
        title = _strip_tags(match.group(1)) if match else ""
        if not title or any(word in title for word in SITE_TITLES):
            return None
        return title

    name = next((found[key] for key in NAME_KEYS if found.get(key)), None)
    if not name:
        return None
    for key in COUNT_KEYS:
        if str(found.get(key, "")).isdigit() and int(found[key]) > 1:
            return "{} 외 {}건".format(name, int(found[key]) - 1)
    return name


def _clean_filename(name):
    """파일명에 못 쓰는 글자를 걷어내고 길이를 자른다."""
    name = re.sub(r'[\/:*?"<>|]', " ", name or "")
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:80]


def _result_path(path):
    """결과 파일은 언제나 '가이드_조회결과' 폴더 안에 만든다.

    절대경로를 직접 준 경우만 그 경로를 존중하고, 그 밖에는 파일명만 떼어 쓴다.
    """
    path = os.path.expanduser(path.strip().strip('"'))
    if os.path.isabs(path):
        return path
    return os.path.join(RESULT_DIR, os.path.basename(path))


def _unique_path(path):
    """같은 이름이 있으면 ' (2)', ' (3)' 을 붙여 덮어쓰지 않는다."""
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    for number in range(2, 1000):
        candidate = "{} ({}){}".format(stem, number, ext)
        if not os.path.exists(candidate):
            return candidate
    return path


def save_text(text, path, keep_existing=False):
    """응답을 통째로(화면과 달리 자르지 않고) 파일에 쓴다."""
    path = _result_path(path)
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    if keep_existing:
        path = _unique_path(path)
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(text)
    print("저장: {} ({:,}자)".format(os.path.abspath(path), len(text)))


def auto_filename(text, name, out_type):
    """응답에서 뽑은 이름으로 파일명을 만든다. 못 뽑으면 htmlName_시각."""
    ext = EXT_BY_TYPE.get((out_type or "").upper(), "txt")
    guessed = _clean_filename(guess_result_name(text, out_type))
    if guessed:
        return "{}.{}".format(guessed, ext)
    return "{}_{}.{}".format(name or "response", time.strftime("%Y%m%d_%H%M%S"), ext)


def offer_save(text, name, out_type):
    """화면에는 앞부분만 나오므로, 전체를 파일로 받아 갈지 물어본다."""
    if not text:
        return
    suggested = auto_filename(text, name, out_type)
    print("저장 폴더: {}".format(RESULT_DIR))
    answer = ask("파일로 저장 [{}] (엔터=안 함, y=이 이름, 파일명 직접 입력, ESC=취소): "
                 .format(suggested))
    if answer is None:
        return
    answer = answer.strip()
    if not answer:
        return
    if answer.lower() in ("y", "yes"):
        answer = suggested
    elif not os.path.splitext(answer)[1]:
        answer = "{}.{}".format(answer, EXT_BY_TYPE.get((out_type or "").upper(), "txt"))
    try:
        save_text(text, answer, keep_existing=True)
    except OSError as exc:
        print("저장 실패: {}".format(exc))


def _missing_required(items, extra):
    """OC/target/type 은 자동으로 채워지니 빼고, '(필수)'인데 안 채운 변수만 고른다.

    ID/MST 처럼 '둘 중 하나만 있으면 되는' 변수는 가이드 표에도 '필수' 표시가
    안 붙어 있어서(서로 다른 줄에 그 조건만 설명으로 적힘) 여기 안 걸린다.
    """
    return [(key, desc) for key, value, desc in items
            if "필수" in value and key not in ("OC", "target", "type")
            and key not in extra]


def confirm_required(items, extra):
    """필수 변수가 빠졌으면 알려주고, 채우거나 그대로 부를지 고르게 한다."""
    while True:
        missing = _missing_required(items, extra)
        if not missing:
            return extra
        print()
        print("!! 필수 파라미터가 빠졌습니다:")
        for key, desc in missing:
            print("   {} — {}".format(key, re.sub(r"\s*/\s*", " ", desc).strip()))
        answer = ask("값 입력(key=value), 엔터=그대로 호출, ESC=취소: ")
        if answer is None:
            return None
        answer = answer.strip()
        if not answer:
            return extra
        extra = dict(extra)
        extra.update(_split_pairs(answer, [key for key, _value, _desc in items]))


def call_api(request_url, extra, oc, out_type, out_path=None, full=False):
    """가이드에 적힌 요청 URL을 그대로 호출해서 응답 모양을 보여준다."""
    if not request_url:
        print("요청 URL을 가이드에서 찾지 못했습니다.")
        return

    # 가이드의 요청 URL에는 target=... 이 이미 붙어 있다. 그걸 살리고 나머지를 합친다.
    base, _, query = request_url.partition("?")
    base = base.replace("http://", "https://")
    params = {}
    for pair in query.split("&"):
        if "=" in pair:
            key, value = pair.split("=", 1)
            params[key] = value
    params["OC"] = oc
    params["type"] = out_type
    params.update(extra)

    print("=" * 78)
    print("[실제 호출]")
    print("  URL    : " + base)
    print("  params : {}".format(params))
    try:
        res = requests.get(base, params=params, headers=HEADERS, timeout=20)
    except requests.RequestException as exc:
        print("  요청 실패: {}".format(exc))
        return
    print("  최종 URL     : " + res.url)
    print("  status       : {}".format(res.status_code))
    print("  Content-Type : {}".format(res.headers.get("Content-Type")))
    print("  응답 크기    : {:,} bytes".format(len(res.content)))
    print("=" * 78)

    text = res.text
    ctype = (res.headers.get("Content-Type") or "").lower()
    upper = out_type.upper()

    if upper == "JSON" or "json" in ctype:
        try:
            data = res.json()
        except ValueError:
            print("!! type=JSON 으로 요청했지만 JSON이 아닌 응답이 왔습니다"
                  " (인증키 오류이거나 해당 API가 JSON 미지원일 수 있음).")
            print(_cut(text, None if full else PREVIEW_LIMIT))
        else:
            print("\n[응답 구조 요약]")
            _summarize_json(data)
            print("\n[응답 본문]")
            pretty = json.dumps(data, ensure_ascii=False, indent=2)
            print(_cut(pretty, None if full else PREVIEW_LIMIT))
            text = pretty
    elif upper == "XML" or "xml" in ctype:
        print("\n[응답 구조 요약]")
        _summarize_xml(text)
        print("\n[응답 본문]")
        print(_cut(text, None if full else PREVIEW_LIMIT))
    else:
        print("\n[응답 본문(HTML)]")
        print(_cut(text, None if full else PREVIEW_LIMIT))

    if out_path:
        # --out auto 면 응답에서 뽑은 이름(법령명ㆍ별표명 등)으로 저장한다.
        if out_path.strip().lower() == "auto":
            out_path = auto_filename(text, None, out_type)
        save_text(text, out_path)
    return text


# ----------------------------------------------------------------- CLI 처리


def _request_params(guide):
    """가이드의 요청변수 표에서 (이름, 값, 설명)을 뽑는다.

    이름은 키 생략 입력을 보정할 때, 값ㆍ설명은 입력 안내를 띄울 때 쓴다.
    """
    items = []
    for section in guide["sections"]:
        if "요청" not in section["title"]:
            continue
        for _headers, rows in section["tables"]:
            for row in rows:
                key = row[0].split()[0] if row and row[0] else ""
                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key or ""):
                    items.append((key, row[1] if len(row) > 1 else "",
                                  row[2] if len(row) > 2 else ""))
    return items


def _guess_key(value, names):
    """키 없이 값만 넣었을 때 어느 요청변수에 넣을지 고른다.

    숫자면 일련번호(ID)ㆍ행정규칙ID(LID) 쪽, 글자면 이름(LM)ㆍ검색어(query) 쪽을
    가이드에 실제로 있는 변수 중에서 순서대로 찾는다.
    """
    order = ["ID", "MST", "LID", "query"] if value.isdigit() else ["LM", "query"]
    for key in order:
        if key in names:
            return key
    return ""


DESC_LIMIT = 66   # 요청변수 설명을 한 줄로 줄일 때의 상한(문자)


def _extra_prompt(items):
    """지금 보고 있는 API의 요청변수를 설명과 함께 보여 주는 입력 안내 문구.

    API마다 쓸 수 있는 변수가 달라서(목록 조회는 query/display, 본문 조회는
    ID/MST/LM) 고정된 예시를 띄우면 없는 변수를 넣게 된다. 설명은 가이드의
    요청변수 표에 적힌 것을 그대로 한 줄로 줄여 쓴다.
    """
    usable = [item for item in items if item[0] not in ("OC", "target", "type")]
    if not usable:
        return "추가 파라미터 (이 API에는 없음, 엔터): "

    width = max(len(key) for key, _value, _desc in usable)
    lines = ["추가 파라미터 — 쓸 수 있는 변수"]
    for key, value, desc in usable:
        text = re.sub(r"\s*/\s*", " / ", desc).strip()
        if len(text) > DESC_LIMIT:
            text = text[:DESC_LIMIT] + "…"
        mark = "*" if "필수" in value else " "
        lines.append("   {}{}  {}".format(mark, key.ljust(width), text))

    names = [key for key, _value, _desc in usable]
    hints = ["* 필수"] if any("필수" in value for _key, value, _desc in usable) else []
    for label, sample in (("글자", "가"), ("숫자", "1")):
        key = _guess_key(sample, names)
        if key:
            hints.append("{}만 넣으면 {}".format(label, key))
    hints.append("q=취소")
    lines.append("  (key=value 형식" + (", " + " / ".join(hints) if hints else "") + ")")
    return "\n".join(lines) + "\n> "


def _split_pairs(raw, names=()):
    """'query=주차 display=3' 같은 한 줄을 {키: 값}으로.

    LM 처럼 값에 공백이 들어가는 변수가 있어 따옴표를 인정한다
    (LM="조달수수료 고시"). 따옴표를 닫지 않았으면 예전처럼 공백으로만 나눈다.
    key= 를 빼고 값만 넣는 실수가 잦아서, 남은 조각은 하나로 이어 붙여
    가이드의 요청변수 중 알맞은 곳에 넣어 준다.
    """
    try:
        tokens = shlex.split(raw)
    except ValueError:
        tokens = [token.strip("\"'") for token in raw.split()]

    pairs, loose = {}, []
    for token in tokens:
        if "=" in token:
            key, value = token.split("=", 1)
            pairs[key] = value
        else:
            loose.append(token)

    if loose:
        value = " ".join(loose)
        key = _guess_key(value, names)
        if key and key not in pairs:
            pairs[key] = value
            print('  (키가 없어서 {}="{}" 로 넣었습니다)'.format(key, value))
        else:
            print('  ("{}" 은 key=value 형태가 아니라 무시했습니다)'.format(value))
    return pairs


def _parse_argv(argv):
    """[명령, 인자], --옵션, key=value 추가 파라미터로 나눈다."""
    positional, options, extra = [], {}, {}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token.startswith("--"):
            key = token[2:]
            if key == "full":
                options["full"] = True
            else:
                index += 1
                options[key] = argv[index] if index < len(argv) else ""
        elif "=" in token and not token.startswith("-"):
            key, value = token.split("=", 1)
            extra[key] = value
        else:
            positional.append(token)
        index += 1
    return positional, options, extra


def _print_list(items, keyword=""):
    for number, (name, title) in enumerate(items, 1):
        if keyword and keyword not in title and keyword not in name:
            continue
        print("{:3d}. {}".format(number, title))
        print("     htmlName = " + name)


def _resolve(items, token):
    """번호 또는 htmlName 으로 항목을 찾는다."""
    if token.isdigit():
        index = int(token) - 1
        if 0 <= index < len(items):
            return items[index][0]
        return None
    return token


def interactive():
    items = fetch_guide_list()
    print("가이드 {}건\n".format(len(items)))
    _print_list(items)
    print()
    token = ask("번호 또는 htmlName (엔터=기본 가이드, ESC=취소): ")
    if token is None:
        return
    token = token.strip()
    html_name = None  # 엔터만 치면 기본 가이드(현행법령 목록 조회)
    if token:
        html_name = _resolve(items, token)
        if html_name is None:
            print("목록에서 찾지 못했습니다.")
            return
    guide = parse_guide(fetch_guide_html(html_name))
    print()
    print_guide(guide, html_name)

    if not guide["request_url"]:
        return
    print()
    oc = os.environ.get("LAW_API_OC", "").strip() or DEFAULT_OC
    out_type = ask("type (기본 JSON, ESC=취소): ")
    if out_type is None:
        return
    out_type = out_type.strip().upper() or "JSON"

    param_items = _request_params(guide)
    # 여기는 한글(법령명ㆍ검색어)을 넣는 자리라 ESC 대신 q 로 취소한다.
    raw_extra = input(_extra_prompt(param_items)).strip()
    if raw_extra.lower() in ("q", "quit"):
        print("취소했습니다.")
        return
    extra = _split_pairs(raw_extra, [key for key, _value, _desc in param_items])
    if extra.get("LM") and "ID" not in extra:
        extra = resolve_by_name(guide["request_url"], extra, oc)
        if extra is None:
            return
    extra = confirm_required(param_items, extra)
    if extra is None:
        return
    print()
    text = call_api(guide["request_url"], extra, oc, out_type)
    print()
    offer_save(text, html_name or "guide", out_type)


def main(argv):
    positional, options, extra = _parse_argv(argv)
    command = positional[0] if positional else ""
    target = positional[1] if len(positional) > 1 else ""
    oc = options.get("oc") or os.environ.get("LAW_API_OC", "").strip() or DEFAULT_OC
    out_type = (options.get("type") or "JSON").upper()
    out_path = options.get("out")
    full = bool(options.get("full"))

    if not command:
        interactive()
        return 0

    if command == "list":
        items = fetch_guide_list()
        print("가이드 {}건 (guideList.do)\n".format(len(items)))
        _print_list(items, target)
        return 0

    if command in ("guide", "raw", "call"):
        items = fetch_guide_list() if target.isdigit() else []
        html_name = _resolve(items, target) if target else None
        if target and html_name is None:
            print("목록에서 {} 번을 찾지 못했습니다.".format(target))
            return 1

        page = fetch_guide_html(html_name)

        if command == "raw":
            if out_path:
                save_text(page, out_path)
            else:
                print(_cut(page, None if full else PREVIEW_LIMIT))
            return 0

        guide = parse_guide(page)
        print_guide(guide, html_name)

        if command == "call":
            print()
            for key, desc in _missing_required(_request_params(guide), extra):
                print("!! 필수 파라미터가 빠졌습니다: {} — {}".format(
                    key, re.sub(r"\s*/\s*", " ", desc).strip()))
            call_api(guide["request_url"], extra, oc, out_type, out_path, full)
        return 0

    print(__doc__)
    return 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print("\n중단")
    except requests.RequestException as error:
        print("요청 실패: {}".format(error))
        sys.exit(1)
