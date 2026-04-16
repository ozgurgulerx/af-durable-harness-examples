"""Blog Example 03: human approval, durable waiting, and resume."""

import logging
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

import azure.functions as func
from azure.durable_functions import DurableOrchestrationClient, DurableOrchestrationContext
from pydantic import BaseModel, ValidationError

from harness_examples.shared import (
    build_chat_client,
    build_status_url,
    json_response,
    parse_model_response,
    require_json_mapping,
)

logger = logging.getLogger(__name__)

APPROVAL_WRITER_AGENT_NAME = "ApprovalWriterAgent"
HUMAN_APPROVAL_EVENT = "HumanApproval"


class ContentGenerationInput(BaseModel):
    topic: str
    max_review_attempts: int = 3
    approval_timeout_hours: float = 72


class GeneratedContent(BaseModel):
    title: str
    content: str


class HumanApproval(BaseModel):
    approved: bool
    feedback: str = ""


def build_approval_writer_agent():
    return build_chat_client().as_agent(
        name=APPROVAL_WRITER_AGENT_NAME,
        instructions=(
            "You are a professional content writer. "
            "Return valid JSON only with exactly these fields: "
            "'title' and 'content'. Do not wrap the JSON in markdown fences."
        ),
    )


def register_example_03(app) -> None:
    @app.activity_trigger(input_name="content")
    def example_03_notify_user_for_approval(content: dict) -> None:
        model = GeneratedContent.model_validate(content)
        logger.info("Approval requested for title: %s", model.title or "(untitled)")

    @app.activity_trigger(input_name="content")
    def example_03_publish_content(content: dict) -> None:
        model = GeneratedContent.model_validate(content)
        logger.info("Publishing content: %s", model.title or "(untitled)")

    @app.orchestration_trigger(context_name="context")
    def example_03_hitl_orchestration(context: DurableOrchestrationContext):
        payload_raw = context.get_input()
        if not isinstance(payload_raw, Mapping):
            raise ValueError("Content generation input is required.")

        payload = ContentGenerationInput.model_validate(payload_raw)
        writer = app.get_agent(context, APPROVAL_WRITER_AGENT_NAME)
        session = writer.create_session()

        initial_raw = yield writer.run(
            messages=f"Write a short article about '{payload.topic}'.",
            session=session,
        )

        content = parse_model_response(
            initial_raw,
            GeneratedContent,
            fallback=GeneratedContent(
                title=f"{payload.topic} Overview",
                content=(
                    f"{payload.topic} is evolving quickly across products, infrastructure, "
                    "and policy. A durable harness matters when draft generation, approvals, "
                    "and publishing need to survive real-world delays and retries."
                ),
            ),
        )

        attempt = 0
        while attempt < payload.max_review_attempts:
            attempt += 1
            context.set_custom_status(
                f"Requesting human feedback. Iteration #{attempt}. "
                f"Timeout: {payload.approval_timeout_hours} hour(s)."
            )

            yield context.call_activity(
                "example_03_notify_user_for_approval", content.model_dump()
            )

            approval_task = context.wait_for_external_event(HUMAN_APPROVAL_EVENT)
            timeout_task = context.create_timer(
                context.current_utc_datetime
                + timedelta(hours=payload.approval_timeout_hours)
            )

            winner = yield context.task_any([approval_task, timeout_task])

            if winner == approval_task:
                timeout_task.cancel()  # type: ignore[attr-defined]
                approval_payload = approval_task.result
                if isinstance(approval_payload, str):
                    approval = HumanApproval.model_validate_json(approval_payload)
                else:
                    approval = HumanApproval.model_validate(approval_payload)

                if approval.approved:
                    context.set_custom_status("Content approved. Publishing...")
                    yield context.call_activity(
                        "example_03_publish_content", content.model_dump()
                    )
                    return {"content": content.content}

                rewritten_raw = yield writer.run(
                    messages=(
                        "The content was rejected. Rewrite it using this feedback:\n\n"
                        f"{approval.feedback or 'No feedback provided.'}\n\n"
                        "Return valid JSON only with exactly these fields: "
                        "'title' and 'content'."
                    ),
                    session=session,
                )
                content = parse_model_response(
                    rewritten_raw,
                    GeneratedContent,
                    fallback=GeneratedContent(
                        title=f"{payload.topic} Revised Overview",
                        content=(
                            f"{payload.topic} is evolving quickly across products, infrastructure, "
                            "and policy. This revised draft adds more technical depth and concrete "
                            f"examples while incorporating the reviewer feedback: {approval.feedback or 'none'}."
                        ),
                    ),
                )
            else:
                raise TimeoutError(
                    f"Human approval timed out after {payload.approval_timeout_hours} hour(s)."
                )

        raise RuntimeError(
            f"Content could not be approved after {payload.max_review_attempts} iteration(s)."
        )

    @app.route(route="hitl/run", methods=["POST"])
    @app.durable_client_input(client_name="client")
    async def example_03_start(
        req: func.HttpRequest,
        client: DurableOrchestrationClient,
    ) -> func.HttpResponse:
        body = require_json_mapping(req)
        if body is None:
            return json_response({"error": "Request body must be valid JSON."}, status_code=400)

        try:
            payload = ContentGenerationInput.model_validate(body)
        except ValidationError as exc:
            return json_response({"error": f"Invalid content generation input: {exc}"}, status_code=400)

        instance_id = await client.start_new(
            orchestration_function_name="example_03_hitl_orchestration",
            client_input=payload.model_dump(),
        )
        return json_response(
            {
                "message": "HITL content generation orchestration started.",
                "topic": payload.topic,
                "instanceId": instance_id,
                "statusQueryGetUri": build_status_url(req.url, instance_id, route="hitl"),
            },
            status_code=202,
        )

    @app.route(route="hitl/approve/{instanceId}", methods=["POST"])
    @app.durable_client_input(client_name="client")
    async def example_03_approve(
        req: func.HttpRequest,
        client: DurableOrchestrationClient,
    ) -> func.HttpResponse:
        instance_id = req.route_params.get("instanceId")
        if not instance_id:
            return json_response({"error": "Missing instanceId."}, status_code=400)

        body = require_json_mapping(req)
        if body is None:
            return json_response({"error": "Approval response is required."}, status_code=400)

        try:
            approval = HumanApproval.model_validate(body)
        except ValidationError as exc:
            return json_response({"error": f"Invalid approval payload: {exc}"}, status_code=400)

        await client.raise_event(instance_id, HUMAN_APPROVAL_EVENT, approval.model_dump())
        return json_response(
            {
                "message": "Human approval sent to orchestration.",
                "instanceId": instance_id,
                "approved": approval.approved,
            }
        )

    @app.route(route="hitl/status/{instanceId}", methods=["GET"])
    @app.durable_client_input(client_name="client")
    async def example_03_status(
        req: func.HttpRequest,
        client: DurableOrchestrationClient,
    ) -> func.HttpResponse:
        instance_id = req.route_params.get("instanceId")
        if not instance_id:
            return json_response({"error": "Missing instanceId."}, status_code=400)

        status = await client.get_status(
            instance_id,
            show_history=False,
            show_history_output=False,
            show_input=True,
        )
        if status is None or getattr(status, "runtime_status", None) is None:
            return json_response({"error": "Instance not found."}, status_code=404)

        payload = {
            "instanceId": getattr(status, "instance_id", None),
            "runtimeStatus": getattr(status.runtime_status, "name", None)
            if getattr(status, "runtime_status", None)
            else None,
            "workflowStatus": getattr(status, "custom_status", None),
        }
        if getattr(status, "input_", None) is not None:
            payload["input"] = status.input_
        if getattr(status, "output", None) is not None:
            payload["output"] = status.output
        if getattr(status, "failure_details", None) is not None:
            payload["failureDetails"] = status.failure_details
        return json_response(payload)
