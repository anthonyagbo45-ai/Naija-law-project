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

# --- ALL 36 NIGERIAN STATES + FCT ---
NIGERIAN_STATES = [
    "Abia", "Adamawa", "Akwa Ibom", "Anambra", "Bauchi", "Bayelsa", "Benue", 
    "Borno", "Cross River", "Delta", "Ebonyi", "Edo", "Ekiti", "Enugu", 
    "FCT - Abuja", "Gombe", "Imo", "Jigawa", "Kaduna", "Kano", "Katsina", 
    "Kebbi", "Kogi", "Kwara", "Lagos", "Nasarawa", "Niger", "Ogun", "Ondo", 
    "Osun", "Oyo", "Plateau", "Rivers", "Sokoto", "Taraba", "Yobe", "Zamfara"
]

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
    title = db.Column(db.String(255), nullable=False)       
    abbreviation = db.Column(db.String(20), nullable=False)   
    category = db.Column(db.String(100), nullable=False)   
    jurisdiction = db.Column(db.String(50), default="Federal") 
    description = db.Column(db.Text, nullable=False)


class StatuteSection(db.Model):
    """Model to store specific sections/clauses of an Act for granular search."""
    id = db.Column(db.Integer, primary_key=True)
    statute_id = db.Column(db.Integer, db.ForeignKey('statute.id'), nullable=False)
    section_number = db.Column(db.String(50), nullable=False) 
    title = db.Column(db.String(255), nullable=True)           
    content = db.Column(db.Text, nullable=False)               

    statute = db.relationship('Statute', backref=db.backref('sections', lazy=True))


class CaseLaw(db.Model):
    """Model for judicial precedents (Lawyers & Legal Research)"""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)          
    citation = db.Column(db.String(100), nullable=False)       
    court = db.Column(db.String(100), nullable=False)          
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
    subject = db.Column(db.String(100), nullable=True, default="General Law")
    facts = db.Column(db.Text, nullable=False)
    issue = db.Column(db.Text, nullable=False)
    held = db.Column(db.Text, nullable=False)
    ratio = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())


class Quiz(db.Model):
    """Model to group questions into structured module/course quizzes."""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    course = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    
    questions = db.relationship('Question', backref='quiz', lazy=True, cascade="all, delete-orphan")


class Question(db.Model):
    """Model for individual questions within a quiz."""
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id'), nullable=False)
    prompt = db.Column(db.Text, nullable=False)
    explanation = db.Column(db.Text, nullable=True)

    options = db.relationship('Option', backref='question', lazy=True, cascade="all, delete-orphan")


class Option(db.Model):
    """Model for answer choices associated with a quiz question."""
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)
    option_text = db.Column(db.String(255), nullable=False)
    is_correct = db.Column(db.Boolean, default=False)


