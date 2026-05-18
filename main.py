import json, os, time, threading
import dotenv, random
from flask import Flask, render_template, request, redirect
from openai import OpenAI

import questions_lib, avatars

STRICT_NAME_CHECKING = False

BANNED_WORDS = [
    "ass", "bitch", "cuck", "cock", "penis", "fuck", "damn", "dick", "pussy", "slut", "whore", "shit", "porn", "sex", "hitler", "trump", "biden", "kamala"
]

active_games = {
    6767: {
        "game_id": 6767,
        "question_set": "test",
        "game_status": "lobby",
        "boss_health": 300,
        "avatars": {
            "Wizard": avatars.Wizard(),
            "Knight": avatars.Knight(),
            "Monk": avatars.Monk()
        },
        "players": [
            {
                "name": "Test",
                "id": 0,
                "player_status": "lobby",
                "assigned_avatar": None
            }
        ],
        "current_question_index": 0,
        "questions_data": [],
        "avatar_states": {
            "Wizard": {"hp": 25, "status": []},
            "Knight": {"hp": 40, "status": []},
            "Monk": {"hp": 35, "status": []}
        },
        "avatar_max_health": {
            "Wizard": 25,
            "Knight": 40,
            "Monk": 35
        },
        "boss_state": {"hp": 300, "status": []},
        "votes": {"Wizard": {}, "Knight": {}, "Monk": {}},
        "action_cooldowns": {"Wizard": None, "Knight": None, "Monk": None},
        "players_answered": set(),
        "game_over": False,
        "round_results": None,
        "round_ready_for_advance_index": None
    }
}

game_locks = {
    6767: threading.RLock(),
}

dotenv.load_dotenv()
app = Flask(__name__)
client = OpenAI()
QUESTION_SETS_DIR = "question_sets"

AVATAR_MAX_HEALTH = {
    "Wizard": 25,
    "Knight": 40,
    "Monk": 35,
}

def is_game_id_valid(game_id):
    game_id = int(game_id)
    if game_id in active_games:
        return True
    else:
        return False

def _get_question_set_path(set_name):
    return os.path.join(QUESTION_SETS_DIR, f"{set_name}.json")


def _validate_question_set_data(data):
    if not isinstance(data, dict):
        raise ValueError("Invalid payload")

    display_name = data.get("displayName", "")
    if not isinstance(display_name, str) or not display_name.strip():
        raise ValueError("displayName is required")

    description = data.get("description", "")
    if not isinstance(description, str):
        raise ValueError("description must be a string")

    questions = data.get("questions", [])
    if not isinstance(questions, list):
        raise ValueError("questions must be a list")

    for idx, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            raise ValueError(f"Question #{idx} is invalid")

        question_text = question.get("question", "")
        if not isinstance(question_text, str) or not question_text.strip():
            raise ValueError(f"Question #{idx} needs text")

        options = question.get("options", [])
        if not isinstance(options, list) or len(options) != 4:
            raise ValueError(f"Question #{idx} must have exactly 4 options")

        correct_count = 0
        for option in options:
            if not isinstance(option, dict):
                raise ValueError(f"Question #{idx} has invalid option data")

            option_text = option.get("text", "")
            if not isinstance(option_text, str) or not option_text.strip():
                raise ValueError(f"Question #{idx} has an empty option")

            if option.get("isCorrect") is True:
                correct_count += 1

        if correct_count != 1:
            raise ValueError(f"Question #{idx} must have exactly one correct answer")

    return {
        "displayName": display_name.strip(),
        "description": description,
        "questions": questions,
    }

def create_new_game(question_set, answer_timeout_seconds=60, vote_timeout_seconds=30, shuffle_questions=False):
    new_game_id = random.randint(11111,99999)
    while new_game_id in active_games:
        new_game_id = random.randint(11111,99999)
    active_games[new_game_id] = _build_game_state(question_set, answer_timeout_seconds, vote_timeout_seconds, shuffle_questions)
    active_games[new_game_id]["game_id"] = new_game_id
    game_locks[new_game_id] = threading.RLock()
    return new_game_id

def _build_game_state(question_set, answer_timeout_seconds=60, vote_timeout_seconds=30, shuffle_questions=False):
    return {
        "game_id": None,
        "question_set": question_set,
        "shuffle_questions": bool(shuffle_questions),
        "game_status": "lobby",
        "boss_health": 300,
        "avatars": {
            "Wizard": avatars.Wizard(),
            "Knight": avatars.Knight(),
            "Monk": avatars.Monk()
        },
        "players": [],
        "current_question_index": 0,
        "questions_data": [],
        "avatar_states": {
            "Wizard": {"hp": AVATAR_MAX_HEALTH["Wizard"], "status": []},
            "Knight": {"hp": AVATAR_MAX_HEALTH["Knight"], "status": []},
            "Monk": {"hp": AVATAR_MAX_HEALTH["Monk"], "status": []}
        },
        "avatar_max_health": dict(AVATAR_MAX_HEALTH),
        "boss_state": {"hp": 300, "status": []},
        "votes": {"Wizard": {}, "Knight": {}, "Monk": {}},
        "eligible_voters": set(),
        "votes_cast": set(),
        "action_cooldowns": {"Wizard": None, "Knight": None, "Monk": None},
        "players_answered": set(),
        "game_over": False,
        "round_results": None,
        "round_started_at": None,
        "round_resolved": False,
        "round_ready_for_advance_index": None,
        "answer_timeout_seconds": int(answer_timeout_seconds),
        "vote_timeout_seconds": int(vote_timeout_seconds),
        "answer_phase_started_at": None,
        "vote_phase_started_at": None,
        "current_phase": "answer",
        "server_time": time.time(),
    }

