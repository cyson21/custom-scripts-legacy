"""
Architectural Role: MCP Tool Execution Hooks.
This module intercepts tool execution requests aimed at MCP servers and 
delegates the execution to the MCPManager, returning the results transparently.
"""
from typing import Dict, Any

async def hook_execute_mcp_tool(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transparent Tool Augmentation for MCP Tools.
    Intercepts any tool execution request and checks if it matches an available MCP tool.
    """
    tool_name = payload.get("tool_name")
    
    # If the tool isn't already handled and a tool name is provided
    if tool_name and "output" not in payload:
        try:
            from orchestrator.core.mcp import MCPManager
            mcp_manager = MCPManager()
            
            # Find the tool in our connected servers
            tools = await mcp_manager.get_all_tools()
            target_tool = next((t for t in tools if t.get("name") == tool_name), None)
            
            if target_tool:
                server_name = target_tool.get("mcp_server")
                arguments = payload.get("arguments", {})
                
                # Execute the tool via MCP
                result = await mcp_manager.call_tool(server_name, tool_name, arguments)
                
                payload["success"] = True
                # Format the result nicely
                if isinstance(result, list) and len(result) > 0 and "text" in result[0]:
                    payload["output"] = "\n".join([item["text"] for item in result if "text" in item])
                else:
                    payload["output"] = str(result)
        except Exception as e:
            payload["success"] = False
            payload["output"] = f"MCP Execution Error: {str(e)}"
            
    return payload
