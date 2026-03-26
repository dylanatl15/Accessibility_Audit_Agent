import random
from datetime import datetime
from omniagents import function_tool


@function_tool
def get_current_time() -> str:
    """Get the current date and time."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@function_tool
def calculate(expression: str) -> str:
    """Evaluate a math expression and return the result.

    Args:
        expression: A mathematical expression to evaluate (e.g. '2 + 2', 'sqrt(16)').
    """
    import math

    allowed = {
        k: v
        for k, v in math.__dict__.items()
        if not k.startswith("_")
    }
    allowed.update({"abs": abs, "round": round, "min": min, "max": max})
    try:
        result = eval(expression, {"__builtins__": {}}, allowed)
        return str(result)
    except Exception as e:
        return f"Error: {e}"


@function_tool
def flip_coin() -> str:
    """Flip a coin and return heads or tails."""
    return random.choice(["heads", "tails"])


@function_tool
def roll_dice(sides: int = 6) -> str:
    """Roll a dice and return the result.

    Args:
        sides: Number of sides on the dice (default 6).
    """
    return str(random.randint(1, sides))
