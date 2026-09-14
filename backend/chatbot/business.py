"""
Pure business logic ported 1:1 from worker.js.

Every constant string, regex, and threshold here is a faithful port of the
Cloudflare Worker so client-visible behaviour is unchanged. Function names are
Pythonic (snake_case) but semantics match the original exactly.
"""
from __future__ import annotations

import re
import uuid
from typing import Optional

# ============================================================================
# CONFIGURATION
# ============================================================================
# worker.js hardcodes `const ENABLE_HISTORY = false;`. Kept env-overridable but
# defaults False so each message is treated as a new conversation.
import os

from programs import DEFAULT_PROGRAM_ID, program_config

from . import appconfig


def enable_history() -> bool:
    raw = os.getenv("ENABLE_HISTORY")
    if raw is None:
        return False
    return raw.strip().lower() in ("1", "true", "yes", "on")


def generate_uuid() -> str:
    """UUID v4 for conversation tracking (worker: crypto.randomUUID())."""
    return str(uuid.uuid4())


# ============================================================================
# VALIDATION HELPERS
# ============================================================================
OUT_OF_SCOPE_KEYWORDS = [
    "capital", "country", "cook", "recipe", "weather", "sports",
    "movie", "music", "celebrity", "politics", "quantum physics",
    "fix.*car", "lose.*weight", "stock market", "cryptocurrency",
    "world cup", "pizza", "guitar", "hack",
]


def is_likely_out_of_scope(question: str) -> bool:
    question_lower = question.lower()
    return any(re.search(rf"\b{keyword}", question_lower, re.IGNORECASE) for keyword in OUT_OF_SCOPE_KEYWORDS)


# ============================================================================
# LANGUAGE SUPPORT
# ============================================================================
SUPPORTED_LANGUAGES = ["english", "hindi", "tamil", "hinglish"]


DEFAULT_GITHUB_BRANCH_BASE_URL = "https://github.com/iitmbsc-student-projects/iitmdocs/blob/main/"

# Kept for parity with the Worker (django-cors-headers applies the real headers).
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}

# One template per language. The programme's own support contacts and the
# contact-details link are filled in per request by get_cannot_answer_message,
# because each of the four bots has its own support email and phone number.
CANNOT_ANSWER_TEMPLATES = {
    "english": """I'm sorry, I don't have the information to answer that question right now. Please rephrase your question and try again. Please refer to the official IITM BS degree program website or contact support for more details. If this is an error - please report this response using the feedback option.
  You can reach out to us at {email} or call us at {phone}.

Need program-wise contacts? [View all program contact details]({contact_details_url}).""",
    "hindi": """मुझे खेद है, मेरे पास अभी इस प्रश्न का उत्तर देने की जानकारी नहीं है। कृपया अपना प्रश्न दोबारा लिखें और पुनः प्रयास करें। अधिक जानकारी के लिए कृपया आधिकारिक IITM BS डिग्री प्रोग्राम वेबसाइट देखें या सहायता से संपर्क करें। यदि यह कोई त्रुटि है - तो कृपया फीडबैक विकल्प का उपयोग करके इस प्रतिक्रिया की रिपोर्ट करें।
आप हमसे {email} पर संपर्क कर सकते हैं या {phone} पर कॉल कर सकते हैं

क्या आपको कार्यक्रम-वार संपर्क विवरण चाहिए? [सभी कार्यक्रम संपर्क विवरण देखें]({contact_details_url})।
""",
    "tamil": """மன்னிக்கவும், இந்த கேள்விக்கு பதிலளிக்க என்னிடம் தற்போது தகவல் இல்லை. உங்கள் கேள்வியை மீண்டும் எழுதி முயற்சிக்கவும். மேலும் விவரங்களுக்கு அதிகாரப்பூர்வ IITM BS டிகிரி புரோகிராம் இணையதளத்தைப் பார்க்கவும் அல்லது ஆதரவைத் தொடர்பு கொள்ளவும். இது ஒரு பிழை என்றால் - பின்னூட்ட விருப்பத்தைப் பயன்படுத்தி இந்த பதிலைப் புகாரளிக்கவும்.
நீங்கள் எங்களை {email} இல் தொடர்பு கொள்ளலாம் அல்லது {phone} என்ற எண்ணில் அழைக்கலாம்

நிரல் வாரியான தொடர்பு விவரங்கள் தேவையா? [அனைத்து நிரல் தொடர்பு விவரங்களையும் காண்க]({contact_details_url}).
""",
    "hinglish": """Maaf kijiye, mere paas abhi is sawaal ka jawaab dene ki jaankari nahi hai. Kripya apna sawaal dobara likhein aur phir se try karein. Zyada jaankari ke liye kripya official IITM BS degree program website dekhein ya support se sampark karein. Agar yeh koi galti hai - toh kripya feedback option use karke is response ki report karein.
Aap humse {email} par sampark kar sakte hain ya {phone} par call kar sakte hain

Kya aapko program-wise contacts chahiye? [Saare program contact details dekhein]({contact_details_url}).
""",
}

