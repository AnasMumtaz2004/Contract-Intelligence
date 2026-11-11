import re
import unicodedata

import pymupdf

# The injection tests turn this off to measure what the defenses add. Never change it in real use.
DEFENSES_ENABLED = True

# The text that replaces an instruction-like sentence
REDACTION_MARKER = "[removed: instruction-like text]"

# Findings keep only the start of the text
MAX_SNIPPET_CHARS = 300

# Hidden text shorter than this is ignored (stray marks, page labels)
MIN_HIDDEN_CHARS = 8
# Text smaller than this (in points) cannot be read by a person
TINY_FONT_SIZE = 3.0
# A colour channel at or above this value (0 to 255) counts as white
NEAR_WHITE = 245

# PDF properties that can hold text
METADATA_FIELDS = ["title", "author", "subject", "keywords", "creator", "producer"]

# Tags that our prompts use to mark where contract text starts and ends
DELIMITER_PATTERN = re.compile(r"</?\s*(?:context|excerpt|sources?|answer|instructions?|system)\b[^>]*>", re.IGNORECASE)

# Each rule is (name, severity, pattern). A "high" rule blocks the document. A "medium" rule removes the sentence.
# The rules are written for text aimed at an AI. Normal contract wording must not match them.
RULE_PATTERNS = [
    (
        "ignore_previous",
        "high",
        r"\b(?:ignore|disregard|forget|override|bypass)\b[^.\n]{0,30}\b(?:previous|prior|above|earlier|preceding)\b"
        r"[^.\n]{0,20}\b(?:instructions?|prompts?|rules|directions?|guidelines?|context|messages?)\b",
    ),
    (
        "ignore_your_rules",
        "high",
        r"\b(?:ignore|disregard|forget|override|bypass)\b[^.\n]{0,20}\b(?:your|the\s+system|safety|ethical)\b"
        r"[^.\n]{0,20}\b(?:instructions?|rules|guidelines?|prompts?|programming|restrictions?)\b",
    ),
    (
        "new_instructions",
        "medium",
        r"\b(?:new|updated|revised|additional)\s+(?:system\s+)?instructions?\s*:",
    ),
    (
        "system_prompt",
        "high",
        r"\b(?:system\s+prompt|developer\s+(?:message|instructions?)|hidden\s+instructions?)\b",
    ),
    (
        "role_change",
        "high",
        r"\byou\s+are\s+(?:now\s+|no\s+longer\s+)?(?:an?\s+|the\s+)?"
        r"(?:ai|assistant|chatbot|language\s+model|unrestricted|jailbroken|dan)\b",
    ),
    (
        "note_to_ai",
        "high",
        r"\b(?:notes?|messages?|attention|attn)\s*:?\s*(?:to|for)?\s*(?:the\s+|all\s+|any\s+)?"
        r"(?:ai|a\.i\.|llms?|language\s+models?|chatbots?|ai\s+assistants?|automated\s+(?:systems?|reviewers?|tools?))\b",
    ),
    (
        "ai_review_directive",
        "high",
        r"\b(?:ai|a\.i\.|llms?|language\s+models?|chatbots?|ai\s+assistants?|automated\s+(?:systems?|reviewers?|tools?))\b"
        r"[^.\n]{0,40}\b(?:reviewing|reading|analy[sz]ing|summari[sz]ing|processing|parsing|evaluating|scanning)\b"
        r"[^.\n]{0,40}\b(?:this|the)\s+(?:document|contract|agreement|file|text)\b"
        r"[^.\n]{0,60}\b(?:must|should|shall|will|always|never|needs?\s+to|has\s+to|have\s+to|is\s+required|are\s+required)\b",
    ),
    (
        "hide_from_user",
        "high",
        r"\b(?:do\s+not|don[’']?t|never)\s+(?:mention|reveal|disclose|tell|report|flag|show|inform)\b"
        r"[^.\n]{0,40}\b(?:the\s+)?(?:user|reviewer|human|reader|operator)\b",
    ),
    (
        "reveal_prompt",
        "high",
        r"\b(?:reveal|print|repeat|show|output|display)\b[^.\n]{0,30}\byour\s+(?:system\s+)?(?:prompt|instructions)\b",
    ),
    (
        "force_conclusion",
        "medium",
        r"\b(?:state|report|say|respond|reply|answer|conclude|declare|tell|mark|label|rate|classify|summari[sz]e)\b"
        r"[^.\n]{0,60}\b(?:no\s+(?:liability|risks?|exposure|issues?|concerns?)"
        r"|all\s+clauses?\s+(?:(?:are|as)\s+)?(?:compliant|acceptable|safe|approved)|fully\s+compliant|risk[\s-]free)\b",
    ),
]

