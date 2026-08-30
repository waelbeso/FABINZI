import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/app_controller.dart';
import '../core/config.dart';
import '../core/l10n.dart';
import '../core/models.dart';

class FabinziWordmark extends StatelessWidget {
  const FabinziWordmark({super.key, this.compact = false});
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Semantics(
      label: 'FABINZI',
      header: true,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: compact ? 30 : 38,
            height: compact ? 30 : 38,
            decoration: BoxDecoration(
              color: const Color(0xFF111827),
              borderRadius: BorderRadius.circular(compact ? 9 : 11),
            ),
            alignment: Alignment.center,
            child: Text(
              'F',
              style: TextStyle(
                color: scheme.brightness == Brightness.dark
                    ? const Color(0xFF9D87FF)
                    : const Color(0xFF7C5CFF),
                fontWeight: FontWeight.w900,
                fontSize: compact ? 19 : 24,
              ),
            ),
          ),
          const SizedBox(width: 9),
          Text(
            'FABINZI',
            style: TextStyle(
              fontWeight: FontWeight.w900,
              letterSpacing: 1.1,
              fontSize: compact ? 18 : 22,
            ),
          ),
        ],
      ),
    );
  }
}

class BusyView extends StatelessWidget {
  const BusyView({super.key, this.label});
  final String? label;
  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const CircularProgressIndicator(),
          const SizedBox(height: 16),
          Text(label ?? L10n.t(context, 'loading')),
        ],
      ),
    ),
  );
}

class EmptyView extends StatelessWidget {
  const EmptyView({
    super.key,
    required this.icon,
    required this.title,
    this.message,
    this.action,
  });
  final IconData icon;
  final String title;
  final String? message;
  final Widget? action;
  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(30),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 420),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 48, color: Theme.of(context).colorScheme.primary),
            const SizedBox(height: 14),
            Text(
              title,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.titleLarge
                  ?.copyWith(fontWeight: FontWeight.w800),
            ),
            if (message != null) ...[
              const SizedBox(height: 8),
              Text(
                message!,
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodyMedium,
              ),
            ],
            if (action != null) ...[const SizedBox(height: 18), action!],
          ],
        ),
      ),
    ),
  );
}

class FailureView extends StatelessWidget {
  const FailureView({super.key, required this.error, required this.onRetry});
  final Object error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    String message = L10n.t(context, 'requestFailed');
    String? support;
    if (error is ApiProblem) {
      final problem = error as ApiProblem;
      message = switch (problem.code) {
        'rate_limited' => L10n.t(context, 'rateLimited'),
        'service_unavailable' => L10n.t(context, 'serviceUnavailable'),
        'conflict' => L10n.t(context, 'conflictRefresh'),
        _ => problem.message.isEmpty ? message : problem.message,
      };
      support = problem.requestId;
    } else if (error is NetworkProblem) {
      message = L10n.t(context, 'offline');
    }
    return EmptyView(
      icon: Icons.cloud_off_rounded,
      title: message,
      message: support == null
          ? null
          : '${L10n.t(context, 'supportRequest')}: $support',
      action: FilledButton.icon(
        onPressed: onRetry,
        icon: const Icon(Icons.refresh),
        label: Text(L10n.t(context, 'retry')),
      ),
    );
  }
}

class SignInRequired extends StatelessWidget {
  const SignInRequired({super.key, required this.onSignIn});
  final VoidCallback onSignIn;
  @override
  Widget build(BuildContext context) => EmptyView(
    icon: Icons.lock_outline_rounded,
    title: L10n.t(context, 'signInRequired'),
    message: L10n.t(context, 'browseAsGuest'),
    action: FilledButton(
      onPressed: onSignIn,
      child: Text(L10n.t(context, 'signIn')),
    ),
  );
}

class MoneyText extends StatelessWidget {
  const MoneyText(this.money, {super.key, this.style});
  final Money money;
  final TextStyle? style;
  @override
  Widget build(BuildContext context) => Text(
    money.display,
    style:
        style ??
        Theme.of(context).textTheme.titleMedium
            ?.copyWith(fontWeight: FontWeight.w800),
  );
}

class PublicImage extends StatelessWidget {
  const PublicImage({
    super.key,
    required this.image,
    this.height = 190,
    this.fit = BoxFit.cover,
  });
  final ApiImage? image;
  final double height;
  final BoxFit fit;
  @override
  Widget build(BuildContext context) {
    if (image == null || image!.url.isEmpty) {
      return Container(
        height: height,
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        child: const Center(
          child: Icon(Icons.image_not_supported_outlined, size: 42),
        ),
      );
    }
    final resolved = AppConfig().resolveApplicationUrl(image!.url).toString();
    return Semantics(
      image: true,
      label: image!.alt ?? '',
      child: Image.network(
        resolved,
        height: height,
        width: double.infinity,
        fit: fit,
        errorBuilder: (_, _, _) => Container(
          height: height,
          color: Theme.of(context).colorScheme.surfaceContainerHighest,
          child: const Center(
            child: Icon(Icons.broken_image_outlined, size: 42),
          ),
        ),
        loadingBuilder: (context, child, progress) => progress == null
            ? child
            : SizedBox(
                height: height,
                child: const Center(child: CircularProgressIndicator()),
              ),
      ),
    );
  }
}

class ProtectedImage extends StatefulWidget {
  const ProtectedImage({
    super.key,
    required this.controller,
    required this.url,
    this.fit = BoxFit.contain,
  });
  final AppController controller;
  final String url;
  final BoxFit fit;
  @override
  State<ProtectedImage> createState() => _ProtectedImageState();
}

class _ProtectedImageState extends State<ProtectedImage> {
  Future<Uint8List>? _future;
  @override
  void initState() {
    super.initState();
    _future = widget.controller.api.protectedMedia(widget.url);
  }

  @override
  void didUpdateWidget(covariant ProtectedImage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.url != widget.url) {
      _future = widget.controller.api.protectedMedia(widget.url);
    }
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<Uint8List>(
    future: _future,
    builder: (context, snapshot) {
      if (snapshot.connectionState != ConnectionState.done) {
        return const Center(child: CircularProgressIndicator());
      }
      if (snapshot.hasError || snapshot.data == null) {
        return const Center(child: Icon(Icons.broken_image_outlined));
      }
      return Image.memory(
        snapshot.data!,
        fit: widget.fit,
        gaplessPlayback: true,
      );
    },
  );
}

Future<void> showProblem(BuildContext context, Object error) async {
  final message = error is ApiProblem
      ? error.message
      : L10n.t(context, 'requestFailed');
  if (!context.mounted) return;
  await showDialog<void>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text(L10n.t(context, 'requestFailed')),
      content: Text(message),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: Text(L10n.t(context, 'close')),
        ),
      ],
    ),
  );
}
