from harness_examples.shared import build_chat_client


def build_joker_agent():
    return build_chat_client().as_agent(
        name="Joker",
        instructions="You are good at telling jokes.",
    )
