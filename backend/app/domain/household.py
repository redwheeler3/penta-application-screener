"""Public household requirements for an opening and its initial committee rules."""


def default_child_limits(bedrooms: int) -> tuple[int, int | None]:
    return bedrooms - 1, 0 if bedrooms == 1 else None


def household_description(minimum: int | None, maximum: int | None) -> str:
    adults = "One or two adults"
    if maximum == 0:
        return f"{adults} and no children"
    if not minimum and maximum is None:
        return f"{adults}, with or without children"
    if minimum == maximum:
        count = f"{minimum} " + ("child" if minimum == 1 else "children")
    elif maximum is None:
        count = {1: "at least one child", 2: "at least two children"}.get(minimum, f"at least {minimum} children")
    elif not minimum:
        count = f"up to {maximum} " + ("child" if maximum == 1 else "children")
    else:
        count = f"{minimum} to {maximum} children"
    return f"{adults} plus {count} under 18"