STANDARD_RAAHAT_MESSAGE = """I'm afraid I am not allowed to give you advice of any kind, but we are here. If you're looking for mental health support, our institute has a Wellness Society that provides confidential counseling services to enrolled students.

📧 Reach out to them at: wellness.society@study.iitm.ac.in
📱 Instagram: @wellness.society_iitmbs

If you are not enrolled in our program yet, but need someone to talk to, please consider reaching out to a local mental health professional or helpline in your area. Some organizations that offer support in India include:

- Aasra - https://www.aasra.info/
- Sneha - https://snehaindia.org/new/

Please don't hesitate to contact them - that's what they're there for. You're not alone in this."""


def extract_language(rewritten_query: Optional[str]) -> str:
    """worker.js currently always returns 'english' (language detection disabled)."""
    return "english"


def get_cannot_answer_message(language: Optional[str], program_id: str = DEFAULT_PROGRAM_ID) -> str:
    """Return the "I cannot answer that" text for one language and one programme.

    Example: get_cannot_answer_message("english", "es") names the ES support address
    support-es@study.iitm.ac.in, not the DS one.
    """
    lang = (language or "english").lower()
    template = CANNOT_ANSWER_TEMPLATES.get(lang, CANNOT_ANSWER_TEMPLATES["english"])
    config = program_config(program_id)
    branch_base_url = appconfig.github_branch_base_url().rstrip("/") + "/"
    return template.format(
        email=config["support_email"],
        phone=config["support_phone"],
        contact_details_url=f"{branch_base_url}docs/program-contact-details.md",
    )


def is_cannot_answer_response(text: Optional[str]) -> bool:
    normalized = re.sub(r"\s+", " ", (text or "").lower()).strip()
    if not normalized:
        return False
    if "don't have the information to answer" in normalized:
        return True
    if "please rephrase your question" in normalized:
        return True

    # Check whether the response starts like any standard "cannot answer" message.
    # The first 80 characters come before any contact details, so the raw template
    # is enough here and we do not need to know which programme produced the text.
    for template in CANNOT_ANSWER_TEMPLATES.values():
        prefix = re.sub(r"\s+", " ", template.lower()).strip()[:80]
        if prefix and prefix in normalized:
            return True
    return False


# ============================================================================
# PROMPT INJECTION PROTECTION
# ============================================================================
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|rules?)", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|above|prior)", re.IGNORECASE),
    re.compile(r"forget\s+(everything|all|what)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+a?", re.IGNORECASE),
    re.compile(r"pretend\s+(you\s+are|to\s+be)", re.IGNORECASE),
    re.compile(r"act\s+as\s+(if|a)", re.IGNORECASE),
    re.compile(r"new\s+instructions?:", re.IGNORECASE),
    re.compile(r"system\s*:", re.IGNORECASE),
    re.compile(r"assistant\s*:", re.IGNORECASE),
    re.compile(r"\[system\]", re.IGNORECASE),
    re.compile(r"\[assistant\]", re.IGNORECASE),
    re.compile(r"<system>", re.IGNORECASE),
    re.compile(r"</system>", re.IGNORECASE),
]

MAX_QUERY_LENGTH = 500


def sanitize_query(query) -> str:
    """Strip injection patterns + cap length. Non-string/empty -> ''."""
    if not query or not isinstance(query, str):
        return ""
    sanitized = query[:MAX_QUERY_LENGTH]
    for pattern in INJECTION_PATTERNS:
        sanitized = pattern.sub("", sanitized)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized


