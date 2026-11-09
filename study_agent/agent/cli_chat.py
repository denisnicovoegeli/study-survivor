"""Chat in der Kommandozeile: `study ask FRAGE` oder ohne Frage interaktiv."""
import json


def _print(state: dict, as_json: bool) -> None:
    r = state.get("response") or {}
    if as_json:
        print(json.dumps({"category": state.get("category"), "in_scope": state.get("in_scope"),
                          "tools_used": state.get("tools_used"), **r}, ensure_ascii=False, indent=2))
        return
    print(f"[{state.get('category')} · zuständig: {state.get('in_scope')} · Tools: {', '.join(state.get('tools_used') or []) or '-'}]")
    print(r.get("answer", ""))
    if r.get("quellen"):
        print("\nQuellen:\n" + "\n".join(f"- {q}" for q in r["quellen"]))


async def run_ask(args) -> int:
    from study_agent.agent.chat import make_chat_graph
    from study_agent.agent.memory import Context, open_memory

    async with open_memory() as (saver, store):
        graph = await make_chat_graph(checkpointer=saver, store=store)
        config = {"configurable": {"thread_id": args.thread}}
        context = Context(user_id=args.user)
        fragen = [" ".join(args.frage)] if args.frage else None
        while True:
            frage = fragen.pop(0) if fragen else (None if fragen is not None else input("\nDu: ").strip())
            if not frage:
                return 0
            state = await graph.ainvoke({"messages": [("user", frage)]}, config, context=context)
            _print(state, args.json)
            if fragen is not None and not fragen:
                return 0
