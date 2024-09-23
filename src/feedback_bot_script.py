import os
import asyncio
import gspread
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from oauth2client.service_account import ServiceAccountCredentials
from aiogram.filters import StateFilter
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

API_TOKEN = os.getenv("API_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# Инициализация бота и диспетчера
storage = MemoryStorage()
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=storage)

# Настройка доступа к Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)

# Открываем Google таблицу по ID
sheet = client.open_by_key(os.getenv("GOOGLE_SHEET_ID")).sheet1

# Определяем состояния для FSM
class SurveyStates(StatesGroup):
    add_question = State()  # Состояние для добавления вопроса
    delete_question = State()  # Состояние для удаления вопроса
    answering = State()  # Состояние для ответа на вопросы


# Хранение вопросов
questions = []

# Загрузка вопросов из файла
def load_questions():
    try:
        with open("questions.txt", "r", encoding='utf-8') as file:
            return [line.strip() for line in file.readlines()]
    except FileNotFoundError:
        return []

# Сохранение вопросов в файл
def save_questions():
    with open("questions.txt", "w", encoding='utf-8') as file:
        for question in questions:
            file.write(f"{question}\n")

# Инициализация вопросов при старте
questions = load_questions()

# Админская панель
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("Админ-панель:\n"
                             "/add_question - Добавить вопрос\n"
                             "/delete_question - Удалить вопрос\n"
                             "/show_questions - Показать вопросы")
    else:
        await message.answer("У вас нет доступа к этой команде.")

# Добавление вопроса
@dp.message(Command('add_question'))
async def add_question(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        new_state = FSMContext(storage, key=StorageKey(bot.id, message.chat.id, message.from_user.id))
        await message.answer("Отправьте текст нового вопроса.")
        await new_state.set_state(SurveyStates.add_question)

# Получение нового вопроса и сохранение его в список
@dp.message(StateFilter(SurveyStates.add_question))
async def process_add_question(message: types.Message):
    new_state = FSMContext(storage, key=StorageKey(bot.id, message.chat.id, message.from_user.id))
    questions.append(message.text)
    save_questions()
    await message.answer(f"Вопрос добавлен: {message.text}")
    await new_state.clear()

# Удаление вопроса
@dp.message(Command('delete_question'))
async def delete_question(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        new_state = FSMContext(storage, key=StorageKey(bot.id, message.chat.id, message.from_user.id))
        if not questions:
            await message.answer("Список вопросов пуст.")
        else:
            question_list = "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))
            await message.answer(f"Выберите номер вопроса для удаления:\n{question_list}")
            await new_state.set_state(SurveyStates.delete_question)

# Удаление вопроса по номеру
@dp.message(StateFilter(SurveyStates.delete_question))
async def process_delete_question(message: types.Message):
    new_state = FSMContext(storage, key=StorageKey(bot.id, message.chat.id, message.from_user.id))
    try:
        index = int(message.text) - 1
        if 0 <= index < len(questions):
            removed_question = questions.pop(index)
            save_questions()
            await message.answer(f"Вопрос удален: {removed_question}")
        else:
            await message.answer("Некорректный номер вопроса.")
    except ValueError:
        await message.answer("Пожалуйста, введите корректный номер.")
    await new_state.clear()

# Показать все вопросы
@dp.message(Command('show_questions'))
async def show_questions(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        if not questions:
            await message.answer("Список вопросов пуст.")
        else:
            question_list = "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))
            await message.answer(f"Текущие вопросы:\n{question_list}")

# Начало опроса для пользователей
@dp.message(Command('start'))
async def start_survey(message: types.Message):
    new_state = FSMContext(storage, key=StorageKey(bot.id, message.chat.id, message.from_user.id))
    if not questions:
        await message.answer("Опросник пока пуст. Приходите позже.")
    else:
        await new_state.set_state(SurveyStates.answering)
        await message.answer(questions[0])
        await new_state.update_data(current_question=0, answers=[])

# Обработка ответов
@dp.message(StateFilter(SurveyStates.answering))
async def process_answer(message: types.Message):
    new_state = FSMContext(storage, key=StorageKey(bot.id, message.chat.id, message.from_user.id))
    data = await new_state.get_data()
    current_question = data.get('current_question', 0)
    answers = data.get('answers', [])

    # Сохраняем ответ
    answers.append(message.text)
    await new_state.update_data(answers=answers)

    # Если есть еще вопросы, задаем следующий
    if current_question + 1 < len(questions):
        next_question = questions[current_question + 1]
        await message.answer(next_question)
        await new_state.update_data(current_question=current_question + 1)
    else:
        # Если вопросы закончились, сохраняем ответы
        row = [str(message.from_user.id)] + answers
        sheet.append_row(row)
        await message.answer("Спасибо за прохождение опроса!")
        await new_state.clear()

async def main():
    await dp.start_polling(bot, skip_updates=True)

if __name__ == '__main__':
    asyncio.run(main())

