import { useEffect, useRef, useState } from 'react';
import { Link, Navigate, useLocation, useNavigate, useParams } from 'react-router-dom';

import {
  BottomSheet,
  SheetButton,
  SheetField,
  SheetFootnote,
  SheetHeading,
  SheetOption,
  SheetSubtitle,
  SheetTile,
  SheetTitle,
} from '../../components/BottomSheet.jsx';
import { useKits } from '../../kits/KitsContext.jsx';
import { KitRow } from './KitsPage.jsx';
import { api, toFormError } from '../../lib/api.js';
import { formatBytes } from '../../lib/format.js';
import { useLanguage, useT } from '../../i18n/index.js';
import { buildProcessingNavigation, isSourceReadyForStudy } from './processingFlow.js';

/**
 * What the server's fileFilter accepts (backend/app/middleware/upload.py). Kept
 * in step by hand — the accept attribute is a convenience for the file picker,
 * never the check that matters; the server re-validates mime, extension and
 * magic bytes on every upload.
 */
const ACCEPT_IMAGE = 'image/jpeg,image/png,image/webp';

/**
 * Extensions are listed alongside the mime types on purpose. Windows reports
 * an Office file's Content-Type from its own registry, which a machine without
 * Office installed often gets wrong or leaves blank — a mime-only accept list
 * then greys out the very .docx the student is trying to pick. The extension
 * entries keep it selectable, and the server re-checks the bytes either way.
 */
const ACCEPT_DOCUMENT = [
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  'text/plain',
  'text/markdown',
  'text/csv',
  '.pdf',
  '.docx',
  '.xlsx',
  '.pptx',
  '.txt',
  '.md',
  '.csv',
].join(',');

/**
 * The four "add material" sheets, from docs/screens/03-study-kits/02, 04, 05
 * and 06. When opened from a kit detail page (`/kits/:kitId/add`), they stay
 * scoped to that kit; otherwise they run from the Kits tab (`/kits/new`).
 */

const useAddMaterialPaths = () => {
  const { kitId } = useParams();
  const root = kitId ? `/kits/${kitId}/add` : '/kits/new';
  const closeTo = kitId ? `/kits/${kitId}` : '/kits';
  return { kitId, root, closeTo };
};

/**
 * Which kit the material lands in — the step before the chooser.
 *
 * Reached from the dashboard's "Add your material" card, where no kit is in
 * hand yet. Picking one hands the whole flow over to `/kits/:kitId/add`, so
 * everything downstream is the kit-scoped path that already exists; "New study
 * kit" falls through to `/kits/new`, which still creates the kit only once a
 * file, link or topic has actually been chosen.
 *
 * An account with no kits never sees this: there is nothing to choose between,
 * so it goes straight to the chooser rather than showing a list of one option.
 */
export const ChooseKitSheet = () => {
  const t = useT();
  const { kits, status } = useKits();

  return (
    <BottomSheet closeTo="/kits" labelledBy="choose-kit-title">
      <SheetTitle id="choose-kit-title">{t('dashboard.addMaterial')}</SheetTitle>
      <SheetSubtitle>{t('kits.chooseKitSubtitle')}</SheetSubtitle>

      <div className="mt-5 space-y-3">
        <SheetOption
          to="/kits/new"
          tone="blue"
          icon={<PlusMark />}
          title={t('kits.newKitOption')}
          description={t('kits.newKitOptionHint')}
        />

        {status === 'loading' && (
          <p className="py-2 text-base font-medium text-ink-600">{t('kits.chooseKitLoading')}</p>
        )}
        {status === 'error' && <SheetError>{t('kits.loadFailed')}</SheetError>}

        {/* The same row the Kits tab and the dashboard draw, pointed at the
            add flow instead of the kit itself. */}
        {kits.map((kit) => (
          <KitRow key={kit.id} kit={kit} to={`/kits/${kit.id}/add`} />
        ))}
      </div>
    </BottomSheet>
  );
};

/** 04-add-youtube-url-popup — the chooser. */
export const AddMaterialSheet = () => {
  const t = useT();
  const navigate = useNavigate();
  const { kitId, root, closeTo } = useAddMaterialPaths();
  const { getKit } = useKits();
  const { language } = useLanguage();
  const kit = kitId ? getKit(kitId) : null;
  const kitName = kit ? (language === 'km' ? (kit.titleKm ?? kit.title) : kit.title) : null;
  const [leaving, setLeaving] = useState(null);
  const leaveTimer = useRef();

  useEffect(
    () => () => {
      window.clearTimeout(leaveTimer.current);
    },
    [],
  );

  /**
   * Every option leaves the same way: this sheet slides out to the left and
   * the chosen one slides in from the right, so the four routes feel like one
   * stack rather than four unrelated popups. The 300ms matches
   * `.sheet-slide-to-left` in index.css — shorten one and they tear.
   */
  const slideTo = (step) => {
    if (leaving) return;
    setLeaving(step);
    leaveTimer.current = window.setTimeout(() => navigate(`${root}/${step}`), 300);
  };

  return (
    <BottomSheet closeTo={closeTo} labelledBy="add-material-title" transition={leaving ? 'to-left' : 'up'}>
      <SheetTitle id="add-material-title">{t('dashboard.addMaterial')}</SheetTitle>
      {/* Which kit the material lands in, named under the title as the
          reference does — this sheet also opens from the Kits tab, where no
          kit exists yet, so the line only appears when there is one. */}
      {kitName && (
        <p className="mt-1.5 flex items-center gap-2 text-lg font-bold text-ink-900">
          <FolderMark />
          <span className="truncate">{kitName}</span>
        </p>
      )}
      <SheetSubtitle>{t('kits.addMaterialSubtitle')}</SheetSubtitle>

      <div className="mt-5 space-y-3">
        <SheetOption
          onClick={() => slideTo('photo')}
          tone="blue"
          icon={<PhotoIcon />}
          title={t('kits.uploadPhoto')}
          description={t('kits.uploadPhotoHint')}
        />
        <SheetOption
          onClick={() => slideTo('pdf')}
          tone="violet"
          icon={<PdfIcon />}
          title={t('kits.uploadPdf')}
          description={t('kits.uploadPdfHint')}
        />
        <SheetOption
          onClick={() => slideTo('youtube')}
          tone="amber"
          icon={<PlayIcon />}
          title={t('kits.addYoutubeUrl')}
          description={t('kits.addYoutubeUrlHint')}
        />
        <SheetOption
          onClick={() => slideTo('topic')}
          tone="green"
          icon={<SparkIcon />}
          title={t('kits.enterTopic')}
          description={t('kits.enterTopicHint')}
        />
      </div>
    </BottomSheet>
  );
};

