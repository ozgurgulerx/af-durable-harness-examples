import logging
from datetime import timedelta
from typing import Any

import azure.functions as func
from azure.durable_functions import DurableOrchestrationClient, DurableOrchestrationContext
from pydantic import BaseModel, ValidationError

from harness_examples.shared import (
    build_chat_client,
    build_status_url,
    json_response,
    require_json_mapping,
)

logger = logging.getLogger(__name__)

GOAL_LOOP_OPERATOR_AGENT_NAME = "GoalLoopOperatorAgent"


class GoalLoopInput(BaseModel):
    goal: str
    max_iterations: int = 6
    poll_interval_minutes: int = 1


class NextAction(BaseModel):
    done: bool
    summary: str = ""
    action: str = ""
    wait_minutes: int | None = None


def build_goal_loop_operator_agent():
    return build_chat_client().as_agent(
        name=GOAL_LOOP_OPERATOR_AGENT_NAME,
        instructions=(
            "You are an operations agent. "
            "Given the current state of a task, decide whether the goal is complete. "
            "If not complete, return the next action and how long to wait before checking again. "
            "Return JSON with fields: done, summary, action, wait_minutes."
        ),
    )


def register_example_04(app) -> None:
    @app.activity_trigger(input_name="payload")
    def example_04_observe_external_state(payload: dict) -> dict:
        iteration = int(payload["iteration"])
        goal = payload["goal"]
        if iteration >= 3:
            return {
                "goal": goal,
                "status": "complete",
                "details": "The export job finished successfully.",
            }
        return {
            "goal": goal,
            "status": "pending",
            "details": f"The export job is still running. Check #{iteration}.",
        }

    @app.activity_trigger(input_name="payload")
    def example_04_execute_next_action(payload: dict) -> dict:
        action = payload["action"]
        logger.info("Executing action: %s", action)
        return {"executed": True, "action": action}

    @app.orchestration_trigger(context_name="context")
    def example_04_goal_loop_orchestration(context: DurableOrchestrationContext):
        raw_input = context.get_input()
        payload = GoalLoopInput.model_validate(raw_input)

        agent = app.get_agent(context, GOAL_LOOP_OPERATOR_AGENT_NAME)
        thread = agent.get_new_thread()

        iteration = 0
        while iteration < payload.max_iterations:
            iteration += 1

            context.set_custom_status(
                f"Iteration #{iteration}: observing state for goal '{payload.goal}'."
            )

            observation = yield context.call_activity(
                "example_04_observe_external_state",
                {"goal": payload.goal, "iteration": iteration},
            )

            decision_raw = yield agent.run(
                messages=(
                    f"Goal: {payload.goal}\n"
                    f"Current state: {observation}\n"
                    "Decide whether the goal is complete. "
                    "If complete, return done=true and a summary. "
                    "If not complete, return done=false, the next action, and wait_minutes."
                ),
                thread=thread,
                options={"response_format": NextAction},
            )

            decision = decision_raw.try_parse_value(NextAction)
            if decision is None:
                raise ValueError("Agent returned no structured decision.")

            if decision.done:
                context.set_custom_status(f"Goal achieved: {decision.summary}")
                return {
                    "goal": payload.goal,
                    "iterations": iteration,
                    "result": decision.summary,
                    "lastObservation": observation,
                }

            action = decision.action or "Continue monitoring and prepare for the next check."
            yield context.call_activity(
                "example_04_execute_next_action",
                {"goal": payload.goal, "action": action},
            )

            wait_minutes = decision.wait_minutes or payload.poll_interval_minutes
            context.set_custom_status(
                f"Iteration #{iteration}: action executed. Sleeping for {wait_minutes} minute(s)."
            )
            yield context.create_timer(
                context.current_utc_datetime + timedelta(minutes=wait_minutes)
            )

        raise RuntimeError(f"Goal not achieved after {payload.max_iterations} iterations.")

    @app.route(route="goal-loop/run", methods=["POST"])
    @app.durable_client_input(client_name="client")
    async def example_04_start(
        req: func.HttpRequest,
        client: DurableOrchestrationClient,
    ) -> func.HttpResponse:
        body = require_json_mapping(req)
        if body is None:
            return json_response({"error": "Request body must be valid JSON."}, status_code=400)

        try:
            payload = GoalLoopInput.model_validate(body)
        except ValidationError as exc:
            return json_response({"error": f"Invalid goal loop input: {exc}"}, status_code=400)

        instance_id = await client.start_new(
            orchestration_function_name="example_04_goal_loop_orchestration",
            client_input=payload.model_dump(),
        )
        return json_response(
            {
                "message": "Persistent goal loop started.",
                "instanceId": instance_id,
                "statusQueryGetUri": build_status_url(
                    req.url, instance_id, route="goal-loop"
                ),
            },
            status_code=202,
        )

    @app.route(route="goal-loop/status/{instanceId}", methods=["GET"])
    @app.durable_client_input(client_name="client")
    async def example_04_status(
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