class LegalDirectory(db.Model):
    """Model for public legal aid, NGO, and court office contacts"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    organization_type = db.Column(db.String(100), nullable=False) 
    state = db.Column(db.String(50), nullable=False)
    address = db.Column(db.Text, nullable=False)
    phone = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(120), nullable=True)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# --- SEED & SYNC FUNCTION ---
def populate_and_sync_sections():
    """Ensure all statutes have actual indexed sections populated."""
    statute_data = [
        {
            "abbreviation": "CFRN 1999",
            "title": "Constitution of the Federal Republic of Nigeria 1999 (as amended)",
            "category": "Constitutional Law",
            "jurisdiction": "Federal",
            "description": "The supreme law of the Federal Republic of Nigeria establishing government framework and fundamental human rights.",
            "sections": [
                {"num": "Section 33", "title": "Right to Life", "content": "Every person has a right to life, and no one shall be deprived intentionally of his life, save in execution of the sentence of a court in respect of a criminal offence of which he has been found guilty in Nigeria."},
                {"num": "Section 34", "title": "Right to Dignity of Human Person", "content": "Every individual is entitled to respect for the dignity of his person, and accordingly: (a) no person shall be subjected to torture or to inhuman or degrading treatment; (b) no person shall be held in slavery or servitude; and (c) no person shall be required to perform forced or compulsory labour."},
                {"num": "Section 35", "title": "Right to Personal Liberty", "content": "Every person shall be entitled to his personal liberty and no person shall be deprived of such liberty save in accordance with a procedure permitted by law."},
                {"num": "Section 36", "title": "Right to Fair Hearing", "content": "In the determination of his civil rights and obligations, including any question or determination by or against any government or authority, a person shall be entitled to a fair hearing within a reasonable time by a court or other tribunal established by law."}
            ]
        },
        {
            "abbreviation": "Criminal Code",
            "title": "Criminal Code Act",
            "category": "Criminal Law",
            "jurisdiction": "Southern Nigeria",
            "description": "Primary statutory framework governing criminal offenses and procedure applicable in Southern Nigerian states.",
            "sections": [
                {"num": "Section 316", "title": "Definition of Murder", "content": "Except as hereinafter set forth, a person who unlawfully kills another under any of the following circumstances is guilty of murder: (1) If the offender intends to cause the death of the person killed..."},
                {"num": "Section 351", "title": "Unlawful Assault", "content": "Any person who unlawfully assaults another is guilty of a misdemeanor, and is liable, if no greater punishment is provided, to imprisonment for one year."},
                {"num": "Section 383", "title": "Definition of Stealing", "content": "A person who fraudulently takes anything capable of being stolen, or fraudulently converts to his own use or to the use of any other person anything capable of being stolen, is said to steal that thing."}
            ]
        },
        {
            "abbreviation": "Penal Code",
            "title": "Penal Code Law",
            "category": "Criminal Law",
            "jurisdiction": "Northern Nigeria",
            "description": "Primary criminal law code governing criminal liability and offenses across Northern Nigerian states.",
            "sections": [
                {"num": "Section 220", "title": "Culpable Homicide", "content": "Whoever causes death by doing an act with the intention of causing death or such bodily injury as is likely to cause death, or with the knowledge that he is likely by such act to cause death, commits the offense of culpable homicide."},
                {"num": "Section 286", "title": "Theft Defined", "content": "Whoever, intending to take dishonestly any movable property out of the possession of any person without that person's consent, moves that property in order to such taking, is said to commit theft."}
            ]
        },
        {
            "abbreviation": "VAPA 2015",
            "title": "Violence Against Persons (Prohibition) Act 2015",
            "category": "Human Rights & Protection",
            "jurisdiction": "Federal / FCT",
            "description": "Eliminates violence in private and public life, prohibiting gender-based violence and domestic abuse.",
            "sections": [
                {"num": "Section 1", "title": "Rape and Penalties", "content": "A person commits the offense of rape if he or she intentionally penetrates the vagina, anus, or mouth of another person with any other part of his or her body or anything else, without consent."},
                {"num": "Section 2", "title": "Inflicting Physical Injury", "content": "A person who willfully causes or attempts to cause physical injury on another person commits an offense and is liable on conviction to imprisonment for a term not exceeding 4 years or a fine."}
            ]
        },
        {
            "abbreviation": "CRA 2003",
            "title": "Child Rights Act 2003",
            "category": "Family & Human Rights",
            "jurisdiction": "Federal",
            "description": "Protects the rights and welfare of children in Nigeria under domestic and international law.",
            "sections": [
                {"num": "Section 1", "title": "Best Interest of the Child", "content": "In every action concerning a child, whether undertaken by an individual, public or private body, institutions or courts, the best interest of the child shall be the primary consideration."},
                {"num": "Section 11", "title": "Right to Dignity of the Child", "content": "Every child is entitled to respect for the dignity of his person, and accordingly, no child shall be subjected to physical, mental or emotional abuse."}
            ]
        }
    ]

    for item in statute_data:
        statute = Statute.query.filter_by(abbreviation=item["abbreviation"]).first()
        if not statute:
            statute = Statute(
                title=item["title"],
                abbreviation=item["abbreviation"],
                category=item["category"],
                jurisdiction=item["jurisdiction"],
                description=item["description"]
            )
            db.session.add(statute)
            db.session.commit()

        for sec in item["sections"]:
            existing_sec = StatuteSection.query.filter_by(
                statute_id=statute.id, 
                section_number=sec["num"]
            ).first()
            if not existing_sec:
                new_sec = StatuteSection(
                    statute_id=statute.id,
                    section_number=sec["num"],
                    title=sec["title"],
                    content=sec["content"]
                )
                db.session.add(new_sec)
        db.session.commit()


# --- INITIALIZE DATABASE & SEED DATA ---
with app.app_context():
    db.create_all()
    populate_and_sync_sections()

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

    if CaseBrief.query.count() == 0:
        sample_brief = CaseBrief(
            case_name="Bello v. Attorney-General of Oyo State",
            citation="(1986) 5 NWLR (Pt. 45) 828",
            subject="Constitutional Law",
            facts="The appellant was convicted of armed robbery and sentenced to death. While his appeal was pending before the Court of Appeal, the Oyo State Government executed him.",
            issue="Whether the execution of a convict while his appeal against conviction and sentence is pending violates his fundamental rights.",
            held="The Supreme Court held unanimously that the execution was premature, illegal, and unconstitutional.",
            ratio="It is an infringement of the fundamental right to life and fair hearing to execute a convict when an appeal challenging the conviction is pending."
        )
        db.session.add(sample_brief)
        db.session.commit()

    # --- POPULATE DIRECTORY FOR ALL 36 STATES + FCT ---
    if LegalDirectory.query.count() < 37:
        all_state_directories = [
            LegalDirectory(name="High Court of Abia State", organization_type="Superior Court", state="Abia", address="Judicial Complex, Umuahia, Abia State", phone="+234 800 000 0001", email="info@abiacourts.gov.ng"),
            LegalDirectory(name="High Court of Adamawa State", organization_type="Superior Court", state="Adamawa", address="Judicial Complex, Yola, Adamawa State", phone="+234 800 000 0002", email="info@adamawacourts.gov.ng"),
            LegalDirectory(name="High Court of Akwa Ibom State", organization_type="Superior Court", state="Akwa Ibom", address="Wellington Bassey Way, Uyo, Akwa Ibom State", phone="+234 800 000 0003", email="info@akwaibomcourts.gov.ng"),
            LegalDirectory(name="High Court of Anambra State", organization_type="Superior Court", state="Anambra", address="Court Road, Awka, Anambra State", phone="+234 800 000 0004", email="info@anambracourts.gov.ng"),
            LegalDirectory(name="High Court of Bauchi State", organization_type="Superior Court", state="Bauchi", address="Ahmadu Bello Way, Bauchi, Bauchi State", phone="+234 800 000 0005", email="info@bauchicourts.gov.ng"),
            LegalDirectory(name="High Court of Bayelsa State", organization_type="Superior Court", state="Bayelsa", address="Ovom, Yenagoa, Bayelsa State", phone="+234 800 000 0006", email="info@bayelsacourts.gov.ng"),
            LegalDirectory(name="High Court of Benue State", organization_type="Superior Court", state="Benue", address="Judicial Complex, Makurdi, Benue State", phone="+234 800 000 0007", email="info@benuecourts.gov.ng"),
            LegalDirectory(name="High Court of Borno State", organization_type="Superior Court", state="Borno", address="Kashim Ibrahim Way, Maiduguri, Borno State", phone="+234 800 000 0008", email="info@bornocourts.gov.ng"),
            LegalDirectory(name="High Court of Cross River State", organization_type="Superior Court", state="Cross River", address="Mary Slessor Avenue, Calabar, Cross River State", phone="+234 800 000 0009", email="info@crossrivercourts.gov.ng"),
            LegalDirectory(name="High Court of Delta State", organization_type="Superior Court", state="Delta", address="Okpanam Road, Asaba, Delta State", phone="+234 800 000 0010", email="info@deltacourts.gov.ng"),
            LegalDirectory(name="High Court of Ebonyi State", organization_type="Superior Court", state="Ebonyi", address="Town Planning Road, Abakaliki, Ebonyi State", phone="+234 800 000 0011", email="info@ebonyicourts.gov.ng"),
            LegalDirectory(name="High Court of Edo State", organization_type="Superior Court", state="Edo", address="Sapele Road, Benin City, Edo State", phone="+234 800 000 0012", email="info@edocourts.gov.ng"),
            LegalDirectory(name="High Court of Ekiti State", organization_type="Superior Court", state="Ekiti", address="Fajuyi Park Area, Ado-Ekiti, Ekiti State", phone="+234 800 000 0013", email="info@ekiticourts.gov.ng"),
            LegalDirectory(name="High Court of Enugu State", organization_type="Superior Court", state="Enugu", address="Independence Layout, Enugu, Enugu State", phone="+234 800 000 0014", email="info@enugucourts.gov.ng"),
            LegalDirectory(name="Legal Aid Council HQ / FCT High Court", organization_type="Legal Aid / Court", state="FCT - Abuja", address="Area 11, Garki, Abuja", phone="+234 9 291 8221", email="info@legalaidcouncil.gov.ng"),
            LegalDirectory(name="High Court of Gombe State", organization_type="Superior Court", state="Gombe", address="Tudun Wada, Gombe, Gombe State", phone="+234 800 000 0015", email="info@gombecourts.gov.ng"),
            LegalDirectory(name="High Court of Imo State", organization_type="Superior Court", state="Imo", address="Orlu Road, Owerri, Imo State", phone="+234 800 000 0016", email="info@imocourts.gov.ng"),
            LegalDirectory(name="High Court of Jigawa State", organization_type="Superior Court", state="Jigawa", address="Kiyawa Road, Dutse, Jigawa State", phone="+234 800 000 0017", email="info@jigawacourts.gov.ng"),
            LegalDirectory(name="High Court of Kaduna State", organization_type="Superior Court", state="Kaduna", address="Bida Road, Kaduna, Kaduna State", phone="+234 800 000 0018", email="info@kadunacourts.gov.ng"),
            LegalDirectory(name="High Court of Kano State", organization_type="Superior Court", state="Kano", address="Audu Bako Secretariat, Kano, Kano State", phone="+234 800 000 0019", email="info@kanocourts.gov.ng"),
            LegalDirectory(name="High Court of Katsina State", organization_type="Superior Court", state="Katsina", address="Kanta Road, Katsina, Katsina State", phone="+234 800 000 0020", email="info@katsinacourts.gov.ng"),
            LegalDirectory(name="High Court of Kebbi State", organization_type="Superior Court", state="Kebbi", address="Sultan Abubakar Road, Birnin Kebbi, Kebbi State", phone="+234 800 000 0021", email="info@kebbicourts.gov.ng"),
            LegalDirectory(name="High Court of Kogi State", organization_type="Superior Court", state="Kogi", address="Murtala Mohammed Way, Lokoja, Kogi State", phone="+234 800 000 0022", email="info@kogicourts.gov.ng"),
            LegalDirectory(name="High Court of Kwara State", organization_type="Superior Court", state="Kwara", address="Laird Street, Ilorin, Kwara State", phone="+234 800 000 0023", email="info@kwaracourts.gov.ng"),
            LegalDirectory(name="High Court of Lagos State (Ikeja)", organization_type="Superior Court", state="Lagos", address="Oba Akinjobi Way, Ikeja, Lagos State", phone="+234 1 497 0000", email="registrar@lagoscourts.gov.ng"),
            LegalDirectory(name="High Court of Nasarawa State", organization_type="Superior Court", state="Nasarawa", address="Shendam Road, Lafia, Nasarawa State", phone="+234 800 000 0024", email="info@nasarawacourts.gov.ng"),
            LegalDirectory(name="High Court of Niger State", organization_type="Superior Court", state="Niger", address="Bosso Road, Minna, Niger State", phone="+234 800 000 0025", email="info@nigercourts.gov.ng"),
            LegalDirectory(name="High Court of Ogun State", organization_type="Superior Court", state="Ogun", address="Kobape Road, Abeokuta, Ogun State", phone="+234 800 000 0026", email="info@oguncourts.gov.ng"),
            LegalDirectory(name="High Court of Ondo State", organization_type="Superior Court", state="Ondo", address="Hospital Road, Akure, Ondo State", phone="+234 800 000 0027", email="info@ondocourts.gov.ng"),
            LegalDirectory(name="High Court of Osun State", organization_type="Superior Court", state="Osun", address="Gbongan Road, Osogbo, Osun State", phone="+234 800 000 0028", email="info@osuncourts.gov.ng"),
            LegalDirectory(name="High Court of Oyo State", organization_type="Superior Court", state="Oyo", address="Ring Road, Ibadan, Oyo State", phone="+234 800 000 0029", email="info@oyocourts.gov.ng"),
            LegalDirectory(name="High Court of Plateau State", organization_type="Superior Court", state="Plateau", address="Bank Road, Jos, Plateau State", phone="+234 800 000 0030", email="info@plateaucourts.gov.ng"),
            LegalDirectory(name="High Court of Rivers State", organization_type="Superior Court", state="Rivers", address="Ahmadu Bello Way, Port Harcourt, Rivers State", phone="+234 800 000 0031", email="info@riverscourts.gov.ng"),
            LegalDirectory(name="High Court of Sokoto State", organization_type="Superior Court", state="Sokoto", address="Sultan Abubakar Road, Sokoto, Sokoto State", phone="+234 800 000 0032", email="info@sokotocourts.gov.ng"),
            LegalDirectory(name="High Court of Taraba State", organization_type="Superior Court", state="Taraba", address="Hammaruwa Way, Jalingo, Taraba State", phone="+234 800 000 0033", email="info@tarabacourts.gov.ng"),
            LegalDirectory(name="High Court of Yobe State", organization_type="Superior Court", state="Yobe", address="Maiduguri Road, Damaturu, Yobe State", phone="+234 800 000 0034", email="info@yobecourts.gov.ng"),
            LegalDirectory(name="High Court of Zamfara State", organization_type="Superior Court", state="Zamfara", address="Sokoto Road, Gusau, Zamfara State", phone="+234 800 000 0035", email="info@zamfaracourts.gov.ng")
        ]
        for d in all_state_directories:
            if not LegalDirectory.query.filter_by(state=d.state).first():
                db.session.add(d)
        db.session.commit()

    if Quiz.query.count() == 0:
        sample_quiz = Quiz(
            title="Constitutional Rights Practice Quiz",
            course="CON101",
            description="Test your knowledge of Fundamental Human Rights guaranteed under Chapter IV of the CFRN 1999."
        )
        db.session.add(sample_quiz)
        db.session.commit()

        q1 = Question(
            quiz_id=sample_quiz.id,
            prompt="Which section of the CFRN 1999 guarantees the Right to Life?",
            explanation="Section 33(1) guarantees that every person has a right to life."
        )
        db.session.add(q1)
        db.session.commit()

        opts = [
            Option(question_id=q1.id, option_text="Section 33", is_correct=True),
            Option(question_id=q1.id, option_text="Section 34", is_correct=False),
            Option(question_id=q1.id, option_text="Section 35", is_correct=False),
            Option(question_id=q1.id, option_text="Section 36", is_correct=False)
        ]
        db.session.add_all(opts)
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

    featured_statutes = Statute.query.limit(5).all()

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
    statute = db.get_or_404(Statute, statute_id)

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
    response_mode = request.form.get("mode", "legal")

    if request.method == "POST":
        user_query = (request.form.get("user_query") or "").strip()

        if user_query:
            keywords = user_query.split()
            search_filters = [StatuteSection.content.ilike(f"%{word}%") for word in keywords if len(word) > 3]

            if search_filters:
                referenced_sections = StatuteSection.query.filter(db.or_(*search_filters)).limit(5).all()
            else:
                referenced_sections = StatuteSection.query.limit(5).all()

            context_text = "\n".join([
                f"- [{sec.statute.abbreviation} {sec.section_number} ({sec.title or 'N/A'})]: {sec.content}"
                for sec in referenced_sections
            ])

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
    case = db.get_or_404(CaseLaw, case_id)
    return render_template("case_detail.html", case=case)


# --- 1. STUDENT HUB MAIN ROUTE ---
@app.route('/student-hub')
@login_required
def student_hub():
    # Fetch all briefs (or filter/paginate as needed)
    briefs = CaseBrief.query.order_by(CaseBrief.created_at.desc()).all()
    
    # Fetch all active quizzes
    quizzes = Quiz.query.all()
    
    # Render student_hub.html with both query datasets
    return render_template('student_hub.html', briefs=briefs, quizzes=quizzes)


# --- 2. SINGLE CASE BRIEF ROUTE ---
@app.route('/briefs/<int:brief_id>')
@login_required
def view_brief(brief_id):
    brief = db.get_or_404(CaseBrief, brief_id)
    return render_template('brief_detail.html', brief=brief)


# --- 3. TAKE QUIZ ROUTE (GET & POST) ---
@app.route('/quiz/<int:quiz_id>', methods=['GET', 'POST'])
@login_required
def take_quiz(quiz_id):
    quiz = db.get_or_404(Quiz, quiz_id)

    if request.method == 'POST':
        score = 0
        total_questions = len(quiz.questions)
        results = []

        # Process user submitted answers
        for question in quiz.questions:
            # Selected option ID passed from HTML form input name="question_<id>"
            selected_option_id = request.form.get(f'question_{question.id}')
            selected_option = db.session.get(Option, int(selected_option_id)) if selected_option_id else None
            
            # Identify correct option for evaluation
            correct_option = next((opt for opt in question.options if opt.is_correct), None)
            
            is_correct = False
            if selected_option and selected_option.is_correct:
                score += 1
                is_correct = True

            results.append({
                'question': question,
                'selected_option': selected_option,
                'correct_option': correct_option,
                'is_correct': is_correct
            })

        # Calculate percentage score
        percentage = round((score / total_questions) * 100, 1) if total_questions > 0 else 0

        return render_template(
            'quiz_result.html', 
            quiz=quiz, 
            score=score, 
            total=total_questions, 
            percentage=percentage,
            results=results
        )

    # Render quiz form for GET requests
    return render_template('quiz_take.html', quiz=quiz)


@app.route("/directory")
@login_required
def legal_directory():
    name_query = request.args.get("q", "").strip()
    state_filter = request.args.get("state", "").strip()

    has_searched = bool(name_query or state_filter)
    entries = []

    if has_searched:
        query = LegalDirectory.query

        if state_filter:
            clean_state = state_filter.replace("FCT - ", "").replace(" State", "").strip()
            query = query.filter(LegalDirectory.state.ilike(f"%{clean_state}%"))

        if name_query:
            search_terms = name_query.split()
            for term in search_terms:
                pattern = f"%{term}%"
                query = query.filter(
                    db.or_(
                        LegalDirectory.name.ilike(pattern),
                        LegalDirectory.organization_type.ilike(pattern),
                        LegalDirectory.address.ilike(pattern),
                        LegalDirectory.state.ilike(pattern)
                    )
                )

        entries = query.all()

    return render_template(
        "directory.html",
        entries=entries,
        has_searched=has_searched,
        states=NIGERIAN_STATES,
        selected_state=state_filter,
        search_query=name_query
    )


if __name__ == "__main__":
    app.run(debug=True)