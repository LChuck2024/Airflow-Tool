import re
from typing import Dict


def _extract_header(curl_text: str, header_name: str) -> str:
    pattern = re.compile(
        rf"-H\s+'{re.escape(header_name)}:\s*(.*?)'|-H\s+\"{re.escape(header_name)}:\s*(.*?)\"",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(curl_text)
    if not match:
        return ""
    return (match.group(1) or match.group(2) or "").strip()


def _extract_cookie(curl_text: str) -> str:
    # Prefer explicit Cookie header if present.
    cookie = _extract_header(curl_text, "cookie")
    if cookie:
        return cookie

    # Fallback to curl cookie arg: -b 'session=...' or --cookie "session=..."
    pattern = re.compile(
        r"(?:-b|--cookie)\s+'(.*?)'|(?:-b|--cookie)\s+\"(.*?)\"",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(curl_text)
    if not match:
        return ""
    return (match.group(1) or match.group(2) or "").strip()


def parse_curl_auth(curl_text: str) -> Dict[str, str]:
    cookie = _extract_cookie(curl_text)
    csrf = _extract_header(curl_text, "x-csrftoken")
    return {"cookie": cookie, "csrf": csrf}
