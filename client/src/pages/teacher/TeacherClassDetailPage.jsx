import { useMemo, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';

import { useT } from '../../i18n/index.js';
import { API_BASE_URL } from '../../lib/api.js';
import { useClassDetail } from '../classes/useClasses.js';
import { deleteTeacherAssignment, deleteTeacherClass, deleteTeacherMaterial, useTeacherClassStudents, useTeacherMaterials } from './useTeacher.js';
import { Avatar, ClassArt, Chevron, Progress, SearchField, StatusPill, TeacherButton, TeacherCard, TeacherHeader, TeacherIcon, TeacherIconTile, TeacherToggle } from './TeacherUI.jsx';

const TABS = ['overview', 'materials', 'classwork', 'people'];

export const TeacherClassDetailPage = () => {
  const t = useT();
  const navigate = useNavigate();
  const location = useLocation();
  const { classId } = useParams();
  const { data, refresh } = useClassDetail(classId);
  const { data: studentsData } = useTeacherClassStudents(classId);
  const { data: materialsData, refresh: refreshMaterials } = useTeacherMaterials(classId);
  const [tab, setTab] = useState(new URLSearchParams(location.search).get('tab') || 'overview');
  const [manage, setManage] = useState(new URLSearchParams(location.search).get('manage') === '1');
  const [scores, setScores] = useState(new URLSearchParams(location.search).get('scores') === '1');
  const klass = data?.class;
  const students = studentsData?.students ?? [];
  const materials = materialsData?.materials?.length ? materialsData.materials : (data?.materials ?? []);
  const assignments = data?.assignments ?? [];

  const chooseTab = (next) => {
    setTab(next);
    navigate(`/teacher/classes/${classId}?tab=${next}`, { replace: true });
  };

  if (scores) return <TeacherScores classId={classId} klass={klass} students={students} />;

  return (
    <main className="teacher-page min-h-full pb-5">
      <TeacherHeader backTo="/teacher/classes" compact>
        <ClassSummary klass={klass} students={students} />
      </TeacherHeader>
      <div className="px-5 pt-4">
        <div role="tablist" aria-label={t('teacher.classesTitle')} className="grid grid-cols-4 rounded-[1.35rem] bg-white p-1 shadow-sm ring-1 ring-[#dceafb]">
          {TABS.map((key) => <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => chooseTab(key)} className={`relative rounded-xl px-1 py-3 text-sm font-extrabold ${tab === key ? 'text-[#124a9a]' : 'text-[#5680bd]'}`}>{t(`teacher.${key}`)}{tab === key && <span className="absolute inset-x-3 bottom-1 h-1 rounded-full bg-[#2459b3]" />}</button>)}
        </div>
        <div className="pt-4">
          {tab === 'overview' && <Overview t={t} classId={classId} assignments={assignments} materials={materials} students={students} setTab={chooseTab} onManage={() => setManage(true)} />}
          {tab === 'materials' && <Materials t={t} classId={classId} materials={materials} assignments={assignments} quizzes={data?.quizzes ?? []} refresh={() => { refreshMaterials(); refresh(); }} />}
          {tab === 'classwork' && <Classwork t={t} classId={classId} assignments={assignments} />}
          {tab === 'people' && <People t={t} students={students} onScores={() => setScores(true)} />}
        </div>
      </div>
      {manage && <ManageSheet t={t} classId={classId} klass={klass} onClose={() => setManage(false)} onDeleted={() => navigate('/teacher/classes', { replace: true })} />}
    </main>
  );
};

const ClassSummary = ({ klass, students }) => {
  const t = useT();
  return <div className="mt-4 flex items-center gap-3 rounded-[1.45rem] bg-white p-3 text-[#16458e] shadow-[0_9px_20px_rgb(5_37_102/0.12)]"><ClassArt coverUrl={klass?.coverUrl} className="size-[5.2rem]" /><div className="min-w-0 flex-1"><h1 className="truncate text-2xl font-extrabold leading-tight">{klass?.title ?? t('common.loading')}</h1><p className="mt-2 flex items-center gap-1.5 text-sm font-bold text-[#1d58ad]"><TeacherIcon name="people" className="size-4" />{students.length} {t('teacher.students')}</p>{klass?.joinCode && <span className="mt-2 inline-flex rounded-full bg-[#e7f4ff] px-2.5 py-1 text-sm font-bold text-[#0b67d0]">{t('teacher.joinCode')}: {klass.joinCode}</span>}</div></div>;
};

