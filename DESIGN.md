---
name: 국가법령정보 통합검색 UI
description: 회색 작업공간 위에서 법률 근거를 빠르게 찾고 읽고 비교하는 문서 작업대
colors:
  canvas: "#f4f4f3"
  paper: "#ffffff"
  ink: "#242529"
  muted-ink: "#62666f"
  border: "#dedfdf"
  current: "#2563eb"
  focus: "#3b82f6"
  primary-action: "#202124"
  hover-gray: "#eeeeed"
  header-surface: "#fafafa"
  rail-surface: "#f7f7f6"
  selection-surface: "#edf3ff"
  selection-ink: "#174ea6"
typography:
  title:
    fontFamily: "Pretendard SemiBold, Pretendard, Malgun Gothic"
    fontSize: "10.5pt"
    fontWeight: 600
  body:
    fontFamily: "Pretendard, Malgun Gothic"
    fontSize: "10pt"
    fontWeight: 400
  reader:
    fontFamily: "Gulim, 굴림, Malgun Gothic, 맑은 고딕"
    fontSize: "9pt"
    fontWeight: 400
  label:
    fontFamily: "Pretendard, Malgun Gothic"
    fontSize: "9pt"
    fontWeight: 500
rounded:
  flat: "0px"
  control: "6px"
  surface: "8px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
components:
  app-header:
    backgroundColor: "{colors.header-surface}"
    textColor: "{colors.ink}"
    height: "52px"
    rounded: "{rounded.flat}"
  navigation-rail:
    backgroundColor: "{colors.rail-surface}"
    textColor: "{colors.ink}"
    width: "168px"
    rounded: "{rounded.flat}"
  paper-surface:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.surface}"
  button-primary:
    backgroundColor: "{colors.primary-action}"
    textColor: "{colors.paper}"
    rounded: "{rounded.control}"
    height: "36px"
  field:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    height: "36px"
---

# Design System: 국가법령정보 통합검색

## Overview

**Creative North Star: “회색 문서 작업대”**

이 제품은 포털이나 장식적인 대시보드가 아니라, 법령·판례·해석례를 오래 읽고
대조하는 실무자의 데스크톱 작업공간이다. 따뜻한 회색 캔버스 위에 흰 종이 같은
본문 면을 놓고, 숯빛 잉크로 정보 위계를 만든다. 인터페이스는 조용히 물러나되
현재 위치, 열린 문서, 포커스와 대기 상태는 즉시 식별되어야 한다.

**Key Characteristics:**

- 따뜻한 회색 캔버스와 흰 종이 면의 분명한 층위
- 숯빛 잉크를 중심으로 한 저채도 작업 도구
- 포커스와 현재 선택에만 제한적으로 쓰는 파랑
- 52px 헤더, 168px 평면 레일, 긴 본문이 우선하는 조밀한 데스크톱 밀도
- 좁은 창에서 기능을 없애지 않고 필요할 때 공개하는 compact reader

## Colors

팔레트의 중심은 warm gray canvas, white paper surfaces, charcoal ink다. 파랑은
브랜드 장식이나 일반 강조색이 아니라 포커스와 현재 선택을 알리는 상태색이다.
주요 실행 버튼은 파랑 대신 숯빛 면을 사용한다. 실제 값의 단일 기준은
`ui/theme.py`의 `WORKBENCH_COLORS`이며, objectName 기반 상태색은
`LawSearchWindow._apply_style`에서 이 역할 체계를 따라야 한다.

### Primary

- **Current Blue:** 현재 탭, 현재 카테고리, 선택 행, 체크 상태와 키보드 포커스에만 쓴다.
- **Charcoal Action:** 검색·전송 같은 주요 실행 동작의 채운 버튼에 쓴다.

### Neutral

- **Warm Gray Canvas:** 창 바탕과 페이지 사이의 작업공간을 만든다.
- **White Paper:** 카드, 입력 필드, 표, 목차와 법령 본문의 읽기 면이다.
- **Charcoal Ink:** 제목과 본문, 강한 정보 계층의 기본 잉크다.
- **Muted Ink:** 부가 설명과 비활성에 가까운 보조 정보에 쓰되 일반 크기 텍스트는
  캔버스 위에서 최소 4.5:1 대비를 유지한다.
- **Quiet Border:** 종이 면과 컨트롤을 구분하는 1px 선이다.
- **Hover Gray:** 중립 컨트롤의 hover를 알리는 면 변화다.

