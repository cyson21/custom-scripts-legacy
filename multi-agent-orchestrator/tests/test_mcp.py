import pytest
import asyncio
import json
from unittest.mock import patch, MagicMock, AsyncMock
from orchestrator.core.mcp import MCPManager, MCPClient

@pytest.mark.asyncio
async def test_mcp_client_lifecycle():
    # Mock the subprocess
    mock_process = AsyncMock()
    mock_process.stdin = MagicMock() # write is sync
    mock_process.stdin.drain = AsyncMock()
    mock_process.stdout = AsyncMock()
    
    # Mock the response for tools/list
    list_response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "tools": [
                {"name": "get_weather", "description": "Get current weather"}
            ]
        }
    }
    
    # Mock the response for tools/call
    call_response = {
        "jsonrpc": "2.0",
        "id": 2,
        "result": "Sunny and 25C"
    }
    
    mock_process.stdout.readline.side_effect = [
        json.dumps(list_response).encode() + b"\n",
        json.dumps(call_response).encode() + b"\n"
    ]
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        manager = MCPManager()
        # Reset the singleton state for testing
        manager.clients = {}
        
        await manager.add_server("test_server", ["dummy_cmd"])
        
        # Test listing tools
        tools = await manager.get_all_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "get_weather"
        assert tools[0]["mcp_server"] == "test_server"
        
        # Test calling tool
        result = await manager.call_tool("test_server", "get_weather", {"location": "Seoul"})
        assert result == "Sunny and 25C"
        
        # Ensure stdin was written to
        assert mock_process.stdin.write.call_count == 2