# The rules with their patterns compiled, ready to use
COMPILED_RULES = []
for _rule, _severity, _pattern in RULE_PATTERNS:
    COMPILED_RULES.append((_rule, _severity, re.compile(_pattern, re.IGNORECASE)))

# A readable name for each rule, used in messages to the user
RULE_LABELS = {
    "ignore_previous": "an instruction to ignore earlier instructions",
    "ignore_your_rules": "an instruction to ignore the assistant's rules",
    "new_instructions": "text that gives new instructions",
    "system_prompt": "a mention of the system prompt",
    "role_change": "text that tries to change the assistant's role",
    "note_to_ai": "a note addressed to an AI",
    "ai_review_directive": "an order addressed to an AI that reviews the document",
    "hide_from_user": "an order to hide information from the user",
    "reveal_prompt": "an order to reveal the assistant's instructions",
    "force_conclusion": "text that dictates the conclusion of a review",
    "hidden_text": "hidden text",
}


def remove_format_characters(text: str) -> str:
    """Remove invisible format characters, like zero-width spaces, that can hide a word."""
    kept = []
    for character in text:
        if unicodedata.category(character) == "Cf":
            continue
        kept.append(character)
    return "".join(kept)


def flatten(text: str) -> str:
    """Make a text easy to scan: look-alike letters become normal, invisible characters go, whitespace is one space."""
    # NFKC turns wide letters like "ｉｇｎｏｒｅ" into normal ones
    text = unicodedata.normalize("NFKC", text)
    text = remove_format_characters(text)
    return " ".join(text.split())


def find_sentence(flat: str, start: int, end: int) -> tuple:
    """Find the start and end of the sentence that contains the given span."""
    sentence_start = 0
    for mark in (". ", "? ", "! "):
        position = flat.rfind(mark, 0, start)
        if position != -1 and position + 2 > sentence_start:
            sentence_start = position + 2

    sentence_end = len(flat)
    for mark in (". ", "? ", "! "):
        position = flat.find(mark, end)
        if position != -1 and position + 1 < sentence_end:
            sentence_end = position + 1

    return sentence_start, sentence_end


def find_injection_in_flat(flat: str) -> list[dict]:
    """Find the instruction-like sentences in an already flattened text."""
    matches = []
    for rule, severity, pattern in COMPILED_RULES:
        for match in pattern.finditer(flat):
            sentence_start, sentence_end = find_sentence(flat, match.start(), match.end())
            matches.append(
                {
                    "rule": rule,
                    "severity": severity,
                    "start": sentence_start,
                    "end": sentence_end,
                    "snippet": flat[sentence_start:sentence_end],
                }
            )

    matches.sort(key=lambda item: item["start"])
    return matches


def find_injection(text: str) -> list[dict]:
    """Find the instruction-like sentences in a text. A sentence that wraps over several lines is found too."""
    return find_injection_in_flat(flatten(text))


def redact_injection(text: str) -> tuple:
    """Replace instruction-like sentences with a marker. Returns the new text and how many were replaced."""
    if not DEFENSES_ENABLED:
        return text, 0

    flat = flatten(text)
    matches = find_injection_in_flat(flat)
    if len(matches) == 0:
        # Nothing found, so the text keeps its original line breaks
        return text, 0

    # Merge sentences that overlap, so no text is cut twice
    spans = []
    for match in matches:
        if len(spans) > 0 and match["start"] <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], match["end"])
        else:
            spans.append([match["start"], match["end"]])

    # We cut from the end, so the earlier positions stay correct
    result = flat
    for start, end in reversed(spans):
        result = result[:start] + REDACTION_MARKER + result[end:]
    return result, len(spans)


