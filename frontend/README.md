# 탄소줄이슈

Figma 디자인을 바탕으로 만든 행사 비용·탄소 분석 웹사이트의 화면 구현 프로젝트입니다. 팀원들과 GitHub에서 함께 수정할 수 있도록 정리한 독립 실행 파일입니다.

메인 → 행사 정보 → 품목 입력 → 탄소 분석 → AI 개선안 → 비교 보고서로 이동합니다. 품목 입력은 인쇄물·홍보물, 음료·일회용품, 음식·간식, 굿즈의 네 카테고리로 구성됩니다.

로그인·마이페이지는 제거되어 있습니다. 품목 입력칸과 배송 버튼 정렬, 배출계수 출처 창의 선택·검색·링크 수정도 포함되어 있습니다.

## 실행

Node.js 20.11 이상이 필요합니다. 프로젝트 폴더에서 다음 명령을 실행하세요.

```sh
npm start
```

브라우저에서 http://127.0.0.1:4173 에 접속하세요. 외부 패키지가 없어 `npm install`은 필요하지 않습니다. `index.html`을 더블클릭하면 화면 데이터를 불러올 수 없으므로 서버로 실행해주세요.

## 파일 수정 위치

| 수정할 내용 | 파일 |
| --- | --- |
| 메인 화면 | `pages/home.html` |
| 행사 정보 입력 | `pages/event.html` |
| 품목 입력 | `pages/items-print.html`, `items-drink.html`, `items-food.html`, `items-goods.html` |
| 분석 결과 | `pages/analysis.html` |
| AI 추천 | `pages/recommend.html`, `pages/recommend-more.html` |
| 비교 보고서 | `pages/report.html` |
| 팝업 화면 | `pages/custom-dialog.html`, `pages/sources-dialog.html` |
| 화면 이동·입력·버튼 동작 | `app.js` |
| 배출계수 출처 창의 동작·디자인 | `sources-dialog.js`, `sources-dialog.css` |
| 공통 스타일 | `base.css` |
| 모바일·태블릿 배치 | `responsive.css` |
| 품목 입력칸·배송 버튼 배치 | `items-layout.css` |
| Figma에서 변환한 기본 스타일 | `design.css` |
| 이미지·로고·글꼴 | `assets/`, `fonts.css` |

HTML의 `data-name`은 원본 디자인의 영역 이름입니다. `app.js`가 `data-name`과 `data-node-id`로 동작을 연결하므로, 이름을 바꿀 때는 연결 코드도 함께 수정하세요. `design.css`의 해시 형태 클래스는 원본 디자인 값이며, 추가 스타일은 해당 화면의 CSS 파일에 작성하면 찾기 쉽습니다.

`pages/*.html`을 수정한 뒤 `npm run build`를 실행하고 브라우저를 새로고침하세요. `npm start`도 시작할 때 화면을 자동 반영합니다. 개발 서버에는 자동 새로고침 기능이 없습니다.

`screens.json`은 HTML 화면들을 합쳐 만든 생성 파일입니다. 직접 수정하지 말고 `pages/`를 수정한 뒤 다시 생성하세요. 바로 정적 호스팅할 수 있도록 이 파일도 저장소에 포함합니다.

## GitHub에 올리기

1. GitHub에서 새 저장소를 만드세요.
2. ZIP을 풀고 이 폴더 안의 파일과 폴더를 저장소 최상위에 올리세요. `index.html`과 `package.json`이 최상위에 오면 됩니다.
3. 저장소에 함께 수정할 팀원을 초대하세요.
4. 팀원마다 브랜치를 만들어 수정한 뒤 Pull Request로 변경사항을 합치세요. 자세한 방법은 [CONTRIBUTING.md](CONTRIBUTING.md)에 있습니다.

숨김 파일 `.gitignore`와 `.gitattributes`도 포함해주세요. 기존 Sites 호스팅의 식별 정보, Git 기록, 인증 정보는 이 패키지에 포함하지 않았습니다.

## 정적 배포

루트의 `index.html`, JavaScript, CSS, `screens.json`, `assets/`를 함께 제공하면 됩니다. 상대 경로와 해시 주소를 사용하므로 저장소 하위 경로에서도 작동합니다. 화면을 수정했다면 배포 전에 `npm run build`를 실행하세요.

## 확인 명령

```sh
npm run check
npm run build
```

첫 명령은 JavaScript 문법을, 두 번째 명령은 필수 화면 파일과 생성 과정을 확인합니다. 버튼 동작과 PC·모바일 배치는 브라우저에서도 직접 확인해주세요.

## 구현 범위

분석 수치와 AI 추천은 Figma를 바탕으로 한 예시입니다. 실제 탄소 계산, AI 요청, 서버 저장은 연결하지 않았습니다. 행사 입력 내용은 새로고침하면 초기화됩니다.

배출계수 출처 창은 카테고리·품목 선택과 검색을 지원합니다. 미등록 배출계수는 임의로 채우지 않았고, 개별 원문 링크가 없는 항목은 등록 상태를 안내합니다. 이미지와 글꼴은 로컬 파일로 포함되어 있습니다.
