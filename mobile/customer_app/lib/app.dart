import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'core/app_controller.dart';
import 'core/l10n.dart';
import 'core/theme.dart';
import 'features/account/account_screen.dart';
import 'features/artwork/artwork_screen.dart';
import 'features/auth/login_screen.dart';
import 'features/cart/cart_screen.dart';
import 'features/discover/discover_screen.dart';
import 'features/notifications/notifications_screen.dart';
import 'features/purchases/purchases_screen.dart';
import 'features/studio/studio_screen.dart';
import 'ui/common.dart';

class FabinziCustomerApp extends StatefulWidget {
  const FabinziCustomerApp({super.key, this.controller});
  final AppController? controller;

  @override
  State<FabinziCustomerApp> createState() => _FabinziCustomerAppState();
}

class _FabinziCustomerAppState extends State<FabinziCustomerApp> {
  late final AppController controller = widget.controller ?? AppController();
  late final bool ownsController = widget.controller == null;

  @override
  void initState() {
    super.initState();
    controller.initialize();
  }

  @override
  void dispose() {
    if (ownsController) controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: controller,
    builder: (context, _) => MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'FABINZI',
      locale: controller.locale,
      supportedLocales: L10n.supportedLocales,
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      theme: FabinziTheme.light(),
      darkTheme: FabinziTheme.dark(),
      themeMode: controller.themeMode,
      home: _AppGateway(controller: controller),
    ),
  );
}

class _AppGateway extends StatelessWidget {
  const _AppGateway({required this.controller});
  final AppController controller;

  @override
  Widget build(BuildContext context) {
    if (controller.initializing ||
        (!controller.initialized && controller.initializationError == null)) {
      return const Scaffold(body: BusyView());
    }
    if (!controller.initialized && controller.initializationError != null) {
      return Scaffold(
        appBar: AppBar(title: const FabinziWordmark()),
        body: FailureView(
          error: controller.initializationError!,
          onRetry: controller.retryInitialize,
        ),
      );
    }
    return CustomerShell(controller: controller);
  }
}

class CustomerShell extends StatefulWidget {
  const CustomerShell({super.key, required this.controller});
  final AppController controller;

  @override
  State<CustomerShell> createState() => _CustomerShellState();
}

class _CustomerShellState extends State<CustomerShell> {
  int index = 0;

  Future<bool> ensureSignIn() async {
    if (widget.controller.isAuthenticated) return true;
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => LoginScreen(controller: widget.controller),
      ),
    );
    return widget.controller.isAuthenticated;
  }

  void openProtected(Widget Function() builder) async {
    if (await ensureSignIn() && mounted) {
      await Navigator.of(context)
          .push(MaterialPageRoute<void>(builder: (_) => builder()));
    }
  }

  @override
  Widget build(BuildContext context) {
    final tabs = <Widget>[
      DiscoverScreen(
        controller: widget.controller,
        requestSignIn: ensureSignIn,
      ),
      ArtworkScreen(controller: widget.controller),
      widget.controller.isAuthenticated
          ? StudioProjectsScreen(controller: widget.controller)
          : SignInRequired(onSignIn: ensureSignIn),
      widget.controller.isAuthenticated
          ? PurchasesScreen(controller: widget.controller)
          : SignInRequired(onSignIn: ensureSignIn),
      AccountScreen(controller: widget.controller, requestSignIn: ensureSignIn),
    ];
    return Scaffold(
      appBar: AppBar(
        title: const FabinziWordmark(compact: true),
        actions: [
          IconButton(
            tooltip: L10n.t(context, 'notifications'),
            onPressed: () => openProtected(
              () => NotificationsScreen(controller: widget.controller),
            ),
            icon: const Icon(Icons.notifications_none_rounded),
          ),
          IconButton(
            tooltip: L10n.t(context, 'cart'),
            onPressed: () =>
                openProtected(() => CartScreen(controller: widget.controller)),
            icon: const Icon(Icons.shopping_bag_outlined),
          ),
          const SizedBox(width: 4),
        ],
      ),
      body: IndexedStack(index: index, children: tabs),
      bottomNavigationBar: NavigationBar(
        selectedIndex: index,
        onDestinationSelected: (value) => setState(() => index = value),
        destinations: [
          NavigationDestination(
            icon: const Icon(Icons.explore_outlined),
            selectedIcon: const Icon(Icons.explore),
            label: L10n.t(context, 'discover'),
          ),
          NavigationDestination(
            icon: const Icon(Icons.palette_outlined),
            selectedIcon: const Icon(Icons.palette),
            label: L10n.t(context, 'artwork'),
          ),
          NavigationDestination(
            icon: const Icon(Icons.auto_fix_high_outlined),
            selectedIcon: const Icon(Icons.auto_fix_high),
            label: L10n.t(context, 'studio'),
          ),
          NavigationDestination(
            icon: const Icon(Icons.receipt_long_outlined),
            selectedIcon: const Icon(Icons.receipt_long),
            label: L10n.t(context, 'purchases'),
          ),
          NavigationDestination(
            icon: const Icon(Icons.person_outline),
            selectedIcon: const Icon(Icons.person),
            label: L10n.t(context, 'account'),
          ),
        ],
      ),
    );
  }
}
