import base64
import hashlib
import io
import json
import os
import random
import threading
from datetime import date, timedelta

import requests
from flask import render_template, request
from loguru import logger
from PIL import Image, ImageFilter

import theticketpost.llm as llm
import theticketpost.settings
from theticketpost.application import Application


# Providers that can draw, and the model used when the app's setting is empty
IMAGE_MODELS = {
    "gemini": "gemini-2.5-flash-image",
    "openai": "gpt-image-1-mini",
    "openrouter": "google/gemini-2.5-flash-image",
}
TIMEOUT = 180

DETAIL = {
    "simple": "for young children: a few big simple shapes, very thick outlines, "
              "large areas to color, no background or a very simple one",
    "medium": "for children: clear shapes, thick outlines, a simple background",
    "detailed": "for adults: rich details and patterns, a full background, "
                "fine but solid outlines",
}

# what to draw when the idea is left empty: one per day
SURPRISES = [
    "a friendly dragon reading a book",
    "a cat astronaut floating in space",
    "an underwater castle with fish and seahorses",
    "a treehouse in a big oak tree",
    "a dinosaur having a picnic",
    "a hot air balloon over the mountains",
    "a robot watering flowers in a garden",
    "an owl family on a branch under the moon",
    "a pirate ship on the waves",
    "a unicorn in a meadow of flowers",
    "a busy farm with a tractor and animals",
    "a lighthouse by the sea with seagulls",
    "a fox in an autumn forest with mushrooms",
    "a train crossing a bridge",
    "a turtle surfing a wave",
    "a bakery shop full of cakes",
    "a knight and a castle",
    "a penguin building a snowman",
    "a jungle with a monkey, a parrot and a toucan",
    "a mandala of flowers and leaves",
]

# drawings no section has asked for in this many days are deleted
KEEP_DAYS = 14
# how many recent drawings the model is told not to repeat
DEFAULT_REMEMBER = 10
FILE_PREFIX = "coloring-"


