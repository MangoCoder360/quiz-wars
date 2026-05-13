import json, os
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
        "question_set": "test",
        "game_status": "lobby",
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
        ]
    }
}

dotenv.load_dotenv()
app = Flask(__name__)
client = OpenAI()
QUESTION_SETS_DIR = "question_sets"

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

def create_new_game(question_set):
    new_game_id = random.randint(11111,99999)
    while new_game_id in active_games:
        new_game_id = random.randint(11111,99999)
    active_games[new_game_id] = {
        "question_set": question_set,
        "game_status": "lobby",
        "players": []
    }
    return new_game_id

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/host', methods=["GET", "POST"])
def host():
    if request.method == "POST":
        # Handle game creation logic here
        question_set = request.form.get("question_set")
        if question_set not in questions_lib.get_all_question_sets():
            return "Invalid question set selected", 400
        new_game_id = create_new_game(question_set)
        return redirect(f"/host/{new_game_id}")
    else:
        avail_q_sets = questions_lib.get_all_question_sets()
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
    
    players = game_data.get("players", [])
    if player_id < 0 or player_id >= len(players):
        return "Player not found", 404
    
    players[player_id]["player_status"] = "kicked"
    return "200 OK"

@app.route("/game/player/get-data/<int:player_id>")
def get_player_status(player_id):
    for game in active_games.values():
        for player in game.get("players", []):
            if player["id"] == player_id:
                return player
    return "Player not found", 404

@app.route("/game/start/<int:game_id>")
def start_game(game_id):
    global active_games
    game_data = active_games.get(game_id)
    if not game_data:
        return "Game not found", 404
    if game_data["game_status"] != "lobby":
        return "Game is not in lobby state", 400
    
    game_data["game_status"] = "starting" # lock player joining and signal clients to transition to game start screen

    # scramble the order of all players to make avatar selection fair
    random.shuffle(game_data["players"])

    avatar_pool = list(game_data.get("avatars", {}).values()) # add multiple times to creat a large pool
    avatar_pool *= 50  # create a large pool of avatars

    # iterate over each joined player and register them in the game as well as assign them an avatar
    for player in game_data.get("players", []):
        if player["player_status"] == "lobby":
            player["player_status"] = "starting"
            if avatar_pool:
                assigned_avatar = avatar_pool.pop()
                player["assigned_avatar"] = assigned_avatar.name
            else:
                player["assigned_avatar"] = None
        else:
            player["player_status"] = "kicked"

    # check to make sure every player starting has an avatar assigned. error out if not
    for player in game_data.get("players", []):
        if player["player_status"] == "starting" and not player.get("assigned_avatar"):
            return f"Not enough avatars for all players. Player {player['name']} could not be assigned an avatar.", 500
    
    # count how many players each avatar has assigned to it
    avatar_counts = {}
    for player in game_data.get("players", []):
        if player["player_status"] == "starting":
            avatar_name = player.get("assigned_avatar")
            if avatar_name:
                avatar_counts[avatar_name] = avatar_counts.get(avatar_name, 0) + 1
    print(f"Avatar counts for game {game_id}:", avatar_counts)
    print(f"{len(game_data.get('players', []))} players in game")
    print("Ready to start..")

    return "200 OK"

@app.route("/debug")
def debug_options():
    return render_template("debug.html")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)