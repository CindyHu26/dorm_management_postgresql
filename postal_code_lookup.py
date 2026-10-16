import json
import re
from functools import lru_cache
from pathlib import Path


POSTAL_CODE_DATA_PATH = (
    Path(__file__).resolve().parent / "resources" / "postal_code3_tw_source.json"
)


def _normalize_address(value):
    text = re.sub(r"\s+", "", str(value or "")).replace("台", "臺")
    return text or None


@lru_cache(maxsize=1)
def _postal_code_index():
    """Load the bundled government data once and build address lookup indexes."""
    with POSTAL_CODE_DATA_PATH.open("r", encoding="utf-8") as source:
        data = json.load(source)

    full_matches = []
    district_codes = {}
    for concept in data.get("concept", []):
        postal_code = str(concept.get("code") or "").strip()
        display = _normalize_address(concept.get("display"))
        properties = {
            item.get("code"): item.get("valueString")
            for item in concept.get("property", [])
        }
        district = _normalize_address(properties.get("city"))
        if not postal_code or not display:
            continue
        full_matches.append((display, postal_code))
        if district:
            district_codes.setdefault(district, set()).add(postal_code)

    full_matches.sort(key=lambda item: len(item[0]), reverse=True)
    unique_districts = {
        district: next(iter(codes))
        for district, codes in district_codes.items()
        if len(codes) == 1
    }
    return full_matches, unique_districts


def infer_postal_code(address):
    """Infer an administrative-area 3-digit postal code without persisting it."""
    normalized = _normalize_address(address)
    if not normalized:
        return None

    full_matches, unique_districts = _postal_code_index()
    for administrative_area, postal_code in full_matches:
        if administrative_area in normalized:
            return postal_code

    district_matches = [
        (district, postal_code)
        for district, postal_code in unique_districts.items()
        if district in normalized
    ]
    if not district_matches:
        return None
    district_matches.sort(key=lambda item: len(item[0]), reverse=True)
    return district_matches[0][1]
