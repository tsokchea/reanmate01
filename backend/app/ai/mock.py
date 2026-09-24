"""Mock AI provider (server/src/ai/mock.js).

Every AI feature is built and tested against this until OPENAI_API_KEY
exists, so the shapes here are the real shapes — same fields, both languages,
realistic lengths. Output is deterministic (seeded off the input) and uses the
same PRNG as the Node mock, so the same text yields the same mock embedding
before and after the migration.
"""

import hashlib
import json
import logging
import math
import re
import unicodedata

from ..utils.js import js_round
from .types import EMBEDDING_DIMENSIONS, assert_embedding_width

log = logging.getLogger("reanmate")

# Mirrors EMBED_BATCH_SIZE in the OpenAI provider so mock api_calls stay comparable.
MOCK_EMBED_BATCH_SIZE = 96

# Stamps generated text so it cannot be mistaken for real content. ASCII and
# leading, so it survives Khmer text and is the first thing visible anywhere.
MOCK_MARKER = "[MOCK]"


def marked(value):
    return f"{MOCK_MARKER} {value}"


def ignored_note(language, title):
    """Says out loud that the document was never opened."""
    quoted = f' "{title}"' if title else ""
    if language == "km":
        return f"{MOCK_MARKER} ខ្លឹមសារសាកល្បង — មិនបានអានឯកសារ{quoted}ទេ"
    return f"{MOCK_MARKER} Placeholder content — the document{quoted} was not read"


def seed_from(value):
    return int(hashlib.sha256(str(value).encode()).hexdigest()[:8], 16)


def make_random(seed):
    """Small deterministic LCG, identical to the Node mock's."""
    state = seed or 1

    def random():
        nonlocal state
        state = (state * 1_664_525 + 1_013_904_223) % 4_294_967_296
        return state / 4_294_967_296

    return random


def pick(items, random):
    return items[math.floor(random() * len(items)) % len(items)]


