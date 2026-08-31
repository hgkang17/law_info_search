# Qt UI 공용 디자인 체계

이 문서는 화면별 복제를 막기 위한 최소 공용 계약을 기록한다. 새 요소는 같은
의도로 세 화면 이상에서 반복될 때 공용화하며, 화면 하나에만 필요한 동작은 해당
탭에 둔다.

제품의 North Star, 반응형 규칙, 접근성 원칙과 대표 컴포넌트는 루트의
`DESIGN.md`가 상위 계약이다. 실제 작업대 색상 값은 `ui/theme.py`의
`WORKBENCH_COLORS`를 사용한다.

## 역할 구분

- `ui/theme.py`: 색상 팔레트, 본문 글자색 처리, 글꼴 등록처럼 시각 표현을 공유한다.
- `ui/widgets.py`: 검색 결과 머리글, 본문 머리글 조절부처럼 구조와 상호작용 규격을
  공유한다.
- Qt `objectName`은 `ui/main_window.py`의 QSS와 연결되는 공개 스타일 계약이다.
  공용 위젯을 수정할 때 이름을 임의로 바꾸지 않는다.

## 본문 머리글 조절부

`build_detail_header_controls(font_size)`는 법령검색, 키워드검색, 자료검색의
`본문 / 글자 / 크기 조절` 묶음을 만든다.

- 글자 크기 범위: 7.0–18.0pt
- 증감 단위: 0.5pt
- 라벨 폭: 24px
- 입력 폭: 80px
- 반환값: `DetailHeaderControls(title, font_label, font_spin)`

더블클릭 전환과 글자 크기 저장 신호는 화면마다 수명주기와 저장 키가 다르므로 각
탭에서 연결한다. 저장값의 범위 제한은 `clamp_detail_font_size`, 사용자가 바꾼
값의 0.5pt 단위 정규화는 `normalize_detail_font_size`를 사용한다.
