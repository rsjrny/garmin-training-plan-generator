"""Public website addresses and explicit local race-bookmark preferences."""
from contextlib import closing
import ipaddress
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit, urlunsplit
import webbrowser

SETTING_KEY = "race_browse_bookmarks.v1"
DEFAULT_BOOKMARKS = (
    ("Running in the USA", "https://www.runningintheusa.com/race/list"),
    ("Races by state", "https://www.runningintheusa.com/race/find-by-state/"),
)
COMMON_RACE_SITES = (
    dict(name="RunSignup",url="https://runsignup.com/races",description="Find local races by place, date and distance."),
    dict(name="UltraSignup",url="https://ultrasignup.com/events/search.aspx",description="Trail and ultrarunning event search."),
    dict(name="FindMyMarathon",url="https://www.findmymarathon.com/calendar.php",description="Marathon calendar and course comparisons.",prefer_browser=True),
    dict(name="ACTIVE",url="https://www.active.com/running/",description="Running races and event registration."),
)
_BROWSER_ONLY_HOSTS = {
    "runningintheusa.com":"Running in the USA", "runsignup.com":"RunSignup",
    "ultrasignup.com":"UltraSignup", "active.com":"ACTIVE",
}


class BrowseError(ValueError):
    pass


def _bookmark_name(name):
    if not isinstance(name,str) or not 1<=len(name.strip())<=120 or re.search(r"[\x00-\x1f\x7f]",name):
        raise BrowseError("Give this bookmark a name of 1–120 characters.")
    return name.strip()


def website_address(value):
    if not isinstance(value,str):
        raise BrowseError("Enter a public HTTPS website address.")
    value = value.strip()
    if not value or len(value)>2048 or re.search(r"[\s\\\x00-\x1f\x7f]",value):
        raise BrowseError("Enter a website address without spaces or control characters.")
    if "://" not in value and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:",value):
        value = "https://"+value
    try:
        parts = urlsplit(value)
        host = parts.hostname
        if parts.scheme.lower()!="https" or not host or parts.username is not None or parts.password is not None or parts.port not in (None,443):
            raise ValueError()
        host = host.encode("idna").decode("ascii").lower().rstrip(".")
        if host in {"localhost","localhost.localdomain"} or host.endswith((".localhost",".local",".internal")):
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if "." not in host or len(host)>253 or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",label) for label in host.split(".")):
                raise ValueError()
            # Reject alternative numeric host representations.
            if all(re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)",label) for label in host.split(".")):
                raise ValueError()
        else:
            raise ValueError()
        return urlunsplit(("https",host,parts.path or "/",parts.query,parts.fragment))
    except (ValueError,UnicodeError):
        raise BrowseError("Use a public HTTPS website name, without a login or custom port.") from None


def _bookmarks(conn):
    raw = conn.execute("SELECT value FROM app_settings WHERE key=?",(SETTING_KEY,)).fetchone()
    if raw is None:
        return [dict(name=name,url=url) for name,url in DEFAULT_BOOKMARKS]
    try:
        rows = json.loads(raw[0])
        if not isinstance(rows,list) or len(rows)>50:
            raise ValueError()
        seen = set()
        for row in rows:
            if not isinstance(row,dict) or set(row)!={"name","url"} or _bookmark_name(row["name"]) != row["name"]:
                raise ValueError()
            normalized = website_address(row["url"])
            if normalized != row["url"] or normalized in seen:
                raise ValueError()
            seen.add(normalized)
        return rows
    except (ValueError,TypeError):
        raise BrowseError("Saved race bookmarks are unreadable. Restore default bookmarks to start a new list.") from None


def race_bookmarks(db_path):
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri()+"?mode=ro",uri=True,timeout=10)) as conn:
        return _bookmarks(conn)


def _save(db_path, change):
    path = Path(db_path)
    if not path.is_file():
        raise BrowseError("The configured database does not exist.")
    with closing(sqlite3.connect(path,timeout=10)) as conn,conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = change(conn)
        conn.execute("""INSERT INTO app_settings(key,value) VALUES(?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')""",
            (SETTING_KEY,json.dumps(rows,ensure_ascii=False,separators=(",",":"))))
    return rows


def save_race_bookmark(db_path, name, url):
    name = _bookmark_name(name)
    url = website_address(url)
    def change(conn):
        rows = _bookmarks(conn)
        found = next((row for row in rows if row["url"]==url),None)
        if found:
            found["name"] = name.strip()
        elif len(rows)<50:
            rows.append(dict(name=name.strip(),url=url))
        else:
            raise BrowseError("The bookmark list is full. Remove a bookmark before adding another.")
        return rows
    return _save(db_path,change)


def remove_race_bookmark(db_path, url):
    url = website_address(url)
    return _save(db_path,lambda conn:[row for row in _bookmarks(conn) if row["url"]!=url])


def restore_race_bookmarks(db_path):
    return _save(db_path,lambda conn:[dict(name=name,url=url) for name,url in DEFAULT_BOOKMARKS])


def open_race_browser(url):
    return webbrowser.open(website_address(url),new=2)


def browser_only_site(url):
    """Known sites whose SAMEORIGIN/frame-ancestors policies were verified."""
    return browser_only_site_name(url) is not None


def browser_only_site_name(url):
    host = urlsplit(website_address(url)).hostname
    return _BROWSER_ONLY_HOSTS.get(host.removeprefix("www."))
