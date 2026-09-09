
import asyncio
import pytest
from pathlib import Path
from orchestrator.core.state import OrchestratorState
from orchestrator.agents.swarm import run_swarm_logic
from orchestrator.core.models import DeploymentUnit

@pytest.mark.asyncio
async def test_autonomous_flow():
    print("--- Starting Autonomous Workflow Test ---")
    controller = OrchestratorState()
    controller.autonomous_mode = True # Force autonomous mode
    controller.workspace_dir = str(Path.cwd())
    
    # Define a simple test mission
    user_prompt = "Say hello and confirm system readiness."
    units = [DeploymentUnit(persona="engineer", engine="gemini")]
    
    print(f"Mission: {user_prompt}")
    print(f"Agents: {[u.persona for u in units]}")
    
    try:
        # Run the actual swarm logic
        await run_swarm_logic(
            controller=controller,
            user_prompt=user_prompt,
            deployment_units=units,
            max_rounds=1 # One round is enough for test
        )
        print("\n--- Autonomous Workflow Completed Successfully ---")
    except Exception as e:
        print(f"\n--- Autonomous Workflow FAILED: {e} ---")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_autonomous_flow())
