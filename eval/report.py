import json
from pathlib import Path

EVAL_FOLDER = Path(__file__).resolve().parent
RESULTS_FOLDER = EVAL_FOLDER / "results"
REPORT_FILE = RESULTS_FOLDER / "report.md"

# The order in which pipelines appear in the tables
PIPELINE_ORDER = ["naive", "hybrid", "hybrid_rerank", "hybrid_rerank_xref", "agentic"]
MISSING_LEVEL = 7
# Scanned copies are loaded under the vendor name of the original plus this ending
SCANNED_ENDING = " Scan"


def load_json(path: Path) -> list:
    """Read a JSON file, or return an empty list if it does not exist."""
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def average(values: list):
    """Average the numbers in a list. Returns None if the list is empty."""
    if len(values) == 0:
        return None
    return sum(values) / len(values)


def format_number(value) -> str:
    """Show a number with two decimals, or a dash if there is no value."""
    if value is None:
        return "-"
    return "{:.2f}".format(value)


def to_number(flag: bool) -> float:
    """Turn True or False into 1.0 or 0.0, so it can be averaged."""
    if flag:
        return 1.0
    return 0.0


def find_score(scores: dict, word: str):
    """Find a Ragas score by a word in its name, like 'faithfulness'."""
    for name, value in scores.items():
        if word in name:
            return value
    return None


def is_scanned(item: dict) -> bool:
    """Check if a question belongs to a scanned copy of a contract."""
    return item["vendor_name"].endswith(SCANNED_ENDING)


def find_pipeline_names() -> list[str]:
    """Find the pipelines that have saved answers."""
    names = []
    for name in PIPELINE_ORDER:
        if (RESULTS_FOLDER / ("answers_" + name + ".json")).exists():
            names.append(name)
    return names


def summarize(items: list[dict], scores_by_id: dict) -> dict:
    """Average the free metrics and the Ragas scores of a group of questions."""
    hit_values = []
    answered_values = []
    ragas_values = {"faithfulness": [], "relevancy": [], "precision": [], "recall": []}

    for item in items:
        hit_values.append(to_number(item["context_hit"]))
        answered_values.append(to_number(item["status"] == "found"))

        scores = scores_by_id.get(item["id"])
        if scores is None:
            continue
        for word in ragas_values:
            value = find_score(scores, word)
            if value is not None:
                ragas_values[word].append(value)

    summary = {"count": len(items), "hit": average(hit_values), "answered": average(answered_values)}
    for word in ragas_values:
        summary[word] = average(ragas_values[word])
    return summary


def build_answerable_table(pipeline_names: list[str], results: dict, scores: dict) -> list[str]:
    """Table for digital questions that have an answer in the contract (levels 1 to 6)."""
    lines = []
    lines.append("## Questions that have an answer (digital contracts)")
    lines.append("")
    lines.append("| Pipeline | Level | Questions | Context hit | Answered | Faithfulness | Relevancy | Ctx precision | Ctx recall |")
    lines.append("|---|---|---|---|---|---|---|---|---|")

    levels = set()
    for name in pipeline_names:
        for item in results[name]:
            if item["level"] != MISSING_LEVEL and not is_scanned(item):
                levels.add(item["level"])

    for level in sorted(levels):
        for name in pipeline_names:
            items = []
            for item in results[name]:
                if item["level"] == level and not is_scanned(item):
                    items.append(item)
            if len(items) == 0:
                continue

            summary = summarize(items, scores[name])
            row = "| " + name + " | " + str(level) + " | " + str(summary["count"])
            row += " | " + format_number(summary["hit"])
            row += " | " + format_number(summary["answered"])
            row += " | " + format_number(summary["faithfulness"])
            row += " | " + format_number(summary["relevancy"])
            row += " | " + format_number(summary["precision"])
            row += " | " + format_number(summary["recall"]) + " |"
            lines.append(row)

    return lines


def build_amendment_table(pipeline_names: list[str], results: dict) -> list[str]:
    """Table for the amendment questions (level 5): did the answer give the current value?"""
    lines = []
    lines.append("## Amendment questions (level 5, only the ones where an amendment changed the answer)")
    lines.append("")
    lines.append("| Pipeline | Questions | Amendment retrieved | Answer states the current value |")
    lines.append("|---|---|---|---|")

    for name in pipeline_names:
        retrieved_values = []
        mention_values = []
        for item in results[name]:
            if item["level"] != 5 or item.get("mention_hit") is None:
                continue
            retrieved_values.append(to_number(item["amendment_retrieved"]))
            mention_values.append(to_number(item["mention_hit"]))

        if len(mention_values) == 0:
            continue
        row = "| " + name + " | " + str(len(mention_values))
        row += " | " + format_number(average(retrieved_values))
        row += " | " + format_number(average(mention_values)) + " |"
        lines.append(row)

    return lines


