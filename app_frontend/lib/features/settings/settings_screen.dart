import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../../core/api_error.dart';
import '../../core/format.dart';
import '../../models/auth.dart';
import '../../models/organization.dart';
import '../../state/auth_controller.dart';
import '../../state/data_providers.dart';
import '../../state/providers.dart';
import '../../state/theme_controller.dart';
import '../../theme/app_theme.dart';
import '../../theme/oklch.dart';
import '../../theme/tokens.dart';
import '../../widgets/app_badge.dart';
import '../../widgets/app_button.dart';
import '../../widgets/app_card.dart';
import '../../widgets/app_input.dart';
import '../../widgets/app_modal.dart';
import '../../widgets/app_select.dart';
import '../../widgets/primitives.dart';
import '../../widgets/toast.dart';
import '../auth/password_policy.dart';

/// Settings - profile, security, organization, appearance.
class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AuthState auth = ref.watch(authControllerProvider);
    final bool canEditOrganization =
        auth.can('organization:update') && auth.organization != null;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        const PageHeader(
          title: 'Settings',
          description: 'Your profile, security, and organization.',
        ),
        LayoutBuilder(
          builder: (BuildContext context, BoxConstraints constraints) {
            final List<Widget> main = <Widget>[
              const _ProfileCard(),
              const _TwoFactorCard(),
              const _PasswordCard(),
              const _SessionsCard(),
              if (canEditOrganization) const _OrganizationCard(),
              if (auth.organization == null) const CreateOrganizationCard(),
            ];
            final List<Widget> side = <Widget>[
              const _AppearanceCard(),
              const _AccountCard(),
            ];

            if (constraints.maxWidth < 1180) {
              return Column(spacing: 16, children: <Widget>[...main, ...side]);
            }
            return Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              spacing: 16,
              children: <Widget>[
                Expanded(flex: 2, child: Column(spacing: 16, children: main)),
                Expanded(child: Column(spacing: 16, children: side)),
              ],
            );
          },
        ),
      ],
    );
  }
}

// =============================================================================
// Profile
// =============================================================================
class _ProfileCard extends ConsumerStatefulWidget {
  const _ProfileCard();

  @override
  ConsumerState<_ProfileCard> createState() => _ProfileCardState();
}

class _ProfileCardState extends ConsumerState<_ProfileCard> {
  final TextEditingController _name = TextEditingController();
  final TextEditingController _phone = TextEditingController();

  /// Whether the fields have been filled from the loaded profile yet.
  ///
  /// **The seeding has to happen when the profile arrives, not on the first build**, and
  /// that is the whole reason this flag exists. The web app initialised its state from the
  /// user object on mount - at which point the profile had not loaded, so the name field
  /// initialised to empty and stayed there. Saving then sent an empty name, which the API
  /// rejects for being under one character, so nothing saved and the reason was a generic
  /// toast away from the actual cause.
  bool _seeded = false;
  bool _saving = false;

