import os
import sys

current = os.path.dirname(os.path.realpath(__file__))
sys.path.append(current)

from theticketpost.application import Application
from flask import render_template, request, jsonify, abort
from loguru import logger
from urllib.parse import quote
import datetime
import json
import threading
import uuid


DEFAULT_LIST = "To do"


class App(Application):
    """To-do lists kept in state.json, by name. Each section picks its list in
    the inspector ("List") and links to the app's own page to edit it
    (/api/apps/checklist/tasks?list=<name>). A task ticked off on day D still
    prints, crossed out, on D and D+1, and is gone from D+2."""

    def __init__(self, desc, flaskApp):
        Application.__init__(self, __name__, __file__, desc, flaskApp)
        # Kept next to the app's code: store updates don't overwrite it.
        self.state_path = os.path.join(self.root_path, "state.json")
        self.lock = threading.Lock()


    def handlers(self):
        handlers = Application.handlers(self)
        handlers['tasks'] = (self.tasks_page, ['GET'])
        handlers['list'] = (self.list_tasks, ['GET'])
        handlers['add'] = (self.add_task, ['POST'])
        handlers['toggle'] = (self.toggle_task, ['POST'])
        handlers['edit'] = (self.edit_task, ['POST'])
        handlers['delete'] = (self.delete_task, ['POST'])
        return handlers


    # ---- state ----

    def today(self):
        return datetime.date.today()


    def list_name(self, value):
        name = " ".join(str(value or "").split())[:60]
        return name or DEFAULT_LIST


    def tidy(self, text):
        """One line, single spaces, starting with a capital letter (after any
        leading "¿" or "¡")."""
        text = " ".join(str(text or "").split())[:200]
        for i, char in enumerate(text):
            if char.isalpha():
                return text[:i] + char.upper() + text[i + 1:]
            if char.isalnum():
                break
        return text


    def load_lists(self):
        try:
            with open(self.state_path) as f:
                state = json.load(f)
        except (OSError, ValueError):
            return {}
        lists = state.get("lists")
        if not isinstance(lists, dict):
            lists = {}
        # 1.0.0 kept a single list
        if isinstance(state.get("tasks"), list):
            lists.setdefault(DEFAULT_LIST, []).extend(state["tasks"])
        lists = {name: [task for task in tasks if isinstance(task, dict) and task.get("id")]
                 for name, tasks in lists.items() if isinstance(tasks, list)}
        # tasks saved before they were tidied
        for tasks in lists.values():
            for task in tasks:
                task["text"] = self.tidy(task.get("text"))
        return lists


    def save_lists(self, lists):
        lists = {name: tasks for name, tasks in lists.items() if tasks}
        tmp = self.state_path + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump({"lists": lists}, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.state_path)
        except OSError as e:
            logger.error(f"checklist: could not save the tasks: {e}")


    def still_shown(self, task):
        """Pending, or done today or yesterday."""
        done = task.get("done")
        if not done:
            return True
        try:
            done = datetime.date.fromisoformat(done)
        except ValueError:
            return False
        return done >= self.today() - datetime.timedelta(days=1)


    def current_lists(self):
        """All the lists without the tasks done before yesterday, which are dropped for good."""
        lists = self.load_lists()
        changed = False
        for name, tasks in lists.items():
            kept = [task for task in tasks if self.still_shown(task)]
            if len(kept) != len(tasks):
                lists[name] = kept
                changed = True
        if changed:
            self.save_lists(lists)
        return lists


    # ---- ticket ----

    def render_component(self):
        title = DEFAULT_LIST
        name = DEFAULT_LIST
        if request.headers.get('Content-Type') == 'application/json':
            for element in request.json or []:
                if element.get("name") == "title":
                    title = element.get("value") or ""
                elif element.get("name") == "list":
                    name = self.list_name(element.get("value"))
        printing = request.headers.get("X-TTP-Print") == "1"

        with self.lock:
            tasks = self.current_lists().get(name, [])
        pending = [task for task in tasks if not task.get("done")]
        done = [task for task in tasks if task.get("done")]

        return render_template('checklist/component.html',
                               style_url=self.static_url('style.css'),
                               tasks_url='/api/apps/' + self.name + '/tasks?list=' + quote(name),
                               title=title, list_name=name, pending=pending, done=done,
                               printing=printing)


    # ---- task page and its API ----

    def tasks_page(self):
        return render_template('checklist/tasks.html', api='/api/apps/' + self.name,
                               list_name=self.list_name(request.args.get("list")))


    def answer(self, lists, name):
        names = sorted(set(lists) | {name}, key=str.casefold)
        return jsonify({"list": name, "lists": names, "tasks": lists.get(name, [])})


    def list_tasks(self):
        name = self.list_name(request.args.get("list"))
        with self.lock:
            return self.answer(self.current_lists(), name)


    def body(self):
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}


    def add_task(self):
        data = self.body()
        name = self.list_name(data.get("list"))
        text = self.tidy(data.get("text"))
        if not text:
            abort(400)
        with self.lock:
            lists = self.current_lists()
            lists.setdefault(name, []).append({"id": uuid.uuid4().hex, "text": text,
                                               "created": self.today().isoformat(), "done": None})
            self.save_lists(lists)
            return self.answer(lists, name)


    def toggle_task(self):
        data = self.body()
        name = self.list_name(data.get("list"))
        with self.lock:
            lists = self.current_lists()
            task = next((task for task in lists.get(name, []) if task["id"] == data.get("id")), None)
            if task is None:
                abort(404)
            task["done"] = self.today().isoformat() if data.get("done") else None
            self.save_lists(lists)
            return self.answer(lists, name)


    def edit_task(self):
        data = self.body()
        name = self.list_name(data.get("list"))
        text = self.tidy(data.get("text"))
        if not text:
            abort(400)
        with self.lock:
            lists = self.current_lists()
            task = next((task for task in lists.get(name, []) if task["id"] == data.get("id")), None)
            if task is None:
                abort(404)
            task["text"] = text
            self.save_lists(lists)
            return self.answer(lists, name)


    def delete_task(self):
        data = self.body()
        name = self.list_name(data.get("list"))
        with self.lock:
            lists = self.current_lists()
            lists[name] = [task for task in lists.get(name, []) if task["id"] != data.get("id")]
            self.save_lists(lists)
            return self.answer(lists, name)