const Overview = ({ t, classId, assignments, materials, students, setTab, onManage }) => {
  const pending = assignments.filter((item) => item.status !== 'completed').length;
  return <div className="space-y-4">
    <TeacherCard className="border-l-4 border-l-[#ffae2f]">
      <div className="flex flex-wrap items-center gap-3"><TeacherIconTile name="info" tone="gold" /><h2 className="flex-1 text-xl font-extrabold text-[#16458e]">{t('teacher.needsAttention')}</h2><StatusPill tone="gold">{t('teacher.actionNeeded')}</StatusPill></div>
      <AttentionRow to={`/teacher/assignments${assignments[0]?.id ? `/${assignments[0].id}` : ''}`} icon="assignment" title={`${pending} ${t('teacher.toReview').toLowerCase()}`} label={t('teacher.classwork')} />
      <AttentionRow onClick={() => setTab('people')} icon="people" title={`${students.filter((student) => Number(student.averageScore) < 70).length} ${t('teacher.needsSupport').toLowerCase()}`} label={t('teacher.people')} />
      <AttentionRow onClick={() => setTab('materials')} icon="book" title={`${materials.length} ${t('teacher.materials').toLowerCase()}`} label={t('teacher.materials')} />
    </TeacherCard>
    <TeacherCard>
      <div className="flex items-center gap-3"><TeacherIconTile name="clock" /><h2 className="text-xl font-extrabold text-[#16458e]">{t('teacher.recentActivity')}</h2></div>
      {students.slice(0, 3).map((student, index) => <div key={student.id} className="mt-3 flex items-center gap-3 border-t border-[#e4effb] pt-3"><Avatar name={student.name} className="size-11" /><span className="min-w-0 flex-1"><strong className="block truncate text-base text-[#17488f]">{student.name}</strong><span className="block text-sm font-semibold text-[#7a9ed2]">{index === 0 ? t('teacher.submitted') : t('teacher.active')}</span></span><Chevron className="text-[#1555ad]" /></div>)}
      {!students.length && <p className="mt-4 text-center font-semibold text-[#7a9ed2]">{t('teacher.noClasses')}</p>}
    </TeacherCard>
    <TeacherButton tone="gold" className="w-full" onClick={onManage}><TeacherIcon name="settings" className="size-6" />{t('teacher.manageClass')}</TeacherButton>
    <Link to={`/teacher/classes/${classId}?tab=materials`} className="sr-only">{t('teacher.materials')}</Link>
  </div>;
};

const AttentionRow = ({ title, label, icon, to, onClick }) => {
  const content = <><TeacherIconTile name={icon} className="size-10 rounded-xl" iconClassName="size-5" /><span className="min-w-0 flex-1"><strong className="block truncate text-base text-[#17488f]">{title}</strong><span className="text-sm font-semibold text-[#7597ca]">{label}</span></span><Chevron className="text-[#1555ad]" /></>;
  const className = 'mt-3 flex w-full items-center gap-3 border-t border-[#e4effb] pt-3 text-left';
  return to ? <Link to={to} className={className}>{content}</Link> : <button type="button" onClick={onClick} className={className}>{content}</button>;
};

