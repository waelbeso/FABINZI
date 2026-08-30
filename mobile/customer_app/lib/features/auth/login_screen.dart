import 'package:flutter/material.dart';

import '../../core/app_controller.dart';
import '../../core/l10n.dart';
import '../../core/models.dart';
import '../../ui/common.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key, required this.controller});
  final AppController controller;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final username = TextEditingController();
  final password = TextEditingController();
  bool busy = false;
  String? error;

  @override
  void dispose() {
    username.dispose();
    password.dispose();
    super.dispose();
  }

  Future<void> submit() async {
    if (busy || username.text.trim().isEmpty || password.text.isEmpty) return;
    setState(() { busy = true; error = null; });
    try {
      await widget.controller.login(username.text.trim(), password.text);
      if (mounted) Navigator.pop(context);
    } on ApiProblem catch (problem) {
      setState(() => error = problem.code == 'invalid_credentials' ? problem.message : problem.message);
    } catch (_) {
      setState(() => error = L10n.t(context, 'offline'));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(),
        body: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 420),
                child: AutofillGroup(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const Center(child: FabinziWordmark()),
                      const SizedBox(height: 32),
                      Text(L10n.t(context, 'signIn'), style: Theme.of(context).textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.w900)),
                      const SizedBox(height: 8),
                      Text(L10n.t(context, 'browseAsGuest')),
                      const SizedBox(height: 24),
                      TextField(
                        controller: username,
                        autofillHints: const [AutofillHints.username],
                        textInputAction: TextInputAction.next,
                        decoration: InputDecoration(labelText: L10n.t(context, 'username'), prefixIcon: const Icon(Icons.person_outline)),
                      ),
                      const SizedBox(height: 14),
                      TextField(
                        controller: password,
                        obscureText: true,
                        enableSuggestions: false,
                        autocorrect: false,
                        autofillHints: const [AutofillHints.password],
                        onSubmitted: (_) => submit(),
                        decoration: InputDecoration(labelText: L10n.t(context, 'password'), prefixIcon: const Icon(Icons.lock_outline)),
                      ),
                      if (error != null) ...[
                        const SizedBox(height: 12),
                        Semantics(liveRegion: true, child: Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
                      ],
                      const SizedBox(height: 20),
                      FilledButton.icon(
                        onPressed: busy ? null : submit,
                        icon: busy ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.login),
                        label: Text(L10n.t(context, 'signIn')),
                      ),
                      const SizedBox(height: 18),
                      Text(L10n.t(context, 'unsupportedAccountActions'), textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodySmall),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      );
}
