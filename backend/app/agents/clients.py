import json

from app.agents.tools import TOOLS
from app.config import settings


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