# ============================================================================
# QUERY SYNONYMS
# ============================================================================
# One synonym list per programme. Each entry is (trigger phrases, expansion). When a
# trigger appears in the user's question, the expansion is appended to the search
# query and the LLM rewrite is skipped.
#
# RULE: expansions are KEYWORDS ONLY. No rupee amounts, salaries, CGPA values or DS
# course codes (PDSA, MLF, MLT, MLP, BDM, BA, TDS). Anything appended here must be
# findable in that programme's src/ folder, and hard-coded figures drift (issue #179).
# Hybrid search already matches a course code typed by the user from the question
# itself, so repeating it here adds nothing.
DS_QUERY_SYNONYMS = [
    (["grading policy", "grading formula", "grade calculation", "how is grade calculated", "marks distribution", "score calculation"],
     "grading formula score calculation GAA quiz end term OPPE weightage"),
    (["pdsa grading", "pdsa marks", "pdsa score"],
     "Programming Data Structures Algorithms grading formula quiz end term OPPE"),
    (["python grading", "python marks"],
     "Python programming grading formula OPPE PE1 PE2 quiz end term"),
    (["i grade", "incomplete grade", "i_op", "i_both"],
     "I grade incomplete I_OP I_BOTH absent end term OPPE fail next term"),
    (["quiz 1 syllabus", "quiz1 syllabus", "q1 syllabus"],
     "Quiz 1 syllabus weeks 1-4 content coverage"),
    (["quiz 2 syllabus", "quiz2 syllabus", "q2 syllabus"],
     "Quiz 2 Qz2 syllabus Week 5-8 Week 3-8 content coverage grading"),
    (["end term syllabus", "final exam syllabus", "et syllabus"],
     "End term exam syllabus weeks 1-12 full course content"),
    (["exam city change", "change exam center", "change quiz city", "edit exam city"],
     "exam city change registration different cities quiz end term each term"),
    (["answer review", "review answers", "see my answers", "check answers after exam"],
     "answer review exam results dashboard score release"),
    (["no quiz 1", "without quiz 1", "courses no quiz"],
     "courses without Quiz 1 Software Engineering Big Data"),
    (["no quiz 2", "without quiz 2"],
     "courses without Quiz 2 Python Programming C Big Data"),
    (["3 credits", "three credits", "3 credit subjects", "which subjects 3 credits"],
     "credits per course foundation 4 credits diploma degree 4 credits NPTEL 1-3 credits"),
    (["4 credits", "four credits"],
     "4 credits foundation courses diploma courses apprenticeship"),
    (["nptel credits", "nptel transfer", "how many nptel", "nptel credit transfer"],
     "NPTEL credit transfer maximum 8 credits 4-week 8-week 12-week per credit fee"),
    (["campus credits", "iitm campus courses"],
     "campus courses credit transfer maximum 24 credits CGPA requirement per credit fee"),
    (["diploma data science courses", "ds diploma courses", "data science diploma subjects"],
     "Diploma Data Science courses Machine Learning Foundations Techniques Practice Business Data Management Analytics Tools"),
    (["diploma programming courses", "dp diploma courses", "programming diploma subjects"],
     "Diploma Programming courses DBMS Data Structures Algorithms Java System Commands AppDev"),
    (["foundation courses", "foundation subjects", "year 1 courses"],
     "Foundation courses Maths 1 2 Statistics 1 2 English 1 2 Python Computational Thinking"),
    (["degree courses", "bsc courses", "bs courses"],
     "Degree level courses Software Engineering Testing AI Deep Learning electives"),
    (["core pairs", "mandatory pairs"],
     "core pairs Software Engineering Testing AI Search Deep Learning degree level"),
    (["prerequisites", "prereq", "pre-requisite"],
     "prerequisites course requirements Maths Statistics English Python foundation diploma"),
    (["registration date", "important dates", "academic calendar", "term start", "term dates", "registration deadline"],
     "registration dates academic calendar term start important dates admissions timeline course registration deadline"),
    (["direct entry", "dad", "direct admission diploma", "skip foundation"],
     "Direct Admission Diploma DAD 2 years UG qualifier exam fee"),
    (["jee entry", "jee admission", "jee advanced"],
     "JEE Advanced direct entry foundation level skip qualifier"),
    (["eligibility", "who can apply", "qualification required"],
     "eligibility Class 12 passed Mathematics English Class 10 any age any stream"),
    (["qualifier exam", "qualifier process", "how to qualify"],
     "qualifier exam 4 weeks preparation application fee process"),
    (["fee waiver", "scholarship", "fee reduction", "concession"],
     "fee waiver SC ST PwD OBC-NCL EWS income 50% 75% waiver"),
    (["fee waiver documents", "documents for waiver", "waiver proof"],
     "fee waiver documents category certificate income certificate PwD certificate"),
    (["army fee waiver", "defense fee waiver", "military fee waiver"],
     "fee waiver army defense General category income based EWS 50% 75% waiver"),
    (["total fee", "programme fee", "course fee", "how much fee"],
     "fee structure total programme cost Foundation Diploma BSc BS level-wise fees"),
    (["international fee", "foreign student fee", "outside india fee"],
     "international students facilitation fee quiz end term additional fee"),
    (["hard copy certificate", "original certificate", "physical certificate"],
     "original certificate hard copy alumni registration fee exit form processing"),
    (["transcript", "mark sheet", "grade card"],
     "transcript academic record grades courses completed CGPA"),
    (["oppe", "online proctored", "programming exam"],
     "OPPE Online Proctored Programming Exam remote proctored coding"),
    (["sct", "system compatibility", "compatibility test"],
     "SCT System Compatibility Test mandatory before OPPE camera microphone check"),
    (["placement eligibility", "when placement", "eligible for placement"],
     "placement eligibility internship after 1 diploma job after BSc degree"),
    (["average salary", "placement salary", "package"],
     "placement salary average highest package internship stipend"),
    (["companies", "recruiters", "which companies"],
     "recruiters Amazon Microsoft Deloitte Wipro TCS companies placement"),
    (["repeat course", "fail course", "retake"],
     "repeat course fail full fee again all assessments next term"),
    (["probation", "struck off", "removed"],
     "academic probation 2 terms struck off 3 terms without registration readmission"),
    (["chatgpt", "llm", "ai help", "plagiarism"],
     "LLM ChatGPT plagiarism honor code violation not allowed assignments"),
    (["masters", "mtech", "ms", "phd", "higher studies"],
     "Masters MTech MS PhD GATE CFTI route CGPA requirement research campus upgrade"),
]

