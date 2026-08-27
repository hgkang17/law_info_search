# GitHub Releases 자동 업데이트 배포

프로그램은 공개 저장소 `hgkang17/law_info_search`의 최신 **정식 Release**를
6시간 간격으로 확인합니다. 초안(Draft)과 시험판(Pre-release)은 자동 업데이트
대상에서 제외됩니다.

> 이 저장소는 공개 상태여야 인증 토큰이 없는 배포 EXE가 Release를 읽을 수
> 있습니다. 비공개로 되돌린다면 공개된 배포 전용 저장소를 만든 뒤
> `utils/constants.py`의 `GITHUB_REPOSITORY`를 그 저장소로 바꿔야 합니다.
> GitHub 토큰을 EXE 안에 넣는 방식은 토큰이 추출될 수 있으므로 사용하지
> 않습니다.

## 최초 배포

공개 저장소의 첫 릴리스는 `1.0.0`입니다. 이미 다른 사람에게 전달된 공개 전
EXE에는 업데이트 확인 코드가 없거나 버전 번호 체계가 달라서 자동 업데이트가
닿지 않습니다. 따라서 `1.0.0` EXE는 기존 사용자에게 한 번 직접 전달해야
합니다. 그 이후 버전부터 앱 안의 알림으로 업데이트할 수 있습니다.

## 새 버전 배포 순서

1. `utils/constants.py`의 `APP_VERSION`을 올립니다. 예: `1.1.0`.
2. 변경 내용을 커밋하고 GitHub에 push합니다.
3. 같은 버전의 태그를 만들고 push합니다.

   ```powershell
   git tag v1.1.0 origin/main
   git push origin v1.1.0
   ```

   이 작업 폴더에서 공개 저장소는 `origin` 원격이고 공개 브랜치는 `main`
   입니다. 태그는 반드시 공개 브랜치를 대상으로 만들어 `origin`에 푸시합니다.
   비공개 개발 이력(`private` 원격)에 붙은 커밋에 태그를 만들어 공개 원격으로
   보내지 않습니다.

4. GitHub Actions의 `Windows Release` 작업이 다음 네 파일을 빌드하여
   정식 Release에 올립니다.

   - `국가법령정보 통합검색.exe`
   - `국가법령정보 통합검색.exe.sha256`
   - `law-search-ai-source-v버전.zip`
   - `law-search-ai-build-info.txt`

5. Actions 작업이 성공한 뒤 프로그램에서 `업데이트 확인`을 눌러 시험합니다.

태그와 `APP_VERSION`이 다르면 빌드는 의도적으로 실패합니다. 릴리스 EXE나
SHA-256 파일 이름도 바꾸면 앱이 안전하지 않은 릴리스로 판단하여 설치하지
않습니다.

소스 ZIP과 빌드 정보는 자동 업데이트에 사용하지 않지만, Release EXE와 정확히
같은 소스ㆍ도구 버전을 보존하고 수정한 Qt/PySide6로 다시 빌드할 수 있게 하는
배포 자료입니다. Qt/PySide6 대응 소스 제공 안내는
[`QT_SOURCE_OFFER.md`](QT_SOURCE_OFFER.md)를 따릅니다.

## 사용자 쪽 동작

- 프로그램 시작 2.5초 뒤 업데이트를 확인하며, 성공 여부와 관계없이 다음
  자동 확인은 6시간 뒤입니다.
- 새 버전이 있을 때만 알림을 표시합니다.
- 사용자가 `지금 업데이트`를 누르면 EXE를 내려받아 Release의 파일 크기와
  SHA-256을 모두 확인합니다.
- 검증이 끝난 새 EXE가 교체 도우미로 실행되고, 현재 프로그램이 종료된 뒤
  원래 EXE를 원자적으로 교체하여 다시 실행합니다.
- EXE가 쓰기 금지 폴더에 있으면 교체할 수 없습니다. 일반 사용자에게는
  바탕화면이나 문서 폴더처럼 본인이 쓸 수 있는 위치에 두도록 안내합니다.

## 수동 빌드로 Release를 올릴 때

GitHub Actions를 쓰지 않는 경우에도 spec으로 빌드한 다음 배포 파일 이름과
SHA-256 파일을 정확히 맞춰야 합니다.

```powershell
python -m PyInstaller --noconfirm --clean "국가법령정보 통합검색.spec"
$hash = (Get-FileHash -LiteralPath "dist\국가법령정보 통합검색.exe" -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "dist\국가법령정보 통합검색.exe.sha256" -Value "$hash  국가법령정보 통합검색.exe" -Encoding utf8
```

GitHub Release는 반드시 Draft/Pre-release가 아닌 정식 Release로 발행하고 위
네 파일을 모두 첨부합니다.
