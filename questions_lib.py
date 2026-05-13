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