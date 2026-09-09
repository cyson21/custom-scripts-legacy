"""
Architectural Role: Model Context Protocol (MCP) Integration.
This module implements a lightweight client for interacting with MCP servers.
It allows the orchestrator to dynamically discover and invoke external tools
provided by the ecosystem, expanding the agents' capabilities without 
hardcoding specific tool logic.
"""
import json
import asyncio
import subprocess
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("mcp")

class MCPClient:
    """
    Function: Client for stdio-based MCP servers.
    Why: MCP is the emerging standard for AI tool interoperability. By supporting 
    it, we allow our agents to use hundreds of existing tools (web search, 
    browsers, DBs) with zero custom code.
    """
    def __init__(self, server_name: str, command: List[str], env: Optional[Dict[str, str]] = None):
        self.server_name = server_name
        self.command = command
        self.env = env
        self.process: Optional[asyncio.subprocess.Process] = None
        self._id_counter = 0

    async def connect(self):
        """Spawns the MCP server process."""
        import os
        spawn_env = os.environ.copy()
        if self.env:
            spawn_env.update(self.env)
            
        self.process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=spawn_env
        )
        logger.info(f"Connected to MCP server: {self.server_name}")

    async def _send_request(self, method: str, params: Dict[str, Any]) -> Any:
        if not self.process or not self.process.stdin:
            raise RuntimeError("Not connected to MCP server")
            
        self._id_counter += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._id_counter,
            "method": method,
            "params": params
        }
        
        line = json.dumps(request) + "\n"
        self.process.stdin.write(line.encode())
        await self.process.stdin.drain()
        
        # Read one line from stdout
        response_line = await self.process.stdout.readline()
        if not response_line:
            raise EOFError("MCP server closed connection")
            
        response = json.loads(response_line.decode())
        if "error" in response:
            raise Exception(f"MCP Error: {response['error']}")
            
        return response.get("result")

    async def list_tools(self) -> List[Dict[str, Any]]:
        """Discover tools available on this server."""
        result = await self._send_request("tools/list", {})
        return result.get("tools", [])

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Invoke a tool on the server."""
        return await self._send_request("tools/call", {
            "name": name,
            "arguments": arguments
        })

    async def disconnect(self):
        if self.process:
            self.process.terminate()
            await self.process.wait()
            self.process = None

class MCPManager:
    """
    Function: Orchestrates multiple MCP connections.
    Why: A mission might require tools from different servers (e.g., one for 
    PostgreSQL, one for Google Search). MCPManager provides a unified 
    registry for all active server connections.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MCPManager, cls).__new__(cls)
            cls._instance.clients = {}
        return cls._instance

    async def add_server(self, name: str, command: List[str], env: Optional[Dict[str, str]] = None):
        client = MCPClient(name, command, env)
        await client.connect()
        self.clients[name] = client

    async def get_all_tools(self) -> List[Dict[str, Any]]:
        all_tools = []
        for name, client in self.clients.items():
            tools = await client.list_tools()
            for t in tools:
                t["mcp_server"] = name
                all_tools.append(t)
        return all_tools

    async def call_tool(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Any:
        client = self.clients.get(server_name)
        if not client:
            raise ValueError(f"MCP Server not found: {server_name}")
        return await client.call_tool(tool_name, arguments)

    async def get_tools_prompt(self) -> str:
        """Generates a markdown instruction block explaining available MCP tools."""
        tools = await self.get_all_tools()
        if not tools:
            return ""
            
        prompt = "\n[Available External Tools (MCP)]\n"
        prompt += "You have access to the following external tools. To use them, respond with ONLY a JSON block in the following format:\n"
        prompt += "```json\n{\"tool_name\": \"<tool_name>\", \"arguments\": {<kwargs>}}\n```\n\n"
        
        for t in tools:
            name = t.get("name", "unknown")
            desc = t.get("description", "No description")
            schema = t.get("inputSchema", {})
            prompt += f"- Tool: `{name}`\n  Description: {desc}\n  Arguments Schema: {json.dumps(schema)}\n"
            
        return prompt + "\n"
