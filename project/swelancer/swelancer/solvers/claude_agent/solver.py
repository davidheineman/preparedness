import asyncio
import json
import logging
import os
import re
import shlex
from textwrap import dedent
from typing import Any, AsyncGenerator, cast

import structlog
import tenacity
import tiktoken
from dotenv import load_dotenv
from nanoeval_alcatraz.alcatraz_computer_interface import (
    AlcatrazComputerRuntime,
)
from typing_extensions import override

import chz
from nanoeval.contrib.utils import run_with_startup_timeout
from nanoeval.eval import RolloutSystemError
from nanoeval.solvers.computer_tasks.code_execution_interface import (
    ComputerRuntime,
    RuntimeConfig,
)
from nanoeval.solvers.computer_tasks.solver import PythonCodingSolver
from nanoeval.solvers.computer_tasks.steps import (
    FinalResult,
    Step,
)
from nanoeval.solvers.computer_tasks.task import ComputerTask
from swelancer.eval import SWELancerTask

logger = structlog.stdlib.get_logger(component=__name__)

load_dotenv()

STARTUP_TIMEOUT = 1200  # seconds (20 mins)

ALLOWED_TOOLS = [
    "Bash",
    "Edit",
    "Write",
    "Read",
    "Glob",
    "Grep",
    "LS",
    "WebFetch",
    "NotebookEdit",
    "NotebookRead",
    "TodoRead",
    "TodoWrite",
    "Agent",
]


# @davidh -- Doesn't properly replace:
# - name: Kill all node processes if they exist
#     shell: ""
#     failed_when: false
NPM_FIX = """
old='pgrep -f node && pkill -f node || true'; new='pgrep -af node | grep webpack-dev | awk '\''{print $1}'\'' | xargs -r kill'; grep -qF "$old" /app/tests/run_tests.yml && sed -i "s#$old#$new#" /app/tests/run_tests.yml || true
"""


