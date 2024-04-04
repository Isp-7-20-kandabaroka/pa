import os
import re
import uuid

import asyncio
import logging
import sqlite3
import hashlib
import datetime

import aiosqlite

from datetime import datetime
from datetime import timedelta

from aiohttp import ClientSession

from collections import defaultdict

from aiogram.types import CallbackQuery
from aiogram.dispatcher import FSMContext

from forbidden_words import forbidden_words_list

from aiogram import Bot, Dispatcher, types, executor

from aiogram.utils.exceptions import MessageNotModified

from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

from aiogram.dispatcher.filters.state import State, StatesGroup

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.exceptions import MessageToDeleteNotFound, MessageCantBeDeleted, BadRequest





from aiogram.types import Message

subscription_start = datetime.now()
# Создаем подключение к базе данных
connection = sqlite3.connect('my_database.db')
cursor = connection.cursor()


# Список городов
cities_list = [
    "Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань", "Нижний Новгород",
    "Челябинск", "Красноярск", "Самара", "Уфа", "Ростов-на-Дону", "Омск", "Краснодар",
    "Воронеж", "Волгоград", "Пермь", "Томск", "Кемерово", "Владивосток", "Хабаровск", "Иркутск"
]

# Словарь для отслеживания активности пользователя
last_activity = {}


# Сохраняем изменения и закрываем соединение
connection.commit()
connection.close()
# Инициализация логгера
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

storage = MemoryStorage()
bot = Bot(token='6669399410:AAHWkE80Jqix61KmaXW-TQzqYw6bMZaFuhE')
dp = Dispatcher(bot, storage=storage)

CHANNEL_ID = -1002025346514
ADMIN_IDS = [487242878]  # Замените на реальные ID администраторов
class UserState(StatesGroup):
    AddCity = State()
    CitySelected = State()
    Subscribed = State()
    AdDescription = State()
    WaitForContact = State()
    AskForPhoto = State()
    WaitForPhotos = State()
    AdPhotos = State()
    Complaint = State()
    DeleteAd = State()
    SupportSession = State()
    AwaitReply = State()
    DeleteCity = State()


async def register_user_if_not_exists(user_id: int, username: str = None):
    async with aiosqlite.connect('my_database.db') as db:
        # Проверяем, существует ли пользователь в базе данных
        async with db.execute("SELECT id FROM users WHERE id = ?", (user_id,)) as cursor:
            user_exists = await cursor.fetchone()
            if not user_exists:
                # Если пользователя нет, регистрируем его и сохраняем его телеграм-ссылку
                await db.execute("INSERT INTO users (id, username, is_blocked, plus) VALUES (?, ?, 0, 1)",
                                 (user_id, username))
                await db.commit()

                # После регистрации пользователя отправляем сообщение в канал
                message_text = f"🎉 Новый пользователь [id{user_id}] присоединился к боту!"
                await bot.send_message(CHANNEL_ID, message_text, parse_mode=types.ParseMode.HTML)
async def check_and_block_user_if_needed(user_id: int):
    async with aiosqlite.connect('my_database.db') as db:
        # Инкрементируем счётчик жалоб
        await db.execute("UPDATE users SET complaints_count = complaints_count + 1 WHERE id = ?", (user_id,))
        # Проверяем количество жалоб после инкремента
        async with db.execute("SELECT complaints_count FROM users WHERE id = ?", (user_id,)) as cursor:
            complaints_count = await cursor.fetchone()
            if complaints_count and complaints_count[0] >= 3:
                # Обновляем статус блокировки пользователя
                await db.execute("UPDATE users SET is_blocked = 1 WHERE id = ?", (user_id,))
                await db.commit()
                return True  # Возвращаем True, если пользователь был заблокирован
        await db.commit()  # Важно помнить о коммите изменений
        return False  # Возвращаем False, если количество жалоб меньше 3

async def update_last_activity(user_id: int):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # Форматируем текущее время как строку
    async with aiosqlite.connect('my_database.db') as db:
        await db.execute("UPDATE users SET last_activity = ? WHERE id = ?", (now, user_id))
        await db.commit()
async def check_inactivity():
    while True:
        try:
            now = datetime.now()
            time_threshold = now - timedelta(seconds=3600)

            async with aiosqlite.connect('my_database.db') as db:
                # Выполняем запрос для поиска неактивных пользователей
                async with db.execute("SELECT id FROM users WHERE last_activity < ?", (time_threshold,)) as cursor:
                    inactive_users = await cursor.fetchall()

                # Отправляем уведомления найденным пользователям
                for user_id, in inactive_users:
                    await send_notification(user_id)

            # Ждем перед следующей проверкой
            await asyncio.sleep(21600)
        except Exception as e:
            # Логируем любые ошибки и продолжаем цикл
            print(f"Ошибка при проверке неактивности: {e}")

def restart_button():
    # Создаем кнопку для перезапуска
    markup = InlineKeyboardMarkup()
    button = InlineKeyboardButton(text="Перезапустить", callback_data="clear_chat1")
    markup.add(button)
    return markup



async def send_notification(user_id: int):
    try:
        # Используем user_id как chat_id для отправки сообщения
        await bot.send_message(user_id,
                               "Вы были неактивны в течение последних 6 часов.\nНажмите на кнопку перезапустить ниже\nчтобы продолжить пользоваться функциями бота.",
                               reply_markup=restart_button())
    except Exception as e:
        # Логируем ошибку, если что-то пошло не так
        print(f"Ошибка при отправке уведомления пользователю {user_id}: {e}")
@dp.message_handler(commands=['stat'])
async def send_statistics(message: types.Message):
    user_id = message.from_user.id  # Получаем ID пользователя, отправившего команду

    # Проверяем, есть ли пользователь в списке администраторов
    if user_id not in ADMIN_IDS:
        await message.reply("Извините, у вас нет доступа к этой команде.")
        return

    async with aiosqlite.connect('my_database.db') as db:
        # Получаем количество объявлений в каждом городе
        async with db.execute("SELECT city_id, COUNT(*) as count FROM advertisements GROUP BY city_id") as cursor:
            rows = await cursor.fetchall()

        # Проверяем, есть ли результаты
        if rows:
            message_text = "Количество объявлений по городам:\n" + "\n".join([f"{row[0]}: {row[1]}" for row in rows])
            await message.reply(message_text)
        else:
            await message.reply("В базе данных пока нет объявлений.")

@dp.message_handler(commands=['start'], state="*")
async def send_welcome(message: types.Message):

    user_id = message.from_user.id
    await update_last_activity(user_id)
    username = message.from_user.username  # Получаем username пользователя
    await register_user_if_not_exists(user_id,username)
    if await is_user_blocked(user_id):
        await message.reply("Извините, ваш аккаунт заблокирован.")
        return
    keyboard = InlineKeyboardMarkup(row_width=2)
    button_subscribe = InlineKeyboardButton(text="Подписаться", url="https://t.me/SOVMESTNAYA_ARENDA_RU")
    button_continue = InlineKeyboardButton(text="Продолжить", callback_data='continue')

    keyboard.add(button_subscribe, button_continue)

    # Отправка картинки с кнопками в одном сообщении
    with open('main.jpg', 'rb') as photo:
        await message.answer_photo(photo, caption="Добро пожаловать в бота. Выберите, пожалуйста, действие.",reply_markup=keyboard)
async def is_user_blocked(user_id: int) -> bool:
    async with aiosqlite.connect('my_database.db') as db:
        async with db.execute("SELECT is_blocked FROM users WHERE id = ?", (user_id,)) as cursor:
            result = await cursor.fetchone()
            if result and result[0] == 1:
                return True
    return False
