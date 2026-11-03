import os
import sys

current = os.path.dirname(os.path.realpath(__file__))
sys.path.append(current)

from theticketpost.application import Application
from flask import render_template, request, jsonify
from loguru import logger
from concurrent.futures import ThreadPoolExecutor
import calendar
import copy
import datetime
import re
import feedparser
import requests

# some sites refuse requests that don't look like a browser
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) theticketpost"}
TIMEOUT = 15


class App(Application):
    """Headlines from RSS/Atom feeds.

    RSS has no "importance" field: a feed is just a list. Front page feeds
    (El País, elDiario.es...) list the stories in the order of the website's
    front page, so their first items are the top headlines. Others (La Voz de
    Galicia) list them by time. The "order" option chooses between keeping the
    feed's order and sorting by date."""

    def __init__(self, desc, flaskApp):
        Application.__init__(self, __name__, __file__, desc, flaskApp)


    def feeds(self):
        """[{"name", "url"}] from the app settings, in their order."""
        entries = self.get_configuration_value("feeds", [])
        feeds = []
        for index, entry in enumerate(entries if isinstance(entries, list) else [], start=1):
            url = str(entry.get("url", "")).strip()
            if url:
                url = re.sub(r"^feed://", "https://", url, flags=re.I)
                feeds.append({"name": str(entry.get("name", "")).strip() or f"Feed {index}", "url": url})
        return feeds


    def get_inspector_json(self):
        """The section options, with the feeds from the settings to choose from."""
        template = copy.deepcopy(self.desc["inspector_template"])
        for item in template:
            if item["name"] == "feed":
                item["options"] = [{"value": "", "description": "All feeds"}] + \
                    [{"value": feed["name"], "description": feed["name"]} for feed in self.feeds()]
        return jsonify({"refresh_component": self.desc["refresh_component"], "config": template})


    def fetch(self, feed):
        """The feed's items, in the feed's order. None if it can't be read."""
        try:
            response = requests.get(feed["url"], headers=HEADERS, timeout=TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as e:
            error = f"HTTP {e.response.status_code}" if isinstance(e, requests.HTTPError) else type(e).__name__
            logger.error(f"RSS {feed['name']}: could not read the feed ({error})")
            return None

        # feedparser copes with RSS 0.9x-2.0, Atom and broken feeds (e.g. RTVE's)
        parsed = feedparser.parse(response.content)
        if not parsed.entries:
            logger.error(f"RSS {feed['name']}: no items (is it an RSS or Atom address?)")
            return None

        items = []
        for entry in parsed.entries:
            title = " ".join(str(entry.get("title", "")).split())
            if not title:
                continue
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            date = None
            if published:
                date = datetime.datetime.fromtimestamp(calendar.timegm(published), datetime.timezone.utc).astimezone()
            items.append({"title": title, "date": date, "source": feed["name"]})
        return items


    def pick(self, items, count, order, max_age):
        if max_age > 0:
            oldest = datetime.datetime.now().astimezone() - datetime.timedelta(hours=max_age)
            # undated items stay: there's no way to tell how old they are
            items = [item for item in items if not item["date"] or item["date"] >= oldest]
        if order == "newest":
            items = sorted(items, key=lambda item: item["date"] or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc), reverse=True)
        return items[:count]


    def get_entries(self, feeds, count, order, max_age):
        """The headlines to print, and the names of the feeds that couldn't be read."""
        with ThreadPoolExecutor(max_workers=min(8, len(feeds))) as pool:
            results = list(pool.map(self.fetch, feeds))
        failed = [feed["name"] for feed, items in zip(feeds, results) if items is None]

        entries = []
        seen = set()
        for items in results:
            if items is None:
                continue
            for item in self.pick(items, count, order, max_age):
                # the same story often comes in several sections of a paper
                key = item["title"].lower()
                if key not in seen:
                    seen.add(key)
                    entries.append(item)

        # one feed after another, unless the newest from all of them go first
        if order == "newest" and len(feeds) > 1:
            entries.sort(key=lambda item: item["date"] or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc), reverse=True)

        for entry in entries:
            entry["date"] = entry["date"].strftime("%B %-d, %Y at %-I:%M %p") if entry["date"] else ""
        return entries, failed


    def parse_number(self, value, default, minimum):
        try:
            return max(minimum, int(value))
        except (TypeError, ValueError):
            return default


    def render_component(self):
        options = {"feed": "", "count": 5, "order": "feed", "max_age": 24, "show_source": True, "show_date": True}
        content_type = request.headers.get('Content-Type')
        if (content_type == 'application/json'):
            for element in request.json:
                if element["name"] in options:
                    options[element["name"]] = element["value"]
        count = self.parse_number(options["count"], 5, 1)
        max_age = self.parse_number(options["max_age"], 24, 0)

        feeds = self.feeds()
        message = None
        entries = []
        failed = []
        if not feeds:
            message = "Add your RSS feeds in the app settings"
        else:
            if options["feed"]:
                feeds = [feed for feed in feeds if feed["name"] == options["feed"]]
            if not feeds:
                message = f'There is no feed called "{options["feed"]}" in the app settings'
            else:
                entries, failed = self.get_entries(feeds, count, options["order"], max_age)

        return render_template('rss/component.html', entries=entries, message=message, failed=failed,
                               show_source=bool(options["show_source"]), show_date=bool(options["show_date"]))