@chz.chz
class ClaudeCodeSolver(PythonCodingSolver):
    computer_runtime: ComputerRuntime = chz.field(default_factory=AlcatrazComputerRuntime)

    name: str = chz.field(default="ClaudeCodeSolver")
    model: str = chz.field(
        default="anthropic/claude-sonnet-4-20250514",
        doc="Claude model to use for the solver",
    )

    runtime_config: RuntimeConfig = chz.field(default_factory=RuntimeConfig)

    def shortname(self) -> str:
        return "claude-code-solver"

    def _env(self) -> dict[str, str]:
        env = {
            "ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"],
            "FORCE_AUTO_BACKGROUND_TASKS": "1",
            "ENABLE_BACKGROUND_TASKS": "1",
        }
        env["ANTHROPIC_MODEL"] = self.model.removeprefix("anthropic/")
        return env

    @override
    async def run(self, task: ComputerTask) -> AsyncGenerator[Step | FinalResult, None]:
        ctx_logger = logger.bind(
            run_group_id=task.run_group_id,
            runs_dir=task.runs_dir,
            run_id=task.run_id,
        )

        try:
            ctx_logger.info("Starting computer...", destinations=["run"])
            async with run_with_startup_timeout(
                self.computer_runtime, task, STARTUP_TIMEOUT
            ) as computer:
                # Get task prompt
                assert "content" in task.prompt[0]
                assert isinstance(task.prompt[0]["content"], str)
                instruction = task.prompt[0]["content"]

                # Set environment variables in the container
                env_vars = self._env()
                for key, value in env_vars.items():
                    escaped_value = shlex.quote(value)
                    await computer.check_shell_command(f"echo 'export {key}={escaped_value}' >> ~/.bashrc")
                    ctx_logger.info(f"Set environment variable {key}", destinations=["run"])

                # Run the task setup
                async with asyncio.timeout(2400):
                    try:
                        await task.setup(computer, self.runtime_config)
                    except Exception as e:
                        raise RolloutSystemError(f"Error during task setup: {e}") from e

                # Unzip locked testing files
                ctx_logger.info("Unzipping tests", destinations=["run"])
                res = await computer.check_shell_command(
                    "unzip -q -P 'secretpasswordhere' -o /app/tests.zip -d /app/tests"
                )
                ctx_logger.info(res.output.decode("utf-8"), destinations=["run"])

                # Add the NPM fix
                ctx_logger.info("Adding npm fix", destinations=["run"])
                res = await computer.check_shell_command(NPM_FIX)
                ctx_logger.info(res.output.decode("utf-8"), destinations=["run"])
                
                # Run claude code setup
                async with asyncio.timeout(2400):
                    try:
                        # Upload setup.sh
                        setup_script_path = os.path.join(os.path.dirname(__file__), "setup.sh")
                        with open(setup_script_path, "rb") as f:
                            setup_script_content = f.read()
                        
                        await computer.upload(setup_script_content, "/tmp/setup.sh")
                        
                        # Run setup.sh
                        await computer.check_shell_command("chmod +x /tmp/setup.sh")
                        execution_res = await computer.check_shell_command("/tmp/setup.sh")
                        execution_output = execution_res.output.decode(
                            "utf-8", errors="replace"
                        )
                        ctx_logger.info(execution_output, destinations=["run"])
                        
                        ctx_logger.info("Claude code setup completed successfully", destinations=["run"])
                    except Exception as e:
                        raise RolloutSystemError(f"Error when initializing claude code: {e}") from e

                ctx_logger.info(
                    "Setup complete",
                    destinations=["run"],
                )

                # Query the Claude Code agent
                # @davidh -- Hard-coded version of NVM here
                try:
                    # escaped_instruction = shlex.quote(instruction)
                    # execution_res = await computer.check_shell_command(
                    #     'bash -c "' +
                    #     f'/root/.nvm/versions/node/v22.18.0/bin/claude --verbose --output-format stream-json -p {escaped_instruction} --allowedTools {" ".join(ALLOWED_TOOLS)}'
                    #     + '"'
                    # )

                    prompt_path = "/tmp/prompt.txt"

                    # First: write the prompt safely to a file
                    await computer.upload(instruction.encode('utf-8'), prompt_path)

                    # Second: invoke claude reading from that file
                    cmd = (
                        "source ~/.bashrc; "
                        "/root/.nvm/versions/node/v22.19.0/bin/node "
                        "/root/.nvm/versions/node/v22.19.0/bin/claude "
                        "--verbose --output-format stream-json "
                        f"-p \"$(cat {prompt_path})\" "
                        f"--allowedTools {' '.join(ALLOWED_TOOLS)}"
                    )
                    execution_res = await computer.check_shell_command(
                        "bash -c -i " + shlex.quote(cmd)
                    )

                    execution_output = execution_res.output.decode(
                        "utf-8", errors="replace"
                    )
                    ctx_logger.info(execution_output, destinations=["run"])
                    
                    print(execution_output)
                except Exception as e:
                    print(f'claude code failed: {e}')
                    # raise RuntimeError(f'claude code failed: {e}')

                    ctx_logger.info("Pausing...", destinations=["run"])
                    print("Pausing...")
                    execution_res = await computer.check_shell_command("sleep 6000")

                # Grade and yield the final result
                try:
                    grade = await task.grade(computer, self.runtime_config)
                except Exception as e:
                    raise RolloutSystemError(f"Error during grading: {e}") from e

                yield FinalResult(grade=grade)
        except asyncio.TimeoutError as e:
            ctx_logger.exception("Computer startup timed out", destinations=["run"])
            raise RolloutSystemError("Computer startup timed out") from e
        except Exception as e:
            if isinstance(e, RolloutSystemError):
                ctx_logger.exception(
                    f"RolloutSystemError in {task.run_id}: {e}", destinations=["run"]
                )
                raise
            ctx_logger.exception(
                f"Unexpected error in task {task.run_id}: {e}", destinations=["run"]
            )
            raise RolloutSystemError(f"Unexpected error during rollout: {e}") from e
