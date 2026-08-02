import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:timezone/data/latest_all.dart' as tz_data;

import 'app.dart';
import 'core/api_client.dart';
import 'state/providers.dart';
import 'state/theme_controller.dart';

/// Start-up.
///
/// Three things have to finish before the first frame, and each is here rather than in a
/// widget because doing it later would be visible:
///
/// * **The cookie jar.** It is file-backed, so opening it is async. The session restore
///   depends on it, and a client built without it would report "not signed in" on every
///   launch.
/// * **The stored theme.** The web app runs an inline script before first paint for
///   exactly this reason - applying it after mount is a flash of the wrong theme.
/// * **The timezone database.** Every timestamp in the app is rendered in the
///   organization's zone, and `getLocation` throws until this is loaded.
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  tz_data.initializeTimeZones();

  final ApiClient client = await ApiClient.create();
  final ThemeChoice theme = await ThemeController.load();

  runApp(
    ProviderScope(
      overrides: <Override>[
        apiClientProvider.overrideWithValue(client),
        themeControllerProvider.overrideWith(
          (Ref ref) => ThemeController(theme),
        ),
      ],
      child: const PersonalErpApp(),
    ),
  );
}
