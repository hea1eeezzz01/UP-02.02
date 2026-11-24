"""Role-based, timed knowledge-testing web application."""
from __future__ import annotations

import io
import os
import random
import time
from functools import wraps
from pathlib import Path

from flask import (
    Flask, abort, flash, jsonify, redirect, render_template, request,
    send_file, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from database import close_db, get_db, init_db

BASE_DIR = Path(__file__).resolve().parent.parent
LETTERS = ("A", "B", "C", "D")
MAX_VIOLATIONS = 3


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Для продолжения войдите в систему.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def teacher_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if session.get("role") != "teacher":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def student_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if session.get("role") != "student":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-key-change-before-deployment"),
        DATABASE=os.environ.get("QUIZ_DATABASE", str(BASE_DIR / "instance" / "knowledge_testing.db")),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)

    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()

    @app.template_filter("duration")
    def duration_filter(seconds: int | None) -> str:
        value = max(0, int(seconds or 0))
        minutes, seconds_left = divmod(value, 60)
        if minutes:
            return f"{minutes} мин {seconds_left:02d} сек"
        return f"{seconds_left} сек"

    @app.template_filter("datetime_local")
    def datetime_filter(timestamp: int | None) -> str:
        if not timestamp:
            return "—"
        return time.strftime("%d.%m.%Y %H:%M", time.localtime(timestamp))

    @app.context_processor
    def inject_user():
        if session.get("user_id"):
            return {"current_user": {
                "id": session.get("user_id"),
                "full_name": session.get("full_name", ""),
                "role": session.get("role", "student"),
            }}
        return {"current_user": None}

    @app.get("/")
    def index():
        if session.get("user_id"):
            return redirect(url_for("teacher_dashboard" if session.get("role") == "teacher" else "student_dashboard"))
        return redirect(url_for("login"))

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            full_name = " ".join(request.form.get("full_name", "").split())[:100]
            username = request.form.get("username", "").strip().lower()[:40]
            password = request.form.get("password", "")
            if len(full_name) < 2 or len(username) < 3 or len(password) < 6:
                flash("Проверьте данные: имя от 2 символов, логин от 3, пароль от 6.", "error")
                return render_template("register.html")
            db = get_db()
            try:
                cursor = db.execute(
                    "INSERT INTO users (username,full_name,password_hash,role,created_at) VALUES (?,?,?,?,?)",
                    (username, full_name, generate_password_hash(password), "student", int(time.time())),
                )
                db.commit()
            except Exception:
                db.rollback()
                flash("Такой логин уже занят. Выберите другой.", "error")
                return render_template("register.html")
            session.clear()
            user = db.execute("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)).fetchone()
            _set_session_user(user)
            flash("Регистрация завершена. Добро пожаловать!", "success")
            return redirect(url_for("student_dashboard"))
        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip().lower()
            password = request.form.get("password", "")
            user = get_db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            if user is None or not check_password_hash(user["password_hash"], password):
                flash("Неверный логин или пароль.", "error")
                return render_template("login.html")
            session.clear()
            _set_session_user(user)
            return redirect(url_for("teacher_dashboard" if user["role"] == "teacher" else "student_dashboard"))
        return render_template("login.html")

    @app.post("/logout")
    @login_required
    def logout():
        session.clear()
        flash("Вы вышли из аккаунта.", "success")
        return redirect(url_for("login"))

    @app.get("/student")
    @student_required
    def student_dashboard():
        db = get_db()
        quizzes = db.execute(
            """SELECT q.*, COUNT(p.id) AS question_count
               FROM quizzes q LEFT JOIN questions p ON p.quiz_id=q.id
               WHERE q.is_active=1 GROUP BY q.id ORDER BY q.id"""
        ).fetchall()
        attempts = db.execute(
            """SELECT a.*, q.title FROM attempts a JOIN quizzes q ON q.id=a.quiz_id
               WHERE a.student_id=? AND a.status!='in_progress'
               ORDER BY a.finished_at DESC, a.id DESC LIMIT 10""",
            (session["user_id"],),
        ).fetchall()
        return render_template("student.html", quizzes=quizzes, attempts=attempts)

    @app.get("/teacher")
    @teacher_required
    def teacher_dashboard():
        db = get_db()
        results = db.execute(
            """SELECT a.*, q.title, u.full_name, u.username
               FROM attempts a JOIN quizzes q ON q.id=a.quiz_id
               JOIN users u ON u.id=a.student_id
               WHERE a.status!='in_progress'
               ORDER BY a.finished_at DESC, a.id DESC LIMIT 100"""
        ).fetchall()
        stats = db.execute(
            """SELECT COUNT(*) AS attempts,
                      COUNT(DISTINCT student_id) AS students,
                      ROUND(AVG(CASE WHEN total>0 THEN 100.0*score/total END)) AS average_score
               FROM attempts WHERE status!='in_progress'"""
        ).fetchone()
        difficult = _question_statistics(db)
        quizzes = db.execute(
            """SELECT q.*, u.full_name AS author,
                      COUNT(DISTINCT p.id) AS question_count
               FROM quizzes q LEFT JOIN users u ON u.id=q.created_by
               LEFT JOIN questions p ON p.quiz_id=q.id
               GROUP BY q.id ORDER BY q.id DESC"""
        ).fetchall()
        return render_template(
            "teacher.html", results=results, stats=stats,
            difficult=difficult, quizzes=quizzes,
        )

    @app.route("/teacher/quizzes/new", methods=["GET", "POST"])
    @teacher_required
    def create_quiz():
        if request.method == "POST":
            title = " ".join(request.form.get("title", "").split())[:120]
            description = " ".join(request.form.get("description", "").split())[:500]
            try:
                duration_minutes = int(request.form.get("duration_minutes", "10"))
            except (TypeError, ValueError):
                duration_minutes = 0

            question_texts = request.form.getlist("question_text")
            options_a = request.form.getlist("option_a")
            options_b = request.form.getlist("option_b")
            options_c = request.form.getlist("option_c")
            options_d = request.form.getlist("option_d")
            correct_options = request.form.getlist("correct_option")
            explanations = request.form.getlist("explanation")
            question_count = len(question_texts)

            errors = []
            if len(title) < 3:
                errors.append("Название теста должно содержать не менее 3 символов.")
            if len(description) < 5:
                errors.append("Добавьте краткое описание теста.")
            if not 1 <= duration_minutes <= 180:
                errors.append("Время прохождения должно быть от 1 до 180 минут.")
            if not 1 <= question_count <= 30:
                errors.append("В тесте должно быть от 1 до 30 вопросов.")
            if not all(len(items) == question_count for items in [options_a, options_b, options_c, options_d, correct_options, explanations]):
                errors.append("Не удалось прочитать все поля вопросов. Проверьте форму и попробуйте снова.")

            cleaned_questions = []
            if not errors:
                for index in range(question_count):
                    question_text = " ".join(question_texts[index].split())[:800]
                    options = [
                        " ".join(options_a[index].split())[:200],
                        " ".join(options_b[index].split())[:200],
                        " ".join(options_c[index].split())[:200],
                        " ".join(options_d[index].split())[:200],
                    ]
                    correct = correct_options[index].strip().upper()
                    explanation = " ".join(explanations[index].split())[:1000] or "Проверьте теорию по этой теме и повторите материал."
                    if len(question_text) < 5:
                        errors.append(f"Вопрос №{index + 1}: добавьте текст вопроса (не менее 5 символов).")
                    if any(len(option) < 1 for option in options):
                        errors.append(f"Вопрос №{index + 1}: заполните все четыре варианта ответа.")
                    if len({option.casefold() for option in options}) != 4:
                        errors.append(f"Вопрос №{index + 1}: варианты ответов должны отличаться друг от друга.")
                    if correct not in LETTERS:
                        errors.append(f"Вопрос №{index + 1}: выберите правильный вариант ответа.")
                    cleaned_questions.append((question_text, options, correct, explanation))

            if errors:
                for error in errors:
                    flash(error, "error")
                return render_template("quiz_create.html", form_data=request.form, question_count=min(30, max(1, question_count)))

            db = get_db()
            try:
                cursor = db.execute(
                    """INSERT INTO quizzes (title,description,duration_seconds,is_active,created_by)
                       VALUES (?,?,?,?,?)""",
                    (title, description, duration_minutes * 60,
                     1 if request.form.get("is_active") == "1" else 0,
                     session["user_id"]),
                )
                quiz_id = cursor.lastrowid
                for question_text, options, correct, explanation in cleaned_questions:
                    db.execute(
                        """INSERT INTO questions
                           (quiz_id,question_text,option_a,option_b,option_c,option_d,correct_option,explanation)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (quiz_id, question_text, *options, correct, explanation),
                    )
                db.commit()
            except Exception:
                db.rollback()
                app.logger.exception("Unable to create quiz")
                flash("Не удалось сохранить тест. Проверьте данные и попробуйте ещё раз.", "error")
                return render_template("quiz_create.html", form_data=request.form, question_count=min(30, max(1, question_count)))

            flash("Тест успешно создан и добавлен в каталог.", "success" if request.form.get("is_active") == "1" else "info")
            return redirect(url_for("teacher_dashboard"))

        return render_template("quiz_create.html", form_data={}, question_count=1)

    @app.post("/teacher/quizzes/<int:quiz_id>/toggle")
    @teacher_required
    def toggle_quiz(quiz_id: int):
        db = get_db()
        quiz = db.execute("SELECT id,is_active FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
        if quiz is None:
            abort(404)
        new_status = 0 if quiz["is_active"] else 1
        db.execute("UPDATE quizzes SET is_active=? WHERE id=?", (new_status, quiz_id))
        db.commit()
        flash("Тест опубликован." if new_status else "Тест снят с публикации.", "success" if new_status else "info")
        return redirect(url_for("teacher_dashboard"))

    @app.post("/start/<int:quiz_id>")
    @student_required
    def start_quiz(quiz_id: int):
        db = get_db()
        quiz = db.execute("SELECT * FROM quizzes WHERE id=? AND is_active=1", (quiz_id,)).fetchone()
        if quiz is None:
            abort(404)
        questions = db.execute("SELECT * FROM questions WHERE quiz_id=?", (quiz_id,)).fetchall()
        if not questions:
            flash("В выбранном тесте пока нет вопросов.", "warning")
            return redirect(url_for("student_dashboard"))

        random.shuffle(questions)
        now = int(time.time())
        attempt_id = db.execute(
            """INSERT INTO attempts (student_id,quiz_id,started_at,total)
               VALUES (?,?,?,?)""",
            (session["user_id"], quiz_id, now, len(questions)),
        ).lastrowid
        for question_position, question in enumerate(questions):
            db.execute(
                "INSERT INTO attempt_questions (attempt_id,question_id,position) VALUES (?,?,?)",
                (attempt_id, question["id"], question_position),
            )
            options = [
                ("A", question["option_a"]), ("B", question["option_b"]),
                ("C", question["option_c"]), ("D", question["option_d"]),
            ]
            random.shuffle(options)
            for option_position, (letter, option_text) in enumerate(options):
                db.execute(
                    """INSERT INTO attempt_options
                       (attempt_id,question_id,option_letter,option_text,position)
                       VALUES (?,?,?,?,?)""",
                    (attempt_id, question["id"], letter, option_text, option_position),
                )
        db.commit()
        return redirect(url_for("take_quiz", attempt_id=attempt_id))

    @app.get("/quiz/<int:attempt_id>")
    @student_required
    def take_quiz(attempt_id: int):
        db = get_db()
        attempt = _get_attempt(db, attempt_id)
        _ensure_owner(attempt)
        if attempt["status"] != "in_progress":
            return redirect(url_for("result", attempt_id=attempt_id))
        quiz = db.execute("SELECT * FROM quizzes WHERE id=?", (attempt["quiz_id"],)).fetchone()
        elapsed = max(0, int(time.time()) - attempt["started_at"])
        remaining = quiz["duration_seconds"] - elapsed
        if remaining <= 0:
            _finish_attempt(db, attempt, {}, final_status="time_expired", elapsed=elapsed)
            return redirect(url_for("result", attempt_id=attempt_id))

        question_rows = db.execute(
            """SELECT q.*, aq.position AS question_position
               FROM attempt_questions aq JOIN questions q ON q.id=aq.question_id
               WHERE aq.attempt_id=? ORDER BY aq.position""",
            (attempt_id,),
        ).fetchall()
        questions = []
        for question in question_rows:
            options = db.execute(
                """SELECT option_letter,option_text FROM attempt_options
                   WHERE attempt_id=? AND question_id=? ORDER BY position""",
                (attempt_id, question["id"]),
            ).fetchall()
            questions.append({
                "id": question["id"],
                "text": question["question_text"],
                "options": [
                    {"value": option["option_letter"], "label": option["option_text"], "display_letter": LETTERS[i]}
                    for i, option in enumerate(options)
                ],
            })
        return render_template("quiz.html", attempt=attempt, quiz=quiz, questions=questions, remaining=remaining)

    @app.post("/quiz/<int:attempt_id>/violation")
    @student_required
    def record_violation(attempt_id: int):
        db = get_db()
        attempt = _get_attempt(db, attempt_id)
        _ensure_owner(attempt)
        if attempt["status"] != "in_progress":
            return jsonify({"status": "closed", "redirect": url_for("result", attempt_id=attempt_id)})
        payload = request.get_json(silent=True) or {}
        event_type = str(payload.get("event_type", "focus_lost"))[:40]
        details = str(payload.get("details", ""))[:160]
        now = int(time.time())
        db.execute(
            "INSERT INTO violations (attempt_id,event_type,created_at,details) VALUES (?,?,?,?)",
            (attempt_id, event_type, now, details),
        )
        db.execute("UPDATE attempts SET violations=violations+1 WHERE id=?", (attempt_id,))
        db.commit()
        updated = db.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
        disqualified = updated["violations"] >= MAX_VIOLATIONS
        if disqualified:
            answers = payload.get("answers", {})
            submitted = _clean_submitted_answers(answers)
            elapsed = max(0, now - updated["started_at"])
            _finish_attempt(db, updated, submitted, final_status="disqualified", elapsed=elapsed)
        return jsonify({
            "violations": updated["violations"],
            "limit": MAX_VIOLATIONS,
            "disqualified": disqualified,
            "redirect": url_for("result", attempt_id=attempt_id) if disqualified else None,
        })

    @app.post("/quiz/<int:attempt_id>/submit")
    @student_required
    def submit_quiz(attempt_id: int):
        db = get_db()
        attempt = _get_attempt(db, attempt_id)
        _ensure_owner(attempt)
        if attempt["status"] != "in_progress":
            return redirect(url_for("result", attempt_id=attempt_id))
        submitted = _clean_submitted_answers(request.form)
        elapsed = max(0, int(time.time()) - attempt["started_at"])
        quiz = db.execute("SELECT duration_seconds FROM quizzes WHERE id=?", (attempt["quiz_id"],)).fetchone()
        status = "time_expired" if elapsed >= quiz["duration_seconds"] else "completed"
        _finish_attempt(db, attempt, submitted, final_status=status, elapsed=elapsed)
        return redirect(url_for("result", attempt_id=attempt_id))

    @app.get("/result/<int:attempt_id>")
    @login_required
    def result(attempt_id: int):
        db = get_db()
        attempt = _get_attempt(db, attempt_id)
        _check_attempt_access(attempt)
        if attempt["status"] == "in_progress":
            if session["role"] == "teacher":
                flash("Эта попытка ещё не завершена.", "info")
                return redirect(url_for("teacher_dashboard"))
            return redirect(url_for("take_quiz", attempt_id=attempt_id))
        review = _build_review(db, attempt_id)
        percent = round(100 * attempt["score"] / attempt["total"]) if attempt["total"] else 0
        return render_template("result.html", attempt=attempt, review=review, percent=percent)

    @app.get("/result/<int:attempt_id>/pdf")
    @login_required
    def export_result_pdf(attempt_id: int):
        db = get_db()
        attempt = _get_attempt(db, attempt_id)
        _check_attempt_access(attempt)
        if attempt["status"] == "in_progress":
            abort(400)
        try:
            pdf_bytes = _make_pdf(attempt, _build_review(db, attempt_id))
        except ImportError:
            app.logger.exception("PDF export dependencies are missing")
            flash("Не установлена библиотека для PDF. В терминале проекта выполните: python -m pip install -r requirements.txt", "error")
            return redirect(url_for("result", attempt_id=attempt_id))
        except Exception:
            app.logger.exception("Unable to create PDF for attempt %s", attempt_id)
            flash("Не удалось сформировать PDF. Проверьте установку зависимостей и наличие системного шрифта Arial, DejaVu Sans или Noto Sans.", "error")
            return redirect(url_for("result", attempt_id=attempt_id))

        if not pdf_bytes.startswith(b"%PDF"):
            app.logger.error("PDF generator returned an invalid document for attempt %s", attempt_id)
            abort(500, description="Не удалось сформировать корректный PDF-файл.")

        response = send_file(
            io.BytesIO(pdf_bytes), mimetype="application/pdf", as_attachment=True,
            download_name=f"result_{attempt_id}.pdf", conditional=False, max_age=0,
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health():
        return {"status": "ok", "app": "knowledge-testing-module"}

    return app


def _set_session_user(user) -> None:
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["full_name"] = user["full_name"]
    session["role"] = user["role"]


def _get_attempt(db, attempt_id: int):
    attempt = db.execute(
        """SELECT a.*, q.title, q.duration_seconds, u.full_name AS student_name, u.username
           FROM attempts a JOIN quizzes q ON q.id=a.quiz_id
           JOIN users u ON u.id=a.student_id WHERE a.id=?""",
        (attempt_id,),
    ).fetchone()
    if attempt is None:
        abort(404)
    return attempt


def _ensure_owner(attempt) -> None:
    if attempt["student_id"] != session.get("user_id"):
        abort(403)


def _check_attempt_access(attempt) -> None:
    if session.get("role") != "teacher" and attempt["student_id"] != session.get("user_id"):
        abort(403)


def _clean_submitted_answers(source) -> dict[int, str]:
    cleaned = {}
    try:
        items = source.items()
    except AttributeError:
        return cleaned
    for key, value in items:
        key = str(key)
        if key.startswith("q_") and str(value) in LETTERS:
            try:
                cleaned[int(key[2:])] = str(value)
            except ValueError:
                continue
    return cleaned


def _finish_attempt(db, attempt, submitted: dict[int, str], final_status: str, elapsed: int | None = None) -> None:
    """Grade answers against the immutable randomized snapshot and close once."""
    if attempt["status"] != "in_progress":
        return
    now = int(time.time())
    if elapsed is None:
        elapsed = max(0, now - attempt["started_at"])
    snapshot_questions = db.execute(
        """SELECT q.id,q.correct_option FROM attempt_questions aq
           JOIN questions q ON q.id=aq.question_id
           WHERE aq.attempt_id=? ORDER BY aq.position""",
        (attempt["id"],),
    ).fetchall()
    score = 0
    for question in snapshot_questions:
        question_id = question["id"]
        selected = submitted.get(question_id)
        allowed = db.execute(
            "SELECT 1 FROM attempt_options WHERE attempt_id=? AND question_id=? AND option_letter=?",
            (attempt["id"], question_id, selected),
        ).fetchone() if selected else None
        if not allowed:
            selected = None
        is_correct = int(selected is not None and selected == question["correct_option"])
        score += is_correct
        db.execute(
            """INSERT OR REPLACE INTO answers
               (attempt_id,question_id,selected_option,is_correct) VALUES (?,?,?,?)""",
            (attempt["id"], question_id, selected, is_correct),
        )
    db.execute(
        """UPDATE attempts SET finished_at=?,score=?,total=?,time_taken_seconds=?,status=?
           WHERE id=? AND status='in_progress'""",
        (now, score, len(snapshot_questions), elapsed, final_status, attempt["id"]),
    )
    db.commit()


def _build_review(db, attempt_id: int) -> list[dict]:
    rows = db.execute(
        """SELECT q.id,q.question_text,q.option_a,q.option_b,q.option_c,q.option_d,
                  q.correct_option,q.explanation,a.selected_option,a.is_correct
           FROM answers a JOIN questions q ON q.id=a.question_id
           JOIN attempt_questions aq ON aq.attempt_id=a.attempt_id AND aq.question_id=q.id
           WHERE a.attempt_id=? ORDER BY aq.position""",
        (attempt_id,),
    ).fetchall()
    review = []
    for row in rows:
        options = {"A": row["option_a"], "B": row["option_b"], "C": row["option_c"], "D": row["option_d"]}
        review.append({
            "question": row["question_text"],
            "selected": options.get(row["selected_option"], "Ответ не выбран"),
            "correct": options[row["correct_option"]],
            "is_correct": bool(row["is_correct"]),
            "explanation": row["explanation"],
        })
    return review


def _question_statistics(db) -> list[dict]:
    rows = db.execute(
        """SELECT q.id,q.question_text,z.title AS quiz_title,COUNT(a.id) AS answers_count,
                  SUM(CASE WHEN a.is_correct=1 THEN 1 ELSE 0 END) AS correct_count,
                  SUM(CASE WHEN a.is_correct=0 THEN 1 ELSE 0 END) AS wrong_count
           FROM questions q JOIN quizzes z ON z.id=q.quiz_id
           LEFT JOIN answers a ON a.question_id=q.id
           GROUP BY q.id ORDER BY
             CASE WHEN COUNT(a.id)=0 THEN 101 ELSE 100.0*SUM(CASE WHEN a.is_correct=1 THEN 1 ELSE 0 END)/COUNT(a.id) END ASC,
             COUNT(a.id) DESC LIMIT 30"""
    ).fetchall()
    data = []
    for row in rows:
        count = row["answers_count"] or 0
        accuracy = round((row["correct_count"] or 0) * 100 / count) if count else None
        if not count:
            label = "Пока нет данных"
        elif accuracy < 50:
            label = "Сложный вопрос"
        elif accuracy < 75:
            label = "Средняя сложность"
        else:
            label = "Лёгкий вопрос"
        data.append({**dict(row), "accuracy": accuracy, "difficulty": label})
    return data


def _make_pdf(attempt, review: list[dict]) -> bytes:
    """Generate a downloadable PDF report with Cyrillic-capable font when available."""
    from reportlab.lib import colors
    from xml.sax.saxutils import escape
    from reportlab.lib.enums import TA_LEFT, TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

    font_name = "Helvetica"
    bold_name = "Helvetica-Bold"
    windows_fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    font_candidates = [
        windows_fonts / "arial.ttf", windows_fonts / "segoeui.ttf",
        windows_fonts / "tahoma.ttf", windows_fonts / "calibri.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
        Path("/Library/Fonts/Arial.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    ]
    bold_candidates = [
        windows_fonts / "arialbd.ttf", windows_fonts / "segoeuib.ttf",
        windows_fonts / "tahomabd.ttf", windows_fonts / "calibrib.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"),
        Path("/Library/Fonts/Arial Bold.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ]
    regular_path = next((path for path in font_candidates if path.is_file()), None)
    bold_path = next((path for path in bold_candidates if path.is_file()), None)

    # ReportLab's built-in Helvetica does not contain Cyrillic glyphs. Use a
    # locally installed Unicode font whenever possible; never bundle font files.
    if regular_path is None:
        raise RuntimeError(
            "Не найден системный шрифт с поддержкой кириллицы. Установите Arial, DejaVu Sans или Noto Sans."
        )
    try:
        pdfmetrics.registerFont(TTFont("AppFont", str(regular_path)))
        font_name = "AppFont"
        if bold_path is not None:
            pdfmetrics.registerFont(TTFont("AppFont-Bold", str(bold_path)))
            bold_name = "AppFont-Bold"
        else:
            bold_name = font_name
    except Exception as exc:
        raise RuntimeError("Не удалось подключить системный шрифт для PDF.") from exc

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm, topMargin=16*mm, bottomMargin=16*mm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="AppTitle", parent=styles["Title"], fontName=bold_name, fontSize=18, leading=22, alignment=TA_LEFT, textColor=colors.HexColor("#17243b"), spaceAfter=8))
    styles.add(ParagraphStyle(name="AppBody", parent=styles["BodyText"], fontName=font_name, fontSize=9, leading=13, spaceAfter=3))
    styles.add(ParagraphStyle(name="AppSmall", parent=styles["BodyText"], fontName=font_name, fontSize=8, leading=11))
    styles.add(ParagraphStyle(name="AppHeading", parent=styles["Heading2"], fontName=bold_name, fontSize=11, leading=14, spaceBefore=8, spaceAfter=5))

    percent = round(100 * attempt["score"] / attempt["total"]) if attempt["total"] else 0
    status_names = {"completed": "Завершён", "time_expired": "Время истекло", "disqualified": "Завершён из-за нарушений"}
    story = [
        Paragraph("Результат тестирования", styles["AppTitle"]),
        Paragraph(f"Тест: {escape(attempt['title'])}", styles["AppBody"]),
        Paragraph(f"Студент: {escape(attempt['student_name'])}", styles["AppBody"]),
        Paragraph(f"Результат: {attempt['score']} из {attempt['total']} ({percent}%)", styles["AppBody"]),
        Paragraph(f"Статус: {status_names.get(attempt['status'], attempt['status'])}", styles["AppBody"]),
        Paragraph(f"Затраченное время: {int(attempt['time_taken_seconds']) // 60} мин {int(attempt['time_taken_seconds']) % 60} сек", styles["AppBody"]),
        Paragraph(f"Нарушения: {attempt['violations']}", styles["AppBody"]),
        Spacer(1, 6*mm),
        Paragraph("Разбор ответов", styles["AppHeading"]),
    ]
    for index, item in enumerate(review, start=1):
        color = "#16734a" if item["is_correct"] else "#b42318"
        story.append(KeepTogether([
            Paragraph(f"{index}. {escape(item['question'])}", styles["AppBody"]),
            Paragraph(f"Ваш ответ: {escape(item['selected'])}", styles["AppSmall"]),
            Paragraph(f"Правильный ответ: {escape(item['correct'])}", styles["AppSmall"]),
            Paragraph(f"Пояснение: {escape(item['explanation'])}", styles["AppSmall"]),
            Spacer(1, 3*mm),
        ]))
    doc.build(story)
    return buffer.getvalue()


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