def _sync_boss_health(game_data):
    boss_state = game_data.get("boss_state")
    if isinstance(boss_state, dict):
        game_data["boss_health"] = boss_state.get("hp", game_data.get("boss_health", 300))

def _get_player_by_id(game_data, player_id):
    for player in game_data.get("players", []):
        if player.get("id") == player_id:
            return player
    return None


def _get_game_lock(game_id):
    lock = game_locks.get(game_id)
    if lock is None:
        lock = threading.RLock()
        game_locks[game_id] = lock
    return lock


def _build_question_response(game_data, question_index):
    questions = game_data.get("questions_data", [])
    if question_index < 0 or question_index >= len(questions):
        return None

    current_question = questions[question_index]
    return {
        "question": current_question["question"],
        "options": [opt["text"] for opt in current_question["options"]],
        "question_index": question_index,
        "total_questions": len(questions)
    }

def _reset_round_state(game_data):
    game_data["votes"] = {"Wizard": {}, "Knight": {}, "Monk": {}}
    game_data["eligible_voters"] = set()
    game_data["votes_cast"] = set()
    game_data["players_answered"] = set()
    game_data["round_results"] = None
    game_data["round_resolved"] = False
    game_data["round_ready_for_advance_index"] = None
    game_data["round_started_at"] = time.time()
    game_data["answer_phase_started_at"] = time.time()
    game_data["vote_phase_started_at"] = None
    game_data["current_phase"] = "answer"
    game_data["server_time"] = time.time()

def _mark_game_over(game_data, outcome, round_results=None):
    game_data["game_over"] = True
    game_data["game_status"] = "ended"
    game_data["round_resolved"] = True
    game_data["round_results"] = round_results
    _sync_boss_health(game_data)
    game_data["current_question_index"] = min(game_data.get("current_question_index", 0), max(len(game_data.get("questions_data", [])) - 1, 0))
    return {
        "game_over": True,
        "outcome": outcome,
        "boss_hp": game_data["boss_state"]["hp"],
        "avatar_states": game_data["avatar_states"],
        "round_results": round_results or {"actions": [], "boss_attacks": [], "game_over": True, "outcome": outcome}
    }

def _start_game_logic(game_data):
    question_set_name = game_data.get("question_set")
    questions = questions_lib.get_questions(question_set_name)
    if not questions:
        return None, {"error": "Question set not found or is empty"}, 400

    if game_data.get("shuffle_questions"):
        questions = list(questions)
        random.shuffle(questions)

    game_data["questions_data"] = questions
    game_data["current_question_index"] = 0
    game_data["game_status"] = "in-progress"
    game_data["game_over"] = False
    game_data["boss_state"] = {"hp": 300, "status": []}
    game_data["avatar_max_health"] = dict(AVATAR_MAX_HEALTH)
    game_data["avatar_states"]["Wizard"] = {"hp": AVATAR_MAX_HEALTH["Wizard"], "status": []}
    game_data["avatar_states"]["Knight"] = {"hp": AVATAR_MAX_HEALTH["Knight"], "status": []}
    game_data["avatar_states"]["Monk"] = {"hp": AVATAR_MAX_HEALTH["Monk"], "status": []}
    game_data["action_cooldowns"] = {"Wizard": None, "Knight": None, "Monk": None}
    _sync_boss_health(game_data)
    _reset_round_state(game_data)
    return {
        "status": "in-progress",
        "question_index": 0,
        "question": questions[0],
        "total_questions": len(questions)
    }, None, None

def _maybe_resolve_round(game_data):
    if game_data.get("game_over") or game_data.get("game_status") != "in-progress":
        return False

    if game_data.get("round_resolved"):
        return True

    answer_timeout = game_data.get("answer_timeout_seconds", 60)
    vote_timeout = game_data.get("vote_timeout_seconds", 30)
    
    answer_phase_started_at = game_data.get("answer_phase_started_at")
    if answer_phase_started_at is None:
        return False
    
    current_time = time.time()
    players = game_data.get("players", [])
    players_answered = game_data.get("players_answered", set())
    eligible_voters = game_data.get("eligible_voters", set())
    votes_cast = game_data.get("votes_cast", set())
    
    # Check if answer phase should end (all players answered or answer timeout)
    answer_phase_elapsed = current_time - answer_phase_started_at
    all_answered = len(players_answered) >= len(players) if players else False
    
    current_phase = game_data.get("current_phase", "answer")
    
    # Transition to vote phase if answer phase is over
    if (all_answered or answer_phase_elapsed >= answer_timeout) and current_phase == "answer":
        # Transition to vote phase
        game_data["vote_phase_started_at"] = current_time
        game_data["current_phase"] = "vote"
        current_phase = "vote"
    
    vote_phase_started_at = game_data.get("vote_phase_started_at")
    
    # Check if all eligible voters have voted
    if eligible_voters and eligible_voters.issubset(votes_cast) and vote_phase_started_at is not None:
        game_data["round_results"] = resolve_round(game_data)
        game_data["round_resolved"] = True
        game_data["round_ready_for_advance_index"] = game_data.get("current_question_index", 0)
        return True
    
    # Check if vote phase timeout has elapsed
    if vote_phase_started_at is not None:
        vote_phase_elapsed = current_time - vote_phase_started_at
        if vote_phase_elapsed >= vote_timeout:
            game_data["round_results"] = resolve_round(game_data)
            game_data["round_resolved"] = True
            game_data["round_ready_for_advance_index"] = game_data.get("current_question_index", 0)
            return True
    
    return False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/host', methods=["GET", "POST"])
