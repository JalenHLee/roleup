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

# A title matching a category's excludes can't take that category; it falls
# through to the next rules (so "Product Strategy" can still be PM).
CATEGORY_EXCLUDES = {
    "Strategy": [
        r"\bsystematic\b",  # quant/trading strategies
        r"multi-strategy",  # hedge-fund platforms
        r"\btrading\b",
        r"investment strateg",  # strategy / strategies
    ],
    "Operations": [
        r"mission operations",  # aerospace
        r"field operations",
        r"power system operations",
        r"flight operations",
        r"security operations",
        r"\bit operations\b",
        r"\btrading\b",  # trading-desk operations
    ],
}

# --- Jobright -------------------------------------------------------------

# Jobright's PM internship list. It only shows the last 7 days, so run daily.
JOBRIGHT_README_URL = (
    "https://raw.githubusercontent.com/jobright-ai/2026-Product-Management-Internship"
    "/master/README.md"
)

# --- Term check from titles (all sources) ----------------------------------
# Jobright and alert emails have no term field, so a title matching any of
# these gets term="Summer 2027" (else "unknown").
TITLE_TARGET_TERM_PATTERNS = [r"summer 2027", r"2027 summer"]

# Off-cycle titles are dropped by the term layer (src/pipeline.py), for every source.
# STRONG: dropped unless the title also says Summer 2027, even if the source
# tagged it Summer 2027 (e.g. Simplify-tagged "Spring 2027 Product Intern").
TITLE_OFF_CYCLE_STRONG = [
    r"\bfall 2026\b", r"\b2026 fall\b",
    r"\bspring 2027\b", r"\b2027 spring\b",
    r"\bwinter\b",
    r"\boff[- ]cycle\b",
    r"\b2026 start\b",
]
# WEAK: dropped only when the term is unknown; a source-tagged Summer 2027
# role is kept (e.g. "Product Management Intern/Co-op").
TITLE_OFF_CYCLE_WEAK = [r"\bco[- ]?op\b", r"\bpart[- ]time\b"]

# --- Dedupe (role_id normalization) ----------------------------------------
# These are matched as whole words after lowercasing and replacing
# punctuation with spaces, so write them without punctuation.

# Term phrases removed from titles. Bare years (e.g. "2027") are also removed.
ROLE_ID_TERM_PHRASES = ["summer 2027", "2027 summer", "2027 start"]

ROLE_ID_INTERN_WORDS = ["internship", "intern"]

# Country tokens some sources append to titles ("..., 2027 Summer U.S.").
# Degree markers like "MBA" are deliberately NOT here: those are different roles.
# "Multiple Teams" is a team-picker suffix (Coinbase), not a different role.
ROLE_ID_TITLE_NOISE = ["multiple teams", "united states", "usa", "u s", "us"]

ROLE_ID_COMPANY_SUFFIXES = ["inc", "llc", "ltd", "corp", "group", "holdings"]

# Normalized company name -> canonical name, applied after suffix removal.
COMPANY_ALIASES = {
    "nissan motor corporation": "nissan",
    "white cap canada": "white cap",
}

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

# --- Links -------------------------------------------------------------------
# Query params stripped by links.canonicalize (matched case-insensitively).
# Any param starting with "utm_" is stripped too.
TRACKING_PARAMS = [
    "trackingId", "refId", "lipi", "midToken", "midSig",
    "trk", "trkEmail", "eid", "otpToken",
]

# --- Location (US-only, unclear kept) ---------------------------------------
# Used by src/location.py, and by dedupe to strip " - City, ST" from titles.
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

# A location segment matching any of these counts as US (checked first, so
# "London, KY" stays US). State codes/names are checked separately.
US_LOCATION_PATTERNS = [r"\bunited states\b", r"\busa\b", r"\bu\.?s\.?a?\b", r"\bamerica\b"]

# A segment matching these (and no US pattern) is clearly non-US. Anything
# else is "unclear" and kept. A role is dropped only if ALL segments are non-US.
NON_US_LOCATION_PATTERNS = [
    r"\bcanada\b", r"\bontario\b", r"\bquebec\b", r"\bbritish columbia\b", r"\balberta\b",
    r",\s*(on|bc|ab|qc|ns|mb|sk)\b",  # Canadian province codes after a comma
    r"\btoronto\b", r"\bmontr[eé]al\b", r"\bvancouver\b", r"\bcalgary\b", r"\bmarkham\b",
    r"\bottawa\b", r"\bwaterloo\b", r"\bkitchener\b", r"\bburnaby\b", r"\bmississauga\b",
    r"\buk\b", r"\bunited kingdom\b", r"\bengland\b", r"\bscotland\b", r"\bwales\b",
    r"\bireland\b", r"\blondon\b", r"\bmanchester\b", r"\bedinburgh\b", r"\bdublin\b",
    r"\bindia\b", r"\bbengaluru\b", r"\bbangalore\b", r"\bhyderabad\b", r"\bmumbai\b",
    r"\bpune\b", r"\bgurgaon\b", r"\bgurugram\b", r"\bnoida\b", r"\bchennai\b",
    r"\bmexico\b", r"\bbrazil\b", r"\bgermany\b", r"\bfrance\b", r"\bnetherlands\b",
    r"\bspain\b", r"\bpoland\b", r"\bsingapore\b", r"\bjapan\b", r"\bkorea\b", r"\bchina\b",
    r"\bhong kong\b", r"\btaiwan\b", r"\baustralia\b", r"\bisrael\b", r"\bphilippines\b",
]

# --- Eligibility --------------------------------------------------------------
# Title patterns (lowercased) for roles open only to grad students -> "grad-only".
# Plain "MS" is not here: "(BS/MS)" roles are open to undergrads.
GRAD_ONLY_TITLE_PATTERNS = [
    r"\bmba\b",  # also "MS or MBA"
    r"\bmaster'?s\b",
    r"\bmasters\b",
    r"\bgrad(uate)? intern",  # Grad Intern, Graduate Internship
    r"\bph\.?d\b",
]

# --- Google Sheet sync ----------------------------------------------------------
# Credentials come from env vars only: GOOGLE_SERVICE_ACCOUNT_JSON (the full JSON key)
# and SHEET_ID. Never commit either.

# The hand-kept tracker tab. READ-ONLY: Roleup never writes to it. Every row counts
# as already applied, whatever its Stage. Columns are found by header name.
TRACKER_TAB = "Job Tracker"
TRACKER_COMPANY_HEADER = "Company"
TRACKER_POSITION_HEADER = "Position"
TRACKER_URL_HEADER = "Job URL"

# Roleup's own tab, created if missing. Append-only: existing rows are never changed.
ROLEUP_TAB = "Roleup"
ROLEUP_HEADERS = [
    "Status", "First Seen", "Posted", "Category", "Company", "Title", "Location",
    "Term", "Sources", "Link", "Other Links", "Eligibility", "Notes", "Role ID",
]
ROLEUP_STATUSES = ["New", "Applied", "Skip", "Hidden"]  # Status dropdown
ROLEUP_ID_HEADER = "Role ID"

# "First Seen" is the run date in this time zone (the 18:00 UTC run is 3:00 KST).
RUN_TIMEZONE = "Asia/Seoul"
