# Agent Framework Durable Harness Examples

This repo packages the four examples from the blog post into a single runnable Azure Functions project using Microsoft Agent Framework plus Durable Extensions.

The blog presents each example as a small standalone app to keep the concepts clear. This repo combines all four examples into one runnable Function App. The durable behaviors are the same, but some internal agent names are unique in code so the examples can coexist in one host.

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

Simplified shape from the blog:

```python
WRITER_AGENT_NAME = "WriterAgent"

def create_writer_agent():
    return OpenAIChatClient(...).as_agent(
        name=WRITER_AGENT_NAME,
        instructions=(
            "You refine short pieces of text. "
            "When given an initial sentence you enhance it; "
            "when given an improved sentence you polish it further."
        ),
    )

app = AgentFunctionApp(
    agents=[create_writer_agent()],
    enable_health_check=True,
)

@app.orchestration_trigger(context_name="context")
def single_agent_orchestration(context):
    writer = app.get_agent(context, WRITER_AGENT_NAME)
    session = writer.create_session()

    first = yield writer.run(
        messages="Write a concise inspirational sentence about learning.",
        session=session,
    )

    second = yield writer.run(
        messages=f"Improve this further while keeping it under 25 words: {first.text}",
        session=session,
    )

    return second.text
```

Runtime surface:

Start:

```http
POST http://localhost:7071/api/singleagent/run
```

Status:

```http
GET http://localhost:7071/api/singleagent/status/<instanceId>
```

What Durable Extensions add here:

- Durable progression across steps
- Shared agent session across steps
- Instance identity and queryable status
- Restart-safe continuation

In other words, Agent Framework gives you the workflow logic. Durable Extensions give that workflow a durable runtime object with tracked step boundaries, status by `instanceId`, and recovery after restarts.

## Example 03 - Human-in-the-loop orchestration

Simplified shape from the blog:

```python
WRITER_AGENT_NAME = "WriterAgent"
HUMAN_APPROVAL_EVENT = "HumanApproval"

class ContentGenerationInput(BaseModel): ...
class GeneratedContent(BaseModel): ...
class HumanApproval(BaseModel): ...

def create_writer_agent():
    return OpenAIChatClient(...).as_agent(...)

app = AgentFunctionApp(
    agents=[create_writer_agent()],
    enable_health_check=True,
)

@app.activity_trigger(input_name="content")
def notify_user_for_approval(content: dict) -> None:
    ...

@app.activity_trigger(input_name="content")
def publish_content(content: dict) -> None:
    ...

@app.orchestration_trigger(context_name="context")
def content_generation_hitl_orchestration(context):
    ...
    approval_task = context.wait_for_external_event(HUMAN_APPROVAL_EVENT)
    timeout_task = context.create_timer(...)
    winner = yield context.task_any([approval_task, timeout_task])
    ...
```

Runtime surface:

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

What Durable Extensions add here:

- Durable suspension while waiting for a human
- External event resume
- Timeout handling as part of the workflow
- Persisted review loop state

This is the clearest example of the harness governing a human-gated process. Waiting becomes durable state, approval becomes an external re-entry event, timeouts become part of the workflow contract, and the orchestration can survive long delays and host restarts.

## Example 04 - Persistent goal loop

Simplified shape from the blog:

```python
GOAL_LOOP_AGENT_NAME = "GoalLoopAgent"

class GoalLoopInput(BaseModel): ...
class NextAction(BaseModel): ...

def create_goal_loop_agent():
    return OpenAIChatClient(...).as_agent(...)

app = AgentFunctionApp(
    agents=[create_goal_loop_agent()],
    enable_health_check=True,
)

@app.activity_trigger(input_name="payload")
def observe_external_state(payload: dict) -> dict:
    ...

@app.activity_trigger(input_name="payload")
def execute_next_action(payload: dict) -> dict:
    ...

@app.orchestration_trigger(context_name="context")
def persistent_goal_loop(context):
    ...
    while iteration < payload.max_iterations:
        observation = yield context.call_activity(...)
        decision_raw = yield agent.run(...)
        yield context.call_activity(...)
        yield context.create_timer(...)
```

Runtime surface:

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

What Durable Extensions add here:

- Durable observe-decide-act loops
- Timer-backed waiting without pinned compute
- Persisted iteration state
- Bounded long-running autonomy

Agent Framework can model the same loop logic. Durable Extensions make that loop durable as a runtime object: persisted iteration state, timer-driven waiting, restart-safe continuation, and status you can query from outside the process.

## Files

- [function_app.py](./function_app.py) - app bootstrap
- [harness_examples/example_01_single_agent.py](./harness_examples/example_01_single_agent.py)
- [harness_examples/example_02_sequential_orchestration.py](./harness_examples/example_02_sequential_orchestration.py)
- [harness_examples/example_03_hitl.py](./harness_examples/example_03_hitl.py)
- [harness_examples/example_04_persistent_loop.py](./harness_examples/example_04_persistent_loop.py)
- [examples.http](./examples.http) - ready-to-run requests for VS Code REST Client
