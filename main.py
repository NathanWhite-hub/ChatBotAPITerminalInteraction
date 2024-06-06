import asyncio
import io
import json
import logging
import time
import tracemalloc
from configparser import ConfigParser

import requests
import websockets
from pydub import AudioSegment


class Chat:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.waiting_for_chat_reply = asyncio.Event()
        self.chat_started_event = asyncio.Event()


def set_chat_waiting_event(chat: Chat) -> None:
    chat.waiting_for_chat_reply.set()


def clear_chat_waiting_event(chat: Chat) -> None:
    chat.waiting_for_chat_reply.clear()


def configure_logging() -> tuple[logging.Logger, logging.Logger]:

    config = ConfigParser()
    config.read("config.ini")
    general_logger = logging.getLogger("my_logger")
    general_logger.setLevel(
        logging.DEBUG if config["debug_logging"] is True else logging.INFO
    )
    file_handler = logging.FileHandler("app.log")
    file_handler.setLevel(
        logging.DEBUG if config["debug_logging"] is True else logging.INFO
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    general_logger.addHandler(file_handler)

    websocket_logger = logging.getLogger("websockets")
    websocket_logger.setLevel(
        logging.DEBUG if config["debug_logging"] is True else logging.INFO
    )
    websocket_logger.addHandler(logging.StreamHandler())

    return general_logger, websocket_logger


logger, ws_logger = configure_logging()


tracemalloc.start()

message_semaphore = asyncio.Semaphore(1)


VOXTA_SERVER = "http://127.0.0.1:5384"
HUB_URL = "ws://127.0.0.1:5384/hub"
AUDIO_STREAM_URL = "ws://127.0.0.1:5384/ws/audio/input/stream"

character_dict = {}


async def send_with_separator(
    hub_ws: websockets.WebSocketClientProtocol, payload: dict
) -> None:
    await hub_ws.send(str(json.dumps(payload).strip('"') + "\u001E").replace("\\", ""))


def get_all_characters() -> None:
    # Make a POST request to the /api/chats endpoint
    response = requests.get(f"{VOXTA_SERVER}/api/characters", timeout=5)
    response.raise_for_status()  # This will raise an exception for HTTP error responses
    characters_list = response.json()["characters"]
    for character in characters_list:
        character_dict.update({character["id"]: character["name"]})


# Function to get the chat ID for "Skyrim""
def get_skyrim_chat_id() -> str:
    # Define the JSON request body
    json_body = {
        "characters": ["6227dc38-f656-413f-bba8-773380bad9d9"],
        "roles": {"main": "6227dc38-f656-413f-bba8-773380bad9d9"},
        "scenario": "a146eafe-0560-5f0f-aaed-3107e62f8c9b",
        "client": "Voxta.Talk",
    }

    # Make a POST request to the /api/chats endpoint
    response = requests.post(f"{VOXTA_SERVER}/api/chats", json=json_body, timeout=5)
    response.raise_for_status()  # This will raise an exception for HTTP error responses
    chat_id = response.json()["id"]

    # Write the chat ID to a text file
    with open("chat_id.txt", "w", encoding="utf-8") as file:
        file.write(chat_id)

    return chat_id


# Function to authenticate and resume chat
async def authenticate_and_resume_chat(
    hub_ws: websockets.WebSocketClientProtocol, chat_id: str
) -> None:

    logger.debug("Sending initial protocol message")
    # Start the hub connection and wait for it to establish
    initial_payload = json.dumps({"protocol": "json", "version": 1})
    await send_with_separator(hub_ws, initial_payload)
    await asyncio.sleep(0.02)

    # Authenticate
    auth_payload = {
        "arguments": [
            {
                "$type": "authenticate",
                "client": "Voxta.Talk",
                "clientVersion": "1.0.0",
                "scope": ["role:app", "role:admin", "role:inspector"],
                "capabilities": {
                    "audioInput": "WebSocketStream",
                    "audioOutput": "Url",
                    "acceptedAudioContentTypes": ["audio/x-wav", "audio/mpeg"],
                },
            }
        ],
        "target": "SendMessage",
        "type": 1,
    }
    logger.debug("Sending authentication payload: %s", auth_payload)
    await send_with_separator(hub_ws, auth_payload)
    await asyncio.sleep(0.02)

    # Resume chat
    resume_chat_payload = {
        "arguments": [
            {
                "$type": "resumeChat",
                "chatId": chat_id,
                "contextKey": "Talk",
                "context": "",
                "characterFunctions": [
                    {
                        "name": "play_hearts_emote",
                        "layer": "Emojis",
                        "description": r"When {{ char }} feels intense love or "
                        "wants to show their love to {{ user }}.",
                    },
                    {
                        "name": "play_unhappy_emote",
                        "layer": "Emojis",
                        "description": r"When {{ char }} is displeased about "
                        "what {{ user }} said.",
                    },
                    {
                        "name": "play_smile_emote",
                        "layer": "Emojis",
                        "description": r"When {{ char }} is happy.",
                    },
                    {
                        "name": "play_laugh_emote",
                        "layer": "Emojis",
                        "description": r"When {{ char }} is laughing.",
                    },
                    {
                        "name": "play_cry_emote",
                        "layer": "Emojis",
                        "description": r"When {{ char }} is crying or very sad.",
                    },
                    {
                        "name": "play_fear_emote",
                        "layer": "Emojis",
                        "description": r"When {{ char }} is afraid or telling a scary thing.",
                    },
                    {
                        "name": "play_angry_emote",
                        "layer": "Emojis",
                        "description": r"When {{ char }} is angry about what {{ user }} said.",
                    },
                    {
                        "name": "play_horny_emote",
                        "layer": "Emojis",
                        "description": r"When {{ char }} is aroused about what {{ user }} said.",
                    },
                    {
                        "name": "play_question_emote",
                        "layer": "Emojis",
                        "description": r"When {{ char }} is confused.",
                    },
                    {
                        "name": "play_surprise_emote",
                        "layer": "Emojis",
                        "description": r"When {{ char }} is surprised or startled.",
                    },
                    {
                        "name": "play_neutral_emote",
                        "layer": "Emojis",
                        "description": r"When {{ char }} does not have an emotion "
                        "strong enough to justify an emote.",
                    },
                ],
            }
        ],
        "target": "SendMessage",
        "type": 1,
    }
    logger.debug("Sending resume chat payload: %s", resume_chat_payload)
    await send_with_separator(hub_ws, resume_chat_payload)
    await asyncio.sleep(0.02)


async def handle_hub_messages(
    hub_ws: websockets.WebSocketClientProtocol, new_chat: Chat
) -> None:
    async with message_semaphore:
        async for messages in hub_ws:
            messages = messages.split("\x1e")
            logger.debug("Received messages RAW: %s", messages)
            for message in messages:
                try:
                    data = json.loads(message)
                    # print(f"DATA: \n\n{data}")
                    if data:
                        if "arguments" in data:
                            message_dict = data["arguments"][0]
                            if "$type" in message_dict:
                                logger.debug("Received message: %s", data)
                                if "sessionId" in message_dict:
                                    new_chat.session_id = message_dict["sessionId"]

                                if (
                                    message_dict["$type"] == "replyChunk"
                                    or message_dict["$type"] == "chatFlow"
                                ):
                                    if "audioUrl" in message_dict:
                                        audio_url = (
                                            VOXTA_SERVER + message_dict["audioUrl"]
                                        )
                                        response = requests.get(audio_url, timeout=5)
                                        audio_data = response.content
                                        audio_segment = AudioSegment.from_file(
                                            io.BytesIO(audio_data), format="mp3"
                                        )
                                        audio_segment.export(
                                            f"response_{message_dict['messageId']}.wav",
                                            format="wav",
                                        )
                                    if "text" in message_dict:
                                        print(
                                            f"{character_dict[message_dict['senderId']]}: "
                                            f"{message_dict['text']}"
                                        )
                                elif message_dict["$type"] == "chatStarted":
                                    print("CHAT STARTED")
                                    print(f"{new_chat.chat_started_event.is_set()}")
                                    new_chat.chat_started_event.set()
                                    new_chat.session_id = message_dict
                                    for chat_message in message_dict["messages"]:
                                        if chat_message["role"] == "Assistant":
                                            print(
                                                f"{chat_message['name']}: {chat_message['text']}"
                                            )
                                            break
                                elif message_dict["$type"] == "chatsSessionsUpdated":
                                    new_chat.session_id = message_dict["sessions"][0][
                                        "sessionId"
                                    ]
                                elif message_dict["$type"] == "replyEnd":
                                    print("\n")
                                    asyncio.get_running_loop().call_soon_threadsafe(
                                        set_chat_waiting_event, new_chat
                                    )
                except json.JSONDecodeError as e:
                    logger.error("Error decoding JSON: %s", e)


# Function to send a message
async def send_message(hub_ws, chat_obj: Chat, text):
    message_payload = {
        "arguments": [
            {
                "$type": "send",
                "sessionId": chat_obj.session_id,
                "text": text,
                "doReply": True,
                "doCharacterActionInference": True,
            }
        ],
        "target": "SendMessage",
        "type": 1,
    }
    logger.debug("Sending message payload: %s", message_payload)
    await send_with_separator(hub_ws, message_payload)
    asyncio.get_running_loop().call_soon_threadsafe(clear_chat_waiting_event, chat_obj)
    # print(f"is waiting for chat set: {chat_obj.waiting_for_chat_reply.is_set()}")
    await asyncio.sleep(0.02)


def get_type_value(data):
    if "$type" in data:
        return data["$type"]
    return None


def handle_chat_messages(chat_message_list):
    for chat_message in chat_message_list:
        if chat_message["role"] == "Assistant":
            print(f"{chat_message['name']}: {chat_message['text']}")


# Function to handle received messages


# Function to handle audio stream
async def handle_audio_stream() -> None:
    async with websockets.connect(AUDIO_STREAM_URL) as audio_ws:
        initial_message = {
            "contentType": "audio/wav",
            "sampleRate": 48000,
            "channels": 1,
            "bitsPerSample": 16,
            "bufferMilliseconds": 30,
        }
        logger.debug("Sending initial audio stream message: %s", initial_message)
        await audio_ws.send(json.dumps(initial_message))
        async for message in audio_ws:
            audio_data = message
            audio_segment = AudioSegment(
                data=audio_data,
                sample_width=2,  # 16 bits = 2 bytes
                frame_rate=48000,
                channels=1,
            )
            audio_segment.export(f"audio_stream_{int(time.time())}.wav", format="wav")


# Function to read input from the terminal and send message
async def async_terminal_input(
    hub_ws: websockets.WebSocketClientProtocol, chat_obj: Chat
) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    while True:
        text = input("Enter your message: ")
        await send_message(hub_ws, chat_obj, text)
        await chat_obj.waiting_for_chat_reply.wait()


async def ping(websocket):
    while True:
        await send_with_separator(websocket, json.dumps({}))
        print("------ ping")
        await asyncio.sleep(5)


# Main function
async def main() -> None:
    # Read the chat ID from the text file
    try:
        get_all_characters()
        with open("chat_id.txt", "r", encoding="utf-8") as file:
            chat_id = file.read().strip()
    except FileNotFoundError:
        logger.error("Skyrim chat not found.")
        chat_id = get_skyrim_chat_id()

    chat_id = "b18cd042-dcce-bc4f-c63c-6265154d9eb9"

    async with websockets.connect(HUB_URL) as hub_ws:
        new_chat = Chat(session_id="183869ed-64de-ab3e-ad64-aed9d8e4b2d8")
        new_chat.waiting_for_chat_reply.clear()
        asyncio.create_task(handle_hub_messages(hub_ws, new_chat))
        await authenticate_and_resume_chat(hub_ws, chat_id)
        # asyncio.create_task(ping(hub_ws))
        await new_chat.chat_started_event.wait()
        # Start audio stream handler
        # asyncio.create_task(handle_audio_stream())
        # Start the terminal input in a separate thread
        input_task = asyncio.create_task(async_terminal_input(hub_ws, new_chat))
        # handle_audio_stream(),
        while True:
            await asyncio.gather(handle_hub_messages(hub_ws, new_chat), input_task)
    print("test")

    # Keep the connection alive
    await hub_ws.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
