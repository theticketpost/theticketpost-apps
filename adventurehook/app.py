import os
import sys

current = os.path.dirname(os.path.realpath(__file__))
sys.path.append(current)

from theticketpost.application import Application
from flask import render_template, request
from loguru import logger
import openai
from openai.error import OpenAIError, RateLimitError
import random
import json

class App(Application):

    def __init__(self, desc):
        Application.__init__(self, __name__, __file__, desc)
        self.theme_dict = {}
        self.location_dict = {}
        self.objectives_dict = {}
        self.threats_dict = {}
        self.npcs_dict = {}
        self.adventure_type_dict = {}
        self.parse_config_parameters()



    def parse_config_parameters(self):
        for attr in self.desc["inspector_template"]:
            if attr["name"] == "theme":
                self.theme_dict = {item["value"]: item["description"] for item in attr["options"]}
            elif attr["name"] == "location":
                self.location_dict = {item["value"]: item["description"] for item in attr["options"]}
            elif attr["name"] == "objectives":
                self.objectives_dict = {item["value"]: item["description"] for item in attr["options"]}
            elif attr["name"] == "threats":
                self.threats_dict = {item["value"]: item["description"] for item in attr["options"]}
            elif attr["name"] == "npcs":
                self.npcs_dict = {item["value"]: item["description"] for item in attr["options"]}
            elif attr["name"] == "adventure_type":
                self.adventure_type_dict = {item["value"]: item["description"] for item in attr["options"]}


    # Function that generates a role-playing game adventure hook from a list of categories
    def generate_hook(self, language, theme, location, objectives, threats, npcs, adventure_type):

        # get app configuration parameters
        response = self.get_configuration_json()
        json_object = json.loads(response.data)
        api_key = next((item for item in json_object if item["name"] == "api_key"), None)
        openai.api_key = api_key["value"]

        # Concatenate the categories into a single input text string
        input_text = f"Please generate an adventure hook without listing the given parameters. " \
                    f"Generate only one role-playing game adventure hook in {language} with the following parameters:\n\n" \
                    f"Theme: {theme}\n" \
                    f"Location: {location}\n" \
                    f"Objectives: {objectives}\n" \
                    f"Threats: {threats}\n" \
                    f"NPCs: {npcs}\n" \
                    f"Type of adventure: {adventure_type}"

        try:
            # Generate a role-playing game adventure hook from the input text string using the OpenAI API

            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are an AI trained to generate short and concise role-playing game adventure hooks based on specific parameters."},
                    {"role": "user", "content": input_text}
                ],
                max_tokens=250,
                temperature=0.8
            )


            logger.info(response)
            
            # Extract the generated text from the API response
            output_text = response.choices[0].message.content

        except RateLimitError as e:
            # Handle the OpenAI API rate limit error
            print(f"OpenAI API rate limit error: {e}")
            output_text = "Sorry, I've exceeded my usage quota on the OpenAI API. Please try again later."

        except OpenAIError as e:
            # Handle other OpenAI API errors
            print(f"OpenAI API error: {e}")
            output_text = "An error occurred on the OpenAI API. Please try again later."

        return output_text



    def render_component(self):


        # Ejemplo de uso de la función generar_gancho
        language = "english"
        theme = ""
        location = ""
        objectives = ""
        threats = ""
        npcs = ""
        adventure_type = ""
        content_type = request.headers.get('Content-Type')
        if (content_type == 'application/json'):
            response = request.json
            for element in response:
                if element["value"]:
                    if element["name"] == "language":
                        language = element["value"]
                    elif element["name"] == "theme":
                        theme = self.theme_dict[element["value"]]
                    elif element["name"] == "location":
                        location = self.location_dict[element["value"]]
                    elif element["name"] == "objectives":
                        objectives = self.objectives_dict[element["value"]]
                    elif element["name"] == "threats":
                        threats = self.threats_dict[element["value"]]
                    elif element["name"] == "npcs":
                        npcs = self.npcs_dict[element["value"]]
                    elif element["name"] == "adventure_type":
                        adventure_type = self.adventure_type_dict[element["value"]]

            hook = self.generate_hook(language, theme, location, objectives, threats, npcs, adventure_type)

            return render_template('adventurehook/component.html', hook=hook)
