"""지표·측정 계산. 모델 선택, 데이터 분할, 결과 저장을 하지 않는다."""

import ctypes
import os
import statistics
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

from contracts.classification import LABELS as ROUTING_LABELS

LABELS = list(ROUTING_LABELS)


def evaluate(rows, predictions, labels=None):
    labels = LABELS if labels is None else labels
    if labels != LABELS:
        raise ValueError("현재 요청 처리 3개 라벨만 평가할 수 있습니다.")
    actual = [row["label"] for row in rows]
    if (
        len(predictions) != len(rows)
        or set(predictions) - set(labels)
        or set(actual) - set(labels)
    ):
        raise ValueError("예측 개수 또는 라벨이 현재 데이터와 맞지 않습니다.")
    # 카테고리별 precision·recall·F1·정답 수와 전체 평균을 계산
    scores = classification_report(
        actual, predictions, labels=labels, output_dict=True, zero_division=0
    )
    # zip은 각 질문과 같은 위치의 예측을 묶고, 틀린 질문만 오답 표에 보관
    errors = [
        [
            row["question_id"],
            row["text"],
            row["label"],
            prediction,
        ]
        for row, prediction in zip(rows, predictions)
        if row["label"] != prediction
    ]
    return {
        "accuracy": accuracy_score(actual, predictions),
        "macro_f1": scores["macro avg"]["f1-score"],
        "per_class": {label: scores[label] for label in labels},
        "confusion_matrix": confusion_matrix(
            actual, predictions, labels=labels
        ).tolist(),
        "errors": errors,
    }


def memory_mib():
    """현재 프로세스의 RAM 사용량(RSS). 모델만의 메모리가 아님."""
    if sys.platform == "win32":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        get_process = ctypes.windll.kernel32.GetCurrentProcess
        get_process.restype = wintypes.HANDLE
        query = ctypes.windll.psapi.GetProcessMemoryInfo
        query.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if query(get_process(), ctypes.byref(counters), counters.cb):
            return counters.WorkingSetSize / 1024**2
    elif sys.platform == "linux":
        resident_pages = int(Path("/proc/self/statm").read_text().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE") / 1024**2
    return None


def summarize_durations(durations):
    if not durations:
        return {}
    return {
        "mean_ms": statistics.mean(durations),
        "median_ms": statistics.median(durations),
        "p95_ms": float(np.percentile(durations, 95)),
        "samples": len(durations),
    }
