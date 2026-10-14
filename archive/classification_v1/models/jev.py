"""Jev HTTP 요청. 재시도하지 않으며 재사용 함수는 프로세스를 종료하지 않는다."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..types import Prediction, validate_label
from .jev_prompt import API_URL, CATEGORIES, INSTRUCTIONS, MODEL_NAME


class JevRequestError(RuntimeError):
    """인증 설정 부재 또는 외부 요청 실패. CLI에서 종료 메시지로 변환한다."""


def request_classification(question: str) -> dict:
    api_key = os.environ.get("TYPESAFE_API_KEY")  # 키는 환경변수에서 읽기
    if not api_key:
        raise JevRequestError("TYPESAFE_API_KEY 환경변수에 API 키를 설정해 주세요.")

    # 현재 질문의 정답은 보내지 않으며, 판단 기준에는 train 대표 예시를 포함
    payload = {
        "model": MODEL_NAME,
        "state": question,
        "questions": {
            "category": {
                "type": "choice",
                "instructions": INSTRUCTIONS,
                "criteria": CATEGORIES,
            }
        },
    }
    request = Request(
        API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise JevRequestError(
            f"Jev API 요청 실패 (HTTP {error.code}). API 키·사용 권한·크레딧을 확인해 주세요."
        ) from None
    except (URLError, TimeoutError):
        raise JevRequestError(
            "Jev API 연결에 실패했습니다. 네트워크를 확인해 주세요."
        ) from None

    category = result["answers"]["category"]["choice"]
    if category not in CATEGORIES:
        raise ValueError("API가 반환한 카테고리가 현재 목록에 없습니다.")
    return result  # 평가에서는 실제 모델 버전과 토큰 사용량도 기록


def predict(question):
    result = request_classification(question)
    answer = result["answers"]["category"]
    return Prediction(
        validate_label(answer["choice"]),
        answer.get("confidence"),
        answer.get("probabilities"),
        result.get("model"),
        result.get("usage", {}).get("input_tokens"),
    )


def require_credentials():
    if not os.environ.get("TYPESAFE_API_KEY"):
        raise JevRequestError("TYPESAFE_API_KEY 환경변수에 API 키를 설정해 주세요.")
