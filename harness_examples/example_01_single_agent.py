import os

from agent_framework.openai import OpenAIChatClient
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential


def _get_credential():
    client_id = os.getenv("AZURE_CLIENT_ID")
    if client_id:
        return ManagedIdentityCredential(client_id=client_id)
    return DefaultAzureCredential()


def _get_deployment_name() -> str:
    deployment_name = (
        os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME")
        or os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT")
        or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
    )
    if deployment_name:
        return deployment_name
    raise RuntimeError(
        "Missing Azure OpenAI deployment name. "
        "Set AZURE_OPENAI_CHAT_DEPLOYMENT_NAME or AZURE_OPENAI_DEPLOYMENT_NAME."
    )


def create_joker_agent():
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    if not endpoint:
        raise RuntimeError("Missing required environment variable: AZURE_OPENAI_ENDPOINT")

    client_kwargs = {
        "model": _get_deployment_name(),
        "azure_endpoint": endpoint,
        "api_version": os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
    }

    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    if api_key:
        client_kwargs["api_key"] = api_key
    else:
        client_kwargs["credential"] = _get_credential()

    return OpenAIChatClient(**client_kwargs).as_agent(
        name="Joker",
        instructions="You are good at telling jokes.",
    )
