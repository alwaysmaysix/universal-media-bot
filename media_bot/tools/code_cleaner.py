# Source cleaner.
#
# Ported from the notebook's `clean_bot_code()` helper. The notebook version had
# its regex patterns stripped (they were empty strings), so this is a working,
# configurable re-implementation: it drops whole blocks that match a pattern and
# optionally applies literal regex substitutions.
#
# CLI:
#     python -m media_bot.tools.code_cleaner input.txt output.py
#     python -m media_bot.tools.code_cleaner input.txt output.py --pattern "after_date"

import argparse
import os
import re
import sys

# Default patterns describe the "date filter" feature that was removed.
DEFAULT_PATTERNS = [
    r"def .*date.*\(",
    r"after_date",
    r"before_date",
]


def _matches_any(line: str, patterns):
    return any(re.search(pattern, line, re.IGNORECASE) for pattern in patterns)


def clean_bot_code(input_file, output_file, patterns=None):
    """Remove blocks/lines matching `patterns` and write the result.

    A matched line that opens a block (ends with ':') causes the whole indented
    block to be skipped; a simple matched statement is dropped on its own.
    """
    patterns = patterns or DEFAULT_PATTERNS

    if not os.path.exists(input_file):
        print(f"❌ Error: Could not find '{input_file}'")
        return False

    with open(input_file, "r", encoding="utf-8") as file:
        lines = file.readlines()

    cleaned_lines = []
    skip_mode = False
    skip_indent = 0

    for line in lines:
        stripped = line.strip()
        current_indent = len(line) - len(line.lstrip())

        if skip_mode:
            if not stripped:
                continue
            if current_indent <= skip_indent:
                skip_mode = False
            else:
                continue

        if _matches_any(line, patterns):
            if stripped.endswith(":"):
                skip_mode = True
                skip_indent = current_indent
            continue

        cleaned_lines.append(line)

    with open(output_file, "w", encoding="utf-8") as file:
        file.writelines(cleaned_lines)

    print(f"✅ Success! Cleaned code saved to '{output_file}'.")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Remove selected blocks from a source file.")
    parser.add_argument("input_file", help="file to read")
    parser.add_argument("output_file", help="file to write")
    parser.add_argument(
        "--pattern",
        action="append",
        dest="patterns",
        help="regex to strip (repeatable). Defaults to the removed date-filter feature.",
    )
    args = parser.parse_args(argv)
    ok = clean_bot_code(args.input_file, args.output_file, args.patterns)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
