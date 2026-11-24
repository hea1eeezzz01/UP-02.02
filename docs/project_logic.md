# Анализ и бизнес-логика проекта

## 1. Назначение

«Модуль тестирования знаний с таймером и сохранением результатов» предназначен для проведения учебных тестов. Студент выбирает тест, отвечает на вопросы в ограниченное время и получает результат. Преподаватель просматривает результаты студентов и анализирует вопросы, вызывающие наибольшие затруднения.

## 2. Роли пользователей

| Роль | Возможности |
|---|---|
| Студент | Регистрация, вход, просмотр тестов, прохождение тестов, история и PDF собственных результатов |
| Преподаватель | Создание и публикация тестов, просмотр результатов всех студентов, подробный разбор попыток, статистика сложных вопросов, экспорт PDF |

## 3. Основные бизнес-процессы

1. Пользователь проходит авторизацию. Незарегистрированный студент создаёт аккаунт.
2. Преподаватель создаёт тест: указывает название, описание, время, добавляет вопросы, четыре варианта ответа, правильный ответ и пояснение; затем публикует тест или сохраняет черновиком.
3. Студент выбирает опубликованный тест.
4. Сервер создаёт попытку, случайно перемешивает вопросы и варианты и сохраняет их порядок в базе.
5. Студент отвечает на вопросы. JavaScript отображает обратный отсчёт и состояние заполнения.
6. Система фиксирует уход со страницы, потерю фокуса окна и выход из полноэкранного режима. После трёх событий попытка закрывается со статусом нарушения.
7. При отправке или завершении времени сервер проверяет ответы, считает баллы и сохраняет результат.
8. Студент просматривает собственный результат и скачивает PDF.
9. Преподаватель просматривает результаты группы и статистику правильных/неправильных ответов по каждому вопросу.

## 4. UML-диаграмма вариантов использования

```mermaid
flowchart LR
    Student[Студент]
    Teacher[Преподаватель]
    subgraph System[Модуль тестирования знаний]
      A((Регистрация и вход))
      B((Просмотр каталога тестов))
      C((Прохождение теста с таймером))
      D((Просмотр личных результатов))
      E((Экспорт результата в PDF))
      F((Просмотр результатов группы))
      G((Анализ сложных вопросов))
      H((Экспорт результата студента в PDF))
      I((Контроль переключения вкладок))
      J((Создание теста и вопросов))
      K((Публикация и снятие теста с публикации))
    end
    Student --> A
    Student --> B
    Student --> C
    Student --> D
    Student --> E
    Student --> I
    Teacher --> A
    Teacher --> F
    Teacher --> G
    Teacher --> H
    Teacher --> J
    Teacher --> K
```

## 5. UML-диаграмма последовательности прохождения теста

```mermaid
sequenceDiagram
    actor Student as Студент
    participant Browser as Браузер
    participant Flask as Flask-сервер
    participant DB as SQLite
    Student->>Browser: Выбирает тест
    Browser->>Flask: POST /start/{id}
    Flask->>DB: Создать попытку
    Flask->>DB: Сохранить случайный порядок вопросов и ответов
    Flask-->>Browser: Страница теста и оставшееся время
    loop Прохождение теста
      Student->>Browser: Выбирает ответы
      Browser->>Browser: Обновляет таймер и прогресс
      opt Потеря фокуса / вкладка скрыта
        Browser->>Flask: POST /quiz/{id}/violation
        Flask->>DB: Записать событие нарушения
      end
    end
    Browser->>Flask: POST /quiz/{id}/submit
    Flask->>DB: Проверить и сохранить ответы
    Flask->>DB: Сохранить баллы и статус
    Flask-->>Browser: Страница результата
    Student->>Browser: Запрашивает PDF
    Browser->>Flask: GET /result/{id}/pdf
    Flask-->>Browser: PDF-файл
```

## 6. ER-диаграмма базы данных

```mermaid
erDiagram
    USERS ||--o{ ATTEMPTS : проходит
    USERS ||--o{ QUIZZES : создаёт
    QUIZZES ||--o{ QUESTIONS : содержит
    QUIZZES ||--o{ ATTEMPTS : проверяется
    ATTEMPTS ||--o{ ATTEMPT_QUESTIONS : фиксирует
    QUESTIONS ||--o{ ATTEMPT_QUESTIONS : включается
    ATTEMPT_QUESTIONS ||--o{ ATTEMPT_OPTIONS : содержит
    ATTEMPTS ||--o{ ANSWERS : сохраняет
    QUESTIONS ||--o{ ANSWERS : получает
    ATTEMPTS ||--o{ VIOLATIONS : регистрирует
    USERS {
      int id PK
      string username UK
      string full_name
      string password_hash
      string role
      int created_at
    }
    QUIZZES {
      int id PK
      string title
      string description
      int duration_seconds
      int is_active
      int created_by FK
    }
    QUESTIONS {
      int id PK
      int quiz_id FK
      string question_text
      string option_a
      string option_b
      string option_c
      string option_d
      string correct_option
      string explanation
    }
    ATTEMPTS {
      int id PK
      int student_id FK
      int quiz_id FK
      int started_at
      int finished_at
      int score
      int total
      int time_taken_seconds
      string status
      int violations
    }
    ATTEMPT_QUESTIONS {
      int attempt_id PK,FK
      int question_id PK,FK
      int position
    }
    ATTEMPT_OPTIONS {
      int attempt_id PK,FK
      int question_id PK,FK
      string option_letter PK
      string option_text
      int position
    }
    ANSWERS {
      int id PK
      int attempt_id FK
      int question_id FK
      string selected_option
      int is_correct
    }
    VIOLATIONS {
      int id PK
      int attempt_id FK
      string event_type
      int created_at
      string details
    }
```

## 7. Статистика сложности

Сложность рассчитывается по доле правильных ответов на вопрос:
- менее 50% — сложный вопрос;
- от 50% до 74% — средняя сложность;
- 75% и выше — лёгкий вопрос.

Если ответов ещё нет, выводится статус «Пока нет данных».

## 8. Ограничение защиты от списывания

Браузер предоставляет события видимости страницы, потери фокуса и полноэкранного режима, но не даёт обычному сайту абсолютного запрета на переключение вкладок. В проекте используется обнаружение и журналирование этих событий, а также автоматическое завершение попытки после трёх нарушений.
