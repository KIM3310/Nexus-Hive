"""CLI interface for Nexus-Hive Agent Framework.

Usage:
    python -m cli.main ask "Show me total revenue by region"
    python -m cli.main agents
    python -m cli.main tools
    python -m cli.main memory --stats
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import traceback

from framework.memory import MemoryManager
from framework.tools import ToolRegistry
from framework.orchestrator import Orchestrator, OrchestrationError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nexus-hive",
        description="Nexus-Hive Agent Framework CLI",
    )
    sub = parser.add_subparsers(dest="command")

    ask_p = sub.add_parser("ask", help="Send a question to the agent pipeline")
    ask_p.add_argument("question", type=str, help="Natural language question")
    ask_p.add_argument("--mode", choices=["sequential", "parallel", "router"], default="sequential")
    ask_p.add_argument("--max-steps", type=int, default=10)

    sub.add_parser("agents", help="List registered agents")
    sub.add_parser("tools", help="List registered tools and metrics")

    mem_p = sub.add_parser("memory", help="Inspect memory state")
    mem_p.add_argument("--stats", action="store_true", help="Show memory statistics")
    mem_p.add_argument("--search", type=str, help="Search long-term memory by prefix")
    mem_p.add_argument("--clear", type=str, help="Clear short-term memory for a request_id")
    mem_p.add_argument("--cleanup", action="store_true", help="Remove expired entries")

    return parser


def cmd_agents(orchestrator: Orchestrator) -> None:
    agents = orchestrator.list_agents()
    if not agents:
        print("No agents registered.")
        return
    print(f"Registered agents ({len(agents)}):")
    for name in agents:
        agent = orchestrator._agents[name]
        print(f"  - {name} (status={agent.status.value}, tools={len(agent.tools.list_tools())})")


def cmd_tools(orchestrator: Orchestrator) -> None:
    has_tools = False
    for agent in orchestrator._agents.values():
        tools = agent.tools.list_tools()
        if tools:
            has_tools = True
            print(f"\n  [{agent.name}]")
            for tool in tools:
                print(f"    - {tool.name}: {tool.description[:60]}")
                if tool.call_count > 0:
                    print(f"      calls={tool.call_count}, avg={tool.avg_duration_ms:.1f}ms")

    if not has_tools:
        print("No tools registered.")


def cmd_memory(memory: MemoryManager, args: argparse.Namespace) -> None:
    if args.cleanup:
        removed = memory.cleanup_expired()
        print(f"Removed {removed} expired entries.")
    elif args.search:
        results = memory.search_long_term(args.search)
        if not results:
            print(f"No memories matching prefix '{args.search}'")
        else:
            for k, v in results.items():
                print(f"  {k}: {json.dumps(v, default=str)[:100]}")
    elif args.clear:
        memory.clear_request(args.clear)
        print(f"Cleared memory for request '{args.clear}'")
    else:
        stats = memory.stats()
        print(json.dumps(stats, indent=2))


async def cmd_ask(orchestrator: Orchestrator, args: argparse.Namespace) -> None:
    if not orchestrator.list_agents():
        print("No agents registered. Start the API server or register agents programmatically.")
        return

    print(f"Question: {args.question}")
    print(f"Mode: {args.mode}")
    print("---")

    if args.mode == "sequential":
        result = await orchestrator.run_sequential(args.question)
    elif args.mode == "parallel":
        result = await orchestrator.run_parallel(args.question)
    else:
        result = await orchestrator.run_routed(args.question)

    print(f"\nExecution: {' -> '.join(result.execution_order)}")
    print(f"Steps: {result.total_steps} | Elapsed: {result.elapsed_ms:.0f}ms")
    print(f"\nOutputs:")
    for agent_name, output in result.outputs.items():
        print(f"  [{agent_name}]: {json.dumps(output, default=str, ensure_ascii=False)[:200]}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    memory = MemoryManager()
    orchestrator = Orchestrator(memory=memory)

    try:
        if args.command == "agents":
            cmd_agents(orchestrator)
        elif args.command == "tools":
            cmd_tools(orchestrator)
        elif args.command == "memory":
            cmd_memory(memory, args)
        elif args.command == "ask":
            asyncio.run(cmd_ask(orchestrator, args))
    except OrchestrationError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