def build_missing_table(pipeline_names: list[str], results: dict) -> list[str]:
    """Table for questions whose clause is not in the contract (level 7)."""
    lines = []
    lines.append("## Questions with no answer in the contract (level 7)")
    lines.append("")
    lines.append("| Pipeline | Questions | Correctly said not found |")
    lines.append("|---|---|---|")

    for name in pipeline_names:
        values = []
        for item in results[name]:
            if item["level"] == MISSING_LEVEL and not is_scanned(item):
                values.append(to_number(item["status"] == "not_found"))
        if len(values) == 0:
            continue
        lines.append("| " + name + " | " + str(len(values)) + " | " + format_number(average(values)) + " |")

    return lines


def build_scanned_table(pipeline_names: list[str], results: dict) -> list[str]:
    """Table for the scanned copies. Compare it with the digital rows above."""
    lines = []
    lines.append("## Scanned copies (OCR)")
    lines.append("")
    lines.append("| Pipeline | Questions (levels 1-2) | Context hit | Answered | Questions (level 7) | Correctly said not found |")
    lines.append("|---|---|---|---|---|---|")

    for name in pipeline_names:
        hit_values = []
        answered_values = []
        missing_values = []
        for item in results[name]:
            if not is_scanned(item):
                continue
            if item["level"] == MISSING_LEVEL:
                missing_values.append(to_number(item["status"] == "not_found"))
            else:
                hit_values.append(to_number(item["context_hit"]))
                answered_values.append(to_number(item["status"] == "found"))

        if len(hit_values) == 0 and len(missing_values) == 0:
            continue
        row = "| " + name + " | " + str(len(hit_values))
        row += " | " + format_number(average(hit_values))
        row += " | " + format_number(average(answered_values))
        row += " | " + str(len(missing_values))
        row += " | " + format_number(average(missing_values)) + " |"
        lines.append(row)

    return lines

def load_retrieval() -> dict:
    """Load the retrieval-only results of every pipeline that has them."""
    retrieval = {}
    for name in PIPELINE_ORDER:
        path = RESULTS_FOLDER / ("retrieval_" + name + ".json")
        if path.exists():
            retrieval[name] = load_json(path)
    return retrieval


def make_retrieval_row(name: str, group: str, items: list[dict]) -> str:
    """Write one table row: how often the right clause (and the amendment) reached the model."""
    hit_values = []
    amendment_values = []
    for item in items:
        hit_values.append(to_number(item["context_hit"]))
        if item["amendment_retrieved"] is not None:
            amendment_values.append(to_number(item["amendment_retrieved"]))

    row = "| " + name + " | " + group + " | " + str(len(items))
    row += " | " + format_number(average(hit_values))
    row += " | " + format_number(average(amendment_values)) + " |"
    return row


def build_retrieval_table(retrieval: dict) -> list[str]:
    """Table for retrieval only. It needs no LLM, so it covers every question."""
    lines = []
    lines.append("## Retrieval only (no LLM): did the right clause reach the model?")
    lines.append("")
    lines.append("| Pipeline | Group | Questions | Context hit | Amendment retrieved |")
    lines.append("|---|---|---|---|---|")

    names = []
    for name in PIPELINE_ORDER:
        if name in retrieval:
            names.append(name)

    levels = set()
    for name in names:
        for item in retrieval[name]:
            if item["answerable"] and not is_scanned(item):
                levels.add(item["level"])

    for level in sorted(levels):
        for name in names:
            items = []
            for item in retrieval[name]:
                if item["answerable"] and not is_scanned(item) and item["level"] == level:
                    items.append(item)
            if len(items) > 0:
                lines.append(make_retrieval_row(name, "level " + str(level), items))

    for name in names:
        scanned_items = []
        for item in retrieval[name]:
            if item["answerable"] and is_scanned(item):
                scanned_items.append(item)
        if len(scanned_items) > 0:
            lines.append(make_retrieval_row(name, "scanned copies", scanned_items))

    return lines


def main() -> None:
    """Print the comparison tables and save them to results/report.md."""
    retrieval = load_retrieval()
    pipeline_names = find_pipeline_names()
    if len(retrieval) == 0 and len(pipeline_names) == 0:
        print("No saved results found. Run run_retrieval.py or run_ragas.py first.")
        return

    lines = []

    if len(retrieval) > 0:
        lines.extend(build_retrieval_table(retrieval))
        lines.append("")

    if len(pipeline_names) > 0:
        results = {}
        scores = {}
        for name in pipeline_names:
            results[name] = load_json(RESULTS_FOLDER / ("answers_" + name + ".json"))
            scores[name] = {}
            for entry in load_json(RESULTS_FOLDER / ("scores_" + name + ".json")):
                scores[name][entry["id"]] = entry["scores"]

        lines.extend(build_answerable_table(pipeline_names, results, scores))
        lines.append("")
        lines.extend(build_amendment_table(pipeline_names, results))
        lines.append("")
        lines.extend(build_missing_table(pipeline_names, results))
        lines.append("")
        lines.extend(build_scanned_table(pipeline_names, results))
        lines.append("")

    lines.append("Context hit = share of questions where the retrieved chunks contain the expected clause.")
    lines.append("Answered = share of answerable questions where the model gave an answer instead of not found.")
    lines.append("Amendment retrieved / current value are free checks from the amendment manifest, no LLM judge.")
    lines.append("Ragas scores only cover answers that were actually given.")

    text = "\n".join(lines)
    print(text)
    REPORT_FILE.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()