  @override
  void dispose() {
    _name.dispose();
    _phone.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final UserProfile? profile = ref.watch(userProfileProvider).valueOrNull;

    if (!_seeded && profile != null) {
      _seeded = true;
      _name.text = profile.fullName;
      _phone.text = profile.phone ?? '';
    }

    final String name = _name.text;
    final String phone = _phone.text;

    // Blocked here rather than left to a 422. "Save changes" failing on a rule the form
    // never mentioned is the worst version of this: nothing happens and nothing explains why.
    final bool canSave = name.trim().isNotEmpty;

    Future<void> save() async {
      setState(() => _saving = true);
      try {
        await ref
            .read(usersApiProvider)
            .updateProfile(
              fullName: name.trim(),
              // Sent even when cleared, so a number can be removed rather than only changed.
              phone: phone.trim(),
            );
        ref.invalidate(userProfileProvider);
        // Both caches: this query holds the phone, and the session holds the name shown in
        // the sidebar and on every avatar.
        await ref.read(authControllerProvider.notifier).refresh();
        if (context.mounted) context.toastSuccess('Profile updated');
      } catch (error) {
        if (context.mounted) {
          context.toastApiError(error, 'Could not save your profile');
        }
      } finally {
        if (mounted) setState(() => _saving = false);
      }
    }

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const CardHeader(
            title: 'Profile',
            description: 'How you appear across the organization.',
          ),
          CardBody(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              spacing: 16,
              children: <Widget>[
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  spacing: 16,
                  children: <Widget>[
                    Expanded(
                      child: AppInput(
                        label: 'Full name',
                        required: true,
                        controller: _name,
                        error: canSave ? null : 'A name is required',
                        onChanged: (_) => setState(() {}),
                      ),
                    ),
                    Expanded(
                      child: AppInput(
                        label: 'Phone',
                        controller: _phone,
                        placeholder: '+91 98765 43210',
                      ),
                    ),
                  ],
                ),
                AppInput(
                  label: 'Email',
                  // Keyed on the value so the disabled field repaints when the profile
                  // lands, without a controller this card would have to own and dispose.
                  key: ValueKey<String>(profile?.email ?? ''),
                  initialValue: profile?.email ?? '',
                  enabled: false,
                  // Changing an email requires re-verification, which is its own flow.
                  // Disabling with an explanation beats a field that silently fails.
                  hint:
                      'Email changes need re-verification and arrive in a later stage.',
                ),
                Row(
                  spacing: 12,
                  children: <Widget>[
                    AppButton(
                      onPressed: canSave && !_saving ? save : null,
                      loading: _saving,
                      label: 'Save changes',
                    ),
                    if (profile != null)
                      AppBadge(
                        profile.isEmailVerified
                            ? 'Email verified'
                            : 'Email not verified',
                        tone: profile.isEmailVerified
                            ? BadgeTone.success
                            : BadgeTone.warning,
                        dot: true,
                      ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// =============================================================================
// Two-factor authentication
// =============================================================================
class _TwoFactorCard extends ConsumerStatefulWidget {
  const _TwoFactorCard();

  @override
  ConsumerState<_TwoFactorCard> createState() => _TwoFactorCardState();
}

class _TwoFactorCardState extends ConsumerState<_TwoFactorCard> {
  TwoFactorSetup? _setup;
  List<String>? _recoveryCodes;
  final TextEditingController _code = TextEditingController();
  final TextEditingController _password = TextEditingController();
  String? _error;
  bool _busy = false;

  @override
  void dispose() {
    _code.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _begin() async {
    setState(() => _busy = true);
    try {
      final TwoFactorSetup setup = await ref
          .read(authApiProvider)
          .beginTwoFactorSetup();
      if (mounted) setState(() => _setup = setup);
    } catch (error) {
      if (mounted) context.toastApiError(error, 'Could not start 2FA setup');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _enable() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final TwoFactorEnableResponse result = await ref
          .read(authApiProvider)
          .enableTwoFactor(_code.text.trim());
      await ref.read(authControllerProvider.notifier).refresh();
      ref.invalidate(userStatsProvider);
      if (!mounted) return;
      setState(() {
        _recoveryCodes = result.recoveryCodes;
        _setup = null;
        _code.clear();
      });
      context.toastSuccess('Two-factor authentication enabled');
    } catch (error) {
      if (mounted) {
        setState(() => _error = ApiError.from(error).message);
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _disable() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(authApiProvider).disableTwoFactor(_password.text);
      await ref.read(authControllerProvider.notifier).refresh();
      if (!mounted) return;
      _password.clear();
      context.toastSuccess('Two-factor authentication disabled');
    } catch (error) {
      if (mounted) setState(() => _error = ApiError.from(error).message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final AppTokens t = context.tokens;
    final AuthState auth = ref.watch(authControllerProvider);
    final bool enabled = auth.user?.isTwoFactorEnabled ?? false;

    // Recovery codes are returned exactly once. This view is the only chance to save them,
    // so it blocks everything else until acknowledged.
    if (_recoveryCodes != null) {
      return AppCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            const CardHeader(
              title: 'Save your recovery codes',
              description:
                  'Each code works once. Store them somewhere safe - they are the only way '
                  'in if you lose your authenticator.',
            ),
            CardBody(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                spacing: 16,
                children: <Widget>[
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: t.surfaceSunken,
                      borderRadius: BorderRadius.circular(Radii.lg),
                      border: Border.all(color: t.border),
                    ),
                    child: Wrap(
                      spacing: 24,
                      runSpacing: 8,
                      children: <Widget>[
                        for (final String code in _recoveryCodes!)
                          SelectableText(
                            code,
                            style: monoStyle(fontSize: 13, color: t.content),
                          ),
                      ],
                    ),
                  ),
                  Row(
                    spacing: 8,
                    children: <Widget>[
                      AppButton(
                        onPressed: () async {
                          await Clipboard.setData(
                            ClipboardData(text: _recoveryCodes!.join('\n')),
                          );
                          if (context.mounted) {
                            context.toastSuccess('Recovery codes copied');
                          }
                        },
                        variant: AppButtonVariant.secondary,
                        leftIcon: LucideIcons.copy,
                        label: 'Copy all',
                      ),
                      AppButton(
                        onPressed: () => setState(() => _recoveryCodes = null),
                        label: 'I have saved them',
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      );
    }

    if (_setup != null) {
      return AppCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            const CardHeader(
              title: 'Set up two-factor authentication',
              description:
                  'Scan the QR code with your authenticator app, then enter the code it '
                  'shows.',
            ),
            CardBody(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                spacing: 20,
                children: <Widget>[
                  _QrImage(dataUri: _setup!.qrCode),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      spacing: 12,
                      children: <Widget>[
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: <Widget>[
                            Text(
                              'Or enter this key manually',
                              style: TextStyle(
                                fontSize: 12,
                                fontWeight: FontWeight.w500,
                                color: t.contentSecondary,
                              ),
                            ),
                            const SizedBox(height: 4),
                            Container(
                              width: double.infinity,
                              padding: const EdgeInsets.symmetric(
                                horizontal: 10,
                                vertical: 8,
                              ),
                              decoration: BoxDecoration(
                                color: t.surfaceSunken,
                                borderRadius: BorderRadius.circular(Radii.sm),
                              ),
                              child: SelectableText(
                                _setup!.secret,
                                style: monoStyle(
                                  fontSize: 12,
                                  color: t.content,
                                ),
                              ),
                            ),
                          ],
                        ),
                        AppInput(
                          label: 'Verification code',
                          controller: _code,
                          placeholder: '000000',
                          error: _error,
                          maxLength: 6,
                          keyboardType: TextInputType.number,
                          textStyle: monoStyle(
                            fontSize: 14,
                          ).copyWith(letterSpacing: 3),
                          onChanged: (_) => setState(() {}),
                        ),
                        Row(
                          spacing: 8,
                          children: <Widget>[
                            AppButton(
                              onPressed: _code.text.trim().length < 6 || _busy
                                  ? null
                                  : _enable,
                              loading: _busy,
                              label: 'Verify and enable',
                            ),
                            AppButton(
                              onPressed: () => setState(() {
                                _setup = null;
                                _error = null;
                              }),
                              variant: AppButtonVariant.ghost,
                              label: 'Cancel',
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      );
    }

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          CardHeader(
            title: 'Two-factor authentication',
            description:
                'Require a code from your phone in addition to your password.',
            action: AppBadge(
              enabled ? 'Enabled' : 'Disabled',
              tone: enabled ? BadgeTone.success : BadgeTone.neutral,
              dot: true,
            ),
          ),
          CardBody(
            child: enabled
                ? Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    spacing: 12,
                    children: <Widget>[
                      Text(
                        'Your account is protected. Disabling 2FA requires your password.',
                        style: TextStyle(fontSize: 13, color: t.contentMuted),
                      ),
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        spacing: 8,
                        children: <Widget>[
                          AppInput(
                            controller: _password,
                            placeholder: 'Confirm your password',
                            obscureText: true,
                            error: _error,
                            width: 224,
                            onChanged: (_) => setState(() {}),
                          ),
                          AppButton(
                            onPressed: _password.text.isEmpty || _busy
                                ? null
                                : _disable,
                            loading: _busy,
                            variant: AppButtonVariant.destructive,
                            label: 'Disable 2FA',
                          ),
                        ],
                      ),
                    ],
                  )
                : Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    spacing: 12,
                    children: <Widget>[
                      Container(
                        width: 36,
                        height: 36,
                        decoration: BoxDecoration(
                          color: t.primary.at(0.10),
                          borderRadius: BorderRadius.circular(Radii.lg),
                        ),
                        alignment: Alignment.center,
                        child: Icon(
                          LucideIcons.shieldCheck,
                          size: 16,
                          color: t.primary,
                        ),
                      ),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          spacing: 12,
                          children: <Widget>[
                            Text(
                              'Works with Google Authenticator, 1Password, Authy, and any '
                              'other TOTP app.',
                              style: TextStyle(
                                fontSize: 13,
                                color: t.contentMuted,
                                height: 1.6,
                              ),
                            ),
                            AppButton(
                              onPressed: _busy ? null : _begin,
                              loading: _busy,
                              label: 'Set up 2FA',
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
          ),
        ],
      ),
    );
  }
}

/// The 2FA QR code, which arrives as a `data:image/png;base64,…` URI.
///
/// Inline in the response so the secret never becomes a fetchable URL - which means it has
/// to be decoded here rather than handed to a network image.
class _QrImage extends StatelessWidget {
  const _QrImage({required this.dataUri});

  final String dataUri;

  @override
  Widget build(BuildContext context) {
    final AppTokens t = context.tokens;
    final UriData? data = Uri.tryParse(dataUri)?.data;

    return Container(
      width: 160,
      height: 160,
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        // White regardless of theme: a QR code inverted on a dark surface will not scan.
        color: Colors.white,
        borderRadius: BorderRadius.circular(Radii.lg),
        border: Border.all(color: t.border),
      ),
      child: data == null
          ? const SizedBox.shrink()
          : Image.memory(data.contentAsBytes(), fit: BoxFit.contain),
    );
  }
}

// =============================================================================
// Password
// =============================================================================
class _PasswordCard extends ConsumerStatefulWidget {
  const _PasswordCard();

  @override
  ConsumerState<_PasswordCard> createState() => _PasswordCardState();
}

class _PasswordCardState extends ConsumerState<_PasswordCard> {
  final TextEditingController _current = TextEditingController();
  final TextEditingController _next = TextEditingController();
  String? _error;
  bool _busy = false;

  @override
  void dispose() {
    _current.dispose();
    _next.dispose();
    super.dispose();
  }

  Future<void> _change() async {
    setState(() {
      _error = null;
      _busy = true;
    });
    try {
      await ref
          .read(authApiProvider)
          .changePassword(
            currentPassword: _current.text,
            newPassword: _next.text,
          );
      if (!mounted) return;
      context.toastSuccess(
        'Password changed',
        description: 'All sessions were signed out. Please sign in again.',
      );
      // No local cleanup needed: the server revoked every session including this one, so
      // the next request 401s and the auth controller signs us out.
    } catch (error) {
      if (mounted) {
        final ApiError apiError = ApiError.from(error);
        setState(
          () => _error = apiError.fieldErrors['password'] ?? apiError.message,
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    // Fetched, not hard-coded - the server owns the rules.
    final PasswordPolicy? policy = ref
        .watch(passwordPolicyProvider)
        .valueOrNull;

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const CardHeader(
            title: 'Password',
            description:
                'Changing your password signs you out of every device.',
          ),
          CardBody(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              spacing: 16,
              children: <Widget>[
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  spacing: 16,
                  children: <Widget>[
                    Expanded(
                      child: AppInput(
                        label: 'Current password',
                        controller: _current,
                        obscureText: true,
                        onChanged: (_) => setState(() {}),
                      ),
                    ),
                    Expanded(
                      child: AppInput(
                        label: 'New password',
                        controller: _next,
                        obscureText: true,
                        placeholder: passwordPlaceholder(policy),
                        error: _error,
                        hint: _error == null ? summarisePolicy(policy) : null,
                        onChanged: (_) => setState(() {}),
                      ),
                    ),
                  ],
                ),
                AppButton(
                  onPressed:
                      _current.text.isEmpty || _next.text.isEmpty || _busy
                      ? null
                      : _change,
                  loading: _busy,
                  label: 'Change password',
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// =============================================================================
// Sessions
// =============================================================================
class _SessionsCard extends ConsumerWidget {
  const _SessionsCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppTokens t = context.tokens;
    final AsyncValue<List<SessionInfo>> sessions = ref.watch(sessionsProvider);
    final List<SessionInfo> rows =
        sessions.valueOrNull ?? const <SessionInfo>[];

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const CardHeader(
            title: 'Active sessions',
            description: 'Devices currently signed in to your account.',
          ),
          if (sessions.isLoading)
            CardBody(
              child: Column(
                spacing: 12,
                children: <Widget>[
                  for (int index = 0; index < 2; index++)
                    const Skeleton(height: 48),
                ],
              ),
            )
          else
            Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: <Widget>[
                for (final SessionInfo session in rows)
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 20,
                      vertical: 14,
                    ),
                    decoration: BoxDecoration(
                      border: session == rows.last
                          ? null
                          : Border(bottom: BorderSide(color: t.border)),
                    ),
                    child: Row(
                      spacing: 12,
                      children: <Widget>[
                        Container(
                          width: 32,
                          height: 32,
                          decoration: BoxDecoration(
                            color: t.surfaceSunken,
                            borderRadius: BorderRadius.circular(Radii.lg),
                          ),
                          alignment: Alignment.center,
                          child: Icon(
                            switch (session.deviceType) {
                              'mobile' || 'tablet' => LucideIcons.smartphone,
                              'api' => LucideIcons.monitor,
                              _ => LucideIcons.laptop,
                            },
                            size: 16,
                            color: t.contentMuted,
                          ),
                        ),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: <Widget>[
                              Row(
                                spacing: 8,
                                children: <Widget>[
                                  Flexible(
                                    child: Text(
                                      session.deviceLabel ?? 'Unknown device',
                                      overflow: TextOverflow.ellipsis,
                                      style: TextStyle(
                                        fontSize: 13,
                                        fontWeight: FontWeight.w500,
                                        color: t.content,
                                      ),
                                    ),
                                  ),
                                  if (session.isCurrent)
                                    const AppBadge(
                                      'This device',
                                      tone: BadgeTone.primary,
                                    ),
                                ],
                              ),
                              Text(
                                '${session.ipAddress ?? 'unknown IP'} · via '
                                '${session.loginMethod} · '
                                '${session.lastUsedAt != null ? 'active ${formatRelative(session.lastUsedAt!)}' : 'started ${formatRelative(session.createdAt)}'}',
                                overflow: TextOverflow.ellipsis,
                                style: TextStyle(
                                  fontSize: 11,
                                  color: t.contentMuted,
                                ),
                              ),
                            ],
                          ),
                        ),
                        // The current session is not offered - signing out is the dedicated
                        // action for that, and revoking yourself here would look like a bug.
                        if (!session.isCurrent)
                          AppIconButton(
                            icon: LucideIcons.trash2,
                            tooltip:
                                'Revoke session on ${session.deviceLabel ?? 'unknown device'}',
                            size: 14,
                            colour: t.danger,
                            onPressed: () async {
                              try {
                                await ref
                                    .read(authApiProvider)
                                    .revokeSession(session.id);
                                ref.invalidate(sessionsProvider);
                                ref.invalidate(userStatsProvider);
                                if (context.mounted) {
                                  context.toastSuccess('Session revoked');
                                }
                              } catch (error) {
                                if (context.mounted) {
                                  context.toastApiError(
                                    error,
                                    'Could not revoke the session',
                                  );
                                }
                              }
                            },
                          ),
                      ],
                    ),
                  ),
                const SizedBox(height: 8),
              ],
            ),
        ],
      ),
    );
  }
}

// =============================================================================
// Organization
// =============================================================================
/// Currencies offered for an organization.
///
/// A short list rather than all 180 ISO codes: this is self-hosted software for one small
/// business, which deals in one currency and picks it once. The API still accepts any
/// three-letter code, so this is what the dropdown offers, not what the system permits.
const List<SelectOption> _currencyOptions = <SelectOption>[
  SelectOption(value: 'INR', label: 'INR - Indian rupee'),
  SelectOption(value: 'USD', label: 'USD - US dollar'),
  SelectOption(value: 'EUR', label: 'EUR - Euro'),
  SelectOption(value: 'GBP', label: 'GBP - Pound sterling'),
  SelectOption(value: 'AED', label: 'AED - UAE dirham'),
  SelectOption(value: 'SGD', label: 'SGD - Singapore dollar'),
  SelectOption(value: 'AUD', label: 'AUD - Australian dollar'),
  SelectOption(value: 'CAD', label: 'CAD - Canadian dollar'),
  SelectOption(value: 'JPY', label: 'JPY - Japanese yen'),
  SelectOption(value: 'LKR', label: 'LKR - Sri Lankan rupee'),
  SelectOption(value: 'NPR', label: 'NPR - Nepalese rupee'),
  SelectOption(value: 'BDT', label: 'BDT - Bangladeshi taka'),
];

/// A short list of zones, plus whatever is already saved.
///
/// The web app enumerates the browser's own IANA database. The bundled `timezone` package
/// here has one too, but offering 400-odd rows in a dropdown is a worse control than a dozen
/// - and this is a setting chosen once. [_withCurrent] guarantees the stored value is always
/// among them.
const List<SelectOption> _timezoneOptions = <SelectOption>[
  SelectOption(value: 'Asia/Kolkata', label: 'Asia/Kolkata'),
  SelectOption(value: 'Asia/Dubai', label: 'Asia/Dubai'),
  SelectOption(value: 'Asia/Singapore', label: 'Asia/Singapore'),
  SelectOption(value: 'Asia/Colombo', label: 'Asia/Colombo'),
  SelectOption(value: 'Asia/Kathmandu', label: 'Asia/Kathmandu'),
  SelectOption(value: 'Asia/Dhaka', label: 'Asia/Dhaka'),
  SelectOption(value: 'Europe/London', label: 'Europe/London'),
  SelectOption(value: 'Europe/Berlin', label: 'Europe/Berlin'),
  SelectOption(value: 'America/New_York', label: 'America/New_York'),
  SelectOption(value: 'America/Los_Angeles', label: 'America/Los_Angeles'),
  SelectOption(value: 'Australia/Sydney', label: 'Australia/Sydney'),
  SelectOption(value: 'UTC', label: 'UTC'),
];

/// Guarantee the value already saved is offered.
///
/// Without this, a stored value the list happens not to contain leaves the picker showing a
/// placeholder - and pressing Save could write something the user never chose. A settings
/// form that silently changes a setting you never touched is the worst kind of bug in a
/// settings form.
List<SelectOption> _withCurrent(List<SelectOption> options, String? current) {
  if (current == null || options.any((SelectOption o) => o.value == current)) {
    return options;
  }
  return <SelectOption>[
    SelectOption(value: current, label: current),
    ...options,
  ];
}

class _OrganizationCard extends ConsumerStatefulWidget {
  const _OrganizationCard();

  @override
  ConsumerState<_OrganizationCard> createState() => _OrganizationCardState();
}

class _OrganizationCardState extends ConsumerState<_OrganizationCard> {
  String? _name;
  String? _gstin;
  // Undefined until touched, so an untouched field is left out of the PATCH entirely rather
  // than sent back as the value it already had.
  String? _currency;
  String? _timezone;
  int? _fiscalStart;
  String? _error;
  bool _saving = false;

  @override
  Widget build(BuildContext context) {
    final AppTokens t = context.tokens;
    final AsyncValue<Organization> query = ref.watch(
      currentOrganizationProvider,
    );
    final Organization? organization = query.valueOrNull;

    if (organization == null) {
      return AppCard(
        padding: const EdgeInsets.all(20),
        child: const Skeleton(height: 200),
      );
    }

    Future<void> save() async {
      setState(() {
        _error = null;
        _saving = true;
      });
      try {
        await ref
            .read(organizationsApiProvider)
            .update(
              name: _name,
              gstin: _gstin,
              currency: _currency,
              timezone: _timezone,
              fiscalYearStartMonth: _fiscalStart,
            );
        ref.invalidate(currentOrganizationProvider);
        ref.invalidate(organizationsProvider);
        ref.invalidate(periodOptionsProvider);
        // The session carries the currency, timezone, and fiscal year that every formatter
        // reads, so it has to be re-fetched or the screen keeps rendering the old currency.
        await ref.read(authControllerProvider.notifier).refresh();
        if (context.mounted) context.toastSuccess('Organization updated');
      } catch (error) {
        if (mounted) {
          final ApiError apiError = ApiError.from(error);
          setState(
            () => _error = apiError.fieldErrors['gstin'] ?? apiError.message,
          );
        }
      } finally {
        if (mounted) setState(() => _saving = false);
      }
    }

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          CardHeader(
            title: 'Organization',
            description: '${organization.name} · ${organization.slug}',
            action: AppBadge(organization.plan),
          ),
          CardBody(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              spacing: 16,
              children: <Widget>[
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  spacing: 16,
                  children: <Widget>[
                    Expanded(
                      child: AppInput(
                        label: 'Display name',
                        initialValue: organization.name,
                        onChanged: (String value) => _name = value,
                      ),
                    ),
                    Expanded(
                      child: AppInput(
                        label: 'GSTIN',
                        initialValue: organization.gstin ?? '',
                        placeholder: '29AABCU9603R1ZM',
                        error: _error,
                        hint: '15 characters. Validated on save.',
                        onChanged: (String value) => _gstin = value,
                      ),
                    ),
                  ],
                ),

                // These three read as plain text in an earlier revision, which says "fixed,
                // do not ask" - and the API had accepted all three as editable the whole
                // time.
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  spacing: 16,
                  children: <Widget>[
                    Expanded(
                      child: AppSelect(
                        label: 'Currency',
                        value: _currency ?? organization.currency,
                        options: _withCurrent(
                          _currencyOptions,
                          organization.currency,
                        ),
                        hint: 'Used for every amount shown.',
                        onChanged: (String next) =>
                            setState(() => _currency = next),
                      ),
                    ),
                    Expanded(
                      child: AppSelect(
                        label: 'Timezone',
                        value: _timezone ?? organization.timezone,
                        options: _withCurrent(
                          _timezoneOptions,
                          organization.timezone,
                        ),
                        hint: 'Decides what counts as today.',
                        onChanged: (String next) =>
                            setState(() => _timezone = next),
                      ),
                    ),
                    Expanded(
                      child: AppSelect(
                        label: 'Financial year starts',
                        value:
                            '${_fiscalStart ?? organization.fiscalYearStartMonth}',
                        options: <SelectOption>[
                          for (int month = 1; month <= 12; month++)
                            SelectOption(
                              value: '$month',
                              label: monthName(month),
                            ),
                        ],
                        hint: 'April in India.',
                        onChanged: (String next) =>
                            setState(() => _fiscalStart = int.parse(next)),
                      ),
                    ),
                  ],
                ),

                if (_fiscalStart != null &&
                    _fiscalStart != organization.fiscalYearStartMonth)
                  // Stated rather than silently accepted: the years already created keep
                  // their own dates, so a mid-year change leaves the report presets and the
                  // existing fiscal year describing different windows until the next one
                  // opens.
                  Text(
                    'Changing this does not move the financial years already created. '
                    'Entries already posted keep the year they went into.',
                    style: TextStyle(
                      fontSize: 12,
                      color: t.warning,
                      height: 1.5,
                    ),
                  ),

                AppButton(
                  onPressed: _saving ? null : save,
                  loading: _saving,
                  label: 'Save organization',
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// Used by the dashboard's onboarding path when the user has no organization.
class CreateOrganizationCard extends ConsumerStatefulWidget {
  const CreateOrganizationCard({super.key});

  @override
  ConsumerState<CreateOrganizationCard> createState() =>
      _CreateOrganizationCardState();
}

class _CreateOrganizationCardState
    extends ConsumerState<CreateOrganizationCard> {
  final TextEditingController _name = TextEditingController();
  String? _error;
  bool _saving = false;

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    Future<void> create() async {
      setState(() {
        _error = null;
        _saving = true;
      });
      try {
        await ref
            .read(organizationsApiProvider)
            .create(name: _name.text.trim());
        await ref.read(authControllerProvider.notifier).refresh();
        if (context.mounted) context.toastSuccess('Organization created');
      } catch (error) {
        if (mounted) {
          setState(() => _error = ApiError.from(error).message);
        }
      } finally {
        if (mounted) setState(() => _saving = false);
      }
    }

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const CardHeader(
            title: 'Create an organization',
            description: 'You will be its owner, with full access.',
          ),
          CardBody(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              spacing: 16,
              children: <Widget>[
                AppInput(
                  label: 'Company name',
                  controller: _name,
                  placeholder: 'Acme Trading Co',
                  leftIcon: LucideIcons.building2,
                  error: _error,
                  onChanged: (_) => setState(() {}),
                ),
                AppButton(
                  onPressed: _name.text.trim().isEmpty || _saving
                      ? null
                      : create,
                  loading: _saving,
                  label: 'Create organization',
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// =============================================================================
// Appearance
// =============================================================================
class _AppearanceCard extends ConsumerWidget {
  const _AppearanceCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppTokens t = context.tokens;
    final ThemeChoice choice = ref.watch(themeControllerProvider);

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const CardHeader(
            title: 'Appearance',
            description: 'Applies to this installation.',
          ),
          CardBody(
            child: Semantics(
              label: 'Colour theme',
              child: Row(
                spacing: 8,
                children: <Widget>[
                  for (final ThemeChoice option in ThemeChoice.values)
                    Expanded(
                      child: _ThemeOption(
                        option: option,
                        selected: choice == option,
                        onTap: () => ref
                            .read(themeControllerProvider.notifier)
                            .set(option),
                        tokens: t,
                      ),
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ThemeOption extends StatefulWidget {
  const _ThemeOption({
    required this.option,
    required this.selected,
    required this.onTap,
    required this.tokens,
  });

  final ThemeChoice option;
  final bool selected;
  final VoidCallback onTap;
  final AppTokens tokens;

  @override
  State<_ThemeOption> createState() => _ThemeOptionState();
}

class _ThemeOptionState extends State<_ThemeOption> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final AppTokens t = widget.tokens;
    final IconData icon = switch (widget.option) {
      ThemeChoice.light => LucideIcons.sun,
      ThemeChoice.dark => LucideIcons.moon,
      ThemeChoice.system => LucideIcons.monitor,
    };
    final Color foreground = widget.selected ? t.primary : t.contentSecondary;

    return Semantics(
      selected: widget.selected,
      button: true,
      child: MouseRegion(
        cursor: SystemMouseCursors.click,
        onEnter: (_) => setState(() => _hovered = true),
        onExit: (_) => setState(() => _hovered = false),
        child: GestureDetector(
          onTap: widget.onTap,
          child: AnimatedContainer(
            duration: Motion.fast,
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 12),
            decoration: BoxDecoration(
              color: widget.selected
                  ? t.primary.at(0.10)
                  : _hovered
                  ? t.surfaceHover
                  : Colors.transparent,
              borderRadius: BorderRadius.circular(Radii.lg),
              border: Border.all(color: widget.selected ? t.primary : t.border),
            ),
            child: Column(
              spacing: 6,
              children: <Widget>[
                Icon(icon, size: 16, color: foreground),
                Text(
                  widget.option.shortLabel,
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w500,
                    color: foreground,
                  ),
                ),
                if (widget.selected)
                  Icon(LucideIcons.check, size: 12, color: foreground),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

// =============================================================================
// Account summary
// =============================================================================
class _AccountCard extends ConsumerWidget {
  const _AccountCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppTokens t = context.tokens;
    final AuthState auth = ref.watch(authControllerProvider);
    final UserStats? stats = ref.watch(userStatsProvider).valueOrNull;

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const CardHeader(title: 'Account'),
          CardBody(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              spacing: 16,
              children: <Widget>[
                Column(
                  spacing: 10,
                  children: <Widget>[
                    _StatRow(
                      label: 'Organizations',
                      value: stats == null ? '-' : '${stats.organizations}',
                    ),
                    _StatRow(
                      label: 'Active sessions',
                      value: stats == null ? '-' : '${stats.activeSessions}',
                    ),
                    if (auth.user?.isTwoFactorEnabled == true)
                      _StatRow(
                        label: 'Recovery codes left',
                        value: stats == null
                            ? '-'
                            : '${stats.recoveryCodesRemaining}',
                      ),
                    _StatRow(
                      label: 'Last sign-in',
                      value: auth.user?.lastLoginAt != null
                          ? formatRelative(auth.user!.lastLoginAt!)
                          : '-',
                    ),
                  ],
                ),
                Container(
                  padding: const EdgeInsets.only(top: 16),
                  decoration: BoxDecoration(
                    border: Border(top: BorderSide(color: t.border)),
                  ),
                  child: Column(
                    spacing: 8,
                    children: <Widget>[
                      AppButton(
                        onPressed: () =>
                            ref.read(authControllerProvider.notifier).refresh(),
                        variant: AppButtonVariant.secondary,
                        fullWidth: true,
                        label: 'Refresh permissions',
                      ),
                      AppButton(
                        onPressed: () async {
                          final bool confirmed = await confirmAction(
                            context,
                            title: 'Sign out of every device?',
                            message:
                                'Every session on every machine ends, including this one.',
                            confirmLabel: 'Sign out everywhere',
                          );
                          if (!confirmed) return;
                          await ref
                              .read(authControllerProvider.notifier)
                              .signOut(allDevices: true);
                        },
                        variant: AppButtonVariant.ghost,
                        fullWidth: true,
                        leftIcon: LucideIcons.shield,
                        label: 'Sign out everywhere',
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _StatRow extends StatelessWidget {
  const _StatRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final AppTokens t = context.tokens;
    return Row(
      children: <Widget>[
        Text(label, style: TextStyle(fontSize: 13, color: t.contentMuted)),
        const Spacer(),
        Text(
          value,
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w500,
            color: t.content,
          ),
        ),
      ],
    );
  }
}
