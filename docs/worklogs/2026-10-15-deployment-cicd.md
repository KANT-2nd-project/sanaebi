# 공개 시연 배포·CI/CD 구현 기록

최신 main `55a060c06d8577f65c0a0b4615927f92892d8e82`에서 별도 `feat/deployment-cicd-20261015` worktree를 구성했다. 기존 기능 브랜치 전체를 병합하지 않고 사용자 미커밋 웹 변경을 복사해 검증 대상으로 포함했다. 원래 worktree·학습 결과는 보존한다.

## 검증 진행 상태

- 서버 전용 HF 토큰으로 pinned private 모델 config 접근 HTTP 200 확인.
- API 제한·KST 영속 생성 예산·health probe 구현. 클라이언트 취소 후에도 실제 작업 종료까지 동시 요청 슬롯 유지.
- ARM64 CPU 의존성·nginx allowlist·배포/백업/reset helper·Delivery workflow 준비.
- 웹 테스트 71개(429 안내·입력 보존 포함), lint·typecheck·빌드 통과. production npm audit 취약점 0개.
- 서버 Docker 설치, deploy SSH 접속, 고정 host key, production main 환경 정책 확인. 자동 배포는 첫 검증 전까지 비활성화.
- archive 테스트의 로컬 DB 의존성·HF 테스트 runner 불일치를 수정한 뒤 전체 Python 630개 통과.
- 실제 서버에서 aarch64, PyTorch 2.14.1+cpu, CUDA 미포함을 확인했다. HF 5개 파일 다운로드·해시 검증과 네트워크/토큰 없는 캐시 재사용을 확인했다.
- 새 nginx 설정을 별도 설정 파일로 nginx -t 검증했고, 설치한 root 배포 wrapper --help와 잘못된 release ID 거부를 확인했다.

실제 Actions·이미지·모델 회귀·부하·HTTPS·재기동·복원 결과는 확인 후 추가한다. 전체 운영 완료 상태는 아니다.

- [ARM64 측정 원자료](evidence/2026-10-15-arm64-runtime.json): 저장 예측 133/133 일치, cold 571.9ms, warm 평균 105.237ms, peak RSS 912601088 bytes. mock 동시 요청 1·2 모두 초과 429 즉시 반환. 실제 유료 생성 부하를 의미하지 않는다.
- 독립 검토로 최초 배포 rollback, ContextVar, 운영 로그, DB mount 격리, 강제 종료 복구, nginx activation 재시도 문제를 발견하고 보완했다. 배포·reset 관련 34개 테스트 통과.
