import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { FileText, Filter } from 'lucide-react';
import { useState } from 'react';

import { PageHeader } from '@/components/layout/AppShell';
import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { Skeleton } from '@/components/ui/Skeleton';
import { organizationsApi } from '@/features/organizations/api';
import { formatDateTime, formatRelative } from '@/lib/format';
import type { AuditSeverity } from '@/types/api';

/**
 * Render an audit diff value for display.
 *
 * The values are `unknown` - a diff can hold a string, number, boolean, null, or
 * a nested JSONB object. Passing an object to `String()` yields
 * "[object Object]", which is worse than useless in an audit trail, so objects
 * are serialised instead.
 */
function renderDiffValue(value: unknown): string {
  if (value === null || value === undefined) return '-';
  if (typeof value === 'object') return JSON.stringify(value);
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return '-';
}

const SEVERITY_TONE: Record<AuditSeverity, BadgeTone> = {
  info: 'neutral',
  warning: 'warning',
  critical: 'danger',
};

export function AuditPage() {
  const [action, setAction] = useState('');
  const [severity, setSeverity] = useState('');

  const { data: actions } = useQuery({
    queryKey: ['audit-actions'],
    queryFn: organizationsApi.auditActions,
    staleTime: 60 * 60 * 1000,
  });

  /**
   * Cursor pagination via `useInfiniteQuery`.
   *
   * The trail is append-heavy: offsets both degrade with depth and shift rows
   * under the reader as new events land, so the API is cursor-based and the
   * client follows `next_cursor`.
   */
  const { data, isLoading, fetchNextPage, hasNextPage, isFetchingNextPage } = useInfiniteQuery({
    queryKey: ['audit', { action, severity }],
    queryFn: ({ pageParam }) =>
      organizationsApi.listAudit({
        limit: 25,
        ...(pageParam ? { cursor: pageParam } : {}),
        ...(action ? { action } : {}),
        ...(severity ? { severity } : {}),
      }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  });

  const entries = data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <div>
      <PageHeader
        title="Audit log"
        description="An append-only record of every action taken in this organization."
      />

      <Card className="mb-4">
        <CardBody className="flex flex-wrap items-center gap-3 py-4">
          <Filter className="text-content-muted h-4 w-4" aria-hidden />

          <select
            value={action}
            onChange={(event) => setAction(event.target.value)}
            aria-label="Filter by action"
            className="border-border bg-surface text-content h-8 rounded-md border px-2.5 text-[13px]"
          >
            <option value="">All actions</option>
            {(actions ?? []).map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>

          <select
            value={severity}
            onChange={(event) => setSeverity(event.target.value)}
            aria-label="Filter by severity"
            className="border-border bg-surface text-content h-8 rounded-md border px-2.5 text-[13px]"
          >
            <option value="">All severities</option>
            <option value="info">Info</option>
            <option value="warning">Warning</option>
            <option value="critical">Critical</option>
          </select>

          {(action || severity) && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setAction('');
                setSeverity('');
              }}
            >
              Clear filters
            </Button>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardBody className="p-0">
          {isLoading ? (
            <div className="space-y-3 p-5">
              {Array.from({ length: 8 }).map((_, index) => (
                <Skeleton key={index} className="h-10 rounded-md" />
              ))}
            </div>
          ) : entries.length === 0 ? (
            <EmptyState
              icon={FileText}
              title="No matching events"
              description={
                action || severity
                  ? 'Try widening your filters.'
                  : 'Actions across your organization will appear here as they happen.'
              }
            />
          ) : (
            <ul className="divide-border divide-y">
              {entries.map((entry) => (
                <li key={entry.id} className="hover:bg-surface-hover/40 px-5 py-3.5">
                  <div className="flex items-start gap-3">
                    <Badge tone={SEVERITY_TONE[entry.severity]} className="mt-0.5 shrink-0">
                      {entry.severity}
                    </Badge>

                    <div className="min-w-0 flex-1">
                      <p className="text-content text-[13px] leading-snug">
                        {entry.summary ?? entry.action}
                      </p>

                      <div className="text-content-muted mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11px]">
                        <code className="bg-surface-sunken rounded px-1.5 py-0.5">
                          {entry.action}
                        </code>
                        <span>{entry.actor.name ?? entry.actor.email ?? 'System'}</span>
                        {entry.ip_address && <span>{entry.ip_address}</span>}
                        <span title={formatDateTime(entry.created_at)}>
                          {formatRelative(entry.created_at)}
                        </span>
                      </div>

                      {/* The field-level diff. Shown inline because "what
                          changed" is usually the reason someone opened this. */}
                      {Object.keys(entry.changes).length > 0 && (
                        <dl className="border-border mt-2 space-y-1 border-l-2 pl-3">
                          {Object.entries(entry.changes).map(([field, change]) => (
                            <div key={field} className="flex flex-wrap gap-1.5 text-[11px]">
                              <dt className="text-content-secondary font-medium">{field}:</dt>
                              <dd className="text-content-muted">
                                <span className="line-through">
                                  {renderDiffValue(change.before)}
                                </span>
                                {' → '}
                                <span className="text-content">
                                  {renderDiffValue(change.after)}
                                </span>
                              </dd>
                            </div>
                          ))}
                        </dl>
                      )}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      {hasNextPage && (
        <div className="mt-4 flex justify-center">
          <Button
            variant="secondary"
            loading={isFetchingNextPage}
            onClick={() => void fetchNextPage()}
          >
            Load more
          </Button>
        </div>
      )}
    </div>
  );
}