const Materials = ({ t, classId, materials, assignments, quizzes, refresh }) => {
  const [error, setError] = useState(null);
  const classwork = [
    ...assignments.filter((item) => item.status === 'published').map((item) => ({ ...item, materialType: item.type === 'quiz' ? 'quiz' : 'assignment', week: item.week ?? 1 })),
    ...quizzes.filter((item) => item.status === 'ready' && !assignments.some((assignment) => assignment.quizId === item.id)).map((item) => ({ ...item, materialType: 'quiz', week: item.week ?? 1 })),
  ];
  const byWeek = [...materials, ...classwork].reduce((groups, item) => {
    const week = Number(item.week ?? 1);
    groups[week] ??= [];
    groups[week].push(item);
    return groups;
  }, {});
  const removeMaterial = async (item) => {
    if (!window.confirm(t('teacher.deleteMaterialConfirm', { name: item.title }))) return;
    try { await deleteTeacherMaterial(classId, item.id); refresh(); } catch (cause) { setError(cause?.response?.data?.error?.message ?? t('errors.generic')); }
  };
  return <div className="space-y-4"><div className="flex justify-end"><Link to={`/teacher/classes/${classId}/materials/new`}><TeacherButton tone="gold"><TeacherIcon name="plus" className="size-5" />{t('teacher.uploadMaterial')}</TeacherButton></Link></div>{error && <p role="alert" className="rounded-xl bg-danger-50 p-3 text-sm font-semibold text-danger-600">{error}</p>}<h2 className="text-xl font-extrabold text-[#16458e]">{t('teacher.materials')}</h2>{Object.entries(byWeek).sort(([a], [b]) => Number(a) - Number(b)).map(([week, items]) => <section key={week} className="space-y-3"><h3 className="text-lg font-extrabold text-[#5680bd]">{t('classes.week', { number: week })}</h3>{items.map((item) => item.materialType ? <ClassworkMaterialCard key={`${item.materialType}-${item.id}`} item={item} t={t} /> : <MaterialCard key={item.id} item={item} classId={classId} t={t} onDelete={removeMaterial} />)}</section>)}{!Object.keys(byWeek).length && <TeacherCard className="py-10 text-center"><TeacherIconTile name="book" className="mx-auto size-16" iconClassName="size-9" /><p className="mt-3 font-bold text-[#658abf]">{t('teacher.attachments')}</p></TeacherCard>}</div>;
};

const ClassworkMaterialCard = ({ item, t }) => {
  const [open, setOpen] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const [error, setError] = useState(null);
  const remove = async () => {
    if (!window.confirm(t('teacher.deleteAssignmentConfirm', { name: item.title }))) return;
    try {
      await deleteTeacherAssignment(item.id);
      setDeleted(true);
    } catch (cause) {
      setError(cause?.response?.data?.error?.message ?? t('errors.generic'));
    }
  };
  if (deleted) return null;
  return <div className="relative flex items-center gap-3 rounded-[1.35rem] bg-white p-4 shadow-sm ring-1 ring-[#dceafb]"><Link to={`/teacher/assignments/${item.id}`} className="flex min-w-0 flex-1 items-center gap-3"><TeacherIconTile name={item.materialType === 'quiz' ? 'check' : 'assignment'} tone={item.materialType === 'quiz' ? 'blue' : 'gold'} /><span className="min-w-0 flex-1"><strong className="block truncate text-base text-[#17488f]">{item.title}</strong><span className="block text-sm font-semibold text-[#80a4dc]">{item.materialType === 'quiz' ? t('teacher.quiz') : t('teacher.createAssignment')}{item.dueAt ? ` · ${new Date(item.dueAt).toLocaleDateString()}` : ''}</span></span><Chevron className="text-[#1555ad]" /></Link><div className="relative"><button type="button" aria-label={t('teacher.moreActions')} aria-expanded={open} onClick={() => setOpen((value) => !value)} className="grid size-10 place-items-center rounded-full text-[#1555ad] hover:bg-[#edf6ff]"><TeacherIcon name="more" className="size-6" /></button>{open && <div className="absolute right-0 top-11 z-20 min-w-48 rounded-2xl bg-white p-2 shadow-xl ring-1 ring-[#dceafb]"><Link to={`/teacher/assignments/${item.id}/edit`} onClick={() => setOpen(false)} className="block rounded-xl px-3 py-2 text-sm font-extrabold text-[#1555ad] hover:bg-[#edf6ff]">{t('teacher.editAssignment')}</Link><button type="button" onClick={() => { setOpen(false); remove(); }} className="block w-full rounded-xl px-3 py-2 text-left text-sm font-extrabold text-danger-600 hover:bg-danger-50">{t('teacher.deleteAssignment')}</button></div>}</div>{error && <p role="alert" className="absolute left-4 top-full z-10 mt-1 rounded-lg bg-danger-50 px-2 py-1 text-xs font-semibold text-danger-600">{error}</p>}</div>;
};

