"""Minimal MediaWiki API client (standard library only) for bot-password logins."""

from __future__ import annotations

import http.cookiejar
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "research-assessment-wiki-bot/0.1 (+https://github.com/jtapolcai/research-assessment-wiki)"


def load_env(path: Path) -> None:
    """Load KEY=VALUE lines from a .env file into os.environ (existing values win)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


class WikiError(RuntimeError):
    pass


class Wiki:
    def __init__(self, api_url: str):
        self.api_url = api_url
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        self.csrf_token: str | None = None
        self._credentials: tuple[str, str] | None = None

    # -- low level -----------------------------------------------------------
    def _call(self, params: dict, post: bool = False, retries: int = 6) -> dict:
        params = {**params, "format": "json", "formatversion": "2"}
        data = urllib.parse.urlencode(params).encode() if post else None
        url = self.api_url if post else f"{self.api_url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
        for attempt in range(retries):
            try:
                with self.opener.open(request, timeout=120) as response:
                    result = json.load(response)
            except (urllib.error.URLError, TimeoutError) as error:
                if attempt == retries - 1:
                    raise WikiError(f"cannot reach {self.api_url}: {error}") from error
                time.sleep(2 ** attempt)
                continue
            error = result.get("error")
            if error and error.get("code") in ("maxlag", "ratelimited", "readonly"):
                time.sleep(max(5, 2 ** attempt))
                continue
            if error:
                raise WikiError(f"{error.get('code')}: {error.get('info')}")
            return result
        raise WikiError(f"giving up after {retries} attempts: {params.get('action')}")

    def get(self, **params) -> dict:
        return self._call(params)

    def post(self, **params) -> dict:
        return self._call(params, post=True)

    # -- session -------------------------------------------------------------
    def login(self, user: str, password: str) -> None:
        token = self.get(action="query", meta="tokens", type="login")["query"]["tokens"]["logintoken"]
        result = self.post(action="login", lgname=user, lgpassword=password, lgtoken=token)["login"]
        if result.get("result") != "Success":
            raise WikiError(f"login failed: {result.get('reason', result)}")
        self.csrf_token = self.get(action="query", meta="tokens")["query"]["tokens"]["csrftoken"]
        self._credentials = (user, password)

    def relogin(self) -> None:
        if not self._credentials:
            raise WikiError("not logged in")
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        self.login(*self._credentials)

    # -- pages ---------------------------------------------------------------
    def read_pages(self, titles: list[str]) -> dict[str, str | None]:
        """Current wikitext of each title (None if the page does not exist). 50 per request."""
        contents: dict[str, str | None] = {}
        for start in range(0, len(titles), 50):
            batch = titles[start:start + 50]
            result = self.get(
                action="query", prop="revisions", rvprop="content", rvslots="main",
                titles="|".join(batch),
            )
            query = result.get("query", {})
            # Map normalised titles back to the titles we asked for.
            back = {n["to"]: n["from"] for n in query.get("normalized", [])}
            for page in query.get("pages", []):
                asked = back.get(page["title"], page["title"])
                if page.get("missing") or "revisions" not in page:
                    contents[asked] = None
                else:
                    contents[asked] = page["revisions"][0]["slots"]["main"]["content"]
        return contents

    def edit(self, title: str, text: str, summary: str, bot: bool = True) -> dict:
        if not self.csrf_token:
            raise WikiError("not logged in")
        for attempt in range(2):
            params = {
                "action": "edit", "title": title, "text": text, "summary": summary,
                "token": self.csrf_token, "assert": "user", "maxlag": "5",
            }
            if bot:
                params["bot"] = "1"
            try:
                return self.post(**params)["edit"]
            except WikiError as error:
                # Session lost (expired or evicted): log in again once and retry.
                if attempt == 0 and str(error).startswith(("assertuserfailed", "badtoken", "notoken")):
                    self.relogin()
                    continue
                raise
        raise WikiError("unreachable")