/**
 * Deleting a kit, and deleting one material out of a kit.
 *
 * Both are the same shape — name the thing, say what goes with it, then one
 * red button — so they share a body. What they do not share is the warning:
 * a kit takes every material in it down with it, which is a much bigger
 * action than removing one file and worth spelling out separately.
 *
 * Deletion cascades on the server (kit_sources, summaries, quizzes,
 * flashcards) and unlinks the uploaded file from disk, so there is nothing
 * left to undo. That is why both sheets confirm rather than acting on the tap
 * that opened them.
 */
const ConfirmDeleteSheet = ({ labelledBy, closeTo, title, body, confirmLabel, onConfirm }) => {
  const t = useT();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const confirm = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
    } catch (err) {
      setError(toFormError(err));
      setBusy(false);
    }
  };

  return (
    <BottomSheet closeTo={closeTo} labelledBy={labelledBy}>
      <SheetTitle id={labelledBy}>{title}</SheetTitle>
      <SheetSubtitle>{body}</SheetSubtitle>

      <div className="mt-5 space-y-3">
        {error && <SheetError>{error.message ?? t('kits.deleteFailed')}</SheetError>}
        <SheetButton
          onClick={confirm}
          disabled={busy}
          className="!bg-danger-600 hover:!bg-danger-600/90"
        >
          {busy ? t('kits.deleting') : confirmLabel}
        </SheetButton>
        <div className="text-center">
          <button
            type="button"
            onClick={() => navigate(closeTo)}
            disabled={busy}
            className="text-base font-bold text-ink-600"
          >
            {t('common.cancel')}
          </button>
        </div>
      </div>
    </BottomSheet>
  );
};

/** Delete a whole study kit, from the ⋮ on its header. */
export const DeleteKitSheet = () => {
  const t = useT();
  const navigate = useNavigate();
  const { language } = useLanguage();
  const { kitId } = useParams();
  const { getKit, getFiles, removeKit } = useKits();

  const kit = getKit(kitId);
  const name = kit ? (language === 'km' ? (kit.titleKm ?? kit.title) : kit.title) : '';
  // The kit row carries fileCount, so the warning is right on first paint even
  // when the file list has not been fetched on this screen.
  const count = kit?.fileCount ?? getFiles(kitId).length;

  return (
    <ConfirmDeleteSheet
      labelledBy="delete-kit-title"
      closeTo={`/kits/${kitId}`}
      title={t('kits.deleteKitConfirm', { name })}
      body={t('kits.deleteKitBody', { count })}
      confirmLabel={t('kits.deleteKit')}
      onConfirm={async () => {
        await removeKit(kitId);
        // Back to the list rather than the kit that no longer exists.
        navigate('/kits', { replace: true });
      }}
    />
  );
};

/** Delete one material out of a kit, from the ⋮ on its row. */
export const DeleteFileSheet = () => {
  const t = useT();
  const navigate = useNavigate();
  const { kitId, fileId } = useParams();
  const { getFiles, removeFile } = useKits();

  const file = getFiles(kitId).find((item) => item.id === fileId);

  return (
    <ConfirmDeleteSheet
      labelledBy="delete-file-title"
      closeTo={`/kits/${kitId}`}
      title={t('kits.deleteFileConfirm', { name: file?.name ?? t('kits.thisFile') })}
      body={t('kits.deleteFileBody')}
      confirmLabel={t('kits.deleteFile')}
      onConfirm={async () => {
        await removeFile(kitId, fileId);
        navigate(`/kits/${kitId}`, { replace: true });
      }}
    />
  );
};

/**
 * Upload progress for a real request.
 *
 * The bar is driven by axios's onUploadProgress, so it advances with bytes on
 * the wire and stops where the wire stops. The YouTube sheet below still runs a
 * timer, because nothing is being uploaded there — it is waiting on work the
 * server has not been taught to do yet. Keeping the two apart matters: a fake
 * bar next to a real one teaches you to distrust both.
 */