const MaterialCard = ({ item, classId, t, onDelete }) => {
  const [open, setOpen] = useState(false);
  return <TeacherCard className="relative flex items-center gap-3"><a href={`${API_BASE_URL}/teacher/classes/${classId}/materials/${item.id}/file`} target="_blank" rel="noreferrer" className="flex min-w-0 flex-1 items-center gap-3 rounded-xl text-left" aria-label={`${t('teacher.viewMaterial')}: ${item.title}`}><TeacherIconTile name="document" tone={String(item.mimeType).includes('pdf') ? 'red' : 'gold'} /><span className="min-w-0 flex-1"><strong className="block truncate text-base text-[#17488f]">{item.title}</strong><span className="block text-sm font-semibold text-[#80a4dc]">{formatFile(item)}</span></span></a><div className="relative"><button type="button" aria-label={t('teacher.moreActions')} aria-expanded={open} onClick={() => setOpen((value) => !value)} className="grid size-10 place-items-center rounded-full text-[#1555ad] hover:bg-[#edf6ff]"><TeacherIcon name="more" className="size-6" /></button>{open && <div className="absolute right-0 top-11 z-10 min-w-36 rounded-2xl bg-white p-2 shadow-xl ring-1 ring-[#dceafb]"><a href={`${API_BASE_URL}/teacher/classes/${classId}/materials/${item.id}/file`} target="_blank" rel="noreferrer" onClick={() => setOpen(false)} className="block rounded-xl px-3 py-2 text-left text-sm font-bold text-[#1555ad] hover:bg-[#edf6ff]">{t('teacher.viewMaterial')}</a><button type="button" onClick={() => { setOpen(false); onDelete(item); }} className="block w-full rounded-xl px-3 py-2 text-left text-sm font-bold text-danger-600 hover:bg-danger-50">{t('teacher.deleteMaterial')}</button></div>}</div></TeacherCard>;
};

