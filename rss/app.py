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
import hashlib
import html
import json
import re
import threading
import feedparser
import requests
import theticketpost.llm as llm

# some sites refuse requests that don't look like a browser
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) theticketpost"}
TIMEOUT = 15

# AI editor
MAX_CANDIDATES = 150      # news sent to the AI at most, to keep the prompt small
SUMMARY_CHARS = 200       # of each news item's summary
HISTORY_DAYS = 4          # printed headlines it remembers, so it doesn't repeat stories
CACHED_CHOICES = 30       # front pages it keeps, so reloading the editor doesn't ask again
DEFAULT_EDITORIAL = "A general interest newspaper: the news most people would want to know about today."

EDITOR_PROMPT = """You are the editor-in-chief of a small printed newspaper. You get today's candidate news, numbered, from several feeds, and choose the front page: at most {front_page} headlines, the most important first.

How to judge importance, as you have no other source:
- A story covered by several feeds is more important than one covered by one.
- In each feed, a lower "rank" means the newspaper placed it higher on its front page (for feeds sorted by time it means more recent).
- Recent news over old news, and your own knowledge of what usually matters.
- Above all, the editorial line below.

Rules:
- One headline per story. When several feeds tell the same story, choose the clearest and most factual headline, the least sensational or clickbait one.
- "Already printed" lists the headlines of the last days. Don't choose a story that was already printed, unless the new headline brings a real development (a new fact, a decision, a result), not just the same story told again.
- Leave out what doesn't deserve the front page. Fewer headlines, or none, is fine.
- Choose only from the candidates, by their number. Never write headlines.

Editorial line:
{editorial}

First group the candidates into stories: the same event or case, even when the headlines look at it from different angles (the news, a profile of who is involved, reactions, an analysis). Then choose the front page with at most one candidate from each story.

Answer with a JSON object:
{{"stories": [{{"story": "a few words", "candidates": [numbers], "best": the number of its best headline}}, ...],
 "front_page": [numbers of the chosen headlines, most important first]}}
"stories" only needs the stories with more than one candidate."""