# ES, MG and AE corpora are all about the qualifier and admission process, so their
# lists share a shape. They are kept separate on purpose: the eligibility rules and
# Week 1 subjects differ per programme, and a future edit to one must not leak to the
# others. Written from the front-matter of src/<program_id>/*.md.
ES_QUERY_SYNONYMS = [
    (["eligibility", "who can apply", "qualification required", "am i eligible"],
     "eligibility Class 12 Physics Mathematics Class 11 NIOS Electronic Systems qualifier"),
    (["physics and maths", "physics mathematics", "pcm required", "need physics"],
     "Physics Mathematics Class 12 requirement BS Electronic Systems eligibility NIOS"),
    (["multiple programs", "apply for two programs", "ds and es together", "more than one program"],
     "multiple programme application restriction apply one programme at a time"),
    (["jee entry", "jee admission", "jee advanced", "direct entry"],
     "JEE Advanced direct entry Foundation Level proof validation admission cycle CCC"),
    (["regular entry", "admission process", "how to join", "how to get admission", "admission paths"],
     "admission paths regular entry qualifier process JEE-based entry Foundation Level"),
    (["qualifier exam", "qualifier process", "how to qualify", "qualifier preparation"],
     "qualifier process 4 weeks Week 1 content videos tutorials graded assignments exam"),
    (["qualifier registration", "register for qualifier", "application form", "how to apply"],
     "qualifier registration form official website Week-1 content application fee JEE eligibility"),
    (["qualifier fee", "application fee", "how much fee", "total fee", "programme fee", "course fee"],
     "qualifier application fee category-wise fee re-attempt fee non-refundable fresh application"),
    (["refund", "fee refund", "money back"],
     "non-refundable fee policy qualifier application fee refund rules"),
    (["assignment", "weekly assignment", "assignment cutoff", "hall ticket"],
     "weekly graded assignments assignment score cutoff category-wise hall ticket eligibility"),
    (["passing criteria", "cutoff", "cut off", "pass marks", "qualifying marks"],
     "qualifier passing criteria subject cut-off total cut-off category-wise relaxation"),
    (["reattempt", "re-attempt", "second attempt", "failed qualifier", "absent for qualifier"],
     "qualifier reattempt policy two attempts per term reattempt fee reattempt application form"),
    (["result", "qualifier result", "marks", "score validity", "admission letter"],
     "qualifier results marks portal email WhatsApp admission letter score validity 3 terms"),
    (["course registration", "foundation registration", "register for courses", "how many courses", "exam city"],
     "Foundation Level registration same-term subsequent-term prerequisites maximum courses exam city"),
    (["about the program", "program overview", "exit levels", "is it online", "which programs"],
     "programme overview BS programmes online content in-person exams exit levels Foundation Diploma Degree"),
]

MG_QUERY_SYNONYMS = [
    (["eligibility", "who can apply", "qualification required", "am i eligible"],
     "eligibility Class 10 Maths English Class 12 Class 11 Foundation Level qualifier"),
    (["class 10 maths", "maths and english", "class 10 english", "need maths"],
     "Class 10 Maths English requirement MG qualifier eligibility"),
    (["multiple programs", "apply for two programs", "ds and mg together", "more than one program"],
     "multiple programme application restriction apply one programme at a time"),
    (["jee entry", "jee admission", "jee advanced", "direct entry"],
     "JEE Advanced direct entry Foundation Level proof validation admission cycle CCC"),
    (["regular entry", "admission process", "how to join", "how to get admission", "admission paths"],
     "admission paths regular entry qualifier process 4 weeks invalid JEE proof conversion"),
    (["qualifier exam", "qualifier process", "how to qualify", "qualifier preparation"],
     "qualifier process 4 weeks MG qualifier subjects Week 1 content graded assignments exams week 4 week 8"),
    (["qualifier registration", "register for qualifier", "application form", "how to apply"],
     "qualifier registration form Week-1 sample content fee payment reattempt application form"),
    (["qualifier fee", "application fee", "how much fee", "total fee", "programme fee", "course fee"],
     "qualifier application fee category-wise fee reattempt fee fresh attempt fee course credit payment pay per credit"),
    (["refund", "fee refund", "money back"],
     "non-refundable fee policy qualifier application fee refund rules"),
    (["assignment", "weekly assignment", "assignment cutoff", "hall ticket"],
     "weekly graded assignments assignment score cutoff category-wise hall ticket eligibility course access revoked"),
    (["passing criteria", "cutoff", "cut off", "pass marks", "qualifying marks"],
     "qualifier exam passing criteria subject cutoff total cutoff category-wise relaxation"),
    (["reattempt", "re-attempt", "second attempt", "failed qualifier", "absent for qualifier"],
     "qualifier reattempt two attempts within a term reattempt eligibility reattempt fee fresh application"),
    (["result", "qualifier result", "marks", "score validity", "admission letter"],
     "qualifier results marks email WhatsApp portal admission letter score validity Quiz 1 qualifier score used as Quiz 1"),
    (["course registration", "foundation registration", "register for courses", "how many courses", "exam city"],
     "Foundation Level registration same-term subsequent-term prerequisites maximum courses exam city Quiz 1 credits"),
    (["about the program", "program overview", "exit levels", "is it online", "which programs"],
     "programme overview BS programmes online learning in-person exams exit levels credentials BS degree credits"),
]

