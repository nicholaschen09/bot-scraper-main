"""Shared title / location filters for both watchers.

The target profile is a US-based general software engineering internship:
generic SWE, full-stack, frontend, backend, infrastructure/platform, and
product *engineering*. Product management, data science/ML, hardware, QA,
security, and non-engineering roles are out.

parse_boards.py uses only the location half (the Simplify board already
scopes rows to its Software Engineering section); ats_watcher.py uses both
halves, since an ATS board is one undifferentiated list of every open req.
"""

import re

INTERN_RE = re.compile(r"\bintern(ship)?\b|\bco[- ]?op\b", re.I)

# Titles that count as in-profile. Generic "Software Engineer Intern" is the
# common case — big companies rarely label the specialization — and EXCLUDE_RE
# below strips the ones that declare an out-of-profile focus.
ROLE_RE = re.compile(
    r"software (engineer|engineering|developer|development)|\bswe\b|"
    r"back[- ]?end|front[- ]?end|full[- ]?stack|"
    r"web (developer|development|engineer)|"
    r"product (engineer|engineering)|application(s)? (engineer|developer)|"
    r"\bdeveloper\b|server|infrastructure|\binfra\b|platform|dev[- ]?ops|"
    r"site reliability|\bsre\b|cloud|distributed",
    re.I,
)

EXCLUDE_RE = re.compile(
    r"mobile|\bios\b|android|"
    r"data scien|data analy|data engineer|analytics|business|"
    r"hardware|electrical|mechanical|manufactur|embedded|firmware|silicon|"
    r"\basic\b|fpga|\brf\b|optic|quality|\bqa\b|\btest\b|security|"
    r"research (scientist|engineer)|designer\b|\bux\b|user experience|"
    r"graphics|\bgame\b|quantitative|\bquant\b|"
    r"product manag|program manag|project manag|technical program|"
    r"marketing|sales|solutions|support|success|recruit|people|legal|"
    r"finance|accounting|supply chain|"
    r"advocate|evangelis|developer relations",
    re.I,
)

# AI/ML terms only disqualify when the title isn't clearly a software
# engineering role — "Software Engineer Intern, AI Platform" is in profile,
# "Machine Learning Intern" is not.
AI_EXCLUDE_RE = re.compile(
    r"machine learning|\bml\b|\bai\b|artificial intelligence|deep learning",
    re.I,
)

SWE_RE = re.compile(
    r"software (engineer|engineering|developer|development)|\bswe\b|"
    r"back[- ]?end|front[- ]?end|full[- ]?stack|product engineer|"
    r"infrastructure|\binfra\b|platform|dev[- ]?ops|site reliability|\bsre\b",
    re.I,
)

US_HINT_RE = re.compile(
    r"united states|\busa?\b|u\.s\.|remote.*(us|america)|"
    r"alabama|alaska|arizona|arkansas|california|colorado|connecticut|"
    r"delaware|florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|"
    r"kentucky|louisiana|maine|maryland|massachusetts|michigan|minnesota|"
    r"mississippi|missouri|montana|nebraska|nevada|new hampshire|"
    r"new jersey|new mexico|new york|north carolina|north dakota|ohio|"
    r"oklahoma|oregon|pennsylvania|rhode island|south carolina|"
    r"south dakota|tennessee|texas|utah|vermont|virginia|washington|"
    r"west virginia|wisconsin|wyoming|"
    r"san francisco|\bnyc\b|seattle|austin|boston|chicago|denver|atlanta|"
    r"los angeles|mountain view|palo alto|sunnyvale|san jose|menlo park|"
    r"bellevue|redmond|\bd\.?c\.?\b|miami|dallas|houston|philadelphia|"
    r"pittsburgh|portland|san diego|santa clara|cupertino|irvine|"
    r"nashville|charlotte|phoenix|salt lake|"
    r",\s?(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|"
    r"MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|"
    r"TN|TX|UT|VT|VA|WA|WV|WI|WY)\b",
    re.I,
)

NON_US_RE = re.compile(
    r"canada|ontario|toronto|vancouver|montr[eé]al|quebec|calgary|ottawa|"
    r"waterloo|british columbia|united kingdom|\buk\b|london|ireland|"
    r"dublin|germany|berlin|munich|france|paris|netherlands|amsterdam|"
    r"belgium|spain|madrid|barcelona|portugal|lisbon|italy|milan|"
    r"switzerland|zurich|geneva|austria|vienna|poland|warsaw|krakow|"
    r"czech|prague|sweden|stockholm|norway|oslo|denmark|copenhagen|"
    r"finland|helsinki|estonia|tallinn|romania|bucharest|hungary|"
    r"budapest|israel|tel aviv|\buae\b|dubai|abu dhabi|saudi|riyadh|"
    r"india|bangalore|bengaluru|hyderabad|mumbai|delhi|gurgaon|gurugram|"
    r"chennai|pune|noida|singapore|malaysia|kuala lumpur|indonesia|"
    r"jakarta|vietnam|thailand|bangkok|philippines|manila|china|beijing|"
    r"shanghai|shenzhen|hangzhou|hong kong|taiwan|taipei|japan|tokyo|"
    r"osaka|korea|seoul|australia|sydney|melbourne|brisbane|new zealand|"
    r"auckland|brazil|paulo|mexico|guadalajara|argentina|buenos aires|"
    r"colombia|bogot|chile|santiago|nigeria|lagos|egypt|cairo|kenya|"
    r"nairobi|south africa|turkey|istanbul|ukraine|kyiv|serbia|belgrade|"
    r"bulgaria|sofia|croatia|zagreb|lithuania|vilnius|latvia|riga|"
    r"armenia|yerevan|cyprus|malta|luxembourg|emea|apac|latam|"
    r",\s?(?-i:ON|QC|BC|AB|MB|SK|NS|NB|NL|PE|YT)\b",
    re.I,
)


def wanted_title(title: str) -> bool:
    """True for an in-profile internship title on a raw ATS board."""
    if not (INTERN_RE.search(title) and ROLE_RE.search(title)):
        return False
    if EXCLUDE_RE.search(title):
        return False
    if AI_EXCLUDE_RE.search(title) and not SWE_RE.search(title):
        return False
    return True


def is_us(location: str) -> bool:
    """US hint wins, then a clearly-foreign hint loses; ambiguous strings
    (bare "Remote", city-only names) are kept rather than dropped.

    Multi-location rows ("Toronto, ON · New York, NY") keep on the US hit,
    so a role that is US-available anywhere still gets through.
    """
    if not location:
        return True
    if US_HINT_RE.search(location):
        return True
    if NON_US_RE.search(location):
        return False
    return True