def host():
    if request.method == "POST":
        # Handle game creation logic here
        question_set = request.form.get("question_set")
        if question_set not in questions_lib.get_question_set_ids():
            return "Invalid question set selected", 400
        try:
            answer_timeout_seconds = int(request.form.get("answer_timeout_seconds", 60))
            vote_timeout_seconds = int(request.form.get("vote_timeout_seconds", 30))
        except (TypeError, ValueError):
            return "Invalid timeout values", 400

        shuffle_questions = request.form.get("shuffle_questions") == "on"

        answer_timeout_seconds = max(10, min(answer_timeout_seconds, 300))
        vote_timeout_seconds = max(5, min(vote_timeout_seconds, 120))

        new_game_id = create_new_game(question_set, answer_timeout_seconds, vote_timeout_seconds, shuffle_questions)
        return redirect(f"/host/{new_game_id}")
    else:
        avail_q_sets = questions_lib.get_question_set_choices()
        return render_template('host.html', question_sets = avail_q_sets)

@app.route('/host/<int:game_id>')
def host_game(game_id):
    game_data = active_games.get(game_id)
    if not game_data:
        return "Game not found", 404
    
    return render_template('host_game.html', game_id=game_id)

@app.route('/question-sets')
def question_sets():
    avail_q_sets = []
    for filename in os.listdir(QUESTION_SETS_DIR):
        if not filename.endswith('.json'):
            continue

        file_path = os.path.join(QUESTION_SETS_DIR, filename)
        try:
            with open(file_path, 'r') as f:
                set_data = json.load(f)
            avail_q_sets.append({
                'id': filename[:-5],
                'displayName': set_data.get('displayName', filename[:-5])
            })
        except Exception:
            continue

    return render_template('question_sets.html', question_sets=avail_q_sets)

@app.route('/question-sets/create', methods=["POST"])
def create_question_set():
    if request.method == "POST":
        try:
            questions_lib.create_empty_question_set(request.form['id'], request.form['display_name'])
        except:
            return "An error occured while creating the question set. Make sure the ID is unique and try again.", 500
        return "200 OK"

@app.route('/question-sets/delete/<set_name>')
def delete_question_set(set_name):
    set_path = _get_question_set_path(set_name)
    if not os.path.exists(set_path):
        return "Question set not found", 404

    try:
        os.remove(set_path)
        return "200 OK"
    except:
        return "Failed to delete question set", 500

@app.route('/question-sets/edit/<set_name>', methods=["GET", "POST"])
def edit_question_set(set_name):
    set_path = _get_question_set_path(set_name)
    if not os.path.exists(set_path):
        return "Question set not found", 404

    if request.method == "POST":
        raw_set_data = request.form.get("set_data_json", "")
        try:
            parsed_data = json.loads(raw_set_data)
            cleaned_data = _validate_question_set_data(parsed_data)
            with open(set_path, "w") as f:
                json.dump(cleaned_data, f, indent=4)
            return redirect(f"/question-sets/edit/{set_name}?saved=1")
        except ValueError as exc:
            with open(set_path, "r") as f:
                current_data = json.load(f)
            return render_template(
                'edit_question_set.html',
                set_name=set_name,
                set_data=current_data,
                error_msg=str(exc)
            ), 400
        except Exception:
            with open(set_path, "r") as f:
                current_data = json.load(f)
            return render_template(
                'edit_question_set.html',
                set_name=set_name,
                set_data=current_data,
                error_msg="Failed to save question set"
            ), 500
    else:
        with open(set_path, "r") as f:
            set_data = json.load(f)

        # Normalize any existing old-format questions into 4 options for editor compatibility.
        for question in set_data.get("questions", []):
            options = question.get("options", [])
            if not isinstance(options, list):
                question["options"] = []
                options = question["options"]

            while len(options) < 4:
                options.append({"text": "", "isCorrect": False})
            if len(options) > 4:
                question["options"] = options[:4]
                options = question["options"]

            if not any(option.get("isCorrect") is True for option in options):
                options[0]["isCorrect"] = True

        return render_template(
            'edit_question_set.html',
            set_name=set_name,
            set_data=set_data,
            success_msg="Saved" if request.args.get("saved") == "1" else None,
            error_msg=None,
        )

