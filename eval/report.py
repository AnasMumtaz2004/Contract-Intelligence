import json
from pathlib import Path

EVAL_FOLDER = Path(__file__).resolve().parent
RESULTS_FOLDER = EVAL_FOLDER / "results"
REPORT_FILE = RESULTS_FOLDER / "report.md"

PIPELINE_NAMES = ["naive", "hybrid"]
ANSWERABLE_LEVELS = [1, 2]
MISSING_LEVEL = 7


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


def find_score(scores: dict, word: str):
    """Find a Ragas score by a word in its name, like 'faithfulness'."""
    for name, value in scores.items():
        if word in name:
            return value
    return None


def build_answerable_table(results_by_pipeline: dict, scores_by_pipeline: dict) -> list[str]:
    """Build the table for questions that have an answer in the contract."""
    lines = []
    lines.append("## Questions that have an answer (levels 1 and 2)")
    lines.append("")
    lines.append("| Pipeline | Level | Questions | Context hit | Answered | Faithfulness | Relevancy | Ctx precision | Ctx recall |")
    lines.append("|---|---|---|---|---|---|---|---|---|")

    for pipeline_name in PIPELINE_NAMES:
        results = results_by_pipeline[pipeline_name]
        scores_list = scores_by_pipeline[pipeline_name]

        scores_by_id = {}
        for entry in scores_list:
            scores_by_id[entry["id"]] = entry["scores"]

        for level in ANSWERABLE_LEVELS:
            items = []
            for item in results:
                if item["level"] == level:
                    items.append(item)
            if len(items) == 0:
                continue

            hit_values = []
            answered_values = []
            ragas_values = {"faithfulness": [], "relevancy": [], "precision": [], "recall": []}

            for item in items:
                hit_values.append(1.0 if item["context_hit"] else 0.0)
                answered_values.append(1.0 if item["status"] == "found" else 0.0)

                scores = scores_by_id.get(item["id"])
                if scores is None:
                    continue
                for word in ragas_values:
                    value = find_score(scores, word)
                    if value is not None:
                        ragas_values[word].append(value)

            row = "| " + pipeline_name + " | " + str(level) + " | " + str(len(items))
            row += " | " + format_number(average(hit_values))
            row += " | " + format_number(average(answered_values))
            row += " | " + format_number(average(ragas_values["faithfulness"]))
            row += " | " + format_number(average(ragas_values["relevancy"]))
            row += " | " + format_number(average(ragas_values["precision"]))
            row += " | " + format_number(average(ragas_values["recall"]))
            row += " |"
            lines.append(row)

    return lines


def build_missing_table(results_by_pipeline: dict) -> list[str]:
    """Build the table for questions whose clause is not in the contract."""
    lines = []
    lines.append("## Questions with no answer in the contract (level 7)")
    lines.append("")
    lines.append("| Pipeline | Questions | Correctly said not found |")
    lines.append("|---|---|---|")

    for pipeline_name in PIPELINE_NAMES:
        items = []
        for item in results_by_pipeline[pipeline_name]:
            if item["level"] == MISSING_LEVEL:
                items.append(item)
        if len(items) == 0:
            continue

        correct_values = []
        for item in items:
            correct_values.append(1.0 if item["status"] == "not_found" else 0.0)

        row = "| " + pipeline_name + " | " + str(len(items))
        row += " | " + format_number(average(correct_values)) + " |"
        lines.append(row)

    return lines


def main() -> None:
    """Print the comparison tables and save them to results/report.md."""
    results_by_pipeline = {}
    scores_by_pipeline = {}
    for pipeline_name in PIPELINE_NAMES:
        results_by_pipeline[pipeline_name] = load_json(RESULTS_FOLDER / ("answers_" + pipeline_name + ".json"))
        scores_by_pipeline[pipeline_name] = load_json(RESULTS_FOLDER / ("scores_" + pipeline_name + ".json"))

    lines = []
    lines.extend(build_answerable_table(results_by_pipeline, scores_by_pipeline))
    lines.append("")
    lines.extend(build_missing_table(results_by_pipeline))
    lines.append("")
    lines.append("Context hit = share of questions where the retrieved chunks contain the expected clause.")
    lines.append("Answered = share of answerable questions where the model gave an answer instead of not found.")
    lines.append("Ragas scores only cover answers that were actually given.")

    text = "\n".join(lines)
    print(text)
    REPORT_FILE.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()