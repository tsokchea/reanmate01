-- Students are sent Word documents, spreadsheets and lecture decks, not only
-- PDFs, and until now kit_sources could not record one: the kind CHECK from
-- 001_init.sql allows pdf, image, youtube, link, topic and text, so an uploaded
-- .pptx had nowhere to go.
--
-- One new kind, 'document', rather than one per format. The distinction that
-- matters to this table is how the row is processed, and Word, Excel and
-- PowerPoint are the same job — a ZIP of XML parts read by one extractor
-- (server/src/ingest/office.js). Which of them a row actually is, is already
-- recorded in mime_type, which is where the extractor and the client both read
-- it from. Three kinds would have duplicated that, and left two places to
-- disagree about the same file.
--
-- 'text' is deliberately NOT reused for uploaded .txt and .csv files. It
-- already means something else: a source whose content the STUDENT typed,
-- living in extracted_text with no file behind it, which is why the ingest
-- service reads that column rather than opening anything. An uploaded text file
-- has a storage_path and has to be read off disk, so it is a document.

ALTER TABLE kit_sources DROP CONSTRAINT kit_sources_kind_check;
ALTER TABLE kit_sources ADD CONSTRAINT kit_sources_kind_check
  CHECK (kind IN ('pdf', 'image', 'youtube', 'link', 'topic', 'text', 'document'));