@app.route('/join-game', methods=["POST"])
def join_game():
    global active_games

    player_name = request.form['player_name']
    game_id = request.form['game_id']

    if not is_game_id_valid(game_id):
        return render_template("index.html", error_msg="Game does not exist. Check game ID and try again.")
    
    # check for duplicate names in that game
    for player in active_games[int(game_id)]["players"]:
        if player["name"].lower() == player_name.lower():
            return render_template("index.html", error_msg="A player with that name already exists in this game. Please choose a different name and try again.")

    name_flagged = False

    if any(banned_word in player_name.lower() for banned_word in BANNED_WORDS):
        name_flagged = True
    else:
        try:
            name_moderation_check = client.moderations.create(input=player_name)
            if name_moderation_check.results[0].flagged:
                name_flagged = True
        except:
            if STRICT_NAME_CHECKING:
                return "Name check failed, please try again later."
        
    if name_flagged:
        return render_template("index.html", error_msg="The name you entered is not allowed. Choose a different name and try again.")
    
    is_lobby_open = active_games[int(game_id)]["game_status"] == "lobby"
    if not is_lobby_open:
        return render_template("index.html", error_msg="This game lobby is closed. You cannot join at this time.")

    # register the player in the game data
    player_id = len(active_games[int(game_id)]["players"])
    active_games[int(game_id)]["players"].append({
        "name": player_name,
        "id": player_id,
        "player_status": "lobby"
    })

    return render_template(
        "player_lobby.html",
        player_name=player_name,
        player_id=player_id,
        game_id=game_id,
    )

@app.route("/game/<int:game_id>/p/<int:player_id>/play")
def player_game_view(game_id, player_id):
    game_data = active_games.get(game_id)
    if not game_data:
        return "Game not found", 404
    
    player_data = _get_player_by_id(game_data, player_id)
    if not player_data:
        return "Player not found", 404
    if player_data["player_status"] == "kicked":
        return "You have been kicked from the game.", 403
    elif player_data["player_status"] == "lobby":
        return "Game has not started yet. Please wait for the host to start the game.", 403
    elif player_data["player_status"] in ("starting", "ingame"):
        return render_template("client_game.html", game_id=game_id, player_id=player_id)
    else:
        return "Invalid player status", 500

@app.route("/game/get-players/<int:game_id>")
def get_players_in_game(game_id):
    game_data = active_games.get(game_id)
    if not game_data:
        return []
    return game_data.get("players", [])

@app.route("/game/kick-player/<int:game_id>/<int:player_id>")
def kick_player(game_id, player_id):
    global active_games
    game_data = active_games.get(game_id)
    if not game_data:
        return "Game not found", 404
    
    player = _get_player_by_id(game_data, player_id)
    if not player:
        return "Player not found", 404
    
    player["player_status"] = "kicked"
    return "200 OK"

@app.route("/game/<int:game_id>/player/get-data/<int:player_id>")
def get_player_status(game_id, player_id):
    game_data = active_games.get(game_id)
    if not game_data:
        return "Game not found", 404

    player = _get_player_by_id(game_data, player_id)
    if player:
        return player
    return "Player not found", 404

def _assign_player_avatars(game_data, game_id=None):
    # scramble the order of all players to make avatar selection fair
    random.shuffle(game_data["players"])

    avatar_pool = list(game_data.get("avatars", {}).values())
    avatar_pool *= 50  # create a large pool of avatars

    # iterate over each joined player and register them in the game as well as assign them an avatar
    for player in game_data.get("players", []):
        if player["player_status"] == "lobby":
            player["player_status"] = "ingame"
            if avatar_pool:
                assigned_avatar = avatar_pool.pop()
                player["assigned_avatar"] = assigned_avatar.name
            else:
                player["assigned_avatar"] = None
        else:
            player["player_status"] = "kicked"

    # check to make sure every player starting has an avatar assigned. error out if not
    for player in game_data.get("players", []):
        if player["player_status"] == "ingame" and not player.get("assigned_avatar"):
            return f"Not enough avatars for all players. Player {player['name']} could not be assigned an avatar.", 500

    # count how many players each avatar has assigned to it
    avatar_counts = {}
    for player in game_data.get("players", []):
        if player["player_status"] == "ingame":
            avatar_name = player.get("assigned_avatar")
            if avatar_name:
                avatar_counts[avatar_name] = avatar_counts.get(avatar_name, 0) + 1
    if game_id is not None:
        print(f"Avatar counts for game {game_id}:", avatar_counts)
    else:
        print("Avatar counts:", avatar_counts)
    print(f"{len(game_data.get('players', []))} players in game")
    print("Ready to start..")

    return None

@app.route("/game/start/<int:game_id>")
def start_game(game_id):
    global active_games
    game_data = active_games.get(game_id)
    if not game_data:
        return "Game not found", 404
    if game_data["game_status"] != "lobby":
        return "Game is not in lobby state", 400

    start_payload, error_payload, status_code = _start_game_logic(game_data)
    if error_payload:
        return error_payload, status_code

    error_payload = _assign_player_avatars(game_data, game_id)
    if error_payload:
        return error_payload

    return start_payload

