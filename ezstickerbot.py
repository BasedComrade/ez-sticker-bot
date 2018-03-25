import codecs
import json
import logging
import os
import sys
import time
from collections import Counter

from PIL import Image
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler

# setup logger
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

dir = os.path.dirname(__file__)

updater = None

config = {}
lang = {}


def start(bot, update):
    # feedback to show bot is processing
    bot.send_chat_action(chat_id=update.message.chat_id, action='typing')
    bot.send_message(chat_id=update.message.chat_id, text=get_message(update.message.chat_id, "start"),
                     parse_mode='Markdown')


def help_command(bot, update):
    # feedback to show bot is processing
    bot.send_chat_action(chat_id=update.message.chat_id, action='typing')
    bot.send_message(chat_id=update.message.chat_id, text=get_message(update.message.chat_id, "help"))


def send_stats(bot, update):
    # feedback to show bot is processing
    bot.send_chat_action(chat_id=update.message.chat_id, action='typing')
    stats_message = get_message(update.message.chat_id, "stats") % (config['uses'], len(config['lang_prefs']))
    bot.send_message(chat_id=update.message.chat_id, text=stats_message, parse_mode='Markdown')


def send_lang_stats(bot, update):
    # feedback to show bot is processing
    bot.send_chat_action(chat_id=update.message.chat_id, action='typing')

    # get message header
    lang_stats_message = get_message(update.message.chat_id, "lang_stats")

    # count lang usage
    lang_usage = dict(Counter(config['lang_prefs'].values()))

    # create stats message entries
    message_lines = {}
    for code, count in lang_usage.items():
        message_lines[str(lang[code]['order'])] = "\n%s: %d" % (lang[code]['lang_name'], count)

    # compile stats message in order
    for index in range(0, len(lang)):
        try:
            lang_stats_message += u"\u200E" + message_lines[str(index)]
        # Skip langs with 0 users
        except KeyError:
            continue

    # send message
    bot.send_message(chat_id=update.message.chat_id, text=lang_stats_message, parse_mode='Markdown')


def main():
    get_config()
    get_lang()
    global updater
    updater = Updater(config['token'])
    global uses
    uses = config['uses']
    dispatcher = updater.dispatcher

    # register a handler to ignore all non-private updates
    dispatcher.add_handler(MessageHandler(~ Filters.private, do_fucking_nothing))

    # register commands
    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(CommandHandler('help', help_command))
    dispatcher.add_handler(CommandHandler('stats', send_stats))
    dispatcher.add_handler(CommandHandler('langstats', send_lang_stats))
    dispatcher.add_handler(CommandHandler('restart', restart_bot))
    dispatcher.add_handler(CommandHandler('info', bot_info))
    dispatcher.add_handler(CommandHandler('lang', change_lang_command))
    dispatcher.add_handler(CommandHandler('broadcast', broadcast_command))

    # register invalid command handler
    dispatcher.add_handler(MessageHandler(Filters.command, invalid_command))

    # register media listener
    dispatcher.add_handler(MessageHandler((Filters.photo | Filters.sticker | Filters.document), image_sticker_received))
    dispatcher.add_handler(MessageHandler(Filters.all, invalid_content))

    # register button handlers
    dispatcher.add_handler(CallbackQueryHandler(change_lang, pattern="lang"))

    # register variable dump loop
    updater.job_queue.run_repeating(dump_variables, 300, 300)

    # register error handler
    dispatcher.add_error_handler(error)

    updater.start_polling(clean=True, timeout=99999)

    print("Bot finished starting")

    updater.idle()


def image_sticker_received(bot, update):
    # get file id
    if update.message.document:
        # check that document is image
        document = update.message.document
        if document.mime_type.lower() in ('image/png', 'image/jpeg', 'image/webp'):
            photo_id = document.file_id
        else:
            # feedback to show bot is processing
            bot.send_chat_action(chat_id=update.message.chat_id, action='typing')

            bot.send_message(chat_id=update.message.chat_id,
                             text=get_message(update.message.from_user.id, 'doc_not_img'), parse_mode='Markdown')
            return
    elif update.message.photo:
        photo_id = update.message.photo[-1].file_id
    else:
        photo_id = update.message.sticker.file_id

    # feedback to show bot is processing
    bot.send_chat_action(chat_id=update.message.chat_id, action='upload_photo')

    # download file
    file = bot.get_file(file_id=photo_id)
    temp = file.file_path.split('/')[-1].split('.')
    if len(temp) > 1:
        ext = '.' + file.file_path.split('/')[-1].split('.')[1]
    else:
        ext = '.webp'
    download_path = os.path.join(dir, (photo_id + ext))
    file.download(custom_path=download_path)

    # process image
    image = Image.open(download_path)
    width, height = image.size
    reference_length = max(width, height)
    ratio = 512 / reference_length
    new_width = int(width * ratio)
    new_height = int(height * ratio)
    image = image.resize((new_width, new_height), Image.ANTIALIAS)
    formatted_path = os.path.join(dir, (photo_id + '_formatted.png'))
    image.save(formatted_path, optimize=True)

    # send formatted image as a document
    document = open(formatted_path, 'rb')
    try:
        update.message.reply_document(document=document, filename='sticker.png',
                                      caption=get_message(update.message.chat_id, "forward"), quote=True, timeout=30)
    except TelegramError:
        bot.send_message(chat_id=update.message.chat_id,
                         text=get_message(user_id=update.message.from_user.id, message="send_timeout"))

    # delete local files and close image object
    image.close()
    time.sleep(0.20)
    os.remove(download_path)
    os.remove(formatted_path)

    # increase total uses count by one
    global config
    config['uses'] += 1


