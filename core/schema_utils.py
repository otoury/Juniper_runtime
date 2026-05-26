from dataclasses import fields


def validate_dataclass_schema(
    dc_type,
    data: dict,
):
    """
    Filters unknown keys and constructs dataclass safely.
    """

    valid = {}

    for f in fields(dc_type):
        if f.name in data:
            valid[f.name] = data[f.name]

    return dc_type(**valid)