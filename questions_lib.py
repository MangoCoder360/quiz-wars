import json, os

question_sets_dir = "question_sets"

def get_all_question_sets():
    """
    Gets all of the json files in the question_sets directory and returns a list of their names based on the "displayName" key in the JSON
    """
    question_sets = []
    for filename in os.listdir(question_sets_dir):
        if filename.endswith(".json"):
            with open(os.path.join(question_sets_dir, filename), "r") as f:
                data = json.load(f)
                question_sets.append(data["displayName"])
    return question_sets

def get_question_set_choices():
    """
    Returns question set metadata with file IDs and display names.
    """
    choices = []
    for filename in os.listdir(question_sets_dir):
        if filename.endswith(".json"):
            with open(os.path.join(question_sets_dir, filename), "r") as f:
                data = json.load(f)
                choices.append({
                    "id": filename[:-5],
                    "displayName": data.get("displayName", filename[:-5]),
                })
    return choices

def get_question_set_ids():
    return [choice["id"] for choice in get_question_set_choices()]

def create_empty_question_set(id, display_name):
    """
    Creates an empty question set JSON file
    """
    new_set_name = id
    new_set_path = os.path.join(question_sets_dir, f"{new_set_name}.json")
    if os.path.exists(new_set_path):
        raise FileExistsError(f"Question set with id '{new_set_name}' already exists")

    new_set_data = {
        "displayName": display_name,
        "description": "",
        "questions": []
    }

    with open(new_set_path, "w") as f:
        json.dump(new_set_data, f, indent=4)

def load_question_set(set_name):
    """
    Loads a question set by name (without .json extension) and returns the full data.
    Returns None if the set doesn't exist.
    """
    set_path = os.path.join(question_sets_dir, f"{set_name}.json")
    if not os.path.exists(set_path):
        return None
    
    try:
        with open(set_path, "r") as f:
            return json.load(f)
    except Exception:
        return None

def get_questions(set_name):
    """
    Gets the questions array from a question set by name.
    Returns an empty list if the set doesn't exist or has no questions.
    """
    data = load_question_set(set_name)
    if data is None:
        return []
    return data.get("questions", [])