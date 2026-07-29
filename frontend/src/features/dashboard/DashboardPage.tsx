import { useQuery } from '@tanstack/react-query';
import {
  ArrowDownRight,
  ArrowUpRight,
  Building2,
  FileText,
  Plus,
  Sparkles,
  TrendingUp,
  Users,
  Wallet,
} from 'lucide-react';
import type { ReactNode } from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { PageHeader } from '@/components/layout/AppShell';
import { Badge } from '@/components/ui/Badge';
import { Button, buttonClasses } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { Skeleton } from '@/components/ui/Skeleton';
import { useAuth } from '@/features/auth/AuthProvider';
import { organizationsApi } from '@/features/organizations/api';
import { cn } from '@/lib/cn';
import { formatCurrency, formatCompact, formatRelative } from '@/lib/format';
import { Link } from '@tanstack/react-router';

/**
 * The dashboard.
 *
 * An explicit note on the financial figures: **the revenue, expense, and profit
 * tiles and the chart are illustrative placeholders.** There is no ledger yet —
 * double-entry bookkeeping is Stage 2 — so there is nothing real to aggregate.
 * They are labelled "Sample" in the UI rather than shown as real numbers,
 * because an unlabelled fake figure in an accounting product is the single most
 * damaging thing this page could do.
 *
 * Everything not labelled Sample is live: member counts, the organization list,
 * and the activity feed all come from the API.
 */

// Shaped like a plausible small-business revenue curve so the chart's design can be
// evaluated. Replaced by a real query in Stage 2.
const SAMPLE_SERIES = [
  { month: 'Apr', revenue: 420000, expenses: 310000 },
  { month: 'May', revenue: 468000, expenses: 322000 },
  { month: 'Jun', revenue: 512000, expenses: 356000 },
  { month: 'Jul', revenue: 489000, expenses: 341000 },
  { month: 'Aug', revenue: 574000, expenses: 372000 },
  { month: 'Sep', revenue: 638000, expenses: 395000 },
];