**The Blue Means State Rule.** 파랑은 포커스 또는 현재 선택을 뜻해야 한다. 장식,
일반 카드 배경, 모든 주요 버튼에 파랑을 확장하지 않는다.

## Typography

**Display Font:** Pretendard SemiBold (Malgun Gothic fallback)

**Body Font:** Pretendard (Malgun Gothic fallback)

**Reader Font:** Malgun Gothic / 맑은 고딕

UI는 Pretendard의 단정한 폭과 400–600 두께로 밀도를 관리한다. 법령 본문은 한글
가독성과 기존 렌더링 호환성을 위해 맑은 고딕을 유지하고, 사용자가 7–18pt 범위에서
조절할 수 있어야 한다.

### Hierarchy

- **App title:** 10.5pt, 600. 헤더의 제품 식별에만 쓴다.
- **Section title:** Pretendard SemiBold, 600. 검색 구획과 본문 구획을 짧게 구분한다.
- **Body:** 10pt, 400–500. 메뉴, 검색 조건, 결과와 일반 UI의 기본 계층이다.
- **Label:** 8.5–9pt, 500–600. 보조 상태, 그룹 제목과 짧은 컨트롤 레이블에 쓴다.
- **Reader:** 7–18pt, 400. 문서 구조가 본문 서식보다 우선하며 사용자 배율을 보존한다.

**The Document Leads Rule.** UI 제목을 크게 키워 법령 제목이나 조문 위계를
압도하지 않는다.

## Layout

창은 최소 900×640, 기본 1440×860이다. 앱 크롬은 창 가장자리까지 이어지고
레이아웃은 위에서 아래로 52px 헤더, 가운데 작업 영역, 공용 상태줄로 구성된다.
1100px 이상에서는 작업 영역 왼쪽에 168px 고정 폭의 평면 레일을 두고, 나머지 폭은
검색·결과·본문에 양보한다. 레일 항목은 40px 높이이며 `조사`와 `도구` 그룹을 짧은
레이블로 구분한다.

1100px 미만에서는 레일과 헤더의 제품명 레이블을 숨기고, 헤더의 `compactNavigation`
콤보로 즐겨찾기·검색·AI·열람 내역의 동일한 목적지를 제공한다. 넓은 레일과 좁은
선택기는 같은 페이지 상태를 양방향으로 동기화해야 한다. 앱 전체 구조를 가로
스크롤로 유지하지 않는다.

compact reader에서는 본문 폭을 먼저 지킨다. 조문 목차는 기본으로 접고, 목차가 있는
문서에서만 `목차` 단추를 보여 준다. 사용자가 단추 또는 Alt+T로 열면 목차 폭은
190–240px 범위에서 작업 영역의 약 1/3을 사용하며, 단추는 `목차 닫기`로 상태를
명시한다. 상시 노출되던 음영색·글자색·초기화·메모 도구는 숨기고 같은 동작을
`서식` 메뉴에서 점진적으로 공개한다. 1100px 이상으로 돌아오면 목차와 서식 도구를
원래의 넓은 화면 배치로 복원한다.

크게 보기에서는 52px 헤더와 열린 본문 띠를 남기되 레일과 compact navigation을
접어 읽기 폭을 최대로 확보한다.

## Elevation & Depth

기본 깊이는 그림자가 아니라 면색과 1px 경계로 만든다. 캔버스, 레일, 흰 종이 면의
작은 명도 차이가 구조를 설명하며, 카드와 본문은 떠 있는 타일보다 놓인 문서처럼
보여야 한다. hover와 선택도 큰 그림자나 이동 대신 중립 면 변화와 선으로 반응한다.

**The Flat-by-Default Rule.** 헤더와 레일은 반경 0의 평면이며, 상시 그림자를
추가하지 않는다. 팝업처럼 실제로 겹치는 요소만 플랫폼이 요구하는 깊이를 가진다.

## Shapes

앱 크롬과 구획 탭은 평평한 직선 구조를 사용한다. 입력과 일반 버튼은 5–6px,
카드와 큰 컨테이너는 8px 안팎의 작은 모서리를 사용한다. 탭과 카테고리 선택은
둥근 캡슐이 아니라 평평한 면과 2px 하단선으로 현재 상태를 표시한다. 경계는 보통
1px이며 선택·포커스에서만 두께나 색이 강해진다.

