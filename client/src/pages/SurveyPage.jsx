import { useEffect, useState } from 'react';
import { Navigate, useNavigate, useParams } from 'react-router-dom';

import { useAuth } from '../auth/AuthContext.jsx';
import { Button, FormAlert, OptionCard, StepIndicator, TextButton } from '../components/ui.jsx';
import { Owl, Wordmark } from '../layouts/AuthLayout.jsx';
import { toFormError } from '../lib/api.js';
import { useT } from '../i18n/index.js';
import {
  BrainIcon,
  CalendarClockIcon,
  CalendarCheckIcon,
  CalendarWeekIcon,
  ExamIcon,
  MixedIcon,
  OpenBookIcon,
  RecallIcon,
  StopwatchIcon,
  UnsureIcon,
} from '../components/surveyIcons.jsx';

/**
 * docs/screens/01-auth-onboarding/05, 06 and 07 — one component, three steps.
 *
 * The option ids here MUST match SURVEY_QUESTIONS in
 * backend/app/services/onboarding_service.py. The server validates with
 * strictObject, so a drifted id comes back as a 422 rather than being silently
 * dropped — and this page renders that as a visible error on the question.
 */
const STEPS = [
  {
    field: 'improveFirst',
    titleKey: 'onboarding.surveyTitle',
    subtitleKey: 'onboarding.surveySubtitle',
    questionKey: 'onboarding.improveQuestion',
    owl: 'default',
    options: [
      { value: 'understand_topics', labelKey: 'onboarding.improveUnderstand', Icon: BrainIcon },
      { value: 'remember', labelKey: 'onboarding.improveRemember', Icon: RecallIcon },
      { value: 'exam_prep', labelKey: 'onboarding.improveExams', Icon: ExamIcon },
      { value: 'daily_habit', labelKey: 'onboarding.improveHabit', Icon: CalendarClockIcon },
    ],
  },
  {
    field: 'studyStyle',
    titleKey: 'onboarding.styleTitle',
    subtitleKey: 'onboarding.styleSubtitle',
    questionKey: 'onboarding.styleQuestion',
    owl: 'default',
    options: [
      {
        value: 'short_sessions',
        labelKey: 'onboarding.styleShort',
        hintKey: 'onboarding.styleShortHint',
        Icon: StopwatchIcon,
      },
      {
        value: 'deep_study',
        labelKey: 'onboarding.styleDeep',
        hintKey: 'onboarding.styleDeepHint',
        Icon: OpenBookIcon,
      },
      {
        value: 'mix',
        labelKey: 'onboarding.styleMix',
        hintKey: 'onboarding.styleMixHint',
        Icon: MixedIcon,
      },
      {
        value: 'unsure',
        labelKey: 'onboarding.styleUnsure',
        hintKey: 'onboarding.styleUnsureHint',
        Icon: UnsureIcon,
      },
    ],
  },
  {
    field: 'studyFrequency',
    titleKey: 'onboarding.rhythmTitle',
    subtitleKey: 'onboarding.rhythmSubtitle',
    questionKey: 'onboarding.rhythmQuestion',
    owl: 'default',
    ctaKey: 'onboarding.seeMyPlan',
    options: [
      {
        value: 'every_day',
        labelKey: 'onboarding.rhythmDaily',
        hintKey: 'onboarding.rhythmDailyHint',
        Icon: CalendarClockIcon,
      },
      {
        value: 'few_times_week',
        labelKey: 'onboarding.rhythmFewTimes',
        hintKey: 'onboarding.rhythmFewTimesHint',
        Icon: CalendarWeekIcon,
      },
      {
        value: 'once_week',
        labelKey: 'onboarding.rhythmWeekly',
        hintKey: 'onboarding.rhythmWeeklyHint',
        Icon: CalendarCheckIcon,
      },
      {
        value: 'decide_later',
        labelKey: 'onboarding.rhythmLater',
        hintKey: 'onboarding.rhythmLaterHint',
        Icon: CalendarClockIcon,
      },
    ],
  },
];