export function DashboardPage() {
  const { user, can } = useAuth();

  const { data: organizations, isLoading: orgsLoading } = useQuery({
    queryKey: ['organizations'],
    queryFn: organizationsApi.list,
  });

  const { data: members } = useQuery({
    queryKey: ['members'],
    queryFn: organizationsApi.listMembers,
    enabled: can('member:read') && Boolean(user?.active_organization),
  });

  const { data: auditPage } = useQuery({
    queryKey: ['audit', { limit: 6 }],
    queryFn: () => organizationsApi.listAudit({ limit: 6 }),
    enabled: can('audit:read') && Boolean(user?.active_organization),
  });

  const firstName = user?.full_name.split(' ')[0] ?? 'there';

  // No organization yet: onboarding, not a dashboard.
  if (!user?.active_organization) {
    return (
      <div className="p-6 lg:p-8">
        <PageHeader title={`Welcome, ${firstName}`} />
        <Card>
          <EmptyState
            icon={Building2}
            title="Create your organization"
            description="An organization holds your books, your team, and your data. Create one to get started, or ask a colleague to invite you to theirs."
            action={
              <Link to="/settings" className={buttonClasses('primary', 'md')}>
                <Plus className="mr-2 h-4 w-4" aria-hidden />
                Create organization
              </Link>
            }
          />
        </Card>
      </div>
    );
  }

  return (
    <div className="p-6 lg:p-8">
      <PageHeader
        title={`Good ${greeting()}, ${firstName}`}
        description={`Here is what is happening at ${user.active_organization.name}.`}
        action={
          <Button variant="secondary" leftIcon={<Sparkles className="h-4 w-4" />} disabled>
            Ask AI
          </Button>
        }
      />

      {/* ---- KPI tiles ---- */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Revenue"
          value={formatCurrency(638000)}
          delta={11.2}
          icon={TrendingUp}
          sample
        />
        <StatCard
          label="Expenses"
          value={formatCurrency(395000)}
          delta={5.8}
          deltaGood={false}
          icon={Wallet}
          sample
        />
        <StatCard
          label="Net profit"
          value={formatCurrency(243000)}
          delta={19.4}
          icon={TrendingUp}
          sample
        />
        <StatCard
          label="Team members"
          value={members ? String(members.length) : undefined}
          icon={Users}
          hint={members ? `${members.filter((m) => m.status === 'active').length} active` : ''}
        />
      </div>

      {/* ---- Chart + activity ---- */}
      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader
            title="Revenue and expenses"
            description="Last six months"
            action={
              <Badge tone="warning" title="Illustrative data until Stage 2 ships the ledger">
                Sample data
              </Badge>
            }
          />
          <CardBody>
            <div className="h-[280px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={SAMPLE_SERIES} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
                  <defs>
                    <linearGradient id="revenueFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="var(--primary)" stopOpacity={0.28} />
                      <stop offset="100%" stopColor="var(--primary)" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="expenseFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="var(--warning)" stopOpacity={0.2} />
                      <stop offset="100%" stopColor="var(--warning)" stopOpacity={0} />
                    </linearGradient>
                  </defs>

                  {/* Horizontal rules only: vertical grid lines add clutter
                      without helping anyone read a value off a time axis. */}
                  <CartesianGrid stroke="var(--border)" vertical={false} />
                  <XAxis
                    dataKey="month"
                    stroke="var(--content-muted)"
                    fontSize={11}
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis
                    stroke="var(--content-muted)"
                    fontSize={11}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(value: number) => formatCompact(value)}
                  />
                  <Tooltip
                    contentStyle={{
                      background: 'var(--surface-raised)',
                      border: '1px solid var(--border)',
                      borderRadius: 'var(--radius-lg)',
                      fontSize: 12,
                      boxShadow: 'var(--shadow-lg)',
                    }}
                    labelStyle={{ color: 'var(--content)', fontWeight: 600 }}
                    // Recharts types the value as a broad `ValueType`, so it is
                    // narrowed here rather than asserted.
                    formatter={(value, name) => [
                      typeof value === 'number' ? formatCurrency(value) : String(value ?? ''),
                      name === 'revenue' ? 'Revenue' : 'Expenses',
                    ]}
                  />
                  <Area
                    type="monotone"
                    dataKey="revenue"
                    stroke="var(--primary)"
                    strokeWidth={2}
                    fill="url(#revenueFill)"
                  />
                  <Area
                    type="monotone"
                    dataKey="expenses"
                    stroke="var(--warning)"
                    strokeWidth={2}
                    fill="url(#expenseFill)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Recent activity"
            description="From the audit trail"
            action={
              can('audit:read') ? (
                <Link to="/audit" className="text-primary text-[13px] hover:underline">
                  View all
                </Link>
              ) : undefined
            }
          />
          <CardBody>
            {!can('audit:read') ? (
              <p className="text-content-muted py-8 text-center text-[13px]">
                You do not have permission to view the audit trail.
              </p>
            ) : auditPage === undefined ? (
              <div className="space-y-3">
                {Array.from({ length: 5 }).map((_, index) => (
                  <div key={index} className="flex items-start gap-3">
                    <Skeleton className="h-7 w-7 rounded-full" />
                    <div className="flex-1 space-y-1.5">
                      <Skeleton className="h-3 w-full" />
                      <Skeleton className="h-2.5 w-20" />
                    </div>
                  </div>
                ))}
              </div>
            ) : auditPage.items.length === 0 ? (
              <EmptyState
                icon={FileText}
                title="Nothing yet"
                description="Actions across your organization will appear here."
                className="py-8"
              />
            ) : (
              <ul className="space-y-3.5">
                {auditPage.items.map((entry) => (
                  <li key={entry.id} className="flex items-start gap-3">
                    <span
                      className={cn(
                        'mt-1 h-1.5 w-1.5 shrink-0 rounded-full',
                        entry.severity === 'critical'
                          ? 'bg-danger'
                          : entry.severity === 'warning'
                            ? 'bg-warning'
                            : 'bg-success',
                      )}
                      aria-hidden
                    />
                    <div className="min-w-0 flex-1">
                      <p className="text-content text-[13px] leading-snug">
                        {entry.summary ?? entry.action}
                      </p>
                      <p className="text-content-muted mt-0.5 text-[11px]">
                        {entry.actor.name ?? entry.actor.email ?? 'System'} ·{' '}
                        {formatRelative(entry.created_at)}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>
      </div>

      {/* ---- Organizations ---- */}
      {organizations && organizations.length > 1 && (
        <Card className="mt-4">
          <CardHeader title="Your organizations" description="Switch with ⌘K" />
          <CardBody>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {organizations.map((organization) => (
                <div
                  key={organization.id}
                  className="border-border bg-surface-sunken/40 flex items-center gap-3 rounded-lg border p-3"
                >
                  <span
                    className="bg-primary/12 text-primary flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-[11px] font-bold"
                    aria-hidden
                  >
                    {organization.name.slice(0, 2).toUpperCase()}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-content truncate text-[13px] font-medium">
                      {organization.name}
                    </p>
                    <p className="text-content-muted text-[11px]">
                      {organization.role_name} · {organization.member_count} member
                      {organization.member_count === 1 ? '' : 's'}
                    </p>
                  </div>
                  {organization.id === user.active_organization?.id && (
                    <Badge tone="primary">Current</Badge>
                  )}
                </div>
              ))}
            </div>
          </CardBody>
        </Card>
      )}

      {orgsLoading && <Skeleton className="mt-4 h-28 rounded-xl" />}
    </div>
  );
}

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return 'morning';
  if (hour < 17) return 'afternoon';
  return 'evening';
}

function StatCard({
  label,
  value,
  delta,
  deltaGood = true,
  icon: Icon,
  hint,
  sample,
}: {
  label: string;
  value: string | undefined;
  delta?: number;
  /** Whether a rising value is good. Expenses going up is not. */
  deltaGood?: boolean;
  icon: typeof TrendingUp;
  hint?: string;
  /** Marks the figure as illustrative. */
  sample?: boolean;
}) {
  const positive = (delta ?? 0) >= 0;
  const good = positive === deltaGood;

  return (
    <Card className="p-4">
      <div className="flex items-start justify-between">
        <span className="text-content-muted text-[12px] font-medium">{label}</span>
        <Icon className="text-content-muted h-4 w-4" aria-hidden />
      </div>

      <div className="mt-2 flex items-baseline gap-2">
        {value === undefined ? (
          <Skeleton className="h-7 w-24" />
        ) : (
          <span className="text-content text-[24px] leading-none font-semibold tracking-[-0.02em]">
            {value}
          </span>
        )}
      </div>

      <div className="mt-2 flex items-center gap-2">
        {delta !== undefined && (
          <span
            className={cn(
              'inline-flex items-center gap-0.5 text-[12px] font-medium',
              good ? 'text-success' : 'text-danger',
            )}
          >
            {positive ? (
              <ArrowUpRight className="h-3 w-3" aria-hidden />
            ) : (
              <ArrowDownRight className="h-3 w-3" aria-hidden />
            )}
            {Math.abs(delta).toFixed(1)}%
          </span>
        )}
        {hint && <span className="text-content-muted text-[12px]">{hint}</span>}
        {sample && (
          <Badge tone="warning" className="ml-auto text-[9px]">
            Sample
          </Badge>
        )}
      </div>
    </Card>
  );
}

/** Re-exported so route files can compose a heading without importing the shell. */
export type { ReactNode };