@app.route("/game/state/<int:game_id>")
def get_full_game_state(game_id):
    game_data = active_games.get(game_id)
    if not game_data:
        return "Game not found", 404
    with _get_game_lock(game_id):
        _maybe_resolve_round(game_data)
        # Update server time on every state call so client has current time for countdown
        game_data["server_time"] = time.time()
        
        # Ensure timing fields exist (in case game hasn't started yet)
        if game_data.get("answer_phase_started_at") is None:
            game_data["answer_phase_started_at"] = time.time()
        if game_data.get("vote_phase_started_at") is None and game_data.get("current_phase") == "vote":
            game_data["vote_phase_started_at"] = time.time()
        if game_data.get("current_phase") is None:
            game_data["current_phase"] = "answer"
        if game_data.get("answer_timeout_seconds") is None:
            game_data["answer_timeout_seconds"] = 60
        if game_data.get("vote_timeout_seconds") is None:
            game_data["vote_timeout_seconds"] = 30

        def _sanitize(obj):
            # dict -> sanitize each value
            if isinstance(obj, dict):
                return {k: _sanitize(v) for k, v in obj.items()}
            # list/tuple -> sanitize items
            if isinstance(obj, (list, tuple)):
                return [_sanitize(v) for v in obj]
            # sets are converted to lists so the response stays JSON-safe
            if isinstance(obj, set):
                return [_sanitize(v) for v in obj]
            # objects with __dict__ (like avatar instances) -> convert to their attributes
            if hasattr(obj, '__dict__'):
                return _sanitize(vars(obj))
            # basic JSON types passthrough
            if isinstance(obj, (str, int, float, bool)) or obj is None:
                return obj
            # fallback: stringify unknown types
            try:
                return str(obj)
            except Exception:
                return None

        return _sanitize(game_data)

@app.route("/game/<int:game_id>/start-game")
def start_game_endpoint(game_id):
    """Compatibility endpoint for the turn-based round system."""
    game_data = active_games.get(game_id)
    if not game_data:
        return {"error": "Game not found"}, 404

    if game_data["game_status"] not in ("lobby", "starting"):
        return {"error": "Game is not ready to start"}, 400

    start_payload, error_payload, status_code = _start_game_logic(game_data)
    if error_payload:
        return error_payload, status_code

    error_payload = _assign_player_avatars(game_data, game_id)
    if error_payload:
        return {"error": error_payload}, 500

    return start_payload

# ==================== PHASE 1: TURN-BASED VOTING SYSTEM ====================

def get_avatar_actions(avatar_name):
    """Returns the list of available actions for an avatar."""
    actions = {
        "Wizard": ["Fire", "Ice", "Lightning", "Shield"],
        "Knight": ["Break", "Cleave", "Parry"],
        "Monk": ["Heal", "Enchant", "DoublePunch"]
    }
    return actions.get(avatar_name, [])

def apply_action_damage(game_data, avatar_name, action):
    """
    Executes an avatar action and applies damage/effects to the boss.
    Returns a dict with action result: {action, damage, status_applied}
    """
    boss = game_data["boss_state"]
    avatar_hp = game_data["avatar_states"][avatar_name]["hp"]
    
    result = {
        "avatar": avatar_name,
        "action": action,
        "damage": 0,
        "status_applied": []
    }
    
    # Apply flat bonus damage from avatar buffs
    bonus_damage = 0
    if "Enchanted" in game_data["avatar_states"][avatar_name]["status"]:
        bonus_damage += 5
        game_data["avatar_states"][avatar_name]["status"].remove("Enchanted")
    
    # Apply vulnerability modifiers from boss debuffs
    vulnerability_multiplier = 1.0
    if "Weakened" in boss["status"]:
        vulnerability_multiplier = 0.5
        boss["status"].remove("Weakened")
    
    # Execute action
    if avatar_name == "Wizard":
        if action == "Fire":
            result["damage"] = int((10 + bonus_damage) * vulnerability_multiplier)
            boss["hp"] -= result["damage"]
        elif action == "Ice":
            result["damage"] = int((5 + bonus_damage) * vulnerability_multiplier)
            boss["hp"] -= result["damage"]
            if "Frozen" not in boss["status"]:
                boss["status"].append("Frozen")
                result["status_applied"].append("Boss is Frozen!")
        elif action == "Lightning":
            result["damage"] = int((5 + bonus_damage) * vulnerability_multiplier)
            boss["hp"] -= result["damage"]
            if "Shocked" not in boss["status"]:
                boss["status"].append("Shocked")
                result["status_applied"].append("Boss is Shocked!")
        elif action == "Shield":
            # Shield doesn't do damage, just adds a protective status.
            if "Shielded" not in game_data["avatar_states"][avatar_name]["status"]:
                game_data["avatar_states"][avatar_name]["status"].append("Shielded")
            result["status_applied"].append(f"{avatar_name} is Shielded!")
    
    elif avatar_name == "Knight":
        if action == "Break":
            base_damage = 12
            if "Frozen" in boss["status"]:
                base_damage *= 2
            result["damage"] = int((base_damage + bonus_damage) * vulnerability_multiplier)
            boss["hp"] -= result["damage"]
        elif action == "Cleave":
            result["damage"] = int((20 + bonus_damage) * vulnerability_multiplier)
            boss["hp"] -= result["damage"]
        elif action == "Parry":
            # Parry adds a protective status but doesn't do damage
            if "Parrying" not in game_data["avatar_states"][avatar_name]["status"]:
                game_data["avatar_states"][avatar_name]["status"].append("Parrying")
            result["status_applied"].append(f"{avatar_name} is Parrying!")
    
    elif avatar_name == "Monk":
        if action == "Heal":
            # Heal restores 10 HP to the avatar (for now, heal self)
            heal_amount = 10
            old_hp = game_data["avatar_states"][avatar_name]["hp"]
            max_hp = game_data.get("avatar_max_health", {}).get(avatar_name, 35)
            game_data["avatar_states"][avatar_name]["hp"] = min(max_hp, old_hp + heal_amount)
            actual_heal = game_data["avatar_states"][avatar_name]["hp"] - old_hp
            result["status_applied"].append(f"{avatar_name} healed {actual_heal} HP!")
        elif action == "Enchant":
            # Enchant buffs this avatar's next attack
            if "Enchanted" not in game_data["avatar_states"][avatar_name]["status"]:
                game_data["avatar_states"][avatar_name]["status"].append("Enchanted")
            result["status_applied"].append(f"{avatar_name} is Enchanted (+5 damage next)!")
        elif action == "DoublePunch":
            base_damage = 10
            if "Frozen" in boss["status"]:
                base_damage *= 2
            punch_damage = int((base_damage * 2 + bonus_damage) * vulnerability_multiplier)
            result["damage"] = punch_damage
            boss["hp"] -= result["damage"]
    
    # Remove Frozen status if boss was hit again.
    if "Frozen" in boss["status"] and result["damage"] > 0 and action != "Ice":
        boss["status"].remove("Frozen")
        result["status_applied"].append("Boss is no longer Frozen!")

    _sync_boss_health(game_data)
    
    return result

