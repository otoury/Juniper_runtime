def is_simple_standalone(text: str) -> bool:
    clean = text.strip()

    if not clean:
        return False

    if len(clean) > 300:
        return False

    if "\n" in clean:
        return False

    # Short messages are often follow-ups in any language.
    if len(clean) < 35:
        return False

    # Medium-short without enough content is also suspicious.
    if len(clean.split()) < 6:
        return False

    return True
