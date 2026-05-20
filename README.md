# ⚡ 영업현황 자동화 시스템

EV 충전기 영업현황 + 누리집 등록 자동화 RPA 관리 도구

## 📋 페이지 구성

| 페이지 | 설명 |
|---|---|
| [`index.html`](./index.html) | 대시보드 — 담당자 세션 + 오늘 작업 요약 |
| [`bpms.html`](./bpms.html) | BPMS 데이터 조회·매핑 — 엑셀 업로드/매칭/필터 |
| [`files.html`](./files.html) | 파일·PDF 관리 — 검수 목록 + 7종 첨부파일 매칭 |
| [`queue.html`](./queue.html) | 작업 큐 — 실시간 진행/대기/완료 모니터링 |

## 🛠 기술 스택

- **Frontend**: HTML / CSS / Vanilla JS
- **Excel Parser**: [SheetJS (xlsx.js)](https://sheetjs.com/)
- **Storage**: localStorage (각 브라우저 단위)

## ⚠️ 임시 데모용 안내

현재 프론트엔드 전용 프로토타입입니다.

- 데이터는 **각 브라우저 localStorage**에 저장됩니다.
- 사용자 간 데이터 공유는 **별도 백엔드(서버 + DB) 필요**.
- 실제 자동화(Playwright)는 **팀 PC에서 별도 실행** 필요.

## 🚀 운영 단계 (Phase 2~3 예정)

- Python FastAPI + PostgreSQL 백엔드
- Playwright 기반 누리집·BPMS 자동화
- 회사 NAS 연동 (첨부파일 보관)
- PDF 파싱 + OCR (사업자등록증)

---

**Made with ⚡ by 서아름**
