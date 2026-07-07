# Jehyun Dashboards

개인 연구/운영 환경을 한눈에 보기 위한 정적 대시보드 모음입니다. 현재는 Mac mini에서 돌아가는 자동 작업과 OpenAI·Anthropic·Google 토큰/접속 상태를 웹 대시보드와 macOS 바탕화면 위젯으로 보여줍니다.

- 웹: <https://tech.jehyunlee.dev/dashboards/>
- 토큰 대시보드: <https://tech.jehyunlee.dev/dashboards/tokens/>
- 저장소: <https://github.com/jehyunlee/dashboards>

## 왜 필요한가

LLM 도구와 자동화가 여러 머신에서 동시에 돌아가면 “지금 API가 살아 있는지”, “구독 토큰을 얼마나 쓰고 있는지”, “API 과금/토큰 사용이 어디서 발생하는지”를 터미널 로그만으로 추적하기 어렵습니다. 이 저장소는 그 상태를 5분 단위로 모아 공개 가능한 JSON과 정적 페이지로 만들고, 자주 보는 정보는 macOS 위젯으로 바탕화면에 올려두는 역할을 합니다.

## 구성

| 영역 | 역할 |
| --- | --- |
| `index.html`, `app.js`, `style.css` | 대시보드 홈 |
| `tokens/` | OpenAI·Anthropic·Google API/토큰 상태 웹 대시보드 |
| `learn/` | Mac mini 자동 작업/학습 워크플로 상태 대시보드 |
| `tools/` | Mac mini에서 데이터를 수집·게시하는 스크립트 |
| `widgets/widgetkit/` | macOS 바탕화면용 WidgetKit 앱/위젯 |
| `widgets/ubersicht/` | Übersicht용 보조 위젯 |
| `data/` | 개발용 샘플 데이터. 실제 서비스 데이터는 `data` 브랜치에서 Pages 빌드 때 합쳐짐 |

## 운영 원칙

**대시보드 소스 작성과 커밋은 Mac mini가 주관합니다.**

- Mac mini: 서버/실행/소스 작성/커밋/push
- MacBook 등 클라이언트: GitHub에서 받아서 위젯 설치만
- 이 저장소에는 `.githooks/pre-commit`이 있어 Mac mini가 아닌 머신에서 실수로 커밋하는 것을 막습니다.

## 빠른 시작

### 1. Mac mini에서 소스와 데이터 저장소 준비

```bash
git clone git@github.com:jehyunlee/dashboards.git ~/pc_agent/dashboards
git clone -b data git@github.com:jehyunlee/dashboards.git ~/pc_agent/dashboards-data
```

### 2. Mac mini에 키 설정

민감한 키는 저장소에 넣지 않습니다. 기본 위치는 다음 중 하나입니다.

- `~/pc_agent/keys.env`
- `~/pc_agent/dashboard_keys.json`
- 환경변수

대표 키 이름:

```bash
OPENAI_API_KEY=...
OPENAI_ADMIN_KEY=...
ANTHROPIC_API_KEY=...
ANTHROPIC_ADMIN_KEY=...
GOOGLE_API_KEY=...
```

자세한 키/스케줄 설정은 [docs/setup.md](docs/setup.md)를 보세요.

### 3. Mac mini에서 데이터 게시

```bash
DASHBOARD_REPO=$HOME/pc_agent/dashboards-data \
python3 $HOME/pc_agent/dashboards/tools/token_status.py
```

이 스크립트는 `data` 브랜치의 `data/tokens.json`, `data/tokens_history.json`을 갱신합니다. GitHub Pages는 `main` 브랜치의 정적 파일과 `data` 브랜치의 JSON을 합쳐 배포합니다.

### 4. MacBook/클라이언트에서 위젯 설치

```bash
git clone git@github.com:jehyunlee/dashboards.git
cd dashboards
./tools/install_from_macmini.sh
```

설치 후 바탕화면 우클릭 → **위젯 편집** → **Jehyun Dashboards**에서 위젯을 추가합니다.

현재 제공 위젯:

- `Token Matrix`: OpenAI·Anthropic·Google 전체 매트릭스
- `OpenAI Token Status`
- `Anthropic Token Status`
- `Google Token Status`

위젯 크기와 문제 해결은 [docs/widgets.md](docs/widgets.md)에 정리했습니다.

## 데이터 흐름

```text
Mac mini collectors / local usage receiver
        ↓
tools/*.py
        ↓
github.com/jehyunlee/dashboards:data branch JSON
        ↓
GitHub Pages workflow
        ↓
tech.jehyunlee.dev/dashboards + macOS widgets
```

운영 절차와 자주 쓰는 명령은 [docs/operations.md](docs/operations.md)를 보세요.

## 보안 메모

- API 키, admin key, 개인 로그 원본은 커밋하지 않습니다.
- 공개되는 것은 정리된 상태 JSON과 정적 화면입니다.
- 토큰/비용 값은 provider API와 로컬 사용량 수집기의 가용성에 따라 지연되거나 일부 비어 있을 수 있습니다.
