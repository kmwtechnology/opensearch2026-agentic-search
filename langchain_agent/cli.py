"""Interactive terminal REPL for EcommerceSearchAgent (split out of main.py in #47).

Developer entry point only -- the deployed service runs `uvicorn api.main:app`
and never imports this module. Run with `make run` / `PYTHONPATH=. python main.py`.
"""

import sys
from typing import List, Sequence

import httpx
from langchain_core.messages import BaseMessage, HumanMessage

from config import DEFAULT_ALPHA, SEARCH_DEFAULTS, VECTOR_COLLECTION_NAME
from main import EcommerceSearchAgent


def run_conversation(agent):
    """Run the interactive conversation loop"""
    print("=" * 70)
    print("E-Commerce Search Agent - Product Knowledge Base & Memory")
    print("=" * 70)
    print()
    print("Agent is ready! You can search for:")
    print("  - Products by brand or type")
    print("  - Products by color or attributes")
    print("  - Product comparisons and details")
    print()
    print("Commands:")
    print("  - Type your question and press Enter")
    print("  - Type 'new' to start a new conversation")
    print("  - Type 'list' to see previous conversations")
    print("  - Type 'load <id>' to resume a conversation")
    print("  - Type 'clear' to delete all conversations")
    print("  - Type 'quit' or 'exit' to stop")
    print()
    print("=" * 70)
    print()

    agent.generate_thread_id()
    print(f"Conversation ID: {agent.thread_id}")
    print("(Title will be updated after each message)")
    print()

    while True:
        try:
            # Get user input
            user_input = input("You: ").strip()

            if not user_input:
                continue

            # Handle special commands
            if user_input.lower() == "quit" or user_input.lower() == "exit":
                print("\nGoodbye!")
                break

            if user_input.lower() == "new":
                agent.generate_thread_id()
                print(f"\n✓ New conversation started")
                print(f"Conversation ID: {agent.thread_id}")
                print()
                continue

            if user_input.lower() == "list":
                print("\n📋 Previous Conversations:")
                conversations = agent.list_conversations()
                if conversations:
                    for i, (thread_id, title, created_at) in enumerate(conversations, 1):
                        # Format the date nicely
                        date_str = (
                            created_at.strftime("%Y-%m-%d %H:%M") if created_at else "Unknown"
                        )
                        print(f"  {i}. {title}")
                        print(f"     ID: {thread_id} | {date_str}")
                    print("\nUse 'load <id>' to resume a conversation")
                else:
                    print("  No previous conversations found")
                print()
                continue

            if user_input.lower().startswith("load "):
                thread_id = user_input[5:].strip()
                if thread_id:
                    agent.set_thread_id(thread_id)
                    print(f"\n✓ Loaded conversation: {thread_id}")
                    print()
                else:
                    print("\n✗ Please provide a conversation ID: load <id>")
                    print()
                continue

            if user_input.lower() == "clear":
                # Confirm before clearing
                confirm = (
                    input(
                        "\n⚠️  This will delete ALL conversations and history. Continue? (yes/no): "
                    )
                    .strip()
                    .lower()
                )
                if confirm == "yes":
                    metadata_count, checkpoint_count = agent.clear_all_conversations()
                    print(
                        f"\n✓ Cleared {metadata_count} conversation(s) and {checkpoint_count} checkpoint record(s)"
                    )
                else:
                    print("✗ Clear cancelled")
                print()
                continue

            # Process the input through the agent
            print()
            _invoke_agent(agent, user_input)
            print()

        except KeyboardInterrupt:
            print("\n\nInterrupted. Goodbye!")
            break
        except Exception as e:
            print(f"\n✗ Error: {e}")
            print("Try again or type 'quit' to exit\n")


