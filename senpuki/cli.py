import argparse
import asyncio
import os
import sys
from datetime import datetime

from senpuki import Senpuki, ExecutionState

async def list_executions(executor: Senpuki, args):
    executions = await executor.list_executions(limit=args.limit, state=args.state)
    if not executions:
        print("No executions found.")
        return

    print(f"{'ID':<36} | {'State':<10} | {'Started At':<26}")
    print("-" * 80)
    for exc in executions:
        started = exc.started_at.isoformat() if exc.started_at else "Pending"
        print(f"{exc.id:<36} | {exc.state:<10} | {started:<26}")

async def show_execution(executor: Senpuki, args):
    try:
        state = await executor.state_of(args.id)
    except ValueError:
        print(f"Execution {args.id} not found.")
        return

    print(f"ID: {state.id}")
    print(f"State: {state.state}")
    
    if state.started_at:
        print(f"Started At: {state.started_at}")
    if state.completed_at:
        print(f"Completed At: {state.completed_at}")
    
    print("\nProgress:")
    for p in state.progress:
        timestamp = p.completed_at or p.started_at
        ts_str = timestamp.strftime("%H:%M:%S") if timestamp else "??:??:??"
        if p.status == "completed":
            status_icon = "+"
        elif p.status == "failed":
            status_icon = "x"
        else:
            status_icon = ">"
        
        print(f"[{ts_str}] {status_icon} {p.step} ({p.status})")
        if p.detail:
            print(f"    Detail: {p.detail}")
    
    if state.result is not None:
        print(f"\nResult: {state.result}")

async def main_async():
    parser = argparse.ArgumentParser(description="Senpuki CLI")
    default_db = os.environ.get("SENPUKI_DB", "senpuki.sqlite")
    parser.add_argument("--db", default=default_db, help=f"Path to SQLite DB or Postgres DSN (default: {default_db}, env: SENPUKI_DB)")
    
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    list_parser = subparsers.add_parser("list", help="List executions")
    list_parser.add_argument("--limit", type=int, default=10, help="Number of executions to show")
    list_parser.add_argument("--state", type=str, help="Filter by state (e.g. pending, running, completed, failed)")
    
    show_parser = subparsers.add_parser("show", help="Show execution details")
    show_parser.add_argument("id", help="Execution ID")

    args = parser.parse_args()

    # Determine backend
    if "://" in args.db or "postgres" in args.db:
         backend = Senpuki.backends.PostgresBackend(args.db)
    else:
         backend = Senpuki.backends.SQLiteBackend(args.db)
    
    executor = Senpuki(backend=backend)
    
    if args.command == "list":
        await list_executions(executor, args)
    elif args.command == "show":
        await show_execution(executor, args)

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
