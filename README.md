# Agent Framework Durable Harness Examples

This repo packages the four examples from the blog post into a single runnable Azure Functions project using Microsoft Agent Framework plus Durable Extensions.

The examples focus on the harness layer around probabilistic agents:

1. `Example 01` - Durable hosting surface for a single agent
2. `Example 02` - Durable sequential orchestration on a shared thread
3. `Example 03` - Human approval, external events, timeout, and resume
4. `Example 04` - Persistent goal loop with timers and durable progress

## Prerequisites

- Python 3.11+
- Azure Functions Core Tools 4.x
- Azurite
- Docker
- An Azure OpenAI resource and chat deployment
- Either an Azure OpenAI API key or Azure CLI / managed identity auth

## Setup

```bash
git clone https://github.com/ozgurgulerx/af-durable-harness-examples.git
cd af-durable-harness-examples

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
cp local.settings.json.template local.settings.json
```

Update `local.settings.json` with your Azure OpenAI settings.

- If you want to use an API key, set `AZURE_OPENAI_API_KEY`.
- If you want to use Microsoft Entra ID instead, leave `AZURE_OPENAI_API_KEY` empty and run `az login`.

## Local infrastructure

Start Azurite:

```bash
azurite
```

Start the Durable Task Scheduler emulator:

```bash
docker run -d --name dts-emulator -p 8080:8080 -p 8082:8082 mcr.microsoft.com/dts/dts-emulator:latest
```

The DTS dashboard is available at `http://localhost:8082`.

## Run the app

```bash
func start
```

## Example 01 - Single durable agent

The repo keeps all four examples in one Function App. The Example 01 part is intentionally this small:

```python
import os
import azure.functions as func

from agent_framework.azure import AgentFunctionApp
from agent_framework.openai import OpenAIChatClient
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

def create_joker_agent():
    client_id = os.getenv("AZURE_CLIENT_ID")
    credential = (
        ManagedIdentityCredential(client_id=client_id)
        if client_id
        else DefaultAzureCredential()
    )

    return OpenAIChatClient(
        model=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        credential=credential,
    ).as_agent(
        name="Joker",
        instructions="You are good at telling jokes.",
    )

app = AgentFunctionApp(
    agents=[create_joker_agent()],
    http_auth_level=func.AuthLevel.FUNCTION,
    enable_health_check=True,
    max_poll_retries=50,
)
```

For brevity, this snippet shows the Entra ID / managed identity path. The repo code also supports `AZURE_OPENAI_API_KEY`.

This is still the same Agent Framework mental model: define an agent, give it instructions, host it. What changes is the runtime contract around it.

Request:

```http
GET http://localhost:7071/api/health
```

```http
POST http://localhost:7071/api/agents/joker/run
Content-Type: application/json

{
  "message": "Tell me a short joke about cloud reliability.",
  "thread_id": "thread-001",
  "wait_for_response": false
}
```

A typical response from the built-in durable agent route currently looks like this:

```json
{
  "response": "",
  "message": "Tell me a short joke about cloud reliability.",
  "thread_id": "thread-001",
  "status": "success",
  "correlation_id": "<guid>",
  "message_count": 2
}
```

The important point is not the exact joke payload. The model is still probabilistic. Durable Extensions do not make the model deterministic. They make the execution governable.

What gets bounded here:

- Built-in HTTP hosting surface
- Durable thread identity
- Hosted request lifecycle with correlation
- Health endpoint at `GET /api/health`
- State managed by the durable host instead of ad hoc application plumbing

## Example 02 - Durable sequential orchestration

Start:

```http
POST http://localhost:7071/api/singleagent/run
```

Status:

```http
GET http://localhost:7071/api/singleagent/status/<instanceId>
```

Benefit highlighted:

- Durable progression across steps
- Shared agent thread across steps
- Instance identity and queryable status
- Restart-safe continuation

## Example 03 - Human-in-the-loop orchestration

Start:

```http
POST http://localhost:7071/api/hitl/run
Content-Type: application/json

{
  "topic": "The Future of Artificial Intelligence",
  "max_review_attempts": 3,
  "approval_timeout_hours": 24
}
```

Approve or reject:

```http
POST http://localhost:7071/api/hitl/approve/<instanceId>
Content-Type: application/json

{
  "approved": false,
  "feedback": "Please add more examples and technical depth."
}
```

Status:

```http
GET http://localhost:7071/api/hitl/status/<instanceId>
```

Benefit highlighted:

- Durable suspension while waiting for a human
- External event resume
- Timeout handling as part of the workflow
- Persisted review loop state

## Example 04 - Persistent goal loop

Start:

```http
POST http://localhost:7071/api/goal-loop/run
Content-Type: application/json

{
  "goal": "Watch for the export job to complete and deliver the result",
  "max_iterations": 6,
  "poll_interval_minutes": 1
}
```

Status:

```http
GET http://localhost:7071/api/goal-loop/status/<instanceId>
```

Benefit highlighted:

- Durable observe-decide-act loops
- Timer-backed waiting without pinned compute
- Persisted iteration state
- Bounded long-running autonomy

## Files

- [function_app.py](./function_app.py) - app bootstrap
- [harness_examples/example_01_single_agent.py](./harness_examples/example_01_single_agent.py)
- [harness_examples/example_02_sequential_orchestration.py](./harness_examples/example_02_sequential_orchestration.py)
- [harness_examples/example_03_hitl.py](./harness_examples/example_03_hitl.py)
- [harness_examples/example_04_persistent_loop.py](./harness_examples/example_04_persistent_loop.py)
- [examples.http](./examples.http) - ready-to-run requests for VS Code REST Client
