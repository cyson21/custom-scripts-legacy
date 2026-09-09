from ai_tool import GeminiProvider, ClaudeProvider
import os, glob

print("Gemini move_copy_session:")
gemini = GeminiProvider()
sessions = gemini.load_sessions(False)
if sessions:
    s = sessions[0]
    print(f"Original: {s.session_id} in {s.cwd} (Workspace: {s.workspace_name})")
    # try to move it
    dest = "$HOME/customScripts"
    print(f"Moving to {dest}")
    # We will copy it to test
    gemini.move_copy_session(s, dest, move=False)
    sessions2 = gemini.load_sessions(False)
    for s2 in sessions2:
        if s2.session_id == s.session_id:
            print(f"Found: {s2.session_id} in {s2.cwd} (Workspace: {s2.workspace_name})")
else:
    print("No Gemini sessions found.")

print("Claude move_copy_session:")
claude = ClaudeProvider()
csessions = claude.load_sessions(False)
if csessions:
    cs = csessions[0]
    print(f"Original: {cs.session_id} in {cs.cwd} (Workspace: {cs.workspace_name})")
    dest = "$HOME/customScripts"
    print(f"Moving to {dest}")
    claude.move_copy_session(cs, dest, move=False)
    csessions2 = claude.load_sessions(False)
    for cs2 in csessions2:
        if cs2.session_id == cs.session_id:
            print(f"Found: {cs2.session_id} in {cs2.cwd} (Workspace: {cs2.workspace_name})")
else:
    print("No Claude sessions found.")
