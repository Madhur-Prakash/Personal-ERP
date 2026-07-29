/**
 * The app footer.
 *
 * Deliberately quiet. A footer inside an application is not a marketing site's footer —
 * nobody comes here to browse — so it carries only what someone occasionally needs: what
 * they are running, whether their books balance, and the one legal line that matters for
 * an accounting product.
 *
 * **The reconciliation line is the reason this is worth having.** It is the only place in
 * the app that says "your books agree" on every screen rather than only when you visit
 * the analytics page. A control that is invisible until it fails offers no reassurance
 * while it holds.
 */
import { useQuery } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { AlertTriangle, ShieldCheck } from 'lucide-react';

import { analyticsApi } from '@/features/analytics/api';
import { useAuth } from '@/features/auth/AuthProvider';
import { env } from '@/lib/env';

export function Footer() {
  const { user, can } = useAuth();
  const hasOrg = Boolean(user?.active_organization);
  const canSeeMoney = can('report:read');

  const { data: checks } = useQuery({
    queryKey: ['analytics-control-checks'],
    queryFn: () => analyticsApi.controlChecks(),
    enabled: canSeeMoney && hasOrg,
    // Shared with the dashboard and analytics pages, so this costs no extra request.
    staleTime: 60_000,
  });

  return (
    <footer className="border-border text-content-muted mt-2 border-t px-6 py-5 text-[12px] lg:px-8">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <p>
          <span className="text-content-secondary font-medium">{env.appName}</span>
          <span className="mx-1.5" aria-hidden>
            ·
          </span>
          Self-hosted. Your data stays in your own database.
        </p>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          {checks &&
            (checks.all_agree ? (
              <span className="flex items-center gap-1.5">
                <ShieldCheck className="text-success h-3.5 w-3.5" aria-hidden />
                Books reconcile
              </span>
            ) : (
              // Linked, not just flagged: the point of surfacing a discrepancy everywhere
              // is that it is one click from the screen that explains it.
              <Link
                to="/analytics"
                className="text-danger flex items-center gap-1.5 font-medium hover:underline"
              >
                <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
                Books do not reconcile
              </Link>
            ))}

          <span>Money is stored as exact decimals, never rounded in transit</span>
        </div>
      </div>

      <p className="mt-3 max-w-3xl leading-relaxed">
        This software keeps a double-entry ledger and computes GST, but it is not a substitute for
        professional advice. Figures you file remain your responsibility — have them reviewed before
        submitting a return.
      </p>
    </footer>
  );
}
