import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from google import genai

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-123")

# --- GEMINI CLIENT CONFIGURATION ---
gemini_api_key = os.getenv("GEMINI_API_KEY")
ai_client = genai.Client(api_key=gemini_api_key) if gemini_api_key else None

# --- DATABASE CONFIGURATION ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'law_portal.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- LOGIN MANAGER CONFIGURATION ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


# --- DATA MODELS ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Statute(db.Model):
    """Model to store laws like CFRN 1999, Penal Code, VAPA, CRA etc."""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)       # e.g. "Constitution of the Federal Republic of Nigeria 1999"
    abbreviation = db.Column(db.String(20), nullable=False)   # e.g. "CFRN 1999"
    category = db.Column(db.String(100), nullable=False)   # e.g. "Constitutional Law", "Criminal Law"
    jurisdiction = db.Column(db.String(50), default="Federal") # Federal, Northern Nigeria, Southern Nigeria
    description = db.Column(db.Text, nullable=False)


class StatuteSection(db.Model):
    """Model to store specific sections/clauses of an Act for granular search."""
    id = db.Column(db.Integer, primary_key=True)
    statute_id = db.Column(db.Integer, db.ForeignKey('statute.id'), nullable=False)
    section_number = db.Column(db.String(50), nullable=False) # e.g. "Section 33"
    title = db.Column(db.String(255), nullable=True)           # e.g. "Right to Life"
    content = db.Column(db.Text, nullable=False)               # Full text of the section

    statute = db.relationship('Statute', backref=db.backref('sections', lazy=True))


# --- ADDITIVE DATA MODELS ---

class CaseLaw(db.Model):
    """Model for judicial precedents (Lawyers & Legal Research)"""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)          # e.g. "FRN v. Anache & Ors"
    citation = db.Column(db.String(100), nullable=False)       # e.g. "(2004) 14 NWLR (Pt. 893) 245"
    court = db.Column(db.String(100), nullable=False)          # e.g. "Supreme Court of Nigeria"
    year = db.Column(db.Integer, nullable=False)
    summary = db.Column(db.Text, nullable=False)
    ratio_decidendi = db.Column(db.Text, nullable=False)
    statute_section_id = db.Column(db.Integer, db.ForeignKey('statute_section.id'), nullable=True)

    statute_section = db.relationship('StatuteSection', backref=db.backref('cases', lazy=True))


class CaseBrief(db.Model):
    """Model for structured law student case briefs"""
    id = db.Column(db.Integer, primary_key=True)
    case_name = db.Column(db.String(255), nullable=False)
    citation = db.Column(db.String(100), nullable=False)
    facts = db.Column(db.Text, nullable=False)
    issue = db.Column(db.Text, nullable=False)
    held = db.Column(db.Text, nullable=False)
    ratio = db.Column(db.Text, nullable=False)


class QuizQuestion(db.Model):
    """Model for bar exam and law student practice questions"""
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(100), nullable=False)       # e.g. "Constitutional Law", "Criminal Litigation"
    question = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.String(255), nullable=False)
    option_b = db.Column(db.String(255), nullable=False)
    option_c = db.Column(db.String(255), nullable=False)
    option_d = db.Column(db.String(255), nullable=False)
    correct_option = db.Column(db.String(1), nullable=False)  # "A", "B", "C", or "D"
    explanation = db.Column(db.Text, nullable=False)