COPY = {
    "km": {
        "summaryTitle": "ទិដ្ឋភាពរួមនៃមេរៀន",
        "summaryBody": "\n".join([
            "## ចំណុចសំខាន់",
            "",
            "មេរៀននេះពន្យល់ពីរបៀបដែលមូលដ្ឋានទិន្នន័យរក្សាទុក និងរៀបចំព័ត៌មាន។",
            "អ្នកនឹងយល់ពីតារាង ជួរដេក ជួរឈរ និងទំនាក់ទំនងរវាងតារាងនីមួយៗ។",
            "",
            "## អ្វីដែលអ្នកនឹងរៀន",
            "",
            "- របៀបរចនាតារាងដែលមិនមានទិន្នន័យស្ទួន",
            "- តួនាទីរបស់គន្លឹះចម្បងក្នុងការកំណត់អត្តសញ្ញាណកំណត់ត្រា",
            "- របៀបសរសេរសំណួរ SQL ដើម្បីទាញយកទិន្នន័យដែលត្រូវការ",
        ]),
        "keyPoints": [
            "មូលដ្ឋានទិន្នន័យរក្សាទុកព័ត៌មានជាទម្រង់តារាង",
            "គន្លឹះចម្បងកំណត់អត្តសញ្ញាណកំណត់ត្រានីមួយៗដោយឯកឯង",
            "ទំនាក់ទំនងភ្ជាប់តារាងពីរឬច្រើនចូលគ្នា",
            "សំណួរ SQL ប្រើដើម្បីទាញយក និងកែប្រែទិន្នន័យ",
            "សន្ទស្សន៍ជួយឱ្យការស្វែងរកលឿនជាងមុន",
        ],
        "guideModules": [
            {
                "title": "គន្លឹះចម្បង (Primary key)",
                "explanationMd": "\n".join([
                    "- **គន្លឹះចម្បង** កំណត់អត្តសញ្ញាណកំណត់ត្រានីមួយៗដោយឯកឯង។",
                    "- តម្លៃរបស់វា **មិនស្ទួន** និង **មិនទទេ** — នេះជាមូលហេតុដែលវាដំណើរការ។",
                    "- បើគ្មានវាទេ កំណត់ត្រាដូចគ្នាពីរមិនអាចបែងចែកបានឡើយ។",
                ]),
                "applicationMd": "\n".join([
                    "```sql",
                    "CREATE TABLE students (",
                    "  student_id integer PRIMARY KEY,",
                    "  full_name  text NOT NULL",
                    ");",
                    "```",
                ]),
                "pitfallsMd": "\n".join([
                    "- ប្រើឈ្មោះជាគន្លឹះចម្បង — សិស្សពីរនាក់អាចមានឈ្មោះដូចគ្នា។",
                    "- ភ្លេចថាគន្លឹះសមាសភាគអាចត្រូវការជួរឈរច្រើន។",
                    "- **គន្លឹះប្រឡង៖** តារាងមួយមានគន្លឹះចម្បងតែមួយ តែអាចមានគន្លឹះបរទេសច្រើន។",
                ]),
                "recall": [{
                    "question": "ហេតុអ្វីលេខទូរស័ព្ទមិនសមជាគន្លឹះចម្បងសម្រាប់តារាងសិស្ស?",
                    "answer": "ព្រោះវាអាចផ្លាស់ប្តូរ អាចទទេ និងអាចប្រើរួមគ្នាក្នុងគ្រួសារ។ គន្លឹះចម្បងត្រូវតែថេរ មិនទទេ និងមិនស្ទួន។",
                }],
            },
            {
                "title": "ការធ្វើឱ្យធម្មតា (Normalization)",
                "explanationMd": "\n".join([
                    "- **ការធ្វើឱ្យធម្មតា** បំបែកតារាងធំជាតារាងតូចៗគ្មានទិន្នន័យស្ទួន។",
                    "- ទិន្នន័យនីមួយៗរក្សាទុក **តែម្តងគត់** នៅកន្លែងតែមួយ។",
                    "- ដូច្នេះការកែម្តងគឺគ្រប់គ្រាន់ — នេះជាគោលបំណងទាំងមូល។",
                ]),
                "applicationMd": "\n".join([
                    "| course | teacher |",
                    "| --- | --- |",
                    "| Math 1 | Sokha |",
                    "| Math 2 | Sokha |",
                    "",
                    "បំបែកជា `teachers` និង `courses` ភ្ជាប់ដោយ `teacher_id`។",
                ]),
                "pitfallsMd": "\n".join([
                    "- បំបែកច្រើនពេក រហូតសំណួរត្រូវការ JOIN ដប់ដង។",
                    "- ភ្លេចថារបាយការណ៍ខ្លះទុកទិន្នន័យស្ទួនដោយចេតនា ដើម្បីល្បឿន។",
                    "- **គន្លឹះប្រឡង៖** 3NF — ជួរឈរនីមួយៗអាស្រ័យលើគន្លឹះ តែលើគន្លឹះប៉ុណ្ណោះ។",
                ]),
                "recall": [{
                    "question": "តើទិន្នន័យស្ទួនបង្កបញ្ហាអ្វីនៅពេលកែប្រែ?",
                    "answer": "បើឈ្មោះមួយស្ថិតនៅដប់ជួរដេក ការកែម្តងនឹងទុកជួរដេកប្រាំបួនទៀតខុស — នេះហៅថា update anomaly។",
                }],
            },
        ],
        "chapterTitles": [
            "មូលដ្ឋានគ្រឹះនៃមូលដ្ឋានទិន្នន័យ", "គំរូទិន្នន័យ និងគ្រោងការណ៍", "មូលដ្ឋានទិន្នន័យទំនាក់ទំនង",
            "មូលដ្ឋានគ្រឹះនៃ SQL", "សន្ទស្សន៍ និងដំណើរការ", "ការធ្វើឱ្យធម្មតា", "ប្រតិបត្តិការ", "ការរចនាគ្រោងការណ៍",
            "សំណួរកម្រិតខ្ពស់", "សុវត្ថិភាព និងសិទ្ធិ", "ការបម្រុងទុក និងការស្តារ", "ការអនុវត្តជាក់ស្តែង",
        ],
        "tutorGreeting": "សួស្តី! សួរខ្ញុំអំពីឯកសាររបស់អ្នកបាន។",
        "tutorAnswers": [
            "គន្លឹះចម្បងគឺជាជួរឈរដែលកំណត់អត្តសញ្ញាណកំណត់ត្រានីមួយៗក្នុងតារាងដោយឯកឯង។ តម្លៃរបស់វាមិនអាចស្ទួន ឬទទេបានឡើយ។",
            "តារាងមួយអាចភ្ជាប់ទៅតារាងមួយទៀតតាមរយៈគន្លឹះបរទេស ដែលចង្អុលទៅគន្លឹះចម្បងរបស់តារាងនោះ។",
            "សំណួរ SELECT ប្រើដើម្បីអានទិន្នន័យ។ អ្នកអាចបន្ថែម WHERE ដើម្បីត្រងលទ្ធផលតាមលក្ខខណ្ឌ។",
        ],
        "followups": ["ពន្យល់ពី SQL JOIN", "សង្ខេបសប្តាហ៍ទី ២", "ផ្តល់ឧទាហរណ៍មួយ"],
        "imageDescription": "ទំព័រកត់ត្រាសរសេរដោយដៃអំពីមូលដ្ឋានទិន្នន័យ មានប្លង់តារាងមួយនៅផ្នែកខាងក្រោម។",
        "imageLines": [
            "មេរៀនទី ៣ — មូលដ្ឋានទិន្នន័យទំនាក់ទំនង",
            "",
            "តារាង = ជួរដេក + ជួរឈរ",
            "គន្លឹះចម្បង (Primary Key) — តម្លៃមិនស្ទួន មិនទទេ",
            "គន្លឹះបរទេស (Foreign Key) — ចង្អុលទៅតារាងមួយទៀត",
            "",
            "ឧទាហរណ៍៖ SELECT * FROM students WHERE grade = 12;",
            "",
            "កិច្ចការផ្ទះ៖ អនុវត្តលំហាត់ទំព័រ ៤៥",
        ],
        "takeaways": [
            "អ្នកយល់ពីគោលបំណងនៃមូលដ្ឋានទិន្នន័យ",
            "ត្រូវពិនិត្យឡើងវិញនូវគំនិតទំនាក់ទំនង",
            "បន្តអនុវត្តមូលដ្ឋានគ្រឹះនៃ SQL",
        ],
        "terms": [
            ["មូលដ្ឋានទិន្នន័យទំនាក់ទំនង", "មូលដ្ឋានទិន្នន័យដែលរក្សាទុកព័ត៌មានជាតារាងដែលមានទំនាក់ទំនងគ្នា"],
            ["គន្លឹះចម្បង", "ជួរឈរដែលកំណត់អត្តសញ្ញាណកំណត់ត្រានីមួយៗដោយឯកឯង"],
            ["គន្លឹះបរទេស", "ជួរឈរដែលចង្អុលទៅគន្លឹះចម្បងនៃតារាងមួយទៀត"],
            ["សំណួរ", "ពាក្យបញ្ជាដែលប្រើដើម្បីទាញយក ឬកែប្រែទិន្នន័យ"],
            ["សន្ទស្សន៍", "រចនាសម្ព័ន្ធដែលធ្វើឱ្យការស្វែងរកទិន្នន័យលឿនជាងមុន"],
            ["ការធ្វើឱ្យធម្មតា", "ដំណើរការរៀបចំទិន្នន័យដើម្បីកាត់បន្ថយការស្ទួន"],
        ],
        "gradeCorrect": "ចម្លើយត្រូវ — អ្នកបានពន្យល់គំនិតសំខាន់។",
        "gradeIncorrect": "ចម្លើយនេះខ្វះចំណុចសំខាន់នៃចម្លើយដែលរំពឹងទុក។",
        "questions": [
            {
                "prompt": "តើគន្លឹះចម្បងមានតួនាទីអ្វី?",
                "options": ["កំណត់អត្តសញ្ញាណកំណត់ត្រានីមួយៗដោយឯកឯង", "រក្សាទុករូបភាព", "លុបតារាង", "បង្កើតអ្នកប្រើប្រាស់ថ្មី"],
                "correct": 0,
                "explanation": "គន្លឹះចម្បងធានាថាកំណត់ត្រានីមួយៗមានតម្លៃតែមួយគត់ មិនស្ទួន និងមិនទទេ។",
            },
            {
                "prompt": "តើ SQL តំណាងឱ្យអ្វី?",
                "options": ["Structured Query Language", "Simple Question List", "System Quality Log", "Standard Queue Layer"],
                "correct": 0,
                "explanation": "SQL គឺជា Structured Query Language ដែលប្រើសម្រាប់ធ្វើការជាមួយមូលដ្ឋានទិន្នន័យទំនាក់ទំនង។",
            },
            {
                "prompt": "តារាងមួយអាចមានគន្លឹះចម្បងច្រើនជាងមួយ។",
                "options": ["ពិត", "មិនពិត"],
                "correct": 1,
                "explanation": "តារាងមួយមានគន្លឹះចម្បងតែមួយប៉ុណ្ណោះ ទោះបីជាវាអាចផ្សំពីជួរឈរច្រើនក៏ដោយ។",
            },
        ],
        "topics": ["មូលដ្ឋានទិន្នន័យ", "សំណួរ SQL", "គន្លឹះចម្បង", "ការធ្វើឱ្យធម្មតា"],
    },
    "en": {
        "guideModules": [
            {
                "title": "Primary keys",
                "explanationMd": "\n".join([
                    "- A **primary key** identifies each row uniquely.",
                    "- Its values are **unique** and **never null** — that is what makes it work.",
                    "- Without one, two identical rows cannot be told apart.",
                ]),
                "applicationMd": "\n".join([
                    "```sql",
                    "CREATE TABLE students (",
                    "  student_id integer PRIMARY KEY,",
                    "  full_name  text NOT NULL",
                    ");",
                    "```",
                ]),
                "pitfallsMd": "\n".join([
                    "- Using a name as the key — two students can share one.",
                    "- Forgetting that a composite key may need several columns.",
                    "- **Exam tip:** one primary key per table, but many foreign keys.",
                ]),
                "recall": [{
                    "question": "Why is a phone number a poor primary key for a students table?",
                    "answer": "It changes, it can be blank, and a family may share one. A primary key has to be stable, never null and unique.",
                }],
            },
            {
                "title": "Normalization",
                "explanationMd": "\n".join([
                    "- **Normalization** splits a wide table into smaller ones with no repeated data.",
                    "- Each fact is then stored **exactly once**, in one place.",
                    "- So correcting it once is enough — that is the whole point.",
                ]),
                "applicationMd": "\n".join([
                    "| course | teacher |",
                    "| --- | --- |",
                    "| Math 1 | Sokha |",
                    "| Math 2 | Sokha |",
                    "",
                    "Split into `teachers` and `courses`, joined by `teacher_id`.",
                ]),
                "pitfallsMd": "\n".join([
                    "- Splitting so far that ordinary queries need ten joins.",
                    "- Forgetting that reporting tables duplicate data on purpose, for speed.",
                    "- **Exam tip:** 3NF — every column depends on the key, the whole key, nothing but the key.",
                ]),
                "recall": [{
                    "question": "What goes wrong when the same fact is stored in ten rows?",
                    "answer": "Correcting it once leaves the other nine wrong. That is an update anomaly, and it is what normalization removes.",
                }],
            },
        ],
        "summaryTitle": "Course overview",
        "summaryBody": "\n".join([
            "## The main idea",
            "",
            "This lesson explains how a database stores and organises information.",
            "You will understand tables, rows, columns, and how tables relate to one another.",
            "",
            "## What you will learn",
            "",
            "- How to design tables that avoid duplicated data",
            "- What a primary key does and why every record needs one",
            "- How to write SQL queries that return exactly the rows you want",
        ]),
        "keyPoints": [
            "A database stores information in tables made of rows and columns",
            "A primary key uniquely identifies each record in a table",
            "Relationships connect two or more tables together",
            "SQL queries read and modify the stored data",
            "Indexes make lookups faster as a table grows",
        ],
        "chapterTitles": [
            "Database foundations", "Data models and schemas", "Relational databases", "SQL fundamentals",
            "Indexing and performance", "Normalization", "Transactions", "Schema design", "Advanced queries",
            "Security and permissions", "Backup and recovery", "Putting it into practice",
        ],
        "tutorGreeting": "Hi! Ask me anything about your study kit.",
        "tutorAnswers": [
            "A primary key uniquely identifies each record in a table. Its value cannot be duplicated or left empty.",
            "One table links to another through a foreign key, which points at the primary key of the table it references.",
            "A SELECT query reads data. Add a WHERE clause to filter the results down to the rows that match a condition.",
        ],
        "followups": ["Explain SQL JOINs", "Summarize Week 2", "Give me an example"],
        "imageDescription": "A page of handwritten database notes, with a small table diagram near the bottom.",
        "imageLines": [
            "Lesson 3 - Relational Databases",
            "",
            "table = rows + columns",
            "Primary Key - unique, never null",
            "Foreign Key - points at another table",
            "",
            "Example: SELECT * FROM students WHERE grade = 12;",
            "",
            "Homework: exercises on page 45",
        ],
        "takeaways": [
            "You understand what a database is for",
            "Review the relational concepts",
            "Practice SQL fundamentals next",
        ],
        "terms": [
            ["Relational database", "A database that stores information in tables that relate to one another"],
            ["Primary key", "A column whose value uniquely identifies each record in a table"],
            ["Foreign key", "A column that points at the primary key of another table"],
            ["Query", "A statement used to read or modify stored data"],
            ["Index", "A structure that makes looking up rows faster"],
            ["Normalization", "Organising data to reduce duplication"],
        ],
        "gradeCorrect": "Correct — you covered the key idea.",
        "gradeIncorrect": "This misses the substance of the expected answer.",
        "questions": [
            {
                "prompt": "What does a primary key do?",
                "options": ["Uniquely identifies each record in a table", "Stores image data", "Deletes a table", "Creates a new user"],
                "correct": 0,
                "explanation": "A primary key guarantees every record has one unique, non-null identifying value.",
            },
            {
                "prompt": "What does SQL stand for?",
                "options": ["Structured Query Language", "Simple Question List", "System Quality Log", "Standard Queue Layer"],
                "correct": 0,
                "explanation": "SQL is Structured Query Language, used to work with relational databases.",
            },
            {
                "prompt": "A table can have more than one primary key.",
                "options": ["True", "False"],
                "correct": 1,
                "explanation": "A table has exactly one primary key, though that key may be composed of several columns.",
            },
        ],
        "topics": ["Databases", "SQL queries", "Primary keys", "Normalization"],
    },
}


