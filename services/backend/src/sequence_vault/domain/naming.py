"""Project-scoped record name keys (design section 7)."""


def name_key(display_name: str) -> str:
    """Trim and case-fold; the original spelling is kept separately for display."""
    key = display_name.strip().casefold()
    if not key:
        raise ValueError("A record name cannot be blank.")
    return key