class LegalDirectory(db.Model):
    """Model for public legal aid, NGO, and court office contacts"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    organization_type = db.Column(db.String(100), nullable=False) # e.g. "Legal Aid Council", "NGO", "NBA Branch"
    state = db.Column(db.String(50), nullable=False)
    address = db.Column(db.Text, nullable=False)
    phone = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(120), nullable=True)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# --- INITIALIZE DATABASE & SEED DATA ---
with app.app_context():
    db.create_all()

    # Seed default Nigerian laws and sections if database is empty
    if Statute.query.count() == 0:
        cfrn = Statute(
            title="Constitution of the Federal Republic of Nigeria 1999 (as amended)",
            abbreviation="CFRN 1999",
            category="Constitutional Law",
            jurisdiction="Federal",
            description="The supreme law of the Federal Republic of Nigeria establishing government framework and fundamental human rights."
        )
        criminal_code = Statute(
            title="Criminal Code Act",
            abbreviation="Criminal Code",
            category="Criminal Law",
            jurisdiction="Southern Nigeria",
            description="Primary statutory framework governing criminal offenses and procedure applicable in Southern Nigerian states."
        )
        penal_code = Statute(
            title="Penal Code Law",
            abbreviation="Penal Code",
            category="Northern Nigeria",
            description="Primary criminal law code governing criminal liability and offenses across Northern Nigerian states."
        )
        vapa = Statute(
            title="Violence Against Persons (Prohibition) Act 2015",
            abbreviation="VAPA 2015",
            category="Human Rights & Protection",
            jurisdiction="Federal / FCT",
            description="Eliminates violence in private and public life, prohibiting gender-based violence and domestic abuse."
        )
        cra = Statute(
            title="Child Rights Act 2003",
            abbreviation="CRA 2003",
            category="Family & Human Rights",
            jurisdiction="Federal",
            description="Protects the rights and welfare of children in Nigeria under domestic and international law."
        )

        db.session.add_all([cfrn, criminal_code, penal_code, vapa, cra])
        db.session.commit()

        # Seed sample sections for CFRN 1999
        cfrn_sections = [
            StatuteSection(
                statute_id=cfrn.id,
                section_number="Section 33",
                title="Right to Life",
                content="Every person has a right to life, and no one shall be deprived intentionally of his life, save in execution of the sentence of a court in respect of a criminal offence of which he has been found guilty in Nigeria."
            ),
            StatuteSection(
                statute_id=cfrn.id,
                section_number="Section 34",
                title="Right to Dignity of Human Person",
                content="Every individual is entitled to respect for the dignity of his person, and accordingly: (a) no person shall be subjected to torture or to inhuman or degrading treatment; (b) no person shall be held in slavery or servitude; and (c) no person shall be required to perform forced or compulsory labour."
            ),
            StatuteSection(
                statute_id=cfrn.id,
                section_number="Section 35",
                title="Right to Personal Liberty",
                content="Every person shall be entitled to his personal liberty and no person shall be deprived of such liberty save in the following cases and in accordance with a procedure permitted by law..."
            )
        ]
        db.session.add_all(cfrn_sections)
        db.session.commit()

    # Seed Case Law sample data
    if CaseLaw.query.count() == 0:
        sec_33 = StatuteSection.query.filter_by(section_number="Section 33").first()
        sec_33_id = sec_33.id if sec_33 else None

        sample_case = CaseLaw(
            title="Bello v. Attorney-General of Oyo State",
            citation="(1986) 5 NWLR (Pt. 45) 828",
            court="Supreme Court of Nigeria",
            year=1986,
            summary="A landmark decision on the constitutional right to life and procedural fairness prior to execution.",
            ratio_decidendi="Execution of an accused person while his appeal is pending violates the fundamental right to life under the Constitution.",
            statute_section_id=sec_33_id
        )
        db.session.add(sample_case)
        db.session.commit()

    # Seed Legal Directory sample data
    if LegalDirectory.query.count() == 0:
        sample_dir = LegalDirectory(
            name="Legal Aid Council of Nigeria (HQ)",
            organization_type="Legal Aid Council",
            state="FCT - Abuja",
            address="No. 22 Port Harcourt Crescent, Off Gimbiya Street, Area 11, Garki, Abuja",
            phone="+234 9 291 8221",
            email="info@legalaidcouncil.gov.ng"
        )
        db.session.add(sample_dir)
        db.session.commit()

    # Seed Quiz sample data
    if QuizQuestion.query.count() == 0:
        sample_quiz = QuizQuestion(
            subject="Constitutional Law",
            question="Which section of the CFRN 1999 guarantees the Right to Life?",
            option_a="Section 33",
            option_b="Section 34",
            option_c="Section 35",
            option_d="Section 36",
            correct_option="A",
            explanation="Section 33(1) guarantees that every person has a right to life."
        )
        db.session.add(sample_quiz)
        db.session.commit()


# --- APPLICATION ROUTES ---

@app.route("/")
def home():
    featured_statutes = Statute.query.limit(3).all()
    return render_template("index.html", featured_statutes=featured_statutes)


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")

        if not full_name or not email or not password:
            flash("All fields are required.", "danger")
            return redirect(url_for("register"))

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("register"))

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash("Email address is already registered. Please log in.", "warning")
            return redirect(url_for("login"))

        new_user = User(full_name=full_name, email=email)
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()

        login_user(new_user)
        flash("Account created successfully! Welcome aboard.", "success")
        return redirect(url_for("dashboard"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password")

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            login_user(user, remember=True)
            flash("Welcome back!", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "danger")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    total_statutes = Statute.query.count()
    total_sections = StatuteSection.query.count()

    categories = db.session.query(Statute.category).distinct().all()
    total_categories = len([c[0] for c in categories if c[0]])

    featured_statutes = Statute.query.limit(4).all()

    return render_template(
        "dashboard.html",
        total_statutes=total_statutes,
        total_sections=total_sections,
        total_categories=total_categories,
        featured_statutes=featured_statutes
    )


@app.route("/laws")
@login_required
def laws_directory():
    search_query = request.args.get("q", "").strip()
    category_filter = request.args.get("category", "").strip()

    query = Statute.query

    if search_query:
        query = query.filter(
            (Statute.title.ilike(f"%{search_query}%")) |
            (Statute.abbreviation.ilike(f"%{search_query}%")) |
            (Statute.description.ilike(f"%{search_query}%"))
        )

    if category_filter:
        query = query.filter(Statute.category == category_filter)

    statutes = query.all()

    categories = db.session.query(Statute.category).distinct().all()
    category_list = [c[0] for c in categories if c[0]]

    return render_template(
        "laws.html",
        statutes=statutes,
        categories=category_list,
        search_query=search_query,
        selected_category=category_filter
    )


@app.route("/laws/<int:statute_id>")
@login_required
def statute_detail(statute_id):
    statute = db.session.get(Statute, statute_id)
    if not statute:
        flash("Statute not found.", "warning")
        return redirect(url_for("laws_directory"))

    section_query = request.args.get("q", "").strip()

    sections_query = StatuteSection.query.filter_by(statute_id=statute.id)
    if section_query:
        sections_query = sections_query.filter(
            (StatuteSection.section_number.ilike(f"%{section_query}%")) |
            (StatuteSection.title.ilike(f"%{section_query}%")) |
            (StatuteSection.content.ilike(f"%{section_query}%"))
        )

    sections = sections_query.all()

    return render_template(
        "statute_detail.html",
        statute=statute,
        sections=sections,
        section_query=section_query
    )


@app.route("/ai-search", methods=["GET", "POST"])
@login_required
def ai_search():
    user_query = ""
    ai_response = ""
    referenced_sections = []
    response_mode = request.form.get("mode", "legal")  # "legal", "case_brief", or "plain_english"

    if request.method == "POST":
        user_query = (request.form.get("user_query") or "").strip()

        if user_query:
            # 1. Database Retrieval: Find matching statutory provisions
            keywords = user_query.split()
            search_filters = [StatuteSection.content.ilike(f"%{word}%") for word in keywords if len(word) > 3]

            if search_filters:
                referenced_sections = StatuteSection.query.filter(db.or_(*search_filters)).limit(5).all()
            else:
                referenced_sections = StatuteSection.query.limit(5).all()

            # 2. Construct Prompt Context
            context_text = "\n".join([
                f"- [{sec.statute.abbreviation} {sec.section_number} ({sec.title or 'N/A'})]: {sec.content}"
                for sec in referenced_sections
            ])

            # Adjust Persona Instructions based on Response Mode
            if response_mode == "plain_english":
                persona_instructions = """You are a legal assistant explaining Nigerian law to citizens and non-lawyers.
