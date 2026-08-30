import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/app_controller.dart';
import '../../core/l10n.dart';
import '../../core/models.dart';
import '../../ui/common.dart';

class PurchasesScreen extends StatefulWidget {
  const PurchasesScreen({super.key, required this.controller});
  final AppController controller;

  @override
  State<PurchasesScreen> createState() => _PurchasesScreenState();
}

class _PurchasesScreenState extends State<PurchasesScreen> {
  List<Purchase> rows = [];
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
      final first = await widget.controller.api.purchases();
      final all = <Purchase>[...first.results];
      var page = 2;
      while (all.length < first.count) {
        final next = await widget.controller.api.purchases(page: page++);
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

  @override
  Widget build(BuildContext context) {
    if (loading) return const BusyView();
    if (error != null) return FailureView(error: error!, onRetry: load);
    if (rows.isEmpty) {
      return EmptyView(
        icon: Icons.receipt_long_outlined,
        title: L10n.t(context, 'noPurchases'),
      );
    }
    return RefreshIndicator(
      onRefresh: load,
      child: ListView.separated(
        padding: const EdgeInsets.all(16),
        itemCount: rows.length,
        separatorBuilder: (_, _) => const SizedBox(height: 10),
        itemBuilder: (context, index) {
          final row = rows[index];
          return Card(
            child: ListTile(
              contentPadding: const EdgeInsets.symmetric(
                horizontal: 16,
                vertical: 10,
              ),
              leading: CircleAvatar(
                child: Icon(_statusIcon(row.fulfillmentStatus)),
              ),
              title: Text(
                row.statusLabel.isEmpty ? row.status : row.statusLabel,
                style: const TextStyle(fontWeight: FontWeight.w800),
              ),
              subtitle: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const SizedBox(height: 4),
                  Text(
                    row.fulfillmentStatusLabel.isEmpty
                        ? row.fulfillmentStatus
                        : row.fulfillmentStatusLabel,
                  ),
                  const SizedBox(height: 4),
                  Text(
                    row.reference,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ],
              ),
              trailing: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  MoneyText(row.total),
                  const Icon(Icons.chevron_right, size: 18),
                ],
              ),
              onTap: () async {
                await Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) => PurchaseDetailScreen(
                      controller: widget.controller,
                      reference: row.reference,
                      initial: row,
                    ),
                  ),
                );
                load();
              },
            ),
          );
        },
      ),
    );
  }

  IconData _statusIcon(String status) => switch (status) {
    'delivered' => Icons.check_circle_outline,
    'shipped' || 'partially_shipped' => Icons.local_shipping_outlined,
    'cancelled' || 'failed' || 'returned' => Icons.error_outline,
    _ => Icons.inventory_2_outlined,
  };
}

class PurchaseDetailScreen extends StatefulWidget {
  const PurchaseDetailScreen({
    super.key,
    required this.controller,
    required this.reference,
    this.initial,
  });
  final AppController controller;
  final String reference;
  final Purchase? initial;

  @override
  State<PurchaseDetailScreen> createState() => _PurchaseDetailScreenState();
}

class _PurchaseDetailScreenState extends State<PurchaseDetailScreen> {
  Purchase? purchase;
  Object? error;
  bool loading = false;
  late final AppLifecycleListener lifecycle;

  @override
  void initState() {
    super.initState();
    purchase = widget.initial;
    lifecycle = AppLifecycleListener(onResume: refresh);
    refresh();
  }

  @override
  void dispose() {
    lifecycle.dispose();
    super.dispose();
  }