def _dict(language):
    return COPY.get(language, COPY["km"])


def _build_outline(language, chapter_count, duration_seconds):
    d = _dict(language)
    count = min(max(chapter_count, 1), len(d["chapterTitles"]))
    span = max(60, math.floor((duration_seconds or count * 900) / count))
    return [
        {"chapterIndex": i + 1, "title": d["chapterTitles"][i], "startSeconds": i * span, "endSeconds": (i + 1) * span}
        for i in range(count)
    ]


# Synthetic token ESTIMATES (not measurements) so the ai_generations pipeline
# can be exercised before a real key exists. The ai_token_ratios view excludes
# provider = 'mock' so these never contaminate the real measurement.
CHARS_PER_TOKEN = {"en": 4, "km": 1}


def _estimate_tokens(text, language):
    length = len(str(text or ""))
    if length == 0:
        return 0
    return max(1, math.ceil(length / CHARS_PER_TOKEN.get(language, CHARS_PER_TOKEN["km"])))


def _mock_usage(*, input="", output="", language="km", api_calls=1):
    prompt = _estimate_tokens(input, language)
    completion = _estimate_tokens(output, language)
    return {
        "promptTokens": prompt,
        "completionTokens": completion,
        "reasoningTokens": 0,
        "cachedPromptTokens": 0,
        "totalTokens": prompt + completion,
        "apiCalls": api_calls,
        "model": "mock",
    }


