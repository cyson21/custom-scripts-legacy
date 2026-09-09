import asyncio
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append(os.getcwd())

from orchestrator.tui.controller import TUIController
from orchestrator.agents.swarm import run_swarm_logic
from orchestrator.core.models import DeploymentUnit, ExecutionMode

async def run_sanity_test():
    controller = TUIController()
    
    # 1. Setup Temporary Workspace
    test_dir = Path("./temp_sanity_test").resolve()
    test_dir.mkdir(exist_ok=True)
    test_file = test_dir / "sanity-log.md"
    test_file.write_text("# Sanity Test Log\n\n- Status: Initial\n", encoding="utf-8")
    
    print(f"✅ Created test workspace: {test_dir}")
    
    controller.workspace_dir = str(test_dir)
    controller.autonomous_mode = True  # Don't wait for UI approval
    
    # 2. Define Mission
    user_prompt = (
        "Read sanity-log.md and discuss how to improve it. "
        "Then, add a new section '## Discussion Result' at the end with a summary. "
        "Keep it very brief (one sentence). Mention 'Verified by Swarm'."
    )
    
    # 3. Select Agents (1 Architect + 3 Reviewers)
    units = [
        DeploymentUnit(persona="architect", engine="gemini"),
        DeploymentUnit(persona="reviewer", engine="gemini"),
        DeploymentUnit(persona="reviewer", engine="gemini"),
        DeploymentUnit(persona="reviewer", engine="gemini")
    ]
    
    print(f"🚀 Launching Sanity Mission (Mode: DISCUSSION)...")
    
    try:
        await run_swarm_logic(
            controller=controller,
            user_prompt=user_prompt,
            deployment_units=units,
            execution_mode=ExecutionMode.DISCUSSION,
            max_rounds=1
        )
        
        # 4. Verify Result
        if test_file.exists():
            updated_content = test_file.read_text(encoding="utf-8")
            print("\n--- Updated File Content ---")
            print(updated_content)
            print("----------------------------")
            
            if "Discussion Result" in updated_content or "Verified by Swarm" in updated_content:
                print("\n🎉 SUCCESS: Workflow is fully functional!")
            else:
                print("\n❌ FAILURE: File was not updated as expected.")
        else:
             print("\n❌ FAILURE: Test file disappeared.")
            
    except Exception as e:
        print(f"\n💥 CRASH: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        try:
            if test_file.exists():
                test_file.unlink()
            if test_dir.exists():
                test_dir.rmdir()
            print("🧹 Cleanup complete.")
        except Exception:
            pass

if __name__ == "__main__":
    asyncio.run(run_sanity_test())