def invalid_command(bot, update):
    # feedback to show bot is processing
    bot.send_chat_action(chat_id=update.message.chat_id, action='typing')
    bot.send_message(chat_id=update.message.chat_id, text=get_message(update.message.chat_id, "invalid_command"))


def invalid_content(bot, update):
    # feedback to show bot is processing
    bot.send_chat_action(chat_id=update.message.chat_id, action='typing')

    bot.send_message(chat_id=update.message.chat_id, text=get_message(update.message.chat_id, "cant_process"))
    bot.send_message(chat_id=update.message.chat_id, text=get_message(update.message.chat_id, "send_sticker_photo"),
                     parse_mode='Markdown')


def bot_info(bot, update):
    # feedback to show bot is processing
    bot.send_chat_action(chat_id=update.message.chat_id, action='typing')
    keyboard = [
        [InlineKeyboardButton(get_message(update.message.chat_id, "contact_dev"), url="https://t.me/BasedComrade"),
         InlineKeyboardButton(get_message(update.message.chat_id, "source"),
                              url="https://github.com/BasedComrade/ez-sticker-bot")],
        [InlineKeyboardButton(get_message(update.message.chat_id, "rate"),
                              url="https://telegram.me/storebot?start=ezstickerbot")]]
    markup = InlineKeyboardMarkup(keyboard)
    bot.send_message(chat_id=update.message.chat_id, text=get_message(update.message.chat_id, "info") % config['uses'],
                     parse_mode='Markdown', reply_markup=markup)


def restart_bot(bot, update):
    # feedback to show bot is processing
    bot.send_chat_action(chat_id=update.message.chat_id, action='typing')
    if update.message.from_user.id in config['admins']:
        bot.send_message(chat_id=update.message.chat_id, text=get_message(update.message.chat_id, "restarting"))
        dump_variables()
        os.execl(sys.executable, sys.executable, *sys.argv)
    else:
        bot.send_message(chat_id=update.message.chat_id, text=get_message(update.message.chat_id, "no_permission"))


def broadcast_command(bot, update):
    chat_id = update.message.chat_id
    # feedback to show bot is processing
    bot.send_chat_action(chat_id=chat_id, action='typing')
    # check for permission
    if update.message.from_user.id not in config['admins']:
        bot.send_message(chat_id=chat_id, text=get_message(chat_id, "no_permission"))
        return

    target_message = update.message.reply_to_message

    # check that command was used in reply to a message
    if target_message is None:
        bot.send_message(chat_id=chat_id, text=get_message(chat_id, "broadcast_in_reply"), parse_mode='Markdown')
        return

    broadcast_message = target_message.text_html
    # check that target message is a text message
    if broadcast_message is None:
        bot.send_message(chat_id=chat_id, text=get_message(chat_id, "broadcast_only_text"), parse_mode='Markdown')
        return

    bot.send_message(chat_id=chat_id, text=get_message(chat_id, "will_broadcast"))
    updater.job_queue.run_once(broadcast_thread, 2, context=broadcast_message)


def broadcast_thread(bot, job):
    # check that message was included with the job obj
    if job.context is None:
        print("Broadcast thread created without message stored in job context")
        return

    index = 0
    for user_id in config['lang_prefs']:
        # catch any errors thrown by users who have stopped bot
        try:
            bot.send_message(chat_id=int(user_id), text=job.context, parse_mode='HTML', disable_web_page_preview=True)
        except TelegramError:
            pass

        index += 1
        if index >= 10:
            time.sleep(15)
            index = 0


def change_lang_command(bot, update):
    ordered_langs = [None] * len(lang)
    for lang_code in lang.keys():
        ordered_langs[int(lang[lang_code]['order'])] = lang_code
    keyboard = [[]]
    row = 0
    for lang_code in ordered_langs:
        if len(keyboard[row]) == 2:
            row += 1
            keyboard.append([])
        keyboard[row].append(InlineKeyboardButton(lang[lang_code]['lang_name'], callback_data="lang:%s" % lang_code))
    markup = InlineKeyboardMarkup(keyboard, )
    bot.send_message(chat_id=update.message.chat_id, text=get_message(update.message.chat_id, "select_lang"),
                     reply_markup=markup)


def change_lang(bot, update):
    query = update.callback_query
    lang_code = query.data.split(':')[-1]
    user_id = query.from_user.id
    global config
    config['lang_prefs'][str(user_id)] = lang_code
    query.edit_message_text(text=get_message(user_id, "lang_set"), reply_markup=None)
    query.answer()


def get_message(user_id, message):
    global config
    user_id = str(user_id)
    if user_id not in config['lang_prefs']:
        config['lang_prefs'][user_id] = 'en'
        lang_pref = 'en'
    else:
        lang_pref = config['lang_prefs'][user_id]
        if message not in lang[lang_pref]:
            lang_pref = 'en'
    return lang[lang_pref][message]


def get_lang():
    path = os.path.join(dir, 'lang.json')
    data = json.load(codecs.open(path, 'r', 'utf-8-sig'))
    for lang_code in data:
        for message in data[lang_code]:
            data[lang_code][message] = data[lang_code][message].replace('\\n', '\n')
    global lang
    lang = data


def get_config():
    path = os.path.join(dir, 'config.json')
    with open(path) as data_file:
        data = json.load(data_file)
    global config
    config = data


def dump_variables(bot=None, job=None):
    data = json.dumps(config)
    path = os.path.join(dir, 'config.json')
    with open(path, "w") as f:
        f.write(data)


# logs bot errors thrown
def error(bot, update, error):
    logger.warning('Update "%s" caused error "%s"' % (update, error))


def do_fucking_nothing(bot, update):
    pass


if __name__ == '__main__':
    main()