def _report(on_usage, usage):
    if not callable(on_usage):
        return
    try:
        on_usage(usage)
    except Exception as err:  # telemetry never breaks a generation
        log.warning("[ai] usage reporter threw, ignoring: %s", err)


def _js_dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class MockProvider:
    name = "mock"

    def summarize(self, *, text=None, title=None, language="km", on_usage=None, **_):
        d = _dict(language)
        result = {"title": ignored_note(language, title), "bodyMd": d["summaryBody"], "keyPoints": d["keyPoints"]}
        _report(on_usage, _mock_usage(input=text, output=result["bodyMd"], language=language))
        return result

    def summarize_chapters(self, *, text=None, title=None, language="km", duration_seconds=None, chapter_count=12,
                           outline=None, only=None, on_usage=None, **_):
        """Resumable: a supplied outline is reused and costs nothing; ``only`` narrows the bodies."""
        d = _dict(language)
        full_outline = outline if outline is not None else _build_outline(language, chapter_count, duration_seconds)
        if outline is None:
            _report(on_usage, _mock_usage(input=text, output=" ".join(c["title"] for c in full_outline),
                                          language=language))
        indices = [c["chapterIndex"] for c in full_outline]
        wanted = indices if only is None else [i for i in dict.fromkeys(only) if i in indices]

        paragraphs = d["summaryBody"].split("\n\n")
        chapters = []
        for c in full_outline:
            if c["chapterIndex"] not in wanted:
                continue
            body = paragraphs[2] if len(paragraphs) > 2 else d["keyPoints"][0]
            chapter = {**c, "bodyMd": f"### {c['title']}\n\n{body}", "keyPoints": d["keyPoints"][:3]}
            _report(on_usage, _mock_usage(input=text, output=chapter["bodyMd"], language=language))
            chapters.append(chapter)

        return {
            "title": f"{d['summaryTitle']}: {title}" if title else d["summaryTitle"],
            "bodyMd": d["summaryBody"],
            "outline": full_outline,
            "chapters": chapters,
        }

    def generate_study_guide(self, *, text=None, title=None, language="km", module_count=8, outline=None, only=None,
                             on_usage=None, **_):
        d = _dict(language)
        random = make_random(seed_from(f"{title or ''}:{module_count}"))
        modules_fixture = d["guideModules"]

        if outline is not None:
            full_outline = outline
        else:
            full_outline = [
                {
                    "moduleIndex": i + 1,
                    "title": modules_fixture[i % len(modules_fixture)]["title"]
                    + (f" ({i + 1})" if i >= len(modules_fixture) else ""),
                    "focus": pick(d["topics"], random),
                }
                for i in range(max(1, module_count))
            ]
            _report(on_usage, _mock_usage(input=text, output=" ".join(m["title"] for m in full_outline),
                                          language=language))

        indices = [m["moduleIndex"] for m in full_outline]
        wanted = indices if only is None else [i for i in dict.fromkeys(only) if i in indices]

        modules = []
        for m in full_outline:
            if m["moduleIndex"] not in wanted:
                continue
            fixture = modules_fixture[(m["moduleIndex"] - 1) % len(modules_fixture)]
            module = {
                "moduleIndex": m["moduleIndex"],
                "title": m["title"],
                "explanationMd": fixture["explanationMd"],
                "applicationMd": fixture["applicationMd"],
                "pitfallsMd": fixture["pitfallsMd"],
                "recall": fixture["recall"],
            }
            _report(on_usage, _mock_usage(
                input=text,
                output=f"{module['explanationMd']}{module['applicationMd']}{module['pitfallsMd']}",
                language=language,
            ))
            modules.append(module)

        return {"outline": full_outline, "modules": modules}

    def generate_quiz(self, *, text=None, title=None, language="km", count=10, question_types=None,
                      difficulty="medium", avoid_questions=None, weak_topics=None, on_usage=None, **_):
        """Adaptive in the ways a mock honestly can be: skips avoided prompts, aims 70% at weak topics."""
        d = _dict(language)
        question_types = question_types or ["multipleChoice"]
        weak_topics = weak_topics or []
        seen = set(avoid_questions or [])
        targeted = js_round(count * 0.7) if weak_topics else 0

        # Marked before the seen-check: avoid_questions holds prompts read back
        # from the database, which are already marked.
        stamped = [{**q, "prompt": marked(q["prompt"])} for q in d["questions"]]
        fresh = [q for q in stamped if q["prompt"] not in seen]
        pool = fresh or stamped

        questions = []
        for i in range(max(1, count)):
            q = pool[i % len(pool)]
            cycle = i // len(pool)
            prompt = f"{q['prompt']} ({len(seen) + i + 1})" if cycle or not fresh else q["prompt"]
            requested = question_types[i % len(question_types)]
            kind = ("true_false" if requested == "trueFalse"
                    else "short_answer" if requested == "shortAnswer" else "multiple_choice")
            if kind == "multiple_choice":
                options = q["options"] if len(q["options"]) == 4 else [*q["options"], "Neither", "Both"][:4]
            elif kind == "true_false":
                options = ["True", "False"]
            else:
                options = []
            correct = (q["options"][q["correct"]] if kind == "short_answer"
                       else q["correct"] % 2 if kind == "true_false" else q["correct"])
            is_targeted = i < targeted
            questions.append({
                "kind": kind,
                "prompt": prompt,
                "options": options,
                "correctAnswer": correct,
                "explanation": q["explanation"],
                "topic": weak_topics[i % len(weak_topics)] if is_targeted else d["topics"][i % len(d["topics"])],
                "targetedWeakConcept": weak_topics[i % len(weak_topics)] if is_targeted else None,
            })

        _report(on_usage, _mock_usage(input=text, output=_js_dumps(questions), language=language))
        return {"title": ignored_note(language, title if title is not None else d["summaryTitle"]),
                "questions": questions}

    def generate_mock_exam(self, *, text=None, title=None, language="km", count=30, on_usage=None, **_):
        d = _dict(language)
        levels = ["easy", "medium", "hard"]
        questions = []
        for i in range(max(1, count)):
            q = d["questions"][i % len(d["questions"])]
            cycle = i // len(d["questions"])
            # A true/false fixture keeps its two options; padding it would fail validation.
            is_true_false = len(q["options"]) == 2
            options = q["options"] if is_true_false or len(q["options"]) == 4 else [*q["options"], "Neither", "Both"][:4]
            questions.append({
                "kind": "true_false" if is_true_false else "multiple_choice",
                "prompt": marked(f"{q['prompt']} ({i + 1})" if cycle else q["prompt"]),
                "options": options,
                "correctAnswer": q["correct"],
                "expectedAnswer": q["options"][q["correct"]],
                "difficulty": levels[i % len(levels)],
                "explanation": q["explanation"],
                "topic": d["topics"][i % len(d["topics"])],
            })
        _report(on_usage, _mock_usage(input=text, output=_js_dumps(questions), language=language))
        return {"title": ignored_note(language, title if title is not None else d["summaryTitle"]),
                "questions": questions}

    def grade_written_answers(self, *, answers=None, language="km", on_usage=None, **_):
        """Marks on keyword overlap — crude on purpose, but different answers get different verdicts."""
        answers = answers or []
        if not answers:
            return []
        d = _dict(language)

        def pieces(value):
            text = unicodedata.normalize("NFKC", str(value if value is not None else "")).lower().strip()
            words = [w for w in re.split(r"[\s.,;:!?()\"'​]+", text) if w]
            # Khmer has no spaces between words: compare characters instead.
            return words if len(words) > 1 else [ch for ch in text if ch.strip()]

        grades = []
        for answer in answers:
            expected = set(pieces(answer.get("expectedAnswer")))
            got = pieces(answer.get("response"))
            hits = len([piece for piece in got if piece in expected])
            overlap = 0 if not expected else hits / len(expected)
            is_correct = len(got) > 0 and overlap >= 0.4
            grades.append({"isCorrect": is_correct, "note": marked(d["gradeCorrect"] if is_correct else d["gradeIncorrect"])})

        _report(on_usage, _mock_usage(input=_js_dumps(answers), output=_js_dumps(grades), language=language))
        return grades

    def generate_flashcards(self, *, text=None, language="km", count=12, on_usage=None, **_):
        d = _dict(language)
        cards = []
        for i in range(max(1, count)):
            term, definition = d["terms"][i % len(d["terms"])]
            cycle = i // len(d["terms"])
            cards.append({
                "term": marked(f"{term} {cycle + 1}" if cycle else term),
                "definition": definition,
                "hint": None,
                "topic": d["topics"][i % len(d["topics"])],
            })
        _report(on_usage, _mock_usage(input=text, output=_js_dumps(cards), language=language))
        return cards

    def tutor_reply(self, *, messages=None, language="km", sources=None, on_usage=None, **_):
        """Yields word-sized deltas, then exactly one terminal chunk."""
        messages = messages or []
        sources = sources or []
        d = _dict(language)
        last_user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
        random = make_random(seed_from(last_user["content"] if last_user else "greeting"))
        content = pick(d["tutorAnswers"], random) if last_user else d["tutorGreeting"]

        try:
            for token in re.split(r"(\s+)", content):
                if token:
                    yield {"type": "delta", "text": token}

            # Reported after the last delta, where the real provider's usage arrives.
            _report(on_usage, _mock_usage(
                input="\n".join([*(s["content"] for s in sources), *(m["content"] for m in messages)]),
                output=content,
                language=language,
            ))

            cited = sources[0] if sources else None
            yield {
                "type": "done",
                "citations": [{
                    "sourceTitle": cited.get("title"),
                    "pageNumber": cited.get("pageNumber"),
                    "startSeconds": cited.get("startSeconds"),
                }] if cited else [],
                "suggestedFollowups": d["followups"],
            }
        except Exception as err:
            yield {"type": "error", "message": str(err)}

    def summarize_attempt(self, *, language="km", correct_count=0, total_questions=1, missed_topics=None,
                          quiz_title=None, on_usage=None, **_):
        d = _dict(language)
        _report(on_usage, _mock_usage(
            input=_js_dumps({"quizTitle": quiz_title, "correctCount": correct_count,
                             "totalQuestions": total_questions, "missedTopics": missed_topics or []}),
            output=" ".join(d["takeaways"]),
            language=language,
        ))
        return {"takeaways": d["takeaways"]}

    def extract_image_text(self, *, images=None, language="km", on_usage=None, **_):
        """Canned OCR; a zero-byte image really does come back hasText: False."""
        d = _dict(language)
        items = images if isinstance(images, list) else [images]
        readable = [image for image in items if image and len(image.get("data") or b"") > 0]

        if not readable:
            _report(on_usage, _mock_usage(input="", output="", language=language, api_calls=1))
            return {"text": "", "hasText": False, "description": ""}

        text = "\n\n".join("\n".join(d["imageLines"]) for _ in readable)
        _report(on_usage, _mock_usage(input="", output=text, language=language, api_calls=len(readable)))
        return {"text": text, "hasText": True, "description": d["imageDescription"]}

    def embed(self, *, texts=None, on_usage=None, **_):
        """Deterministic unit vectors — enough for the pgvector plumbing, not semantic."""
        items = texts if isinstance(texts, list) else [texts]
        embeddings = []
        for i, text in enumerate(items):
            random = make_random(seed_from(text))
            vector = [random() * 2 - 1 for _ in range(EMBEDDING_DIMENSIONS)]
            squares = 0.0
            for value in vector:  # sequential, as Array.reduce sums
                squares += value * value
            norm = math.sqrt(squares) or 1
            embeddings.append(assert_embedding_width([value / norm for value in vector], f"mock embedding[{i}]"))

        _report(on_usage, _mock_usage(
            input="".join(str(t) for t in items),
            output="",
            language="en",
            api_calls=max(1, math.ceil(len(items) / MOCK_EMBED_BATCH_SIZE)),
        ))
        return {"embeddings": embeddings, "dimensions": EMBEDDING_DIMENSIONS}


def create_mock_provider():
    return MockProvider()
