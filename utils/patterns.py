"""법령·행정규칙 원문에서 조문 번호와 인용을 찾아내는 정규식 모음.

원문 구조를 읽는 규칙이 한곳에 모여 있어야 조문 번호 체계가 바뀌었을 때
고칠 자리를 빨리 찾을 수 있다.
"""

from __future__ import annotations

import re


CIRCLED_NUMBER_MARKERS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"

# 수립지침 세항 표지. ①(항)과 달리 ㉮㉯는 목(가·나)에 해당하는 동그라미 한글이다.
CIRCLED_HANGUL_ITEM_MARKERS = "㉠㉡㉢㉣㉤㉥㉦㉧㉨㉩㉪㉫㉬㉭㉮㉯㉰㉱㉲㉳㉴㉵㉶㉷㉸㉹㉺㉻"


BULLET_PATTERN = re.compile(
    r"^\s*(■|□|○|◦|●|•|◎|◇|◆|▪|▫|[OoΟο]|ㅇ|\d+\)|-)\s+(.+)$"
)


LAW_HEADING_PATTERN = re.compile(r"^(제\d+(?:편|장|절|관))\s*(.*)$")


LAW_ARTICLE_PATTERN = re.compile(
    r"^(제\d+조(?:의\d+)?(?:\([^)]*\))?)\s*(.*)$"
)


LAW_PARAGRAPH_PATTERN = re.compile(r"^([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])\s*(.*)$")


CIRCLED_HANGUL_ITEM_PATTERN = re.compile(
    rf"^([{CIRCLED_HANGUL_ITEM_MARKERS}])\s*(.*)$"
)


LAW_SUBPARAGRAPH_PATTERN = re.compile(r"^(\d+(?:의\d+)*\.)\s*(.*)$")


LAW_ITEM_PATTERN = re.compile(r"^([가나다라마바사아자차카타파하]\.)\s*(.*)$")


# 수립지침 원문에서 한 줄에 이어진 독립 목 표지. 앞뒤가 공백으로
# 구분된 완전한 토큰만 허용하므로 ``계획한다.``의 ``다.``는 잡지 않는다.
ADMIN_RULE_INLINE_KOREAN_ITEM_PATTERN = re.compile(
    r"[ \t]+([가나다라마바사아자차카타파하]\.)[ \t]+(?=\S)"
)


# 원문 API가 ``...사용할 수 있`` / ``다.)``처럼 문장 한가운데서 줄을
# 끊어 보내면 문장 끝 ``다.``가 목 표지 자리에 서서 새 목으로 그려진다.
# 표지 뒤에 닫는 괄호나 따옴표만 남는 줄은 목이 될 수 없으므로 앞
# 문장의 꼬리로 본다. 뒤에 실제 내용이 있는 ``다. 임의수립주체...``는
# 줄 끝 조건에 걸리지 않아 그대로 목으로 남는다.
ADMIN_RULE_SENTENCE_TAIL_ITEM_PATTERN = re.compile(
    r"^[가나다라마바사아자차카타파하]\."
    r"\s*[)\]}」』”’\"']+\s*$"
)


LAW_SUBITEM_PATTERN = re.compile(
    r"^(\(\d+\)|\d+\)|[가나다라마바사아자차카타파하]\))\s*(.*)$"
)


_INLINE_PAREN_ITEM_PATTERN = re.compile(r"\((\d{1,2})\)")


_CIRCLED_REFERENCE_TAIL_PATTERN = re.compile(
    # "②항 또는 ③항의 집단취락"처럼 번호에 항·호·목이 바로 붙으면
    # 새 항목이 아니라 다른 항목을 가리키는 참조번호다.
    # "② 항만시설"처럼 사이에 공백이 있으면 본문이므로 제외한다.
    r"^(?:[항호목](?=[의을를과와이가에도만은는,\s]|$)"
    r"|\s*(?:[ㆍ·,;]|및(?=\s|$)|의(?=\s|$)|에서(?=\s|$)|에(?=\s|$)|부터|까지))"
)


_MARKER_ONLY_LINE_PATTERN = re.compile(
    rf"^(?:\d+(?:-\d+)+\.|\(\d{{1,2}}\)|\([가-하]\)"
    rf"|[{CIRCLED_NUMBER_MARKERS}]|\d{{1,2}}\.)\s*$"
)


ADMIN_RULE_PAREN_REFERENCE_LINE_PATTERN = re.compile(
    r"^\((?:\d+|[가나다라마바사아자차카타파하])\)"
    # API에 따라 ``(1)에서``와 ``(1) 에서``가 모두 내려온다.
    # 번호 뒤가 조사인 경우에만 참조로 판단하므로 일반 ``(1) 내용``
    # 목록과는 구별된다.
    # ``(1)부터(3)까지``도 새 (1) 항목이 아니라 범위 참조다.
    r"\s*(?:부터|까지|내지|에서|에|의|항|호|목|을|를|은|는|이|가)"
    # ``(4)까지의``, ``(3)까지에``처럼 범위 표현 뒤 조사가 바로
    # 이어지는 형태도 같은 참조 문장으로 본다.
    r"(?=\s|\(|$|의|에|을|를|은|는|이|가)"
)


# ``이 지침 2-2-5\n(2) 단서에 따라``처럼 지침 번호 뒤의 항 번호가
# API에서 다음 줄로 떨어진 내부 참조. 일반 목록과 구분하기 위해 항 번호
# 뒤에 참조 위치를 뜻하는 명사가 오는 경우만 대상으로 삼는다.
ADMIN_RULE_CLAUSE_SUBREFERENCE_LINE_PATTERN = re.compile(
    r"^\((?:\d+|[가나다라마바사아자차카타파하])\)\s*"
    r"(?:본문|단서|전단|후단)(?=\s|에|의|을|를|은|는|이|가|$)"
)