AE_QUERY_SYNONYMS = [
    (["eligibility", "who can apply", "qualification required", "am i eligible"],
     "eligibility Class 12 Physics Mathematics Class 11 AE qualifier JEE Advanced prerequisites"),
    (["physics and maths", "physics mathematics", "pcm required", "need physics"],
     "Physics Mathematics Class 12 requirement AE qualifier eligibility"),
    (["multiple programs", "apply for two programs", "ds and ae together", "more than one program"],
     "multiple programme application restriction apply one programme at a time"),
    (["jee entry", "jee admission", "jee advanced", "direct entry"],
     "JEE Advanced direct entry Foundation Level proof validation admission cycle CCC admission letter"),
    (["regular entry", "admission process", "how to join", "how to get admission", "admission paths"],
     "admission paths regular entry qualifier process JEE-based entry Foundation Level"),
    (["qualifier exam", "qualifier process", "how to qualify", "qualifier preparation"],
     "qualifier process 4 weeks AE Week-1 Foundation courses videos tutorials graded assignments exam after four weeks"),
    (["qualifier registration", "register for qualifier", "application form", "how to apply"],
     "qualifier registration form official website Week-1 sample content application fee AE qualifier conditions JEE proof"),
    (["qualifier fee", "application fee", "how much fee", "total fee", "programme fee", "course fee"],
     "qualifier application fee category-wise fee re-attempt fee non-refundable international facilitation fee credit-based course payment"),
    (["refund", "fee refund", "money back"],
     "non-refundable fee policy qualifier application fee refund rules"),
    (["assignment", "weekly assignment", "assignment cutoff", "hall ticket"],
     "weekly graded assignments assignment score cutoff category-wise hall ticket eligibility Quiz 1 requirement"),
    (["passing criteria", "cutoff", "cut off", "pass marks", "qualifying marks"],
     "qualifier pass criteria subject cutoff total cutoff category-wise relaxation Quiz 1 score treatment"),
    (["reattempt", "re-attempt", "second attempt", "failed qualifier", "absent for qualifier"],
     "qualifier reattempt same-term attempts eligibility after absence or failure reattempt fee fresh application"),
    (["result", "qualifier result", "marks", "score validity", "admission letter"],
     "qualifier results marks email WhatsApp portal admission letter score validity 3 terms"),
    (["course registration", "foundation registration", "register for courses", "how many courses", "exam city"],
     "Foundation Level registration same-term subsequent-term prerequisites maximum courses exam city course access revoked"),
    (["about the program", "program overview", "exit levels", "is it online", "which programs"],
     "programme overview BS programmes online learning in-person quizzes exams exit levels Foundation Diploma Degree"),
]

PROGRAM_QUERY_SYNONYMS = {
    "ds": DS_QUERY_SYNONYMS,
    "es": ES_QUERY_SYNONYMS,
    "mg": MG_QUERY_SYNONYMS,
    "ae": AE_QUERY_SYNONYMS,
}

# Compile each synonym into a case-insensitive whole-word regex for query matching.
# For example: "Can you explain the grading policy?" can be rewritten using the canonical query: "grading formula score calculation GAA quiz end term OPPE weightage"
COMPILED_SYNONYMS = {
    program_id: [
        ([re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE) for p in patterns], canonical)
        for patterns, canonical in entries
    ]
    for program_id, entries in PROGRAM_QUERY_SYNONYMS.items()
}

