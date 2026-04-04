# Apple Vision OCR

`apple_ocr.swift` uses Apple's Vision framework to extract text from images and scanned PDFs. It is macOS-only and requires no third-party dependencies.

## Usage

```bash
swift apple_ocr.swift /path/to/document.pdf
swift apple_ocr.swift /path/to/scan.png
```

Outputs recognized text to stdout. Exit code 1 if no input path is given.

## Verification

On macOS with Xcode command-line tools installed:

```bash
# Quick smoke test with any image or PDF
echo "test" > /tmp/test.txt
swift scripts/apple_ocr.swift /tmp/test.txt  # will produce empty output (not an image)

# Real test with an actual image or PDF
swift scripts/apple_ocr.swift path/to/any-image.png
```

The script is called by `care_workspace.py` via `run_apple_ocr()` as a fallback when `pdfplumber` and `pypdf` cannot extract text. On non-macOS systems it silently returns empty output.

## Limitations

- macOS only (requires Vision framework)
- OCR accuracy varies with scan quality
- OCR-derived extractions default to `do_not_trust_without_human_review` tier
