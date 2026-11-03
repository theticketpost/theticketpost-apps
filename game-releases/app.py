import os
import sys

current = os.path.dirname(os.path.realpath(__file__))
sys.path.append(current)

from theticketpost.application import Application
from flask import render_template, request
from loguru import logger
import calendar
import datetime
import threading
import time
import requests

API_URL = "https://api.rawg.io/api/games"
TIMEOUT = 15
CACHE_SECONDS = 3600

# RAWG parent platforms: one per family, so new consoles (Switch 2...) come in too
FAMILIES = {
    "platform_pc": [1],
    "platform_playstation": [2],
    "platform_xbox": [3],
    "platform_mobile": [4, 8],
    "platform_nintendo": [7],
}

# Short platform names for the ticket, by RAWG slug
SHORT_NAMES = {
    "pc": "PC", "macos": "Mac", "linux": "Linux",
    "playstation5": "PS5", "playstation4": "PS4",
    "xbox-series-x": "Xbox Series", "xbox-one": "Xbox One",
    "nintendo-switch": "Switch", "nintendo-switch-2": "Switch 2",
    "ios": "iOS", "android": "Android",
}
# same order on every game
PLATFORM_ORDER = ["PS5", "PS4", "Xbox Series", "Xbox One", "Switch 2", "Switch", "PC", "Mac", "Linux", "iOS", "Android"]

TEXTS = {
    "es": {"title": "Lanzamientos", "subtitle": "Videojuegos", "featured": "Lo más esperado",
           "nothing": "No hay lanzamientos en estas fechas.",
           "days": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"],
           "months": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                      "septiembre", "octubre", "noviembre", "diciembre"],
           "date": "{weekday} {day} de {month}", "range": "Del {d1} al {d2} de {m2}", "range_months": "Del {d1} de {m1} al {d2} de {m2}"},
    "en": {"title": "New games", "subtitle": "Video game releases", "featured": "Most awaited",
           "nothing": "No releases on these dates.",
           "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
           "months": ["January", "February", "March", "April", "May", "June", "July", "August",
                      "September", "October", "November", "December"],
           "date": "{weekday}, {month} {day}", "range": "{m2} {d1} to {d2}", "range_months": "{m1} {d1} to {m2} {d2}"},
    "fr": {"title": "Sorties jeux", "subtitle": "Jeux vidéo", "featured": "Le plus attendu",
           "nothing": "Pas de sorties à ces dates.",
           "days": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
           "months": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
                      "septembre", "octobre", "novembre", "décembre"],
           "date": "{weekday} {day} {month}", "range": "Du {d1} au {d2} {m2}", "range_months": "Du {d1} {m1} au {d2} {m2}"},
    "de": {"title": "Neue Spiele", "subtitle": "Videospiele", "featured": "Am meisten erwartet",
           "nothing": "Keine Veröffentlichungen in diesem Zeitraum.",
           "days": ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"],
           "months": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
                      "September", "Oktober", "November", "Dezember"],
           "date": "{weekday}, {day}. {month}", "range": "{d1}. bis {d2}. {m2}", "range_months": "{d1}. {m1} bis {d2}. {m2}"},
    "it": {"title": "Nuovi giochi", "subtitle": "Videogiochi", "featured": "Il più atteso",
           "nothing": "Nessuna uscita in queste date.",
           "days": ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"],
           "months": ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
                      "settembre", "ottobre", "novembre", "dicembre"],
           "date": "{weekday} {day} {month}", "range": "Dal {d1} al {d2} {m2}", "range_months": "Dal {d1} {m1} al {d2} {m2}"},
    "pt": {"title": "Lançamentos", "subtitle": "Videojogos", "featured": "O mais esperado",
           "nothing": "Sem lançamentos nestas datas.",
           "days": ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"],
           "months": ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
                      "setembro", "outubro", "novembro", "dezembro"],
           "date": "{weekday}, {day} de {month}", "range": "De {d1} a {d2} de {m2}", "range_months": "De {d1} de {m1} a {d2} de {m2}"},
}


def format_date(date, texts):
    return texts["date"].format(weekday=texts["days"][date.weekday()], day=date.day, month=texts["months"][date.month - 1])


def format_range(start, end, texts):
    """"Del 2 al 8 de noviembre": the month only once when it's the same."""
    key = "range" if (start.year, start.month) == (end.year, end.month) else "range_months"
    return texts[key].format(d1=start.day, d2=end.day, m1=texts["months"][start.month - 1], m2=texts["months"][end.month - 1])