export const UploadingSheet = () => {
  const t = useT();
  const { language } = useLanguage();
  const navigate = useNavigate();
  const location = useLocation();
  const { uploadFile } = useKits();
  const { kitId, root, closeTo } = useAddMaterialPaths();

  const file = location.state?.file ?? null;
  // Asked as "is this a photo?" rather than "is this a PDF?": the picker now
  // also returns Word, Excel, PowerPoint and text files, and every one of
  // those would have been labelled "Analyzing your photo" by the old test.
  const isPhoto = file?.type?.startsWith('image/') ?? false;
  const [percent, setPercent] = useState(0);
  const [error, setError] = useState(null);
  const started = useRef(false);

  useEffect(() => {
    // A File cannot survive a reload — router state is gone on refresh — so
    // send the user back to pick again rather than showing an empty bar.
    if (!file || !kitId) {
      navigate(root, { replace: true });
      return;
    }
    if (started.current) return;
    started.current = true;

    uploadFile(kitId, file, { onProgress: setPercent })
      .then((source) => {
        if (!source?.id) return navigate(closeTo, { replace: true });
        // The state has to ride in the options, not in the `to` object —
        // React Router's To is only { pathname, search, hash }, so a `state`
        // key inside it is dropped without a word. That is what left the
        // processing sheet with no source id to poll for.
        const next = buildProcessingNavigation(kitId, source.id, { uploaded: true, photo: isPhoto });
        return navigate(next.pathname, { replace: true, state: next.state });
      })
      .catch(setError);
    // `isPhoto` is derived from `file`, so it cannot change without it.
  }, [file, isPhoto, kitId, navigate, root, closeTo, uploadFile]);

  /**
   * The upload is the first of the three steps, so it fills the first third of
   * the bar — the processing sheet picks up from 33% rather than starting a
   * second bar at zero. `percent` is axios's byte count, so this segment moves
   * with what is actually on the wire.
   */
  const overallPercent = Math.round(percent / 3);

  const message = () => {
    if (!error) return null;
    if (error.code === 'file_too_large') {
      return t('kits.uploadTooLarge', { limit: formatBytes(error.details?.limit, language) });
    }
    if (error.code === 'unsupported_file_type') return t('kits.uploadWrongType');
    return error.message ?? t('kits.uploadFailed');
  };

  return (
    <BottomSheet closeTo={closeTo} labelledBy="uploading-title">
      {error ? (
        <>
          <SheetTitle id="uploading-title">{t('kits.uploadFailed')}</SheetTitle>
          {file && (
            <SheetSubtitle>
              {file.name} · {formatBytes(file.size, language)}
            </SheetSubtitle>
          )}
          <div className="mt-5 space-y-3">
            <SheetError>{message()}</SheetError>
            <SheetButton onClick={() => navigate(root, { replace: true })}>
              {t('kits.uploadAnother')}
            </SheetButton>
            <div className="text-center">
              <button
                type="button"
                onClick={() => navigate(closeTo, { replace: true })}
                className="text-base font-bold text-ink-600"
              >
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </>
      ) : (
        <AnalyzingBody
          id="uploading-title"
          title={t(isPhoto ? 'kits.analyzingPhoto' : 'kits.analyzingPdf')}
          subtitle={t(isPhoto ? 'kits.analyzingSubtitle' : 'kits.analyzingSubtitleDocument')}
          percent={overallPercent}
          steps={[
            // A camera and the word "photo" on a .docx upload is just wrong —
            // both follow what was actually picked.
            {
              key: isPhoto ? 'kits.stageUploading' : 'kits.stageUploadingDocument',
              tone: 'green',
              icon: isPhoto ? <CameraMark /> : <PdfIcon />,
              state: 'active',
            },
            {
              key: isPhoto ? 'kits.stageReadingNotes' : 'kits.stageReadingFile',
              tone: 'blue',
              icon: <PdfIcon />,
              state: 'pending',
            },
            { key: 'kits.stageCreatingMaterials', tone: 'blue', icon: <CapMark />, state: 'pending' },
          ]}
        />
      )}
    </BottomSheet>
  );
};

/** 05-youtube-url-entry. */
export const YouTubeUrlSheet = () => {
  const t = useT();
  const navigate = useNavigate();
  const { addKit, isDemo } = useKits();
  const { kitId, root } = useAddMaterialPaths();
  const [url, setUrl] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!url.trim() || submitting) return;

    if (isDemo) {
      navigate(`${root}/processing`);
      return;
    }

    setSubmitting(true);
    setError(null);

    try {
      let targetKitId = kitId;
      if (!targetKitId) {
        const createdKit = await addKit({
          title: 'YouTube study kit',
          titleKm: 'ឯកសារសិក្សា YouTube',
          sourceKind: 'youtube',
        });
        targetKitId = createdKit.id;
      }

      const { data } = await api.post(`/kits/${targetKitId}/sources`, {
        kind: 'youtube',
        url: url.trim(),
      });

      navigate(`/kits/${targetKitId}/add/processing`, {
        state: { kitId: targetKitId, sourceId: data.source.id },
      });
    } catch (err) {
      setError(toFormError(err));
      setSubmitting(false);
    }
  };

  return (
    <BottomSheet closeTo={root} labelledBy="youtube-title" transition="from-right">
      <SheetHeading
        id="youtube-title"
        tone="amber"
        icon={<YouTubeMark />}
        title={t('kits.addYoutubeUrl')}
        subtitle={t('kits.addYoutubeUrlHint')}
      />

      <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
        <SheetField
          id="youtube-url"
          label={t('kits.addYoutubeUrl')}
          icon={<LinkMark />}
          placeholder={t('kits.youtubePlaceholder')}
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          type="url"
          inputMode="url"
          required
        />

        {error && <SheetError>{error.message ?? t('kits.createFailed')}</SheetError>}

        <SheetButton type="submit" disabled={submitting || !url.trim()}>
          {submitting ? t('kits.creating') : t('common.continue')}
        </SheetButton>
        <SheetFootnote className="mt-3">{t('kits.youtubeFootnote')}</SheetFootnote>
      </form>
    </BottomSheet>
  );
};