# ``(1) 도시ㆍ군관리계획수립지침`` 다음의
# ``3-2-8-1. (3)에 해당하는 지역``은 새 조항이 아니라 다른 지침
# 조항을 인용해 앞 항목을 설명하는 문장이다.
ADMIN_RULE_NUMBERED_CLAUSE_REFERENCE_PATTERN = re.compile(
    r"^\d+(?:-\d+)+\.\s*"
    r"\((?:\d+|[가나다라마바사아자차카타파하])\)\s*"
    r"(?:에|의|에서|부터|까지)(?=\s|$)"
)


_CIRCLED_REFERENCE_LINE_PATTERN = re.compile(
    rf"^[{CIRCLED_NUMBER_MARKERS}{CIRCLED_HANGUL_ITEM_MARKERS}]\s*"
    r"(?:[ㆍ·,;]|및(?=\s|$)|의(?=\s|$)|에서(?=\s|$)|에(?=\s|$)|부터|까지)"
)


_SENTENCE_END_SUFFIXES = ("다", "다.", "경우", "함", "음", "것", "요건", ")")


ADMIN_RULE_CLAUSE_PATTERN = re.compile(
    r"^(\d+(?:-\d+)+\.)\s*(.*)$"
)


ADMIN_RULE_NUMBERED_ITEM_PATTERN = re.compile(r"^(\d{1,2}\.)\s+(.*)$")


ADMIN_RULE_PAREN_ITEM_PATTERN = re.compile(
    r"^(\((?:\d+|[가나다라마바사아자차카타파하])\))\s*(.*)$"
)


_FRAGMENT_MARKER_PATTERNS = (
    LAW_PARAGRAPH_PATTERN,
    ADMIN_RULE_PAREN_ITEM_PATTERN,
    ADMIN_RULE_NUMBERED_ITEM_PATTERN,
    ADMIN_RULE_CLAUSE_PATTERN,
)


_FRAGMENT_LEADING_PARTICLES = (
    "부터",
    "까지",
    "에서",
    "에게",
    "으로",
    "의",
    "는",
    "은",
    "이",
    "가",
    "을",
    "를",
    "과",
    "와",
    "도",
    "만",
    "로",
)


_BARE_CLAUSE_REFERENCE_PATTERN = re.compile(
    r"^(\d+(?:-\d+)+\.)"
    r"(의|는|은|이|가|을|를|과|와|도|만|로|부터|까지|에서|에게|으로)"
)


LAW_REFERENCE_PATTERN = re.compile(
    r"「(?P<law>[^」\n]{1,80}?(?:시행규칙|시행령|법률|법|규칙|조례|규정))」"
    r"(?P<law_detail>\s*(?P<law_article>제\d+조(?:의\d+)?)"
    r"(?:제\d+항(?:의\d+)?)?(?:제\d+호(?:의\d+)?)?(?:[가-하]목)?)?"
    # 시행령·시행규칙 본문의 "법 제62조제1항", "영 제55조제3항", "같은 법 제11조"처럼
    # 괄호 없이 상·하위 법령을 가리키는 인용. 앞 글자가 한글이면(예: 건축"법")
    # 법령명의 일부이므로 제외한다.
    r"|(?<![가-힣])(?P<sibling_scope>같은\s*)?"
    # ``대통령령``은 ``부령``으로 끝나지 않아 부령 갈래에 걸리지 않으므로
    # 따로 적는다. 빠뜨리면 "대통령령 제5조"의 조문만 잡혀 현재 법령의
    # 조문을 가리키는 인용으로 잘못 읽힌다.
    r"(?P<sibling_unit>대통령령|[가-힣]{2,20}부령|총리령|부령|법률|법|시행령|영|시행규칙|규칙)\s*"
    r"(?P<sibling_article>제\d+조(?:의\d+)?"
    r"(?:제\d+항(?:의\d+)?)?(?:제\d+호(?:의\d+)?)?(?:[가-하]목)?)"
    r"|(?P<current_article>(?:제\d+조(?:의\d+)?"
    r"(?:제\d+항(?:의\d+)?)?(?:제\d+호(?:의\d+)?)?(?:[가-하]목)?"
    r"|제\d+항(?:의\d+)?(?:제\d+호(?:의\d+)?)?(?:[가-하]목)?))"
)


LAW_UNIT_REFERENCE_PATTERN = re.compile(
    r"(?=제\d+(?:조|항|호)|[가-하]목)"
    r"(?:제(?P<jo>\d+)조(?:의(?P<jo_branch>\d+))?)?"
    r"(?:제(?P<hang>\d+)항(?:의(?P<hang_branch>\d+))?)?"
    r"(?:제(?P<ho>\d+)호(?:의(?P<ho_branch>\d+))?)?"
    r"(?:(?P<mok>[가-하])목)?"
)


_ADJACENT_GAP_PATTERN = re.compile(r'^\s*(?:\([^()]*\)|「[^」]*」)?\s*$')


_ENUMERATION_GAP_PATTERN = re.compile(
    r'^(?:부터|까지|내지|및|또는|이나|과|와'
    # 조 없이 항·호만 열거한 조각(제5항, 제3호의2)도 열거의 일부로 본다.
    r'|제\d+[항호목](?:의\d+)?'
    r'|[,、·ㆍ\s])*$'
)


_LAW_ALIAS_PATTERN = re.compile(
    r'^\s*\(\s*이하\s*["\'“”‘’]?(?P<alias>[^"\'“”‘’()]{1,12}?)'
    r'["\'“”‘’]?\s*(?:이|라|이라)?\s*(?:한다|합니다)\s*\)'
)