def clean_for_prompt(text: str) -> str:
    """Make contract text safe for a prompt: no hidden characters, no fake tags, no instruction-like sentences."""
    if not DEFENSES_ENABLED:
        return text

    text = remove_format_characters(text)
    text = DELIMITER_PATTERN.sub("", text)
    cleaned, _count = redact_injection(text)
    return cleaned


def count_flagged_chunks(chunks: list[dict]) -> int:
    """Count the chunks that hold instruction-like text, or that were cleaned when the document was loaded."""
    if not DEFENSES_ENABLED:
        return 0

    count = 0
    for chunk in chunks:
        content = chunk["content"]
        if REDACTION_MARKER in content or len(find_injection(content)) > 0:
            count += 1
    return count


def redact_chunks(chunks: list[dict]) -> int:
    """Clean the instruction-like sentences out of chunks before they are saved. Returns how many were removed."""
    removed = 0
    for chunk in chunks:
        new_text, count = redact_injection(chunk["content"])
        if count > 0:
            chunk["content"] = new_text
            removed += count
    return removed


def make_finding(kind: str, rule: str, severity: str, page, snippet: str) -> dict:
    """Make one finding of the scan."""
    return {
        "kind": kind,
        "rule": rule,
        "severity": severity,
        "page": page,
        "snippet": snippet[:MAX_SNIPPET_CHARS],
        "action": "",
    }


def is_near_white_color(color: int) -> bool:
    """Check if a PDF text colour (a whole number) is white or almost white."""
    red = (color >> 16) & 255
    green = (color >> 8) & 255
    blue = color & 255
    return red >= NEAR_WHITE and green >= NEAR_WHITE and blue >= NEAR_WHITE


def is_light_fill(fill) -> bool:
    """Check if a fill colour (values from 0 to 1) is white or almost white."""
    for value in fill:
        if value * 255 < NEAR_WHITE:
            return False
    return True


def get_dark_boxes(page) -> list:
    """Find the coloured shapes on a page. White text on them (a table header, for example) can be read."""
    boxes = []

    # Drawing data can be odd in some PDFs, and then we simply find no shapes
    try:
        drawings = page.get_drawings()
    except Exception:
        return boxes

    for drawing in drawings:
        fill = drawing.get("fill")
        if fill is None or is_light_fill(fill):
            continue
        boxes.append(pymupdf.Rect(drawing["rect"]))
    return boxes


def get_hidden_reason(span: dict, dark_boxes: list) -> str:
    """Return why a piece of text is hidden from readers, or an empty text if it is readable."""
    if span.get("size", 12) < TINY_FONT_SIZE:
        return "tiny font"

    if is_near_white_color(span.get("color", 0)):
        span_box = pymupdf.Rect(span["bbox"])
        for box in dark_boxes:
            if box.contains(span_box):
                return ""
        return "white text"

    return ""


def find_hidden_text(file_path: str) -> list[dict]:
    """Find text that people cannot see: white text and tiny text."""
    hidden_spans = []
    pdf = pymupdf.open(file_path)

    for page_index in range(len(pdf)):
        page = pdf[page_index]
        dark_boxes = get_dark_boxes(page)

        for block in page.get_text("dict")["blocks"]:
            # Block type 0 is text. Other types are pictures.
            if block.get("type") != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"].strip()
                    if len(text) < MIN_HIDDEN_CHARS:
                        continue
                    reason = get_hidden_reason(span, dark_boxes)
                    if reason != "":
                        hidden_spans.append({"page": page_index + 1, "text": text, "reason": reason})

    pdf.close()
    return hidden_spans


def scan_hidden_spans(hidden_spans: list[dict]) -> list[dict]:
    """Turn the hidden text into findings. Hidden text that looks like an instruction is a high finding."""
    texts_by_page = {}
    for span in hidden_spans:
        if span["page"] not in texts_by_page:
            texts_by_page[span["page"]] = []
        texts_by_page[span["page"]].append(span["text"])

    findings = []
    for page_number, texts in texts_by_page.items():
        # All hidden text of a page is read together, because a sentence can wrap over lines
        joined = " ".join(texts)
        matches = find_injection(joined)

        if len(matches) == 0:
            findings.append(make_finding("hidden_text", "hidden_text", "medium", page_number, joined))
        for match in matches:
            findings.append(make_finding("hidden_text", match["rule"], match["severity"], page_number, match["snippet"]))

    return findings