# Condensed knowledge base summaries used as query-rewriting context, one per
# programme. Each numbered line describes one file in src/<program_id>/, in filename
# order, so the rewrite model is only told about topics that programme's corpus has.
# HAND-WRITTEN: when a file is added to or removed from src/<program_id>/, update the
# matching summary here (a test checks that the line count equals the file count).
DS_KNOWLEDGE_BASE_SUMMARY = """Topics available in knowledge base:
1. About IIT Madras BS Program: program overview, four BS programmes (DS, ES, MG, AE), online learning with in-person exams, programme levels, exit points, certificates and degrees, official website and contact details
2. JEE-Based Entry: admission pathways, direct entry using JEE Advanced eligibility, validity period, application process, proof upload, benefits like skipping qualifier, CCC of 4, entry type restrictions
3. Academic Level Progression and Rules: Foundation, Diploma, Degree progression, credit requirements (32, 59, 86, 114, 142, 162, 182), cannot take courses across levels, U grade, re-registration, prerequisites, CGPA impact, exit pathways
4. Qualifier Assignments and Cutoff: assignment grading rules, minimum assignment scores by category, qualifier exam cutoffs, category-wise relaxations, hall ticket eligibility, first and second attempt eligibility rules
5. Academic Structure and Exams: quizzes and end-term exams, exam structure, eligibility requirements, attendance through assignments, exam rules, refund policy, non-refundable fees, academic guidelines
6. Qualifier Eligibility: eligibility for DS, MG, ES, AE programs, Class 10 Maths and English, Class 12 requirements, Physics and Mathematics for ES/AE, Class 11 eligibility, NIOS pathway, no age restriction
7. BS in Electronic Systems Program: ES program overview, eligibility requirements, qualifier subjects, registration process, differences from Data Science, restriction on switching programs
8. Qualifier Exam Format and Centers: exam format (MCQ, MSQ, numerical, short answer), 4-hour duration, no negative marking, exam cities, in-person India exams, remote proctored international exams, required documents
9. Contact and Support Information: support emails for DS, ES, AE, MG, qualifier support, Global Entry contact, phone number, office address, when to contact support, chatbot scope and limitations
10. Qualifier Exam Overview: 4-week qualifier process, weekly content release, videos, tutorials, graded assignments, sample Week-1 access, self-paced learning structure
11. Course Registration Process: course selection steps, exam city selection, prerequisite checks, payment process, same-term and subsequent-term registration rules, maximum 4 courses, qualifier score usage
12. Qualifier Reattempts: attempts within a term, eligibility for reattempt, reattempt process, fee structure by category, assignment carry-forward rules, reattempt in future terms
13. Fees and Payments: qualifier fees, reattempt fees, per-course fees, total program cost by level, online payment rules, fee waivers, international facilitation fees, refund rules
14. Qualifier Results and Validity: result communication via portal/email/WhatsApp, admission letter, validity for 3 terms, Class 12 special rule, expiry rules, registration after qualifying
15. International Students Information: eligibility for foreign students, remote proctored exams, IST timing, additional fees, required documents, payment issues, Global Entry support
16. Working Professionals and Parallel Study: studying alongside job or degree, flexible schedule, pre-recorded lectures, weekly time commitment, in-person exams, taking breaks, self-study approach
"""

ES_KNOWLEDGE_BASE_SUMMARY = """Topics available in knowledge base:
1. Admission Paths: regular entry through the qualifier process, JEE-based direct entry to Foundation Level, JEE Advanced proof validation, admission cycles by JEE qualification year
2. Assignment and Exam Eligibility: weekly graded assignments, qualifier exam eligibility, assignment scoring and missed assignments, category-wise assignment cutoffs, hall ticket release, official communication channels
3. Eligibility Requirements: one programme application at a time, BS in Electronic Systems qualifier eligibility, Class 11 and Class 12 conditions, Physics and Mathematics requirement, NIOS or equivalent, JEE Advanced direct entry eligibility
4. Foundation Course Registration: registration after qualifier results, same-term and subsequent-term rules, JEE direct course registration, course prerequisites and limits, quiz and exam city selection, payment, progression to Diploma and Degree levels
5. Programme Overview: aims of the IIT Madras BS programmes, offered programmes, online content with in-person exams, rigour, exit levels, Foundation to Diploma to Degree progression
6. Qualifier Fees: qualifier application fee, category-wise fee amounts, re-attempt fees, non-refundable fee policy, full fee for fresh applications in later terms
7. Qualifier Passing Criteria: qualifier exam subjects, individual subject cut-off, total cut-off, category-wise passing scores, relaxations that apply to the qualifier process only
8. Qualifier Preparation: 4-week qualifier process, Week 1 course content, weekly content release, graded assignments, portal and email announcements, handling of invalid JEE proof
9. Qualifier Registration: registration form on the official website, Week-1 sample content access, application fee timing, JEE Advanced eligibility selection
10. Reattempt Policy: two attempts within a term, reattempt after absence or failure, exams at end of week 4 and week 8, reattempt application form and fees, unlimited qualifier process attempts, fresh application in later terms
11. Score Validity and Results: qualifier marks and result alerts, validity for 3 terms, expiry and retaking the qualifier, official communication channels, admission letter, example validity terms, no reattempt after qualifying
"""

