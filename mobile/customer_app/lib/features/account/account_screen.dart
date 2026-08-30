import 'package:flutter/material.dart';

import '../../core/app_controller.dart';
import '../../core/l10n.dart';
import '../auth/login_screen.dart';

class AccountScreen extends StatelessWidget {
  const AccountScreen({super.key, required this.controller, required this.requestSignIn});
  final AppController controller;
  final Future<bool> Function() requestSignIn;

  @override
  Widget build(BuildContext context) => ListView(padding: const EdgeInsets.all(16), children: [
    if (controller.profile != null)
      Card(child: ListTile(
        contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
        leading: const CircleAvatar(radius: 26, child: Icon(Icons.person_outline)),
        title: Text(controller.profile!.displayName, style: const TextStyle(fontWeight: FontWeight.w900)),
        subtitle: Text(controller.profile!.email.isNotEmpty ? controller.profile!.email : controller.profile!.username),
      ))
    else
      Card(child: Padding(padding: const EdgeInsets.all(18), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(L10n.t(context, 'guest'), style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w900)),
        const SizedBox(height: 6), Text(L10n.t(context, 'browseAsGuest')), const SizedBox(height: 14),
        FilledButton.icon(onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => LoginScreen(controller: controller))), icon: const Icon(Icons.login), label: Text(L10n.t(context, 'signIn'))),
      ]))),
    const SizedBox(height: 18),
    Text(L10n.t(context, 'language'), style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w900)),
    RadioListTile<String>(value: 'en', groupValue: controller.locale.languageCode, onChanged: (value) { if (value != null) controller.setLocale(value); }, title: Text(L10n.t(context, 'english'))),
    RadioListTile<String>(value: 'ar', groupValue: controller.locale.languageCode, onChanged: (value) { if (value != null) controller.setLocale(value); }, title: Text(L10n.t(context, 'arabic'))),
    const Divider(height: 28),
    Text(L10n.t(context, 'theme'), style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w900)),
    RadioListTile<ThemeMode>(value: ThemeMode.system, groupValue: controller.themeMode, onChanged: (value) { if (value != null) controller.setThemeMode(value); }, title: Text(L10n.t(context, 'system'))),
    RadioListTile<ThemeMode>(value: ThemeMode.light, groupValue: controller.themeMode, onChanged: (value) { if (value != null) controller.setThemeMode(value); }, title: Text(L10n.t(context, 'light'))),
    RadioListTile<ThemeMode>(value: ThemeMode.dark, groupValue: controller.themeMode, onChanged: (value) { if (value != null) controller.setThemeMode(value); }, title: Text(L10n.t(context, 'dark'))),
    const Divider(height: 28),
    ListTile(leading: const Icon(Icons.info_outline), title: Text(L10n.t(context, 'accountCapabilities')), subtitle: Text(L10n.t(context, 'unsupportedAccountActions'))),
    if (controller.profile != null) ...[
      const SizedBox(height: 12),
      OutlinedButton.icon(onPressed: controller.logout, icon: const Icon(Icons.logout), label: Text(L10n.t(context, 'signOut'))),
    ],
    const SizedBox(height: 32),
  ]);
}
