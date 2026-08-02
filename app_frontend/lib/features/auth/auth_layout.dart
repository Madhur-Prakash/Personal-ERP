import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../../layout/theme_toggle.dart';
import '../../theme/tokens.dart';

/// Shell for the unauthenticated screens.
///
/// A single centred column rather than the usual split-screen marketing panel: these
/// screens exist to get someone through a form, and a decorative half-screen only pushes
/// the fields around on smaller laptops.
class AuthLayout extends StatelessWidget {
  const AuthLayout({
    super.key,
    required this.title,
    this.subtitle,
    required this.child,
    this.footer,
  });

  final String title;

  /// A widget rather than a string: several of these embed the user's own email in bold
  /// mid-sentence, which is the whole point of the sentence.
  final Widget? subtitle;

  final Widget child;
  final Widget? footer;

  @override
  Widget build(BuildContext context) {
    final AppTokens t = context.tokens;

    return Scaffold(
      backgroundColor: t.canvas,
      body: Stack(
        children: <Widget>[
          // A very soft radial wash. Enough to stop a large empty window reading as
          // unstyled, subtle enough not to compete with the form.
          Positioned.fill(
            child: DecoratedBox(
              decoration: BoxDecoration(
                gradient: RadialGradient(
                  center: const Alignment(0, -1.6),
                  radius: 1.1,
                  colors: <Color>[
                    t.primary.withValues(alpha: 0.14),
                    t.canvas.withValues(alpha: 0),
                  ],
                  stops: const <double>[0, 0.7],
                ),
              ),
            ),
          ),
          Column(
            children: <Widget>[
              Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: 24,
                  vertical: 20,
                ),
                child: Row(
                  children: <Widget>[
                    MouseRegion(
                      cursor: SystemMouseCursors.click,
                      child: GestureDetector(
                        onTap: () => context.go('/login'),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          spacing: 8,
                          children: <Widget>[
                            Container(
                              width: 28,
                              height: 28,
                              decoration: BoxDecoration(
                                color: t.primary,
                                borderRadius: BorderRadius.circular(Radii.lg),
                              ),
                              alignment: Alignment.center,
                              child: Text(
                                'N',
                                style: TextStyle(
                                  fontSize: 14,
                                  fontWeight: FontWeight.w700,
                                  color: t.primaryContent,
                                  height: 1,
                                ),
                              ),
                            ),
                            Text(
                              'Personal ERP',
                              style: TextStyle(
                                fontSize: 15,
                                fontWeight: FontWeight.w600,
                                letterSpacing: -0.3,
                                color: t.content,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                    const Spacer(),
                    const ThemeToggle(),
                  ],
                ),
              ),
              Expanded(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.fromLTRB(24, 8, 24, 64),
                  child: Center(
                    child: ConstrainedBox(
                      constraints: const BoxConstraints(maxWidth: 400),
                      child: Column(
                        children: <Widget>[
                          Text(
                            title,
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              fontSize: 26,
                              height: 1.15,
                              fontWeight: FontWeight.w600,
                              letterSpacing: -0.78,
                              color: t.content,
                            ),
                          ),
                          if (subtitle != null) ...<Widget>[
                            const SizedBox(height: 8),
                            DefaultTextStyle(
                              style: TextStyle(
                                fontSize: 14,
                                color: t.contentMuted,
                                height: 1.6,
                              ),
                              textAlign: TextAlign.center,
                              child: subtitle!,
                            ),
                          ],
                          const SizedBox(height: 28),
                          Container(
                            width: double.infinity,
                            padding: const EdgeInsets.all(24),
                            decoration: BoxDecoration(
                              color: t.surface,
                              borderRadius: BorderRadius.circular(Radii.xl2),
                              border: Border.all(color: t.border),
                              boxShadow: t.shadowLg,
                            ),
                            child: child,
                          ),
                          if (footer != null) ...<Widget>[
                            const SizedBox(height: 24),
                            DefaultTextStyle(
                              style: TextStyle(
                                fontSize: 13,
                                color: t.contentMuted,
                              ),
                              textAlign: TextAlign.center,
                              child: footer!,
                            ),
                          ],
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// The "Already have an account? Sign in" line under an auth card.
///
/// One widget because all six screens have one and they must sit identically - a
/// hand-built row per screen drifted by a pixel or two on the web before the layout was
/// shared.
class AuthFooterPrompt extends StatelessWidget {
  const AuthFooterPrompt({
    super.key,
    required this.prompt,
    required this.actionLabel,
    required this.onAction,
  });

  final String prompt;
  final String actionLabel;
  final VoidCallback onAction;

  @override
  Widget build(BuildContext context) {
    final AppTokens t = context.tokens;
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Text(prompt, style: TextStyle(fontSize: 13, color: t.contentMuted)),
        const SizedBox(width: 4),
        MouseRegion(
          cursor: SystemMouseCursors.click,
          child: GestureDetector(
            onTap: onAction,
            child: Text(
              actionLabel,
              style: TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w500,
                color: t.primary,
              ),
            ),
          ),
        ),
      ],
    );
  }
}

/// The `or` divider between the password form and the passwordless options.
class AuthDivider extends StatelessWidget {
  const AuthDivider({super.key});

  @override
  Widget build(BuildContext context) {
    final AppTokens t = context.tokens;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 20),
      child: Row(
        spacing: 12,
        children: <Widget>[
          Expanded(child: Container(height: 1, color: t.border)),
          Text(
            'OR',
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w500,
              letterSpacing: 0.6,
              color: t.contentMuted,
            ),
          ),
          Expanded(child: Container(height: 1, color: t.border)),
        ],
      ),
    );
  }
}

/// The "← Back to sign in" footer link.
///
/// In the layout file rather than duplicated per screen: five of the auth screens end
/// with it, and a hand-built row per screen drifted by a pixel on the web before it was
/// shared.
class BackToSignIn extends StatelessWidget {
  const BackToSignIn({super.key});

  @override
  Widget build(BuildContext context) {
    final AppTokens t = context.tokens;
    return MouseRegion(
      cursor: SystemMouseCursors.click,
      child: GestureDetector(
        onTap: () => context.go('/login'),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          mainAxisSize: MainAxisSize.min,
          spacing: 6,
          children: <Widget>[
            Icon(LucideIcons.arrowLeft, size: 14, color: t.contentMuted),
            Text(
              'Back to sign in',
              style: TextStyle(fontSize: 13, color: t.contentMuted),
            ),
          ],
        ),
      ),
    );
  }
}