MG_KNOWLEDGE_BASE_SUMMARY = """Topics available in knowledge base:
1. Assignment Eligibility: weekly graded assignments, zero for missed assignments, first and second qualifier attempt eligibility, category-wise assignment cutoffs, hall ticket eligibility, reattempt assignment rules, course access revocation
2. Eligibility Requirements: one programme application at a time, Class 10 Maths and English requirement, Class 11 and Class 12 eligibility, Foundation Level eligibility, qualifier score validity for current Class 12 students
3. Exam Passing Criteria: qualifier exam subject and total cutoffs, category-wise passing criteria, relaxations limited to the qualifier process, two attempts within a term, reattempt eligibility, non-refundable fee condition, same-term registration after qualifying
4. Fees and Payments: qualifier application fee, category-wise fees, non-refundable fee policy, reattempt fees, fresh attempt fees, paying only for course credits signed up for
5. Foundation Registration: registration after qualifier or JEE-based entry, same-term and subsequent-term timing, prerequisites and maximum courses, exam city choices, Quiz 1 and assignment requirements, credits and payments, progression to Diploma and Degree levels
6. JEE-Based Entry: direct admission to Foundation Level, JEE Advanced eligibility, admission cycles by JEE qualification year, proof upload and validation, Foundation registration with CCC of 4
7. Programme Overview: aims of the IIT Madras BS programmes, available programmes, online learning with in-person exams, academic rigour, exit levels and credentials, admission paths, BS degree credit requirements
8. Qualifier Preparation: 4-week qualifier process, MG qualifier subjects, weekly videos, tutorials, assignments and transcripts, weekly graded assignment submission, qualifier exams at week 4 and week 8
9. Qualifier Registration: registration form, Week-1 sample content access, fee payment during registration, reattempt application form, unlimited qualifier process attempts, fresh application and full fee rules, JEE proof
10. Regular Entry: regular entry admission path, qualifier process requirement, 4-week qualifier process, invalid JEE proof converted to regular entry
11. Results and Communication: qualifier marks display, email, WhatsApp and portal alerts, official communication channels, hall ticket release updates, admission letter generation, reattempt form timing
12. Score Validity: qualifier score valid for the current and next two terms, invalid score rules, term examples for 2026 exams, Class 12 validity rule, no reattempt after qualifying, qualifier score used as Quiz 1 score
"""

AE_KNOWLEDGE_BASE_SUMMARY = """Topics available in knowledge base:
1. Admission Paths: regular entry through the qualifier process, JEE-based direct entry to Foundation Level, JEE admission cycles and proof validation, admission letter and direct Foundation registration with CCC of 4
2. Course Registration: Foundation Level registration after qualifying, same-term and subsequent-term registration, Quiz 1 and qualifier score rules, prerequisites and maximum courses per term, exam city selection, registration dates, course access revocation
3. Eligibility Criteria: one programme application at a time, Class 11 and Class 12 eligibility, Physics and Mathematics requirement for AE, JEE Advanced admission cycle eligibility, course prerequisite and level progression criteria
4. Exam Eligibility: assignment grading and zero for missed assignments, first and second qualifier attempt eligibility, category-wise assignment cutoffs, hall ticket eligibility and release, assignments and Quiz 1 requirements after registration
5. Fees and Payments: qualifier application fees by category, non-refundable fee rules, re-attempt fees by category, full fee for fresh applications in later terms, international exam facilitation fee, credit-based course payment
6. Passing Criteria: qualifier exam subject and total cutoffs, category-wise pass criteria, relaxations limited to the qualifier process, Quiz 1 score treatment for same-term and later registrations
7. Programme Overview: aims and structure of the IIT Madras BS programmes, online learning with in-person quizzes and exams, programme list and exit credentials, Foundation to Diploma to Degree progression, quality compared with regular IIT Madras degrees
8. Qualifier Preparation: 4-week qualifier process, AE Week-1 Foundation courses, videos, tutorials, assignments and transcripts, weekly graded assignment submission, qualifier exam after four weeks
9. Qualifier Registration: registration form on the official website, Week-1 sample content access, application fee timing, regular entry qualifier requirement, AE qualifier conditions, JEE proof submission
10. Reattempt Policy: same-term qualifier reattempts, eligibility after absence or failure, reattempt application form timing, reattempt and non-refundable fees, score validity restrictions, unlimited qualifier process attempts, fresh application in later terms
11. Results Communication: email, WhatsApp and student portal communication, qualifier marks display and alerts, admission letter generation, JEE-based admission letter, reattempt form opening after results
12. Score Validity: qualifier score valid for 3 terms, invalid from the fourth term, Class 12 student validity rule, no reattempt during score validity, term examples for 2026 qualifier exam dates
"""

KNOWLEDGE_BASE_SUMMARIES = {
    "ds": DS_KNOWLEDGE_BASE_SUMMARY,
    "es": ES_KNOWLEDGE_BASE_SUMMARY,
    "mg": MG_KNOWLEDGE_BASE_SUMMARY,
    "ae": AE_KNOWLEDGE_BASE_SUMMARY,
}


