-- Make "Write your answer" gradeable.
--
-- The setup screen offers two answer formats. Written answers are currently
-- marked in practiceDb.answer by lowercasing both sides and comparing them for
-- equality, against `correct_answer` — which for a multiple-choice question is
-- the text of the winning option. So a student who understands the material
-- perfectly and phrases it in their own words is marked wrong, and Khmer gets
-- no normalisation at all. That is worse than not offering the format, which is
-- why the toggle was quietly hardcoded off for mock exams instead of fixed.
--
-- Two columns, one for each half of the problem.

-- What a typed answer is marked AGAINST: the correct answer written out in
-- full, carried over from mock_exam_questions.expected_answer when the session
-- is built. Nullable, because a session drawn from the quiz pool has no such
-- text — quiz questions only ever stored an index into their options, which is
-- the whole reason grading them as prose fails. Those fall back to the existing
-- string comparison, so nothing that works today stops working.
ALTER TABLE practice_session_questions
  ADD COLUMN expected_answer text;

-- Why an answer was marked the way it was, in the student's language.
--
-- A wrong mark on free text is not self-evident the way a wrong multiple-choice
-- answer is — the student can see they typed something reasonable, and without
-- a reason the score just looks broken. One line, written by the grader.
ALTER TABLE practice_answers
  ADD COLUMN grader_note text;

-- `practice_answers.is_correct` is already nullable, which is what lets a
-- written answer be saved ungraded and marked at submit instead. That matters:
-- grading at submit is one batched AI call per session rather than one per
-- answer, and the student never waits on the model while typing. No change
-- needed here — recorded because it is load-bearing and easy to "tidy" into
-- NOT NULL later.
