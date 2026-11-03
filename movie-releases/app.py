import os
import sys

current = os.path.dirname(os.path.realpath(__file__))
sys.path.append(current)

from theticketpost.application import Application
from flask import render_template, request
from loguru import logger
import datetime
import threading
import time
import requests

API_URL = "https://api.themoviedb.org/3"
IMAGE_URL = "https://image.tmdb.org/t/p/w185"
TIMEOUT = 15
# Releases don't change by the minute: ask TMDB again after an hour
CACHE_SECONDS = 3600
# TMDB release types: 2 limited theatrical, 3 theatrical
THEATRICAL = (2, 3)

# Text printed on the ticket, by the first part of the TMDB language
TEXTS = {
    "es": {
        "title": "Cartelera", "release_day": "Estrenos del {date}", "director": "Dir.",
        "nothing": "No hay estrenos esta semana.",
        "days": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"],
        "months": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                   "septiembre", "octubre", "noviembre", "diciembre"],
        "date": "{weekday} {day} de {month}", "short_date": "{weekday} {day}",
    },
    "en": {
        "title": "Now showing", "release_day": "Opening {date}", "director": "Dir.",
        "nothing": "No new releases this week.",
        "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "months": ["January", "February", "March", "April", "May", "June", "July", "August",
                   "September", "October", "November", "December"],
        "date": "{weekday}, {month} {day}", "short_date": "{weekday} {day}",
    },
    "fr": {
        "title": "À l'affiche", "release_day": "Sorties du {date}", "director": "Réal.",
        "nothing": "Pas de sorties cette semaine.",
        "days": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
        "months": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
                   "septembre", "octobre", "novembre", "décembre"],
        "date": "{weekday} {day} {month}", "short_date": "{weekday} {day}",
    },
    "de": {
        "title": "Kinoprogramm", "release_day": "Kinostart {date}", "director": "Regie:",
        "nothing": "Diese Woche keine Kinostarts.",
        "days": ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"],
        "months": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
                   "September", "Oktober", "November", "Dezember"],
        "date": "{weekday}, {day}. {month}", "short_date": "{weekday} {day}.",
    },
    "it": {
        "title": "Al cinema", "release_day": "Uscite di {date}", "director": "Regia:",
        "nothing": "Nessuna uscita questa settimana.",
        "days": ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"],
        "months": ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
                   "settembre", "ottobre", "novembre", "dicembre"],
        "date": "{weekday} {day} {month}", "short_date": "{weekday} {day}",
    },
    "pt": {
        "title": "Em cartaz", "release_day": "Estreias de {date}", "director": "Real.",
        "nothing": "Sem estreias esta semana.",
        "days": ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"],
        "months": ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
                   "setembro", "outubro", "novembro", "dezembro"],
        "date": "{weekday}, {day} de {month}", "short_date": "{weekday} {day}",
    },
}


def texts_for(language):
    return TEXTS.get(language.split("-")[0], TEXTS["en"])


def format_date(date, texts, key="date"):
    return texts[key].format(weekday=texts["days"][date.weekday()], day=date.day, month=texts["months"][date.month - 1])


def week_start(today, release_day, week):
    """First day of the release week: the last release day (today included),
    or the next one when asking for next week's releases."""
    start = today - datetime.timedelta(days=(today.weekday() - release_day) % 7)
    if week == "next":
        start += datetime.timedelta(days=7)
    return start