const Classwork = ({ t, classId, assignments }) => {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [deletedIds, setDeletedIds] = useState([]);
  const [openId, setOpenId] = useState(null);
  const [deleteError, setDeleteError] = useState(null);
  const visible = assignments.filter((item) => !deletedIds.includes(item.id) && item.title.toLowerCase().includes(query.trim().toLowerCase()));
  const byWeek = visible.reduce((groups, item) => {
    const week = Number(item.week ?? 1);
    groups[week] ??= [];
    groups[week].push(item);
    return groups;
  }, {});
  const remove = async (item) => {
    if (!window.confirm(t('teacher.deleteAssignmentConfirm', { name: item.title }))) return;
    try {
      await deleteTeacherAssignment(item.id);
      setDeletedIds((current) => [...current, item.id]);
    } catch (cause) {
      setDeleteError(cause?.response?.data?.error?.message ?? t('errors.generic'));
    }
  };
  return <div className="space-y-4"><div className="grid grid-cols-2 gap-3"><Link to={`/teacher/assignments/new?classId=${classId}`}><TeacherButton tone="gold" className="w-full px-2 text-sm"><TeacherIcon name="plus" className="size-5" />{t('teacher.createAssignment')}</TeacherButton></Link><Link to={`/teacher/quizzes/new?classId=${classId}`}><TeacherButton className="w-full px-2 text-sm"><TeacherIcon name="plus" className="size-5" />{t('teacher.createQuiz')}</TeacherButton></Link></div><SearchField value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('teacher.allClasswork')} />{deleteError && <p role="alert" className="rounded-xl bg-danger-50 p-3 text-sm font-semibold text-danger-600">{deleteError}</p>}<div className="space-y-5">{Object.entries(byWeek).sort(([a], [b]) => Number(a) - Number(b)).map(([week, items]) => <section key={week} className="space-y-3"><h2 className="text-xl font-extrabold text-[#16458e]">{t('classes.week', { number: week })}</h2>{items.map((item) => <div key={item.id} role="link" tabIndex={0} onClick={() => navigate(`/teacher/assignments/${item.id}`)} onKeyDown={(event) => { if (event.key === 'Enter') navigate(`/teacher/assignments/${item.id}`); }} className="relative flex cursor-pointer items-center gap-3 rounded-[1.4rem] bg-white p-4 shadow-sm ring-1 ring-[#dceafb]"><TeacherIconTile name={item.type === 'quiz' ? 'check' : 'document'} /><span className="min-w-0 flex-1"><strong className="block truncate text-lg text-[#17488f]">{item.title}</strong><span className="mt-1 block text-sm font-semibold text-[#80a4dc]">{item.type === 'quiz' ? t('teacher.quiz') : t('teacher.createAssignment')} · {t('teacher.points')}</span></span><StatusPill>{t('teacher.review')}</StatusPill><div className="relative"><button type="button" aria-label={t('teacher.moreActions')} aria-expanded={openId === item.id} onClick={(event) => { event.stopPropagation(); setOpenId((current) => current === item.id ? null : item.id); }} className="grid size-10 place-items-center rounded-full text-[#1555ad] hover:bg-[#edf6ff]"><TeacherIcon name="more" className="size-6" /></button>{openId === item.id && <div className="absolute right-0 top-11 z-20 min-w-48 rounded-2xl bg-white p-2 text-left shadow-xl ring-1 ring-[#dceafb]"><Link to={`/teacher/assignments/${item.id}/edit`} onClick={(event) => { event.stopPropagation(); setOpenId(null); }} className="block rounded-xl px-3 py-2 text-sm font-extrabold text-[#1555ad] hover:bg-[#edf6ff]">{t('teacher.editAssignment')}</Link><button type="button" onClick={(event) => { event.stopPropagation(); setOpenId(null); remove(item); }} className="block w-full rounded-xl px-3 py-2 text-left text-sm font-extrabold text-danger-600 hover:bg-danger-50">{t('teacher.deleteAssignment')}</button></div>}</div><Chevron className="text-[#1555ad]" /></div>)}</section>)}</div>{!visible.length && <TeacherCard className="py-10 text-center"><TeacherIconTile name="assignment" className="mx-auto size-16" iconClassName="size-9" /><p className="mt-3 font-bold text-[#658abf]">{t('teacher.noDueDate')}</p></TeacherCard>}<Link to={`/teacher/classes/${classId}`} className="sr-only">{t('teacher.classwork')}</Link></div>;
};

const People = ({ t, students, onScores }) => {
  const [query, setQuery] = useState('');
  const visible = useMemo(() => students.filter((student) => student.name.toLowerCase().includes(query.toLowerCase())), [query, students]);
  const average = students.length ? Math.round(students.reduce((sum, student) => sum + Number(student.averageScore || 0), 0) / students.length) : 0;
  return <div className="space-y-4"><button type="button" onClick={onScores} className="flex w-full items-center gap-3 rounded-[1.25rem] bg-[#e9f5ff] p-4 text-left text-[#0e5fbf] shadow-sm ring-1 ring-[#d6e9fb]"><TeacherIcon name="chart" className="size-7" /><strong className="flex-1 text-lg">{t('teacher.scoreDashboard')}</strong><Chevron /></button><TeacherCard className="grid grid-cols-2 gap-4"><span className="flex items-center gap-3"><TeacherIconTile name="people" /><span><strong className="block text-2xl text-[#17488f]">{students.length}</strong><span className="text-sm font-semibold text-[#7b9ed0]">{t('teacher.students')}</span></span></span><span className="flex items-center gap-3 border-l border-[#dceafb] pl-4"><TeacherIconTile name="chart" /><span><strong className="block text-2xl text-[#17488f]">{average}%</strong><span className="text-sm font-semibold text-[#7b9ed0]">{t('teacher.classAverage')}</span></span></span></TeacherCard><SearchField value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('teacher.searchStudents')} /><TeacherButton tone="gold" className="w-full"><TeacherIcon name="plus" className="size-5" />{t('teacher.addStudents')}</TeacherButton><div className="divide-y divide-[#e6effb] rounded-[1.45rem] bg-white px-4 shadow-sm ring-1 ring-[#dceafb]">{visible.map((student) => { const score = Math.round(Number(student.averageScore) || 0); const status = score < 70 ? 'gold' : 'green'; return <div key={student.id} className="flex items-center gap-3 py-3"><Avatar name={student.name} className="size-12" /><span className="min-w-0 flex-1"><strong className="block truncate text-base text-[#17488f]">{student.name}</strong><span className="mt-2 flex items-center gap-2"><Progress value={score} className="flex-1" /><strong className="text-sm text-[#1952a3]">{score}%</strong></span></span><StatusPill tone={status}>{score < 70 ? t('teacher.needsSupport') : t('teacher.active')}</StatusPill><Chevron className="text-[#1555ad]" /></div>; })}{!visible.length && <p className="py-8 text-center font-semibold text-[#7597ca]">{t('teacher.allStudents')}</p>}</div></div>;
};

