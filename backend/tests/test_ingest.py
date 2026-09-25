"""Extraction and the upload gate, ported from office-extract, youtube-transcript and upload-formats tests."""

import io
import json
import zipfile

import pytest

from app.ingest.errors import IngestError
from app.ingest.office import OFFICE_FORMATS, detect_ooxml_format, extract_document, format_for_mime_type
from app.ingest.youtube import extract_video_id, ingest_youtube, parse_transcript
from app.middleware.errors import ApiError
from app.middleware.upload import ACCEPTED_MIME_TYPES, LEGACY_FORMAT_ADVICE, file_filter, verify_uploaded_file

MIME = {key: OFFICE_FORMATS[key]["mimeType"] for key in ("docx", "xlsx", "pptx")}


def pack(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


# --- Word -------------------------------------------------------------------------------

def docx(paragraphs):
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    return pack({"[Content_Types].xml": "<Types/>", "word/document.xml": f"<w:document><w:body>{body}</w:body></w:document>"})


def test_word_paragraphs_in_order():
    result = extract_document(docx(["Chapter 1", "A database stores rows."]), mime_type=MIME["docx"])
    assert result["format"] == "docx"
    assert result["fullText"] == "Chapter 1\nA database stores rows."
    assert OFFICE_FORMATS["docx"]["unit"] == "section"


def test_long_word_document_sections():
    result = extract_document(docx([f"Paragraph {i + 1}" for i in range(95)]), mime_type=MIME["docx"], plan_tier="plus")
    assert result["sectionCount"] == 3
    assert [s["number"] for s in result["sections"]] == [1, 2, 3]
    assert result["sections"][0]["text"].startswith("Paragraph 1")


def test_entities_decoded_ampersand_last():
    result = extract_document(docx(["Tom &amp; Jerry", "&amp;lt;not a tag&amp;gt;", "5 &lt; 6"]), mime_type=MIME["docx"])
    assert result["fullText"] == "Tom & Jerry\n&lt;not a tag&gt;\n5 < 6"


def test_khmer_survives():
    khmer = "មូលដ្ឋានទិន្នន័យរក្សាទុកព័ត៌មាន"
    assert extract_document(docx([khmer]), mime_type=MIME["docx"])["fullText"] == khmer


# --- Excel ------------------------------------------------------------------------------

def xlsx(sheets, strings=(), styles=None):
    files = {
        "[Content_Types].xml": "<Types/>",
        "xl/workbook.xml": "<workbook><sheets>" + "".join(
            f'<sheet name="{s["name"]}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, s in enumerate(sheets)
        ) + "</sheets></workbook>",
        "xl/_rels/workbook.xml.rels": "<Relationships>" + "".join(
            f'<Relationship Id="rId{i + 1}" Target="worksheets/sheet{i + 1}.xml"/>' for i in range(len(sheets))
        ) + "</Relationships>",
        "xl/sharedStrings.xml": "<sst>" + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>",
    }
    if styles:
        files["xl/styles.xml"] = styles
    for i, sheet in enumerate(sheets):
        files[f"xl/worksheets/sheet{i + 1}.xml"] = sheet["xml"]
    return pack(files)


def row(r, cells):
    def cell(c):
        t = f' t="{c["t"]}"' if c.get("t") else ""
        s = f' s="{c["s"]}"' if "s" in c else ""
        return f'<c r="{c["ref"]}"{t}{s}><v>{c["v"]}</v></c>'

    return f'<row r="{r}">' + "".join(cell(c) for c in cells) + "</row>"


def sheet_xml(*rows):
    return f"<worksheet><sheetData>{''.join(rows)}</sheetData></worksheet>"


def test_shared_strings_resolved():
    result = extract_document(xlsx(strings=["Term", "Definition", "Primary key"], sheets=[{
        "name": "Glossary",
        "xml": sheet_xml(row(1, [{"ref": "A1", "t": "s", "v": 0}, {"ref": "B1", "t": "s", "v": 1}]),
                         row(2, [{"ref": "A2", "t": "s", "v": 2}, {"ref": "B2", "v": "42"}])),
    }]), mime_type=MIME["xlsx"])
    assert result["format"] == "xlsx"
    assert result["fullText"] == "Glossary\nTerm\tDefinition\nPrimary key\t42"


def test_date_cells_rendered_as_dates():
    styles = '<styleSheet><cellXfs><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>'
    result = extract_document(xlsx(styles=styles, sheets=[{
        "name": "Dates", "xml": sheet_xml(row(1, [{"ref": "A1", "s": 1, "v": "45678"}, {"ref": "B1", "s": 0, "v": "45678"}])),
    }]), mime_type=MIME["xlsx"])
    assert "2025-01-21" in result["fullText"]
    assert "45678" in result["fullText"]


def test_booleans_as_words():
    result = extract_document(xlsx(sheets=[{
        "name": "B", "xml": sheet_xml(row(1, [{"ref": "A1", "t": "b", "v": "1"}, {"ref": "B1", "t": "b", "v": "0"}])),
    }]), mime_type=MIME["xlsx"])
    assert "TRUE\tFALSE" in result["fullText"]


def test_empty_sheet_does_not_renumber():
    result = extract_document(xlsx(strings=["first", "third"], sheets=[
        {"name": "One", "xml": sheet_xml(row(1, [{"ref": "A1", "t": "s", "v": 0}]))},
        {"name": "Two", "xml": "<worksheet><sheetData/></worksheet>"},
        {"name": "Three", "xml": sheet_xml(row(1, [{"ref": "A1", "t": "s", "v": 1}]))},
    ]), mime_type=MIME["xlsx"])
    assert [s["number"] for s in result["sections"]] == [1, 3]
    assert result["sections"][1]["title"] == "Three"


# --- PowerPoint -------------------------------------------------------------------------

def pptx(slides, order=None, notes=None):
    notes = notes or {}
    ids = [f"rId{i + 1}" for i in range(len(slides))]
    sequence = order or ids
    files = {
        "[Content_Types].xml": "<Types/>",
        "ppt/presentation.xml": "<presentation><sldIdLst>" + "".join(
            f'<p:sldId id="{256 + i}" r:id="{rid}"/>' for i, rid in enumerate(sequence)) + "</sldIdLst></presentation>",
        "ppt/_rels/presentation.xml.rels": "<Relationships>" + "".join(
            f'<Relationship Id="rId{i + 1}" Target="slides/slide{i + 1}.xml"/>' for i in range(len(slides))
        ) + "</Relationships>",
    }
    for i, lines in enumerate(slides):
        files[f"ppt/slides/slide{i + 1}.xml"] = "<p:sld><p:cSld>" + "".join(
            f"<a:p><a:r><a:t>{line}</a:t></a:r></a:p>" for line in lines) + "</p:cSld></p:sld>"
    for index, text in notes.items():
        n = index + 1
        files[f"ppt/slides/_rels/slide{n}.xml.rels"] = (
            '<Relationships><Relationship Id="rIdN" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            f'relationships/notesSlide" Target="../notesSlides/notesSlide{n}.xml"/></Relationships>')
        files[f"ppt/notesSlides/notesSlide{n}.xml"] = f"<p:notes><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:notes>"
    return pack(files)


def test_slides_in_presentation_order():
    result = extract_document(pptx([["First file"], ["Second file"], ["Third file"]], order=["rId3", "rId1", "rId2"]),
                              mime_type=MIME["pptx"])
    assert [s["text"] for s in result["sections"]] == ["Third file", "First file", "Second file"]


def test_picture_only_slide_does_not_renumber():
    result = extract_document(pptx([["Intro"], [], ["Conclusion"]]), mime_type=MIME["pptx"])
    assert [s["number"] for s in result["sections"]] == [1, 3]


def test_speaker_notes_on_owning_slide():
    result = extract_document(pptx([["Slide one"], ["Slide two"], ["Slide three"]], notes={2: "The three rules are…"}),
                              mime_type=MIME["pptx"])
    with_notes = [s for s in result["sections"] if "Speaker notes:" in s["text"]]
    assert len(with_notes) == 1 and with_notes[0]["number"] == 3


def test_slide_title_is_section_title():
    result = extract_document(pptx([["Normalization", "Three rules"]]), mime_type=MIME["pptx"])
    assert result["sections"][0]["title"] == "Normalization"


# --- plain text, detection, failures -----------------------------------------------------

def test_plain_text_one_section_crlf_normalised():
    result = extract_document("line one\r\nline two\r\n".encode(), mime_type="text/plain")
    assert result["format"] == "text" and result["sectionCount"] == 1
    assert result["fullText"] == "line one\nline two"


def test_real_format_read_from_package():
    package = xlsx(strings=["hello"], sheets=[{"name": "S", "xml": sheet_xml(row(1, [{"ref": "A1", "t": "s", "v": 0}]))}])
    assert extract_document(package, mime_type=MIME["docx"])["format"] == "xlsx"


def test_detection_and_mime_mapping():
    assert detect_ooxml_format({"word/document.xml": b""}) == "docx"
    assert detect_ooxml_format({"xl/workbook.xml": b""}) == "xlsx"
    assert detect_ooxml_format({"ppt/presentation.xml": b""}) == "pptx"
    assert detect_ooxml_format({"mimetype": b""}) is None
    assert format_for_mime_type("text/markdown") == "text"
    assert format_for_mime_type("application/msword") is None


@pytest.mark.parametrize("data, mime, code, pattern", [
    (pack({"random.txt": "hello"}), MIME["docx"], "extract_failed", "Word, Excel or PowerPoint"),
    (b"not a zip at all", MIME["docx"], "extract_failed", "corrupt or password-protected"),
    (b"", MIME["docx"], "extract_failed", "empty"),
    (docx([]), MIME["docx"], "empty_content", ""),
    (b"   \n  ", "text/plain", "empty_content", ""),
])
def test_extraction_failures(data, mime, code, pattern):
    with pytest.raises(IngestError) as err:
        extract_document(data, mime_type=mime)
    assert err.value.code == code
    assert pattern.lower() in str(err.value).lower()


def test_free_plan_part_cap():
    big = pptx([[f"Slide {i + 1}"] for i in range(60)])
    with pytest.raises(IngestError) as err:
        extract_document(big, mime_type=MIME["pptx"], plan_tier="free")
    assert err.value.code == "page_limit_exceeded" and "slides" in str(err.value)
    assert extract_document(big, mime_type=MIME["pptx"], plan_tier="plus")["sectionCount"] == 60


# --- YouTube ------------------------------------------------------------------------------

SRV3 = """<?xml version="1.0" encoding="utf-8" ?><timedtext format="3">
<body>
<p t="1200" d="2160">All right, so here we are, in front of the
elephants</p>
<p t="5318" d="2656">the cool thing about these guys</p>
<p t="12616" d="1751">and that&#39;s cool</p>
</body>
</timedtext>"""
LEGACY = """<?xml version="1.0" encoding="utf-8" ?><transcript>
<text start="1.2" dur="2.16">All right</text>
<text start="5.318" dur="2.656">the cool thing</text>
</transcript>"""
JSON3 = json.dumps({"events": [
    {"tStartMs": 1200, "dDurationMs": 2160, "segs": [{"utf8": "All "}, {"utf8": "right"}]},
    {"tStartMs": 5318, "dDurationMs": 2656, "segs": [{"utf8": "the cool thing"}]},
]})


def test_srv3_milliseconds_and_entities():
    cues = parse_transcript(SRV3)
    assert len(cues) == 3
    assert (cues[0]["startSeconds"], cues[0]["durationSeconds"], cues[2]["startSeconds"]) == (1.2, 2.16, 12.616)
    assert cues[0]["text"] == "All right, so here we are, in front of the elephants"
    assert cues[2]["text"] == "and that's cool"


def test_srv3_spans_and_breaks():
    assert [c["text"] for c in parse_transcript(
        '<timedtext format="3"><body><p t="0" d="10">\n</p><p t="10" d="10">real</p></body></timedtext>')] == ["real"]
    assert parse_transcript('<timedtext format="3"><body><p t="1000" d="2000"><s t="0">hello</s><s t="300"> there</s>'
                            "</p></body></timedtext>") == [{"text": "hello there", "startSeconds": 1, "durationSeconds": 2}]


def test_all_formats_agree():
    starts = [[c["startSeconds"] for c in parse_transcript(body)[:2]] for body in (SRV3, LEGACY, JSON3)]
    assert starts[0] == starts[1] == starts[2]
    assert [c["text"] for c in parse_transcript(JSON3)] == ["All right", "the cool thing"]


def test_unparseable_bodies():
    assert parse_transcript("") == []
    assert parse_transcript("<html><body>nope</body></html>") == []
    assert parse_transcript("{not json") == []


def test_ingest_allows_login_required_player_status(monkeypatch):
    class FakeResponse:
        def __init__(self, text):
            self.text = text
            self.is_success = True
            self.status_code = 200

    def fake_fetch(video_id):
        return {
            "playabilityStatus": {"status": "LOGIN_REQUIRED"},
            "videoDetails": {
                "title": "Age-gated but readable",
                "lengthSeconds": "123",
                "thumbnail": {"thumbnails": [{"url": "https://example.com/thumb.jpg"}]},
                "isLiveContent": False,
            },
            "captions": {"playerCaptionsTracklistRenderer": {"captionTracks": [{
                "languageCode": "en",
                "baseUrl": "https://example.com/captions",
            }]}}
        }

    monkeypatch.setattr("app.ingest.youtube._fetch_player_response", fake_fetch)
    monkeypatch.setattr("app.ingest.youtube.httpx.get", lambda *args, **kwargs: FakeResponse(
        '<?xml version="1.0" ?><transcript><text start="0" dur="1">hello</text></transcript>'
    ))

    result = ingest_youtube("https://www.youtube.com/watch?v=jNQXAC9IVRw")
    assert result["title"] == "Age-gated but readable"
    assert result["fullText"] == "hello"


@pytest.mark.parametrize("value", [
    "jNQXAC9IVRw", "https://youtu.be/jNQXAC9IVRw", "https://youtu.be/jNQXAC9IVRw?t=30",
    "https://www.youtube.com/watch?v=jNQXAC9IVRw", "https://www.youtube.com/watch?v=jNQXAC9IVRw&t=30s",
    "https://m.youtube.com/watch?v=jNQXAC9IVRw", "https://www.youtube.com/shorts/jNQXAC9IVRw",
    "https://www.youtube.com/embed/jNQXAC9IVRw", "  https://youtu.be/jNQXAC9IVRw  ",
])
def test_video_ids(value):
    assert extract_video_id(value) == "jNQXAC9IVRw"


@pytest.mark.parametrize("value", ["https://example.com/watch?v=abc", "hello", "", None])
def test_invalid_video_urls(value):
    with pytest.raises(IngestError) as err:
        extract_video_id(value)
    assert err.value.code == "invalid_url"


# --- upload gate ----------------------------------------------------------------------------

@pytest.mark.parametrize("name, mime", [
    ("notes.docx", MIME["docx"]), ("budget.xlsx", MIME["xlsx"]), ("lecture.pptx", MIME["pptx"]),
    ("notes.txt", "text/plain"), ("notes.md", "text/markdown"), ("grades.csv", "text/csv"),
    ("week1.pdf", "application/pdf"), ("page.jpg", "image/jpeg"), ("page.png", "image/png"),
])
def test_accepted_formats(name, mime):
    file_filter(name, mime)


def test_legacy_doc_gets_conversion_step():
    with pytest.raises(ApiError) as err:
        file_filter("essay.doc", "application/msword")
    assert (err.value.status, err.value.code) == (415, "unsupported_file_type")
    assert "Save As" in err.value.message and ".docx" in err.value.message
    assert err.value.details["convertTo"] == ".docx"


def test_each_legacy_format_mapped():
    expected = {".doc": ".docx", ".xls": ".xlsx", ".ppt": ".pptx", ".pages": ".docx", ".numbers": ".xlsx",
                ".key": ".pptx", ".odt": ".docx", ".ods": ".xlsx", ".odp": ".pptx", ".rtf": ".docx"}
    for ext, convert_to in expected.items():
        assert LEGACY_FORMAT_ADVICE[ext]["convertTo"] == convert_to
        assert f"{convert_to})" in LEGACY_FORMAT_ADVICE[ext]["advice"]


def test_unknown_and_mislabelled_formats():
    with pytest.raises(ApiError) as err:
        file_filter("archive.zip", "application/zip")
    assert "Word, Excel or PowerPoint" in err.value.message
    assert err.value.details["accepted"] == ACCEPTED_MIME_TYPES
    with pytest.raises(ApiError) as err:
        file_filter("notes.docx", MIME["xlsx"])
    assert "must be named .xlsx" in err.value.message


@pytest.fixture
def upload_file(tmp_path, monkeypatch):
    # verify_uploaded_file only deletes inside the upload root, so point it at tmp_path.
    monkeypatch.setattr("app.middleware.upload.upload_root", str(tmp_path))

    def make(name, data, mime):
        path = tmp_path / name
        path.write_bytes(data)
        return {"path": str(path), "mimetype": mime, "originalname": name}

    return make


def test_byte_level_verification(upload_file):
    assert verify_uploaded_file(upload_file("a.docx", b"PK\x03\x04" + b"\x00" * 8, MIME["docx"]))["kind"] == "document"
    assert verify_uploaded_file(upload_file("a.txt", b"Week 1 notes\nDatabases store rows.", "text/plain"))["kind"] == "document"
    assert verify_uploaded_file(upload_file("km.txt", "មូលដ្ឋានទិន្នន័យ".encode(), "text/plain"))["kind"] == "document"
    for name, data, mime in [("fake.docx", b"MZ this is an executable", MIME["docx"]),
                             ("fake.txt", bytes([0x41, 0, 0x42, 0, 0x43]), "text/plain")]:
        with pytest.raises(ApiError) as err:
            verify_uploaded_file(upload_file(name, data, mime))
        assert err.value.code == "unsupported_file_type"
    with pytest.raises(ApiError, match="empty"):
        verify_uploaded_file(upload_file("empty.docx", b"", MIME["docx"]))