def resolve_round(game_data):
    """
    Resolves a round: tallies votes, executes avatar actions, applies damage, boss counter-attacks.
    Returns a dict with round results.
    """
    round_results = {
        "actions": [],
        "boss_attacks": [],
        "vote_details": {},
        "game_over": False,
        "outcome": None
    }
    
    # For each avatar, find majority action
    for avatar_name in ["Wizard", "Knight", "Monk"]:
        avatar_votes = game_data["votes"][avatar_name]
        vote_detail = {
            "votes": dict(avatar_votes),
            "selected_action": None,
            "selection_reason": None,
            "cooldown_before": game_data["action_cooldowns"][avatar_name],
        }
        
        if not avatar_votes:
            # No votes for this avatar; pick random action
            available_actions = [a for a in get_avatar_actions(avatar_name) if a != game_data["action_cooldowns"][avatar_name]]
            if available_actions:
                chosen_action = random.choice(available_actions)
            else:
                chosen_action = get_avatar_actions(avatar_name)[0]
            vote_detail["selection_reason"] = "no_votes_random"
        else:
            # Find action with most votes
            max_votes = max(avatar_votes.values())
            tied_actions = [action for action, count in avatar_votes.items() if count == max_votes]
            chosen_action = random.choice(tied_actions)
            vote_detail["selection_reason"] = "majority_vote"
            
            # Check cooldown; if violates, pick another
            if chosen_action == game_data["action_cooldowns"][avatar_name]:
                available_actions = [a for a in get_avatar_actions(avatar_name) if a != chosen_action]
                if available_actions:
                    chosen_action = random.choice(available_actions)
                    vote_detail["selection_reason"] = "cooldown_override"
        
        vote_detail["selected_action"] = chosen_action
        round_results["vote_details"][avatar_name] = vote_detail

        # Update cooldown
        game_data["action_cooldowns"][avatar_name] = chosen_action
        
        # Execute action
        action_result = apply_action_damage(game_data, avatar_name, chosen_action)
        round_results["actions"].append(action_result)
    
    # Check if boss is defeated
    if game_data["boss_state"]["hp"] <= 0:
        _sync_boss_health(game_data)
        round_results["game_over"] = True
        round_results["outcome"] = "WIN"
        return round_results
    
    # Boss counter-attack (random chance ~70%)
    if "Frozen" in game_data["boss_state"]["status"]:
        round_results["boss_attacks"].append({
            "target": None,
            "damage": 0,
            "frozen": True,
            "message": "Boss is Frozen and cannot attack this round!"
        })
    elif random.random() < 0.7:
        target_avatar = random.choice(["Wizard", "Knight", "Monk"])
        boss_damage = random.randint(5, 15)
        
        # Check if target has Parry active
        if "Parrying" in game_data["avatar_states"][target_avatar]["status"]:
            # Redirect to self but take half damage
            boss_damage = boss_damage // 2
            game_data["avatar_states"][target_avatar]["hp"] -= boss_damage
            game_data["avatar_states"][target_avatar]["status"].remove("Parrying")
            round_results["boss_attacks"].append({
                "target": target_avatar,
                "damage": boss_damage,
                "redirected": True,
                "message": f"Boss attacked {target_avatar}, but was parried! {target_avatar} took {boss_damage} damage."
            })
        elif "Shielded" in game_data["avatar_states"][target_avatar]["status"]:
            # Shield blocks the attack entirely
            game_data["avatar_states"][target_avatar]["status"].remove("Shielded")
            round_results["boss_attacks"].append({
                "target": target_avatar,
                "damage": 0,
                "shielded": True,
                "message": f"Boss attacked {target_avatar}, but was shielded!"
            })
        else:
            # Normal damage, apply Shocked modifier if boss has it
            actual_damage = boss_damage
            if "Shocked" in game_data["boss_state"]["status"]:
                actual_damage += 2
            
            game_data["avatar_states"][target_avatar]["hp"] -= actual_damage
            round_results["boss_attacks"].append({
                "target": target_avatar,
                "damage": actual_damage,
                "message": f"Boss attacked {target_avatar} for {actual_damage} damage!"
            })
            
            # Consume Shocked status after use
            if "Shocked" in game_data["boss_state"]["status"]:
                game_data["boss_state"]["status"].remove("Shocked")
    
    # Check if all avatars are defeated
    all_avatars_dead = all(game_data["avatar_states"][avatar]["hp"] <= 0 for avatar in ["Wizard", "Knight", "Monk"])
    if all_avatars_dead:
        _sync_boss_health(game_data)
        round_results["game_over"] = True
        round_results["outcome"] = "LOSE"
        return round_results
    
    _sync_boss_health(game_data)
    return round_results