const TeacherScores = ({ classId, klass, students }) => {
  const t = useT();
  const ordered = [...students].sort((a, b) => Number(b.averageScore) - Number(a.averageScore));
  const average = ordered.length ? Math.round(ordered.reduce((sum, item) => sum + Number(item.averageScore || 0), 0) / ordered.length) : 0;
  const high = ordered.filter((item) => Number(item.averageScore) >= 80).length;
  const middle = ordered.filter((item) => Number(item.averageScore) >= 60 && Number(item.averageScore) < 80).length;
  return <main className="teacher-page min-h-full pb-5"><TeacherHeader title={t('teacher.studentScores')} backTo={`/teacher/classes/${classId}?tab=people`} /><div className="space-y-4 px-5 pt-5"><div className="grid grid-cols-2 gap-3"><TeacherCard className="p-3"><span className="text-sm font-semibold text-[#80a4dc]">{t('teacher.classTitle')}</span><strong className="mt-1 block truncate text-base text-[#17488f]">{klass?.title}</strong></TeacherCard><TeacherCard className="p-3"><span className="text-sm font-semibold text-[#80a4dc]">{t('teacher.period')}</span><strong className="mt-1 block text-base text-[#17488f]">{t('teacher.allTime')}</strong></TeacherCard></div><TeacherCard><div className="flex items-center gap-3"><TeacherIconTile name="chart" /><h2 className="text-xl font-extrabold text-[#16458e]">{t('teacher.performance')}</h2></div><div className="mt-4 flex items-end gap-6"><span><strong className="block text-5xl text-[#16458e]">{average}%</strong><span className="font-semibold text-[#7b9ed0]">{t('teacher.averageScore')}</span></span><span className="mb-1 font-bold text-[#08a879]">↑ +6%</span></div><h3 className="mt-5 font-extrabold text-[#17488f]">{t('teacher.scoreDistribution')}</h3><div className="mt-3 flex h-5 overflow-hidden rounded-full bg-[#e9f3fc]"><span className="bg-[#0878f9]" style={{ width: `${ordered.length ? high / ordered.length * 100 : 0}%` }} /><span className="bg-[#ffb73f]" style={{ width: `${ordered.length ? middle / ordered.length * 100 : 0}%` }} /><span className="bg-[#a4c9f7]" style={{ width: `${ordered.length ? (ordered.length - high - middle) / ordered.length * 100 : 0}%` }} /></div><div className="mt-3 grid grid-cols-3 gap-2 text-sm font-bold text-[#3769b1]"><span>{t('teacher.above80')}<em className="mt-1 block not-italic text-[#82a5d8]">{high} {t('teacher.students')}</em></span><span>{t('teacher.between60and79')}<em className="mt-1 block not-italic text-[#82a5d8]">{middle} {t('teacher.students')}</em></span><span>{t('teacher.below60')}<em className="mt-1 block not-italic text-[#82a5d8]">{ordered.length - high - middle} {t('teacher.students')}</em></span></div></TeacherCard><TeacherCard><h2 className="text-xl font-extrabold text-[#16458e]">{t('teacher.studentLeaderboard')}</h2>{ordered.slice(0, 5).map((student, index) => <div key={student.id} className="mt-4 flex items-center gap-3"><span className="grid size-7 place-items-center rounded-full bg-[#e7f2ff] text-sm font-extrabold text-[#1855a8]">{index + 1}</span><Avatar name={student.name} className="size-10" /><strong className="min-w-0 flex-1 truncate text-[#17488f]">{student.name}</strong><Progress value={student.averageScore} className="w-24" /><strong className="text-[#17488f]">{Math.round(student.averageScore)}%</strong></div>)}</TeacherCard></div></main>;
};

