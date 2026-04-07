"""Feedback extraction from user messages for reward-oriented data collection."""

from __future__ import annotations

from typing import Any

_POSITIVE_MARKERS = (
    "thanks",
    "thank you",
    "great",
    "good",
    "nice",
    "perfect",
    "谢谢",
    "很好",
    "不错",
    "可以",
    "正是",
    "对的",
)

_NEGATIVE_MARKERS = (
    "wrong",
    "bad",
    "not helpful",
    "stop",
    "don't",
    "不对",
    "不是",
    "不行",
    "错了",
    "没用",
    "不要",
)

_CORRECTION_MARKERS = (
    "actually",
    "i mean",
    "instead",
    "我的意思",
    "不是这个",
    "应该是",
    "我想要的是",
)

_PREFERENCE_MARKERS = (
    "i like",
    "prefer",
    "usually",
    "我喜欢",
    "更喜欢",
    "偏好",
    "习惯",
    "常用",
)

_URGENCY_MARKERS = (
    "now",
    "today",
    "asap",
    "urgent",
    "现在",
    "今天",
    "马上",
    "尽快",
)

_FRUSTRATION_MARKERS = (
    "too slow",
    "again",
    "annoying",
    "烦",
    "太慢",
    "怎么又",
)


class FeedbackExtractor:
    """Extract simple reward-relevant feedback signals from the incoming user text."""

    @staticmethod
    def _match_markers(text: str, markers: tuple[str, ...]) -> list[str]:
        return [marker for marker in markers if marker in text]

    def extract(self, content: str) -> dict[str, Any]:
        text = (content or "").lower()
        positives = self._match_markers(text, _POSITIVE_MARKERS)
        negatives = self._match_markers(text, _NEGATIVE_MARKERS)
        corrections = self._match_markers(text, _CORRECTION_MARKERS)
        preferences = self._match_markers(text, _PREFERENCE_MARKERS)
        urgency = self._match_markers(text, _URGENCY_MARKERS)
        frustration = self._match_markers(text, _FRUSTRATION_MARKERS)

        return {
            "explicit_positive": bool(positives) and not bool(negatives),
            "explicit_negative": bool(negatives),
            "correction_signal": bool(corrections),
            "preference_signal": bool(preferences),
            "urgency_signal": bool(urgency),
            "frustration_signal": bool(frustration),
            "matched_markers": {
                "positive": positives,
                "negative": negatives,
                "correction": corrections,
                "preference": preferences,
                "urgency": urgency,
                "frustration": frustration,
            },
        }
