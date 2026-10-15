# 독립 코드·결과 검토

별도 읽기 전용 AI 검토자가 현재 diff·배포 실행 경로·실측 원자료를 검토했다. 구현 담당자의 자체 확인과 구분한다.

| 지적 | 반영·재확인 |
|---|---|
| KURE spec에 Tiny 분할 tokenizer identity 누락 | splitter 모델·revision·directory를 spec과 sidecar에 포함. 기존 Tiny ID 유지 및 새 revision의 ID 변경 검증 |
| pooling 파일 배포 준비 목록 누락 | KURE descriptor에 고정 SHA의 `1_Pooling/config.json` 추가. 실제 모델 준비·로딩 성공 |
| 잘못된 pooling 형식·embedder/spec 혼용 | 안전한 오류 및 저장 전 거부 검증 |
| top20 경계 동점·Tiny/KURE 복원 혼용 | 결정적 컷오프·문서 원본/색인 무변경 검증 |
| systemd의 직접 maintenance 실행에서 import 실패(P1) | 설치 레이아웃·무관 cwd·clean PYTHONPATH의 subprocess RED/GREEN. sibling import 전 패키지 루트 등록 |

보완 후 독립 실행한 관련40개 및 standalone 설치 CLI1개 테스트가 통과했다. 최종 코드 검수에서 남은 중대한 지적은 없었다. 실측 JSON의108개 고유 문항·점수 차이0 및 동시1/2 각각144개의 p95를 직접 재계산해164.13/329.03ms와 일치함을 확인했다. 재현 실행기·작은 JSON을 정식 보고서에 보존하라는 문서 권고도 반영했다.

독립 검토는 코드·저장 원자료와 일부 회귀 테스트 재실행이다. 실제 모델 실험을 독립적으로 다시 실행하거나 사람 검수·운영·LLM 품질을 승인한 것은 아니다.
