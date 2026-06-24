from __future__ import annotations

import re


class Redactor:
    def __init__(self, patterns: list[re.Pattern[str]]) -> None:
        self._patterns = patterns

    def redact_lines(self, lines: list[str]) -> list[str]:
        redacted: list[str] = []
        for line in lines:
            for pattern in self._patterns:
                line = pattern.sub("[REDACTED]", line)
            redacted.append(line)
        return redacted
