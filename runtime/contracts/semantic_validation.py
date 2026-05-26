META_FAILURE_PATTERNS = [

    "script created",
    "email drafted",
    "note created",
    "template created",
    "response generated",
    "draft completed",

]


def looks_like_meta_response(text: str) -> bool:
    lower = text.lower()

    for pattern in META_FAILURE_PATTERNS:
        if pattern in lower:
            return True

    return False
