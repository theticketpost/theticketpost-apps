import os
import sys

current = os.path.dirname(os.path.realpath(__file__))
sys.path.append(current)

from theticketpost.application import Application
from flask import render_template, request
from markupsafe import Markup
from loguru import logger
import datetime
import re
import threading
import requests
import chess
import chess.svg

DAILY_URL = "https://lichess.org/api/puzzle/daily"
TIMEOUT = 15

# Colors for a 1-bit thermal print: light squares white, dark squares a mid
# grey that dithers to an even dot pattern, no dark band around the board.
BOARD_COLORS = {
    "square light": "#FFFFFF",
    "square dark": "#A8A8A8",
    "margin": "#FFFFFF",
    "coord": "#000000",
}

# Lichess themes worth saying, as https://lichess.org/training/themes names them
THEMES = {
    "fork": "Fork", "pin": "Pin", "skewer": "Skewer", "discoveredAttack": "Discovered attack",
    "doubleCheck": "Double check", "sacrifice": "Sacrifice", "deflection": "Deflection",
    "attraction": "Attraction", "clearance": "Clearance", "interference": "Interference",
    "intermezzo": "Intermezzo", "quietMove": "Quiet move", "xRayAttack": "X-ray attack",
    "zugzwang": "Zugzwang", "trappedPiece": "Trapped piece", "hangingPiece": "Hanging piece",
    "capturingDefender": "Remove the defender", "promotion": "Promotion",
    "underPromotion": "Underpromotion", "enPassant": "En passant", "castling": "Castling",
    "backRankMate": "Back rank mate", "smotheredMate": "Smothered mate",
    "attackingF2F7": "Attack on f2/f7", "kingsideAttack": "Kingside attack",
    "queensideAttack": "Queenside attack", "defensiveMove": "Defensive move",
    "endgame": "Endgame", "middlegame": "Middlegame", "opening": "Opening",
}


class App(Application):
    """Lichess' daily puzzle. The API gives the position (FEN), the move the
    opponent just played, and the solution in UCI: the solver's moves, with the
    opponent's forced replies in between."""

    def __init__(self, desc, flaskApp):
        Application.__init__(self, __name__, __file__, desc, flaskApp)
        # one puzzle a day: don't ask Lichess again on every render
        self.cache = {}
        self.lock = threading.Lock()


    def fetch_daily(self):
        today = datetime.date.today()
        with self.lock:
            if self.cache.get("date") == today:
                return self.cache["data"]
        response = requests.get(DAILY_URL, headers={"Accept": "application/json"}, timeout=TIMEOUT)
        response.raise_for_status()
        data = response.json()
        with self.lock:
            self.cache = {"date": today, "data": data}
        return data


    def goal(self, themes, solver):
        for theme in themes:
            match = re.fullmatch(r"mateIn(\d)", theme)
            if match:
                moves = int(match.group(1))
                return f"{solver} to play and mate in {moves}" if moves > 1 else f"{solver} to play and mate"
        if "crushing" in themes or "advantage" in themes:
            return f"{solver} to play and win"
        if "equality" in themes:
            return f"{solver} to play and save the game"
        return f"{solver} to play: find the best move"


    def build(self, data):
        puzzle, game = data["puzzle"], data["game"]
        board = chess.Board(puzzle["fen"]) if puzzle.get("fen") else self.board_from_pgn(game["pgn"])
        solver = "White" if board.turn == chess.WHITE else "Black"

        last_move = ""
        if puzzle.get("lastMove"):
            # the FEN is the position after it: replay it on the position before to get its name
            move = chess.Move.from_uci(puzzle["lastMove"])
            before = self.board_from_pgn(game["pgn"], drop_last=True) if game.get("pgn") else None
            if before is not None and move in before.legal_moves:
                last_move = before.san(move)

        svg = chess.svg.board(
            board,
            orientation=board.turn,  # the side to move at the bottom
            coordinates=True,
            size=384,
            colors=BOARD_COLORS,
        )
        solution = board.variation_san([chess.Move.from_uci(uci) for uci in puzzle["solution"]])

        players = {player["color"]: player for player in game.get("players", [])}
        themes = [THEMES[theme] for theme in puzzle.get("themes", []) if theme in THEMES]
        return {
            "svg": Markup(svg),
            "goal": self.goal(puzzle.get("themes", []), solver),
            "rating": puzzle.get("rating"),
            "themes": themes[:3],
            "last_move": last_move,
            "solution": solution,
            "white": players.get("white", {}).get("name", "White"),
            "black": players.get("black", {}).get("name", "Black"),
        }


    def board_from_pgn(self, pgn, drop_last=False):
        """The position after the PGN's moves (the PGN is just the move list)."""
        board = chess.Board()
        tokens = [token for token in pgn.split() if not re.fullmatch(r"\d+\.+|1-0|0-1|1/2-1/2|\*", token)]
        if drop_last:
            tokens = tokens[:-1]
        for san in tokens:
            board.push_san(san)
        return board


    def render_component(self):
        options = {"show_solution": True, "show_game": True}
        if request.headers.get('Content-Type') == 'application/json':
            for element in request.json:
                if element["name"] in options:
                    options[element["name"]] = bool(element["value"])

        try:
            puzzle = self.build(self.fetch_daily())
        except Exception as e:
            error = f"HTTP {e.response.status_code}" if isinstance(e, requests.HTTPError) else type(e).__name__
            logger.error(f"Chess puzzle: could not get today's puzzle ({error})")
            return f'<div style="text-align: center;">No chess puzzle today ({error})</div>'

        return render_template('chess-puzzle/component.html', puzzle=puzzle, **options)
