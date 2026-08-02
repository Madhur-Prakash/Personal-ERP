import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../../core/api_error.dart';
import '../../models/auth.dart';
import '../../state/data_providers.dart';
import '../../state/providers.dart';
import '../../theme/tokens.dart';
import '../../widgets/app_button.dart';
import '../../widgets/app_input.dart';
import '../../widgets/toast.dart';
import 'auth_layout.dart';
import 'password_policy.dart';

// =============================================================================
// Forgot password
// =============================================================================
class ForgotPasswordScreen extends ConsumerStatefulWidget {
  const ForgotPasswordScreen({super.key});

  @override
  ConsumerState<ForgotPasswordScreen> createState() =>
      _ForgotPasswordScreenState();
}

class _ForgotPasswordScreenState extends ConsumerState<ForgotPasswordScreen> {
  final TextEditingController _email = TextEditingController();
  bool _submitting = false;
  bool _sent = false;
  String? _error;

  @override
  void dispose() {
    _email.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final String email = _email.text.trim();
    if (email.isEmpty || !email.contains('@')) {
      setState(() => _error = 'Enter a valid email address');
      return;
    }

    setState(() {
      _error = null;
      _submitting = true;
    });

    try {
      await ref.read(authApiProvider).forgotPassword(email);
    } catch (_) {
      // Swallowed deliberately. The server responds identically whether or not the
      // account exists, and surfacing a transport error differently here would
      // reintroduce the enumeration signal the API works to avoid.
    } finally {
      // Always show the same confirmation, for the same reason.
      if (mounted) {
        setState(() {
          _submitting = false;
          _sent = true;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final AppTokens t = context.tokens;

    if (_sent) {
      return AuthLayout(
        title: 'Check your email',
        subtitle: Text.rich(
          TextSpan(
            children: <InlineSpan>[
              const TextSpan(text: 'If an account exists for '),
              TextSpan(
                text: _email.text.trim(),
                style: TextStyle(color: t.content, fontWeight: FontWeight.w600),
              ),
              const TextSpan(
                text: ', we have sent a link to reset the password.',
              ),
            ],
          ),
        ),
        footer: AuthFooterPrompt(
          prompt: '',
          actionLabel: 'Back to sign in',
          onAction: () => context.go('/login'),
        ),
        child: Column(
          spacing: 16,
          children: <Widget>[
            Container(
              width: 48,
              height: 48,
              decoration: BoxDecoration(
                color: t.infoBg,
                borderRadius: BorderRadius.circular(Radii.xl),
              ),
              alignment: Alignment.center,
              child: Icon(LucideIcons.mail, size: 24, color: t.info),
            ),
            Text(
              'The link expires in 30 minutes and can be used once.',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 13,
                color: t.contentMuted,
                height: 1.6,
              ),
            ),
          ],
        ),
      );
    }

    return AuthLayout(
      title: 'Reset your password',
      subtitle: const Text(
        'Enter your email and we will send you a reset link.',
      ),
      footer: const BackToSignIn(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        spacing: 16,
        children: <Widget>[
          AppInput(
            label: 'Email',
            controller: _email,
            placeholder: 'you@company.com',
            leftIcon: LucideIcons.mail,
            error: _error,
            autofocus: true,
            keyboardType: TextInputType.emailAddress,
            onSubmitted: (_) => _submit(),
          ),
          AppButton(
            onPressed: _submit,
            loading: _submitting,
            fullWidth: true,
            size: AppButtonSize.lg,
            label: 'Send reset link',
          ),
        ],
      ),
    );
  }
}

// =============================================================================
// Reset password
// =============================================================================
class ResetPasswordScreen extends ConsumerStatefulWidget {
  const ResetPasswordScreen({super.key, this.token});

  final String? token;

  @override
  ConsumerState<ResetPasswordScreen> createState() =>
      _ResetPasswordScreenState();
}

class _ResetPasswordScreenState extends ConsumerState<ResetPasswordScreen> {
  final TextEditingController _password = TextEditingController();
  final TextEditingController _confirm = TextEditingController();
  bool _showPassword = false;
  bool _submitting = false;
  String? _passwordError;
  String? _confirmError;

  @override
  void dispose() {
    _password.dispose();
    _confirm.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _passwordError = _password.text.isEmpty ? 'Password is required' : null;
      _confirmError = _confirm.text.isEmpty
          ? 'Confirm your password'
          : _confirm.text != _password.text
          ? 'Passwords do not match'
          : null;
    });
    if (_passwordError != null || _confirmError != null) return;

    setState(() => _submitting = true);
    try {
      await ref
          .read(authApiProvider)
          .resetPassword(token: widget.token!, newPassword: _password.text);
      if (!mounted) return;
      context.toastSuccess(
        'Password updated',
        description: 'All other sessions were signed out.',
      );
      context.go('/login');
    } catch (error) {
      if (!mounted) return;
      final ApiError apiError = ApiError.from(error);
      setState(
        () => _passwordError =
            apiError.fieldErrors['password'] ?? apiError.message,
      );
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final AppTokens t = context.tokens;
    final PasswordPolicy? policy = ref
        .watch(passwordPolicyProvider)
        .valueOrNull;

    // A missing token means the user landed here directly or the link was truncated by a
    // mail client. Say so, rather than failing on submit.
    if (widget.token == null || widget.token!.isEmpty) {
      return AuthLayout(
        title: 'Invalid reset link',
        subtitle: const Text(
          'This link is missing its token. Request a new one.',
        ),
        footer: AuthFooterPrompt(
          prompt: '',
          actionLabel: 'Request a new link',
          onAction: () => context.go('/forgot-password'),
        ),
        child: Text(
          'Reset links expire after 30 minutes and can only be used once.',
          textAlign: TextAlign.center,
          style: TextStyle(fontSize: 13, color: t.contentMuted),
        ),
      );
    }

    return AuthLayout(
      title: 'Choose a new password',
      subtitle: const Text('Make it long and hard to guess.'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        spacing: 16,
        children: <Widget>[
          AppInput(
            label: 'New password',
            controller: _password,
            placeholder: passwordPlaceholder(policy),
            obscureText: !_showPassword,
            error: _passwordError,
            hint: _passwordError == null ? summarisePolicy(policy) : null,
            autofocus: true,
            onChanged: (_) => setState(() {}),
            rightSlot: Padding(
              padding: const EdgeInsets.only(right: 4),
              child: AppIconButton(
                icon: _showPassword ? LucideIcons.eyeOff : LucideIcons.eye,
                tooltip: _showPassword ? 'Hide password' : 'Show password',
                size: 15,
                onPressed: () => setState(() => _showPassword = !_showPassword),
              ),
            ),
          ),
          AppInput(
            label: 'Confirm new password',
            controller: _confirm,
            placeholder: 'Re-enter your password',
            obscureText: !_showPassword,
            error: _confirmError,
            onSubmitted: (_) => _submit(),
          ),
          AppButton(
            onPressed: _submit,
            loading: _submitting,
            fullWidth: true,
            size: AppButtonSize.lg,
            label: 'Update password',
          ),
        ],
      ),
    );
  }
}

// =============================================================================
// Verify email
// =============================================================================
class VerifyEmailScreen extends ConsumerStatefulWidget {
  const VerifyEmailScreen({super.key, this.token});

  final String? token;

  @override
  ConsumerState<VerifyEmailScreen> createState() => _VerifyEmailScreenState();
}

class _VerifyEmailScreenState extends ConsumerState<VerifyEmailScreen> {
  _VerifyState _state = _VerifyState.idle;
  String _message = '';

  /// Verification is confirmed by an explicit press, not automatically on mount.
  ///
  /// The token is single-use, and mail clients and link scanners routinely prefetch URLs -
  /// an auto-verify would be consumed before the user ever saw the screen, leaving them
  /// with a dead link.
  Future<void> _verify() async {
    setState(() => _state = _VerifyState.verifying);
    try {
      await ref.read(authApiProvider).verifyEmail(widget.token!);
      if (!mounted) return;
      setState(() => _state = _VerifyState.done);
      context.toastSuccess('Email verified');
      await Future<void>.delayed(const Duration(milliseconds: 1500));
      if (mounted) context.go('/login');
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _state = _VerifyState.failed;
        _message = ApiError.from(error).message;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final AppTokens t = context.tokens;

    if (widget.token == null || widget.token!.isEmpty) {
      return AuthLayout(
        title: 'Invalid verification link',
        subtitle: const Text('This link is missing its token.'),
        footer: const BackToSignIn(),
        child: Text(
          'Sign in and request a new verification email.',
          textAlign: TextAlign.center,
          style: TextStyle(fontSize: 13, color: t.contentMuted),
        ),
      );
    }

    if (_state == _VerifyState.done) {
      return AuthLayout(
        title: 'Email verified',
        subtitle: const Text('Taking you to sign in…'),
        child: Container(
          width: 48,
          height: 48,
          decoration: BoxDecoration(
            color: t.successBg,
            borderRadius: BorderRadius.circular(Radii.xl),
          ),
          alignment: Alignment.center,
          child: Icon(LucideIcons.check, size: 24, color: t.success),
        ),
      );
    }

    if (_state == _VerifyState.failed) {
      return AuthLayout(
        title: 'Verification failed',
        subtitle: Text(_message),
        footer: const BackToSignIn(),
        child: Text(
          'Verification links expire after 24 hours. Sign in to request a new one.',
          textAlign: TextAlign.center,
          style: TextStyle(fontSize: 13, color: t.contentMuted),
        ),
      );
    }

    return AuthLayout(
      title: 'Verify your email',
      subtitle: const Text('Confirm this address to activate your account.'),
      child: AppButton(
        onPressed: _verify,
        loading: _state == _VerifyState.verifying,
        fullWidth: true,
        size: AppButtonSize.lg,
        label: 'Verify my email address',
      ),
    );
  }
}

enum _VerifyState { idle, verifying, done, failed }