def knowledge_base_summary(program_id: str = DEFAULT_PROGRAM_ID) -> str:
    """Return the topic list for one programme's corpus, used by the rewrite prompt.

    Falls back to the DS summary for an unknown id, like program_config does, so a
    display-only caller can never break a request.

    Example: knowledge_base_summary("es") lists the 11 topics in src/es/.
    """
    return KNOWLEDGE_BASE_SUMMARIES.get(program_id, KNOWLEDGE_BASE_SUMMARIES[DEFAULT_PROGRAM_ID])

STOPWORDS_TO_IGNORE = {"may", "not", "no", "only", "free", "all"}

STOPWORDS = {
    "a", "an", "the",
    "i", "me", "my", "we", "our", "you", "your", "it", "its",
    "is", "are", "was", "were", "am", "be", "been", "being",
    "do", "does", "did", "done",
    "will", "would", "could", "should", "shall",
    "have", "has", "had",
    "what", "where", "when", "how", "which", "who", "whom", "why",
    "this", "that", "these", "those",
    "and", "but", "or", "so",
    "to", "of", "in", "on", "at", "by", "with", "from", "as", "into", "for",
    "please", "tell", "give", "let", "know", "want", "need", "get", "got",
    "there", "here", "just", "also", "very", "if", "then", "any", "some",
}


def remove_stop_words(query: str) -> str:
    """Remove common filler words before synonym matching and retrieval.

    Words such as "the"" and "how" are removed, while important words such
    as "not" and "only" are kept. If every word would be removed, return
    the original query so the search still has useful input.

    Example: "What is the grading policy?" becomes
    "grading policy?".
    """
    words = re.split(r"\s+", query.strip())
    filtered = []
    for word in words:
        lower = re.sub(r"[?!.,]+$", "", word.lower())
        if lower in STOPWORDS_TO_IGNORE:
            filtered.append(word)
            continue
        if lower in STOPWORDS:
            continue
        filtered.append(word)
    result = " ".join(filtered).strip()
    return result if len(result) > 0 else query


def find_synonym_match(query: str, program_id: str = DEFAULT_PROGRAM_ID) -> Optional[str]:
    """Return the expansion for the first matching synonym of ONE programme, else None.

    Only that programme's list is searched, so a DS-only trigger can never add DS
    keywords to an ES, MG or AE search query.

    Example: find_synonym_match("pdsa grading", "ds") -> "Programming Data Structures ..."
             find_synonym_match("pdsa grading", "es") -> None
    """
    entries = COMPILED_SYNONYMS.get(program_id, COMPILED_SYNONYMS[DEFAULT_PROGRAM_ID])
    for regexes, canonical_query in entries:
        for regex in regexes:
            if regex.search(query):
                return canonical_query
    return None


# ============================================================================
# "DID YOU MEAN?" FAQ SUGGESTIONS
# ============================================================================
def format_db_faq_suggestions(db_faqs, language: str = "english") -> str:
    if not db_faqs:
        return ""
    did_you_mean = {
        "english": "**Did you mean:**",
        "hindi": "**क्या आपका मतलब था:**",
        "tamil": "**நீங்கள் கருதுவது:**",
        "hinglish": "**Kya aap ye poochna chahte the:**",
    }
    header = did_you_mean.get(language, did_you_mean["english"])
    suggestions = "\n".join(
        f"{i + 1}. {faq['question']} [FAQID:{faq['id']}]" for i, faq in enumerate(db_faqs[:5])
    )
    return f"\n\n{header}\n\n{suggestions}"


# ============================================================================
# RAAHAT (mental-health) content handling
# ============================================================================
def contains_raahat(text: str) -> bool:
    lower_text = (text or "").lower()
    return (
        "raahat" in lower_text
        or "wellness.society@study.iitm.ac.in" in lower_text
        or "@wellness.society_iitmbs" in lower_text
        or "mental health & wellness society" in lower_text
    )


RAAHAT_KEYWORDS = [
    "raahat",
    "wellness.society@study.iitm.ac.in",
    "@wellness.society_iitmbs",
    "mental health",
    "wellness society",
    "support is available",
    "you're not alone",
    "don't hesitate to contact",
]


def split_raahat_content(text: str) -> dict:
    if not contains_raahat(text):
        return {"raahat_chunk": "", "other_chunk": text, "has_raahat": False}

    raahat_lines = []
    other_lines = []
    for line in text.split("\n"):
        lower_line = line.lower()
        if any(keyword in lower_line for keyword in RAAHAT_KEYWORDS):
            raahat_lines.append(line)
        else:
            other_lines.append(line)

    return {
        "raahat_chunk": "\n".join(raahat_lines).strip(),
        "other_chunk": "\n".join(other_lines).strip(),
        "has_raahat": len(raahat_lines) > 0,
    }


def count_statements(text: str) -> int:
    if not text:
        return 0
    count = 0
    for line in text.split("\n"):
        trimmed = line.strip()
        if len(trimmed) > 0 and not trimmed.startswith("#") and len(trimmed) > 5:
            count += 1
    return count
