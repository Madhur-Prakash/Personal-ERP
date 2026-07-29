import { Link, useNavigate, useSearch } from '@tanstack/react-router';
import { ArrowLeft, Check, Eye, EyeOff, Mail } from 'lucide-react';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { z } from 'zod';

import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { authApi } from '@/features/auth/api';
import { AuthLayout } from '@/features/auth/AuthLayout';
import {
  passwordPlaceholder,
  summarisePolicy,
  usePasswordPolicy,
} from '@/features/auth/passwordPolicy';
import { ApiError } from '@/lib/api';

// =============================================================================
// Forgot password
// =============================================================================
const forgotSchema = z.object({
  email: z.string().min(1, 'Email is required').email('Enter a valid email address'),
});

export function ForgotPasswordPage() {
  const [sent, setSent] = useState(false);
  const {
    register,
    handleSubmit,
    getValues,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<z.infer<typeof forgotSchema>>({ defaultValues: { email: '' } });

  async function onSubmit(values: z.infer<typeof forgotSchema>) {
    const parsed = forgotSchema.safeParse(values);
    if (!parsed.success) {
      setError('email', { message: parsed.error.issues[0]?.message });
      return;
    }

    try {
      await authApi.forgotPassword(parsed.data.email);
    } catch {
      // Swallowed deliberately. The server responds identically whether or not
      // the account exists, and surfacing a transport error differently here
      // would reintroduce the enumeration signal the API works to avoid.
    }
    // Always show the same confirmation, for the same reason.
    setSent(true);
  }

  if (sent) {
    return (
      <AuthLayout
        title="Check your email"
        subtitle={
          <>
            If an account exists for <strong className="text-content">{getValues('email')}</strong>,
            we have sent a link to reset the password.
          </>
        }
        footer={
          <Link to="/login" className="text-primary font-medium hover:underline">
            Back to sign in
          </Link>
        }
      >
        <div className="space-y-4 text-center">
          <div
            className="bg-info-bg text-info mx-auto flex h-12 w-12 items-center justify-center rounded-xl"
            aria-hidden
          >
            <Mail className="h-6 w-6" />
          </div>
          <p className="text-content-muted text-[13px] leading-relaxed">
            The link expires in 30 minutes and can be used once.
          </p>
        </div>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Reset your password"
      subtitle="Enter your email and we will send you a reset link."
      footer={
        <Link
          to="/login"
          className="text-content-muted hover:text-primary inline-flex items-center gap-1"
        >
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
          Back to sign in
        </Link>
      }
    >
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <Input
          label="Email"
          type="email"
          autoComplete="email"
          autoFocus
          placeholder="you@company.com"
          leftIcon={<Mail />}
          error={errors.email?.message}
          {...register('email')}
        />
        <Button type="submit" fullWidth size="lg" loading={isSubmitting}>
          Send reset link
        </Button>
      </form>
    </AuthLayout>
  );
}

// =============================================================================
// Reset password
// =============================================================================
const resetSchema = z
  .object({
    new_password: z.string().min(1, 'Password is required'),
    confirm_password: z.string().min(1, 'Confirm your password'),
  })
  .refine((data) => data.new_password === data.confirm_password, {
    message: 'Passwords do not match',
    path: ['confirm_password'],
  });

export function ResetPasswordPage() {
  const navigate = useNavigate();
  const search = useSearch({ strict: false });
  const [showPassword, setShowPassword] = useState(false);

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<z.infer<typeof resetSchema>>({
    defaultValues: { new_password: '', confirm_password: '' },
  });

  // Declared above the early return below — hooks must run unconditionally.
  const { data: policy } = usePasswordPolicy();

  // A missing token means the user landed here directly or the link was
  // truncated by a mail client. Say so, rather than failing on submit.
  if (!search.token) {
    return (
      <AuthLayout
        title="Invalid reset link"
        subtitle="This link is missing its token. Request a new one."
        footer={
          <Link to="/forgot-password" className="text-primary font-medium hover:underline">
            Request a new link
          </Link>
        }
      >
        <p className="text-content-muted text-center text-[13px]">
          Reset links expire after 30 minutes and can only be used once.
        </p>
      </AuthLayout>
    );
  }

  async function onSubmit(values: z.infer<typeof resetSchema>) {
    const parsed = resetSchema.safeParse(values);
    if (!parsed.success) {
      for (const issue of parsed.error.issues) {
        setError(issue.path[0] as 'new_password' | 'confirm_password', { message: issue.message });
      }
      return;
    }

    try {
      await authApi.resetPassword({
        token: search.token!,
        new_password: parsed.data.new_password,
      });
      toast.success('Password updated', {
        description: 'All other sessions were signed out.',
      });
      void navigate({ to: '/login', replace: true });
    } catch (error) {
      if (error instanceof ApiError) {
        const fieldErrors = error.fieldErrors;
        if (fieldErrors['password']) {
          setError('new_password', { message: fieldErrors['password'] });
          return;
        }
        setError('new_password', { message: error.message });
        return;
      }
      toast.error('Could not reset your password. Please try again.');
    }
  }

  return (
    <AuthLayout title="Choose a new password" subtitle="Make it long and hard to guess.">
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <Input
          label="New password"
          type={showPassword ? 'text' : 'password'}
          autoComplete="new-password"
          autoFocus
          placeholder={passwordPlaceholder(policy)}
          hint={errors.new_password ? undefined : summarisePolicy(policy)}
          error={errors.new_password?.message}
          rightSlot={
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={() => setShowPassword((value) => !value)}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              tabIndex={-1}
            >
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </Button>
          }
          {...register('new_password')}
        />

        <Input
          label="Confirm new password"
          type={showPassword ? 'text' : 'password'}
          autoComplete="new-password"
          placeholder="Re-enter your password"
          error={errors.confirm_password?.message}
          {...register('confirm_password')}
        />

        <Button type="submit" fullWidth size="lg" loading={isSubmitting}>
          Update password
        </Button>
      </form>
    </AuthLayout>
  );
}

// =============================================================================
// Verify email
// =============================================================================
export function VerifyEmailPage() {
  const navigate = useNavigate();
  const search = useSearch({ strict: false });
  const [state, setState] = useState<'idle' | 'verifying' | 'done' | 'failed'>('idle');
  const [message, setMessage] = useState('');

  // Verification is confirmed by an explicit click, not automatically on mount.
  //
  // The token is single-use, and mail clients and link scanners routinely
  // prefetch URLs — an auto-verify would be consumed before the user ever sees
  // the page, leaving them with a dead link.
  async function verify() {
    if (!search.token) return;
    setState('verifying');
    try {
      await authApi.verifyEmail(search.token);
      setState('done');
      toast.success('Email verified');
      setTimeout(() => void navigate({ to: '/login', replace: true }), 1500);
    } catch (error) {
      setState('failed');
      setMessage(
        error instanceof ApiError ? error.message : 'This link is invalid or has expired.',
      );
    }
  }

  if (!search.token) {
    return (
      <AuthLayout
        title="Invalid verification link"
        subtitle="This link is missing its token."
        footer={
          <Link to="/login" className="text-primary font-medium hover:underline">
            Back to sign in
          </Link>
        }
      >
        <p className="text-content-muted text-center text-[13px]">
          Sign in and request a new verification email.
        </p>
      </AuthLayout>
    );
  }

  if (state === 'done') {
    return (
      <AuthLayout title="Email verified" subtitle="Taking you to sign in…">
        <div
          className="bg-success-bg text-success mx-auto flex h-12 w-12 items-center justify-center rounded-xl"
          aria-hidden
        >
          <Check className="h-6 w-6" />
        </div>
      </AuthLayout>
    );
  }

  if (state === 'failed') {
    return (
      <AuthLayout
        title="Verification failed"
        subtitle={message}
        footer={
          <Link to="/login" className="text-primary font-medium hover:underline">
            Back to sign in
          </Link>
        }
      >
        <p className="text-content-muted text-center text-[13px]">
          Verification links expire after 24 hours. Sign in to request a new one.
        </p>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title="Verify your email" subtitle="Confirm this address to activate your account.">
      <Button fullWidth size="lg" loading={state === 'verifying'} onClick={() => void verify()}>
        Verify my email address
      </Button>
    </AuthLayout>
  );
}
