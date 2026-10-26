# 『ファミレス行こ。』 상권 아크릴스탠드 특장판 감시기

**ISBN 9784047377486**. GitHub Actions로 10분마다 공개 상품 페이지를 확인합니다. 실제 실행은 GitHub 일정에 따라 지연될 수 있습니다.

## 현재 구현된 4곳
- KADOKAWA 공식몰
- 애니메이트 온라인
- 키노쿠니야
- 마루젠 준쿠도

**주의:** 기존 ChatGPT 자동 감시 대상 8곳 전체가 구현된 것은 아닙니다. 나머지 사이트는 실제 상품 URL과 각 사이트별 판독 규칙을 추가 검증해야 합니다. 페이지가 자바스크립트로 재고를 표시하거나 봇 접근을 막으면 `unknown`으로 표시됩니다. `possible`도 확정 재고가 아닙니다.

## 시작 방법
1. GitHub에서 새 **private** 저장소를 생성합니다.
2. 이 압축 파일을 풀고 내용물(`.github` 숨김 폴더 포함)을 저장소에 업로드합니다. 파일 경로를 그대로 유지하세요.
3. 저장소 **Settings → Actions → General → Workflow permissions**에서 **Read and write permissions**를 선택합니다. 조직 정책에 따라 선택 불가능할 수 있습니다.
4. **Actions** 탭에서 `Special edition stock monitor`를 선택하고 **Run workflow**를 한 번 실행합니다.
5. 알림 발생 시 저장소에 GitHub Issue가 생성됩니다. **자신이 만든 이슈는 푸시 알림이 오지 않을 수 있으므로, 즉각적인 휴대폰 알림을 원한다면 아래 텔레그램 설정을 추가해야 합니다.**
6. 첫 실행에서 `possible`이 검출되면 Issue가 생성됩니다. 이후 상태가 바뀌었다가 다시 `possible`이 되면 새 Issue가 생성됩니다.

## 알림 및 제약
- 10분 간격으로 예약하지만 정확한 실행 시간은 보장되지 않습니다.
- 상품 본문에 품절/주문 가능 문구가 함께 등장하면 `unknown`으로 보수적으로 분류합니다.
- `unknown`은 품절이 아닙니다. 실행 로그에서 결과를 확인할 수 있습니다.
- GitHub Actions 예약 작업은 비활성 저장소에서 중지될 수 있습니다.
- 사이트별 레이아웃 변경으로 감지가 실패할 수 있습니다. 초기 며칠간 Actions 로그를 점검하세요.
- 사이트 이용약관과 요청 빈도를 준수해야 하며 우회/차단 회피 기능은 포함하지 않습니다.
- **중요:** 이 코드는 실행 환경에서 실제 일본 쇼핑몰 페이지 접속 검증을 완료하지 않은 초안입니다. 알림이 정상 작동하는지 최초 실행 로그를 통해 확인해야 합니다.

## 선택: 아이폰 텔레그램 푸시 알림
1. Telegram에서 `@BotFather`를 통해 개인 봇을 생성하고 봇 토큰을 받습니다.
2. 생성한 봇에 `/start`를 보냅니다.
3. `https://api.telegram.org/bot<봇토큰>/getUpdates`에서 `chat.id`를 확인합니다. 토큰은 타인에게 공유하지 마세요.
4. GitHub 저장소 **Settings → Secrets and variables → Actions → New repository secret**에서 `TELEGRAM_BOT_TOKEN`과 `TELEGRAM_CHAT_ID`를 각각 등록합니다.
5. Telegram 앱에서 알림을 허용합니다.

텔레그램 설정이 없으면 GitHub Issue 기록만 남으며 아이폰 푸시 알림은 보장되지 않습니다.
