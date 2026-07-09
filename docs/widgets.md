# macOS Widgets

이 저장소는 macOS 바탕화면/Notification Center에서 사용할 수 있는 WidgetKit 앱을 빌드합니다.

설치되는 앱:

```text
/Applications/Jehyun Dashboard Widgets.app
```

## 제공 위젯

| 위젯 | 용도 | 크기 |
| --- | --- | --- |
| `Token Matrix` | OpenAI·Anthropic·Google의 구독 토큰과 API 토큰을 한 화면에 매트릭스로 표시 | Small, Medium, Large, Extra Large* |
| `OpenAI Token Status` | OpenAI의 구독 토큰과 API 토큰을 표시 | Small, Medium, Large |
| `Anthropic Token Status` | Anthropic의 구독 토큰과 API 토큰을 표시 | Small, Medium, Large |
| `Google Token Status` | Google/Gemini의 API 토큰을 표시 | Small, Medium, Large |

`Extra Large`는 macOS가 해당 위젯 표면에서 제공할 때만 선택됩니다. Apple WidgetKit은 임의 픽셀 폭, 예를 들어 “지금보다 가로 2배” 같은 크기를 직접 지정할 수 없습니다. 그래서 provider별 위젯을 따로 제공해 세 개를 나란히 놓을 수 있게 했습니다.

## 설치

클라이언트 Mac에서:

```bash
./tools/install_from_macmini.sh
```

또는 WidgetKit 앱만 직접 빌드/설치하려면:

```bash
./widgets/widgetkit/build-install.sh
```

일반 운영에서는 `install_from_macmini.sh`를 권장합니다. Mac mini가 push한 최신 소스를 받은 뒤 설치하기 때문입니다.

## 추가 방법

1. 바탕화면 우클릭
2. **위젯 편집** 선택
3. `Jehyun Dashboards` 검색
4. 원하는 위젯 선택
5. 크기 선택 후 바탕화면에 배치

## 갱신 주기

- 위젯 timeline은 약 5분 뒤 다음 갱신을 요청합니다.
- 실제 데이터도 Mac mini 수집기가 5분 단위로 게시하는 것을 기준으로 설계되어 있습니다.
- provider API 또는 GitHub Pages 캐시 상황에 따라 몇 분 지연될 수 있습니다.

## 위젯이 목록에 안 보일 때

대부분 macOS WidgetKit/chronod descriptor cache 문제입니다.

순서대로 시도하세요.

1. 위젯 편집 창을 닫고 다시 열기
2. 1~2분 기다린 뒤 다시 검색
3. 재설치

```bash
./tools/install_from_macmini.sh
```

4. 등록 확인

```bash
pluginkit -m -v -A -i dev.jehyunlee.dashboards.TokenWidgets.OpenAITokenWidgetExtension
pluginkit -m -v -A -i dev.jehyunlee.dashboards.TokenWidgets.AnthropicTokenWidgetExtension
pluginkit -m -v -A -i dev.jehyunlee.dashboards.TokenWidgets.GoogleTokenWidgetExtension
```

5. 그래도 안 보이면 로그아웃/로그인

## 위젯은 보이는데 데이터가 낡았을 때

1. 웹 대시보드 데이터 확인

```bash
open https://tech.jehyunlee.dev/dashboards/tokens/
```

2. Mac mini에서 데이터 게시가 성공했는지 확인

```bash
ssh 100.114.66.16 'DASHBOARD_REPO=$HOME/pc_agent/dashboards-data python3 $HOME/pc_agent/dashboards/tools/token_status.py'
```

3. 로컬 위젯 재설치/chronod 재시작

```bash
./tools/install_from_macmini.sh
```

## 개발 메모

WidgetKit 코드는 `widgets/widgetkit/Sources/TokenStatusWidget.swift`에 있습니다. 빌드 스크립트는 동일한 Swift 소스를 네 개의 extension으로 나누어 컴파일합니다.

- `TokenStatusWidgetExtension`: 전체 매트릭스
- `OpenAITokenWidgetExtension`: OpenAI 전용
- `AnthropicTokenWidgetExtension`: Anthropic 전용
- `GoogleTokenWidgetExtension`: Google 전용

provider별 위젯을 별도 extension으로 둔 이유는 macOS 위젯 갤러리 descriptor cache가 한 extension 안에 뒤늦게 추가된 여러 widget을 안정적으로 다시 표시하지 않는 경우가 있었기 때문입니다.
