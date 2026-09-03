import json

from app.agents.tools import TOOLS
from app.config import settings

# Groq's flagship tool-calling-capable model at time of writing. Check
# https://console.groq.com/docs/models for current options if this changes.
MODEL = "llama-3.3-70b-versatile"
MAX_TURNS = 6


def _build_client():
    from groq import Groq

    return Groq(api_key=settings.GROQ_API_KEY)


def run_agent_loop(
    system_prompt: str,
    user_message: str,
    tool_executor: dict,
    client=None,
    max_turns: int = MAX_TURNS,
    trace: list | None = None,
) -> dict:
    """
    Runs the tool-calling conversation until the model calls
    submit_recovery_decision, then returns that call's parsed arguments.

    `client` is injected rather than constructed internally so tests can
    pass a fake object with a `.chat.completions.create(...)` method - the
    real Groq API is never touched by our test suite.

    `trace`, if a list is passed in, gets appended to in-place with every
    non-submit tool call made (name, input, output) — lets a caller (e.g.
    the "Try your own scenario" dashboard feature) show exactly what the
    agent looked up before deciding. Optional and backward compatible:
    every existing caller that doesn't pass this gets identical behavior.

    Note the shape here differs from Anthropic's tool-use API in three
    ways that matter: (1) the system prompt is just another message with
    role="system", not a separate parameter; (2) each tool call's arguments
    arrive as a JSON STRING that we must json.loads() ourselves, not an
    already-parsed dict; (3) tool results go back as their own role="tool"
    messages (one per call), not a single user message containing a list
    of tool_result blocks.
    """
    if client is None:
        client = _build_client()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    for _ in range(max_turns):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=1024,
        )
        message = response.choices[0].message
        tool_calls = message.tool_calls or []

        if not tool_calls:
            raise RuntimeError(
                "Agent ended its turn without calling a tool or submitting a decision."
            )

        # Re-append the assistant turn as a plain dict so the conversation
        # history stays a consistent, serializable shape regardless of the
        # SDK's internal object types.
        messages.append(
            {
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                    for call in tool_calls
                ],
            }
        )

        submitted_decision = None
        for call in tool_calls:
            name = call.function.name
            args = json.loads(call.function.arguments)

            if name == "submit_recovery_decision":
                submitted_decision = args
                continue

            result = tool_executor[name](args)
            if trace is not None:
                trace.append({"tool": name, "input": args, "output": result})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result),
                }
            )

        if submitted_decision is not None:
            return submitted_decision

    raise RuntimeError(f"Agent did not submit a decision within {max_turns} turns.")