/**
 * Photo and PDF both need the same sheet: a word about what the file is for,
 * then the OS picker. They slide in like the YouTube sheet so every option in
 * the chooser behaves the same way.
 *
 * A file cannot be uploaded until a kit exists, so when this runs from the
 * Kits tab the kit is created the moment a file is chosen — not before, or an
 * abandoned picker would leave an empty kit against the free-plan cap.
 */
const PickFileSheet = ({ kind }) => {
  const t = useT();
  const navigate = useNavigate();
  const { addKit } = useKits();
  const { kitId, root } = useAddMaterialPaths();
  const inputRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const isPhoto = kind === 'photo';
  const accept = isPhoto ? ACCEPT_IMAGE : ACCEPT_DOCUMENT;

  const onFileChosen = async (event) => {
    const file = event.target.files?.[0];
    if (!file || busy) return;
    setBusy(true);
    setError(null);

    try {
      let targetKitId = kitId;
      if (!targetKitId) {
        const created = await addKit({
          title: file.name.replace(/\.[^.]+$/, '') || t('kits.uploadPdf'),
          // The server decides the real kind from the bytes; this only
          // picks the tile icon, and 'document' covers every format the
          // picker now accepts rather than claiming everything is a PDF.
          sourceKind: isPhoto ? 'image' : 'document',
        });
        targetKitId = created.id;
      }
      // The File rides in router state: out of the URL, and gone the moment
      // the upload screen unmounts.
      navigate(`/kits/${targetKitId}/add/uploading`, { state: { file } });
    } catch (err) {
      setError(toFormError(err));
      setBusy(false);
    }
  };

  /**
   * Opens the OS file picker — the gallery route, and the only route for PDFs.
   *
   * "Take a photo" no longer comes through here. It used to open this same
   * input with `capture` set, which asks a PHONE for its camera and is ignored
   * by every desktop browser: the option named "Take a photo" opened a file
   * browser, which is not taking a photo. It now goes to the camera sheet,
   * which opens a real camera wherever the browser can and falls back to this
   * picker where it cannot.
   */
  const openPicker = () => {
    if (busy) return;
    const input = inputRef.current;
    input.value = '';
    input.click();
  };

  return (
    <BottomSheet closeTo={root} labelledBy="pick-file-title" transition="from-right">
      <SheetTitle id="pick-file-title">
        {t(isPhoto ? 'kits.uploadPhoto' : 'kits.uploadPdf')}
      </SheetTitle>
      <SheetSubtitle>{t(isPhoto ? 'kits.photoSubtitle' : 'kits.pdfSubtitle')}</SheetSubtitle>

      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="sr-only"
        onChange={onFileChosen}
        tabIndex={-1}
        aria-hidden="true"
      />

      {error && (
        <div className="mt-5">
          <SheetError>{error.message ?? t('kits.createFailed')}</SheetError>
        </div>
      )}

      {isPhoto ? (
        <div className="mt-5 space-y-3">
          <SheetOption
            tone="blue"
            icon={<CameraMark />}
            title={t('kits.takePhoto')}
            onClick={() => navigate(`${root}/photo/camera`)}
          />
          <SheetOption
            tone="amber"
            icon={<GalleryMark />}
            title={t('kits.chooseFromGallery')}
            onClick={() => openPicker()}
          />
          <SheetFootnote>{t('kits.photoMoreLater')}</SheetFootnote>
        </div>
      ) : (
        <div className="mt-5 rounded-2xl border-2 border-dashed border-tint-200 bg-canvas px-5 py-7 text-center">
          <SheetTile tone="violet" className="mx-auto !size-16">
            <PdfMark />
          </SheetTile>
          <SheetButton className="mt-5" disabled={busy} onClick={() => openPicker()}>
            {busy ? t('kits.creating') : t('kits.choosePdf')}
          </SheetButton>
          {/* Named rather than left to the picker's own filter, which on
              Windows silently greys out files whose Content-Type the machine
              reports wrongly — the student sees a disabled .docx and no
              reason why. */}
          <p className="mt-3 text-base font-medium text-ink-600">{t('kits.documentFormats')}</p>
          <p className="mt-1 text-base font-medium text-ink-600">{t('kits.pdfMaxSize')}</p>
        </div>
      )}
    </BottomSheet>
  );
};

export const PhotoPickSheet = () => <PickFileSheet kind="photo" />;
export const PdfPickSheet = () => <PickFileSheet kind="pdf" />;