@app.route("/game/<int:game_id>/question")
def get_current_question(game_id):
    """
    Returns the current question and game state (boss HP, avatar states).
    Does NOT expose correct answers.
    """
    game_data = active_games.get(game_id)
    if not game_data:
        return {"error": "Game not found"}, 404
    with _get_game_lock(game_id):
        _maybe_resolve_round(game_data)
        _sync_boss_health(game_data)
        
        if game_data["game_over"]:
            return {
                "question": None,
                "game_state": {
                    "boss_health": game_data["boss_health"],
                    "boss_hp": game_data["boss_state"]["hp"],
                    "boss_status": game_data["boss_state"]["status"],
                    "avatar_states": game_data["avatar_states"],
                    "game_over": True,
                    "round_results": game_data.get("round_results")
                }
            }

        if game_data["game_status"] != "in-progress":
            return {"error": "Game is not in progress"}, 400
        
        current_idx = game_data["current_question_index"]
        question_response = _build_question_response(game_data, current_idx)
        if question_response is None:
            return {"error": "No more questions"}, 400
        
        # Build game state response
        game_state = {
            "boss_health": game_data["boss_health"],
            "boss_hp": game_data["boss_state"]["hp"],
            "boss_status": game_data["boss_state"]["status"],
            "avatar_states": game_data["avatar_states"],
            "game_over": game_data["game_over"],
            "server_time": time.time(),
            "current_phase": game_data.get("current_phase", "answer"),
            "answer_phase_started_at": game_data.get("answer_phase_started_at"),
            "vote_phase_started_at": game_data.get("vote_phase_started_at"),
            "answer_timeout_seconds": game_data.get("answer_timeout_seconds", 60),
            "vote_timeout_seconds": game_data.get("vote_timeout_seconds", 30),
        }
        
        return {
            "question": question_response,
            "game_state": game_state
        }

@app.route("/game/<int:game_id>/answer", methods=["POST"])
def submit_answer(game_id):
    """
    Player submits an answer. Validates correctness.
    Correct answers mark player as eligible to vote.
    """
    global active_games
    game_data = active_games.get(game_id)
    if not game_data:
        return {"error": "Game not found"}, 404

    with _get_game_lock(game_id):
        if game_data["game_status"] != "in-progress":
            return {"error": "Game is not in progress"}, 400
        
        data = request.get_json()
        player_id = data.get("player_id")
        option_index = data.get("option_index")
        
        # Validate inputs
        if player_id is None or option_index is None:
            return {"error": "Missing player_id or option_index"}, 400
        
        if not isinstance(option_index, int) or option_index < 0 or option_index > 3:
            return {"error": "Invalid option_index"}, 400
        
        # Check player exists
        players = game_data.get("players", [])
        if player_id < 0 or player_id >= len(players):
            return {"error": "Player not found"}, 404
        
        current_idx = game_data["current_question_index"]
        questions = game_data["questions_data"]
        
        if current_idx >= len(questions):
            return {"error": "No more questions"}, 400
        
        current_question = questions[current_idx]
        correct_option = current_question["options"][option_index]
        is_correct = correct_option.get("isCorrect", False)
        
        # Mark player as answered
        game_data["players_answered"].add(player_id)
        
        if is_correct:
            # Mark player as eligible to vote
            game_data.setdefault("eligible_voters", set()).add(player_id)
        
            # Check if we should transition to vote phase
            _maybe_resolve_round(game_data)
        
        return {"correct": is_correct}

@app.route("/game/<int:game_id>/vote", methods=["POST"])
def submit_vote(game_id):
    """
    Player votes for an action on their assigned avatar.
    Once all eligible players have voted (or timeout), resolves the round.
    """
    global active_games
    game_data = active_games.get(game_id)
    if not game_data:
        return {"error": "Game not found"}, 404

    with _get_game_lock(game_id):
        if game_data["game_status"] != "in-progress":
            return {"error": "Game is not in progress"}, 400
        
        data = request.get_json()
        player_id = data.get("player_id")
        avatar = data.get("avatar")
        action = data.get("action")
        
        # Validate inputs
        if player_id is None or avatar is None or action is None:
            return {"error": "Missing player_id, avatar, or action"}, 400
        
        # Check player exists and has assigned avatar
        player = _get_player_by_id(game_data, player_id)
        if not player:
            return {"error": "Player not found"}, 404
        
        if player["assigned_avatar"] != avatar:
            return {"error": "Player is not on that avatar team"}, 400

        if player_id not in game_data.get("eligible_voters", set()):
            return {"error": "Player is not eligible to vote this round"}, 403

        if player_id in game_data.setdefault("votes_cast", set()):
            return {"status": "vote already recorded"}
        
        # Check action is valid for avatar
        valid_actions = get_avatar_actions(avatar)
        if action not in valid_actions:
            return {"error": "Invalid action for avatar"}, 400
        
        # Tally vote
        if avatar not in game_data["votes"]:
            game_data["votes"][avatar] = {}
        game_data["votes"][avatar][action] = game_data["votes"][avatar].get(action, 0) + 1
        game_data.setdefault("votes_cast", set()).add(player_id)

        _maybe_resolve_round(game_data)
        
        return {"status": "vote recorded"}

