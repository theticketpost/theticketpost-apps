import os
import sys

current = os.path.dirname(os.path.realpath(__file__))
sys.path.append(current)

from theticketpost.application import Application
from flask import render_template, request
from loguru import logger
import requests
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
import theticketpost.llm as llm
import json
import threading
from datetime import date
from scipy.stats import linregress

RECOMMENDATIONS = ("buy", "hold", "sell")

# The figures box. Languages missing here use English.
TEXTS = {
    "english": {"buy": "Buy", "hold": "Hold", "sell": "Sell", "before": "Before: {}", "since": "Since {}",
                "24h": "24 hours", "7d": "7 days", "ma": "vs 2-year average", "fng": "Fear & Greed",
                "Extreme Fear": "Extreme fear", "Fear": "Fear", "Neutral": "Neutral", "Greed": "Greed", "Extreme Greed": "Extreme greed"},
    "spanish": {"buy": "Comprar", "hold": "Mantener", "sell": "Vender", "before": "Antes: {}", "since": "Desde el {}",
                "24h": "24 horas", "7d": "7 días", "ma": "vs media 2 años", "fng": "Miedo/codicia",
                "Extreme Fear": "Miedo extremo", "Fear": "Miedo", "Neutral": "Neutral", "Greed": "Codicia", "Extreme Greed": "Codicia extrema"},
    "french": {"buy": "Acheter", "hold": "Conserver", "sell": "Vendre", "before": "Avant : {}", "since": "Depuis le {}",
               "24h": "24 heures", "7d": "7 jours", "ma": "vs moyenne 2 ans", "fng": "Peur/avidité",
               "Extreme Fear": "Peur extrême", "Fear": "Peur", "Neutral": "Neutre", "Greed": "Avidité", "Extreme Greed": "Avidité extrême"},
    "german": {"buy": "Kaufen", "hold": "Halten", "sell": "Verkaufen", "before": "Vorher: {}", "since": "Seit {}",
               "24h": "24 Stunden", "7d": "7 Tage", "ma": "vs 2-Jahres-Schnitt", "fng": "Angst/Gier",
               "Extreme Fear": "Extreme Angst", "Fear": "Angst", "Neutral": "Neutral", "Greed": "Gier", "Extreme Greed": "Extreme Gier"},
    "italian": {"buy": "Comprare", "hold": "Mantenere", "sell": "Vendere", "before": "Prima: {}", "since": "Dal {}",
                "24h": "24 ore", "7d": "7 giorni", "ma": "vs media 2 anni", "fng": "Paura/avidità",
                "Extreme Fear": "Paura estrema", "Fear": "Paura", "Neutral": "Neutrale", "Greed": "Avidità", "Extreme Greed": "Avidità estrema"},
    "portuguese": {"buy": "Comprar", "hold": "Manter", "sell": "Vender", "before": "Antes: {}", "since": "Desde {}",
                   "24h": "24 horas", "7d": "7 dias", "ma": "vs média 2 anos", "fng": "Medo/ganância",
                   "Extreme Fear": "Medo extremo", "Fear": "Medo", "Neutral": "Neutro", "Greed": "Ganância", "Extreme Greed": "Ganância extrema"},
    "dutch": {"buy": "Kopen", "hold": "Houden", "sell": "Verkopen", "before": "Eerder: {}", "since": "Sinds {}",
              "24h": "24 uur", "7d": "7 dagen", "ma": "vs 2-jaarsgemiddelde", "fng": "Angst/hebzucht",
              "Extreme Fear": "Extreme angst", "Fear": "Angst", "Neutral": "Neutraal", "Greed": "Hebzucht", "Extreme Greed": "Extreme hebzucht"},
}
# days between reminders of an unchanged recommendation (0: never)
DEFAULT_REMINDER_DAYS = 7

