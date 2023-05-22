import os
import json
import traceback
import random

from enum import Enum

from loguru import logger
from chalice import Chalice

from telegram.ext import (
    Dispatcher,
    MessageHandler,
    Filters, CommandHandler,
)
from telegram import ParseMode, Update, Bot
from chalicelib.api import search
from chalicelib.classifier import ContentModerationSchema
from chalicelib.dao import UserRequestsDao, UserAnalyticsDao
from chalicelib.utils import generate_transcription, TypingThread, generate_random_image_url

# Telegram token
TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

# Chalice Lambda app

APP_NAME = "daniel-search-bot-serverless-v2"
MESSAGE_HANDLER_LAMBDA = "message-handler-lambda"

app = Chalice(app_name=APP_NAME)
app.debug = True

# Telegram bot
bot = Bot(token=TOKEN)
dispatcher = Dispatcher(bot, None, use_context=True)


class Stage(Enum):
    LOCAL = 'local'
    DEV = 'dev'
    PROD = 'prod'


STAGE = Stage(os.environ['STAGE'])

user_requests_dao = UserRequestsDao()
user_analytics_dao = UserAnalyticsDao()


#####################
# Telegram Handlers #
#####################

def get_random_waiting_text():
    with open('chalicelib/ui/ui_searching.json', 'r') as f:
        data = json.load(f)
    return random.choice(data['responses'])


def send_waiting_message(context, chat_id):
    waiting_text = get_random_waiting_text()
    context.bot.send_message(
        chat_id=chat_id,
        text=waiting_text
    )


def get_random_bad_word_warning():
    with open('chalicelib/ui/ui_badwords.json', 'r') as f:
        badwords = json.load(f)
    return random.choice(badwords)


def is_bad_word(text):
    examples = [
        {
            "input": "Попка паука",
            "output": '{"category": "normal"}',
        }
    ]
    moderation = ContentModerationSchema.from_openai(content=text, examples=examples)
    return moderation.category != "normal"


def block_by_bad_words(update, context):
    res = is_bad_word(update.message.text)
    if res:
        bad_word_warning = get_random_bad_word_warning()
        context.bot.send_message(
            chat_id=update.message.chat_id,
            text=bad_word_warning['bad_words_response'],
            parse_mode=ParseMode.HTML,
        )
    return res


def get_random_request_limit_warning():
    with open('chalicelib/ui/ui_limit_reached.json', 'r') as f:
        data = json.load(f)
    return random.choice(data['responses'])


def interaction_allowed(user_id) -> bool:
    requests_count = user_requests_dao.get_user_requests_count(user_id)
    no_limits_ids = [435461305]
    max_request_count = 999 if user_id in no_limits_ids else 10
    return requests_count < max_request_count


def block_by_request_count(update, context) -> bool:
    user_id = update.effective_user.id
    block_user = not interaction_allowed(user_id)
    if block_user:
        request_limit_warning = get_random_request_limit_warning()
        context.bot.send_message(
            chat_id=update.message.chat_id,
            text=request_limit_warning,
            parse_mode=ParseMode.HTML,
        )
    return block_user


def get_random_next_question():
    with open('chalicelib/ui/ui_next_question.json', 'r') as f:
        data = json.load(f)
    return random.choice(data['responses'])


def send_next_message(update, context):
    chat_id = update.effective_message.chat_id
    user_id = update.effective_user.id
    if interaction_allowed(user_id):
        next_question = get_random_next_question()
        context.bot.send_message(
            chat_id=chat_id,
            text=next_question
        )


def process_voice_message(update, context):
    user_id = update.effective_user.id
    chat_id = update.effective_message.chat_id

    user_analytics_dao.update_last_seen(user_id)

    block_execution = block_by_request_count(update, context)
    if block_execution:
        return

    send_waiting_message(context, chat_id)
    typing_thread = TypingThread(context, chat_id)
    typing_thread.start()

    file_id = update.message.voice.file_id
    file = bot.get_file(file_id)
    transcript_msg = generate_transcription(file)

    logger.info(f"Voice transcription: {transcript_msg}")

    try:
        search_result = run_search(chat_id, transcript_msg, context)
        if search_result:
            update_result = user_requests_dao.update_user_requests_count(user_id)
            requests_count = update_result['requests_count']
            logger.info(f"New request count for user {user_id}: {requests_count}")
        else:
            logger.info(f"Search process was rejected for user {user_id}")
    finally:
        typing_thread.stop()

    send_next_message(update, context)


