"""생성 모델 비교 평가: 평가 세트 → LangChain 실행기로 모델별 실행 → 코드·심판 LLM 판정과 사람 확인 → 보고서.

run.py 실행·기록, checks.py 코드 판정·실행 점검, judge.py 심판 LLM, scoring.py 사람 확인·최종 판정,
report.py 보고서, cli.py 명령줄. 평가 기준은 docs/generation-evaluation.md, 사용법은 cli.py 맨 위 설명을 본다.
"""
