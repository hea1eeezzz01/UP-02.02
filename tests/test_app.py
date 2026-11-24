"""Functional tests for authentication, RBAC, attempts, and anti-cheat controls."""
import os
import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app import create_app
from database import get_db


class KnowledgeTestingAppTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test.sqlite3")
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DATABASE": self.db_path,
        })
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def register_student(self, username="student1"):
        return self.client.post("/register", data={
            "full_name": "Тестовый Студент",
            "username": username,
            "password": "student123",
        }, follow_redirects=True)

    def start_first_quiz(self):
        with self.app.app_context():
            quiz_id = get_db().execute("SELECT id FROM quizzes ORDER BY id LIMIT 1").fetchone()[0]
        response = self.client.post(f"/start/{quiz_id}")
        self.assertEqual(response.status_code, 302)
        return int(response.headers["Location"].rsplit("/", 1)[-1])

    def test_six_quizzes_are_seeded(self):
        with self.app.app_context():
            db = get_db()
            quizzes = db.execute("SELECT COUNT(*) FROM quizzes").fetchone()[0]
            questions = db.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
        self.assertEqual(quizzes, 6)
        self.assertEqual(questions, 30)

    def test_student_registration_and_dashboard(self):
        response = self.register_student()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Доступные тесты".encode(), response.data)
        self.assertIn("Основы Python".encode(), response.data)

    def test_student_cannot_open_teacher_dashboard(self):
        self.register_student()
        response = self.client.get("/teacher")
        self.assertEqual(response.status_code, 403)

    def test_teacher_login_and_dashboard(self):
        response = self.client.post("/login", data={
            "username": "teacher", "password": "teacher123"
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Панель преподавателя".encode(), response.data)
        self.assertIn("Статистика по вопросам".encode(), response.data)

    def test_attempt_randomized_snapshot_is_saved(self):
        self.register_student()
        attempt_id = self.start_first_quiz()
        with self.app.app_context():
            db = get_db()
            question_count = db.execute(
                "SELECT COUNT(*) FROM attempt_questions WHERE attempt_id=?", (attempt_id,)
            ).fetchone()[0]
            option_count = db.execute(
                "SELECT COUNT(*) FROM attempt_options WHERE attempt_id=?", (attempt_id,)
            ).fetchone()[0]
            positions = db.execute(
                "SELECT position FROM attempt_questions WHERE attempt_id=? ORDER BY position", (attempt_id,)
            ).fetchall()
        self.assertEqual(question_count, 5)
        self.assertEqual(option_count, 20)
        self.assertEqual([row[0] for row in positions], [0, 1, 2, 3, 4])

    
    def test_three_focus_violations_disqualify_attempt(self):
        self.register_student()
        attempt_id = self.start_first_quiz()

        for violation_number in range(1, 4):
            response = self.client.post(
                f"/quiz/{attempt_id}/violation",
                json={"event_type": "tab_hidden", "answers": {}},
            )
            self.assertEqual(response.status_code, 200)

            data = response.get_json()
            self.assertEqual(data["violations"], violation_number)
            self.assertEqual(data["limit"], 3)

            if violation_number < 3:
                self.assertFalse(data["disqualified"])

                with self.app.app_context():
                    attempt = get_db().execute(
                        "SELECT status FROM attempts WHERE id=?",
                        (attempt_id,)
                    ).fetchone()

                self.assertEqual(attempt["status"], "in_progress")
            else:
                self.assertTrue(data["disqualified"])

        result = self.client.get(f"/result/{attempt_id}")
        self.assertEqual(result.status_code, 200)
        self.assertIn(
            "Попытка завершена из-за нарушений".encode(),
            result.data
        )

        with self.app.app_context():
            attempt = get_db().execute(
                "SELECT status, violations FROM attempts WHERE id=?",
                (attempt_id,)
            ).fetchone()

        self.assertEqual(attempt["status"], "disqualified")
        self.assertEqual(attempt["violations"], 3)


    def test_answers_are_saved_and_visible_to_teacher(self):
        self.register_student()
        attempt_id = self.start_first_quiz()
        with self.app.app_context():
            db = get_db()
            rows = db.execute(
                """SELECT aq.question_id,q.correct_option
                   FROM attempt_questions aq JOIN questions q ON q.id=aq.question_id
                   WHERE aq.attempt_id=?""", (attempt_id,)
            ).fetchall()
        answers = {f"q_{row['question_id']}": row["correct_option"] for row in rows}
        response = self.client.post(f"/quiz/{attempt_id}/submit", data=answers)
        self.assertEqual(response.status_code, 302)
        result = self.client.get(f"/result/{attempt_id}")
        self.assertEqual(result.status_code, 200)
        self.assertIn("5".encode(), result.data)

        self.client.post("/logout")
        self.client.post("/login", data={"username": "teacher", "password": "teacher123"})
        dashboard = self.client.get("/teacher")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("Тестовый Студент".encode(), dashboard.data)

    def test_student_cannot_view_another_students_attempt(self):
        self.register_student("student1")
        attempt_id = self.start_first_quiz()
        self.client.post("/logout")
        self.register_student("student2")
        response = self.client.get(f"/result/{attempt_id}")
        self.assertEqual(response.status_code, 403)


    def login_teacher(self):
        return self.client.post("/login", data={
            "username": "teacher", "password": "teacher123"
        }, follow_redirects=True)

    def test_demo_student_account_is_seeded_and_can_login(self):
        response = self.client.post("/login", data={
            "username": "student", "password": "student123"
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Доступные тесты".encode(), response.data)
        self.assertIn("Демонстрационный Студент".encode(), response.data)

    def test_teacher_can_open_quiz_builder(self):
        self.login_teacher()
        response = self.client.get("/teacher/quizzes/new")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Создать новый тест".encode(), response.data)
        self.assertIn("Добавить вопрос".encode(), response.data)

    def test_teacher_can_create_and_publish_quiz(self):
        self.login_teacher()
        response = self.client.post("/teacher/quizzes/new", data={
            "title": "Тест по алгоритмам",
            "description": "Проверка базовых знаний алгоритмизации",
            "duration_minutes": "15",
            "is_active": "1",
            "question_text": ["Что такое алгоритм?"],
            "option_a": ["Последовательность действий"],
            "option_b": ["Язык программирования"],
            "option_c": ["Текстовый редактор"],
            "option_d": ["Операционная система"],
            "correct_option": ["A"],
            "explanation": ["Алгоритм задаёт конечную последовательность шагов."],
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Тест по алгоритмам".encode(), response.data)
        with self.app.app_context():
            db = get_db()
            quiz = db.execute("SELECT * FROM quizzes WHERE title=?", ("Тест по алгоритмам",)).fetchone()
            questions = db.execute("SELECT * FROM questions WHERE quiz_id=?", (quiz["id"],)).fetchall()
        self.assertIsNotNone(quiz)
        self.assertEqual(quiz["duration_seconds"], 900)
        self.assertEqual(quiz["is_active"], 1)
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]["correct_option"], "A")
        self.client.post("/logout")
        self.client.post("/login", data={"username": "student", "password": "student123"})
        student_catalog = self.client.get("/student")
        self.assertIn("Тест по алгоритмам".encode(), student_catalog.data)

    def test_teacher_can_save_draft_and_publish_it_later(self):
        self.login_teacher()
        self.client.post("/teacher/quizzes/new", data={
            "title": "Черновой тест",
            "description": "Тест пока не опубликован",
            "duration_minutes": "5",
            "question_text": ["Сколько будет 2 + 2?"],
            "option_a": ["3"], "option_b": ["4"],
            "option_c": ["5"], "option_d": ["6"],
            "correct_option": ["B"], "explanation": ["Два плюс два равно четыре."],
        })
        with self.app.app_context():
            db = get_db()
            quiz = db.execute("SELECT id,is_active FROM quizzes WHERE title=?", ("Черновой тест",)).fetchone()
        self.assertEqual(quiz["is_active"], 0)
        self.client.post("/logout")
        self.client.post("/login", data={"username": "student", "password": "student123"})
        student_catalog = self.client.get("/student")
        self.assertNotIn("Черновой тест".encode(), student_catalog.data)
        self.client.post("/logout")
        self.login_teacher()
        self.client.post(f"/teacher/quizzes/{quiz['id']}/toggle")
        with self.app.app_context():
            active = get_db().execute("SELECT is_active FROM quizzes WHERE id=?", (quiz["id"],)).fetchone()[0]
        self.assertEqual(active, 1)
        self.client.post("/logout")
        self.client.post("/login", data={"username": "student", "password": "student123"})
        published_catalog = self.client.get("/student")
        self.assertIn("Черновой тест".encode(), published_catalog.data)

    def test_student_cannot_create_quiz(self):
        self.client.post("/login", data={"username": "student", "password": "student123"})
        response = self.client.get("/teacher/quizzes/new")
        self.assertEqual(response.status_code, 403)

    def test_result_can_be_exported_as_pdf(self):
        self.register_student()
        attempt_id = self.start_first_quiz()
        with self.app.app_context():
            rows = get_db().execute(
                """SELECT aq.question_id,q.correct_option
                   FROM attempt_questions aq JOIN questions q ON q.id=aq.question_id
                   WHERE aq.attempt_id=?""", (attempt_id,)
            ).fetchall()
        answers = {f"q_{row['question_id']}": row["correct_option"] for row in rows}
        self.client.post(f"/quiz/{attempt_id}/submit", data=answers)
        response = self.client.get(f"/result/{attempt_id}/pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertIn("attachment", response.headers.get("Content-Disposition", ""))
        self.assertIn(f"result_{attempt_id}.pdf", response.headers.get("Content-Disposition", ""))
        self.assertTrue(response.data.startswith(b"%PDF"))
        self.assertGreater(len(response.data), 2_000)


if __name__ == "__main__":
    unittest.main()