## Components

### Header

- **Structure:** 52px 고정 높이, 좌우 14px 여백, 28px 로고, 열린 본문 띠와 API 설정.
- **Surface:** 연한 회색 평면과 1px 하단 경계. 크게 보기에서도 유지한다.
- **Open documents:** 32px 높이 탭으로 현재 문서를 흰 면과 파란 2px 하단선으로 표시한다.
- **Compact state:** 제품명 대신 접근성 이름이 있는 화면 선택 콤보를 노출한다.

### Navigation

- **Wide:** 168px 평면 레일, 40px 행, 왼쪽 정렬. hover는 회색 면, 현재 행은 회색 면과
  파란 텍스트, 경계, 600 두께를 함께 사용한다.
- **Compact:** 1100px 미만에서 헤더 콤보로 대체하며 목적지와 현재 상태를 그대로 보존한다.
- **Reading mode:** 레일을 접되 열린 본문 맥락은 헤더에 남긴다.

### Buttons

- **Primary:** 숯빛 배경과 흰 글자, 36px 높이, 6px 모서리. hover는 더 짙은 숯빛이다.
- **Secondary:** 흰 면과 중립 경계. hover는 회색 면 변화로 반응한다.
- **Focus:** 모든 실행 버튼은 파란 2px 경계를 사용한다.

### Inputs and Lists

- **Fields:** 36px 이상 높이, 흰 면, 중립 1px 경계, 6px 모서리. 포커스는 파란 2px 경계다.
- **Tables and trees:** 흰 종이 면, 옅은 교차 행, 중립 그리드. 선택은 옅은 파란 면과
  진한 파란 글자를 함께 써서 색 하나에만 의존하지 않는다.
- **Text browser:** 흰 종이 면과 숯빛 본문을 유지하며 사용자 글자 크기와 선택 서식을 보존한다.

### Compact Reader Controls

- **목차:** 목차가 있을 때만 표시되는 checkable 단추다. 기본은 닫힘이며 Alt+T와
  `조문 목차 열기 또는 닫기` 접근성 이름을 제공한다.
- **서식:** compact reader에서 상시 팔레트를 대신하는 메뉴 단추다. 음영색, 글자색,
  선택·전체 초기화, 선택 영역 메모를 빠짐없이 제공하고 `본문 서식 메뉴` 접근성 이름을 갖는다.

## Do's and Don'ts

### Do:

- **Do** 따뜻한 회색 캔버스, 흰 종이 면, 숯빛 잉크 순서로 시각 계층을 만든다.
- **Do** 52px 헤더, 168px 레일, 1100px compact breakpoint를 공통 계약으로 유지한다.
- **Do** compact reader에서 목차와 서식을 필요할 때 공개하되 기능, 상태와 단축키는 보존한다.
- **Do** 모든 실행 동작을 Tab으로 도달 가능하게 하고 아이콘 전용 또는 의미가 모호한
  컨트롤에는 한국어 접근성 이름과 툴팁을 함께 제공한다.
- **Do** 일반 크기 텍스트는 WCAG AA의 4.5:1 대비를 목표로 하고, 포커스와 현재 선택을
  경계·면·글자 두께 같은 비색상 단서와 함께 표시한다.
- **Do** 키보드 포커스, 접근성 이름, 900px와 1440px 배치, 종료 시 백그라운드 작업 정리를
  회귀 검증에 포함한다.

### Don't:

- **Don't** 파랑을 장식이나 일반 주요 버튼에 사용하지 않는다. 파랑은 포커스와 현재 상태의 언어다.
- **Don't** compact reader에서 목차·서식 기능을 삭제하거나 마우스 전용 메뉴로 축소하지 않는다.
- **Don't** 헤더·레일·카드에 그라디언트, 강한 그림자, 과도한 캡슐 모양을 추가하지 않는다.
- **Don't** `NoFocus`를 실행 가능한 컨트롤에 사용하거나 포커스 윤곽을 제거하지 않는다.
- **Don't** 같은 역할의 색상이나 반복 컴포넌트를 화면별 임의 값으로 복제하지 않는다.
  색상은 `WORKBENCH_COLORS`, 공용 구조는 `ui/widgets.py`, 전역 상태 스타일은
  `LawSearchWindow._apply_style`에서 관리한다.