class App(Application):

    def __init__(self, desc, flaskApp):
        Application.__init__(self, __name__, __file__, desc, flaskApp)
        # What was last printed, so an unchanged recommendation isn't printed every day.
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
                json.dump(state, f, indent=2)
        except OSError as e:
            logger.error(f"Bit-wise advisor: could not save its state: {e}")



    def fetch_historical_data_with_volume(self, currency):
        # CryptoCompare closed its free API in 2026: daily candles come from Kraken's public API
        # (no key, last 720 days, the last row is the current day)
        url = "https://api.kraken.com/0/public/OHLC"
        params = {
            'pair': 'XBT' + currency.upper(),
            'interval': 1440
        }

        try:
            response = requests.get(url, params=params, timeout=15)
            data = response.json()
        except (requests.RequestException, ValueError) as e:
            logger.error(f"Kraken API error: {e}")
            return pd.DataFrame()

        if data.get('error'):
            logger.error(f"Kraken API error: {data['error']}")
            return pd.DataFrame()

        pair = next(key for key in data['result'] if key != 'last')
        columns = ['timestamp', 'open', 'daily_max', 'daily_min', 'price', 'vwap', 'base_volume', 'count']
        df = pd.DataFrame(data['result'][pair], columns=columns)
        for column in columns[1:7]:
            df[column] = df[column].astype(float)
        # volume in the quote currency, like CryptoCompare's 'volumeto'
        df['volume'] = df['base_volume'] * df['vwap']
        df['date'] = pd.to_datetime(df['timestamp'], unit='s')
        df.set_index('date', inplace=True)

        return df



    def calculate_pivot_points(self, df):
        df['pivot_point'] = (df['daily_max'] + df['daily_min'] + df['price']) / 3
        df['R1'] = 2 * df['pivot_point'] - df['daily_min']
        df['R2'] = df['pivot_point'] + (df['daily_max'] - df['daily_min'])

        latest_pivot = df['pivot_point'].iloc[-2]
        latest_R1 = df['R1'].iloc[-2]
        latest_R2 = df['R2'].iloc[-2]

        result = {
            'pivot_point': latest_pivot,
            'R1': latest_R1,
            'R2': latest_R2,
        }
        
        return result



    def calculate_2y_ma_multiplier(self, df):
        df['MA_2y'] = df['price'].rolling(window=730, min_periods=1).mean()
        df['MA_2y_multiplier'] = df['MA_2y'] * 5
        return df



    def fetch_fear_and_greed_index(self, days):
        api_url = "https://api.alternative.me/fng/"
        response = requests.get(f"{api_url}?limit={days}")
        data = response.json()
        index_data = data.get('data', [])
        df = pd.DataFrame(index_data)
        df['timestamp'] = pd.to_numeric(df['timestamp'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s').dt.strftime('%Y-%m-%d')
        df.rename(columns={'value': 'fear_and_greed_index'}, inplace=True)
        df.set_index('timestamp', inplace=True)
        return df



    def calculate_average_volume_last_x_days(self, df, days):
        df_sorted = df.sort_index()
        last_date = df_sorted.index[-1]
        start_date = last_date - timedelta(days=days)
        df_filtered = df_sorted.loc[start_date:last_date]
        average_volume = df_filtered['volume'].mean()
        return average_volume



    def calculate_price_change_percentage_24h_trend(self, df, days):
        df_sorted = df.sort_index()
        last_date = df_sorted.index[-1]
        start_date = last_date - timedelta(days=days)
        df_filtered = df_sorted.loc[start_date:last_date]
        daily_diff = df_filtered['price'].diff()
        percentage_change = (daily_diff / df_filtered['price'].shift(1)) * 100

        price_changes = percentage_change[1:].tolist()
        price_changes = [x for x in price_changes if not np.isnan(x)]

        x = np.arange(len(price_changes))
        slope, intercept, r_value, p_value, std_err = linregress(x, price_changes)
        trend = "ascent" if slope > 0 else "descent" if slope < 0 else "moderate"

        return trend, slope, days



    def get_analysis_data(self, df, latest_pivot_points):

        trend_price_change_24h, slope_price_change_24h, days_price_change_24h = self.calculate_price_change_percentage_24h_trend(df, 7)

        last_row = df.iloc[-1]
        df = df.sort_index()
        ma_2y = last_row['MA_2y']
        ma_2y_multiplier = last_row['MA_2y_multiplier']
        # Kraken's last candle is today's, still open: at 2 am its volume is tiny and
        # looks like a collapse. Volumes compare complete days only.
        complete = df.iloc[:-1]
        volume_mean_last_30_days = self.calculate_average_volume_last_x_days(complete, 30)
        fear_and_greed = self.fetch_fear_and_greed_index(1).iloc[-1]
        fear_and_greed_index = fear_and_greed['fear_and_greed_index']

        diff_ma_2y = df['price'].iloc[-1] - ma_2y
        diff_ma_2y_percent = (diff_ma_2y / ma_2y) * 100
        diff_ma_2y_multiplier = df['price'].iloc[-1] - ma_2y_multiplier
        diff_ma_2y_multiplier_percent = (diff_ma_2y_multiplier / ma_2y_multiplier) * 100
        diff_volume_last_30_days = complete['volume'].iloc[-1] - volume_mean_last_30_days
        diff_volume_percent_last_30_days = ( diff_volume_last_30_days / volume_mean_last_30_days ) * 100

        diff_volume_last_24_h = complete['volume'].iloc[-1] - complete['volume'].iloc[-2]
        diff_volume_percent_last_24_h = ( diff_volume_last_24_h / complete['volume'].iloc[-2] ) * 100

        price = df['price'].iloc[-1]
        change_24h_percent = (price / df['price'].iloc[-2] - 1) * 100
        change_7d_percent = (price / df['price'].iloc[-8] - 1) * 100

        results = {
            'current_price': df['price'].iloc[-1],
            'current_volume': df['volume'].iloc[-1],
            'volume_mean_last_30_days': volume_mean_last_30_days,
            'ma_2y': ma_2y,
            'ma_2y_multiplier': ma_2y_multiplier,
            'diff_ma_2y': diff_ma_2y,
            'diff_ma_2y_percent': diff_ma_2y_percent,
            'diff_ma_2y_multiplier': diff_ma_2y_multiplier,
            'diff_ma_2y_multiplier_percent': diff_ma_2y_multiplier_percent,
            'diff_volume_last_30_days': diff_volume_last_30_days,
            'diff_volume_percent_last_30_days': diff_volume_percent_last_30_days,
            'diff_volume_last_24_h': diff_volume_last_24_h,
            'diff_volume_percent_last_24_h': diff_volume_percent_last_24_h,
            'fear_and_greed_index': fear_and_greed_index,
            'fear_and_greed_class': str(fear_and_greed.get('value_classification', '')),
            'change_24h_percent': change_24h_percent,
            'change_7d_percent': change_7d_percent,
            'pivot_point': latest_pivot_points['pivot_point'],
            'R1': latest_pivot_points['R1'],
            'R2': latest_pivot_points['R2'],
            'trend_price_change_24h': trend_price_change_24h,
            'slope_price_change_24h': slope_price_change_24h,
            'days_price_change_24h': days_price_change_24h
        }
        
        return results



    def analyze_crypto_market(self, analysis_data, strategy, language='English', currency='usd', previous=None):

        # get app configuration parameters
        provider = self.get_configuration_value("llm_provider", "openai")
        model = self.get_configuration_value("model")

        description = (
            "Imagine you're an economic journalist tasked with creating a compelling story about Bitcoin's latest market dynamics, using key data indicators. "
            "Is not allowed markdown. Your assignment is to produce a JSON output with two sections: a 'headline' and an 'article'. The 'article' should be presented as a list of paragraphs, each containing plain text (not JSON objects). "
            "The output must to have this scheme { 'headline': 'the headline', 'article': ['paragraph1', 'paragraph2', ... ], 'recommendation': 'buy' | 'hold' | 'sell' }. "
            "'recommendation' is the advice the article concludes with, as one of those three English words, always in English even when the article is in another language. "
            "The headline needs to succinctly summarize Bitcoin's current market status. The article should then offer a deep dive into Bitcoin's recent market behavior. "
            "Please ensure that you divide your ideas into separate short paragraphs. This will enhance the readability of the text once it is printed. "
            "Please keep the entire article concise, aiming for a maximum of 60 words to ensure it's digestible and impactful for a wide audience. "
            "The printed ticket shows, below your article, a box with the recommendation, the price, the 24 hour and 7 day price change, the distance to the 2-year moving average and the Fear and Greed Index. "
            "Don't repeat those figures and don't list numbers: explain in plain words what the data means together and why that is the recommendation. "
            "Mention another figure (a resistance level, the volume) only when it is key to the story."
        )

        user_input = (
            f"Given the current landscape of the cryptocurrency market with the following key data points: "
            f"Bitcoin's current price at {analysis_data['current_price']:.2f} {currency}, "
            f"which is {analysis_data['diff_ma_2y_percent']:.2f}% {'above the 2-year moving average, indicating potential overvaluation,' if analysis_data['diff_ma_2y_percent'] > 0 else 'below the 2-year moving average, suggesting potential undervaluation,'} "
            f"and {analysis_data['diff_ma_2y_multiplier_percent']:.2f}% {'above the 2-year MA x5, signaling extreme overvaluation,' if analysis_data['diff_ma_2y_multiplier_percent'] > 0 else 'below the 2-year MA x5, indicating more room for growth,'} "
            f"the price changed {analysis_data['change_24h_percent']:.2f}% in 24 hours and {analysis_data['change_7d_percent']:.2f}% in 7 days, "
            f"yesterday's trading volume was {analysis_data['diff_volume_percent_last_30_days']:.2f}% away from the 30-day average, "
            f"and {analysis_data['diff_volume_percent_last_24_h']:.2f}% away from the day before, "
            f"and the Fear and Greed Index is at {analysis_data.get('fear_and_greed_index', 'not provided')} ({analysis_data.get('fear_and_greed_class') or 'no class given'}: use that name for it). "
            f"the pivot point is at {analysis_data['pivot_point']:.2f} {currency}, "
            f"with the first resistance (R1) is at {analysis_data['R1']:.2f} {currency}, "
            f"and the second resistance (R2) is at {analysis_data['R2']:.2f} {currency}. "
            f"Craft a {strategy} analysis strategy for investing in Bitcoin. "
            f"Don't write the current price or the percentages (the box below the article shows them), and conclude with a clear recommendation on whether it is a good time to buy, sell, or hold Bitcoin positions, "
            f"In case You mention any pivot or resistance points in the analysis, You'll make sure to include their values and explain what these levels typically indicate for the market. "
            f"For the long haul, here's a golden nugget: it’s usually a smart move to buy Bitcoin when its price is chillin' below the 2-year MA, kind of like snagging a bargain before the price jumps. "
            f"And when it’s partying way above the 2-year MAx5? That might be your cue to consider selling. Why? Because that's like riding the elevator to the top floor and stepping out before it heads back down. "
            f"This way, you’re maximizing your profit potential by buying low and selling high. Just remember, the crypto market can be as unpredictable as weather in April, so always do your due diligence!"
            f"When you talk about prices, let’s keep things crystal clear by sticking to the format and symbols that match our language and locale instead of write the currency code. "
            f"Provide the output in {language} aiming for a maximum of 60 words."
        )
        if previous:
            # keeps the advice steady: without it, it can flip between hold and buy from one day to the next
            user_input += (
                f" Your previous recommendation, on {previous['date']}, was to {previous['recommendation']}. "
                f"Keep it unless the data has clearly changed enough to justify a different one."
            )

        messages = [
            {"role": "system", "content": description},
            {"role": "user", "content": user_input}
        ]

        try:
            data = llm.chat_json(provider, messages, model=model)
        except llm.LLMError as e:
            logger.error(f"Bit-wise advisor: {e}")
            return {"headline": "No article today", "article": [str(e)], "recommendation": None}

        data["recommendation"] = self.parse_recommendation(data.get("recommendation"))
        return data



    def parse_recommendation(self, value):
        """buy, hold or sell. The AI sometimes answers in the article's language
        ("comprar"): the box's words of each language are accepted too."""
        word = str(value or "").strip().lower().strip(".!")
        if word in RECOMMENDATIONS:
            return word
        for texts in TEXTS.values():
            for key in RECOMMENDATIONS:
                if word == texts[key].lower():
                    return key
        return None



    def should_print(self, signal, recommendation, today, reminder_days):
        """Whether today's ticket prints the article: when the recommendation changed,
        when the last print is reminder_days old, or again on the day it was printed
        (a print can be repeated). When it prints, `signal` records it."""
        if recommendation is None:
            return True
        announced = signal.get("announced")
        if signal.get("recommendation") == recommendation and announced:
            if announced == today:
                return True
            age = (date.fromisoformat(today) - date.fromisoformat(announced)).days
            if not reminder_days or age < reminder_days:
                return False
        if signal.get("recommendation") != recommendation:
            signal["previous"] = signal.get("recommendation")
            signal["since"] = today
        signal["recommendation"] = recommendation
        signal["announced"] = today
        return True



    def render_component(self):

        language = "english"
        currency = "usd"
        strategy = "long-term conservative"
        reminder_days = DEFAULT_REMINDER_DAYS

        content_type = request.headers.get('Content-Type')
        if (content_type == 'application/json'):
            response = request.json
            for element in response:
                if element["value"]:
                    if element["name"] == "language":
                        language = element["value"]
                    elif element["name"] == "currency":
                        currency = element["value"]
                    elif element["name"] == "strategy":
                        strategy = element["value"]
                    elif element["name"] == "reminder":
                        try:
                            reminder_days = max(0, int(element["value"]))
                        except (TypeError, ValueError):
                            pass

        # the service sends X-TTP-Print from the page it prints; the editor's
        # previews don't count as printed
        printing = request.headers.get("X-TTP-Print") == "1"

        with self.state_lock:
            return self.render_article(language, currency, strategy, reminder_days, printing)



    def render_article(self, language, currency, strategy, reminder_days, printing):
        state = self.load_state()
        today = date.today().isoformat()
        # a recommendation depends on the strategy and the currency, not on the language
        signal_key = f"{strategy}|{currency}"
        signal = state.setdefault("signals", {}).setdefault(signal_key, {})

        # one article a day: the editor and the print show the same one, and the
        # AI provider isn't asked again on every load
        cache_key = f"{strategy}|{currency}|{language}"
        cached = state.setdefault("articles", {}).get(cache_key)
        # (one saved by a version before the figures box doesn't count)
        if cached and cached.get("date") == today and cached.get("figures"):
            recommendation = cached
        else:
            recommendation = self.fetch_recommendation(language, currency, strategy, signal)
            if recommendation is None:
                return render_template('bit-wise-advisor/component.html', headline="Error", article=["Market data API error, check theticketpost-service logs"])
            if recommendation["recommendation"]:
                state["articles"][cache_key] = {**recommendation, "date": today}

        if printing:
            printed = self.should_print(signal, recommendation["recommendation"], today, reminder_days)
        else:
            # the editor shows what the next print would do, without recording it
            printed = self.should_print(dict(signal), recommendation["recommendation"], today, reminder_days)
        self.save_state(state)

        if printed:
            box = self.box(recommendation, signal if printing else self.preview_signal(signal, recommendation, today), language, currency, today)
            return render_template('bit-wise-advisor/component.html', headline=recommendation["headline"], article=recommendation["article"], box=box)
        # nothing new: the service leaves the section out of the print
        return render_template('bit-wise-advisor/component.html', unchanged=True,
            recommendation=signal["recommendation"], since=signal["announced"],
            next_reminder=(date.fromisoformat(signal["announced"]) + timedelta(days=reminder_days)).isoformat() if reminder_days else None)



    def preview_signal(self, signal, recommendation, today):
        """The editor's copy of the signal, as the next print would leave it."""
        preview = dict(signal)
        self.should_print(preview, recommendation["recommendation"], today, 1)
        return preview



    def box(self, recommendation, signal, language, currency, today):
        """The figures box below the article, formatted for the language. None
        without figures (an article cached by an older version, an AI error)."""
        figures = recommendation.get("figures")
        if not figures:
            return None
        texts = TEXTS.get(language, TEXTS["english"])
        english = texts is TEXTS["english"]

        def number(value, decimals):
            text = f"{value:,.{decimals}f}"
            # 1,234.5 in English, 1.234,5 elsewhere
            return text if english else text.replace(",", " ").replace(".", ",").replace(" ", ".")

        def percent(value):
            sign = "+" if value > 0 else ""
            return f"{sign}{number(value, 1)}%" if english else f"{sign}{number(value, 1)} %"

        symbol = {"usd": "$", "eur": "€", "gbp": "£"}.get(currency, currency.upper())
        price = number(figures["current_price"], 0)
        since = signal.get("since") or signal.get("announced")
        previous = signal.get("previous")
        if not recommendation.get("recommendation"):
            note = ""
        elif previous and since == today:
            note = texts["before"].format(texts[previous])
        elif since and since != today:
            day = date.fromisoformat(since)
            note = texts["since"].format(day.strftime("%b %-d") if english else day.strftime("%d/%m"))
        else:
            note = ""
        fear_class = figures.get("fear_and_greed_class", "")
        return {
            "signal": texts[recommendation["recommendation"]] if recommendation.get("recommendation") else "",
            "note": note,
            "price": f"{symbol}{price}" if english else f"{price} {symbol}",
            "rows": [
                (texts["24h"], percent(figures["change_24h_percent"])),
                (texts["7d"], percent(figures["change_7d_percent"])),
                (texts["ma"], percent(figures["diff_ma_2y_percent"])),
                (texts["fng"], f'{figures["fear_and_greed_index"]} · {texts.get(fear_class, fear_class)}'),
            ],
        }



    def fetch_recommendation(self, language, currency, strategy, signal):
        df = self.fetch_historical_data_with_volume(currency)

        if not df.empty:
            df_ma = self.calculate_2y_ma_multiplier(df)

            if not df_ma.empty:
                latest_pivot_points = self.calculate_pivot_points(df_ma)

                analysis_data = self.get_analysis_data(df_ma, latest_pivot_points)
                previous = None
                if signal.get("recommendation"):
                    previous = {"recommendation": signal["recommendation"], "date": signal["announced"]}
                data = self.analyze_crypto_market(analysis_data, strategy, language, currency, previous)
                data["figures"] = {key: float(analysis_data[key]) for key in
                                   ("current_price", "change_24h_percent", "change_7d_percent", "diff_ma_2y_percent")}
                data["figures"]["fear_and_greed_index"] = int(analysis_data["fear_and_greed_index"])
                data["figures"]["fear_and_greed_class"] = analysis_data["fear_and_greed_class"]
                return data

        return None
