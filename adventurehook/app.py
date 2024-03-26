import os
import sys

current = os.path.dirname(os.path.realpath(__file__))
sys.path.append(current)

from theticketpost.application import Application
from flask import render_template, request
from loguru import logger
from openai import OpenAI
import random
import json

class App(Application):

    def __init__(self, desc, flaskApp):
        Application.__init__(self, __name__, __file__, desc, flaskApp)
        self.dicts = { "theme": [], "location": [], "objetives": [], "threats": [], "npcs": [], "adventure_type": [] }
        for attr in self.desc["inspector_template"]:
            self.dicts[attr["name"]] = [ item["value"] for item in attr["options"] ]


    def get_parameter(self, element):
        if ( element["name"] in self.dicts ):
            max_index = len(self.dicts[element["name"]]) - 1
            random_index = random.randint(1, max_index)
            return element["value"] if element["value"] != "random" else self.dicts[element["name"]][random_index]



    # Function that generates a role-playing game adventure hook from a list of categories
    def generate_hook(self, language, theme, location, objectives, threats, npcs, adventure_type):

        # get app configuration parameters
        response = self.get_configuration_json()
        json_object = json.loads(response.data)
        api_key = next((item for item in json_object if item["name"] == "api_key"), None)

        client = OpenAI(
            api_key=api_key["value"]
        )

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

            response = client.chat.completions.create(
                model="gpt-4-0125-preview",
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

        except openai.error.OpenAIError as e:
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
                        theme = self.get_parameter(element)
                    elif element["name"] == "location":
                        location = self.get_parameter(element)
                    elif element["name"] == "objectives":
                        objectives = self.get_parameter(element)
                    elif element["name"] == "threats":
                        threats = self.get_parameter(element)
                    elif element["name"] == "npcs":
                        npcs = self.get_parameter(element)
                    elif element["name"] == "adventure_type":
                        adventure_type = self.get_parameter(element)

            hook = self.generate_hook(language, theme, location, objectives, threats, npcs, adventure_type)

            return render_template('adventurehook/component.html', hook=hook, theme=theme)
