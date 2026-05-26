import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.alexis import AlexisAgent
from gateway.telegram.presence import PresenceLoop


class FakeBot:
    def __init__(self):
        self.calls = []

    async def send_chat_action(self, *, chat_id, action):
        self.calls.append(
            {
                "chat_id": chat_id,
                "action": action,
            }
        )


async def check_presence_loop_uses_bot():
    bot = FakeBot()
    presence = PresenceLoop(
        bot=bot,
        chat_id=123,
    )

    await presence.start()
    await asyncio.sleep(0.01)
    await presence.stop()

    assert bot.calls
    assert bot.calls[0]["chat_id"] == 123


def check_alexis_guest_context_binding():
    agent = AlexisAgent()

    assert hasattr(agent, "search_guests")
    assert hasattr(agent, "build_guest_context")

    context = agent.build_guest_context(
        guests=[
            {
                "NAME": "Jane Doe",
                "TITLE/EXPERTISE": "AI policy expert",
            }
        ]
    )

    assert context
    assert "Jane Doe" in context[0]


def main():
    asyncio.run(check_presence_loop_uses_bot())
    check_alexis_guest_context_binding()
    print("PASS latent runtime bug checks")


if __name__ == "__main__":
    main()