const ManageSheet = ({ t, classId, klass, onClose, onDeleted }) => <div className="fixed inset-0 z-40 flex items-end justify-center"><button type="button" aria-label={t('common.cancel')} onClick={onClose} className="absolute inset-0 bg-[#06265b]/55" /><section role="dialog" aria-modal="true" aria-label={t('teacher.manageTitle')} className="relative w-full max-w-[26rem] rounded-t-[2rem] bg-white px-5 pb-8 pt-4 shadow-2xl"><span className="mx-auto block h-1.5 w-12 rounded-full bg-[#c4d8ef]" /><div className="mt-5 flex items-center justify-between"><h2 className="text-3xl font-extrabold text-[#16458e]">{t('teacher.manageTitle')}</h2><button type="button" onClick={onClose} aria-label={t('common.close')}><TeacherIcon name="close" className="size-7 text-[#1457ac]" /></button></div><div className="mt-5 divide-y divide-[#e1eefb]">{[["edit", 'teacher.editClass', 'teacher.editClassHint', 'blue'], ['people', 'teacher.inviteStudents', 'teacher.inviteStudentsHint', 'blue'], ['settings', 'teacher.classSettings', 'teacher.classSettingsHint', 'blue']].map(([icon, title, hint, tone]) => <button type="button" key={title} className="flex w-full items-center gap-3 py-4 text-left"><TeacherIconTile name={icon} tone={tone} /><span className="min-w-0 flex-1"><strong className="block text-lg text-[#17488f]">{t(title)}</strong><span className="block text-base text-[#7398ce]">{title === 'teacher.inviteStudentsHint' ? t(hint, { code: klass?.joinCode ?? '—' }) : t(hint)}</span></span><Chevron className="text-[#1555ad]" /></button>)}<button type="button" onClick={async () => { if (!window.confirm(t('teacher.deleteClassConfirm', { name: klass?.title ?? '' }))) return; try { await deleteTeacherClass(classId); onDeleted(); } catch (cause) { window.alert(cause?.response?.data?.error?.message ?? t('errors.generic')); } }} className="flex w-full items-center gap-3 py-4 text-left"><TeacherIconTile name="trash" tone="red" /><span className="min-w-0 flex-1"><strong className="block text-lg text-[#d43b51]">{t('teacher.deleteClass')}</strong><span className="block text-base text-[#e87888]">{t('teacher.deleteClassHint')}</span></span><Chevron className="text-[#d43b51]" /></button></div><button type="button" onClick={onClose} className="mt-3 w-full py-3 text-lg font-extrabold text-[#0760c9]">{t('common.cancel')}</button></section></div>;

const formatFile = (item) => {
  const type = item.mimeType?.includes('pdf') ? 'PDF' : item.mimeType?.includes('presentation') ? 'PPTX' : item.mimeType?.includes('word') ? 'DOCX' : item.mimeType?.split('/').pop()?.toUpperCase() ?? 'FILE';
  const size = item.byteSize ? `${(item.byteSize / 1024 / 1024).toFixed(1)} MB` : '';
  return [type, size].filter(Boolean).join(' · ');
};