class App(Application):
    """Headlines from RSS/Atom feeds.

    RSS has no "importance" field: a feed is just a list. Front page feeds
    (El País, elDiario.es...) list the stories in the order of the website's
    front page, so their first items are the top headlines. Others (La Voz de
    Galicia) list them by time. The "order" option chooses between keeping the
    feed's order and sorting by date."""

    def __init__(self, desc, flaskApp):
        Application.__init__(self, __name__, __file__, desc, flaskApp)
        # the AI editor's memory: headlines printed and front pages chosen.
        # Kept next to the app's config.json: store updates don't overwrite it.
        self.state_path = os.path.join(self.root_path, "state.json")
        self.state_lock = threading.Lock()


    def load_state(self):
        try:
            with open(self.state_path) as f:
                state = json.load(f)
            return state if isinstance(state, dict) else {}
        except (OSError, ValueError):
            return {}


    def save_state(self, state):
        try:
            with open(self.state_path, "w") as f:
                json.dump(state, f, indent=1, ensure_ascii=False)
        except OSError as e:
            logger.error(f"RSS: could not save the AI editor's memory: {e}")


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
            summary = html.unescape(re.sub(r"<[^>]+>", " ", str(entry.get("summary", ""))))
            summary = " ".join(summary.split())
            items.append({"title": title, "date": date, "source": feed["name"], "rank": len(items) + 1,
                          "summary": summary[:SUMMARY_CHARS]})
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

        return entries, failed


    def format_dates(self, entries):
        for entry in entries:
            entry["date"] = entry["date"].strftime("%B %-d, %Y at %-I:%M %p") if entry["date"] else ""
        return entries


    def parse_choice(self, answer, count):
        """Indexes of the front page in the AI answer: real candidate numbers, at
        most one per story (the AI sometimes picks two headlines of one case)."""
        if not isinstance(answer, dict):
            return []
        story_of = {}
        for story_index, story in enumerate(answer.get("stories") or []):
            numbers = story.get("candidates") if isinstance(story, dict) else None
            for number in numbers if isinstance(numbers, list) else []:
                if isinstance(number, int):
                    story_of.setdefault(number, story_index)
        chosen, stories = [], set()
        for number in answer.get("front_page") or []:
            if not isinstance(number, int) or not 1 <= number <= count or number - 1 in chosen:
                continue
            story = story_of.get(number)
            if story is not None:
                if story in stories:
                    continue
                stories.add(story)
            chosen.append(number - 1)
        return chosen


    def edit_front_page(self, candidates, front_page, editorial, printing):
        """The AI editor's choice among candidates: (entries, error). On a print,
        remembers what it printed so later front pages don't repeat it."""
        today = datetime.date.today().isoformat()
        oldest = (datetime.date.today() - datetime.timedelta(days=HISTORY_DAYS)).isoformat()
        editorial = (editorial or "").strip() or DEFAULT_EDITORIAL

        with self.state_lock:
            state = self.load_state()
            # what was printed before today: a second print the same day shows the same news
            history = [item for item in state.get("printed", []) if oldest <= item.get("day", "") < today]
            # a headline already printed never brings anything new (the AI doesn't
            # always notice): only other headlines of those stories reach it
            printed_titles = {item["title"].lower() for item in history}
            candidates = [item for item in candidates if item["title"].lower() not in printed_titles]
            # with many feeds, every feed gets its top news in: the first of each
            # feed, then the second... (sorted() keeps the feeds' order on ties)
            candidates = sorted(candidates, key=lambda item: item["rank"])[:MAX_CANDIDATES]
            if not candidates:
                return [], None

            listing = []
            for number, item in enumerate(candidates, start=1):
                line = f'{number}. [{item["source"]}, rank {item["rank"]}'
                if item["date"]:
                    line += ", " + item["date"].strftime("%Y-%m-%d %H:%M")
                line += f'] {item["title"]}'
                if item["summary"]:
                    line += f' — {item["summary"]}'
                listing.append(line)
            printed = [f'- {item["day"]}: {item["title"]}' for item in history]
            user = "Candidates:\n" + "\n".join(listing) + "\n\nAlready printed:\n" + ("\n".join(printed) or "(nothing)")
            system = EDITOR_PROMPT.format(front_page=front_page, editorial=editorial)

            key = hashlib.sha256((system + user).encode()).hexdigest()
            choices = state.setdefault("choices", {})
            error = None
            if key in choices:
                chosen = choices[key]["chosen"]
            else:
                try:
                    provider = self.get_configuration_value("llm_provider", "openai")
                    model = self.get_configuration_value("model")
                    answer = llm.chat_json(provider, [{"role": "system", "content": system},
                                                      {"role": "user", "content": user}], model=model)
                    chosen = self.parse_choice(answer, len(candidates))[:front_page]
                    choices[key] = {"day": today, "chosen": chosen}
                    # keep the newest front pages only
                    for old in sorted(choices, key=lambda k: choices[k]["day"])[:-CACHED_CHOICES]:
                        del choices[old]
                except llm.LLMError as e:
                    logger.error(f"RSS AI editor: {e}")
                    error = str(e)
                    # never an empty ticket for an AI failure: the top headline of each
                    # feed, then the second of each...
                    by_rank = sorted(range(len(candidates)), key=lambda index: candidates[index]["rank"])
                    chosen = by_rank[:front_page]

            entries = [candidates[index] for index in chosen]
            if printing and error is None:
                # today's other sections stay, and a second print adds nothing twice
                kept = [item for item in state.get("printed", []) if item.get("day", "") >= oldest]
                titles = {item["title"] for item in kept if item["day"] == today}
                state["printed"] = kept + [{"day": today, "title": item["title"], "source": item["source"]}
                                           for item in entries if item["title"] not in titles]
            self.save_state(state)

        return entries, error


    def parse_number(self, value, default, minimum):
        try:
            return max(minimum, int(value))
        except (TypeError, ValueError):
            return default


    def render_component(self):
        options = {"feed": "", "count": 5, "order": "feed", "max_age": 24, "show_source": True, "show_date": True,
                   "front_page": 6, "editorial": ""}
        content_type = request.headers.get('Content-Type')
        if (content_type == 'application/json'):
            for element in request.json:
                if element["name"] in options:
                    options[element["name"]] = element["value"]
        count = self.parse_number(options["count"], 5, 1)
        max_age = self.parse_number(options["max_age"], 24, 0)
        front_page = self.parse_number(options["front_page"], 6, 1)
        # the service sends X-TTP-Print from the page it prints: only then the
        # AI editor remembers the headlines as printed
        printing = request.headers.get("X-TTP-Print") == "1"
        editor_error = None

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
                if options["order"] == "editor":
                    entries, failed = self.get_entries(feeds, count, "feed", max_age)
                    if entries:
                        entries, editor_error = self.edit_front_page(entries, front_page, options["editorial"], printing)
                else:
                    entries, failed = self.get_entries(feeds, count, options["order"], max_age)
                entries = self.format_dates(entries)

        return render_template('rss/component.html', entries=entries, message=message, failed=failed, editor_error=editor_error,
                               show_source=bool(options["show_source"]), show_date=bool(options["show_date"]))