def period_dates(today, period):
    """(first day, last day) of the period, both included."""
    if period == "today":
        return today, today
    if period == "next7":
        return today, today + datetime.timedelta(days=6)
    if period == "next30":
        return today, today + datetime.timedelta(days=29)
    if period == "month":
        return today.replace(day=1), today.replace(day=calendar.monthrange(today.year, today.month)[1])
    monday = today - datetime.timedelta(days=today.weekday())
    return monday, monday + datetime.timedelta(days=6)


def short_platforms(game):
    names = []
    for entry in game.get("platforms") or []:
        platform = entry.get("platform", {})
        name = SHORT_NAMES.get(platform.get("slug"), (platform.get("name") or "").replace("Nintendo ", ""))
        if name and name not in names:
            names.append(name)
    return sorted(names, key=lambda name: PLATFORM_ORDER.index(name) if name in PLATFORM_ORDER else len(PLATFORM_ORDER))


def resized_image(url, width=640):
    """RAWG serves smaller copies under /media/resize/<width>/-/: the full
    pictures are several MB, too much for a 384 dot ticket."""
    if url and "/media/" in url and "/media/resize/" not in url:
        return url.replace("/media/", f"/media/resize/{width}/-/", 1)
    return url or ""


class App(Application):
    """Video game releases from RAWG, the most awaited first ("added" counts
    how many players have the game in their lists, which keeps the many tiny
    releases of every week out of the ticket)."""

    def __init__(self, desc, flaskApp):
        Application.__init__(self, __name__, __file__, desc, flaskApp)
        self.cache = {}
        self.lock = threading.Lock()


    def fetch(self, start, end, families, count):
        params = {
            "key": str(self.get_configuration_value("api_key", "")).strip(),
            "dates": f"{start.isoformat()},{end.isoformat()}",
            "ordering": "-added",
            "page_size": min(40, count),
            "exclude_additions": "true",
        }
        if families:
            params["parent_platforms"] = ",".join(str(family) for family in families)
        response = requests.get(API_URL, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        return response.json().get("results", [])


    def cached(self, cache_key, fetch):
        now = time.monotonic()
        with self.lock:
            entry = self.cache.get(cache_key)
            if entry and now - entry[0] < CACHE_SECONDS:
                return entry[1]
        value = fetch()
        with self.lock:
            self.cache[cache_key] = (now, value)
        return value


    def to_game(self, data):
        try:
            date = datetime.date.fromisoformat(data.get("released") or "")
        except ValueError:
            return None
        return {
            "name": data.get("name", ""),
            "date": date,
            "platforms": short_platforms(data),
            "genres": [genre["name"] for genre in data.get("genres") or []][:2],
            "image": resized_image(data.get("background_image")),
            "added": data.get("added") or 0,
        }


    def render_component(self):
        options = {"period": "week", "count": 8, "show_image": True, "language": "es",
                   **{family: True for family in FAMILIES}, "platform_mobile": False}
        if request.headers.get('Content-Type') == 'application/json':
            for element in request.json:
                name, value = element.get("name"), element.get("value")
                if name in ("period", "language") and value:
                    options[name] = str(value)
                elif name == "count":
                    try:
                        options[name] = int(value)
                    except (TypeError, ValueError):
                        pass
                elif name in FAMILIES or name == "show_image":
                    options[name] = bool(value)
        options["count"] = min(20, max(1, options["count"]))
        texts = TEXTS.get(options["language"], TEXTS["en"])

        if not self.get_configuration_value("api_key"):
            return '<div style="text-align: center;">Add your RAWG API key in the app settings</div>'

        start, end = period_dates(datetime.date.today(), options["period"])
        families = sorted(id for name, ids in FAMILIES.items() if options[name] for id in ids)
        try:
            results = self.cached((start, end, tuple(families), options["count"]),
                                  lambda: self.fetch(start, end, families, options["count"]))
        except Exception as e:
            error = f"HTTP {e.response.status_code}" if isinstance(e, requests.HTTPError) else type(e).__name__
            logger.error(f"Game releases: could not get the releases ({error})")
            return f'<div style="text-align: center;">Could not get the game releases ({error})</div>'

        games = [game for game in (self.to_game(result) for result in results) if game][:options["count"]]
        featured = games.pop(0) if games else None
        if featured:
            featured["label"] = format_date(featured["date"], texts)

        # the rest by day, the most awaited first within each day
        days = {}
        for game in sorted(games, key=lambda game: (game["date"], -game["added"])):
            days.setdefault(game["date"], []).append(game)

        heading = format_date(start, texts) if start == end else format_range(start, end, texts)

        return render_template('game-releases/component.html',
            texts=texts, heading=heading, featured=featured,
            days=[{"label": format_date(date, texts), "games": day_games} for date, day_games in days.items()],
            show_image=options["show_image"])
