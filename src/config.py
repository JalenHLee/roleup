"""Tunable settings for Roleup. No logic lives here.

All patterns are Python regexes matched against the lowercased job title.
"""

# Recruiting terms to keep. Change "Summer 2027" to "Summer 2028" next year.
# "N/A" listings are kept and labeled term="unknown".
TARGET_TERMS = ["Summer 2027", "N/A"]

# Simplify's structured listings file (lives on the repo's dev branch).
SIMPLIFY_LISTINGS_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships"
    "/dev/.github/scripts/listings.json"
)

# Titles signalling a full-time / senior role rather than an internship.
NON_INTERN_PATTERNS = [
    r"\bsenior\b",
    r"\bsr\b",
    r"\bstaff\b",
    r"\bprincipal\b",
    r"\bdirector\b",
    r"\bhead of\b",
    r"\bvp\b",
    r"full[- ]time",
    r"new grad",
]

# Titles in these functions are dropped even if they mention "product",
# "growth", "operations", etc. (e.g. "Backend Software Engineer - Product").
EXCLUDE_PATTERNS = [
    r"engineer",  # also matches "engineering"
    r"developer",
    r"software",
    r"design",  # also matches "designer"
    r"data scien",
    r"machine learning",
    r"research",
    r"quant",  # also matches "quantitative"
    r"hardware",
    r"firmware",
    r"security",
    r"\bml ?ops\b",  # ML infrastructure, not operations
    r"\bmlops\b",
    r"\boptions\b",  # options trading roles
    r"\bstore operations\b",  # retail store roles
]

# Unambiguous PM titles. These override EXCLUDE_PATTERNS, so
# "Product Manager Intern - Engineering Platform" is still kept.
STRONG_PM_PATTERNS = [
    r"product manag",  # manager / management
    r"\bapm\b",
    r"associate product manager",
    r"product owner",
]

# Ordered (category, patterns) rules. The first matching rule wins.
CATEGORY_RULES = [
    ("PMM", [r"product marketing"]),
    ("PM", [
        r"product manag",
        r"offering manag",  # Honeywell-style name for PM
        r"\bapm\b",
        r"associate product",
        r"product owner",
        r"product analyst",
        r"product intern",
        r"product development",
        r"product strategy",
    ]),
    ("Growth", [r"growth"]),
    # Before Strategy so "Strategy & Operations" lands in Operations.
    ("Operations", [
        r"product operations",
        r"business operations",
        r"bizops",
        r"operations",
        r"\bops\b",
    ]),
    ("Strategy", [r"strategy", r"strategic"]),
    # Catch-all for recall: anything else mentioning "product".
    ("Product (other)", [r"product"]),
]

# --- Jobright -------------------------------------------------------------

# Jobright's PM internship list. It only shows the last 7 days, so run daily.
JOBRIGHT_README_URL = (
    "https://raw.githubusercontent.com/jobright-ai/2026-Product-Management-Internship"
    "/master/README.md"
)

# --- Term inference from titles (Jobright and alert emails) ---------------
# These sources have no term field, so the term is inferred from the title.
# A title matching any of these gets term="Summer 2027".
TITLE_TARGET_TERM_PATTERNS = [r"summer 2027", r"2027 summer"]

# Off-cycle titles are dropped, unless they also match a target pattern
# (e.g. "Fall 2026/Spring- Summer 2027" is kept).
TITLE_OFF_CYCLE_PATTERNS = [r"fall 2026", r"\bwinter\b", r"\bspring\b", r"\bco-?op\b"]

# --- Dedupe (role_id normalization) ----------------------------------------
# These are matched as whole words after lowercasing and replacing
# punctuation with spaces, so write them without punctuation.

# Term phrases removed from titles. Bare years (e.g. "2027") are also removed.
ROLE_ID_TERM_PHRASES = ["summer 2027", "2027 summer", "2027 start"]

ROLE_ID_INTERN_WORDS = ["internship", "intern"]

# Country tokens some sources append to titles ("..., 2027 Summer U.S.").
# Degree markers like "MBA" are deliberately NOT here: those are different roles.
ROLE_ID_TITLE_NOISE = ["united states", "usa", "u s", "us"]

ROLE_ID_COMPANY_SUFFIXES = ["inc", "llc", "ltd", "corp", "group"]

# Normalized company name -> canonical name, applied after suffix removal.
COMPANY_ALIASES = {"nissan motor corporation": "nissan"}

# --- Alert emails (LinkedIn, Early Career Radar) ---------------------------
# Credentials come from env vars only: GMAIL_ADDRESS, GMAIL_APP_PASSWORD, ANTHROPIC_API_KEY.

GMAIL_LABEL = "job-alerts"  # Gmail label = IMAP folder name
EMAIL_LOOKBACK_DAYS = 2  # stateless: re-read recent emails each night; dedupe absorbs repeats

# Model that extracts roles from alert emails.
LLM_MODEL = "claude-haiku-5-5"

# Sender domain -> source name. Subdomains match too (e.g. e.linkedin.com).
SENDER_SOURCES = {
    "linkedin.com": "linkedin",
    "earlycareerradar.com": "early-career-radar",
}
