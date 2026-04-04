import re
import sys

import requests


def main() -> int:
    url = "https://www.ada.gov/resources/web-guidance/"
    html = requests.get(url, timeout=10).text
    idx = html.lower().find("new requirements")
    print("idx", idx)
    if idx != -1:
        snippet = html[max(0, idx - 800) : idx + 800]
        hrefs = re.findall(r"href=\"([^\"]+)\"", snippet)
        for h in hrefs:
            print("href", h)
        return 0

    print("phrase not found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
