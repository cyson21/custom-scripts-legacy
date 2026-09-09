import os
import re

mappings = {
    "orchestrator.context": "orchestrator.core.context",
    "orchestrator.models": "orchestrator.core.models",
    "orchestrator.storage": "orchestrator.core.storage",
    "orchestrator.history": "orchestrator.core.history",
    "orchestrator.hooks": "orchestrator.core.hooks",
    "orchestrator.prompts": "orchestrator.core.prompts",
    "orchestrator.reporting": "orchestrator.core.reporting",
    "orchestrator.path_resolver": "orchestrator.core.path_resolver",
    "orchestrator.sisyphus": "orchestrator.agents.sisyphus",
    "orchestrator.io_provider": "orchestrator.agents.io_provider",
    "orchestrator.manual_io": "orchestrator.agents.manual_io",
    "orchestrator.ast_grep": "orchestrator.tools.ast_grep",
    "orchestrator.diffing": "orchestrator.tools.diffing",
    "orchestrator.hashline": "orchestrator.tools.hashline",
    "orchestrator.merger": "orchestrator.tools.merger",
    "orchestrator.sandbox": "orchestrator.tools.sandbox",
    "orchestrator.workflow": "orchestrator.agents.swarm",
}

# Sort mappings by length of key (descending) to ensure longer paths are replaced first
sorted_mappings = sorted(mappings.items(), key=lambda x: len(x[0]), reverse=True)

def fix_imports(file_path):
    with open(file_path, 'r') as f:
        content = f.read()
    
    new_content = content
    for old, new in sorted_mappings:
        # Match old string only if it's not already preceded by the new structure parts 
        # (e.g., don't replace orchestrator.context in orchestrator.core.context)
        # We use word boundaries \b to be safe.
        
        # Regex to match: 
        # 1. 'from orchestrator.X import'
        # 2. 'import orchestrator.X'
        # 3. 'orchestrator.X.'
        # 4. 'orchestrator.X' as a full symbol
        
        # Simple string replacement might be enough if we are careful.
        # But let's use regex to avoid partial matches.
        
        # We want to match 'orchestrator.X' but not 'orchestrator.core.X' (if X is 'context')
        # Actually, if we use sorted_mappings and they are unique, it should be fine.
        # But wait, 'orchestrator.context' is a prefix of 'orchestrator.context_extra' (if it existed)
        # So \b is good.
        
        pattern = r'\b' + re.escape(old) + r'\b'
        new_content = re.sub(pattern, new, new_content)
    
    if new_content != content:
        with open(file_path, 'w') as f:
            f.write(new_content)
        return True
    return False

def main():
    modified_count = 0
    for root, dirs, files in os.walk('orchestrator'):
        for file in files:
            if file.endswith('.py'):
                path = os.path.join(root, file)
                if fix_imports(path):
                    print(f"Fixed imports in: {path}")
                    modified_count += 1
    
    # Also fix in main.py and test_headless.py in root
    for file in ['main.py', 'test_headless.py', 'validate_todo.py']:
        if os.path.exists(file):
            if fix_imports(file):
                print(f"Fixed imports in: {file}")
                modified_count += 1
                
    print(f"Total files modified: {modified_count}")

if __name__ == "__main__":
    main()