/** The topic sheet — the same shape as the YouTube one, a field and a submit. */
export const TopicSheet = () => {
  const t = useT();
  const navigate = useNavigate();
  const { addKit } = useKits();
  const { kitId, root } = useAddMaterialPaths();
  const [topic, setTopic] = useState('');
  const [difficulty, setDifficulty] = useState('beginner');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (event) => {
    event.preventDefault();
    const title = topic.trim();
    if (!title || submitting) return;

    setSubmitting(true);
    setError(null);

    try {
      let targetKitId = kitId;
      if (!targetKitId) {
        const created = await addKit({ title, sourceKind: 'topic' });
        targetKitId = created.id;
      }

      // `difficulty` is sent but not yet honoured: createSourceSchema
      // (backend/app/validation/schemas.py) does not declare it, and zod
      // strips unknown keys, so the server drops it. Teaching the topic
      // generator to read it is a server change, not a styling one.
      const { data } = await api.post(`/kits/${targetKitId}/sources`, {
        kind: 'topic',
        title,
        difficulty,
      });

      navigate(`/kits/${targetKitId}/add/processing`, {
        state: { kitId: targetKitId, sourceId: data.source.id },
      });
    } catch (err) {
      setError(toFormError(err));
      setSubmitting(false);
    }
  };

  return (
    <BottomSheet closeTo={root} labelledBy="topic-title" transition="from-right">
      <SheetHeading
        id="topic-title"
        tone="green"
        icon={<SparkIcon />}
        title={t('kits.enterTopic')}
        subtitle={t('kits.enterTopicHint')}
        trailing={<SparkleMark className="size-8 shrink-0 text-sky-600" />}
      />

      <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
        <SheetField
          id="topic-name"
          label={t('kits.enterTopic')}
          placeholder={t('kits.topicPlaceholder')}
          value={topic}
          onChange={(event) => setTopic(event.target.value)}
          required
        />

        <fieldset>
          <legend className="text-lg font-extrabold text-ink-900">
            {t('kits.chooseDifficulty')}
          </legend>
          <div className="mt-2.5 flex gap-2.5">
            {DIFFICULTIES.map(({ level, labelKey }) => (
              <button
                key={level}
                type="button"
                aria-pressed={difficulty === level}
                onClick={() => setDifficulty(level)}
                className={`flex-1 rounded-full px-3 py-3 text-base font-bold transition-colors ${
                  difficulty === level
                    ? 'bg-brand-600 text-white'
                    : 'bg-canvas text-ink-600 ring-1 ring-tint-200 hover:bg-tint-100'
                }`}
              >
                {t(labelKey)}
              </button>
            ))}
          </div>
        </fieldset>

        {error && <SheetError>{error.message ?? t('kits.createFailed')}</SheetError>}

        <SheetButton type="submit" disabled={submitting || !topic.trim()}>
          {submitting ? t('kits.creating') : t('kits.generateStudyKit')}
        </SheetButton>
      </form>
    </BottomSheet>
  );
};

/**
 * The stages the server reports, in order: reading, extracting and embedding
 * are the ingest of the text itself; `generating` is the model building the
 * study guide, quiz and flashcards; then `ready`
 * (backend/app/services/ingest_service.py).
 *
 * `ready` now means the materials exist, not merely that the text was chunked —
 * which is why the last step can honestly say it is creating them.
 */
const READING_STAGES = ['reading', 'extracting', 'embedding'];

/** Which of the two processing steps a reported stage belongs to. */
const stepOfStage = (stage) => (READING_STAGES.includes(stage) ? 0 : 1);