def remove_hidden_text(pages: list[dict], hidden_spans: list[dict]) -> list[dict]:
    """Take the hidden text out of the parsed pages, so it is never indexed."""
    texts_by_page = {}
    for span in hidden_spans:
        if span["page"] not in texts_by_page:
            texts_by_page[span["page"]] = []
        texts_by_page[span["page"]].append(span["text"])

    cleaned_pages = []
    for page in pages:
        hidden_texts = texts_by_page.get(page["page_number"], [])

        lines = []
        for line in page["lines"]:
            for hidden_text in hidden_texts:
                line = line.replace(hidden_text, "")
            line = line.strip()
            if line != "":
                lines.append(line)

        cleaned_pages.append({"page_number": page["page_number"], "lines": lines})
    return cleaned_pages


def scan_pages(pages: list[dict]) -> list[dict]:
    """Look for instruction-like text in the visible text of every page."""
    findings = []
    for page in pages:
        # The lines of a page are joined, so a sentence that wraps over lines is still found
        page_text = " ".join(page["lines"])
        for match in find_injection(page_text):
            findings.append(
                make_finding("injection_text", match["rule"], match["severity"], page["page_number"], match["snippet"])
            )
    return findings


def scan_metadata(file_path: str) -> list[dict]:
    """Look for instruction-like text in the properties of the PDF (title, subject, keywords)."""
    pdf = pymupdf.open(file_path)
    metadata = pdf.metadata or {}
    pdf.close()

    findings = []
    for field in METADATA_FIELDS:
        value = metadata.get(field) or ""
        for match in find_injection(value):
            findings.append(make_finding("metadata", match["rule"], match["severity"], None, match["snippet"]))
    return findings


def decide_action(finding: dict, quarantine: bool) -> str:
    """Decide what happens because of a finding."""
    if quarantine:
        return "quarantined"
    if finding["kind"] == "hidden_text":
        return "removed"
    if finding["kind"] == "metadata":
        return "ignored"
    return "redacted"


def scan_document(file_path: str, pages: list[dict], allow_flagged: bool = False) -> dict:
    """Scan a parsed document. Returns the findings, the cleaned pages, and whether to quarantine it."""
    hidden_spans = find_hidden_text(file_path)
    cleaned_pages = remove_hidden_text(pages, hidden_spans)

    findings = []
    findings.extend(scan_hidden_spans(hidden_spans))
    findings.extend(scan_pages(cleaned_pages))
    findings.extend(scan_metadata(file_path))

    has_high_finding = False
    for finding in findings:
        if finding["severity"] == "high":
            has_high_finding = True

    # A released document is not blocked again, but its instruction-like sentences are still removed
    quarantine = has_high_finding and not allow_flagged

    for finding in findings:
        finding["action"] = decide_action(finding, quarantine)

    return {"findings": findings, "pages": cleaned_pages, "quarantine": quarantine}


def make_quarantine_message(findings: list[dict]) -> str:
    """Write the reason why a document was blocked."""
    high_findings = []
    for finding in findings:
        if finding["severity"] == "high":
            high_findings.append(finding)

    parts = []
    for finding in high_findings[:3]:
        label = RULE_LABELS.get(finding["rule"], finding["rule"])
        if finding["kind"] == "metadata":
            place = "in the document properties"
        elif finding["kind"] == "hidden_text":
            place = "in hidden text on page " + str(finding["page"])
        else:
            place = "on page " + str(finding["page"])
        parts.append(label + " " + place + ': "' + finding["snippet"][:80] + '"')

    message = "Blocked by the security scan. Found " + "; ".join(parts) + "."
    if len(high_findings) > 3:
        message += " (" + str(len(high_findings) - 3) + " more)"
    message += " If you trust the sender, you can release the document."
    return message