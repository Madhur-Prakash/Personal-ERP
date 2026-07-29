import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Building2,
  Check,
  Copy,
  Laptop,
  Monitor,
  Moon,
  Shield,
  ShieldCheck,
  Smartphone,
  Sun,
  Trash2,
} from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/layout/AppShell';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Skeleton } from '@/components/ui/Skeleton';
import { authApi } from '@/features/auth/api';
import {
  passwordPlaceholder,
  summarisePolicy,
  usePasswordPolicy,
} from '@/features/auth/passwordPolicy';
import { useAuth } from '@/features/auth/AuthProvider';
import { organizationsApi, usersApi } from '@/features/organizations/api';
import { useTheme, type Theme } from '@/features/theme/ThemeProvider';
import { ApiError } from '@/lib/api';
import { cn } from '@/lib/cn';
import { formatRelative } from '@/lib/format';

export function SettingsPage() {
  const { user, refresh, can } = useAuth();

  return (
    <div className="p-6 lg:p-8">
      <PageHeader title="Settings" description="Your profile, security, and organization." />

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <ProfileCard />
          <TwoFactorCard />
          <PasswordCard />
          <SessionsCard />
          {can('organization:update') && user?.active_organization && <OrganizationCard />}
        </div>

        <div className="space-y-4">
          <AppearanceCard />
          <AccountCard onRefresh={refresh} />
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// Profile
// =============================================================================
function ProfileCard() {
  const { user, refresh } = useAuth();
  const [fullName, setFullName] = useState(user?.full_name ?? '');
  const [phone, setPhone] = useState('');

  const save = useMutation({
    mutationFn: () =>
      usersApi.updateProfile({
        full_name: fullName.trim(),
        ...(phone.trim() ? { phone: phone.trim() } : {}),
      }),
    onSuccess: async () => {
      toast.success('Profile updated');
      await refresh();
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not save your profile'),
  });

  return (
    <Card>
      <CardHeader title="Profile" description="How you appear across the organization." />
      <CardBody className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Full name"
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
          />
          <Input
            label="Phone"
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            placeholder="+91 98765 43210"
          />
        </div>

        <Input
          label="Email"
          value={user?.email ?? ''}
          disabled
          // Changing an email requires re-verification, which is its own flow -
          // Stage 9. Disabling with an explanation beats a field that silently
          // fails.
          hint="Email changes need re-verification and arrive in a later stage."
        />

        <div className="flex items-center gap-3">
          <Button loading={save.isPending} onClick={() => save.mutate()}>
            Save changes
          </Button>
          {user?.is_email_verified ? (
            <Badge tone="success" dot>
              Email verified
            </Badge>
          ) : (
            <Badge tone="warning" dot>
              Email not verified
            </Badge>
          )}
        </div>
      </CardBody>
    </Card>
  );
}

// =============================================================================
// Two-factor authentication
// =============================================================================
function TwoFactorCard() {
  const { user, refresh } = useAuth();
  const [setup, setSetup] = useState<{ secret: string; qr: string } | null>(null);
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const [error, setError] = useState<string>();

  const begin = useMutation({
    mutationFn: authApi.beginTwoFactorSetup,
    onSuccess: (data) => setSetup({ secret: data.secret, qr: data.qr_code }),
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : 'Could not start 2FA setup'),
  });

  const enable = useMutation({
    mutationFn: () => authApi.enableTwoFactor(code.trim()),
    onSuccess: async (data) => {
      setRecoveryCodes(data.recovery_codes);
      setSetup(null);
      setCode('');
      setError(undefined);
      toast.success('Two-factor authentication enabled');
      await refresh();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : 'That code did not work'),
  });

  const disable = useMutation({
    mutationFn: () => authApi.disableTwoFactor(password),
    onSuccess: async () => {
      toast.success('Two-factor authentication disabled');
      setPassword('');
      await refresh();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : 'Password is incorrect'),
  });

  // Recovery codes are returned exactly once. This screen is the only chance to
  // save them, so it blocks everything else until acknowledged.
  if (recoveryCodes) {
    return (
      <Card>
        <CardHeader
          title="Save your recovery codes"
          description="Each code works once. Store them somewhere safe - they are the only way in if you lose your authenticator."
        />
        <CardBody className="space-y-4">
          <div className="bg-surface-sunken border-border grid grid-cols-2 gap-2 rounded-lg border p-4 font-mono text-[13px] sm:grid-cols-5">
            {recoveryCodes.map((recoveryCode) => (
              <span key={recoveryCode} className="text-content">
                {recoveryCode}
              </span>
            ))}
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              variant="secondary"
              leftIcon={<Copy className="h-4 w-4" />}
              onClick={() => {
                void navigator.clipboard
                  .writeText(recoveryCodes.join('\n'))
                  .then(() => toast.success('Recovery codes copied'));
              }}
            >
              Copy all
            </Button>
            <Button onClick={() => setRecoveryCodes(null)}>I have saved them</Button>
          </div>
        </CardBody>
      </Card>
    );
  }

  if (setup) {
    return (
      <Card>
        <CardHeader
          title="Set up two-factor authentication"
          description="Scan the QR code with your authenticator app, then enter the code it shows."
        />
        <CardBody className="space-y-4">
          <div className="flex flex-wrap items-start gap-5">
            <img
              src={setup.qr}
              alt="Two-factor QR code"
              className="border-border h-40 w-40 rounded-lg border bg-white p-2"
            />
            <div className="min-w-[200px] flex-1 space-y-3">
              <div>
                <p className="text-content-secondary mb-1 text-[12px] font-medium">
                  Or enter this key manually
                </p>
                <code className="bg-surface-sunken text-content block rounded-md px-2.5 py-2 font-mono text-[12px] break-all">
                  {setup.secret}
                </code>
              </div>

              <Input
                label="Verification code"
                value={code}
                onChange={(event) => setCode(event.target.value.replace(/\D/g, ''))}
                error={error}
                inputMode="numeric"
                maxLength={6}
                placeholder="000000"
                className="font-mono tracking-[0.2em]"
              />

              <div className="flex gap-2">
                <Button
                  loading={enable.isPending}
                  disabled={code.length < 6}
                  onClick={() => enable.mutate()}
                >
                  Verify and enable
                </Button>
                <Button variant="ghost" onClick={() => setSetup(null)}>
                  Cancel
                </Button>
              </div>
            </div>
          </div>
        </CardBody>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader
        title="Two-factor authentication"
        description="Require a code from your phone in addition to your password."
        action={
          user?.is_two_factor_enabled ? (
            <Badge tone="success" dot>
              Enabled
            </Badge>
          ) : (
            <Badge tone="neutral" dot>
              Disabled
            </Badge>
          )
        }
      />
      <CardBody>
        {user?.is_two_factor_enabled ? (
          <div className="space-y-3">
            <p className="text-content-muted text-[13px]">
              Your account is protected. Disabling 2FA requires your password.
            </p>
            <div className="flex flex-wrap items-start gap-2">
              <div className="w-56">
                <Input
                  type="password"
                  placeholder="Confirm your password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  error={error}
                  autoComplete="current-password"
                  aria-label="Password"
                />
              </div>
              <Button
                variant="destructive"
                loading={disable.isPending}
                disabled={!password}
                onClick={() => disable.mutate()}
              >
                Disable 2FA
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex items-start gap-3">
            <div
              className="bg-primary/10 text-primary flex h-9 w-9 shrink-0 items-center justify-center rounded-lg"
              aria-hidden
            >
              <ShieldCheck className="h-4 w-4" />
            </div>
            <div className="flex-1">
              <p className="text-content-muted mb-3 text-[13px] leading-relaxed">
                Works with Google Authenticator, 1Password, Authy, and any other TOTP app.
              </p>
              <Button loading={begin.isPending} onClick={() => begin.mutate()}>
                Set up 2FA
              </Button>
            </div>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

// =============================================================================
// Password
// =============================================================================
function PasswordCard() {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [error, setError] = useState<string>();

  // Fetched, not hard-coded - the server owns the rules.
  const { data: policy } = usePasswordPolicy();

  const change = useMutation({
    mutationFn: () => authApi.changePassword({ current_password: current, new_password: next }),
    onSuccess: () => {
      toast.success('Password changed', {
        description: 'All sessions were signed out. Please sign in again.',
      });
      // No local cleanup needed: the server revoked every session including this
      // one, so the next request 401s and the auth provider signs us out.
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        setError(err.fieldErrors['password'] ?? err.message);
        return;
      }
      setError('Could not change your password');
    },
  });

  return (
    <Card>
      <CardHeader
        title="Password"
        description="Changing your password signs you out of every device."
      />
      <CardBody className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Current password"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(event) => setCurrent(event.target.value)}
          />
          <Input
            label="New password"
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(event) => setNext(event.target.value)}
            placeholder={passwordPlaceholder(policy)}
            error={error}
            hint={error ? undefined : summarisePolicy(policy)}
          />
        </div>
        <Button
          loading={change.isPending}
          disabled={!current || !next}
          onClick={() => {
            setError(undefined);
            change.mutate();
          }}
        >
          Change password
        </Button>
      </CardBody>
    </Card>
  );
}

// =============================================================================
// Sessions / device history
// =============================================================================
function SessionsCard() {
  const queryClient = useQueryClient();
  const { data: sessions, isLoading } = useQuery({
    queryKey: ['sessions'],
    queryFn: authApi.listSessions,
  });

  const revoke = useMutation({
    mutationFn: authApi.revokeSession,
    onSuccess: () => {
      toast.success('Session revoked');
      void queryClient.invalidateQueries({ queryKey: ['sessions'] });
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not revoke the session'),
  });

  return (
    <Card>
      <CardHeader
        title="Active sessions"
        description="Devices currently signed in to your account."
      />
      <CardBody className="p-0">
        {isLoading ? (
          <div className="space-y-3 p-5">
            {Array.from({ length: 2 }).map((_, index) => (
              <Skeleton key={index} className="h-12 rounded-md" />
            ))}
          </div>
        ) : (
          <ul className="divide-border divide-y">
            {(sessions ?? []).map((session) => {
              const Icon =
                session.device_type === 'mobile' || session.device_type === 'tablet'
                  ? Smartphone
                  : session.device_type === 'api'
                    ? Monitor
                    : Laptop;

              return (
                <li key={session.id} className="flex items-center gap-3 px-5 py-3.5">
                  <div
                    className="bg-surface-sunken text-content-muted flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
                    aria-hidden
                  >
                    <Icon className="h-4 w-4" />
                  </div>

                  <div className="min-w-0 flex-1">
                    <p className="text-content flex items-center gap-2 text-[13px] font-medium">
                      {session.device_label ?? 'Unknown device'}
                      {session.is_current && <Badge tone="primary">This device</Badge>}
                    </p>
                    <p className="text-content-muted text-[11px]">
                      {session.ip_address ?? 'unknown IP'} · via {session.login_method} ·{' '}
                      {session.last_used_at
                        ? `active ${formatRelative(session.last_used_at)}`
                        : `started ${formatRelative(session.created_at)}`}
                    </p>
                  </div>

                  {/* The current session is not offered - signing out is the
                      dedicated action for that, and revoking yourself here
                      would look like a bug. */}
                  {!session.is_current && (
                    <Button
                      variant="ghost"
                      size="icon"
                      title="Revoke this session"
                      aria-label={`Revoke session on ${session.device_label ?? 'unknown device'}`}
                      onClick={() => revoke.mutate(session.id)}
                    >
                      <Trash2 className="text-danger h-3.5 w-3.5" />
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}

// =============================================================================
// Organization
// =============================================================================
function OrganizationCard() {
  const queryClient = useQueryClient();
  const { data: organization, isLoading } = useQuery({
    queryKey: ['organization', 'current'],
    queryFn: organizationsApi.current,
  });

  const [name, setName] = useState('');
  const [gstin, setGstin] = useState('');
  const [error, setError] = useState<string>();

  const save = useMutation({
    mutationFn: () =>
      organizationsApi.update({
        ...(name.trim() ? { name: name.trim() } : {}),
        ...(gstin.trim() ? { gstin: gstin.trim() } : {}),
      }),
    onSuccess: () => {
      toast.success('Organization updated');
      setError(undefined);
      void queryClient.invalidateQueries({ queryKey: ['organization', 'current'] });
      void queryClient.invalidateQueries({ queryKey: ['organizations'] });
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        setError(err.fieldErrors['gstin'] ?? err.message);
        return;
      }
      setError('Could not save');
    },
  });

  if (isLoading) return <Skeleton className="h-56 rounded-xl" />;

  return (
    <Card>
      <CardHeader
        title="Organization"
        description={`${organization?.name ?? ''} · ${organization?.slug ?? ''}`}
        action={<Badge tone="neutral">{organization?.plan}</Badge>}
      />
      <CardBody className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Display name"
            defaultValue={organization?.name}
            onChange={(event) => setName(event.target.value)}
          />
          <Input
            label="GSTIN"
            defaultValue={organization?.gstin ?? ''}
            onChange={(event) => setGstin(event.target.value)}
            error={error}
            placeholder="29AABCU9603R1ZM"
            hint="15 characters. Validated on save."
          />
        </div>

        <div className="text-content-muted grid gap-3 text-[12px] sm:grid-cols-3">
          <div>
            <span className="block font-medium">Currency</span>
            {organization?.currency}
          </div>
          <div>
            <span className="block font-medium">Timezone</span>
            {organization?.timezone}
          </div>
          <div>
            <span className="block font-medium">Fiscal year starts</span>
            {new Date(2000, (organization?.fiscal_year_start_month ?? 4) - 1).toLocaleString('en', {
              month: 'long',
            })}
          </div>
        </div>

        <Button loading={save.isPending} onClick={() => save.mutate()}>
          Save organization
        </Button>
      </CardBody>
    </Card>
  );
}

// =============================================================================
// Appearance
// =============================================================================
function AppearanceCard() {
  const { theme, setTheme } = useTheme();

  const options: { value: Theme; label: string; icon: typeof Sun }[] = [
    { value: 'light', label: 'Light', icon: Sun },
    { value: 'dark', label: 'Dark', icon: Moon },
    { value: 'system', label: 'System', icon: Monitor },
  ];

  return (
    <Card>
      <CardHeader title="Appearance" description="Applies to this browser." />
      <CardBody>
        <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Colour theme">
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={theme === option.value}
              onClick={() => setTheme(option.value)}
              className={cn(
                'flex flex-col items-center gap-1.5 rounded-lg border px-2 py-3 text-[12px] font-medium transition-colors',
                theme === option.value
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-border text-content-secondary hover:bg-surface-hover',
              )}
            >
              <option.icon className="h-4 w-4" aria-hidden />
              {option.label}
              {theme === option.value && <Check className="h-3 w-3" aria-hidden />}
            </button>
          ))}
        </div>
      </CardBody>
    </Card>
  );
}

// =============================================================================
// Account summary
// =============================================================================
function AccountCard({ onRefresh }: { onRefresh: () => Promise<void> }) {
  const { user, signOut } = useAuth();
  const { data: stats } = useQuery({ queryKey: ['user-stats'], queryFn: usersApi.stats });

  return (
    <Card>
      <CardHeader title="Account" />
      <CardBody className="space-y-4">
        <dl className="space-y-2.5 text-[13px]">
          <Row label="Organizations" value={stats ? String(stats.organizations) : '-'} />
          <Row label="Active sessions" value={stats ? String(stats.active_sessions) : '-'} />
          {user?.is_two_factor_enabled && (
            <Row
              label="Recovery codes left"
              value={stats ? String(stats.recovery_codes_remaining) : '-'}
            />
          )}
          <Row
            label="Last sign-in"
            value={user?.last_login_at ? formatRelative(user.last_login_at) : '-'}
          />
        </dl>

        <div className="border-border space-y-2 border-t pt-4">
          <Button variant="secondary" fullWidth onClick={() => void onRefresh()}>
            Refresh permissions
          </Button>
          <Button
            variant="ghost"
            fullWidth
            leftIcon={<Shield className="h-4 w-4" />}
            onClick={() => {
              if (window.confirm('Sign out of every device?')) {
                void signOut(true);
              }
            }}
          >
            Sign out everywhere
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-content-muted">{label}</dt>
      <dd className="text-content font-medium">{value}</dd>
    </div>
  );
}

/** Used by the dashboard's onboarding path when the user has no organization. */
export function CreateOrganizationCard() {
  const { refresh } = useAuth();
  const [name, setName] = useState('');
  const [error, setError] = useState<string>();

  const create = useMutation({
    mutationFn: () => organizationsApi.create({ name: name.trim() }),
    onSuccess: async () => {
      toast.success('Organization created');
      await refresh();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : 'Could not create it'),
  });

  return (
    <Card>
      <CardHeader
        title="Create an organization"
        description="You will be its owner, with full access."
      />
      <CardBody className="space-y-4">
        <Input
          label="Company name"
          placeholder="Acme Trading Co"
          leftIcon={<Building2 />}
          value={name}
          onChange={(event) => setName(event.target.value)}
          error={error}
        />
        <Button loading={create.isPending} disabled={!name.trim()} onClick={() => create.mutate()}>
          Create organization
        </Button>
      </CardBody>
    </Card>
  );
}
