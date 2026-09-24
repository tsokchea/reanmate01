import { useState } from 'react';

import { useAdmin } from '../../admin/AdminContext.jsx';
import { useAdminQuery } from '../../admin/useAdminApi.js';
import { BarChart, Card, ErrorBlock, LoadingBlock, PageHeader, Segmented, StatGrid, useFormat } from '../../admin/ui.jsx';
import { useT } from '../../i18n/index.js';

const RANGES = [
  { value: 'today', labelKey: 'admin.dashboard.range.today' },
  { value: '7d', labelKey: 'admin.dashboard.range.d7' },
  { value: '30d', labelKey: 'admin.dashboard.range.d30' },
  { value: '90d', labelKey: 'admin.dashboard.range.d90' },
];

const METRICS = ['aiTokens', 'uploads', 'assignments', 'flashcards', 'activeUsers'];

export const AdminDashboardPage = () => {
  const t = useT();
  const fmt = useFormat();
  const { can } = useAdmin();
  const { data, status, reload } = useAdminQuery('/admin/dashboard');

  return (
    <>
      <PageHeader title={t('admin.dashboard.title')} subtitle={t('admin.dashboard.subtitle')} />
      {status === 'loading' && <LoadingBlock />}
      {status === 'error' && <ErrorBlock onRetry={reload} />}
      {data && (
        <div className="space-y-6">
          {data.overview && (
            <Card title={t('admin.dashboard.overview')}>
              <StatGrid
                items={[
                  { label: t('admin.dashboard.totalUsers'), value: fmt.number(data.overview.totalUsers) },
                  { label: t('admin.dashboard.students'), value: fmt.number(data.overview.students) },
                  { label: t('admin.dashboard.teachers'), value: fmt.number(data.overview.teachers) },
                  { label: t('admin.dashboard.admins'), value: fmt.number(data.overview.admins) },
                  { label: t('admin.dashboard.activeUsers'), value: fmt.number(data.overview.activeUsers) },
                  { label: t('admin.dashboard.disabledUsers'), value: fmt.number(data.overview.disabledUsers), tone: data.overview.disabledUsers ? 'danger' : undefined },
                ]}
              />
            </Card>
          )}

          <div className="grid gap-6 xl:grid-cols-2">
            {data.aiUsage && (
              <Card title={t('admin.dashboard.aiUsage')}>
                <StatGrid
                  items={[
                    { label: t('admin.dashboard.tokensToday'), value: fmt.compact(data.aiUsage.tokensToday) },
                    { label: t('admin.dashboard.tokensMonth'), value: fmt.compact(data.aiUsage.tokensThisMonth) },
                    { label: t('admin.dashboard.tutorToday'), value: fmt.number(data.aiUsage.tutorMessagesToday) },
                    { label: t('admin.dashboard.uploadsToday'), value: fmt.number(data.aiUsage.uploadsToday) },
                    { label: t('admin.dashboard.processingNow'), value: fmt.number(data.aiUsage.processingNow) },
                  ]}
                />
              </Card>
            )}
            {data.activity && (
              <Card title={t('admin.dashboard.activity')}>
                <StatGrid
                  items={[
                    { label: t('admin.dashboard.newToday'), value: fmt.number(data.activity.newUsersToday) },
                    { label: t('admin.dashboard.newWeek'), value: fmt.number(data.activity.newUsersThisWeek) },
                    { label: t('admin.dashboard.activeToday'), value: fmt.number(data.activity.activeUsersToday) },
                  ]}
                />
              </Card>
            )}
          </div>

          {data.content && (
            <Card title={t('admin.dashboard.content')}>
              <StatGrid
                items={[
                  { label: t('admin.dashboard.pdfs'), value: fmt.number(data.content.pdfs) },
                  { label: t('admin.dashboard.files'), value: fmt.number(data.content.files) },
                  { label: t('admin.dashboard.assignments'), value: fmt.number(data.content.assignments) },
                  { label: t('admin.dashboard.flashcardSets'), value: fmt.number(data.content.flashcardSets) },
                  { label: t('admin.dashboard.courses'), value: fmt.number(data.content.courses) },
                ]}
              />
            </Card>
          )}

          {can('analytics.view', 'usage.view') && <UsageCharts />}
        </div>
      )}
    </>
  );
};

const UsageCharts = () => {
  const t = useT();
  const fmt = useFormat();
  const [range, setRange] = useState('7d');
  const [metric, setMetric] = useState('aiTokens');
  const { data, status, reload } = useAdminQuery('/admin/dashboard/series', { range });

  const hourly = data?.granularity === 'hour';
  const formatBucket = (iso) => {
    const date = new Date(iso);
    return fmt.digits(
      hourly ? `${String(date.getUTCHours()).padStart(2, '0')}:00` : `${date.getUTCDate()}/${date.getUTCMonth() + 1}`,
    );
  };
  const total = (data?.points ?? []).reduce((sum, point) => sum + (point[metric] ?? 0), 0);
  const metricLabel = t(`admin.dashboard.metric.${metric}`);

  return (
    <Card
      title={t('admin.dashboard.charts')}
      actions={
        <Segmented
          label={t('admin.dashboard.charts')}
          value={range}
          onChange={setRange}
          options={RANGES.map((option) => ({ value: option.value, label: t(option.labelKey) }))}
        />
      }
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <Segmented
          label={t('admin.dashboard.charts')}
          value={metric}
          onChange={setMetric}
          options={METRICS.map((key) => ({ value: key, label: t(`admin.dashboard.metric.${key}`) }))}
        />
        <p className="text-base font-semibold text-navy-900">
          {metric === 'activeUsers' ? metricLabel : t('admin.dashboard.chartTotal', { total: fmt.number(total) })}
        </p>
      </div>
      {status === 'loading' && <LoadingBlock />}
      {status === 'error' && <ErrorBlock onRetry={reload} />}
      {data && (
        <BarChart
          points={data.points}
          metric={metric}
          label={t('admin.dashboard.chartLabel', {
            metric: metricLabel,
            unit: t(hourly ? 'admin.dashboard.unitHour' : 'admin.dashboard.unitDay'),
          })}
          formatValue={fmt.number}
          formatBucket={formatBucket}
        />
      )}
    </Card>
  );
};