@dp.callback_query_handler(lambda c: c.data == 'continue', state="*")
async def main(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    user_id = callback_query.from_user.id
    await update_last_activity(callback_query.from_user.id)
    # Отправляем сообщение с инструкциями или информацией
    await callback_query.message.answer("Для начала выберите город", reply_markup=generate_main_menu_markup())
    # Добавляем реплай кнопку "Главное меню"

@dp.message_handler(commands=['delete'], state="*")
async def start_delete_ad(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.reply("Извините, но эта команда доступна только администраторам.")
        return

    await UserState.DeleteAd.set()
    await message.reply("Пожалуйста, введите ID объявления, которое вы хотите удалить:")
@dp.message_handler(state=UserState.DeleteAd)
async def delete_ad(message: types.Message, state: FSMContext):
    ad_id = message.text.strip()

    # Проверка, что введенный текст является числом
    if not ad_id.isdigit():
        await message.reply("ID объявления должен быть числом. Пожалуйста, попробуйте еще раз.")
        return

    async with aiosqlite.connect('my_database.db') as db:
        # Проверяем наличие объявления в базе данных
        async with db.execute("SELECT id FROM advertisements WHERE id = ?", (ad_id,)) as cursor:
            ad = await cursor.fetchone()
            if ad is None:
                await message.reply(f"Объявление с ID {ad_id} не найдено.")
            else:
                # Удаляем объявление
                await db.execute("DELETE FROM advertisements WHERE id = ?", (ad_id,))
                await db.commit()
                await message.reply(f"Объявление с ID {ad_id} успешно удалено.")

    await state.finish()  # Выход из состояния удаления


@dp.message_handler(commands=['menu'], state="*")
async def back_to_main_menu(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await update_last_activity(message.from_user.id)
    user_id = message.from_user.id
    if await is_user_blocked(user_id):
        await message.reply("Извините, ваш аккаунт заблокирован.")
        return
    last_menu_message_id = data.get('last_menu_message_id')

    if last_menu_message_id:
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=last_menu_message_id)
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения с меню: {e}")

    # Отправка нового сообщения с меню
    sent_message = await message.answer("Добро пожаловать в главное меню!", reply_markup=generate_main_menu_markup())

    # Обновляем ID последнего сообщения с меню
    await state.update_data(last_menu_message_id=sent_message.message_id)

def generate_main_menu_markup():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Выбрать город", callback_data="select_city"))
    #markup.add(types.InlineKeyboardButton("Подписка", callback_data="oplata"))
    # Добавьте другие кнопки по мере необходимости
    return markup

async def generate_city_selection_markup():
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []

    # Устанавливаем соединение с базой данных
    connection = sqlite3.connect('my_database.db')
    cursor = connection.cursor()
    cities = await fetch_cities()  # Получаем отсортированный список городов
    # Получаем список городов из базы данных
    cursor.execute("SELECT name FROM cities ORDER BY name ASC")
    cities = cursor.fetchall()

    # Закрываем соединение с базой данных
    connection.close()

    # Создаём кнопки для каждого города
    for city in cities:
        city_name = city[0]  # Получаем название города из кортежа
        button = types.InlineKeyboardButton(city_name, callback_data=f"city_{city_name}")
        buttons.append(button)

    # Добавляем кнопки в разметку
    markup.add(*buttons)

    # Добавляем кнопку "Добавить город"
    markup.row(types.InlineKeyboardButton("Добавить город", callback_data="add_city"))

    return markup


@dp.callback_query_handler(lambda c: c.data == 'add_city')
async def add_city_callback(callback_query: types.CallbackQuery):
    # Создаем Inline клавиатуру с кнопкой "Отменить"
    cancel_markup = InlineKeyboardMarkup().add(
        InlineKeyboardButton("Отменить", callback_data='cancel_adding_city')
    )

    # Переводим пользователя в состояние добавления города
    await UserState.AddCity.set()
    await bot.send_message(
        callback_query.from_user.id,
        "Введите название города:",
        reply_markup=cancel_markup
    )


@dp.callback_query_handler(lambda c: c.data == 'cancel_adding_city', state=UserState.AddCity)
async def cancel_adding_city(callback_query: types.CallbackQuery, state: FSMContext):
    # Сбрасываем состояние пользователя
    await state.reset_state()

    # Удаляем сообщение с запросом на ввод города
    await bot.delete_message(callback_query.from_user.id, callback_query.message.message_id)

    # Отправляем подтверждение об отмене
    await bot.send_message(callback_query.from_user.id, "Добавление города отменено.")

def generate_delete_keyboard():
    markup = types.InlineKeyboardMarkup()
    delete_button = types.InlineKeyboardButton("скрыть", callback_data="delete_message")
    markup.add(delete_button)
    return markup
def generate_back_to_main_markup():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Назад", callback_data="back_to_main"))
    return markup
def generate_skip_button():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Пропустить", callback_data="skip_photos"))
    return markup
def generate_oplata_button():
    markup = types.InlineKeyboardMarkup()
    delete_button = types.InlineKeyboardButton("скрыть", callback_data="delete_message")
    markup.add(types.InlineKeyboardButton("Купить подписку", callback_data="buy"))
    return markup
def generate_done_button():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Завершить создание", callback_data="done_z"))
    return markup
def city_again():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Посмотреть другие объявления", callback_data="sityagain"))
    return markup
def generate_reply_keyboard():
    # Создаем реплай клавиатуру с кнопкой "Главное меню"
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    keyboard.add(KeyboardButton("Главное меню"))
    return keyboard
def generate_clear_chat_button1():
    markup = InlineKeyboardMarkup()
    cancel_button = InlineKeyboardButton("Отменить", callback_data="cancel_complaint")
    markup.add(cancel_button)
    return markup
def generate_cancel_button():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Отменить", callback_data="cancel_support"))
    return markup

def generate_cancel_support_button():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Завершить диалог", callback_data="cancel_support"))
    return markup

def generate_action_keyboard_with_back():
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("Создать объявление", callback_data="create_ad"),
               types.InlineKeyboardButton("Просмотр объявлений", callback_data="view_ads"))
    markup.row(types.InlineKeyboardButton("Моё обьявление", callback_data="my_ad"),
               types.InlineKeyboardButton("Жалобы и предложения", callback_data="complaint_start"))
    markup.row(types.InlineKeyboardButton("Поддержка", callback_data="pod"),
               #types.InlineKeyboardButton("Подписка", callback_data="oplata"))
                types.InlineKeyboardButton("Выбрать другой город", callback_data="back_to_city_selection"))
    return markup

@dp.callback_query_handler(lambda c: c.data == "cancel_complaint", state=UserState.Complaint)
async def cancel_complaint(callback_query: types.CallbackQuery, state: FSMContext):
    # Здесь сохраняем выбор города и сбрасываем только состояние жалобы
    await state.reset_state(with_data=False)  # Сброс только текущего состояния, данные о городе остаются
    await bot.delete_message(callback_query.message.chat.id, callback_query.message.message_id)
    await bot.answer_callback_query(callback_query.id, "Жалоба отменена.")
    await bot.send_message(callback_query.from_user.id, "Вы вернулись в основное меню.")

@dp.callback_query_handler(lambda c: c.data == "pod", state="*")
async def start_support_session(callback_query: types.CallbackQuery, state: FSMContext):
    await update_last_activity(callback_query.from_user.id)
    user_id = callback_query.from_user.id
    await update_last_activity(user_id)
    # Вызываем track_user_action до любых действий, чтобы проверить, не является ли поведение пользователя спамом
    need_to_clear_chat = await track_user_action(user_id)
    if need_to_clear_chat:
        await state.finish()
        await clear_chat(user_id, callback_query.message.message_id)
    else:
        await UserState.SupportSession.set()
        await state.update_data(user_id=callback_query.from_user.id)  # Сохраняем ID пользователя для последующего ответа
        await bot.send_message(
        callback_query.from_user.id,
        "Пожалуйста, напишите ваш вопрос, и наш сотрудник свяжется с вами!\n\nЕсли вы передумали и хотите прекратить действие,\n\nОбязательно нажмите кнопку отменить, прежде чем переходить к другим командам",
        reply_markup=generate_cancel_button()
    )


@dp.callback_query_handler(lambda c: c.data == "cancel_support", state=UserState.SupportSession)
async def cancel_support_session(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    await track_user_action(user_id)  # Отслеживаем активность пользователя
    await state.reset_state(with_data=False)  # Сбрасываем состояние
    await bot.edit_message_text(
        text="Чат поддержки отменен. Вы можете воспользоваться другими командами.",
        chat_id=callback_query.from_user.id,
        message_id=callback_query.message.message_id,
        reply_markup=None  # Убираем клавиатуру
    )


@dp.message_handler(state=UserState.SupportSession)
async def handle_user_question(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username
    support_staff_id = 487242878  # ID сотрудника поддержки

    data = await state.get_data()
    last_message_id = data.get('last_cancel_button_message_id')

    # Если есть предыдущее сообщение с кнопкой, удаляем его
    if last_message_id:
        try:
            await bot.delete_message(chat_id=user_id, message_id=last_message_id)
        except Exception as e:
            print(f"Не удалось удалить сообщение: {e}")

    forward_message = f"Вопрос от @{username} (ID: {user_id}):\n\n{message.text}"
    markup = InlineKeyboardMarkup().add(InlineKeyboardButton("Ответить", callback_data=f"reply_{user_id}_{username}"))
    await bot.send_message(support_staff_id, forward_message, reply_markup=markup)





@dp.callback_query_handler(lambda c: c.data.startswith('reply_'), state="*")
async def initiate_reply(callback_query: types.CallbackQuery, state: FSMContext):
    _, user_id, username = callback_query.data.split('_')
    await state.update_data(reply_to_user_id=user_id)  # Сохраняем ID пользователя для ответа
    await UserState.AwaitReply.set()  # Переводим админа в состояние ожидания ответа

    # Формируем приглашение к ответу, включая имя пользователя
    prompt = f"Введите ваш ответ для @{username}:"
    await bot.send_message(callback_query.from_user.id, prompt)


@dp.message_handler(state=UserState.AwaitReply)
async def send_reply_to_user(message: types.Message, state: FSMContext):
    data = await state.get_data()
    reply_to_user_id = data['reply_to_user_id']  # Получаем ID пользователя для отправки ответа

    # Отправляем ответ пользователю
    await bot.send_message(reply_to_user_id, message.text)

    # Отправляем сообщение с кнопкой для завершения диалога
    sent_message = await bot.send_message(reply_to_user_id, "Ваш вопрос был отвечен.\n\nЕсли хотите завершить диалог, обязательно нажмите кнопку ниже.", reply_markup=generate_cancel_support_button())

    # Обновляем ID последнего сообщения с кнопкой в состоянии пользователя
    await state.update_data(last_cancel_button_message_id=sent_message.message_id)

    # Сообщаем админу, что ответ был отправлен
    await message.reply("Ваш ответ был отправлен.")

    # Сбрасываем состояние админа
    await state.reset_state()


@dp.callback_query_handler(lambda c: c.data == "complaint_start", state="*")
async def start_complaint(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    await update_last_activity(callback_query.from_user.id)
    await track_user_action(user_id)  # Отслеживаем активность пользователя
    await UserState.Complaint.set()
    await bot.send_message(callback_query.from_user.id, "Пожалуйста, опишите вашу проблему или предложение.\n\n"
        "Если вы хотите пожаловаться на пользователя, укажите его имя в формате @имя.\n"
        "\n\nЕсли вы передумали и хотите прекратить действие,\nобязательно нажмите кнопку отменить, прежде чем переходить к другим командам",reply_markup=generate_clear_chat_button1())
@dp.message_handler(state=UserState.Complaint)
async def handle_complaint(message: types.Message, state: FSMContext):
    channel_id = -1002025346514  # ID вашего канала для жалоб
    complaint_text = message.text

    # Попытка извлечь username из текста жалобы
    username_match = re.search(r'@(\w+)', complaint_text)
    if username_match:
        username = username_match.group(1)
        # Проверка наличия пользователя в базе данных и его блокировка при необходимости
        async with aiosqlite.connect('my_database.db') as db:
            async with db.execute("SELECT id FROM users WHERE username = ?", (username,)) as cursor:
                user = await cursor.fetchone()
                if user:
                    user_id = user[0]
                    # Регистрация жалобы и проверка на блокировку
                    user_blocked = await check_and_block_user_if_needed(user_id)
                    if user_blocked:
                        await message.reply(f"Пользователь @{username} был заблокирован после 3 жалоб.")
                    else:
                        await message.reply(f"Жалоба на пользователя @{username} зарегистрирована.")
                else:
                    await message.reply(f"Пользователь @{username} не найден в базе данных.")

    # Сообщение отправляется в канал независимо от того, был ли найден и заблокирован пользователь
    user_mention = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    channel_message = f"Пользователь {user_mention} ({message.from_user.id}) отправил следующее сообщение:\n\n{complaint_text}"
    await bot.send_message(channel_id, channel_message)
    await message.reply("Ваше сообщение отправлено, спасибо за обратную связь!", reply_markup=generate_clear_chat_button())
    await state.finish()

def generate_clear_chat_button():
    markup = InlineKeyboardMarkup()
    clear_button = InlineKeyboardButton("Назад", callback_data="clear_chat")
    markup.add(clear_button)
    return markup


async def city_exists(city_name: str) -> bool:
    async with aiosqlite.connect('my_database.db') as db:
        async with db.execute("SELECT EXISTS(SELECT 1 FROM cities WHERE name = ? LIMIT 1)", (city_name,)) as cursor:
            return (await cursor.fetchone())[0] == 1

@dp.callback_query_handler(lambda c: c.data.startswith("confirm_city"))
async def confirm_city(callback_query: types.CallbackQuery):
    print(f"Callback data received: {callback_query.data}")  # Для логирования
    try:
        _, city_name, user_id_str = callback_query.data.split(":", 2)
    except ValueError as e:
        print(f"Error splitting callback data: {e}")  # Логирование ошибки
        return  # Выход из функции для предотвращения ошибок

    user_id = int(user_id_str)  # Преобразование строки в число

    if await city_exists(city_name):
        await bot.answer_callback_query(callback_query.id, f"Город {city_name} уже существует.")
    else:
        async with aiosqlite.connect('my_database.db') as db:
            await db.execute("INSERT INTO cities (name, proposed_by_user_id) VALUES (?, ?)", (city_name, user_id))
            await db.commit()
        await bot.answer_callback_query(callback_query.id, f"Город {city_name} добавлен.")
        # Отправляем уведомление пользователю, предложившему город
        await bot.send_message(user_id, f"Ваш предложенный город {city_name} был успешно добавлен. Нажмите /menu, чтобы посмотреть его в списке.")
        # Отправляем уведомление в канал для администратора
        channel_id = -1002025346514  # Убедитесь, что здесь правильный ID вашего канала
        await bot.send_message(channel_id, f"Администратор подтвердил добавление города: {city_name}.")


@dp.callback_query_handler(lambda c: c.data == "cancel_city")
async def cancel_city(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id, "Предложение отклонено.")
    # Опционально: отправляйте уведомление пользователю, предложившему город


# Обработчик для кнопки удаления
@dp.callback_query_handler(lambda c: c.data == 'delete_message')
async def process_callback_delete_message(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    await track_user_action(user_id)  # Отслеживаем активность пользователя
    await bot.delete_message(chat_id=callback_query.message.chat.id, message_id=callback_query.message.message_id)

@dp.message_handler(state=UserState.AddCity)
async def add_city(message: types.Message, state: FSMContext):
    city_name = message.text.strip()  # Удаляем пробелы по краям

    async with aiosqlite.connect('my_database.db') as db:
        # Проверяем, существует ли город в базе данных
        async with db.execute("SELECT COUNT(*) FROM cities WHERE name = ?", (city_name,)) as cursor:
            count = await cursor.fetchone()
            if count[0] > 0:
                # Если город найден в базе данных, информируем пользователя
                await message.reply("Такой город уже существует.")
                await state.finish()  # Завершаем состояние
                return  # Прекращаем выполнение функции

    # Если города нет в базе, продолжаем отправку предложения
    channel_id = -1002025346514  # ID вашего канала
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Подтвердить", callback_data=f"confirm_city:{city_name}:{message.from_user.id}")],
        [InlineKeyboardButton(text="Отклонить", callback_data=f"cancel_city_{message.from_user.id}")]
    ])
    try:
        await bot.send_message(channel_id, f"Пользователь @{message.from_user.username} предложил добавить город: {city_name}", reply_markup=markup)
        await message.reply("Ваше предложение отправлено на рассмотрение.")
    except Exception as e:
        await message.reply("Произошла ошибка при отправке предложения.")
        logger.error(f"Ошибка при отправке сообщения в канал: {e}")
    finally:
        await state.finish()  # Завершаем состояние после обработки


@dp.message_handler(commands=['delete_city'], state='*')
async def start_delete_city(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.reply("Извините, у вас нет прав для использования этой команды.")
        return

    await UserState.DeleteCity.set()
    await message.reply("Введите название города, который вы хотите удалить:")


@dp.message_handler(state=UserState.DeleteCity)
async def delete_city(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.reply("Извините, у вас нет прав для использования этой команды.")
        await state.finish()  # Завершаем состояние
        return

    city_name = message.text.strip()  # Удаляем пробелы по краям

    async with aiosqlite.connect('my_database.db') as db:
        # Проверяем, существует ли город в базе данных
        async with db.execute("SELECT id FROM cities WHERE name = ?", (city_name,)) as cursor:
            city = await cursor.fetchone()
            if city is None:
                # Если город не найден
                await message.reply("Город не найден.")
            else:
                # Удаляем город из базы данных
                await db.execute("DELETE FROM cities WHERE name = ?", (city_name,))
                await db.commit()
                await message.reply(f"Город {city_name} удален из базы данных.")

    await state.finish()  # Завершаем состояние после обработки


async def back_to_main(callback_query: types.CallbackQuery):
    await callback_query.message.edit_text("Главное меню:", reply_markup=generate_main_menu_markup())

@dp.callback_query_handler(text="select_city")
async def select_city(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id

    await update_last_activity(callback_query.from_user.id)
    # Используем await для асинхронного получения InlineKeyboardMarkup
    markup = await generate_city_selection_markup()
    await callback_query.message.edit_text("Выберите город:", reply_markup=markup)

@dp.callback_query_handler(lambda c: c.data and c.data.startswith('city_'), state='*')
async def process_city_selection(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    await update_last_activity(callback_query.from_user.id)
    city = callback_query.data.split('_')[1]
    await state.update_data(city=city, user_id=callback_query.from_user.id)
    logger.info(f"Город {city} выбран, обновление данных состояния.")

    # Сохраняем выбранный город в данных состояния
    await state.update_data(city=city)
    logger.info("Данные состояния обновлены с выбранным городом.")

    # Отправляем сообщение с обновленной клавиатурой
    markup = generate_action_keyboard_with_back()
    await callback_query.message.edit_text(f"Вы выбрали город: {city}.", reply_markup=markup)
    logger.info("Сообщение с выбором города отправлено.")

@dp.callback_query_handler(lambda c: c.data == 'sityagain', state='*')
async def select_city_again(callback_query: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()

    # Попытка удалить сообщение с кнопкой "Посмотреть другие объявления"
    try:
        await bot.delete_message(chat_id=callback_query.message.chat.id, message_id=callback_query.message.message_id)
        logger.info("Сообщение с кнопкой 'Посмотреть другие объявления' удалено.")
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения с кнопкой: {e}")

    if 'last_menu_message_id' in data:
        try:
            await bot.delete_message(chat_id=callback_query.message.chat.id, message_id=data['last_menu_message_id'])
            logger.info(f"Сообщение с ID {data['last_menu_message_id']} удалено.")
        except Exception as e:
            logger.error(f"Ошибка при удалении предыдущего сообщения с меню: {e}")

    # Очищаем ID последнего сообщения с меню в состоянии и продолжаем логику функции
    await state.update_data(last_menu_message_id=None)

    # Очистка данных о предыдущих объявлениях и сообщении с меню
    await state.set_data({'ads': [], 'current_ad_index': 0, 'messages_to_delete': []})
    logger.info("Состояние очищено для нового выбора города.")

    # Удаление прошлых объявлений
    for msg_id in data.get('messages_to_delete', []):
        try:
            await bot.delete_message(callback_query.message.chat.id, msg_id)
            logger.info(f"Сообщение объявления с ID {msg_id} удалено.")
        except Exception as e:
            logger.error(f"Не удалось удалить сообщение объявления: {e}")





@dp.callback_query_handler(lambda c: c.data == 'back_to_city_selection', state='*')
async def back_to_city_selection(callback_query: types.CallbackQuery, state: FSMContext):
    # Используем await для асинхронного получения InlineKeyboardMarkup
    markup = await generate_city_selection_markup()
    await callback_query.message.edit_text("Выберите ваш город:", reply_markup=markup)


@dp.callback_query_handler(text="my_ad", state="*")
async def my_ad(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    await update_last_activity(callback_query.from_user.id)
    connection = sqlite3.connect('my_database.db')
    cursor = connection.cursor()
    cursor.execute("SELECT id, description, contact, photos, city_id FROM advertisements WHERE user_id=?", (user_id,))
    ad = cursor.fetchone()
    connection.close()

    if not ad:
        await bot.send_message(user_id, "У вас пока нет созданных объявлений.")
        return

    ad_id, description, contact, photos,city = ad
    message_text = f"Ваше объявление:\nID: {ad_id}\nОписание: {description}\nКонтакт: {contact}\nВ Городе: {city}"

    # Проверяем наличие фотографий в объявлении
    if photos:
        # Предполагаем, что `photos` хранит пути к фотографиям через запятую
        photos_list = photos.split(',')
        # Отправляем первую фотографию с текстом объявления
        with open(photos_list[0].strip(), 'rb') as photo:
            await bot.send_photo(user_id, photo, caption=message_text, reply_markup=generate_delete_keyboard())
        # Если есть дополнительные фотографии, отправляем их отдельными сообщениями
        for photo_path in photos_list[1:]:
            with open(photo_path.strip(), 'rb') as photo:
                await bot.send_photo(user_id, photo)
    else:
        await bot.send_message(user_id, message_text, reply_markup=generate_delete_keyboard())



async def delete_previous_messages(state: FSMContext, chat_id: int):
    async with state.proxy() as data:
        # Удаление сообщения бота
        last_bot_message_id = data.pop('last_bot_message_id', None)
        if last_bot_message_id:
            try:
                await bot.delete_message(chat_id, last_bot_message_id)
            except Exception as e:
                logging.error(f"Error deleting bot's message: {e}")

        # Удаление сообщения пользователя
        last_user_message_id = data.pop('last_user_message_id', None)
        if last_user_message_id:
            try:
                await bot.delete_message(chat_id, last_user_message_id)
            except Exception as e:
                logging.error(f"Error deleting user's message: {e}")


@dp.callback_query_handler(lambda c: c.data == 'create_ad', state="*")
async def create_ad(callback_query: types.CallbackQuery, state: FSMContext):
    chat_id = callback_query.message.chat.id
    user_id = callback_query.from_user.id
    await update_last_activity(callback_query.from_user.id)
    # Вызываем track_user_action до любых действий, чтобы проверить, не является ли поведение пользователя спамом
    need_to_clear_chat = await track_user_action(user_id)
    if need_to_clear_chat:
        await state.finish()
        await clear_chat(user_id, callback_query.message.message_id)
        return

    # Проверяем, есть ли у пользователя активная подписка
    async with aiosqlite.connect('my_database.db') as db:
        async with db.execute("SELECT plus FROM users WHERE id = ?", (user_id,)) as cursor:
            subscription_status = await cursor.fetchone()

    if subscription_status is None or subscription_status[0] == 0 and user_id not in ADMIN_IDS:
        # Если подписка не активна и пользователь не является администратором, сообщаем пользователю
        await bot.send_message(chat_id,
                               "Извините, создавать объявления могут только пользователи с активной подпиской или администраторы.")
        return

    # Удаление предыдущих сообщений
    await delete_previous_messages(state, chat_id)

    if user_id not in ADMIN_IDS:
        # Проверяем, есть ли уже созданное объявление у пользователя, если он не администратор
        async with aiosqlite.connect('my_database.db') as db:
            async with db.execute("SELECT COUNT(*) FROM advertisements WHERE user_id = ?", (user_id,)) as cursor:
                count = await cursor.fetchone()

        if count and count[0] > 0:
            # Если объявление уже существует, информируем пользователя
            await bot.send_message(chat_id,
                                   "Вы уже создали объявление. В данный момент разрешено создавать только одно объявление.")
            return

    # Если объявления нет, или пользователь является администратором, устанавливаем начальное состояние процесса создания объявления
    await bot.send_message(chat_id, "Укажите краткую информацию о себе и вашем предложении:")
    await UserState.AdDescription.set()



def compile_forbidden_words_regex(words_list):
    # Экранируем специальные символы в словах и объединяем их в одно большое регулярное выражение
    escaped_words = [re.escape(word) for word in words_list]
    pattern = '|'.join(escaped_words)
    return re.compile(pattern, re.IGNORECASE)


def filter_description(description):
    # Регулярные выражения для фильтрации контактной информации
    phone_pattern = r'\+7\s?9[0-9]{9}|89[0-9]{9}'
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'  # Шаблон для электронных адресов
    link_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'  # Шаблон для ссылок
    mention_pattern = r'@\w+'  # Шаблон для упоминаний пользователей
    # Шаблон для удаления всех чисел, кроме двухзначных

    # Компилируем регулярное выражение для запрещенных слов
    forbidden_words_regex = compile_forbidden_words_regex(forbidden_words_list)

    # Заменяем запрещенные слова и контактные данные на пустые строки
    patterns = [forbidden_words_regex, phone_pattern, email_pattern, link_pattern, mention_pattern,
                ]
    for pattern in patterns:
        description = re.sub(pattern, "", description)

    return description.strip()  # Удаляем начальные и конечные пробелы

# Обработка введенного описания объявления
@dp.message_handler(state=UserState.AdDescription)
async def process_ad_description(message: types.Message, state: FSMContext):
    filtered_description = filter_description(message.text)  # Фильтруем текст

    async with state.proxy() as data:
        data['description'] = filtered_description

    await UserState.WaitForContact.set()
    await message.answer("Введите контактную информацию:")

@dp.message_handler(state=UserState.WaitForContact)
async def process_contact_info(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['contact'] = message.text

    # Переход к новому состоянию запроса на добавление фото
    await UserState.AskForPhoto.set()
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Добавить фото", callback_data="add_photo"))
    markup.add(InlineKeyboardButton("Пропустить", callback_data="skip_photo"))
    await message.answer("Хотите ли добавить фото?", reply_markup=markup)


@dp.callback_query_handler(lambda c: c.data == 'add_photo', state=UserState.AskForPhoto)
async def add_photo_handler(callback_query: types.CallbackQuery):
    await UserState.WaitForPhotos.set()
    await bot.answer_callback_query(callback_query.id)

    # Создание кнопки "Пропустить"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Пропустить", callback_data="skip_photo"))

    await bot.send_message(callback_query.from_user.id, "Пожалуйста, отправьте фотографию.", reply_markup=markup)

# Обработка полученной фотографии
@dp.message_handler(content_types=types.ContentType.PHOTO, state=UserState.WaitForPhotos)
async def process_photos(message: types.Message, state: FSMContext):
    photo = message.photo[-1]  # Берем последнюю отправленную фотографию
    photo_id = photo.file_id

    # Получаем путь для сохранения фотографии
    photo_path = os.path.join('img', f'{photo_id}.jpg')

    # Сохраняем фотографию на диск
    await photo.download(destination=photo_path)

    # Сохраняем ID фотографии в состояние
    async with state.proxy() as data:
        data['photo'] = photo_path

    await message.answer("Фотография добавлена. нажмите чтобы закончить.",reply_markup=generate_done_button())

async def fetch_cities():
    async with aiosqlite.connect('my_database.db') as db:
        cursor = await db.execute("SELECT name FROM cities ORDER BY name ASC")
        cities = await cursor.fetchall()
        return [city[0] for city in cities]

@dp.callback_query_handler(lambda c: c.data == 'skip_photo', state=UserState.AskForPhoto)
async def skip_photo_handler(callback_query: types.CallbackQuery, state: FSMContext):
    await done_add(callback_query, state)  # Переход к завершению добавления объявления


async def delete_ad_after_duration(ad_id, duration_in_seconds=60):
    await asyncio.sleep(duration_in_seconds)
    connection = None  # Инициализируем переменную заранее
    try:
        connection = sqlite3.connect('my_database.db')
        cursor = connection.cursor()
        cursor.execute("DELETE FROM advertisements WHERE id=?", (ad_id,))
        connection.commit()
    except Exception as e:
        print(f"Ошибка при удалении объявления с ID {ad_id}: {e}")
    finally:
        if connection:  # Проверяем, что соединение было успешно открыто
            connection.close()
    print(f"Объявление с ID {ad_id} удалено из базы данных")

@dp.callback_query_handler(lambda c: c.data == 'skip_photo', state=UserState.WaitForPhotos)
async def skip_photo_handler(callback_query: types.CallbackQuery, state: FSMContext):
    # Переход к завершению добавления объявления или к следующему шагу в зависимости от вашей логики
    await done_add(callback_query, state)

@dp.callback_query_handler(lambda c: c.data == 'done_z', state=UserState.WaitForPhotos)
async def done_add(callback_query: types.CallbackQuery, state: FSMContext):
    # Получаем данные из состояния
    async with state.proxy() as data:
        city = data['city']
        user_id = data.get('user_id')
        description = data['description']
        contact = data['contact']
        photos = data.get('photo', [])

    async with aiosqlite.connect('my_database.db') as db:
        # Определяем количество объявлений в базе
        async with db.execute("SELECT COUNT(*) FROM advertisements") as cursor:
            ads_count = (await cursor.fetchone())[0]

        expiration_duration = timedelta(days=14)  # Стандартный срок
        if ads_count < 500:  # Если объявлений меньше 500, устанавливаем срок в 2 месяца
            expiration_duration = timedelta(days=60)

        expiration_date = datetime.now() + expiration_duration
        try:
            # Вставляем новое объявление в базу данных с датой истечения срока
            cursor = await db.execute('''
                    INSERT INTO advertisements (user_id, city_id, description, contact, photos, published_at, expiration_date) 
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, city, description, contact, ','.join(photos) if isinstance(photos, list) else photos,
                      datetime.now(), expiration_date))
            await db.commit()

            ad_id = cursor.lastrowid  # Получаем ID только что вставленного объявления

            # Сообщаем пользователю о размещении объявления

            message_text = f"Ваше объявление с ID {ad_id}\n\nОписание: {description}\nКонтакт: {contact}\nВ городе: {city}"

            if photos:
                # Если у вас есть путь к фото, отправляем его как фото
                photo_path = photos[0] if isinstance(photos, list) else photos
                with open(photo_path, 'rb') as photo:
                    await bot.send_photo(callback_query.from_user.id, photo=photo, caption=message_text)
            else:
                await bot.send_message(callback_query.from_user.id, message_text)

            await bot.send_message(callback_query.from_user.id,
                                   f"Срок размещения объявления 14 дней, удачи в поисках!\n\nОбязательно нажмите кнопку назад, прежде чем переходить к другим командам",
                                   reply_markup=generate_clear_chat_button())

        except sqlite3.DatabaseError as e:
            await bot.send_message(callback_query.from_user.id, f"Произошла ошибка при сохранении объявления: {e}")
        finally:
            await db.close()

    # Завершаем текущее состояние
    await state.finish()
logging.basicConfig(level=logging.INFO)

# Глобальный обработчик для выхода из процесса создания объявлений
@dp.callback_query_handler(lambda c: True,
                           state=[UserState.AdDescription, UserState.WaitForContact, UserState.AskForPhoto,
                                  UserState.WaitForPhotos])
async def global_exit_handler(callback_query: types.CallbackQuery, state: FSMContext):
    # Список callback_data кнопок, которые используются в процессе создания объявлений
    allowed_callback_data = ['create_ad', 'add_photo', 'skip_photo', 'done_z']

    if callback_query.data not in allowed_callback_data:
        # Если callback_data не из списка разрешенных, завершаем состояние и сбрасываем данные
        await state.finish()  # Завершаем текущее состояние
        await callback_query.message.answer("Процесс создания объявления прерван. Ваши данные очищены.\n\n"
            "Пожалуйста, нажмите снова на кнопку, на которую хотели нажать, или начните процесс создания объявления заново.")

@dp.callback_query_handler(lambda c: c.data == 'view_ads', state='*')
async def view_ads(callback_query: types.CallbackQuery, state: FSMContext):
    await bot.answer_callback_query(callback_query.id)
    await update_last_activity(callback_query.from_user.id)
    state_data = await state.get_data()
    city = state_data.get('city')
    async with aiosqlite.connect('my_database.db') as db:
        cursor = await db.execute("SELECT id, description, contact, photos FROM advertisements WHERE city_id=? ORDER BY RANDOM()", (city,))
        ads = await cursor.fetchall()

    if not ads:
        # Если в выбранном городе нет объявлений
        await bot.send_message(
            callback_query.from_user.id,
            "В данном городе пока нет доступных объявлений.Разместите объявление первым!!!\n\nЕсли вы передумали и хотите прекратить действие,\nобязательно нажмите кнопку назад, прежде чем переходить к другим командам",
            reply_markup=generate_clear_chat_button()  # Предоставляем кнопку "Назад" для возврата к предыдущему выбору
        )
        return  # Останавливаем выполнение функции, чтобы не продолжать с send_ads_batch

    # Если есть объявления, продолжаем как обычно
    await state.set_data({'ads': ads, 'current_ad_index': 0})
    await send_ads_batch(callback_query.from_user.id, state)

async def show_ad(user_id, ad, state: FSMContext):
    ad_id, description, contact, photos = ad
    # Проверяем статус подписки пользователя
    async with aiosqlite.connect('my_database.db') as db:
        async with db.execute("SELECT plus FROM users WHERE id = ?", (user_id,)) as cursor:
            subscription_status = await cursor.fetchone()

    # Если подписка активна, показываем контакт, иначе - сообщение о необходимости подписки
    contact_info = contact if subscription_status and subscription_status[0] == 1 else "для просмотра контактов, необходимо\nприобрести подписку."

    message_text = f"Объявление ID: {ad_id}\nОписание: {description}\nКонтакт: {contact_info}"
    message = None

    if photos:
        photo_ids = photos.split(', ')
        photo_path = photo_ids[0].strip()
        if os.path.exists(photo_path):
            with open(photo_path, 'rb') as photo_file:
                message = await bot.send_photo(user_id, photo_file, caption=message_text)
        else:
            message = await bot.send_message(user_id, "Проблема с загрузкой изображения.")
    else:
        message = await bot.send_message(user_id, message_text)
async def send_ads_batch(user_id, state: FSMContext):
    await update_last_activity(user_id)
    user_data = await state.get_data()
    ads = user_data['ads']
    current_ad_index = user_data['current_ad_index']
    ads_to_send = ads[current_ad_index:current_ad_index+20]

    for ad in ads_to_send:
        await show_ad(user_id, ad, state)
        await asyncio.sleep(0.3)  # Для предотвращения флуда

    new_index = current_ad_index + 20
    await state.update_data(current_ad_index=new_index)

    # Если после этого есть еще объявления, показываем кнопку "Показать ещё"
    if new_index < len(ads):
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Показать ещё", callback_data="next_ad"))
        await bot.send_message(user_id, "Показать следующие объявления?", reply_markup=markup)
        await bot.send_message(user_id, "Нажмите назад чтобы вернуться в меню", reply_markup=generate_clear_chat_button())
    else:
        await bot.send_message(user_id, "Вы просмотрели все доступные объявления в этом городе.\n\nЕсли вы передумали и хотите прекратить действие,\nОбязательно нажмите кнопку назад, прежде чем переходить к другим командам", reply_markup=generate_clear_chat_button())

@dp.callback_query_handler(lambda c: c.data == 'next_ad', state='*')
async def next_ad(callback_query: types.CallbackQuery, state: FSMContext):
    await bot.answer_callback_query(callback_query.id)

    # Получаем текущее состояние
    data = await state.get_data()
    ads = data['ads']
    current_ad_index = data['current_ad_index']

    # Проверяем, достигли ли мы конца списка объявлений
    if current_ad_index >= len(ads):
        # Сбрасываем индекс, если достигли конца списка
        current_ad_index = 0
        await state.update_data(current_ad_index=current_ad_index)
        await bot.send_message(callback_query.from_user.id, "Вы просмотрели все доступные объявления. Начинаем снова.")

    # Продолжаем показ объявлений с текущего индекса
    await send_ads_batch(callback_query.from_user.id, state)

@dp.callback_query_handler(lambda c: c.data == 'oplata', state='*')
async def view_ads(callback_query: types.CallbackQuery, state: FSMContext):
    await bot.send_message(
        callback_query.from_user.id,
        "Стоимость подписки: 499 руб.\n\nПокупая подписку, Вы получаете:\n- доступ к размещению одного объявления;\n- доступ к контактам авторов объявлений сроком на 14 дней.",
        reply_markup=generate_oplata_button()
    )


@dp.errors_handler(exception=MessageNotModified)
async def message_not_modified_handler(update: types.Update, exception: MessageNotModified):
    # Логируем ошибку, если нужно
    logging.error(f"MessageNotModified: {exception}")

    # Пытаемся ответить пользователю, предлагая вернуться в главное меню
    try:
        if update.callback_query:
            chat_id = update.callback_query.from_user.id
        elif update.message:
            chat_id = update.message.chat.id
        else:
            return True  # Если не можем определить chat_id, просто выходим

        # Отправляем сообщение с предложением вернуться в главное меню
        await bot.send_message(chat_id, "Кажется, что-то пошло не так. Попробуйте вернуться в главное меню.",
                               reply_markup=generate_main_menu_markup())
    except Exception as e:
        logging.error(f"Error sending 'return to main menu' message: {e}")

    return True
@dp.callback_query_handler(lambda c: c.data == 'clear_chat')
async def clear_chat_callback(callback_query: types.CallbackQuery):
    keyboard = InlineKeyboardMarkup(row_width=2)
    button_subscribe = InlineKeyboardButton(text="Подписаться", url="https://t.me/SOVMESTNAYA_ARENDA_RU")
    button_continue = InlineKeyboardButton(text="Продолжить", callback_data='continue')

    keyboard.add(button_subscribe, button_continue)
    user_id = callback_query.from_user.id
    with open('main.jpg', 'rb') as photo:
        await bot.send_photo(user_id, photo, caption="Добро пожаловать в бота. Выберите, пожалуйста, действие.", reply_markup=keyboard)
    message_id = callback_query.message.message_id
    start_message_id = message_id
    end_message_id = max(1, start_message_id - 100)  # Предположим, что 1000 — достаточный лимит
    deleted_count = 0

    for msg_id in range(start_message_id, end_message_id, -1):
        try:
            await bot.delete_message(user_id, msg_id)
            deleted_count += 1
        except (MessageToDeleteNotFound, MessageCantBeDeleted, BadRequest):
            # Пропустить ошибки удаления
            continue

@dp.callback_query_handler(lambda c: c.data == 'clear_chat1')
async def clear_chat_callback1(callback_query: types.CallbackQuery):
    await update_last_activity(callback_query.from_user.id)
    keyboard = InlineKeyboardMarkup(row_width=2)
    button_subscribe = InlineKeyboardButton(text="Подписаться", url="https://t.me/SOVMESTNAYA_ARENDA_RU")
    button_continue = InlineKeyboardButton(text="Продолжить", callback_data='continue')

    keyboard.add(button_subscribe, button_continue)
    user_id = callback_query.from_user.id
    with open('main.jpg', 'rb') as photo:
        await bot.send_photo(user_id, photo, caption="Добро пожаловать в бота. Выберите, пожалуйста, действие.", reply_markup=keyboard)
    message_id = callback_query.message.message_id
    start_message_id = message_id
    end_message_id = max(1, start_message_id - 100)  # Предположим, что 1000 — достаточный лимит
    deleted_count = 0

    for msg_id in range(start_message_id, end_message_id, -1):
        try:
            await bot.delete_message(user_id, msg_id)
            deleted_count += 1
        except (MessageToDeleteNotFound, MessageCantBeDeleted, BadRequest):
            # Пропустить ошибки удаления
            continue
async def clear_chat(user_id, start_message_id):
    # Предположим, что мы хотим удалять сообщения начиная с start_message_id и до 100 сообщений назад
    end_message_id = max(1, start_message_id - 100)  # Устанавливаем предел в 100 сообщений назад
    deleted_count = 0

    # Проходим по диапазону сообщений и пытаемся их удалить
    for msg_id in range(start_message_id, end_message_id, -1):
        try:
            await bot.delete_message(user_id, msg_id)
            deleted_count += 1
        except (MessageToDeleteNotFound, MessageCantBeDeleted, BadRequest):
            # Пропустить ошибки удаления, продолжаем попытки удаления остальных сообщений
            continue

    # Отправляем сообщение о завершении очистки


user_payments = {}

# Данные терминала
YOUR_TERMINAL_KEY = "1710936568011"
YOUR_PASSWORD = "zhk96rqg1nud84lc"


def generate_token(data):
    sorted_data = dict(sorted(data.items()))
    concatenated_values = ''.join([str(value) for value in sorted_data.values()])
    return hashlib.sha256(concatenated_values.encode()).hexdigest()


async def create_payment(user_id):
    order_id = str(uuid.uuid4())
    amount = 49900  # Пример суммы в копейках для подарочной карты на 1000 рублей
    description = "Подписка"

    # Данные для генерации токена, включая Password
    data_for_token = {
        "Amount": str(amount),
        "OrderId": order_id,
        "Description": description,
        "Password": YOUR_PASSWORD,
        "TerminalKey": YOUR_TERMINAL_KEY
    }
    token = generate_token(data_for_token)

    # Данные для отправки в запросе
    data = {
        "TerminalKey": YOUR_TERMINAL_KEY,
        "Amount": amount,
        "OrderId": order_id,
        "Description": description,
        "Token": token,
        "DATA": {
            "Phone": "+71234567890",
            "Email": "a@test.com"
        },
        "Payments": {
            "Electronic": 49900,  # Сумма электронным платежом в копейках, должна совпадать с Amount
            "AdvancePayment": 0,
            "Credit": 0,
            "Provision": 0,
        },

        "Receipt": {
            "Email": "a@test.ru",
            "Phone": "+79031234567",
            "Taxation": "usn_income",
            "Items": [
                {
                    "Name": "Подписка",
                    "Price": 49900,
                    "Quantity": 1,
                    "Amount": 49900,
                    "Tax": "none",

                },
                # Добавьте здесь другие товары, если это необходимо
            ]

        }

    }



    # Отправка запроса
    # Отправка запроса
    async with ClientSession() as session:
        async with session.post("https://securepay.tinkoff.ru/v2/Init", json=data) as response:
            response_data = await response.json()
            if response_data.get("Success"):
                payment_info = {
                    "payment_id": response_data.get("PaymentId"),
                    "token": token  # Сохраняем использованный токен
                }
                user_payments[user_id] = payment_info
                return response_data
            else:
                return response_data


async def get_order_status(user_id):
    payment_info = user_payments.get(user_id)
    if not payment_info:
        return {"Error": "Платеж не найден."}

    payment_id = payment_info['payment_id']
    # Генерация токена для GetState
    data_for_token = {
        "TerminalKey": YOUR_TERMINAL_KEY,
        "PaymentId": payment_id,
        "Password": YOUR_PASSWORD
    }
    token = generate_token(data_for_token)

    data = {
        "TerminalKey": YOUR_TERMINAL_KEY,
        "PaymentId": payment_id,
        "Token": token,
    }

    url = "https://securepay.tinkoff.ru/v2/GetState"

    async with ClientSession() as session:
        async with session.post(url, json=data) as response:
            response_data = await response.json()
            if response.status == 200:
                print(f"Статус заказа: {response_data}")
                return response_data
            else:
                print("Ошибка запроса к API Тинькофф Кассы")
                return None




@dp.callback_query_handler(lambda c: c.data == 'buy')
async def process_buy_callback(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id

    # Проверяем, есть ли у пользователя активная подписка
    async with aiosqlite.connect('my_database.db') as db:
        async with db.execute("SELECT plus FROM users WHERE id = ?", (user_id,)) as cursor:
            result = await cursor.fetchone()
            if result and result[0] == 1:
                # Если у пользователя уже есть подписка
                await bot.send_message(user_id, "У вас уже есть активная подписка.")
                return

    # Если у пользователя нет активной подписки, продолжаем процесс покупки

    payment_response = await create_payment(user_id)
    if isinstance(payment_response, dict) and payment_response.get("Success"):
        payment_url = payment_response.get("PaymentURL")
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton("Оплатить", url=payment_url))
        markup.add(types.InlineKeyboardButton("Готово", callback_data=f"check_payment_{user_id}"))
        await bot.send_message(
            user_id,
            "Перейдите по ссылке для оплаты. После оплаты, пожалуйста, нажмите на кнопку 'Готово' ниже.",
            reply_markup=markup
        )
    else:
        await bot.send_message(user_id, "Произошла ошибка при создании платежа, попробуйте позже.")


@dp.callback_query_handler(lambda c: c.data.startswith('check_payment_'))
async def check_payment_callback(callback_query: types.CallbackQuery):
    user_id = int(callback_query.data.split('_')[-1])
    status_response = await get_order_status(user_id)

    if status_response and status_response.get("Success") and status_response.get("Status") == "CONFIRMED":
        await update_user_subscription(user_id, datetime.now(), 30)  # Предположим, подписка длится 30 дней
        await bot.send_message(user_id, "Оплата прошла успешно. Ваша подписка активирована.", reply_markup=generate_clear_chat_button())
    else:
        await bot.send_message(user_id, "Оплата не прошла, попробуйте снова.")



@dp.message_handler(commands=['subscription_status'])
async def subscription_status(message: types.Message):
    user_id = message.from_user.id

    async with aiosqlite.connect('my_database.db') as db:
        async with db.execute("SELECT subscription_end FROM users WHERE id = ?", (user_id,)) as cursor:
            result = await cursor.fetchone()

            if result and result[0]:
                subscription_end = datetime.strptime(result[0], "%Y-%m-%d %H:%M:%S")
                now = datetime.now()  # Исправлено здесь

                if subscription_end > now:
                    remaining_time = subscription_end - now
                    days, remainder = divmod(remaining_time.total_seconds(), 86400)
                    hours, remainder = divmod(remainder, 3600)
                    minutes, seconds = divmod(remainder, 60)
                    await message.reply(f"Ваша подписка активна. Осталось {int(days)} дней, {int(hours)} часов и {int(minutes)} минут.")
                else:
                    await message.reply("Ваша подписка истекла. Вы можете продлить её.")
            else:
                await message.reply("У вас нет активной подписки.")


async def reset_user_subscription(user_id: int):
    try:
        async with aiosqlite.connect('my_database.db') as db:
            await db.execute("UPDATE users SET plus = 0 WHERE id = ?", (user_id,))
            await db.commit()
        print(f"Подписка пользователя {user_id} истекла и была сброшена.")
    except Exception as e:
        print(f"Ошибка при сбросе подписки пользователя {user_id}: {e}")

async def update_user_subscription(user_id: int, subscription_start: datetime, subscription_duration: int):
    try:
        subscription_end = subscription_start + timedelta(minutes=subscription_duration)
        async with aiosqlite.connect('my_database.db') as db:
            await db.execute("UPDATE users SET plus = 1, subscription_start = ?, subscription_end = ? WHERE id = ?",
                            (subscription_start.strftime("%Y-%m-%d %H:%M:%S"),
                            subscription_end.strftime("%Y-%m-%d %H:%M:%S"), user_id))
            await db.commit()

        wait_seconds = (subscription_end - datetime.now()).total_seconds()
        if wait_seconds > 0:
            asyncio.create_task(sleep_and_reset(wait_seconds, user_id))
    except Exception as e:
        print(f"Ошибка при обновлении подписки пользователя {user_id}: {e}")


async def sleep_and_reset(wait_seconds: int, user_id: int):
    await asyncio.sleep(wait_seconds)
    await reset_user_subscription(user_id)
async def set_all_users_plus_status(status: int):
    try:
        async with aiosqlite.connect('my_database.db') as db:
            await db.execute("UPDATE users SET plus = ?", (status,))
            await db.commit()
        print(f"Статус 'plus' для всех пользователей обновлен на {status}.")
    except Exception as e:
        print(f"Ошибка при обновлении статуса 'plus' всех пользователей: {e}")

@dp.message_handler(commands=['krain8904'])
async def change_plus_status(message: types.Message):
    command_params = message.get_args().split()
    if not command_params or command_params[0] not in ['1', '0']:
        await message.reply("Пожалуйста, укажите корректный статус: 1 (активировать) или 0 (деактивировать). Например: /status 1")
        return

    new_status = int(command_params[0])

    await set_all_users_plus_status(new_status)
    await message.reply(f"Статус 'plus' для всех пользователей установлен на {new_status}.")

@dp.message_handler(commands=['addadmin'])
async def add_admin(message: types.Message):
    # Проверяем, является ли отправитель администратором
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("Извините, только администраторы могут добавлять других администраторов.")
        return

    # Извлекаем user_id из сообщения
    try:
        user_id_to_add = int(message.get_args())
    except ValueError:
        await message.reply("Пожалуйста, укажите корректный ID пользователя.")
        return

    # Проверяем, не является ли пользователь уже администратором
    if user_id_to_add in ADMIN_IDS:
        await message.reply("Этот пользователь уже является администратором.")
    else:
        ADMIN_IDS.append(user_id_to_add)
        await message.reply(f"Пользователь с ID {user_id_to_add} теперь администратор.")

user_actions = defaultdict(list)

async def track_user_action(user_id):
    now = datetime.now()
    user_actions[user_id].append(now)
    user_actions[user_id] = [action_time for action_time in user_actions[user_id] if now - action_time < timedelta(minutes=1)]
    if len(user_actions[user_id]) > 4:
        await reset_user_state(user_id)
        user_actions[user_id].clear()
        return True  # Индикатор того, что необходимо выполнить очистку чата
    return False  # Индикатор того, что очистка чата не требуется


async def reset_user_state(user_id):
    # Сбрасываем состояние пользователя и предлагаем вернуться в главное меню
    await dp.current_state(user=user_id).reset_state()
    await bot.send_message(user_id, "Вы совершили слишком много действий. Возвращаем вас в главное меню.",reply_markup=generate_main_menu_markup())
@dp.message_handler()
async def echo(message: Message):
    await update_last_activity(message.from_user.id)
    await message.answer(message.text)


@dp.callback_query_handler()
async def handle_callback_query(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id

    # Обновляем время последней активности пользователя
    await update_last_activity(user_id)

    # Отправляем сообщение с уведомлением и кнопкой перезапуска
    await bot.send_message(user_id,
                           "Вы были неактивны в течение последних 6 часов.\nНажмите на кнопку перезапустить ниже\nчтобы продолжить пользоваться функциями бота.",
                           reply_markup=restart_button())

    # Не забудьте уведомить Telegram, что callback был обработан
    await bot.answer_callback_query(callback_query.id)
async def on_startup(_):
    asyncio.create_task(check_inactivity())

# Точка входа в программу
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
