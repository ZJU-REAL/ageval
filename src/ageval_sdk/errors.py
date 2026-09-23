"""Script failures an author raises when the script itself cannot continue.

The worker that catches this writes ``title`` and ``message`` onto the result
envelope. The parent stores that document. It does not import the dataset.
"""

from __future__ import annotations


class ScriptError(Exception):
    """A stable title plus the text for this occurrence.

    Raise the same class from ``run.py`` and from ``evaluator.py``. The phase
    is whichever worker caught it. ``title`` stays the same on every
    occurrence; variable detail goes in ``message``.
    """

    def __init__(self, title: str, message: str) -> None:
        if not isinstance(title, str) or not title.strip():
            raise ValueError("ScriptError title must be a non-empty string")
        if not isinstance(message, str):
            raise TypeError("ScriptError message must be a string")
        super().__init__(message)
        self.title = title
        self.message = message