  Future<void> refresh() async {
    if (loading) return;
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final value = await widget.controller.api.purchase(widget.reference);
      if (mounted) setState(() => purchase = value);
    } catch (value) {
      if (mounted) setState(() => error = value);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: Text(L10n.t(context, 'purchase')),
      actions: [
        IconButton(
          onPressed: loading ? null : refresh,
          tooltip: L10n.t(context, 'refresh'),
          icon: const Icon(Icons.refresh),
        ),
      ],
    ),
    body: purchase == null && loading
        ? const BusyView()
        : error != null && purchase == null
        ? FailureView(error: error!, onRetry: refresh)
        : _body(context),
  );

  Widget _body(BuildContext context) {
    final row = purchase!;
    return RefreshIndicator(
      onRefresh: refresh,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(18),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          row.statusLabel.isEmpty
                              ? row.status
                              : row.statusLabel,
                          style: Theme.of(context).textTheme.titleLarge
                              ?.copyWith(fontWeight: FontWeight.w900),
                        ),
                      ),
                      MoneyText(
                        row.total,
                        style: Theme.of(context).textTheme.titleLarge
                            ?.copyWith(fontWeight: FontWeight.w900),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(
                    row.reference,
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                  const Divider(height: 26),
                  _detailRow(
                    L10n.t(context, 'fulfillment'),
                    row.fulfillmentStatusLabel.isEmpty
                        ? row.fulfillmentStatus
                        : row.fulfillmentStatusLabel,
                  ),
                  _detailRow(
                    L10n.t(context, 'paymentMethod'),
                    row.paymentMethod,
                  ),
                  if (row.paymentStatus != null)
                    _detailRow(
                      L10n.t(context, 'paymentStatus'),
                      row.paymentStatus!,
                    ),
                  if (row.createdAt != null)
                    _detailRow(
                      L10n.t(context, 'created'),
                      MaterialLocalizations.of(context)
                          .formatMediumDate(row.createdAt!.toLocal()),
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          Text(
            L10n.t(context, 'items'),
            style: Theme.of(context).textTheme.titleLarge
                ?.copyWith(fontWeight: FontWeight.w900),
          ),
          const SizedBox(height: 10),
          ...row.items.map(
            (item) => Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              item.title,
                              style: const TextStyle(
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                          ),
                          MoneyText(item.lineTotal),
                        ],
                      ),
                      if ([item.size, item.colorName].any((v) => v.isNotEmpty))
                        Padding(
                          padding: const EdgeInsets.only(top: 4),
                          child: Text(
                            [
                              item.size,
                              item.colorName,
                            ].where((v) => v.isNotEmpty).join(' · '),
                          ),
                        ),
                      const SizedBox(height: 6),
                      Text('${L10n.t(context, 'quantity')}: ${item.quantity}'),
                      const Divider(height: 22),
                      Text(
                        item.fulfillment.label.isEmpty
                            ? item.fulfillment.status
                            : item.fulfillment.label,
                        style: const TextStyle(fontWeight: FontWeight.w700),
                      ),
                      if (item.fulfillment.carrier != null)
                        Padding(
                          padding: const EdgeInsets.only(top: 5),
                          child: Text(
                            '${L10n.t(context, 'carrier')}: ${item.fulfillment.carrier}',
                          ),
                        ),
                      if (item.fulfillment.trackingNumber != null)
                        Padding(
                          padding: const EdgeInsets.only(top: 5),
                          child: Text(
                            '${L10n.t(context, 'trackingNumber')}: ${item.fulfillment.trackingNumber}',
                          ),
                        ),
                      if (item.fulfillment.trackingUrl != null)
                        Padding(
                          padding: const EdgeInsets.only(top: 8),
                          child: OutlinedButton.icon(
                            onPressed: () => launchUrl(
                              Uri.parse(item.fulfillment.trackingUrl!),
                              mode: LaunchMode.externalApplication,
                            ),
                            icon: const Icon(Icons.open_in_new),
                            label: Text(L10n.t(context, 'tracking')),
                          ),
                        )
                      else
                        Padding(
                          padding: const EdgeInsets.only(top: 6),
                          child: Text(
                            L10n.t(context, 'noTracking'),
                            style: Theme.of(context).textTheme.bodySmall,
                          ),
                        ),
                    ],
                  ),
                ),
              ),
            ),
          ),
          if (loading)
            const Padding(
              padding: EdgeInsets.all(14),
              child: Center(child: LinearProgressIndicator()),
            ),
        ],
      ),
    );
  }

  Widget _detailRow(String label, String value) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 4),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(width: 130, child: Text(label)),
        Expanded(
          child: Text(
            value,
            style: const TextStyle(fontWeight: FontWeight.w700),
          ),
        ),
      ],
    ),
  );
}
