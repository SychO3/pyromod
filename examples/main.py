import sys
from pathlib import Path

import uvloop

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Install uvloop before importing pyromod/pyrogram so they bind to the
# correct event loop policy from the start.
uvloop.install()

from pyromod import Client
from pyrogram import filters, types

bot = Client("my_bot")

@bot.on_message(group=999)
async def handler(client:Client, message:types.Message):
    print(message)

@bot.on_message(filters.command("ask"))
async def ask(client:Client, message:types.Message):
    name = await client.ask(message.chat.id, "What is your name?")
    age = await client.ask(message.chat.id, "What is your age?")
    await message.reply_text(f"Hello {name.text}! You are {age.text} years old.")

# response = await client.listen(chat_id=chat_id)
@bot.on_message(filters.command("listen"))
async def listen(client:Client, message:types.Message):
    response = await client.listen(chat_id=message.chat.id)
    await message.reply_text(f"You said: {response.text}")

bot.run()