def process_message(update, context):
    user_id = update.effective_user.id
    chat_id = update.effective_message.chat_id

    user_analytics_dao.update_last_seen(user_id)

    block_execution = block_by_request_count(update, context)
    if block_execution:
        return

    send_waiting_message(context, chat_id)
    typing_thread = TypingThread(context, chat_id)
    typing_thread.start()
    try:
        search_result = run_search(chat_id, update.message.text, context)
        if search_result:
            update_result = user_requests_dao.update_user_requests_count(user_id)
            requests_count = update_result['requests_count']
            logger.info(f"New request count for user {user_id}: {requests_count}")
        else:
            logger.info(f"Search process was rejected for user {user_id}")
    finally:
        typing_thread.stop()

    send_next_message(update, context)


def run_search(chat_id, chat_text, context):
    try:
        message = search(chat_text)
        logger.info(message)
    except Exception as e:
        app.log.error(e)
        app.log.error(traceback.format_exc())
        context.bot.send_message(
            chat_id=chat_id,
            text="Упс! Кажется, что-то пошло не так 😬 Но не волнуйтесь, наши кодовые мастера уже вовсю трудятся над исправлением проблемы! ⚙️",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
        return False
    else:
        context.bot.send_photo(
            chat_id=chat_id,
            photo=generate_random_image_url(),
            caption=message,
            parse_mode=ParseMode.HTML
        )
        return True


#####################
# Commands #
#####################

def get_random_greeting():
    with open('chalicelib/ui/ui_greetings.json', 'r') as f:
        greetings = json.load(f)
    return random.choice(greetings)


def start_command(update, context):
    user_id = update.effective_user.id

    if user_analytics_dao.user_exists(user_id):
        user_analytics_dao.update_last_seen(user_id)
    else:
        user_analytics_dao.register_user(user_id)

    greetings(context, update)


def greetings(context, update):
    greeting = get_random_greeting()
    context.bot.send_message(
        chat_id=update.message.chat_id,
        text=f"{greeting['greeting']}\n\n{greeting['description']}\n\n{greeting['prompt']}",
        parse_mode=ParseMode.HTML,
    )


def help_command(update, context):
    user_id = update.effective_user.id
    user_analytics_dao.update_last_seen(user_id)
    greetings(context, update)


############################
# Lambda Handler functions #
############################


@app.lambda_function(name=MESSAGE_HANDLER_LAMBDA)
def message_handler(event, context):
    dispatcher.add_handler(CommandHandler("start", start_command))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(MessageHandler(Filters.text, process_message))
    dispatcher.add_handler(MessageHandler(Filters.voice, process_voice_message))

    try:
        dispatcher.process_update(Update.de_json(json.loads(event["body"]), bot))
    except Exception as e:
        logger.error(e)
        return {"statusCode": 500}

    return {"statusCode": 200}


logger.info(f"STAGE: {STAGE}")
if STAGE == Stage.LOCAL:
    @app.route('/', methods=['POST'], content_types=['application/json'])
    def message_handler_route():
        request = app.current_request
        raw_body = request.raw_body
        json_body = json.loads(raw_body)
        response = {"body": json.dumps(json_body)}
        return message_handler(response, None)


@app.route('/analytics', methods=['GET'])
def analytics():
    query_params = app.current_request.query_params
    days = 30
    if query_params is not None and 'days' in query_params:
        days = int(query_params.get('days'))

    active_users = user_analytics_dao.get_active_users_count(days)
    total_users = user_analytics_dao.get_total_users_count()

    return {
        'active_users': active_users,
        'total_users': total_users
    }
