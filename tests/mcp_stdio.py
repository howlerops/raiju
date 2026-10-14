#!/usr/bin/env python3
"""A stdio MCP server for the e2e tests: one tool, `echo`, that repeats its text
with the MCP_GREETING environment variable and its own process id."""
import json, os, sys

def reply(id, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": id, "result": result}) + "\n")
    sys.stdout.flush()

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    method, id = msg.get("method"), msg.get("id")
    if id is None:
        continue  # notifications
    if method == "initialize":
        reply(id, {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "stdio-echo", "version": "1"}})
    elif method == "tools/list":
        reply(id, {"tools": [{"name": "echo", "description": "Repeats text", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}}]})
    elif method == "tools/call":
        text = msg["params"]["arguments"].get("text", "")
        reply(id, {"content": [{"type": "text", "text": f"{os.environ.get('MCP_GREETING', '')}: {text} (pid {os.getpid()})"}], "isError": False})
    else:
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": id, "error": {"code": -32601, "message": "no such method"}}) + "\n")
        sys.stdout.flush()
