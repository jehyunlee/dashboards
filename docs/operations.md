# Operations

운영 원칙은 단순합니다.

> Mac mini가 만들고, GitHub가 배포하고, 다른 Mac은 받아서 설치합니다.

## 브랜치 역할

| 브랜치 | 역할 |
| --- | --- |
| `main` | 정적 사이트, 도구 코드, 위젯 코드, 문서 |
| `data` | 공개 JSON 데이터. GitHub Pages 빌드 때 `main`과 합쳐짐 |

## Mac mini authoritative workflow

대시보드 소스 수정은 Mac mini에서 합니다.

```bash
cd ~/pc_agent/dashboards
# 수정
git status --short
git add <files>
git commit -m "..."
git push origin main
```

MacBook 같은 클라이언트에서는 직접 커밋하지 않습니다. `.githooks/pre-commit`이 이를 막습니다.

예외적으로 긴급 커밋이 필요하면 다음 환경변수로 우회할 수 있지만, 기본 운영에서는 사용하지 않습니다.

```bash
DASHBOARD_ALLOW_LOCAL_COMMIT=1 git commit -m "..."
```

## 클라이언트 업데이트

Mac mini가 push한 뒤 클라이언트 Mac에서:

```bash
cd /path/to/dashboards
./tools/install_from_macmini.sh
```

문서나 웹만 바뀌었고 위젯 설치가 필요 없으면 단순 pull만 해도 됩니다.

```bash
git pull --ff-only origin main
```

## 원격에서 Mac mini repo 확인

클라이언트 저장소에는 Mac mini repo에 명령을 보내는 helper가 있습니다.

```bash
./tools/macmini_authoring.sh git status --short
./tools/macmini_authoring.sh git rev-parse --short HEAD
```

기본값:

- host: `100.114.66.16`
- repo: `/Users/jehyunlee/pc_agent/dashboards`

환경변수로 바꿀 수 있습니다.

```bash
DASHBOARD_MACMINI_HOST=... DASHBOARD_MACMINI_REPO=... ./tools/macmini_authoring.sh git status
```

## 데이터 게시 명령

토큰/API 상태:

```bash
ssh 100.114.66.16 \
  'DASHBOARD_REPO=$HOME/pc_agent/dashboards-data python3 $HOME/pc_agent/dashboards/tools/token_status.py'
```

Mac mini workflow 상태:

```bash
ssh 100.114.66.16 \
  'DASHBOARD_REPO=$HOME/pc_agent/dashboards-data python3 $HOME/pc_agent/dashboards/tools/macmini_heartbeat.py'
```

## 배포 확인

GitHub Pages는 `main` push 때 자동 배포됩니다.

- 홈: <https://tech.jehyunlee.dev/dashboards/>
- 토큰: <https://tech.jehyunlee.dev/dashboards/tokens/>
- 컴팩트 토큰 위젯: <https://tech.jehyunlee.dev/dashboards/tokens/widget/>

raw 데이터:

- <https://raw.githubusercontent.com/jehyunlee/dashboards/data/data/tokens.json>
- <https://raw.githubusercontent.com/jehyunlee/dashboards/data/data/tokens_history.json>
- <https://raw.githubusercontent.com/jehyunlee/dashboards/data/data/macmini.json>

## 상태 확인 명령

WidgetKit extension 등록:

```bash
pluginkit -m -v -A -i dev.jehyunlee.dashboards.TokenWidgets.TokenStatusWidgetExtension
pluginkit -m -v -A -i dev.jehyunlee.dashboards.TokenWidgets.OpenAITokenWidgetExtension
pluginkit -m -v -A -i dev.jehyunlee.dashboards.TokenWidgets.AnthropicTokenWidgetExtension
pluginkit -m -v -A -i dev.jehyunlee.dashboards.TokenWidgets.GoogleTokenWidgetExtension
```

최근 WidgetKit 로그:

```bash
log show --last 5m --style compact --predicate \
  'eventMessage CONTAINS[c] "dev.jehyunlee.dashboards.TokenWidgets" OR process CONTAINS[c] "TokenWidgetExtension"'
```

## 새 대시보드 추가 절차

1. Mac mini의 `~/pc_agent/dashboards`에서 새 정적 페이지를 추가합니다.
2. 필요한 JSON 데이터가 있으면 `data` 브랜치에 게시하는 도구를 `tools/`에 둡니다.
3. `.github/workflows/pages.yml`의 artifact 준비 단계에 새 페이지/데이터를 추가합니다.
4. Mac mini에서 commit/push합니다.
5. GitHub Pages 배포 후 URL을 확인합니다.
6. macOS 위젯이 필요하면 `widgets/widgetkit/`에 추가하고 클라이언트에서 `./tools/install_from_macmini.sh`를 실행합니다.
