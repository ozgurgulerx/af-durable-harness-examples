import json
import os
from collections.abc import Mapping
from typing import Any

import azure.functions as func
from agent_framework.openai import OpenAIChatClient
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential


def get_credential():
    client_id = os.environ.get("AZURE_CLIENT_ID")
    if client_id:
        return ManagedIdentityCredential(client_id=client_id)
    return DefaultAzureCredential()


def get_required_env(name: str) -> str:
    value = os.environ.get(name)
    if value:
        return value
    raise RuntimeError(f"Missing required environment variable: {name}")


def build_chat_client() -> OpenAIChatClient:
    kwargs: dict[str, Any] = {
        "model": get_required_env("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME"),
        "azure_endpoint": get_required_env("AZURE_OPENAI_ENDPOINT"),
        "api_version": os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
    }

    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    if api_key:
        kwargs["api_key"] = api_key
    else:
        kwargs["credential"] = get_credential()

    return OpenAIChatClient(**kwargs)


def build_status_url(request_url: str, instance_id: str, *, route: str) -> str:
    base_url, _, _ = request_url.partition("/api/")
    if not base_url:
        base_url = request_url.rstrip("/")
    return f"{base_url}/api/{route}/status/{instance_id}"


def json_response(payload: dict[str, Any], status_code: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        body=json.dumps(payload),
        status_code=status_code,
        mimetype="application/json",
    )


def require_json_mapping(req: func.HttpRequest) -> Mapping[str, Any] | None:
    try:
        body = req.get_json()
    except ValueError:
        return None
    if not isinstance(body, Mapping):
        return None
    return body