export const SurveyPage = () => {
  const t = useT();
  const navigate = useNavigate();
  const { step: stepParam } = useParams();
  const { submitSurvey, onboarding, user } = useAuth();

  const stepNumber = Number(stepParam);
  const index = stepNumber - 1;
  const step = STEPS[index];

  const [choice, setChoice] = useState(null);
  const [busy, setBusy] = useState(false);
  const [fieldError, setFieldError] = useState(null);
  const [formError, setFormError] = useState(null);

  // Re-hydrate a previous answer when stepping back, and reset errors on move.
  useEffect(() => {
    if (!step) return;
    setChoice(onboarding.surveyAnswers?.[step.field] ?? null);
    setFieldError(null);
    setFormError(null);
    // Only when the step changes — not on every answer update.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stepParam]);

  if (!step) return <Navigate to="/onboarding/survey/1" replace />;

  const isLast = index === STEPS.length - 1;
  const finishOnboarding = () => navigate(user?.role === 'teacher' ? '/teacher' : '/', { replace: true });

  const advance = () => (isLast ? finishOnboarding() : navigate(`/onboarding/survey/${stepNumber + 1}`));

  const persist = async ({ skip }) => {
    setBusy(true);
    setFieldError(null);
    setFormError(null);

    try {
      await submitSurvey({
        answers: skip || !choice ? {} : { [step.field]: choice },
        skipped: skip,
        complete: skip || isLast,
      });
      if (skip) finishOnboarding();
      else advance();
    } catch (error) {
      const { code, message, fields } = toFormError(error);

      // A 422 from strictObject names the offending key. Show it ON the
      // question rather than letting the submit look like a no-op.
      const own = fields[step.field];
      if (own) {
        setFieldError(t('onboarding.answerRejected', { detail: own }));
      } else if (code === 'validation_failed') {
        setFieldError(t('onboarding.answerRejected', { detail: message ?? t('errors.validation') }));
      } else {
        setFormError(code === 'network' ? t('errors.network') : (message ?? t('errors.generic')));
      }
    } finally {
      // Steps 1 and 2 navigate within this same component, so `busy` survives
      // the step change. Clearing it only on the error path left Continue and
      // Skip disabled from step 2 onwards — the survey could not be finished.
      setBusy(false);
    }
  };

  return (
    <main className="flex flex-1 flex-col">
      <div className="flex items-center justify-between pt-2">
        <Wordmark className="text-2xl" />
        <TextButton onClick={() => persist({ skip: true })} disabled={busy}>
          {t('common.skip')}
        </TextButton>
      </div>

      <div className="mt-5">
        <StepIndicator current={stepNumber} total={STEPS.length} />
      </div>

      <div className="mt-6 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold leading-tight text-navy-900">{t(step.titleKey)}</h1>
          <p className="mt-2 text-base text-ink-500">{t(step.subtitleKey)}</p>
        </div>
        <Owl variant={step.owl} className="size-20 shrink-0" />
      </div>

      <hr className="mt-5 border-tint-200" />

      <h2 className="mt-5 text-lg font-bold text-navy-900">{t(step.questionKey)}</h2>

      <div
        className="mt-4 space-y-3"
        role="radiogroup"
        aria-label={t(step.questionKey)}
        aria-invalid={fieldError ? 'true' : undefined}
        aria-describedby={fieldError ? 'survey-error' : undefined}
      >
        {step.options.map(({ value, labelKey, hintKey, Icon }) => (
          <OptionCard
            key={value}
            name={step.field}
            value={value}
            checked={choice === value}
            onChange={(next) => {
              setChoice(next);
              setFieldError(null);
            }}
            icon={<Icon />}
            title={t(labelKey)}
            description={hintKey ? t(hintKey) : undefined}
          />
        ))}
      </div>

      {fieldError && (
        <p id="survey-error" role="alert" className="mt-3 text-sm font-medium text-danger-600">
          {fieldError}
        </p>
      )}

      <div className="mt-8 space-y-3 pb-2">
        <FormAlert>{formError}</FormAlert>
        <Button onClick={() => persist({ skip: false })} disabled={!choice || busy}>
          {busy ? t('common.loading') : t(step.ctaKey ?? 'common.continue')}
        </Button>
        {stepNumber > 1 && (
          <div className="text-center">
            <TextButton onClick={() => navigate(`/onboarding/survey/${stepNumber - 1}`)}>
              {t('common.back')}
            </TextButton>
          </div>
        )}
      </div>
    </main>
  );
};