class App(Application):
    """Cinema releases from TMDB. Discover with a region filters by that
    country's own release dates, so any country works the same, and a 7 day
    window catches every release whatever weekday the country releases on."""

    def __init__(self, desc, flaskApp):
        Application.__init__(self, __name__, __file__, desc, flaskApp)
        self.cache = {}
        self.lock = threading.Lock()


    def get_json(self, path, params):
        key = str(self.get_configuration_value("api_key", "")).strip()
        headers = {"Accept": "application/json"}
        params = dict(params)
        # the v4 Read Access Token (a long JWT) goes in a header, the v3 key in the URL
        if key.startswith("eyJ"):
            headers["Authorization"] = "Bearer " + key
        else:
            params["api_key"] = key
        response = requests.get(API_URL + path, params=params, headers=headers, timeout=TIMEOUT)
        response.raise_for_status()
        return response.json()


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


    def discover(self, country, language, start, end, count):
        data = self.get_json("/discover/movie", {
            "region": country,
            "language": language,
            "with_release_type": "|".join(str(kind) for kind in THEATRICAL),
            "release_date.gte": start.isoformat(),
            "release_date.lte": end.isoformat(),
            "sort_by": "popularity.desc",
            "include_adult": "false",
        })
        return data.get("results", [])[:count]


    def details(self, movie_id, language):
        return self.get_json(f"/movie/{movie_id}", {"language": language, "append_to_response": "credits,release_dates"})


    def country_release(self, details, country):
        """(release date, age rating) of the theatrical release in that country."""
        for entry in details.get("release_dates", {}).get("results", []):
            if entry.get("iso_3166_1") != country:
                continue
            releases = sorted(entry.get("release_dates", []), key=lambda release: release.get("type") != 3)
            for release in releases:
                if release.get("type") in THEATRICAL:
                    try:
                        date = datetime.date.fromisoformat(release.get("release_date", "")[:10])
                    except ValueError:
                        date = None
                    rating = next((r.get("certification") for r in releases if r.get("certification")), "")
                    return date, rating.strip()
        return None, ""


    def runtime(self, minutes):
        if not minutes:
            return ""
        hours, minutes = divmod(int(minutes), 60)
        return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"


    def overview(self, text, limit=170):
        text = " ".join((text or "").split())
        if len(text) <= limit:
            return text
        cut = text[:limit].rsplit(" ", 1)[0].rstrip(",.;:")
        return cut + "…"


    def build_movie(self, summary, country, language, start):
        try:
            details = self.details(summary["id"], language)
        except requests.RequestException as e:
            logger.warning(f"Movie releases: no details for {summary.get('title')} ({type(e).__name__})")
            details = {}
        date, rating = self.country_release(details, country)
        # discover already filtered by the country's dates: without a date of
        # its own in the week (summary dates are worldwide), take the week's start
        if date is None or not start <= date <= start + datetime.timedelta(days=6):
            date = start
        crew = details.get("credits", {}).get("crew", [])
        directors = [person["name"] for person in crew if person.get("job") == "Director"]
        title = details.get("title") or summary.get("title", "")
        original = details.get("original_title") or summary.get("original_title", "")
        poster = details.get("poster_path") or summary.get("poster_path")
        return {
            "title": title,
            # worth printing only when the country shows it under another name
            "original_title": original if original and original.lower() != title.lower() else "",
            "date": date,
            "genres": [genre["name"] for genre in details.get("genres", [])][:2],
            "runtime": self.runtime(details.get("runtime")),
            "rating": rating,
            "directors": directors[:2],
            "overview": self.overview(details.get("overview") or summary.get("overview")),
            "poster": IMAGE_URL + poster if poster else "",
        }


    def releases(self, country, language, start, count):
        end = start + datetime.timedelta(days=6)
        movies = [self.build_movie(movie, country, language, start)
                  for movie in self.discover(country, language, start, end, count)]
        # in release order, the most popular first within each day
        movies.sort(key=lambda movie: movie["date"])
        return movies


    def render_component(self):
        options = {"country": "ES", "language": "es-ES", "release_day": 4, "week": "current",
                   "count": 8, "show_posters": True, "show_overview": True}
        if request.headers.get('Content-Type') == 'application/json':
            for element in request.json:
                name, value = element.get("name"), element.get("value")
                if name in ("country", "language", "week") and value:
                    options[name] = str(value)
                elif name in ("release_day", "count"):
                    try:
                        options[name] = int(value)
                    except (TypeError, ValueError):
                        pass
                elif name in ("show_posters", "show_overview"):
                    options[name] = bool(value)
        options["release_day"] %= 7
        options["count"] = min(20, max(1, options["count"]))

        texts = texts_for(options["language"])
        if not self.get_configuration_value("api_key"):
            return '<div style="text-align: center;">Add your TMDB API key in the app settings</div>'

        start = week_start(datetime.date.today(), options["release_day"], options["week"])
        cache_key = (options["country"], options["language"], start, options["count"])
        try:
            movies = self.cached(cache_key, lambda: self.releases(options["country"], options["language"], start, options["count"]))
        except Exception as e:
            error = f"HTTP {e.response.status_code}" if isinstance(e, requests.HTTPError) else type(e).__name__
            logger.error(f"Movie releases: could not get the releases ({error})")
            return f'<div style="text-align: center;">Could not get the movie releases ({error})</div>'

        for movie in movies:
            # the day only tells something when it isn't the usual release day
            movie["day_label"] = format_date(movie["date"], texts, "short_date") if movie["date"] != start else ""

        return render_template('movie-releases/component.html',
            movies=movies, texts=texts,
            heading=texts["release_day"].format(date=format_date(start, texts)),
            show_posters=options["show_posters"], show_overview=options["show_overview"])
