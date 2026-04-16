import logging

import azure.functions as func
from azure.durable_functions import DurableOrchestrationClient, DurableOrchestrationContext

from harness_examples.shared import build_chat_client, build_status_url, json_response

logger = logging.getLogger(__name__)

WRITER_REFINER_AGENT_NAME = "WriterRefinerAgent"


def build_refiner_agent():
    return build_chat_client().as_agent(
        name=WRITER_REFINER_AGENT_NAME,
        instructions=(
            "You refine short pieces of text. "
            "When given an initial sentence you enhance it; "
            "when given an improved sentence you polish it further."
        ),
    )


def register_example_02(app) -> None:
    @app.orchestration_trigger(context_name="context")
    def example_02_single_agent_orchestration(context: DurableOrchestrationContext):
        writer = app.get_agent(context, WRITER_REFINER_AGENT_NAME)
        session = writer.create_session()

        first = yield writer.run(
            messages="Write a concise inspirational sentence about learning.",
            session=session,
        )
        first_text = first.text.strip() or "Learning grows when curiosity turns effort into progress."

        second = yield writer.run(
            messages=f"Improve this further while keeping it under 25 words: {first_text}",
            session=session,
        )

        return second.text.strip() or "Learning grows when curiosity turns steady effort into mastery."

    @app.route(route="singleagent/run", methods=["POST"])
    @app.durable_client_input(client_name="client")
    async def example_02_start(
        req: func.HttpRequest,
        client: DurableOrchestrationClient,
    ) -> func.HttpResponse:
        instance_id = await client.start_new(
            orchestration_function_name="example_02_single_agent_orchestration",
        )
        logger.info("[example_02] Started orchestration %s", instance_id)
        return json_response(
            {
                "message": "Single-agent orchestration started.",
                "instanceId": instance_id,
                "statusQueryGetUri": build_status_url(
                    req.url, instance_id, route="singleagent"
                ),
            },
            status_code=202,
        )

    @app.route(route="singleagent/status/{instanceId}", methods=["GET"])
    @app.durable_client_input(client_name="client")
    async def example_02_status(
        req: func.HttpRequest,
        client: DurableOrchestrationClient,
    ) -> func.HttpResponse:
        instance_id = req.route_params.get("instanceId")
        if not instance_id:
            return json_response({"error": "Missing instanceId."}, status_code=400)

        status = await client.get_status(instance_id)
        if status is None:
            return json_response({"error": "Instance not found."}, status_code=404)

        payload = {
            "instanceId": status.instance_id,
            "runtimeStatus": status.runtime_status.name if status.runtime_status else None,
        }
        if status.output is not None:
            payload["output"] = status.output
        return json_response(payload)
