from agent_framework.azure import AgentFunctionApp

from harness_examples.example_01_single_agent import build_joker_agent
from harness_examples.example_02_sequential_orchestration import (
    build_refiner_agent,
    register_example_02,
)
from harness_examples.example_03_hitl import build_approval_writer_agent, register_example_03
from harness_examples.example_04_persistent_loop import (
    build_goal_loop_operator_agent,
    register_example_04,
)


app = AgentFunctionApp(
    agents=[
        build_joker_agent(),
        build_refiner_agent(),
        build_approval_writer_agent(),
        build_goal_loop_operator_agent(),
    ],
    enable_health_check=True,
    max_poll_retries=50,
)

register_example_02(app)
register_example_03(app)
register_example_04(app)