export const ProcessingSheet = () => {
  const t = useT();
  const navigate = useNavigate();
  const location = useLocation();
  const { addKit, addFile, isDemo, refresh, loadFiles } = useKits();
  const { kitId, closeTo, root } = useAddMaterialPaths();

  const stateKitId = location.state?.kitId || kitId;
  const stateSourceId = location.state?.sourceId;

  /**
   * The step list adapts to how this sheet was reached. After a file upload the
   * reference shows the upload already ticked off; the YouTube and topic paths
   * never uploaded anything, so they show what the server actually reports
   * instead of a step that did not happen.
   */
  const cameFromUpload = Boolean(location.state?.uploaded);

  /**
   * Which wording the steps use. Seeded from the handoff so the first paint is
   * already right, then confirmed against the kind the server reports — the
   * server reads the real format from the bytes, so a photo saved with a .pdf
   * name is corrected here rather than mislabelled for the whole run.
   */
  const [isPhoto, setIsPhoto] = useState(Boolean(location.state?.photo));

  // Exactly what the server last said, kept unscaled. Everything drawn below is
  // derived from these two values, so the bar and the ticks cannot disagree
  // with the job they are describing.
  const [stage, setStage] = useState('reading');
  const [serverPercent, setServerPercent] = useState(0);
  const [pollError, setPollError] = useState(null);
  const finished = useRef(false);

  /**
   * Demo mode only. It drives the same two values the poller does, so the sheet
   * has one code path to render; it must never run against a real account,
   * which is why the guard is `isDemo` alone. A live visit that arrives without
   * a source id has nothing to report on and is sent back to choose again,
   * rather than being shown a timer pretending to be progress.
   */
  useEffect(() => {
    if (!isDemo) return undefined;

    const timer = setInterval(() => {
      setServerPercent((p) => {
        const next = Math.min(100, p + 4);
        setStage(next >= 100 ? 'ready' : next >= 55 ? 'generating' : 'reading');
        if (next >= 100) {
          clearInterval(timer);
          if (!finished.current) {
            finished.current = true;
            if (kitId) {
              addFile(kitId, {
                name: 'Intro to Databases — full lecture',
                kind: 'youtube',
                size: '5h 02m',
              });
              navigate(closeTo);
            } else {
              const created = addKit({
                title: 'YouTube study kit',
                titleKm: 'ឯកសារសិក្សា YouTube',
                sourceKind: 'youtube',
                cardCount: 6,
                progress: 5,
              });
              navigate(`/kits/${created.id}`);
            }
          }
        }
        return next;
      });
    }, 60);
    return () => clearInterval(timer);
  }, [addFile, addKit, closeTo, isDemo, kitId, navigate]);

  // Nothing to poll and not a demo: go back rather than invent progress.
  useEffect(() => {
    if (isDemo || (stateSourceId && stateKitId)) return;
    navigate(root, { replace: true });
  }, [isDemo, navigate, root, stateKitId, stateSourceId]);

  // Live polling mode
  useEffect(() => {
    if (isDemo || !stateSourceId || !stateKitId) return;

    let isMounted = true;
    let pollTimer;

    const poll = async () => {
      try {
        const { data } = await api.get(`/kits/${stateKitId}/sources/${stateSourceId}`);
        if (!isMounted) return;
        const currentSource = data.source;

        // Taken as reported. No multiplier and no floor: a floor would show
        // progress the server has not claimed, and a multiplier would mean the
        // number on screen is not the one it sent.
        setStage(currentSource.stage || 'reading');
        if (currentSource.kind) setIsPhoto(currentSource.kind === 'image');
        setServerPercent(Math.max(0, Math.min(100, currentSource.progressPercent ?? 0)));

        if (isSourceReadyForStudy(currentSource)) {
          setStage('ready');
          setServerPercent(100);
          await refresh();
          await loadFiles(stateKitId).catch(() => {});
          navigate(`/kits/${stateKitId}`, { replace: true });
        } else if (currentSource.status === 'failed') {
          setPollError(currentSource.errorMessage || t('kits.processingFailed'));
        } else {
          pollTimer = setTimeout(poll, 1500);
        }
      } catch (err) {
        if (!isMounted) return;
        setPollError(err.message || t('kits.processingFailed'));
      }
    };

    poll();

    return () => {
      isMounted = false;
      clearTimeout(pollTimer);
    };
  }, [isDemo, loadFiles, navigate, refresh, stateKitId, stateSourceId, t]);

  // A step is ticked because the server has moved past it, not because a
  // counter crossed a threshold.
  const ready = stage === 'ready';
  const current = stepOfStage(stage);
  const stepState = (index) =>
    ready || index < current ? 'done' : index === current ? 'active' : 'pending';

  const processingSteps = [
    {
      key: cameFromUpload ? (isPhoto ? 'kits.stageReadingNotes' : 'kits.stageReadingFile') : 'kits.stageReading',
      tone: 'blue',
      icon: cameFromUpload ? <PdfIcon /> : <VideoIcon className="size-8" />,
      state: stepState(0),
    },
    { key: 'kits.stageCreatingMaterials', tone: 'blue', icon: <CapMark />, state: stepState(1) },
  ];

  /**
   * The upload is a real step that really finished, so it is shown ticked and
   * counts toward the total. That makes it one of three, which is the only
   * modelling here: the server's own 0–100 for the work that remains fills the
   * last two thirds, so the bar carries on from where the upload sheet left it
   * instead of dropping back to zero.
   */
  const stages = cameFromUpload
    ? [
        {
          key: isPhoto ? 'kits.stageUploading' : 'kits.stageUploadingDocument',
          tone: 'green',
          icon: isPhoto ? <CameraMark /> : <PdfIcon />,
          state: 'done',
        },
        ...processingSteps,
      ]
    : processingSteps;

  const percent = cameFromUpload
    ? Math.round(100 / 3 + serverPercent * (2 / 3))
    : serverPercent;

  return (
    <BottomSheet closeTo={closeTo} labelledBy="processing-title" dismissible={Boolean(pollError)}>
      {pollError ? (
        <>
          <SheetTitle id="processing-title">{t('kits.processingFailed')}</SheetTitle>
          <div className="mt-5 space-y-3">
            <SheetError>{pollError}</SheetError>
            <SheetButton onClick={() => navigate(`${root}/youtube`, { replace: true })}>
              {t('kits.uploadAnother')}
            </SheetButton>
            <div className="text-center">
              <button
                type="button"
                onClick={() => navigate(closeTo, { replace: true })}
                className="text-base font-bold text-ink-600"
              >
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </>
      ) : (
        <AnalyzingBody
          id="processing-title"
          title={t('kits.processingTitle')}
          subtitle={t(
            cameFromUpload && !isPhoto ? 'kits.analyzingSubtitleDocument' : 'kits.analyzingSubtitle',
          )}
          percent={percent}
          steps={stages}
        />
      )}
    </BottomSheet>
  );
};

