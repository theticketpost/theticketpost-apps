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
from openai import OpenAI
import json

class App(Application):

    def __init__(self, desc, flaskApp):
        Application.__init__(self, __name__, __file__, desc, flaskApp)



    def fetch_historical_data_with_volume(self, from_timestamp, to_timestamp, currency):
        url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart/range"
        params = {
            'vs_currency': currency,
            'from': from_timestamp,
            'to': to_timestamp
        }
        response = requests.get(url, params=params)
        data = response.json()

        prices = data['prices']
        volumes = data['total_volumes']
        df = pd.DataFrame(prices, columns=['timestamp', 'price'])
        df_volume = pd.DataFrame(volumes, columns=['timestamp', 'volume'])
        df['volume'] = df_volume['volume']
        df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('date', inplace=True)
        return df



    def fetch_historical_data_min_max_close(self, from_timestamp, to_timestamp, currency):
        url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart/range"

        params = {
            'vs_currency': currency,
            'from': from_timestamp,
            'to': to_timestamp
        }
        response = requests.get(url, params=params)
        data = response.json()

        prices = data['prices']
        df = pd.DataFrame(prices, columns=['timestamp', 'price'])
        df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('date', inplace=True)

        daily_df = pd.DataFrame()
        daily_df['daily_max'] = df['price'].resample('D').max()
        daily_df['daily_min'] = df['price'].resample('D').min()
        daily_df['daily_close'] = df['price'].resample('D').last()

        return daily_df



    def calculate_pivot_points(self, df):
        df['pivot_point'] = (df['daily_max'] + df['daily_min'] + df['daily_close']) / 3
        df['R1'] = 2 * df['pivot_point'] - df['daily_min']
        df['R2'] = df['pivot_point'] + (df['daily_max'] - df['daily_min'])

        latest_pivot = df['pivot_point'].iloc[-1]
        latest_R1 = df['R1'].iloc[-1]
        latest_R2 = df['R2'].iloc[-1]

        result = {
            'pivot_point': latest_pivot,
            'R1': latest_R1,
            'R2': latest_R2,
        }
        
        return result



    def calculate_2y_ma_multiplier(self, df):
        # Assuming 365 days per year, so 730 represents roughly 2 years
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



    def fetch_crypto_data(self, currency):
        url = 'https://api.coingecko.com/api/v3/coins/markets'
        params = {
            'vs_currency': currency,
            'ids': 'bitcoin',
        }
        response = requests.get(url, params=params)
        data = response.json()

        results = {
            'price': data[-1]["current_price"],
            'volume': data[-1]["total_volume"]
        }

        return results



    def calculate_average_volume_last_x_days(self, df, days):
        df_sorted = df.sort_index()

        last_date = df_sorted.index[-1]
        
        start_date = last_date - timedelta(days=days)
        
        df_filtered = df_sorted.loc[start_date:last_date]

        average_volume = df_filtered['volume'].mean()
        
        return average_volume



    def get_analysis_data(self, df, current_data, latest_pivot_points):
        last_row = df.iloc[-1]
        ma_2y = last_row['MA_2y']
        ma_2y_multiplier = last_row['MA_2y_multiplier']
        volume_mean_last_30_days = self.calculate_average_volume_last_x_days(df, 30)
        fear_and_greed_index = self.fetch_fear_and_greed_index(1).iloc[-1]['fear_and_greed_index']

        diff_ma_2y = current_data['price'] - ma_2y
        diff_ma_2y_percent = (diff_ma_2y / ma_2y) * 100
        diff_ma_2y_multiplier = current_data['price'] - ma_2y_multiplier
        diff_ma_2y_multiplier_percent = (diff_ma_2y_multiplier / ma_2y_multiplier) * 100
        diff_volume_last_30_days = current_data['volume'] - volume_mean_last_30_days
        diff_volume_percent_last_30_days = ( diff_volume_last_30_days / volume_mean_last_30_days ) * 100
        
        df_sorted = df.sort_index()
        diff_volume_last_24_h = current_data['volume'] - df_sorted['volume'].iloc[-1]
        diff_volume_percent_last_24_h = ( diff_volume_last_24_h / df_sorted['volume'].iloc[-1] ) * 100

        results = {
            'current_price': current_data['price'],
            'current_volume': current_data['volume'],
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
            'R2': latest_pivot_points['R2']
        }
        
        return results



    def analyze_crypto_market(self, analysis_data, strategy, language='English', currency='usd'):

        # get app configuration parameters
        response = self.get_configuration_json()
        json_object = json.loads(response.data)
        api_key = next((item for item in json_object if item["name"] == "api_key"), None)

        client = OpenAI(
            api_key=api_key["value"]
        )

        description = (
            "Imagine you're an economic journalist tasked with creating a compelling story about Bitcoin's latest market dynamics, using key data indicators. "
            "Is not allowed markdown. Your assignment is to produce a JSON output with two sections: a 'headline' and an 'article'. The 'article' should be presented as a list of paragraphs, each containing plain text (not JSON objects). "
            "The headline needs to succinctly summarize Bitcoin's current market status. The article should then offer a deep dive into Bitcoin's recent market behavior."
            "Please keep the entire article concise, aiming for a maximum of 60 words to ensure it's digestible and impactful for a wide audience. This constraint challenges you to distill your insights into the most engaging and informative essence possible."
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
            f"Craft a {strategy} analysis strategy for investing in Bitcoin. "
            f"Incorporate the current price into the narrative and conclude with a clear recommendation on whether it is a good time to buy, sell, or hold Bitcoin positions, "
            f"considering the provided market data and indicators. "
            f"Imagine you are drafting a concise market insight section for a financial newspaper, aimed at guiding readers through the current investment climate for Bitcoin. "
            f"Your summary should blend both strategies into a seamless narrative, highlighting key decision points and market indicators, "
            f"and conclude with an actionable advice reflecting the current market conditions. "
            f"Remember to prominently incorporate the current Bitcoin price within your analysis and conclusion. "
            f"In case You mention any pivot or resistance points in the analysis, You'll make sure to include their values and explain what these levels typically indicate for the market. "
            f"For the long haul, here's a golden nugget: it’s usually a smart move to buy Bitcoin when its price is chillin' below the 2-year MA, kind of like snagging a bargain before the price jumps. "
            f"And when it’s partying way above the 2-year MAx5? That might be your cue to consider selling. Why? Because that's like riding the elevator to the top floor and stepping out before it heads back down. "
            f"This way, you’re maximizing your profit potential by buying low and selling high. Just remember, the crypto market can be as unpredictable as weather in April, so always do your due diligence!"
            f"When you talk about prices, let’s keep things crystal clear by sticking to the format and symbols that match our language and locale instead of write the currency code. "
            f"Provide the output in {language}."
        )

        messages = [
            {"role": "system", "content": description},
            {"role": "user", "content": user_input}
        ]

        try:
            completion = client.chat.completions.create(
                messages = messages,
                model = "gpt-4-0125-preview",
            )

            logger.info(completion)

        except openai.error.OpenAIError as e:
            completion = f"OpenAI API error: {e}"


        data = json.loads(completion.choices[0].message.content)

        return data



    def render_component(self):

        language = "english"
        currency = "usd"
        strategy = "long-term conservative"

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
        
            now = datetime.now()
            to_date = datetime(now.year, now.month, now.day)
            to_timestamp = int(to_date.timestamp())


            df = self.fetch_historical_data_with_volume((to_date - timedelta(days=730)).timestamp(), to_timestamp, currency)
            df_ma = self.calculate_2y_ma_multiplier(df)

            df_min_max_last = self.fetch_historical_data_min_max_close((to_date - timedelta(days=30)).timestamp(), (to_date).timestamp(), currency) 
            latest_pivot_points = self.calculate_pivot_points(df_min_max_last)

            current_price = self.fetch_crypto_data(currency)
            analysis_data = self.get_analysis_data(df_ma, current_price, latest_pivot_points)
            recommendation = self.analyze_crypto_market(analysis_data, strategy, language, currency)

            return render_template('bit-wise-advisor/component.html', headline=recommendation["headline"], article=recommendation["article"])
