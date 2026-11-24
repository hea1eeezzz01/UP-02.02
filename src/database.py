"""SQLite storage, role accounts, seeded quizzes, and attempt snapshots."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from flask import current_app, g
from werkzeug.security import generate_password_hash


QUIZ_DATA = [
    {
        "title": "Основы Python",
        "description": "Переменные, типы данных, условия, циклы и функции.",
        "duration_minutes": 10,
        "questions": [
            ("Какой тип данных хранит целое число в Python?", ["str", "int", "float", "bool"], "B", "Тип int предназначен для целых чисел."),
            ("Какой оператор сравнивает два значения на равенство?", ["=", "!=", "==", ">="], "C", "Оператор == сравнивает значения, а = присваивает значение."),
            ("Какой результат вернёт выражение len('кот')?", ["2", "3", "4", "Ошибка"], "B", "В строке «кот» три символа, поэтому len() вернёт 3."),
            ("Какое ключевое слово используется для объявления функции?", ["func", "define", "function", "def"], "D", "Функции в Python объявляются с помощью ключевого слова def."),
            ("Что выведет выражение print(2 + 3 * 2)?", ["10", "12", "8", "7"], "C", "Сначала выполняется умножение: 2 + 6 = 8."),
        ],
    },
    {
        "title": "HTML и CSS",
        "description": "Структура веб-страниц, HTML-теги и оформление интерфейса.",
        "duration_minutes": 10,
        "questions": [
            ("Для чего обычно используется HTML?", ["Для структуры страницы", "Для хранения данных SQL", "Для настройки сервера", "Для управления Git"], "A", "HTML задаёт структуру и семантику содержимого страницы."),
            ("Какая технология отвечает за внешний вид веб-страницы?", ["Python", "CSS", "SQLite", "HTTP"], "B", "CSS задаёт цвета, размеры, расположение элементов и другие стили."),
            ("Какой тег создаёт гиперссылку?", ["<img>", "<p>", "<a>", "<div>"], "C", "Тег <a> создаёт гиперссылку; адрес указывается в href."),
            ("Какой атрибут img содержит путь к изображению?", ["href", "alt", "class", "src"], "D", "Атрибут src задаёт источник изображения."),
            ("Как в CSS обратиться к элементу с id=menu?", [".menu", "#menu", "menu()", "@menu"], "B", "Селектор #menu выбирает элемент по идентификатору."),
        ],
    },
    {
        "title": "JavaScript",
        "description": "Переменные, функции, события и работа с DOM.",
        "duration_minutes": 10,
        "questions": [
            ("Какое ключевое слово объявляет переменную с блочной областью видимости?", ["var", "let", "define", "dim"], "B", "let объявляет переменную с блочной областью видимости."),
            ("Как получить элемент по идентификатору в DOM?", ["document.getElementById()", "document.getClass()", "window.findId()", "html.get()"], "A", "Метод document.getElementById() ищет элемент по значению id."),
            ("Какой оператор строго сравнивает значение и тип?", ["=", "==", "===", "<>"], "C", "Оператор === сравнивает и значение, и тип без приведения типов."),
            ("Какое событие возникает при нажатии кнопки мыши?", ["hover", "change", "load", "click"], "D", "Событие click срабатывает при щелчке по элементу."),
            ("Что возвращает JSON.parse()?", ["Строку JSON без изменений", "JavaScript-значение из JSON-строки", "HTML-документ", "HTTP-ответ"], "B", "JSON.parse() разбирает JSON-строку и возвращает соответствующее JavaScript-значение."),
        ],
    },
    {
        "title": "Основы SQL и баз данных",
        "description": "Таблицы, выборка, добавление и связи данных.",
        "duration_minutes": 10,
        "questions": [
            ("Какой SQL-оператор выбирает данные из таблицы?", ["SELECT", "INSERT", "UPDATE", "DELETE"], "A", "SELECT используется для выборки данных."),
            ("Как добавить новую запись в таблицу?", ["SELECT INTO", "INSERT INTO", "ALTER ROW", "CREATE COLUMN"], "B", "INSERT INTO добавляет строки в таблицу."),
            ("Какое ограничение обычно задаёт уникальный идентификатор строки?", ["FOREIGN KEY", "DEFAULT", "PRIMARY KEY", "CHECK"], "C", "PRIMARY KEY однозначно идентифицирует запись в таблице."),
            ("Как отфильтровать строки по условию?", ["ORDER BY", "GROUP BY", "LIMIT", "WHERE"], "D", "WHERE задаёт условие отбора строк."),
            ("Для чего нужен FOREIGN KEY?", ["Для шифрования пароля", "Для связи таблиц и контроля ссылочной целостности", "Для сортировки строк", "Для резервного копирования"], "B", "Внешний ключ связывает запись с ключом другой таблицы и поддерживает ссылочную целостность."),
        ],
    },
    {
        "title": "Git и командная разработка",
        "description": "Коммиты, ветки, репозитории и Kanban-доска из задания практики.",
        "duration_minutes": 10,
        "questions": [
            ("Для чего используется Git?", ["Для контроля версий", "Для оформления CSS", "Для запуска SQL-запросов", "Для создания презентаций"], "A", "Git сохраняет историю изменений и помогает вести совместную разработку."),
            ("Что обычно содержит коммит?", ["Только имя пользователя", "Зафиксированный набор изменений", "Список открытых вкладок", "Только резервную копию БД"], "B", "Коммит фиксирует набор изменений в истории репозитория."),
            ("Зачем создают отдельную feature-ветку?", ["Чтобы удалить историю", "Чтобы отключить тесты", "Чтобы разрабатывать функцию отдельно от основной ветки", "Чтобы заменить Git сервером"], "C", "Отдельная ветка изолирует разработку функции до объединения изменений."),
            ("Какая колонка Kanban означает, что задача завершена?", ["Backlog", "In Progress", "Review", "Done"], "D", "Done содержит задачи, выполнение которых завершено."),
            ("Что обычно указывают в README.md?", ["Описание проекта и инструкцию по запуску", "Пароли всех пользователей", "Историю браузера", "Только скомпилированные файлы"], "A", "README.md описывает назначение проекта, требования и запуск."),
        ],
    },
    {
        "title": "Python Flask и HTTP",
        "description": "Маршруты Flask, HTTP-запросы и ответы веб-сервера.",
        "duration_minutes": 10,
        "questions": [
            ("Для чего во Flask используется декоратор @app.route?", ["Для создания таблицы БД", "Для связывания URL с функцией-обработчиком", "Для хеширования пароля", "Для запуска JavaScript"], "B", "@app.route связывает URL и функцию, которая обрабатывает запрос."),
            ("Какой HTTP-метод обычно используют для получения данных?", ["DELETE", "PATCH", "POST", "GET"], "D", "GET предназначен для получения ресурса или данных."),
            ("Что обычно означает HTTP-статус 404?", ["Успешный запрос", "Ошибка сервера", "Ресурс не найден", "Переадресация"], "C", "Код 404 Not Found означает, что запрошенный ресурс не найден."),
            ("Что такое маршрут (route) веб-приложения?", ["Путь URL и обработчик запроса", "Только строка CSS", "Файл изображения", "Запись в журнале ОС"], "A", "Маршрут определяет адрес и функцию, которая обрабатывает запрос к нему."),
            ("Для чего применяется session во Flask?", ["Для хранения состояния пользователя между запросами", "Для компиляции Python", "Для настройки CSS", "Для создания Git-коммита"], "A", "Сессия позволяет хранить данные пользователя между HTTP-запросами."),
        ],
    },
]


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        db_path = Path(current_app.config["DATABASE"])
        db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        g.db = connection
    return g.db


def close_db(_error=None) -> None:
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_db() -> None:
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            full_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('student','teacher')),
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS quizzes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            duration_seconds INTEGER NOT NULL CHECK(duration_seconds > 0),
            is_active INTEGER NOT NULL DEFAULT 1,
            created_by INTEGER REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_id INTEGER NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
            question_text TEXT NOT NULL,
            option_a TEXT NOT NULL,
            option_b TEXT NOT NULL,
            option_c TEXT NOT NULL,
            option_d TEXT NOT NULL,
            correct_option TEXT NOT NULL CHECK(correct_option IN ('A','B','C','D')),
            explanation TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES users(id),
            quiz_id INTEGER NOT NULL REFERENCES quizzes(id),
            started_at INTEGER NOT NULL,
            finished_at INTEGER,
            score INTEGER NOT NULL DEFAULT 0,
            total INTEGER NOT NULL DEFAULT 0,
            time_taken_seconds INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'in_progress'
                CHECK(status IN ('in_progress','completed','time_expired','disqualified')),
            violations INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS attempt_questions (
            attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
            question_id INTEGER NOT NULL REFERENCES questions(id),
            position INTEGER NOT NULL,
            PRIMARY KEY(attempt_id, question_id),
            UNIQUE(attempt_id, position)
        );
        CREATE TABLE IF NOT EXISTS attempt_options (
            attempt_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            option_letter TEXT NOT NULL CHECK(option_letter IN ('A','B','C','D')),
            option_text TEXT NOT NULL,
            position INTEGER NOT NULL,
            PRIMARY KEY(attempt_id, question_id, option_letter),
            UNIQUE(attempt_id, question_id, position),
            FOREIGN KEY(attempt_id, question_id)
                REFERENCES attempt_questions(attempt_id, question_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
            question_id INTEGER NOT NULL REFERENCES questions(id),
            selected_option TEXT CHECK(selected_option IN ('A','B','C','D') OR selected_option IS NULL),
            is_correct INTEGER NOT NULL DEFAULT 0,
            UNIQUE(attempt_id, question_id)
        );
        CREATE TABLE IF NOT EXISTS violations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            details TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_attempts_student ON attempts(student_id, started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_attempts_status ON attempts(status);
        CREATE INDEX IF NOT EXISTS idx_questions_quiz ON questions(quiz_id);
        CREATE INDEX IF NOT EXISTS idx_answers_question ON answers(question_id);
        """
    )

    # Migrate databases created by earlier project versions.
    quiz_columns = {row["name"] for row in db.execute("PRAGMA table_info(quizzes)").fetchall()}
    if "created_by" not in quiz_columns:
        db.execute("ALTER TABLE quizzes ADD COLUMN created_by INTEGER REFERENCES users(id)")

    # Seed demo accounts on every startup when they are missing.
    demo_accounts = [
        ("teacher", "Преподаватель", "teacher123", "teacher"),
        ("student", "Демонстрационный Студент", "student123", "student"),
    ]
    for username, full_name, password, role in demo_accounts:
        exists = db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone()
        if not exists:
            db.execute(
                "INSERT INTO users (username,full_name,password_hash,role,created_at) VALUES (?,?,?,?,?)",
                (username, full_name, generate_password_hash(password), role, int(time.time())),
            )

    if db.execute("SELECT COUNT(*) FROM quizzes").fetchone()[0] == 0:
        for item in QUIZ_DATA:
            quiz_id = db.execute(
                "INSERT INTO quizzes (title,description,duration_seconds) VALUES (?,?,?)",
                (item["title"], item["description"], item["duration_minutes"] * 60),
            ).lastrowid
            for question_text, options, correct, explanation in item["questions"]:
                db.execute(
                    """INSERT INTO questions
                       (quiz_id,question_text,option_a,option_b,option_c,option_d,correct_option,explanation)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (quiz_id, question_text, *options, correct, explanation),
                )
    db.commit()
