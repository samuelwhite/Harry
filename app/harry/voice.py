import random
from datetime import datetime

OK_LINES = [
    "All systems nominal.",
    "Everything looks stable.",
    "Nothing concerning detected.",
    "Quiet is good.",
    "Infrastructure behaving itself.",
    "No surprises today.",
    "All nodes reporting in.",
    "The fleet is calm.",
    "Metrics within expected bounds.",
    "Boring. Excellent.",
]

WARN_LINES = [
    "Something needs attention.",
    "There’s a ripple in the matrix.",
    "Not catastrophic. Yet.",
    "A small wobble detected.",
]

BAD_LINES = [
    "Immediate attention recommended.",
    "This may end badly.",
    "That’s… not ideal.",
    "Intervention advised.",
]


def line_for_status(status: str) -> str:
    """
    status: ok | warn | bad
    """
    if status == "bad":
        pool = BAD_LINES
    elif status == "warn":
        pool = WARN_LINES
    else:
        pool = OK_LINES

    return random.choice(pool)
