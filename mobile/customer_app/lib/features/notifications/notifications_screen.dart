import 'package:flutter/material.dart';

import '../../core/app_controller.dart';
import '../../core/l10n.dart';
import '../../core/models.dart';
import '../../ui/common.dart';
import '../purchases/purchases_screen.dart';

class NotificationsScreen extends StatefulWidget {
  const NotificationsScreen({super.key, required this.controller});
  final AppController controller;

  @override
  State<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends State<NotificationsScreen> {
  List<NotificationItem> rows = [];
  bool loading = true;
  Object? error;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final first = await widget.controller.api.notifications();
      final all = <NotificationItem>[...first.results];
      var page = 2;
      while (all.length < first.count) {
        final next = await widget.controller.api.notifications(page: page++);
        if (next.results.isEmpty) break;
        all.addAll(next.results);
      }
      if (mounted) setState(() => rows = all);
    } catch (value) {
      if (mounted) setState(() => error = value);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> open(NotificationItem item) async {
    var value = item;
    if (!item.isRead) {
      try {
        value = await widget.controller.api.markNotificationRead(item.id);
      } catch (_) {
        value = item;
      }
      if (mounted) {
        setState(() {
          final index = rows.indexWhere((row) => row.id == item.id);
          if (index >= 0) rows[index] = value;
        });
      }
    }
    if (value.targetResource == 'purchase' &&
        value.targetReference != null &&
        mounted) {
      await Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => PurchaseDetailScreen(
            controller: widget.controller,
            reference: value.targetReference!,
          ),
        ),
      );
    }
  }

  Future<void> markAll() async {
    try {
      await widget.controller.api.markAllNotificationsRead();
      await load();
    } catch (error) {
      if (mounted) await showProblem(context, error);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: Text(L10n.t(context, 'notifications')),
      actions: [
        IconButton(
          tooltip: L10n.t(context, 'preferences'),
          onPressed: () => Navigator.of(context).push(
            MaterialPageRoute<void>(
              builder: (_) =>
                  NotificationPreferencesScreen(controller: widget.controller),
            ),
          ),
          icon: const Icon(Icons.tune),
        ),
        IconButton(
          tooltip: L10n.t(context, 'markAllRead'),
          onPressed: rows.any((row) => !row.isRead) ? markAll : null,
          icon: const Icon(Icons.done_all),
        ),
      ],
    ),
    body: loading
        ? const BusyView()
        : error != null
        ? FailureView(error: error!, onRetry: load)
        : rows.isEmpty
        ? EmptyView(
            icon: Icons.notifications_none,
            title: L10n.t(context, 'noNotifications'),
          )
        : RefreshIndicator(
            onRefresh: load,
            child: ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: rows.length,
              separatorBuilder: (_, _) => const SizedBox(height: 8),
              itemBuilder: (context, index) {
                final row = rows[index];
                return Card(
                  color: row.isRead
                      ? null
                      : Theme.of(context).colorScheme.primaryContainer
                            .withValues(alpha: .35),
                  child: ListTile(
                    leading: Icon(
                      row.isRead
                          ? Icons.notifications_none
                          : Icons.notifications_active_outlined,
                    ),
                    title: Text(
                      row.title,
                      style: TextStyle(
                        fontWeight: row.isRead
                            ? FontWeight.w600
                            : FontWeight.w900,
                      ),
                    ),
                    subtitle: Padding(
                      padding: const EdgeInsets.only(top: 4),
                      child: Text(row.body),
                    ),
                    trailing: row.targetResource == 'purchase'
                        ? const Icon(Icons.chevron_right)
                        : null,
                    onTap: () => open(row),
                  ),
                );
              },
            ),
          ),
  );
}

class NotificationPreferencesScreen extends StatefulWidget {
  const NotificationPreferencesScreen({super.key, required this.controller});
  final AppController controller;
  @override
  State<NotificationPreferencesScreen> createState() =>
      _NotificationPreferencesScreenState();
}

class _NotificationPreferencesScreenState
    extends State<NotificationPreferencesScreen> {
  NotificationPreferences? preferences;
  final phone = TextEditingController();
  bool loading = true;
  bool saving = false;
  Object? error;

  @override
  void initState() {
    super.initState();
    load();
  }

  @override
  void dispose() {
    phone.dispose();
    super.dispose();
  }

  Future<void> load() async {
    try {
      final value = await widget.controller.api.notificationPreferences();
      phone.text = value.phoneE164;
      if (mounted) setState(() => preferences = value);
    } catch (value) {
      if (mounted) setState(() => error = value);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> save({bool? email, bool? sms}) async {
    if (saving || preferences == null) return;
    setState(() => saving = true);
    try {
      final value = await widget.controller.api.updateNotificationPreferences(
        emailEnabled: email,
        smsEnabled: sms,
        phoneE164: phone.text.trim(),
      );
      if (mounted) setState(() => preferences = value);
    } catch (error) {
      if (mounted) await showProblem(context, error);
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text(L10n.t(context, 'preferences'))),
    body: loading
        ? const BusyView()
        : error != null
        ? FailureView(error: error!, onRetry: load)
        : ListView(
            padding: const EdgeInsets.all(18),
            children: [
              SwitchListTile(
                value: preferences!.emailEnabled,
                onChanged: saving ? null : (value) => save(email: value),
                title: Text(L10n.t(context, 'emailNotifications')),
                secondary: const Icon(Icons.email_outlined),
              ),
              SwitchListTile(
                value: preferences!.smsEnabled,
                onChanged: saving ? null : (value) => save(sms: value),
                title: Text(L10n.t(context, 'smsNotifications')),
                secondary: const Icon(Icons.sms_outlined),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: phone,
                keyboardType: TextInputType.phone,
                decoration: InputDecoration(
                  labelText: L10n.t(context, 'smsPhone'),
                  helperText: '+2010…',
                ),
              ),
              const SizedBox(height: 12),
              FilledButton(
                onPressed: saving ? null : () => save(),
                child: Text(L10n.t(context, 'save')),
              ),
              const SizedBox(height: 12),
              Text(
                L10n.t(context, 'deliveryNotGuaranteed'),
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
          ),
  );
}
