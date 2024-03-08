import os
import sys

current = os.path.dirname(os.path.realpath(__file__))
sys.path.append(current)

from theticketpost.application import Application
from flask import render_template, request
from loguru import logger
import requests


class App(Application):

    def __init__(self, desc, flaskApp):
        Application.__init__(self, __name__, __file__, desc, flaskApp)
        self.flaskApp.template_filter('custom_format')(self.custom_format)

    def custom_format(self, value):
        value = float(value)

        if int(value) == 0 and value != 0.0:
            value_str = f"{value:.16f}"
            first_non_zero = next((i for i, ch in enumerate(value_str.split('.')[1]) if ch != '0'), None)
            significant_digits = min(len(value_str.split('.')[1]), first_non_zero + 4)
            formatted_value = f"{value:.{significant_digits}f}".rstrip('0')
            return formatted_value
        else:
            return f"{value:.2f}"



    def currency_symbol_filter(self, currency_code):
        symbols = {
            'usd': { 'symbol': '$', 'position' : 'before' }, 
            'eur': { 'symbol': '€', 'position' : 'after' },
            'gbp': { 'symbol': '£', 'position' : 'before' }
        }
        return symbols.get(currency_code, { 'symbol': 'kk', 'position' : 'before' })



    def fetch_crypto_data(self, crypto_ids, currency):
        url = 'https://api.coingecko.com/api/v3/coins/markets'
        params = {
            'vs_currency': currency,
            'ids': crypto_ids,
        }
        response = requests.get(url, params=params)
        data = response.json()

        logger.debug(data)
        return data



    def render_component(self):
        content_type = request.headers.get('Content-Type')
        if (content_type == 'application/json'):
            response = request.json
            currency = ""
            crypto_list = ""
            for element in response:
                if element["name"] == "currency":
                    currency = element["value"]
                elif element["name"] == "crypto_list":
                    crypto_list = element["value"]

            crypto_data = self.fetch_crypto_data(crypto_list, currency)
            currency = self.currency_symbol_filter(currency)
            return render_template('cryptomarket/component.html', crypto_data=crypto_data, currency=currency)

