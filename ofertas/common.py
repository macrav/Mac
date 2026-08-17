"""Shared HTTP helpers for the offer scrapers."""
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Falabella and Tai Loy both refuse plain requests; these are the headers a
# normal browser navigation sends.
HEADERS = [
    "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language: es-PE,es;q=0.9,en;q=0.8",
    "Sec-Fetch-Dest: document",
    "Sec-Fetch-Mode: navigate",
    "Sec-Fetch-Site: none",
    "Upgrade-Insecure-Requests: 1",
]


def get(url, tries=3, minlen=5000, timeout=60):
    """Fetch a URL, retrying on transport errors and short/truncated bodies."""
    args = ["curl", "-sS", "--compressed", "-L", "--max-time", str(timeout),
            "-H", f"User-Agent: {UA}"]
    for h in HEADERS:
        args += ["-H", h]
    for attempt in range(tries):
        try:
            p = subprocess.run(args + [url], capture_output=True, text=True,
                               errors="replace", timeout=timeout + 15)
            if p.returncode == 0 and len(p.stdout) >= minlen:
                return p.stdout
        except subprocess.TimeoutExpired:
            pass
        time.sleep(1.5 * (attempt + 1))
    return ""


def fanout(fn, items, workers=8):
    """Map fn over items concurrently, preserving order."""
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, items))
