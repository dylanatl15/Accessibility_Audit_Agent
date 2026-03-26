# Basic Agent Starter Kit

A minimal working AI agent built with [OmniAgents](https://pypi.fury.io/ericmichael/). Clone this repo and have a running agent in under 5 minutes.

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Configure your environment
cp .env.example .env
# Edit .env and add your API key
```

## Run

```bash
# Web UI (opens browser)
omniagents run -c agent.yml

# Terminal UI
omniagents run -c agent.yml --mode ink

# API server (for programmatic access)
omniagents run -c agent.yml --mode server --port 9494
```

## Project Structure

```
basic_agent/
├── agent.yml          # Agent configuration — name, model, tools, settings
├── instructions.md    # System prompt — tells the agent how to behave
├── tools/
│   └── utils.py       # Custom tools — get_current_time, calculate, flip_coin, roll_dice
├── .env.example       # Environment variable template
└── requirements.txt   # Python dependencies
```

## Customizing Your Agent

**Change the personality** — Edit `instructions.md` with a new system prompt.

**Add builtin tools** — Add any of these to the `tools` list in `agent.yml` (no code needed):

`read_file`, `write_file`, `edit_file`, `execute_bash`, `glob_files`, `grep_files`, `list_directory`, `web_search`, `download_file`, `read_image`, `display_artifact`, `scholar_search`, `youtube_search`

**Create custom tools** — Add a Python file in `tools/` with decorated functions:

```python
from omniagents import function_tool

@function_tool
def my_tool(param: str) -> str:
    """Description of what this tool does.

    Args:
        param: What this parameter is for.
    """
    return f"Result: {param}"
```

Then add the tool name to the `tools` list in `agent.yml`.

**Generate tools from an API** — If you have an OpenAPI spec:

```bash
omniagents generate openapi --spec my_api.yaml --name my_api
```

This creates `tools/my_api_tools.py` with ready-to-use tools. Add them to `agent.yml` by name.
