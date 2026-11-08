import argparse
import csv
import io
import random
from pathlib import Path

import pymupdf
from PIL import Image

from build_dataset import read_sources
from text_utils import clean_file_name

EVAL_FOLDER = Path(__file__).resolve().parent
DATA_ROOT = EVAL_FOLDER.parent / "data"
CUAD_FOLDER = DATA_ROOT / "cuad_subset"
SCANNED_FOLDER = DATA_ROOT / "synthetic" / "scanned"

# Resolution of the fake scan
DPI = 150


def make_scanned_page(page) -> bytes:
    """Turn one PDF page into a noisy, slightly crooked grey image (as JPEG bytes)."""
    pixmap = page.get_pixmap(dpi=DPI)
    image = Image.open(io.BytesIO(pixmap.tobytes("png")))
    image = image.convert("L")

    # A real scan is never perfectly straight
    angle = random.uniform(-1.0, 1.0)
    image = image.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=255)

    # Mix in some grey noise, like a real scanner
    noise = Image.effect_noise(image.size, 10)
    image = Image.blend(image, noise, 0.07)

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=60)
    return buffer.getvalue()


def make_scanned_pdf(source_path: Path, output_path: Path) -> None:
    """Rebuild a PDF from page images, so it has no text layer."""
    source_pdf = pymupdf.open(str(source_path))
    scanned_pdf = pymupdf.open()

    for page in source_pdf:
        jpeg_bytes = make_scanned_page(page)
        new_page = scanned_pdf.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(new_page.rect, stream=jpeg_bytes)

    scanned_pdf.save(str(output_path))
    scanned_pdf.close()
    source_pdf.close()


def main() -> None:
    """Create scanned copies of a few contracts and write sources_scanned.csv."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=3, help="How many scanned PDFs to make")
    parser.add_argument("--max-pages", type=int, default=20, help="Only scan contracts with at most this many pages")
    parser.add_argument("--from-first", type=int, default=8, help="Pick from the first N contracts, which have questions")
    args = parser.parse_args()

    # The same seed gives the same "scan" every time
    random.seed(7)
    SCANNED_FOLDER.mkdir(parents=True, exist_ok=True)

    rows = read_sources()[: args.from_first]
    output_rows = []

    for row in rows:
        if len(output_rows) >= args.count:
            break

        source_path = CUAD_FOLDER / row["file_name"]
        if not source_path.exists():
            continue

        pdf = pymupdf.open(str(source_path))
        page_count = len(pdf)
        pdf.close()
        if page_count > args.max_pages:
            continue

        output_name = clean_file_name(row["vendor_name"]) + "_scanned.pdf"
        print("Scanning", row["file_name"], "(" + str(page_count) + " pages)")
        make_scanned_pdf(source_path, SCANNED_FOLDER / output_name)

        output_rows.append(
            {
                "file_name": "synthetic/scanned/" + output_name,
                # A different vendor name keeps the scan separate from the original contract
                "vendor_name": row["vendor_name"] + " Scan",
                "document_type": "Other",
                "cuad_title": row["cuad_title"],
            }
        )

    with open(SCANNED_FOLDER / "sources_scanned.csv", "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["file_name", "vendor_name", "document_type", "cuad_title"])
        writer.writeheader()
        writer.writerows(output_rows)

    print("Made", len(output_rows), "scanned PDFs in", SCANNED_FOLDER)


if __name__ == "__main__":
    main()