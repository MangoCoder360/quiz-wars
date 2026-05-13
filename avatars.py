class Avatar:
    """Base avatar class that the avatars will inherit from"""
    def __init__(self, name="Avatar", desc="Generic avatar"):
        self.name = name
        self.desc = desc

class Wizard(Avatar):
    def __init__(self):
        super().__init__(name="Wizard", desc="A powerful spellcaster")
        self.hp = 25

class Knight(Avatar):
    def __init__(self):
        super().__init__(name="Knight", desc="A brave warrior")
        self.hp = 40

class Monk(Avatar):
    def __init__(self):
        super().__init__(name="Monk", desc="A disciplined fighter")
        self.hp = 35