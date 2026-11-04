"""Local operator CLI for the complete personal research MCP product.

Arguments select existing tools; they never supply execution authorization.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, cast

from quantos.application.personal_server_config import load_server_config, make_trusted_service
from quantos.personal_research_mcp import create_server


async def invoke(config_path: Path, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    config = load_server_config(config_path)
    core = make_trusted_service(config.product_root, config.repo_root, config_path)
    server = create_server(config.product_root, config.repo_root, research_service=core)
    tools = {entry.name for entry in await server.list_tools()}
    if tool not in tools:
        raise ValueError("unknown product tool")
    result: Any = await server.call_tool(tool, arguments)
    # FastMCP returns content and structured output; retain the complete tool result.
    if isinstance(result, tuple):
        return {"structured_content": result[1]}
    return {"content": [entry.model_dump(mode="json") for entry in result]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", help="Actual MCP tool name, e.g. research_strategy_capabilities")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument(
        "--arguments", type=Path, help="Local JSON object; authorization remains operator-owned"
    )
    args = parser.parse_args()
    arguments: Any = json.loads(args.arguments.read_bytes()) if args.arguments else {}
    if not isinstance(arguments, dict):
        parser.error("arguments must be a JSON object")
    print(
        json.dumps(
            asyncio.run(invoke(args.config.absolute(), args.tool, cast(dict[str, Any], arguments))),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
