-- Record what each generated question was aiming at.
--
-- A quiz is now adaptive: most of its questions are written to attack the
-- subtopics the student has already got wrong, and the rest cover the rest of
-- the document. `targeted_weak_concept` is the generator saying which of the
-- two a question is, and which weakness it is aimed at.
--
-- Worth storing rather than inferring, for two reasons. The mix has to be
-- checkable after the fact — "70% of questions targeted a weak area" is a claim
-- about a quiz that actually exists, not about a prompt. And a student's weak
-- topics move: the concept that was weak when this question was written is not
-- the set that is weak today, so reading it back off current mastery would
-- rewrite history.
--
-- NULL means the question was not aimed at a known weakness, which is what
-- every question generated before this column existed was.

ALTER TABLE quiz_questions
  ADD COLUMN targeted_weak_concept text;

-- Answers the "how adaptive was this quiz" question in one scan per quiz.
CREATE INDEX quiz_questions_targeted_weak_concept_idx
  ON quiz_questions (quiz_id)
  WHERE targeted_weak_concept IS NOT NULL;
