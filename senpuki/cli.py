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

async def dlq_list(executor: Senpuki, args):
    records = await executor.list_dead_letters(limit=args.limit)
    if not records:
        print("Dead-letter queue is empty.")
        return
    print(f"{'Task ID':<36} | {'Execution':<36} | {'Step':<20} | {'Reason'}")
    print("-" * 120)
    for record in records:
        task = record.task
        reason = (record.reason or "")[:40]
        print(f"{task.id:<36} | {task.execution_id:<36} | {task.step_name:<20} | {reason}")

async def dlq_show(executor: Senpuki, args):
    record = await executor.get_dead_letter(args.id)
    if not record:
        print(f"Dead-letter task {args.id} not found.")
        return
    task = record.task
    print(f"Task ID: {task.id}")
    print(f"Execution ID: {task.execution_id}")
    print(f"Step: {task.step_name} ({task.kind})")
    print(f"Queue: {task.queue or 'default'}")
    print(f"Reason: {record.reason}")
    print(f"Moved At: {record.moved_at.isoformat()}")
    print(f"Retries: {task.retries}")
    print(f"Tags: {', '.join(task.tags) if task.tags else '-'}")

async def dlq_replay(executor: Senpuki, args):
    new_id = await executor.replay_dead_letter(args.id, queue=args.queue)
    print(f"Requeued dead-letter task {args.id} as {new_id}.")

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

    dlq_parser = subparsers.add_parser("dlq", help="Dead-letter queue operations")
    dlq_sub = dlq_parser.add_subparsers(dest="dlq_command", required=True)
    dlq_list_parser = dlq_sub.add_parser("list", help="List DLQ entries")
    dlq_list_parser.add_argument("--limit", type=int, default=20, help="Number of DLQ items to display")
    dlq_show_parser = dlq_sub.add_parser("show", help="Show DLQ entry details")
    dlq_show_parser.add_argument("id", help="Dead-letter task ID")
    dlq_replay_parser = dlq_sub.add_parser("replay", help="Replay a DLQ entry")
    dlq_replay_parser.add_argument("id", help="Dead-letter task ID")
    dlq_replay_parser.add_argument("--queue", help="Override queue when replaying")

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
    elif args.command == "dlq":
        if args.dlq_command == "list":
            await dlq_list(executor, args)
        elif args.dlq_command == "show":
            await dlq_show(executor, args)
        elif args.dlq_command == "replay":
            await dlq_replay(executor, args)

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
