# AGENTS.md — AI Agent Starter Kit

## What this project is

This is a starter kit for building AI agents with OmniAgents. Students use `omniagents run -c agent.yml` to run agents and modify the YAML config, instructions, and custom tools to build their own.

## Key conventions

- **Agent config**: `agent.yml` is the entry point. All agent settings (model, tools, instructions, etc.) go here.
- **Instructions**: `instructions.md` is the system prompt. Write it in plain markdown — tell the model who it is and how to behave.
- **Custom tools**: Python files in `tools/` with functions decorated with `@function_tool` from `omniagents` (not from `agents` — the import source matters for tool discovery).
- **Environment**: API keys and config go in `.env` (never committed). See `.env.example` for the template.
- **Model**: Default model is `gpt-5.2` via `OPENAI_BASE_URL=https://rgvaiclass.com/v1`.

## How to help the user

When the user asks to build or modify an agent:

1. **Check the skill** — There is an `omniagents-basic` skill in `.omni_code/skills/` with comprehensive documentation on agent creation, builtin tools, custom tools, OpenAPI integration, skills, voice mode, and more. Read it before answering.
2. **Edit existing files** — Prefer modifying `agent.yml`, `instructions.md`, or files in `tools/` over creating new agent directories unless the user explicitly wants a separate agent.
3. **Test changes** — After modifying tools or config, remind the user to restart the agent with `omniagents run -c agent.yml`. Use `--approvals skip` during development to avoid tool approval prompts.

## Common tasks

- **Adding a builtin tool**: Add the tool name to the `tools` list in `agent.yml`. No code needed.
- **Creating a custom tool**: Create a `.py` file in `tools/`, decorate functions with `@function_tool`, add tool names to `agent.yml`.
- **Generating tools from an API**: Run `omniagents generate openapi --spec spec.yaml --name api_name`, then add generated tool names to `agent.yml`.
- **Changing the model**: Update the `model` field in `agent.yml`.
- **Using search tools**: `web_search`, `scholar_search`, and `youtube_search` require `SERPAPI_API_KEY` in `.env`.

## Important gotchas

- Import `function_tool` from `omniagents`, not from `agents`. The omniagents decorator adds a discovery marker (`_is_omniagents_core_tool`) that the loader requires.
- Tool functions need type hints on all parameters — these become the JSON schema the model sees.
- The docstring is the tool description. Write it clearly — it directly affects how well the model uses the tool.
- `.env` files are auto-loaded from the agent directory. Never commit `.env` to git.
- If tools aren't being discovered, check the import and make sure the file is in `tools/` (not a subdirectory).

## Code style

- Python 3.10+. Use type hints on all tool parameters.
- Keep tools simple and focused — one clear purpose per function.
- Return `str` from tools for simple results. Use `Dict[str, Any]` for structured data.
- Prefer editing existing files over creating new ones unless building a separate agent.

## Don't

- Don't commit `.env` or API keys.
- Don't create overly complex abstractions — this is a learning environment.
- Don't modify files in `.omni_code/skills/` unless the user explicitly asks.
- Don't install packages without asking — students may have limited environments.