1. Translate legal terminology into simple, clear, everyday English.
2. Clearly explain what rights or duties apply in practical terms.
3. Keep sentences short and accessible."""
            elif response_mode == "case_brief":
                persona_instructions = """You are a legal scholar assisting a law student.
1. Structure your analysis as a formal Case Brief / Legal Study Note.
2. Outline key statutory principles using headings: [Facts/Context], [Legal Issues], [Statutory Provisions], and [Key Rule/Ratio]."""
            else:
                persona_instructions = """You are an expert legal assistant specializing in Nigerian Statutory Law.
1. Provide a clear, structured legal opinion analyzing the query.
2. Specifically cite constitutional or statutory sections (e.g., CFRN 1999, Penal Code, VAPA) relevant to the situation.
3. Keep the tone professional, precise, and objective."""

            prompt = f"""{persona_instructions}

USER QUERY:
{user_query}

RELEVANT STATUTORY PROVISIONS IN DATABASE:
{context_text if context_text else 'No direct sections found in local database.'}
"""

            # 3. Call Gemini API
            if ai_client:
                try:
                    response = ai_client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=prompt,
                    )
                    ai_response = response.text
                except Exception as e:
                    ai_response = f"An error occurred while communicating with Gemini AI: {str(e)}"
            else:
                ai_response = "Gemini API client is not configured. Please set GEMINI_API_KEY in your .env file."

    return render_template(
        "ai_search.html",
        user_query=user_query,
        ai_response=ai_response,
        referenced_sections=referenced_sections,
        response_mode=response_mode
    )


# --- ADDITIVE ROUTES FOR FEATURE EXPANSION ---

# 1. LAWYERS: Case Law & Precedents
@app.route("/cases")
@login_required
def case_directory():
    q = request.args.get("q", "").strip()
    query = CaseLaw.query
    if q:
        query = query.filter(
            (CaseLaw.title.ilike(f"%{q}%")) |
            (CaseLaw.citation.ilike(f"%{q}%")) |
            (CaseLaw.ratio_decidendi.ilike(f"%{q}%"))
        )
    cases = query.all()
    return render_template("cases.html", cases=cases, q=q)


@app.route("/cases/<int:case_id>")
@login_required
def case_detail(case_id):
    case = db.session.get(CaseLaw, case_id)
    if not case:
        flash("Case precedent not found.", "warning")
        return redirect(url_for("case_directory"))
    return render_template("case_detail.html", case=case)


# 2. LAW STUDENTS: Study Hub & Quizzes
@app.route("/student-hub")
@login_required
def student_hub():
    briefs = CaseBrief.query.limit(5).all()
    quizzes = QuizQuestion.query.limit(10).all()
    return render_template("student_hub.html", briefs=briefs, quizzes=quizzes)


# 3. CITIZENS & NON-CITIZENS: Legal Directory & Rights Guides
@app.route("/directory")
def legal_directory():
    state_filter = request.args.get("state", "").strip()
    query = LegalDirectory.query
    if state_filter:
        query = query.filter(LegalDirectory.state.ilike(f"%{state_filter}%"))
    entries = query.all()
    return render_template("directory.html", entries=entries, selected_state=state_filter)


@app.route("/rights-guide")
def rights_guide():
    return render_template("rights_guide.html")


if __name__ == "__main__":
    app.run(debug=True, port=5000)