/** 02-create-study-folder — named "Create a study kit" in the design. */
export const CreateKitSheet = () => {
  const t = useT();
  const navigate = useNavigate();
  const location = useLocation();
  const { addKit } = useKits();
  const [name, setName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const nextPath = location.pathname === '/kits/new' ? (kitId) => `/kits/${kitId}/add` : (kitId) => `/kits/${kitId}`;

  return (
    <BottomSheet closeTo="/kits" labelledBy="create-kit-title">
      <SheetTitle id="create-kit-title">{t('kits.createKitTitle')}</SheetTitle>
      <SheetSubtitle>{t('kits.createKitSubtitle')}</SheetSubtitle>

      <form
        className="mt-6 space-y-4"
        onSubmit={async (event) => {
          event.preventDefault();
          if (submitting) return;
          setSubmitting(true);
          setError(null);
          try {
            const kit = await addKit({ title: name });
            navigate(nextPath(kit.id));
          } catch (err) {
            setError(err);
            setSubmitting(false);
          }
        }}
      >
        {/* The folder sits inside the field as its own tile, per the
            reference, rather than as a plain leading glyph. */}
        <div className="relative">
          <span className="pointer-events-none absolute left-2 top-1/2 grid size-12 -translate-y-1/2 place-items-center rounded-xl bg-tile-blue text-brand-600">
            <FolderMark className="size-7" />
          </span>
          <SheetField
            id="kit-name"
            label={t('kits.createKitTitle')}
            placeholder={t('kits.kitNamePlaceholder')}
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="[&>input]:pl-[4.25rem]"
            required
          />
        </div>

        {/* The cap is the one failure with a way out, so it gets the count and
            a route to Plus rather than a bare error line. */}
        {error?.code === 'quota_exceeded' ? (
          <div className="rounded-card bg-gold-400/20 p-4 text-center">
            <p className="text-base font-bold text-navy-900">{t('kits.quotaTitle')}</p>
            <p className="mt-1 text-sm text-navy-700">
              {t('kits.quotaBody', {
                used: error.details?.used ?? 0,
                limit: error.details?.limit ?? 0,
              })}
            </p>
            <Link
              to="/"
              className="mt-4 inline-flex rounded-full bg-navy-800 px-6 py-3 text-base font-bold text-white"
            >
              {t('kits.upgradeToPlus')}
            </Link>
          </div>
        ) : (
          error && (
            <p className="rounded-card bg-danger-50 px-4 py-3 text-center text-base text-danger-600">
              {error.message ?? t('kits.createFailed')}
            </p>
          )
        )}

        <SheetButton type="submit" disabled={submitting || !name.trim()}>
          {submitting ? t('kits.creating') : t('common.continue')}
        </SheetButton>
        <p className="mt-3 flex items-center justify-center gap-2 text-center text-base font-medium text-ink-600">
          <SparkleMark />
          {t('kits.createKitFootnote')}
        </p>
      </form>
    </BottomSheet>
  );
};


/** The three levels the topic sheet offers. */
const DIFFICULTIES = [
  { level: 'beginner', labelKey: 'kits.difficultyBeginner' },
  { level: 'intermediate', labelKey: 'kits.difficultyIntermediate' },
  { level: 'advanced', labelKey: 'kits.difficultyAdvanced' },
];

/** A failure line inside a sheet. */
const SheetError = ({ children }) => (
  <p role="alert" className="rounded-2xl bg-danger-50 px-4 py-3 text-center text-base font-medium text-danger-600">
    {children}
  </p>
);

/**
 * The analyzing screen: a percentage bar over a checklist of stages.
 *
 * Shared by the upload sheet and the processing sheet so the two routes read as
 * one continuous screen — the reference draws them that way, with the upload
 * already ticked off by the time the server is reading the file.
 */
const AnalyzingBody = ({ id, title, subtitle, percent, steps }) => {
  const t = useT();
  return (
    <>
      <SheetTitle id={id}>{title}</SheetTitle>
      <SheetSubtitle>{subtitle}</SheetSubtitle>

      <div className="mt-4 rounded-card bg-tint-100 p-4">
        <p className="text-sm font-extrabold text-navy-900">{t('kits.processingWhyTitle')}</p>
        <p className="mt-1 text-sm leading-relaxed text-navy-700">{t('kits.processingWhyBody')}</p>
      </div>

      <div className="mt-6 flex items-center gap-3">
        <div
          className="h-2.5 flex-1 overflow-hidden rounded-full bg-tint-100"
          role="progressbar"
          aria-valuenow={percent}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={t('kits.uploading', { percent })}
        >
          <span
            className="block h-full rounded-full bg-sky-600 transition-[width] duration-200"
            style={{ width: `${percent}%` }}
          />
        </div>
        <span className="text-lg font-extrabold text-sky-600">{percent}%</span>
      </div>

      <ol className="mt-5 space-y-3">
        {steps.map(({ key, tone, icon, state }) => (
          <li
            key={key}
            className={`flex items-center gap-3.5 rounded-2xl p-3 ${
              state === 'pending'
                ? 'bg-canvas'
                : 'bg-white shadow-sm ring-1 ring-tint-200/70'
            }`}
          >
            <SheetTile
              tone={state === 'pending' ? 'grey' : tone}
              className={state === 'pending' ? '!text-ink-400' : ''}
            >
              {icon}
            </SheetTile>
            <span
              className={`min-w-0 flex-1 text-lg font-extrabold ${
                state === 'pending' ? 'text-ink-400' : 'text-ink-900'
              }`}
            >
              {t(key)}
            </span>
            <StepState state={state} />
          </li>
        ))}
      </ol>
    </>
  );
};

/**
 * A stage's marker: ticked, spinning, or waiting.
 *
 * The spinner is `motion-safe` — someone who asked for reduced motion gets a
 * still ring, and the percentage beside the bar still tells them work is moving.
 */
const StepState = ({ state }) => {
  if (state === 'done') {
    return (
      <span className="grid size-7 shrink-0 place-items-center rounded-full bg-success-500 text-white">
        <svg viewBox="0 0 20 20" className="size-4" fill="none" aria-hidden="true">
          <path d="M4 10.5 8 14.5 16 6" stroke="currentColor" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
    );
  }
  if (state === 'active') {
    return (
      <span
        className="size-7 shrink-0 rounded-full border-[3px] border-tile-blue border-t-sky-600 motion-safe:animate-spin"
        aria-hidden="true"
      />
    );
  }
  return <span className="size-7 shrink-0 rounded-full border-[3px] border-tint-200" aria-hidden="true" />;
};

const PlusMark = () => (
  <svg viewBox="0 0 24 24" className="size-7" fill="none" aria-hidden="true">
    <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
  </svg>
);

const FolderMark = ({ className = 'size-6' }) => (
  <svg viewBox="0 0 24 24" className={className} fill="none" aria-hidden="true">
    <path
      d="M3 7a2 2 0 0 1 2-2h4.6l2 2.4H19a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"
      fill="currentColor"
      fillOpacity="0.3"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinejoin="round"
    />
  </svg>
);

/** YouTube keeps its own red — it is a brand mark, not a tinted glyph. */
const YouTubeMark = () => (
  <svg viewBox="0 0 32 32" className="size-9" aria-hidden="true">
    <rect x="3" y="7" width="26" height="18" rx="5" fill="#FF3D3D" />
    <path d="m13 12 8 4-8 4z" fill="#fff" />
  </svg>
);

const LinkMark = () => (
  <svg viewBox="0 0 24 24" className="size-6" fill="none" aria-hidden="true">
    <path
      d="M10 13.5a3.5 3.5 0 0 0 5 0l3-3a3.5 3.5 0 0 0-5-5l-1.2 1.2M14 10.5a3.5 3.5 0 0 0-5 0l-3 3a3.5 3.5 0 0 0 5 5l1.2-1.2"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
    />
  </svg>
);

const SparkleMark = ({ className = 'size-5 text-gold-400' }) => (
  <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden="true">
    <path d="m12 2 2.2 5.8L20 10l-5.8 2.2L12 18l-2.2-5.8L4 10l5.8-2.2z" />
    <path d="m19 15 .9 2.1 2.1.9-2.1.9L19 21l-.9-2.1-2.1-.9 2.1-.9z" />
  </svg>
);

const CameraMark = () => (
  <svg {...svg}>
    <path d="M5 11h5l2-3h8l2 3h5a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V13a2 2 0 0 1 2-2Z" />
    <circle cx="16" cy="18.5" r="4.5" />
  </svg>
);

const GalleryMark = () => (
  <svg {...svg}>
    <rect x="4" y="5" width="24" height="22" rx="3" />
    <circle cx="11.5" cy="12" r="2" />
    <path d="m6 24 7-7 4.5 4.5L21 18l5 6" />
  </svg>
);

const PdfMark = () => (
  <svg viewBox="0 0 32 32" className="size-9" fill="none" aria-hidden="true">
    <path
      d="M19 4H9a2 2 0 0 0-2 2v20a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V10z"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinejoin="round"
    />
    <path d="M19 4v6h6" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
    <text x="16" y="23" textAnchor="middle" fontSize="7" fontWeight="700" fill="currentColor">
      PDF
    </text>
  </svg>
);

/** The graduation cap on the "creating study materials" stage. */
const CapMark = () => (
  <svg {...svg}>
    <path d="M16 6 3 12l13 6 13-6z" />
    <path d="M9 15v7c0 1.7 3.1 3 7 3s7-1.3 7-3v-7" />
  </svg>
);

const svg = {
  viewBox: '0 0 32 32',
  fill: 'none',
  className: 'size-8',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': 'true',
};

const PhotoIcon = () => (
  <svg {...svg}>
    <rect x="4" y="6" width="24" height="20" rx="3" />
    <circle cx="12" cy="13" r="2.2" />
    <path d="m6 23 7-7 5 5 3-3 5 5" />
  </svg>
);

const PdfIcon = () => (
  <svg {...svg}>
    <path d="M19 4H9a2 2 0 0 0-2 2v20a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V10z" />
    <path d="M19 4v6h6M12 17h8M12 22h5" />
  </svg>
);

const PlayIcon = () => (
  <svg {...svg}>
    <rect x="3" y="7" width="26" height="18" rx="4" />
    <path d="m13 12 8 4-8 4z" fill="currentColor" stroke="none" />
  </svg>
);

const SparkIcon = () => (
  <svg {...svg}>
    <path d="M28 15.5c0 5.8-5.4 10.5-12 10.5a14 14 0 0 1-3.6-.5L5 28l2.2-5.6A9.7 9.7 0 0 1 4 15.5C4 9.7 9.4 5 16 5s12 4.7 12 10.5Z" />
    <path d="m20 11 1.2 2.6L24 15l-2.8 1.4L20 19l-1.2-2.6L16 15l2.8-1.4z" fill="currentColor" stroke="none" />
  </svg>
);

const VideoIcon = ({ className = 'size-12' }) => (
  <svg viewBox="0 0 48 48" className={className} fill="none" aria-hidden="true">
    <path d="M28 6H14a3 3 0 0 0-3 3v30a3 3 0 0 0 3 3h20a3 3 0 0 0 3-3V15z" fill="#0C3C85" />
    <path d="M28 6v9h9" fill="#fff" fillOpacity="0.35" />
    <path d="m20 20 10 6-10 6z" fill="#fff" />
  </svg>
);

