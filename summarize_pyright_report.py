import json
from collections import defaultdict
from pathlib import Path
import chardet

INPUT_FILE = "pyright_report.json"
OUTPUT_FILE = "pyright_summary.txt"

def detect_encoding(file_path):
    with open(file_path, "rb") as f:
        raw_data = f.read()
        result = chardet.detect(raw_data)
        return result["encoding"]

def load_json_safely(path):
    encoding = detect_encoding(path)
    print(f"Определена кодировка: {encoding}")
    with open(path, "r", encoding=encoding) as f:
        return json.load(f)

def main():
    path = Path(INPUT_FILE)
    if not path.exists():
        print(f"Файл {INPUT_FILE} не найден.")
        return

    data = load_json_safely(path)
    diagnostics = data.get("generalDiagnostics", [])
    grouped = defaultdict(list)

    for diag in diagnostics:
        file_path = diag.get("file", "unknown")
        line = diag.get("range", {}).get("start", {}).get("line", 0) + 1
        message = diag.get("message", "Unknown error")
        severity = diag.get("severity", "info")
        grouped[file_path].append((line, severity, message))

    sorted_files = sorted(grouped.items(), key=lambda x: len(x[1]), reverse=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for file, issues in sorted_files:
            f.write(f"\n[{file}] — {len(issues)} issue(s):\n")
            for line, severity, message in sorted(issues):
                f.write(f"  Line {line:<4} [{severity.upper()}] {message}\n")

    print(f"\nОтчет успешно создан: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
