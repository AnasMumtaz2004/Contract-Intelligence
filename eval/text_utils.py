import json
import re

# Number of neighbouring words in one "shingle"
SHINGLE_SIZE = 4


def get_shingles(text: str) -> set:
    """Split a text into overlapping groups of neighbouring words."""
    words = re.findall(r"[a-z0-9]+", text.lower())

    shingles = set()
    for start in range(0, len(words) - SHINGLE_SIZE + 1):
        shingle = " ".join(words[start : start + SHINGLE_SIZE])
        shingles.add(shingle)
    return shingles


def overlap_share(small_text: str, big_text: str) -> float:
    """Return the share of the small text's word groups that also appear in the big text."""
    small_shingles = get_shingles(small_text)
    if len(small_shingles) == 0:
        return 0.0

    big_shingles = get_shingles(big_text)
    shared = small_shingles & big_shingles
    return len(shared) / len(small_shingles)


def clean_file_name(text: str) -> str:
    """Make a safe, short piece of a file name from any text."""
    text = re.sub(r"[^a-z0-9]+", "_", text.lower())
    text = text.strip("_")
    return text[:40]


def load_cuad_by_title(json_path: str) -> dict:
    """Read CUAD_v1.json and return {contract title: contract}."""
    with open(json_path, encoding="utf-8") as file:
        cuad = json.load(file)

    contracts_by_title = {}
    for contract in cuad["data"]:
        contracts_by_title[contract["title"]] = contract
    return contracts_by_title