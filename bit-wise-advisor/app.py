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
        volume_mean_last_30_days = self.calculate_average_volume_last_x_days(df, 30)
        fear_and_greed_index = self.fetch_fear_and_greed_index(1).iloc[-1]['fear_and_greed_index']

        diff_ma_2y = df['price'].iloc[-1] - ma_2y
        diff_ma_2y_percent = (diff_ma_2y / ma_2y) * 100
        diff_ma_2y_multiplier = df['price'].iloc[-1] - ma_2y_multiplier
        diff_ma_2y_multiplier_percent = (diff_ma_2y_multiplier / ma_2y_multiplier) * 100
        diff_volume_last_30_days = df['volume'].iloc[-1] - volume_mean_last_30_days
        diff_volume_percent_last_30_days = ( diff_volume_last_30_days / volume_mean_last_30_days ) * 100
        
        diff_volume_last_24_h = df['volume'].iloc[-1] - df['volume'].iloc[-2]
        diff_volume_percent_last_24_h = ( diff_volume_last_24_h / df['volume'].iloc[-2] ) * 100

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
            "'recommendation' is the advice the article concludes with, as one of those three English words. "
            "The headline needs to succinctly summarize Bitcoin's current market status. The article should then offer a deep dive into Bitcoin's recent market behavior. "
            "Please ensure that you divide your ideas into separate short paragraphs. This will enhance the readability of the text once it is printed. "
            "Please keep the entire article concise, aiming for a maximum of 100 words to ensure it's digestible and impactful for a wide audience. This constraint challenges you to distill your insights into the most engaging and informative essence possible."
        )

        user_input = (
            f"Given the current landscape of the cryptocurrency market with the following key data points: "
            f"Bitcoin's current price at {analysis_data['current_price']:.2f} {currency}, "
            f"which is {analysis_data['diff_ma_2y_percent']:.2f}% {'above the 2-year moving average, indicating potential overvaluation,' if analysis_data['diff_ma_2y_percent'] > 0 else 'below the 2-year moving average, suggesting potential undervaluation,'} "
            f"and {analysis_data['diff_ma_2y_multiplier_percent']:.2f}% {'above the 2-year MA x5, signaling extreme overvaluation,' if analysis_data['diff_ma_2y_multiplier_percent'] > 0 else 'below the 2-year MA x5, indicating more room for growth,'} "
            f"the trading volume has changed by {analysis_data['diff_volume_percent_last_30_days']:.2f}% compared to the last 30-day volume average, "
            f"the trading volume has changed by {analysis_data['diff_volume_percent_last_24_h']:.2f}% compared to the last 24 hours, "
            f"and the Fear and Greed Index is at {analysis_data.get('fear_and_greed_index', 'not provided')}. "
            f"the pivot point is at {analysis_data['pivot_point']:.2f} {currency}, "
            f"with the first resistance (R1) is at {analysis_data['R1']:.2f} {currency}, "
            f"and the second resistance (R2) is at {analysis_data['R2']:.2f} {currency}. "
            f"Analyzing the percentage change in daily prices over the past {analysis_data['days_price_change_24h']} days reveals a {analysis_data['trend_price_change_24h']} trend in price variations, characterized by a slope of {analysis_data['slope_price_change_24h']:.2f}, "
            f"indicating a {'stronger' if abs(analysis_data['slope_price_change_24h']) > 0.5 else 'moderate'} trend in price movement. "
            f"Craft a {strategy} analysis strategy for investing in Bitcoin. "
            f"Incorporate the current price into the narrative and conclude with a clear recommendation on whether it is a good time to buy, sell, or hold Bitcoin positions, "
            f"In case You mention any pivot or resistance points in the analysis, You'll make sure to include their values and explain what these levels typically indicate for the market. "
            f"For the long haul, here's a golden nugget: it’s usually a smart move to buy Bitcoin when its price is chillin' below the 2-year MA, kind of like snagging a bargain before the price jumps. "
            f"And when it’s partying way above the 2-year MAx5? That might be your cue to consider selling. Why? Because that's like riding the elevator to the top floor and stepping out before it heads back down. "
            f"This way, you’re maximizing your profit potential by buying low and selling high. Just remember, the crypto market can be as unpredictable as weather in April, so always do your due diligence!"
            f"When you talk about prices, let’s keep things crystal clear by sticking to the format and symbols that match our language and locale instead of write the currency code. "
            f"Provide the output in {language} aiming for a maximum of 100 words."
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

        recommendation = str(data.get("recommendation", "")).strip().lower()
        data["recommendation"] = recommendation if recommendation in RECOMMENDATIONS else None
        return data



    def should_print(self, signal, recommendation, today, reminder_days):
        """Whether today's ticket prints the article: when the recommendation changed,
        when the last print is reminder_days old, or again on the day it was printed
        (the editor and the print render it more than once). Updates `signal`."""
        if recommendation is None:
            return True
        announced = signal.get("announced")
        if signal.get("recommendation") == recommendation and announced:
            if announced == today:
                return True
            age = (date.fromisoformat(today) - date.fromisoformat(announced)).days
            if not reminder_days or age < reminder_days:
                return False
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

        with self.state_lock:
            return self.render_article(language, currency, strategy, reminder_days)



    def render_article(self, language, currency, strategy, reminder_days):
        state = self.load_state()
        today = date.today().isoformat()
        # a recommendation depends on the strategy and the currency, not on the language
        signal = state.setdefault("signals", {}).setdefault(f"{strategy}|{currency}", {})

        # one article a day: the editor and the print show the same one, and the
        # AI provider isn't asked again on every load
        cache_key = f"{strategy}|{currency}|{language}"
        cached = state.setdefault("articles", {}).get(cache_key)
        if cached and cached.get("date") == today:
            recommendation = cached
        else:
            recommendation = self.fetch_recommendation(language, currency, strategy, signal)
            if recommendation is None:
                return render_template('bit-wise-advisor/component.html', headline="Error", article=["Market data API error, check theticketpost-service logs"])
            if recommendation["recommendation"]:
                state["articles"][cache_key] = {**recommendation, "date": today}

        printed = self.should_print(signal, recommendation["recommendation"], today, reminder_days)
        self.save_state(state)

        if printed:
            return render_template('bit-wise-advisor/component.html', headline=recommendation["headline"], article=recommendation["article"])
        # nothing new: the service leaves the section out of the print
        return render_template('bit-wise-advisor/component.html', unchanged=True,
            recommendation=signal["recommendation"], since=signal["announced"],
            next_reminder=(date.fromisoformat(signal["announced"]) + timedelta(days=reminder_days)).isoformat() if reminder_days else None)



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
                return self.analyze_crypto_market(analysis_data, strategy, language, currency, previous)

        return None
