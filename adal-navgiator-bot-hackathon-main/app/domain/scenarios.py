import re
from typing import Literal

Category = Literal[
    "garbage",
    "lighting",
    "heating",
    "water",
    "roads",
    "playground",
    "snow",
    "appeals",
    "principles",
    "general",
]

SUPPORTED_CITIES = {"алматы", "almaty", "алма-ата", "alma-ata"}


def is_almaty(city: str | None) -> bool:
    if not city:
        return False
    value = city.strip().casefold()
    value = re.sub(r"^(?:в|из)\s+(?:городе\s+)?", "", value)
    value = re.sub(r"^(?:г\.?|город|қала(?:сы)?)\s+", "", value)
    value = value.rstrip(" .!")
    if value in SUPPORTED_CITIES:
        return True
    return bool(re.fullmatch(r"(?:алматы|almaty|алма-ата|alma-ata),\s*(?:казахстан|қазақстан)", value))
