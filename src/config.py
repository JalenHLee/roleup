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
