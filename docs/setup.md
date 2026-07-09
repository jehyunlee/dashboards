# Setup

이 문서는 새 Mac mini 또는 새 클라이언트 Mac에서 Jehyun Dashboards를 사용할 때 필요한 설정을 정리합니다.

## 전제 조건

### 공통

- GitHub 계정과 `jehyunlee/dashboards` 접근 권한
- SSH key 기반 GitHub push/pull 설정
- Python 3

### Mac mini, 서버/작성 머신

- 저장소 쓰기 권한
- `main` 브랜치 체크아웃: 정적 사이트와 도구 코드
- `data` 브랜치 체크아웃: 공개 JSON 데이터 게시용
- OpenAI, Anthropic, Google API key
- OpenAI/Anthropic 사용량까지 보려면 provider admin key
- 선택: [Gajae Code](https://github.com/Yeachan-Heo/gajae-code)(`gjc`)/Codex/Claude Code/Gemini CLI 사용량을 받는 로컬 usage receiver

### macOS 위젯을 설치할 클라이언트

- macOS 14 이상 권장
- `/usr/bin/swiftc` 사용 가능해야 함. 보통 Xcode Command Line Tools 또는 Xcode 설치로 해결됩니다.
- `/Applications`에 앱을 설치할 수 있는 권한

## 저장소 배치

권장 배치입니다.

```bash
# Mac mini: 소스 작성/커밋/push
git clone git@github.com:jehyunlee/dashboards.git ~/pc_agent/dashboards

# Mac mini: data 브랜치 게시용 별도 worktree/clone
git clone -b data git@github.com:jehyunlee/dashboards.git ~/pc_agent/dashboards-data
```

`tools/token_status.py`의 기본 데이터 저장소 위치는 `~/pc_agent/dashboards-data`입니다. 다른 위치를 쓰면 `DASHBOARD_REPO`로 넘깁니다.

```bash
DASHBOARD_REPO=/path/to/data-branch-checkout python3 tools/token_status.py
```

## 키 설정

`tools/token_status.py`는 다음 순서로 키를 읽습니다.

1. `PC_KEYS_ENV` 또는 기본 `~/pc_agent/keys.env`
2. `PC_LOCAL_KEYS` 또는 기본 `~/Documents/paper-curation/docs/_local_keys.json`
3. `PC_DASHBOARD_KEYS` 또는 기본 `~/pc_agent/dashboard_keys.json`
4. 현재 프로세스 환경변수

### `keys.env` 예시

```bash
OPENAI_API_KEY=sk-...
OPENAI_ADMIN_KEY=sk-admin-...
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_ADMIN_KEY=sk-ant-admin-...
GOOGLE_API_KEY=AIza...
```

지원하는 별칭:

- OpenAI: `OPENAI_API_KEY`, `openai_key`
- OpenAI Admin: `OPENAI_ADMIN_API_KEY`, `OPENAI_ADMIN_KEY`
- Anthropic: `ANTHROPIC_API_KEY`, `anthropic_key`
- Anthropic Admin: `ANTHROPIC_ADMIN_API_KEY`, `ANTHROPIC_ADMIN_KEY`
- Google/Gemini: `GOOGLE_API_KEY`, `GEMINI_API_KEY`, `google_api_key`, `gemini_api_key`

API 접속 상태 probe는 모델 quota를 소모하므로 실행하지 않습니다. Admin key가 없으면 월간 사용량/비용 또는 5분 단위 API 사용량 일부가 비어 있을 수 있습니다.

## 데이터 게시

토큰 상태를 한 번 게시하려면 Mac mini에서 실행합니다.

```bash
DASHBOARD_REPO=$HOME/pc_agent/dashboards-data \
python3 $HOME/pc_agent/dashboards/tools/token_status.py
```

게시 결과:

- `data/tokens.json`: 현재 provider별 상태
- `data/tokens_history.json`: 5분 단위 토큰 사용량 표본 이력

스크립트는 `data` 브랜치에서 pull/rebase 후 변경된 JSON을 commit/push합니다.

## 5분 단위 실행

이 저장소는 특정 launchd plist를 강제하지 않습니다. Mac mini 운영 환경에 맞게 launchd, cron, 또는 다른 scheduler로 5분마다 실행하면 됩니다.

launchd/cron에서 실행할 명령의 핵심은 같습니다.

```bash
DASHBOARD_REPO=$HOME/pc_agent/dashboards-data \
PC_KEYS_ENV=$HOME/pc_agent/keys.env \
python3 $HOME/pc_agent/dashboards/tools/token_status.py
```

## 구독 토큰 사용량 수집

`tools/token_status.py`는 구독/CLI 사용량을 다음 로컬 파일에서 읽습니다.

- `PC_OTEL_USAGE` 또는 `~/pc_agent/otel/usage_local.json`
- `PC_OTEL_USAGE_API` 또는 `~/pc_agent/otel/usage_api_local.json`

[Gajae Code](https://github.com/Yeachan-Heo/gajae-code)(`gjc`) 세션 사용량은 `tools/gjc_usage_reporter.py`가 로컬 receiver로 전송합니다.

```bash
PC_GJC_USAGE_ENDPOINT=http://localhost:4318/gjc/usage \
python3 tools/gjc_usage_reporter.py
```

Gajae Code는 OAuth/구독 기반 사용량이 provider Admin API에 보이지 않을 수 있어 세션 로그를 별도로 집계합니다.

실제 receiver와 LaunchAgent 구성은 개인 운영 환경에 속합니다. 핵심은 5분 bin 단위 JSON이 위 경로에 생성되어야 토큰 대시보드가 subscription/API 사용량 그래프를 채울 수 있다는 점입니다.

## 클라이언트 Mac 위젯 설치

클라이언트 Mac은 소스를 직접 수정하지 않고 Mac mini가 push한 결과만 받아 설치합니다.

```bash
git clone git@github.com:jehyunlee/dashboards.git
cd dashboards
./tools/install_from_macmini.sh
```

이 스크립트는 다음을 수행합니다.

1. `origin/main` fast-forward pull
2. local commit hook 설정
3. WidgetKit 앱 빌드
4. `/Applications/Jehyun Dashboard Widgets.app` 설치
5. `chronod` 재시작 후 앱 열기

## GitHub Pages 배포

`.github/workflows/pages.yml`은 `main` 브랜치 push 때 실행됩니다. 빌드 시:

- `main` 브랜치의 정적 HTML/CSS/JS
- `data` 브랜치의 `data/*.json`

을 합쳐 GitHub Pages artifact로 배포합니다.
