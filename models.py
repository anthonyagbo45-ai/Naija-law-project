from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

# --- CASE BRIEFS MODEL ---
class CaseBrief(db.Model):
    __tablename__ = 'case_briefs'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)        # e.g., "Donoghue v Stevenson"
    citation = db.Column(db.String(100), nullable=True)     # e.g., "[1932] AC 562"
    subject = db.Column(db.String(100), nullable=False)      # e.g., "Law of Torts", "Criminal Law"
    summary = db.Column(db.Text, nullable=False)          # Key facts and holding summary
    full_text = db.Column(db.Text, nullable=True)         # Complete judgment or breakdown
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# --- QUIZ MODELS ---
class Quiz(db.Model):
    __tablename__ = 'quizzes'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)       # e.g., "Constitutional Law Fundamentals"
    course = db.Column(db.String(100), nullable=False)      # e.g., "CON101"
    description = db.Column(db.Text, nullable=True)
    
    # Relationship to Questions
    questions = db.relationship('Question', backref='quiz', lazy=True, cascade="all, delete-orphan")


class Question(db.Model):
    __tablename__ = 'questions'

    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quizzes.id'), nullable=False)
    prompt = db.Column(db.Text, nullable=False)             # The question text
    explanation = db.Column(db.Text, nullable=True)        # Explanation shown after grading

    # Relationship to Options
    options = db.relationship('Option', backref='question', lazy=True, cascade="all, delete-orphan")


class Option(db.Model):
    __tablename__ = 'options'

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    option_text = db.Column(db.String(255), nullable=False)
    is_correct = db.Column(db.Boolean, default=False)       # Identifies the right answer