class App(Application):

    def __init__(self, desc, flaskApp):
        Application.__init__(self, __name__, __file__, desc, flaskApp)
        # Kept next to the app's config.json: store updates don't overwrite it
        self.state_path = os.path.join(self.root_path, "state.json")
        self.files_folder = os.path.join(self.static_folder, "files")
        # the editor and the print can ask for the same drawing at once: draw it once
        self.lock = threading.Lock()


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
            logger.error(f"Coloring: could not save its state: {e}")


    def render_component(self):
        idea, detail, frequency = "", "simple", "daily"
        if request.headers.get('Content-Type') == 'application/json':
            for element in request.json:
                value = element.get("value")
                if element.get("name") == "prompt":
                    idea = (value or "").strip()
                elif element.get("name") == "detail" and value in DETAIL:
                    detail = value
                elif element.get("name") == "frequency" and value in ("daily", "fixed"):
                    frequency = value

        provider = self.get_configuration_value("llm_provider", "gemini")
        model = self.get_configuration_value("model") or IMAGE_MODELS.get(provider)
        today = date.today().isoformat()
        subject = idea or random.Random(today).choice(SURPRISES)

        with self.lock:
            try:
                name = self.drawing(provider, model, idea, subject, detail, frequency, today)
            except llm.LLMError as e:
                logger.error(f"Coloring: {e}")
                return render_template('coloring/component.html', error=f"No coloring page today: {e}")

        return render_template('coloring/component.html', image_url=self.static_url('files/' + name), subject=subject)


    def drawing(self, provider, model, idea, subject, detail, frequency, today):
        """The file name of the drawing for these settings: today's (or, with
        "fixed", the last one) when there is one, else a new one."""
        state = self.load_state()
        drawings = state.setdefault("drawings", {})
        # what was drawn lately, whatever the idea: retouching the idea to get a
        # new page must not forget what came before
        history = state.get("history")
        if isinstance(history, dict):  # 1.1.x kept one list per idea
            history = [item for items in history.values() for item in items]
        if not isinstance(history, list):
            history = []
        state["history"] = history
        key = hashlib.sha1(f"{provider}|{model}|{subject}|{detail}".encode()).hexdigest()[:16]
        entry = drawings.get(key)
        exists = entry and os.path.exists(os.path.join(self.files_folder, entry["file"]))
        if exists and (frequency == "fixed" or entry["date"] == today):
            entry["used"] = today
        else:
            remember = self.remember()
            recent = history[-remember:] if remember else []
            described = self.plan_scene(provider, subject, recent)
            logger.info(f"Coloring: drawing '{described}' with {provider} ({model})")
            image = self.generate(provider, model, self.prompt(subject, described, detail))
            png = self.to_line_art(image)
            if described != subject:  # a chosen scene, not the idea as is
                history.append(described)
                del history[:-max(remember, 1)]
            os.makedirs(self.files_folder, exist_ok=True)
            name = f"{FILE_PREFIX}{key}-{today}.png"
            with open(os.path.join(self.files_folder, name), "wb") as f:
                f.write(png)
            entry = {"file": name, "date": today, "used": today, "drawn": described}
            drawings[key] = entry
        self.clean_up(drawings, today)
        self.save_state(state)
        return entry["file"]


    def clean_up(self, drawings, today):
        oldest = (date.fromisoformat(today) - timedelta(days=KEEP_DAYS)).isoformat()
        for key in [k for k, v in drawings.items() if v.get("used", "") < oldest]:
            del drawings[key]
        keep = {v["file"] for v in drawings.values()}
        try:
            for name in os.listdir(self.files_folder):
                if name.startswith(FILE_PREFIX) and name not in keep:
                    os.remove(os.path.join(self.files_folder, name))
        except OSError:
            pass


    def remember(self):
        try:
            return max(0, int(self.get_configuration_value("remember", DEFAULT_REMEMBER)))
        except (TypeError, ValueError):
            return DEFAULT_REMEMBER


    def plan_scene(self, provider, idea, recent):
        """The concrete scene to draw, chosen by the provider's text model.

        Image models don't follow "don't draw these": a list of recent owlbears
        made them draw more owlbears. A text model picks a scene that differs
        from the recent ones, and the image model only gets that scene.
        Falls back to the idea itself if the text model fails."""
        lines = [f"The idea: {idea}"]
        if recent:
            lines.append("Pages already drawn lately. Choose a different main character "
                         "AND a different activity than every one of these:")
            lines += [f"- {item}" for item in recent]
        # models asked to pick "randomly" pick the same thing every time
        lines.append(f"Random number to make any open choice with: {random.randint(1000, 9999)}. "
                     "Avoid the most obvious option.")
        messages = [
            {"role": "system", "content":
                "You choose the scene for a coloring book page. Answer with one "
                "line only, in English, at most 25 words: the character, what it is doing "
                "and where. No preamble, no quotes."},
            {"role": "user", "content": "\n".join(lines)},
        ]
        try:
            scene = self.first_line(llm.chat(provider, messages))
        except llm.LLMError as e:
            logger.warning(f"Coloring: couldn't choose a scene, drawing the idea as is: {e}")
            scene = ""
        return scene or idea[:200]


    def prompt(self, idea, scene, detail):
        prompt = (f"A coloring book page of: {scene}. "
                  f"Black line art on a pure white background, {DETAIL[detail]}. "
                  "Only black outlines: no color, no gray, no shading, no hatching, "
                  "no large filled black areas, no text, no border or frame. "
                  "The whole drawing fits inside the page, portrait orientation.")
        if scene != idea:
            # the request it comes from may say how it should look
            prompt += ("\n\nDraw exactly that scene. The request it was chosen from, "
                       f"for the style only: {idea}")
        return prompt


    @staticmethod
    def first_line(text):
        """The first line the model wrote, without markdown, quotes or a
        "Scene:" style label."""
        for line in (text or "").splitlines():
            line = line.strip().strip("*#-\"' ").strip()
            label, sep, rest = line.partition(":")
            if sep and len(label.split()) <= 2 and rest.strip():
                line = rest.strip(" *_\"'")
            if line:
                return line[:200]
        return ""


    # --- image generation -------------------------------------------------

    def generate(self, provider, model, prompt):
        """PNG/JPEG bytes from the provider. Raises llm.LLMError."""
        if provider not in IMAGE_MODELS:
            name = llm.PROVIDERS.get(provider, {}).get("name", provider)
            raise llm.LLMError(f"{name} can't draw images: choose Google Gemini, OpenAI or OpenRouter in the app's settings")
        if not llm.is_configured(provider):
            raise llm.LLMError(f"{llm.PROVIDERS[provider]['name']} is not set up: add it in Settings > AI providers")
        config = llm.provider_settings(provider)
        base_url = (config.get("base_url") or llm.PROVIDERS[provider]["base_url"]).rstrip("/")
        key = config.get("api_key", "")
        if provider == "gemini":
            return self.generate_gemini(base_url, key, model, prompt)
        if provider == "openai":
            return self.generate_openai(base_url, key, model, prompt)
        return self.generate_openrouter(base_url, key, model, prompt)


    def post(self, provider, url, body, headers):
        name = llm.PROVIDERS[provider]["name"]
        try:
            response = requests.post(url, json=body, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as e:
            raise llm.LLMError(f"Could not reach {name}: {type(e).__name__}") from e
        if response.status_code != 200:
            raise llm.LLMError(f"{name} error {response.status_code}: {llm.error_message(response)}")
        try:
            return response.json()
        except ValueError as e:
            raise llm.LLMError(f"Unexpected answer from {name}") from e


    def generate_gemini(self, base_url, key, model, prompt):
        # images come from the native API, not the OpenAI compatible one the chats use
        if base_url.endswith("/openai"):
            base_url = base_url[:-len("/openai")]
        data = self.post("gemini", f"{base_url}/models/{model}:generateContent",
                         {"contents": [{"parts": [{"text": prompt}]}],
                          "generationConfig": {"responseModalities": ["IMAGE"],
                                               "imageConfig": {"aspectRatio": "3:4"}}},
                         {"Content-Type": "application/json", "x-goog-api-key": key})
        texts = []
        image = None
        for candidate in data.get("candidates") or []:
            for part in (candidate.get("content") or {}).get("parts") or []:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data") and image is None:
                    image = base64.b64decode(inline["data"])
                elif part.get("text") and not part.get("thought"):
                    texts.append(part["text"])
            if image is not None:
                return image
            if candidate.get("finishReason") not in (None, "STOP"):
                texts.append(candidate["finishReason"])
        block = (data.get("promptFeedback") or {}).get("blockReason")
        reason = block or " ".join(texts)[:200] or "no image in the answer"
        raise llm.LLMError(f"Google Gemini didn't draw it: {reason}")


    def generate_openai(self, base_url, key, model, prompt):
        data = self.post("openai", f"{base_url}/images/generations",
                         {"model": model, "prompt": prompt, "size": "1024x1536", "quality": "medium", "n": 1},
                         {"Content-Type": "application/json", "Authorization": "Bearer " + key})
        try:
            return base64.b64decode(data["data"][0]["b64_json"])
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise llm.LLMError("OpenAI didn't draw it: no image in the answer") from e


    def generate_openrouter(self, base_url, key, model, prompt):
        data = self.post("openrouter", f"{base_url}/chat/completions",
                         {"model": model, "messages": [{"role": "user", "content": prompt}],
                          "modalities": ["image", "text"], "image_config": {"aspect_ratio": "3:4"}},
                         {"Content-Type": "application/json", "Authorization": "Bearer " + key})
        try:
            url = data["choices"][0]["message"]["images"][0]["image_url"]["url"]
            return base64.b64decode(url.split(",", 1)[1])
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise llm.LLMError(f"OpenRouter didn't draw it: is {model} an image model?") from e


    # --- printing ----------------------------------------------------------

    def to_line_art(self, data):
        """The drawing as a 1-bit PNG exactly as wide as the ticket, so the
        browser doesn't scale it and the lines print sharp and black."""
        try:
            img = Image.open(io.BytesIO(data))
            img.load()
        except Exception as e:
            raise llm.LLMError("The drawing isn't a valid image") from e
        if img.mode in ("RGBA", "LA", "P"):
            # a transparent background is white on paper
            img = img.convert("RGBA")
            background = Image.new("RGBA", img.size, "white")
            img = Image.alpha_composite(background, img)
        img = img.convert("L")

        # use the whole width of the paper: crop the white margins
        bbox = self.content_bbox(img)
        if bbox:
            pad = max(4, img.width // 50)
            img = img.crop((max(0, bbox[0] - pad), max(0, bbox[1] - pad),
                            min(img.width, bbox[2] + pad), min(img.height, bbox[3] + pad)))

        device = theticketpost.settings.get_json("config").get("printer", {}).get("device") or {}
        width = int(device.get("dots_per_line", 384))
        scale = img.width / width
        if scale >= 2:
            # thicken the lines first, or thin ones break up when scaled down
            img = img.filter(ImageFilter.MinFilter(3 if scale < 4 else 5))
        img = img.resize((width, max(1, round(img.height / scale))), Image.LANCZOS)
        img = img.point(lambda v: 255 if v > 190 else 0).convert("1", dither=Image.Dither.NONE)

        out = io.BytesIO()
        img.save(out, "PNG")
        return out.getvalue()


    def content_bbox(self, img):
        """Box around the drawing, leaving out specks: a stray dot the model
        left near the edge would otherwise keep a wide white margin."""
        # scan a coarse grid (cells of `cell` px): fast enough in pure Python
        cell = max(1, min(img.size) // 256)
        dark = img.point(lambda v: 255 if v < 160 else 0)
        small = dark.reduce(cell) if cell > 1 else dark
        w, h = small.size
        pixels = small.load()
        seen = bytearray(w * h)
        # keep marks of at least ~1/40 of the width across (a bubble, a star)
        min_size = max(2, w // 40)
        box = None
        for start in range(w * h):
            if seen[start] or not pixels[start % w, start // w]:
                continue
            # flood fill one mark, 8-connected
            seen[start] = 1
            stack = [start]
            x0, y0, x1, y1 = w, h, 0, 0
            while stack:
                i = stack.pop()
                x, y = i % w, i // w
                x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
                for ny in (y - 1, y, y + 1):
                    if 0 <= ny < h:
                        for nx in (x - 1, x, x + 1):
                            if 0 <= nx < w:
                                j = ny * w + nx
                                if not seen[j] and pixels[nx, ny]:
                                    seen[j] = 1
                                    stack.append(j)
            if max(x1 - x0, y1 - y0) + 1 < min_size:
                continue
            box = (x0, y0, x1, y1) if box is None else \
                (min(box[0], x0), min(box[1], y0), max(box[2], x1), max(box[3], y1))
        if box is None:
            return dark.getbbox()
        return (box[0] * cell, box[1] * cell,
                min(img.width, (box[2] + 1) * cell), min(img.height, (box[3] + 1) * cell))
