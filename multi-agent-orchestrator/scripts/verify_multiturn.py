import asyncio
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append(os.getcwd())

from orchestrator.tui.controller import TUIController
from orchestrator.agents.swarm import run_swarm_logic
from orchestrator.core.models import DeploymentUnit, ExecutionMode
from orchestrator.core.history import HistoryManager
from orchestrator.core.storage import RegistryManager

async def run_multiturn_verification():
    controller = TUIController()
    hm = HistoryManager()
    
    # 1. Setup Temporary Workspace
    test_dir = Path("./temp_multiturn_test").resolve()
    test_dir.mkdir(exist_ok=True)
    test_file = test_dir / "project-info.md"
    test_file.write_text("# Project Info\n\n- Baseline: Active\n", encoding="utf-8")
    
    print(f"✅ Created test workspace: {test_dir}")
    
    controller.workspace_dir = str(test_dir)
    controller.autonomous_mode = True 
    
    # --- MISSION 1: Define Secret Information ---
    secret_code = "HYPER-FLUX-77"
    mission1_prompt = (
        f"I am defining a project secret code: '{secret_code}'. "
        "This code is used for quantum-safe encryption. "
        "Please acknowledge this and explain its importance in your response."
    )
    
    units = [DeploymentUnit(persona="architect", engine="gemini")]
    
    print(f"\n🚀 [Mission 1] Launching: Define secret code...")
    try:
        await run_swarm_logic(
            controller=controller,
            user_prompt=mission1_prompt,
            deployment_units=units,
            execution_mode=ExecutionMode.DISCUSSION,
            max_rounds=1
        )
        
        # Retrieve the trace from the latest session using Registry
        registry = RegistryManager.load_registry()
        if not registry:
            print("❌ FAILURE: Registry is empty.")
            return
            
        # Sort by timestamp desc to be safe
        registry.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        
        latest_entry = registry[0]
        artifact_dir = Path(latest_entry["artifacts_path"])
        trace_path = artifact_dir / "execution_trace.md"
        
        if not trace_path.exists():
             print(f"❌ FAILURE: Trace file not found at {trace_path}")
             return

        trace_content = trace_path.read_text(encoding="utf-8")
        
        if secret_code not in trace_content:
            print("❌ FAILURE: Mission 1 trace does not contain the secret code.")
            print(f"Trace snippet: {trace_content[:500]}")
            return

        print(f"✅ [Mission 1] Success. Trace captured (Length: {len(trace_content)}).")

        # --- MISSION 2: Follow-up (Testing Continuity) ---
        print(f"\n🚀 [Mission 2] Launching: Verify continuity (Follow-up)...")
        
        # INJECT CONTEXT (Simulating 'F' key behavior)
        # Using a very clear marker
        h_context = f"--- START PREVIOUS CONTEXT ---\n{trace_content}\n--- END PREVIOUS CONTEXT ---"
        controller.history_context = h_context
        
        mission2_prompt = (
            "Look at the text provided between 'START PREVIOUS CONTEXT' and 'END PREVIOUS CONTEXT'. "
            "What was the project secret code defined there and its purpose? "
            "Respond ONLY with: 'The code is [CODE] for [PURPOSE]'. Do not use any tools."
        )

        print(f"DEBUG: history_context length: {len(h_context)}")
        
        await run_swarm_logic(
            controller=controller,
            user_prompt=mission2_prompt,
            deployment_units=units,
            execution_mode=ExecutionMode.DISCUSSION,
            max_rounds=1,
            history_context=h_context
        )
        
        # Check output from newest trace
        registry2 = RegistryManager.load_registry()
        registry2.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        artifact_dir2 = Path(registry2[0]["artifacts_path"])
        trace_path2 = artifact_dir2 / "execution_trace.md"
        m2_trace = trace_path2.read_text(encoding="utf-8")
        
        print("\n--- Mission 2 Trace Snippet ---")
        print(m2_trace[:1000]) 
        print("-------------------------------")
        
        if secret_code in m2_trace and "encryption" in m2_trace.lower():
            print(f"\n🎉 RIGOROUS SUCCESS: The agent remembered '{secret_code}' from the injected Trace!")
        else:
            print("\n❌ FAILURE: Agent lost context.")
            
    except Exception as e:
        print(f"\n💥 CRASH: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        if test_file.exists():
            test_file.unlink()
        if test_dir.exists():
            # Cleanup artifact dirs inside test_dir if any
            import shutil
            shutil.rmtree(test_dir)
        print("\n🧹 Cleanup complete.")

if __name__ == "__main__":
    asyncio.run(run_multiturn_verification())