def _invoke_agent(agent, user_input: str):
    """
    Invoke the agent with user input and stream intermediate reasoning steps.

    This method uses modern LangGraph streaming to show:
    1. Agent reasoning and decision-making steps
    2. Tool calls to the knowledge base with intermediate results
    3. Final response streamed character-by-character for real-time feedback

    Args:
        user_input: The user's question or command
    """
    try:
        # Prepare input for the agent with new state schema
        input_data = {
            "messages": [],
            "alpha": SEARCH_DEFAULTS.get(VECTOR_COLLECTION_NAME, {}).get(
                "alpha", DEFAULT_ALPHA
            ),  # Collection-aware default
            "query_analysis": "",
            "intent": "question",
            "summary_text": None,
        }

        # Try to apply compaction to conversation if needed
        compacted_messages: List[BaseMessage] = []
        current_messages: Sequence[BaseMessage] = []
        try:
            checkpoint_state = agent.checkpointer.get(
                {"configurable": {"thread_id": agent.thread_id}}
            )
            if checkpoint_state and "messages" in checkpoint_state:
                current_messages = checkpoint_state["messages"]
                compacted_msgs, was_compacted, num_compacted = agent.compact_conversation_if_needed(
                    current_messages
                )
                compacted_messages = list(compacted_msgs)
                if was_compacted:
                    print(f"[🗜️  Compacted {num_compacted} older messages to maintain context]")
        except Exception:
            # If compaction fails, just continue without it
            compacted_messages = []

        if not compacted_messages:
            compacted_messages = list(current_messages) if current_messages else []

        # Include compaction summary + history before the new user message
        history_messages = compacted_messages + [HumanMessage(content=user_input)]
        input_data["messages"] = history_messages

        final_response = ""

        # Get the current message count before invoking
        try:
            checkpoint_before = agent.checkpointer.get(
                {"configurable": {"thread_id": agent.thread_id}}
            )
            messages_before_count = (
                len(checkpoint_before.get("messages", [])) if checkpoint_before else 0
            )
        except Exception:
            messages_before_count = 0

        # Invoke the agent to get the complete response
        result = agent.app.invoke(
            input_data,
            config={"configurable": {"thread_id": agent.thread_id}},
        )

        # Log query analysis for debugging (optional)
        if "query_analysis" in result and result["query_analysis"]:
            print(f"[Debug] Query Analysis: {result['query_analysis']}")
        if "alpha" in result:
            print(f"[Debug] Lambda used: {result.get('alpha', 'N/A'):.2f}")

        # Extract final response and reasoning from result
        if "messages" in result:
            messages = result["messages"]
            # Only look at messages added in this turn (after the user message)
            # We need to find the assistant message that came after the last user input
            new_messages = (
                messages[messages_before_count:] if messages_before_count < len(messages) else []
            )

            # Find the last assistant message in the new messages (final response)
            for msg in reversed(new_messages):
                if hasattr(msg, "content") and msg.content:
                    content = str(msg.content)
                    # Skip messages that are tool calls
                    if not (hasattr(msg, "tool_calls") and msg.tool_calls):
                        final_response = content
                        break

        # Display the final response with streaming
        if final_response:
            print("Agent (response):")
            _stream_text(agent, final_response)
        else:
            print("Agent: Processing complete")

        # Update conversation title after each turn
        agent.update_conversation_title()

    except httpx.ConnectError as e:
        print(f"✗ Cannot connect to Google AI API")
        print(f"  Error: {e}")
        print(f"\n  To fix:")
        print(f"  1. Check that GOOGLE_API_KEY is set correctly")
        print(f"  2. Verify internet connectivity")
    except Exception as e:
        print(f"✗ Error invoking agent: {e}")
        import traceback

        traceback.print_exc()


def _stream_text(agent, text: str, chunk_size: int = 1) -> None:
    """
    Display text output from LLM response without artificial delays.

    Previously used character-by-character delays for simulated streaming.
    Now displays text immediately as it's received from true LLM streaming.

    Args:
        text: The text to display to the console.
        chunk_size: Not used in current implementation (kept for compatibility).
    """
    # Display text immediately without artificial delays
    # True streaming happens via _stream_llm_response and LLM chunk events
    print(text)
    print()  # Final newline


def run(agent):
    """Main entry point for the agent"""
    try:
        agent.verify_prerequisites()
        agent.initialize_components()
        agent.create_agent_graph()
        run_conversation(agent)
    except KeyboardInterrupt:
        print("\n\nShutdown requested.")
    except Exception as e:
        print(f"\n✗ Fatal error: {e}")
        sys.exit(1)
    finally:
        agent.cleanup()


def main():
    """CLI entry point."""
    agent = EcommerceSearchAgent()
    run(agent)


if __name__ == "__main__":
    main()