@app.route("/game/<int:game_id>/next-question")
def advance_round(game_id):
    """
    Advances to the next question/round.
    First resolves the current round if not already done.
    Checks win/lose conditions.
    Uses index-based guard to prevent multiple clients from incrementing the same round.
    """
    global active_games
    game_data = active_games.get(game_id)
    if not game_data:
        return {"error": "Game not found"}, 404

    with _get_game_lock(game_id):
        if game_data["game_status"] != "in-progress":
            return {"error": "Game is not in progress"}, 400

        # Make sure the current round has been resolved if enough time/actions have passed.
        _maybe_resolve_round(game_data)
        _sync_boss_health(game_data)

        round_results = game_data.get("round_results") or {"actions": [], "boss_attacks": [], "game_over": False, "outcome": None}
        if round_results["game_over"]:
            return _mark_game_over(game_data, round_results["outcome"], round_results)

        current_idx = game_data.get("current_question_index", 0)
        ready_idx = game_data.get("round_ready_for_advance_index")
        current_question_response = _build_question_response(game_data, current_idx)

        # If this round is not ready yet, fail closed instead of forcing an advance.
        if ready_idx is None:
            if current_question_response is None:
                return {"error": "No more questions"}, 400
            return {
                "question": current_question_response,
                "game_state": {
                    "boss_health": game_data["boss_health"],
                    "boss_hp": game_data["boss_state"]["hp"],
                    "boss_status": game_data["boss_state"]["status"],
                    "avatar_states": game_data["avatar_states"],
                    "game_over": False,
                    "round_results": round_results
                }
            }

        # Another client already advanced this round; return the current question instead of advancing again.
        if ready_idx != current_idx:
            if current_question_response is not None:
                game_state = {
                    "boss_health": game_data["boss_health"],
                    "boss_hp": game_data["boss_state"]["hp"],
                    "boss_status": game_data["boss_state"]["status"],
                    "avatar_states": game_data["avatar_states"],
                    "game_over": False,
                    "round_results": round_results
                }
                return {"question": current_question_response, "game_state": game_state}
            return {"error": "No more questions"}, 400

        # This client is the first one allowed to advance this completed round.
        game_data["round_ready_for_advance_index"] = None
        game_data["current_question_index"] += 1

        # Check if out of questions
        if game_data["current_question_index"] >= len(game_data["questions_data"]):
            return _mark_game_over(game_data, "LOSE", round_results)

        # Check lose condition (all avatars dead)
        all_avatars_dead = all(game_data["avatar_states"][avatar]["hp"] <= 0 for avatar in ["Wizard", "Knight", "Monk"])
        if all_avatars_dead:
            return _mark_game_over(game_data, "LOSE", round_results)

        # Reset round state for the new question
        _reset_round_state(game_data)

        # Return next question
        current_idx = game_data["current_question_index"]
        question_response = _build_question_response(game_data, current_idx)
        if question_response is None:
            return _mark_game_over(game_data, "LOSE", round_results)

        game_state = {
            "boss_health": game_data["boss_health"],
            "boss_hp": game_data["boss_state"]["hp"],
            "boss_status": game_data["boss_state"]["status"],
            "avatar_states": game_data["avatar_states"],
            "game_over": False,
            "round_results": round_results
        }

        return {
            "question": question_response,
            "game_state": game_state
        }

@app.route("/debug")
def debug_options():
    return render_template("debug.html")


@app.route("/debug/set-boss-health", methods=["POST"])
def debug_set_boss_health():
    raw_game_id = request.form.get("game_id", "")
    raw_boss_health = request.form.get("boss_health", "")

    try:
        game_id = int(raw_game_id)
    except (TypeError, ValueError):
        return "Invalid game ID", 400

    game_data = active_games.get(game_id)
    if not game_data:
        return "Game not found", 404

    try:
        boss_health = int(raw_boss_health)
    except (TypeError, ValueError):
        return "Invalid boss health", 400

    boss_health = max(0, min(boss_health, 9999))

    with _get_game_lock(game_id):
        boss_state = game_data.setdefault("boss_state", {"hp": 300, "status": []})
        if not isinstance(boss_state, dict):
            boss_state = {"hp": 300, "status": []}
            game_data["boss_state"] = boss_state

        boss_state["hp"] = boss_health
        game_data["boss_health"] = boss_health
        game_data["server_time"] = time.time()

    return {
        "game_id": game_id,
        "boss_health": boss_health,
    }

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)